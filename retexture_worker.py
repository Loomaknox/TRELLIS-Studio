"""Generate and bake TRELLIS.2 materials on fixed geometry in a local CUDA process."""
import copy
import gc
import io
import json
import os
from pathlib import Path
import struct
import sys
from time import perf_counter
import traceback


ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / 'engine'), str(ROOT / 'engine' / 'o-voxel')]

from retexture_runtime import MATERIAL_RESOLUTION, checked_recipe, file_sha, pipeline_config


def source_mesh(path):
    import numpy as np
    from glb_data import accessor, read

    document, binary = read(path)
    meshes = document.get('meshes', [])
    if len(meshes) != 1 or len(meshes[0].get('primitives', [])) != 1:
        raise ValueError('Material refinement requires one triangle mesh with one material.')
    primitive = meshes[0]['primitives'][0]
    attributes = primitive.get('attributes', {})
    if (primitive.get('mode', 4) != 4 or 'targets' in primitive or document.get('skins')
            or 'indices' not in primitive or not {'POSITION', 'TEXCOORD_0'} <= attributes.keys()):
        raise ValueError('Material refinement requires a static indexed mesh with existing UVs.')
    positions = accessor(document, binary, attributes['POSITION'])
    uv = accessor(document, binary, attributes['TEXCOORD_0'])
    indices = accessor(document, binary, primitive['indices'])
    if (len(positions) == 0 or len(indices) == 0 or indices.dtype.kind not in ('i', 'u')
            or indices.size % 3 or indices.min() < 0
            or indices.max() >= len(positions) or positions.shape != (len(uv), 3) or uv.shape[1] != 2
            or not np.isfinite(positions).all() or not np.isfinite(uv).all() or uv.min() < 0 or uv.max() > 1):
        raise ValueError('Invalid geometry or UVs for material refinement.')
    extent = np.ptp(positions, axis=0).max()
    if extent <= 0:
        raise ValueError('The material refinement mesh has empty bounds.')
    center = (positions.min(0) + positions.max(0)) * .5
    # Convert the exported Y-up mesh to the engine's normalized Z-up grid.
    normalized = np.asarray((positions - center) * (.99999 / extent), dtype=np.float32)
    normalized = normalized[:, [0, 2, 1]] * np.array([1, -1, 1], np.float32)
    return document, binary, normalized, indices.reshape(-1, 3), uv


class GeometryCache(dict):
    def clear(self):
        # The encoder and decoder need the same inverse maps at every level.
        for level, entries in self.items():
            self[level] = {key: value for key, value in entries.items() if key.startswith('channel2spatial_')}


def move_inverse_maps(cache, device):
    for entries in cache.values():
        for key in entries:
            if key.startswith('channel2spatial_'):
                entries[key] = tuple(tensor.to(device) for tensor in entries[key])


def infer(config, reference, normalized, faces, recipe):
    import numpy as np
    import torch
    import torch.nn.functional as functional
    from PIL import Image
    from o_voxel.convert import mesh_to_flexible_dual_grid
    from trellis2.modules.sparse import SparseTensor
    from trellis2.pipelines import Trellis2ImageTo3DPipeline

    resolution = MATERIAL_RESOLUTION
    # Preserve the inverse maps if a residual operation merges two sparse caches.
    merge_cache = SparseTensor._SparseTensor__merge_sparse_cache
    SparseTensor._SparseTensor__merge_sparse_cache = lambda tensor, other: GeometryCache(merge_cache(tensor, other))
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained(str(config))
    pipeline.cuda()
    with Image.open(reference) as saved:
        prepared = saved.convert('RGB')
    pipeline.image_cond_model.to(pipeline.device)
    conditioning = pipeline._cast_cond(pipeline.get_cond([prepared], resolution))
    pipeline.image_cond_model.cpu()
    torch.cuda.empty_cache()

    print('Encoding the refined surface for TRELLIS.2 material generation', flush=True)
    coords, dual, intersected = mesh_to_flexible_dual_grid(
        torch.from_numpy(normalized), torch.from_numpy(faces.astype(np.int64)),
        grid_size=resolution, aabb=[[-.5, -.5, -.5], [.5, .5, .5]],
        face_weight=1., boundary_weight=.2, regularization_weight=1e-2)
    values = torch.cat((dual * resolution - coords - .5, intersected.float() - .5), dim=1)
    coords_with_batch = torch.cat((torch.zeros_like(coords[:, :1]), coords), dim=1)
    hidden = SparseTensor(values.cuda(), coords_with_batch.cuda(), shape=torch.Size([1, 6]))
    hidden._spatial_cache = GeometryCache()
    encoder = pipeline.models['shape_slat_encoder']
    encoder.input_layer.cuda()
    hidden = encoder.input_layer(hidden).type(encoder.dtype)
    encoder.input_layer.cpu()
    del values, coords, coords_with_batch, dual, intersected
    # Move one level at a time to cap memory use without changing the encoder math.
    for blocks in encoder.blocks:
        blocks.cuda()
        for block in blocks:
            hidden = block(hidden)
        blocks.cpu()
        hidden._spatial_cache.clear()
        torch.cuda.empty_cache()
    for start in range(0, len(hidden.feats), 250_000):
        part = hidden.feats[start:start + 250_000]
        part.copy_(functional.layer_norm(part, part.shape[-1:]))
    encoder.to_latent.cuda()
    hidden = encoder.to_latent(hidden)
    shape = hidden.replace(hidden.feats.chunk(2, dim=-1)[0].contiguous())
    encoder.cpu()
    del hidden, encoder
    move_inverse_maps(shape._spatial_cache, 'cpu')
    torch.cuda.empty_cache()

    torch.manual_seed(recipe['seed'])
    material_model = pipeline.models['tex_slat_flow_model_1024']
    texture = pipeline.sample_tex_slat(conditioning, material_model, shape, recipe['sampler'])
    if not torch.equal(texture.coords, shape.coords):
        raise ValueError('Material sampling changed the encoded surface support.')
    texture._spatial_cache = shape._spatial_cache
    texture._scale = shape._scale
    del shape, conditioning
    move_inverse_maps(texture._spatial_cache, 'cuda')
    decoder = pipeline.models['tex_slat_decoder']
    decoder.low_vram = True
    decoder.from_latent.cuda()
    decoder.output_layer.cuda()
    print('Decoding materials on the fixed surface', flush=True)
    voxels = decoder(texture)
    coords = voxels.coords.cpu().numpy()
    attrs = (voxels.feats * .5 + .5).cpu().numpy()
    decoder.cpu()
    del decoder, pipeline, texture, voxels, material_model
    gc.collect()
    torch.cuda.empty_cache()
    return coords, attrs


