# File: o-voxel/o_voxel/postprocess.py
# o-voxel/o_voxel/postprocess.py
import os
from typing import *
from tqdm import tqdm
import numpy as np
import torch
import cv2
from PIL import Image
import trimesh
import trimesh.visual
from flex_gemm.ops.grid_sample import grid_sample_3d
# nvdiffrast (NVIDIA Source Code License: research / evaluation use only) is optional:
# TRELLIS_UV_RASTERIZER=torch never imports it and bakes with uvraster.py instead.
dr = None
if os.environ.get('TRELLIS_UV_RASTERIZER', 'auto').strip().lower() != 'torch':
    try:
        import nvdiffrast.torch as dr
    except ImportError:
        dr = None
from .uvraster import rasterize_uv  # pure-PyTorch alternative (MIT), see uvraster.py
import cumesh


def within_repair_bounds(vertices, bounds, margin):
    if not vertices.numel():
        return False
    lower, upper = vertices.amin(dim=0), vertices.amax(dim=0)
    return bool(((lower >= bounds[0] - margin) & (upper <= bounds[1] + margin)).all())


def bake_master_material(positions, mask, vertices, faces, bvh, attr_volume, coords, aabb, voxel_size, grid_size,
                         texture_sampling='trilinear'):
    """Sample covered texels in batches and normalize over occupied material voxels."""
    channel_count = attr_volume.shape[1]
    occupied_volume = torch.cat([attr_volume, torch.ones_like(attr_volume[:, :1])], dim=1)
    batch_coords = torch.cat([torch.zeros_like(coords[:, :1]), coords], dim=-1)
    shape = torch.Size([1, channel_count + 1, *grid_size.tolist()])
    texels = mask.flatten().nonzero(as_tuple=True)[0]
    attrs = attr_volume.new_zeros((mask.numel(), channel_count))
    supported_mask = torch.zeros_like(mask).flatten()
    occupied_count = 0
    partial_count = 0
    for points, indices in zip(positions.split(1_000_000), texels.split(1_000_000), strict=True):
        if bvh is not None:
            _, face_id, weights = bvh.unsigned_distance(points, return_uvw=True)
            points = (vertices[faces[face_id.long()]] * weights.unsqueeze(-1)).sum(dim=1)
        grid = ((points - aabb[0]) / voxel_size).reshape(1, -1, 3)
        sampled = grid_sample_3d(occupied_volume, batch_coords, shape=shape, grid=grid, mode=texture_sampling)[0]
        support = sampled[:, -1]
        valid = support >= 1e-4
        valid_indices = indices[valid]
        attrs[valid_indices] = sampled[valid, :-1] / support[valid, None]
        supported_mask[valid_indices] = True
        occupied_count += len(valid_indices)
        partial_count += int((valid & (support < 0.999)).sum().item())
    if not occupied_count:
        raise ValueError('The decoded material volume has no coverage on the master mesh.')
    coverage = dict(rasterized_texels=len(texels), supported_texels=occupied_count,
                    partially_supported_texels=partial_count, inpainted_texels=len(texels) - occupied_count,
                    source='decoded sparse material volume', interpolation=f'occupancy-normalized {texture_sampling}')
    return attrs.view(*mask.shape, channel_count), supported_mask.view_as(mask), coverage


