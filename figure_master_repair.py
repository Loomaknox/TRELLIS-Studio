"""Optional local QuadDC and MeshLib components for Figure Master."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from time import perf_counter
import sys


QUAD_REVISION = 'd10e54c30ddd03d11472c1431693f985501c7966'
MESH_LIB_VERSION = '3.2.0.29'
FLOATER_FACE_RATIO = 0.005


def availability(root):
    folder = Path(root) / 'runtime' / 'figure-master'
    if not (folder / 'quad_dc.py').is_file() or not (folder / 'deps' / 'meshlib').is_dir():
        return dict(available=False, reason='The optional local QuadDC and MeshLib runtime is not installed.')
    return dict(available=True, reason='', quad_revision=QUAD_REVISION, meshlib_version=MESH_LIB_VERSION)


def _load_quad(folder):
    spec = spec_from_file_location('_figure_master_quad_dc', folder / 'quad_dc.py')
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reconstruct_mesh_dc_quad


def _remove_floaters(vertices, faces):
    import numpy as np
    import pymeshlab

    mesh_set = pymeshlab.MeshSet()
    mesh_set.add_mesh(pymeshlab.Mesh(vertex_matrix=vertices, face_matrix=faces), 'QuadDC')
    mesh_set.apply_filter('compute_selection_by_small_disconnected_components_per_face',
                          nbfaceratio=FLOATER_FACE_RATIO)
    mesh_set.apply_filter('compute_selection_transfer_face_to_vertex', inclusive=False)
    mesh_set.apply_filter('meshing_remove_selected_vertices_and_faces')
    mesh = mesh_set.current_mesh()
    return (np.ascontiguousarray(mesh.vertex_matrix(), dtype=np.float32),
            np.ascontiguousarray(mesh.face_matrix(), dtype=np.int32))


def _close_holes(folder, vertices, faces):
    import numpy as np

    dependencies = str(folder / 'deps')
    sys.path.insert(0, dependencies)
    try:
        from meshlib import mrmeshnumpy, mrmeshpy
    finally:
        sys.path.remove(dependencies)

    mesh = mrmeshnumpy.meshFromFacesVerts(faces, vertices)
    counts = []
    for _ in range(3):
        holes = mesh.topology.findHoleRepresentiveEdges()
        counts.append(len(holes))
        if not len(holes):
            break
        for edge in holes:
            params = mrmeshpy.FillHoleParams()
            params.metric = mrmeshpy.getUniversalMetric(mesh)
            mrmeshpy.fillHole(mesh, edge, params)
    if counts[-1]:
        counts.append(len(mesh.topology.findHoleRepresentiveEdges()))
    return (np.ascontiguousarray(mrmeshnumpy.getNumpyVerts(mesh), dtype=np.float32),
            np.ascontiguousarray(mrmeshnumpy.getNumpyFaces(mesh.topology), dtype=np.int32), counts)


def _simplify(vertices, faces, target):
    import cumesh

    mesh = cumesh.CuMesh()
    mesh.init(vertices, faces)
    if mesh.num_faces > target:
        mesh.simplify(target, verbose=True)
    return tuple(array.cpu().numpy() for array in mesh.read())


def _fit_budget(folder, vertices, faces, target, repair_holes):
    candidate_budget = target
    attempts = []
    for _ in range(4):
        compact_vertices, compact_faces = _simplify(vertices, faces, candidate_budget)
        simplified_faces = len(compact_faces)
        holes = []
        if repair_holes:
            compact_vertices, compact_faces, holes = _close_holes(folder, compact_vertices, compact_faces)
        attempts.append(dict(simplification_target=candidate_budget, simplified_triangles=simplified_faces,
                             rebuilt_triangles=len(compact_faces), hole_boundaries_by_pass=holes))
        print(f'Figure Master budget {candidate_budget:,}: {simplified_faces:,} simplified, '
              f'{len(compact_faces):,} after cleanup.', flush=True)
        if len(compact_faces) <= target:
            return compact_vertices, compact_faces, attempts
        # Reduce the original reconstruction again rather than cutting newly filled holes.
        overshoot = len(compact_faces) - target
        lower_budget = min(candidate_budget - overshoot - max(1, target // 100),
                           int(candidate_budget * target / len(compact_faces) * .95))
        if candidate_budget == 4:
            break
        candidate_budget = max(4, lower_budget)
    raise ValueError('MeshLib closure exceeded the Figure Master triangle ceiling. Increase the target or disable hole filling.')


def reconstruct(root, vertices, faces, *, resolution, band, project, target, repair_holes, progress):
    import cumesh
    import numpy as np
    import torch

    folder = Path(root) / 'runtime' / 'figure-master'
    started = perf_counter()
    faces = faces.to(dtype=torch.int32).contiguous()
    vertices = vertices.contiguous()
    lower = vertices.amin(dim=0).cpu().numpy()
    upper = vertices.amax(dim=0).cpu().numpy()
    progress(f'Reconstructing the surface with QuadDC {resolution}', 84)
    source_bvh = cumesh.cuBVH(vertices, faces) if project else None
    rebuilt, triangles = _load_quad(folder)(vertices, faces, resolution=resolution, band=band,
                                           verbose=True, bvh=source_bvh, remove_inner_faces=True)
    if not len(triangles):
        raise ValueError('QuadDC could not reconstruct a surface from these generated faces.')
    if source_bvh is not None:
        for chunk in rebuilt.split(524_288):
            _, face_indices, weights = source_bvh.unsigned_distance(chunk, return_uvw=True)
            closest = (vertices[faces[face_indices.long()]] * weights.unsqueeze(-1)).sum(dim=1)
            chunk.lerp_(closest, project)
    del source_bvh
    reconstructed_triangles = len(triangles)
    screened, screened_faces = _remove_floaters(rebuilt.cpu().numpy(), triangles.cpu().numpy())
    del rebuilt, triangles
    torch.cuda.empty_cache()
    if not len(screened_faces):
        raise ValueError('QuadDC produced no surface after removing disconnected fragments.')
    progress('Reducing the QuadDC surface and closing holes with MeshLib' if repair_holes
             else 'Reducing the QuadDC surface', 85)
    screened_triangles = len(screened_faces)
    device = vertices.device
    final_vertices, final_faces, attempts = _fit_budget(folder, torch.from_numpy(screened).to(device),
                                                        torch.from_numpy(screened_faces).to(device), target, repair_holes)
    del screened, screened_faces
    torch.cuda.empty_cache()
    margin = max(float((upper - lower).max()) * (band + 5) / resolution, .01)
    if (len(final_faces) < 4 or not np.isfinite(final_vertices).all() or final_faces.min() < 0
            or final_faces.max() >= len(final_vertices) or np.any(final_vertices < lower - margin)
            or np.any(final_vertices > upper + margin)):
        raise ValueError('Figure Master could not verify the bounds or faces of the repaired surface.')
    return (torch.from_numpy(final_vertices), torch.from_numpy(final_faces)), dict(
        method='quad_dc_meshlib' if repair_holes else 'quad_dc', quad_revision=QUAD_REVISION,
        meshlib_version=MESH_LIB_VERSION if repair_holes else None, grid_resolution=resolution,
        band=band, projection=project, floater_face_ratio=FLOATER_FACE_RATIO,
        quad_triangles=reconstructed_triangles, screened_triangles=screened_triangles,
        triangle_target=target, output_triangles=len(final_faces), attempts=attempts,
        seconds=round(perf_counter() - started, 2),
    )