def bake_maps(normalized, faces, uv, document, binary, volume, size):
    import numpy as np
    import torch
    from PIL import Image
    from flex_gemm.ops.grid_sample import grid_sample_3d
    from glb_data import image
    from o_voxel.uvraster import rasterize_uv
    from scipy.ndimage import distance_transform_edt

    resolution = MATERIAL_RESOLUTION
    coords, attrs = (torch.from_numpy(tensor).cuda().contiguous() for tensor in volume)
    mask, ids, bary = rasterize_uv(
        torch.from_numpy(uv).cuda(), torch.from_numpy(faces.astype(np.int32)).cuda(), size)
    covered = mask.flatten().nonzero().flatten()
    if covered.numel() == 0:
        raise ValueError('The existing UV layout has no covered texels.')
    ids, bary = ids.flatten(), bary.reshape(-1, 3)
    triangles = torch.from_numpy(normalized[faces]).cuda()
    pixels = np.zeros((size * size, 6), dtype=np.uint8)
    hits = np.zeros(size * size, dtype=bool)
    occupied = torch.ones((len(attrs), 1), dtype=attrs.dtype, device='cuda')
    for start in range(0, len(covered), 100_000):
        index = covered[start:start + 100_000]
        pos = (triangles[ids[index].long()] * bary[index, :, None]).sum(1)
        query = ((pos + .5) * resolution).reshape(1, -1, 3)
        value = grid_sample_3d(attrs, coords, torch.Size([1, 6, resolution, resolution, resolution]),
                               query, mode='trilinear').reshape(-1, 6)
        weight = grid_sample_3d(occupied, coords, torch.Size([1, 1, resolution, resolution, resolution]),
                                query, mode='trilinear').reshape(-1, 1)
        good = weight[:, 0] > 1e-4
        samples = (value / weight.clamp_min(1e-4))[good]
        if not torch.isfinite(samples).all().item():
            raise ValueError('Material refinement produced invalid texture samples.')
        take = index[good].cpu().numpy()
        pixels[take] = (samples.clamp(0, 1) * 255).round().byte().cpu().numpy()
        hits[take] = True
    coverage = mask.cpu().numpy()
    del coords, attrs, occupied, mask, ids, bary, covered, triangles, value, weight, pos, query, index, samples
    torch.cuda.empty_cache()

    hits = hits.reshape(size, size)
    pixels = pixels.reshape(size, size, 6)
    if not hits.any():
        raise ValueError('No generated materials cover the existing UV layout.')
    distance, nearest = distance_transform_edt(~hits, return_indices=True)
    gutter = (~hits) & (distance <= 8)
    pixels[gutter] = pixels[nearest[0][gutter], nearest[1][gutter]]
    missing = coverage & ~hits & ~gutter
    fallback = missing[coverage].mean()
    if fallback > .01:
        raise ValueError('Material refinement left more than 1% of covered texels without support.')
    if missing.any():
        primitive = document['meshes'][0]['primitives'][0]
        original = document['materials'][primitive.get('material', 0)]['pbrMetallicRoughness']
        for key, channels in [('baseColorTexture', [0, 1, 2, 5]), ('metallicRoughnessTexture', [None, 4, 3])]:
            texture = document['textures'][original[key]['index']]
            source = texture.get('source', texture.get('extensions', {}).get('EXT_texture_webp', {}).get('source'))
            old = np.asarray(image(document, binary, source).convert('RGBA').resize((size, size), Image.Resampling.LANCZOS))
            for old_channel, new_channel in enumerate(channels):
                if new_channel is not None:
                    pixels[..., new_channel][missing] = old[..., old_channel][missing]
    base = Image.fromarray(pixels[..., [0, 1, 2, 5]], 'RGBA')
    metal_rough = np.stack([np.zeros((size, size), np.uint8), pixels[..., 4], pixels[..., 3]], axis=-1)
    report = dict(uv_coverage_percent=100 * coverage.mean(), generated_hit_percent=100 * hits[coverage].mean(),
                  original_texture_fallback_percent=100 * fallback, gutter_pixels=8)
    return base, Image.fromarray(metal_rough, 'RGB'), report