def to_glb(
    vertices: torch.Tensor,
    faces: torch.Tensor,
    attr_volume: torch.Tensor,
    coords: torch.Tensor,
    attr_layout: Dict[str, slice],
    aabb: Union[list, tuple, np.ndarray, torch.Tensor],
    voxel_size: Union[float, list, tuple, np.ndarray, torch.Tensor] = None,
    grid_size: Union[int, list, tuple, np.ndarray, torch.Tensor] = None,
    decimation_target: int = 1000000,
    texture_size: int = 2048,
    remesh: bool = False,
    repair_holes: bool = False,
    remesh_band: float = 1,
    remesh_project: float = 0.9,
    mesh_cluster_threshold_cone_half_angle_rad=np.radians(90.0),
    mesh_cluster_refine_iterations=0,
    mesh_cluster_global_iterations=1,
    mesh_cluster_smooth_strength=1,
    verbose: bool = False,
    use_tqdm: bool = False,
    adaptive_mesh: Optional[Callable] = None,
    repair_surface: bool = False,
    remesh_resolution: int = 512,
    texture_sampling: str = 'trilinear',
    reconstructed_mesh: Optional[Tuple[torch.Tensor, torch.Tensor]] = None,
    master_finishing: bool = False,
    preserve_decoded_mesh: bool = False,
):
    """
    Convert an extracted mesh to a GLB file.
    Performs cleaning, optional remeshing, UV unwrapping, and texture baking from a volume.
    
    Args:
        vertices: (N, 3) tensor of vertex positions
        faces: (M, 3) tensor of vertex indices
        attr_volume: (L, C) features of a sprase tensor for attribute interpolation
        coords: (L, 3) tensor of coordinates for each voxel
        attr_layout: dictionary of slice objects for each attribute
        aabb: (2, 3) tensor of minimum and maximum coordinates of the volume
        voxel_size: (3,) tensor of size of each voxel
        grid_size: (3,) tensor of number of voxels in each dimension
        decimation_target: target number of vertices for mesh simplification
        texture_size: size of the texture for baking
        remesh: whether to perform remeshing
        repair_holes: fill small holes before BVH construction (enabled in the D profile)
        repair_surface: check for outliers in the opt-in surface reconstruction
        remesh_band: size of the remeshing band
        remesh_project: projection factor for remeshing
        remesh_resolution: explicit DC grid ceiling (512, 768 or 1024), not the generation grid
        texture_sampling: interpolation in the material voxel volume, after nearest-surface projection
        reconstructed_mesh: optional replacement geometry in decoded coordinates; source vertices still donate the material
        master_finishing: bake material from occupied voxels using bounded-size texel batches
        preserve_decoded_mesh: unwrap and bake the original decoded triangles without geometry finishing
        mesh_cluster_threshold_cone_half_angle_rad: threshold for cone-based clustering in uv unwrapping
        mesh_cluster_refine_iterations: number of iterations for refining clusters in uv unwrapping
        mesh_cluster_global_iterations: number of global iterations for clustering in uv unwrapping
        mesh_cluster_smooth_strength: strength of smoothing for clustering in uv unwrapping
        verbose: whether to print verbose messages
        use_tqdm: whether to use tqdm to display progress bar
    """
    if preserve_decoded_mesh and (remesh or repair_holes or repair_surface or master_finishing
                                  or reconstructed_mesh is not None or adaptive_mesh is not None):
        raise ValueError('Exporting decoded geometry cannot be combined with mesh finishing.')
    if repair_surface and not remesh:
        raise ValueError('Surface repair requires reconstruction.')
    if reconstructed_mesh is not None and (remesh or repair_holes or adaptive_mesh is not None):
        raise ValueError('External reconstruction requires its own finishing recipe.')
    if type(remesh_resolution) is not int or remesh_resolution not in (512, 768, 1024):
        raise ValueError('Reconstruction grid ceiling must be 512, 768 or 1024.')
    if texture_sampling not in ('trilinear', 'nearest'):
        raise ValueError('Material voxel interpolation must be trilinear or nearest.')
    input_triangles = len(faces)
    dc_resolution = None
    reconstructed_triangles = None
    # --- Input Normalization (AABB, Voxel Size, Grid Size) ---
    if isinstance(aabb, (list, tuple)):
        aabb = np.array(aabb)
    if isinstance(aabb, np.ndarray):
        aabb = torch.tensor(aabb, dtype=torch.float32, device='cuda')
    assert isinstance(aabb, torch.Tensor), f"aabb must be a list, tuple, np.ndarray, or torch.Tensor, but got {type(aabb)}"
    assert aabb.dim() == 2, f"aabb must be a 2D tensor, but got {aabb.shape}"
    assert aabb.size(0) == 2, f"aabb must have 2 rows, but got {aabb.size(0)}"
    assert aabb.size(1) == 3, f"aabb must have 3 columns, but got {aabb.size(1)}"

    # Calculate grid dimensions based on AABB and voxel size
    if voxel_size is not None:
        if isinstance(voxel_size, float):
            voxel_size = [voxel_size, voxel_size, voxel_size]
        if isinstance(voxel_size, (list, tuple)):
            voxel_size = np.array(voxel_size)
        if isinstance(voxel_size, np.ndarray):
            voxel_size = torch.tensor(voxel_size, dtype=torch.float32, device='cuda')
        grid_size = ((aabb[1] - aabb[0]) / voxel_size).round().int()
    else:
        assert grid_size is not None, "Either voxel_size or grid_size must be provided"
        if isinstance(grid_size, int):
            grid_size = [grid_size, grid_size, grid_size]
        if isinstance(grid_size, (list, tuple)):
            grid_size = np.array(grid_size)
        if isinstance(grid_size, np.ndarray):
            grid_size = torch.tensor(grid_size, dtype=torch.int32, device=coords.device)
        voxel_size = (aabb[1] - aabb[0]) / grid_size
    
    # Assertions for dimensions
    assert isinstance(voxel_size, torch.Tensor)
    assert voxel_size.dim() == 1 and voxel_size.size(0) == 3
    assert isinstance(grid_size, torch.Tensor)
    assert grid_size.dim() == 1 and grid_size.size(0) == 3
    
    # CPU-offload attr_volume and coords — only needed at the final texture-baking step
    attr_volume_cpu = attr_volume.cpu()
    coords_cpu = coords.cpu()
    del attr_volume, coords
    torch.cuda.empty_cache()
    
    if use_tqdm:
        pbar = tqdm(total=6, desc="Extracting GLB")
    if verbose:
        print(f"Original mesh: {vertices.shape[0]} vertices, {faces.shape[0]} faces")

    # Move data to GPU
    vertices = vertices.cuda()
    faces = faces.cuda()
    raw_material_surface = (vertices.cpu(), faces.cpu()) if master_finishing and repair_holes else None
    repair_bounds = (vertices.amin(dim=0), vertices.amax(dim=0)) if repair_surface else None
    repair_margin = 4 * voxel_size
    initial_fill_used = repair_holes
    
    # Initialize CUDA mesh handler
    mesh = cumesh.CuMesh()
    mesh.init(vertices, faces)
    
    # --- Initial Mesh Cleaning ---
    if repair_holes:
        mesh.fill_holes(max_hole_perimeter=0.03)
        if repair_surface and not within_repair_bounds(mesh.read()[0], repair_bounds, repair_margin):
            # A poorly conditioned loop can introduce a spike and rescale the whole model.
            initial_fill_used = False
            del mesh
            mesh = cumesh.CuMesh()
            mesh.init(vertices, faces)
            if verbose:
                print('Skipped initial hole fill because it exceeded the source bounds.', flush=True)
    if verbose:
        print(f"Initial mesh: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
    vertices, faces = mesh.read()
    cleaned_source_triangles = len(faces)
    if use_tqdm:
        pbar.update(1)
        
    # The raw UV surface already matches the decoded material coordinates.
    bvh = None
    if not preserve_decoded_mesh:
        if use_tqdm:
            pbar.set_description("Building BVH")
        if verbose:
            print("Building BVH for current mesh...", end='', flush=True)
        bvh = cumesh.cuBVH(vertices, faces)
        if verbose:
            print("Done")
    _mesh_offloaded = False
    if use_tqdm:
        pbar.update(1)
        
    if use_tqdm:
        pbar.set_description("Cleaning mesh")
    if verbose and not preserve_decoded_mesh:
        print("Cleaning mesh...")
    
    # DIAGNOSTIC: What's on GPU right now?
    if os.environ.get('SPARSE_DEBUG') == '1':
        print(f"[DIAG] vertices: {vertices.shape}, faces: {faces.shape}, device={vertices.device}")
        print(f"[DIAG] VRAM allocated: {torch.cuda.memory_allocated()/(1024**2):.0f}MB, reserved: {torch.cuda.memory_reserved()/(1024**2):.0f}MB")
    
    # --- Branch 1: Standard Pipeline (Simplification & Cleaning) ---
    adaptive_report = None
    if adaptive_mesh is not None and not remesh:
        # Keep the original BVH for reprojection and choose the output before UV baking.
        del mesh
        mesh, adaptive_report = adaptive_mesh(
            vertices, faces, bvh, decimation_target, float(voxel_size.min()), verbose,
        )
        adaptive_report['reference'] = 'input surface after initial cleanup'
    elif not preserve_decoded_mesh and not remesh and reconstructed_mesh is None:
        # Step 1: Aggressive simplification (3x target)
        mesh.simplify(decimation_target * 3, verbose=verbose)
        if verbose:
            print(f"After inital simplification: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
        
        # Step 2: Clean up topology (duplicates, non-manifolds, isolated parts)
        mesh.remove_duplicate_faces()
        mesh.repair_non_manifold_edges()
        mesh.remove_small_connected_components(1e-5)
        if verbose:
            print(f"After initial cleanup: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
            
        # Step 3: Final simplification to target count
        mesh.simplify(decimation_target, verbose=verbose)
        if verbose:
            print(f"After final simplification: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
        
        # Step 4: Final Cleanup loop
        mesh.remove_duplicate_faces()
        mesh.repair_non_manifold_edges()
        mesh.remove_small_connected_components(1e-5)
        if verbose:
            print(f"After final cleanup: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
            
        # Step 5: Unify face orientations
        mesh.unify_face_orientations()
    
    # --- Branch 2: Remeshing Pipeline ---
    elif not preserve_decoded_mesh:
        # Free CuMesh internal buffers before the heavy remesh allocation —
        # vertices/faces are still held separately for BVH texture baking later
        del mesh
        torch.cuda.empty_cache()
        if reconstructed_mesh is None:
            center = aabb.mean(dim=0)
            scale = (aabb[1] - aabb[0]).max().item()
            resolution = grid_size.max().item()

            # This changes the geometry grid independently of the material volume.
            dc_resolution = min(int(resolution), remesh_resolution)
            if verbose:
                print(f'Reconstruction grid: {dc_resolution} (requested ceiling {remesh_resolution}, '
                      f'generated grid {int(resolution)})', flush=True)
            remesh_verts, remesh_faces = cumesh.remeshing.remesh_narrow_band_dc(
                vertices, faces, center=center,
                scale=(dc_resolution + 3 * remesh_band) / dc_resolution * scale,
                resolution=dc_resolution, band=remesh_band, project_back=remesh_project,
                verbose=verbose, bvh=bvh,
            )
        else:
            remesh_verts, remesh_faces = (array.cuda() for array in reconstructed_mesh)
        # Offload original mesh to CPU and free BVH — not needed until texture baking.
        vertices_cpu, faces_cpu = raw_material_surface if raw_material_surface is not None else (vertices.cpu(), faces.cpu())
        del raw_material_surface
        del vertices, faces, bvh
        torch.cuda.empty_cache()
        _mesh_offloaded = True

        mesh = cumesh.CuMesh()
        mesh.init(remesh_verts, remesh_faces)
        reconstructed_triangles = len(remesh_faces)
        del remesh_verts, remesh_faces

        if verbose:
            print(f"After remeshing: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
        
        if adaptive_mesh is None:
            # A master already trimmed in Blender keeps its indexed connectivity.
            if not (master_finishing and reconstructed_mesh is not None):
                if not master_finishing or mesh.num_faces > decimation_target:
                    mesh.simplify(decimation_target, verbose=verbose)
                if verbose:
                    print(f"After simplifying: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
                mesh.remove_duplicate_faces()
                mesh.repair_non_manifold_edges()
            mesh.remove_small_connected_components(1e-5)
            mesh.unify_face_orientations()
        else:
            rebuilt_vertices, rebuilt_faces = mesh.read()
            del mesh
            rebuilt_bvh = cumesh.cuBVH(rebuilt_vertices, rebuilt_faces)
            mesh, adaptive_report = adaptive_mesh(
                rebuilt_vertices, rebuilt_faces, rebuilt_bvh, decimation_target, float(voxel_size.min()), verbose,
            )
            adaptive_report['reference'] = 'reconstructed surface'
            del rebuilt_vertices, rebuilt_faces, rebuilt_bvh
        if verbose:
            print(f"After cleanup: {mesh.num_vertices} vertices, {mesh.num_faces} faces")
    
    if use_tqdm:
        pbar.update(1)
    if verbose and not preserve_decoded_mesh:
        print("Done")
        
    
    # --- UV Parameterization ---
    if use_tqdm:
        pbar.set_description("Parameterizing new mesh")
    if verbose:
        print("Parameterizing new mesh...")
    
    # Remove UV-unsafe degenerate triangles before xatlas computes normals.
    verts_tmp, faces_tmp = mesh.read()
    if repair_surface:
        # The reconstruction grid can be coarser than the decoded voxel grid.
        rebuilt_margin = 4 * torch.maximum(voxel_size, (aabb[1] - aabb[0]) / dc_resolution)
        if not within_repair_bounds(verts_tmp, repair_bounds, rebuilt_margin):
            raise ValueError('Surface repair exceeded the master bounds. Retry without Repair holes.')
    v0 = verts_tmp[faces_tmp[:, 0]]
    v1 = verts_tmp[faces_tmp[:, 1]]
    v2 = verts_tmp[faces_tmp[:, 2]]
    face_areas = torch.cross(v1 - v0, v2 - v0, dim=1).norm(dim=1)
    degenerate = face_areas < 1e-10
    if degenerate.any():
        faces_tmp = faces_tmp[~degenerate]
        mesh = cumesh.CuMesh()
        mesh.init(verts_tmp, faces_tmp)
        if verbose:
            print(f"Removed {degenerate.sum().item()} degenerate faces")
    master_diagnostics = None
    if master_finishing:
        from master_mesh import master_topology
        master_diagnostics = master_topology(verts_tmp.cpu().numpy(), faces_tmp.cpu().numpy())
    del verts_tmp, faces_tmp, v0, v1, v2, face_areas, degenerate
    
    out_vertices, out_faces, out_uvs, out_vmaps = mesh.uv_unwrap(
        compute_charts_kwargs={
            "threshold_cone_half_angle_rad": mesh_cluster_threshold_cone_half_angle_rad,
            "refine_iterations": mesh_cluster_refine_iterations,
            "global_iterations": mesh_cluster_global_iterations,
            "smooth_strength": mesh_cluster_smooth_strength,
        },
        return_vmaps=True,
        verbose=verbose,
    )
    if preserve_decoded_mesh and (not len(out_faces) or len(out_faces) != mesh.num_faces):
        raise ValueError('UV unwrapping did not preserve the decoded triangles.')
    uv_degenerate_triangles = input_triangles - len(out_faces) if preserve_decoded_mesh else None
    out_vertices = out_vertices.cuda()
    out_faces = out_faces.cuda()
    out_uvs = out_uvs.cuda()
    out_vmaps = out_vmaps.cuda()
    mesh.compute_vertex_normals()
    out_normals = mesh.read_vertex_normals()[out_vmaps]
    # Free CuMesh internal C++ CUDA buffers — no longer needed after normals
    del mesh
    torch.cuda.empty_cache()
    
    if use_tqdm:
        pbar.update(1)
    if verbose:
        print("Done")
    
    # --- Texture Baking (Attribute Sampling) ---
    if not torch.isfinite(out_vertices).all() or not torch.isfinite(out_uvs).all():
        raise ValueError('The mesh or UVs contain non-finite values. Export stopped; try different finishing settings.')
    if use_tqdm:
        pbar.set_description("Sampling attributes")
    if verbose:
        print("Sampling attributes...", end='', flush=True)
        
    # UV rasteriser. nvdiffrast is licensed for research / evaluation only; uvraster.py is a
    # pure-PyTorch (MIT) replacement with the same texel conventions, so the output can be
    # used commercially. TRELLIS_UV_RASTERIZER: 'auto' (default - nvdiffrast when it is
    # installed, else uvraster), 'torch', or 'nvdiffrast'. Both paths yield the coverage
    # mask and the 3D surface point under every covered texel; the rest of the bake is shared.
    _rasterizer = os.environ.get('TRELLIS_UV_RASTERIZER', 'auto').strip().lower()
    if _rasterizer == 'nvdiffrast' and dr is None:
        raise ImportError("TRELLIS_UV_RASTERIZER=nvdiffrast, but nvdiffrast is not installed")
    if _rasterizer == 'torch' or dr is None:
        mask, tri_id, bary = rasterize_uv(out_uvs, out_faces, texture_size)
        if not mask.any():
            raise ValueError('No UV texels are covered. Export stopped to avoid creating an empty texture.')
        tri_verts = out_vertices[out_faces[tri_id[mask]]]              # (N_texels, 3, 3)
        valid_pos = (tri_verts * bary[mask].unsqueeze(-1)).sum(dim=1)  # (N_texels, 3)
        del tri_id, bary, tri_verts
        torch.cuda.empty_cache()
    else:
        # Setup differentiable rasterizer context
        ctx = dr.RasterizeCudaContext()
        # Prepare UV coordinates for rasterization (rendering in UV space)
        uvs_rast = torch.cat([out_uvs * 2 - 1, torch.zeros_like(out_uvs[:, :1]), torch.ones_like(out_uvs[:, :1])], dim=-1).unsqueeze(0)
        rast = torch.zeros((1, texture_size, texture_size, 4), device='cuda', dtype=torch.float32)
    
        # Rasterize in chunks to save memory
        for i in range(0, out_faces.shape[0], 100000):
            rast_chunk, _ = dr.rasterize(
                ctx, uvs_rast, out_faces[i:i+100000],
                resolution=[texture_size, texture_size],
            )
            mask_chunk = rast_chunk[..., 3:4] > 0
            rast_chunk[..., 3:4] += i # Store face ID in alpha channel
            rast = torch.where(mask_chunk, rast_chunk, rast)
    
        # Mask of valid pixels in texture
        mask = rast[0, ..., 3] > 0
    
        # Interpolate 3D positions in UV space (finding 3D coord for every texel)
        pos = dr.interpolate(out_vertices.unsqueeze(0), rast, out_faces)[0][0]
        valid_pos = pos[mask]
    
        # Free rasterization intermediates — only mask and valid_pos needed from here
        del rast, pos, uvs_rast, ctx
        torch.cuda.empty_cache()
    
    # Map these positions back to the *original* high-res mesh to get accurate attributes
    # This corrects geometric errors introduced by simplification/remeshing
    if _mesh_offloaded:
        vertices = vertices_cpu.cuda()
        faces = faces_cpu.cuda()
        del vertices_cpu, faces_cpu
        if verbose:
            print("Building BVH for texture baking...", end='', flush=True)
        bvh = cumesh.cuBVH(vertices, faces)
        if verbose:
            print("Done")

    material_coverage = None
    if master_finishing or preserve_decoded_mesh:
        attrs, mask, material_coverage = bake_master_material(
            valid_pos, mask, vertices, faces, bvh, attr_volume_cpu.cuda(), coords_cpu.cuda(), aabb, voxel_size, grid_size,
            texture_sampling if preserve_decoded_mesh else 'trilinear')
        del vertices, faces, bvh
    else:
        _, face_id, uvw = bvh.unsigned_distance(valid_pos, return_uvw=True)
        orig_tri_verts = vertices[faces[face_id.long()]]
        valid_pos = (orig_tri_verts * uvw.unsqueeze(-1)).sum(dim=1)
        del vertices, faces, bvh, orig_tri_verts, face_id, uvw
        torch.cuda.empty_cache()

        # Material interpolation is independent of nearest-surface BVH projection.
        attr_volume = attr_volume_cpu.cuda()
        coords = coords_cpu.cuda()
        attrs = torch.zeros(texture_size, texture_size, attr_volume.shape[1], device='cuda', dtype=attr_volume.dtype)
        attrs[mask] = grid_sample_3d(
            attr_volume,
            torch.cat([torch.zeros_like(coords[:, :1]), coords], dim=-1),
            shape=torch.Size([1, attr_volume.shape[1], *grid_size.tolist()]),
            grid=((valid_pos - aabb[0]) / voxel_size).reshape(1, -1, 3),
            mode=texture_sampling,
        )
        del attr_volume, coords
    del attr_volume_cpu, coords_cpu, valid_pos
    torch.cuda.empty_cache()

    if use_tqdm:
        pbar.update(1)
    if verbose:
        print("Done")
    
    # --- Texture Post-Processing & Material Construction ---
    if use_tqdm:
        pbar.set_description("Finalizing mesh")
    if verbose:
        print("Finalizing mesh...", end='', flush=True)
    
    mask = mask.cpu().numpy()
    
    # Extract channels based on layout (BaseColor, Metallic, Roughness, Alpha)
    attrs_cpu = attrs.contiguous().cpu().numpy()
    base_color = np.clip(attrs_cpu[..., attr_layout['base_color']] * 255, 0, 255).astype(np.uint8)
    metallic = np.clip(attrs_cpu[..., attr_layout['metallic']] * 255, 0, 255).astype(np.uint8)
    roughness = np.clip(attrs_cpu[..., attr_layout['roughness']] * 255, 0, 255).astype(np.uint8)
    alpha = np.clip(attrs_cpu[..., attr_layout['alpha']] * 255, 0, 255).astype(np.uint8)
    alpha_mode = 'OPAQUE'
    
    # Inpainting: fill gaps (dilation) to prevent black seams at UV boundaries
    mask_inv = (~mask).astype(np.uint8)
    base_color = cv2.inpaint(base_color, mask_inv, 3, cv2.INPAINT_TELEA)
    metallic = cv2.inpaint(metallic, mask_inv, 1, cv2.INPAINT_TELEA)[..., None]
    roughness = cv2.inpaint(roughness, mask_inv, 1, cv2.INPAINT_TELEA)[..., None]
    alpha = cv2.inpaint(alpha, mask_inv, 1, cv2.INPAINT_TELEA)[..., None]
    
    # Create PBR material
    # Standard PBR packs Metallic and Roughness into Blue and Green channels
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=Image.fromarray(np.concatenate([base_color, alpha], axis=-1)),
        baseColorFactor=np.array([255, 255, 255, 255], dtype=np.uint8),
        metallicRoughnessTexture=Image.fromarray(np.concatenate([np.zeros_like(metallic), roughness, metallic], axis=-1)),
        metallicFactor=1.0,
        roughnessFactor=1.0,
        alphaMode=alpha_mode,
        doubleSided=not remesh and reconstructed_mesh is None,
    )
    
    # --- Coordinate System Conversion & Final Object ---
    vertices_np = out_vertices.cpu().numpy()
    faces_np = out_faces.cpu().numpy()
    uvs_np = out_uvs.cpu().numpy()
    normals_np = out_normals.cpu().numpy()
    
    # Swap Y and Z axes, invert Y (common conversion for GLB compatibility)
    vertices_np[:, 1], vertices_np[:, 2] = vertices_np[:, 2], -vertices_np[:, 1]
    normals_np[:, 1], normals_np[:, 2] = normals_np[:, 2], -normals_np[:, 1]
    uvs_np[:, 1] = 1 - uvs_np[:, 1] # Flip UV V-coordinate
    
    textured_mesh = trimesh.Trimesh(
        vertices=vertices_np,
        faces=faces_np,
        vertex_normals=normals_np,
        process=False,
        visual=trimesh.visual.TextureVisuals(uv=uvs_np, material=material)
    )
    method = 'none' if preserve_decoded_mesh else 'wtivo' if reconstructed_mesh is not None else 'remesh' if remesh else 'direct'
    textured_mesh.metadata['finishing'] = dict(
        method=method,
        input_triangles=input_triangles,
        cleaned_source_triangles=cleaned_source_triangles,
        generated_grid_resolution=int(grid_size.max()),
        remesh_resolution_requested=remesh_resolution if remesh else None,
        remesh_resolution_actual=dc_resolution, reconstructed_triangles=reconstructed_triangles,
        output_triangles=len(faces_np), texture_size=texture_size,
        texture_sampling=texture_sampling,
        texture_projection='decoded surface without reprojection' if preserve_decoded_mesh else 'nearest point on source surface',
        initial_fill_used=initial_fill_used,
    )
    if uv_degenerate_triangles is not None:
        textured_mesh.metadata['finishing']['uv_degenerate_triangles_removed'] = uv_degenerate_triangles
    if material_coverage is not None:
        textured_mesh.metadata['finishing']['material_coverage'] = material_coverage
    if master_diagnostics is not None:
        textured_mesh.metadata['finishing']['topology_before_uv'] = master_diagnostics
    if adaptive_report is not None:
        textured_mesh.metadata['adaptive_finishing'] = adaptive_report
    if repair_surface:
        textured_mesh.metadata['surface_repair'] = dict(
            grid_resolution=dc_resolution, projection=float(remesh_project), initial_fill_used=initial_fill_used,
        )
    
    if use_tqdm:
        pbar.update(1)
        pbar.close()
    if verbose:
        print("Done")
    
    return textured_mesh