def append_textures(destination, document, binary, base, metal_rough):
    from glb_data import read

    updated, blob = copy.deepcopy(document), bytearray(binary)

    def append(image):
        stream = io.BytesIO()
        image.save(stream, format='PNG')
        payload = stream.getvalue()
        blob.extend(b'\0' * (-len(blob) % 4))
        views = updated['bufferViews']
        views.append(dict(buffer=0, byteOffset=len(blob), byteLength=len(payload)))
        blob.extend(payload)
        images = updated['images']
        images.append(dict(bufferView=len(views) - 1, mimeType='image/png'))
        textures = updated['textures']
        textures.append(dict(source=len(images) - 1))
        return dict(index=len(textures) - 1, texCoord=0)

    primitive = updated['meshes'][0]['primitives'][0]
    donor_index = primitive.get('material', 0)
    material = copy.deepcopy(updated['materials'][donor_index])
    material['pbrMetallicRoughness'] = dict(
        baseColorTexture=append(base), metallicRoughnessTexture=append(metal_rough),
        baseColorFactor=[1, 1, 1, 1], metallicFactor=1, roughnessFactor=1)
    updated['materials'].append(material)
    primitive['material'] = len(updated['materials']) - 1
    blob.extend(b'\0' * (-len(blob) % 4))
    updated['buffers'][0]['byteLength'] = len(blob)
    descriptor = json.dumps(updated, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    descriptor += b' ' * (-len(descriptor) % 4)
    with destination.open('wb') as stream:
        stream.write(struct.pack('<4sIIII', b'glTF', 2, 28 + len(descriptor) + len(blob), len(descriptor), 0x4E4F534A))
        stream.write(descriptor)
        stream.write(struct.pack('<II', len(blob), 0x004E4942))
        stream.write(blob)
    result, result_binary = read(destination)
    for key in ('accessors', 'nodes', 'scenes', 'skins', 'animations'):
        if result.get(key) != document.get(key):
            raise ValueError(f'Material refinement changed GLB {key}.')
    original = copy.deepcopy(document['meshes'])
    modified = result['meshes']
    original[0]['primitives'][0].pop('material', None)
    modified[0]['primitives'][0].pop('material', None)
    if original != modified or result_binary[:len(binary)] != binary:
        raise ValueError('Material refinement changed GLB geometry.')


def main(model, reference, work):
    from gpu_runtime import configure_attention, select_gpu

    select_gpu(ROOT)
    os.environ['TRELLIS_MAX_RESOLUTION'] = str(MATERIAL_RESOLUTION)
    config = pipeline_config(ROOT, verify_encoder=True)
    recipe = checked_recipe(**json.loads((work / 'recipe.json').read_text(encoding='utf-8')))
    (work / 'pipeline.json').write_text(json.dumps(config), encoding='utf-8')
    source_hash = file_sha(model)
    document, binary, normalized, faces, uv = source_mesh(model)

    import torch
    from api_spz.core.state_manage import _apply_patches

    if not torch.cuda.is_available():
        raise RuntimeError('TRELLIS.2 material refinement requires CUDA.')
    torch.set_num_threads(4)
    configure_attention(torch)
    _apply_patches()
    start = perf_counter()
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        volume = infer(work, reference, normalized, faces, recipe)
        base, metal_rough, report = bake_maps(normalized, faces, uv, document, binary, volume, recipe['texture_size'])
        output = work / 'output.glb'
        append_textures(output, document, binary, base, metal_rough)
    report.update(
        input_sha256=source_hash, output_sha256=file_sha(output), triangles=len(faces),
        geometry_binary_unchanged=True, resolution=MATERIAL_RESOLUTION, texture_size=recipe['texture_size'],
        seed=recipe['seed'], sampler=recipe['sampler'], seconds=round(perf_counter() - start, 2),
        peak_vram_gib=round(torch.cuda.max_memory_allocated() / 1024**3, 3),
    )
    (work / 'result.json').write_text(json.dumps(report, allow_nan=False), encoding='utf-8')


if __name__ == '__main__':
    try:
        main(*map(Path, sys.argv[1:]))
    except Exception as error:
        traceback.print_exc()
        sys.exit(2 if 'out of memory' in str(error).lower() else 1)
