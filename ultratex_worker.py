"""Bake the verified six-view UltraTex recipe onto a single primitive GLB."""
import importlib
import json
import logging
import os
from pathlib import Path
import sys
from time import perf_counter
import traceback


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ultratex_runtime as recipe
from retexture_runtime import file_sha
from studio_workspace import write


def load_surface(path):
    import numpy as np
    from glb_data import accessor, read

    document, binary = read(path)
    meshes = document['meshes']
    if (len(meshes) != 1 or len(meshes[0].get('primitives', [])) != 1 or document.get('skins')
            or any(key in node for node in document.get('nodes', []) for key in
                   ('matrix', 'translation', 'rotation', 'scale'))):
        raise ValueError('UltraTex requires one static mesh with applied transforms and one material.')
    primitive = meshes[0]['primitives'][0]
    attrs = primitive.get('attributes', {})
    if ('indices' not in primitive or primitive.get('mode', 4) != 4
            or 'targets' in primitive or not {'POSITION', 'TEXCOORD_0'} <= attrs.keys()):
        raise ValueError('UltraTex requires indexed triangles with existing UVs.')
    positions = accessor(document, binary, attrs['POSITION']).astype(np.float32)
    uv = accessor(document, binary, attrs['TEXCOORD_0']).astype(np.float32)
    indices = accessor(document, binary, primitive['indices']).ravel()
    if (positions.ndim != 2 or positions.shape != (len(uv), 3) or uv.shape != (len(positions), 2)
            or not len(indices) or len(indices) % 3 or indices.dtype.kind not in 'iu'
            or indices.min() < 0 or indices.max() >= len(positions) or len(positions) >= 2**31
            or not np.isfinite(positions).all() or not np.isfinite(uv).all()
            or uv.min() < -1e-6 or uv.max() > 1 + 1e-6):
        raise ValueError('The GLB has invalid geometry or UV coordinates for UltraTex.')
    faces = indices.reshape(-1, 3).astype(np.int32)
    normals = accessor(document, binary, attrs['NORMAL']).astype(np.float32) if 'NORMAL' in attrs else None
    # Degenerate triangles cannot contribute to the bake. Keep the original GLB and
    # all its faces for assembly; use only the triangles with area for projection.
    valid = np.empty(len(faces), dtype=bool)
    for start in range(0, len(faces), 131072):
        section = faces[start:start + 131072]
        points = positions[section]
        area = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
        texcoords = uv[section]
        a, b = texcoords[:, 1] - texcoords[:, 0], texcoords[:, 2] - texcoords[:, 0]
        uv_area = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        valid[start:start + len(section)] = np.any(area != 0, axis=1) & (uv_area >= 1e-14)
    if not valid.any():
        raise ValueError('The GLB has no triangles with valid geometry and UV area.')
    return document, binary, positions, faces, uv, normals, valid


def setup_environment(runtime, work):
    from gpu_runtime import select_gpu

    select_gpu(ROOT)
    sys.path[:0] = [str(runtime / name) for name in ('repos', 'comfy-deps', 'ComfyUI')]
    sys.path.append(str(runtime / 'deps'))
    sys.argv = ['comfy', '--base-directory', str(work), '--models-directory', str(runtime),
                '--disable-smart-memory', '--offline', '--lowvram', '--reserve-vram', '1.3']
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      TRITON_CACHE_DIR=str(runtime / 'triton-cache'))
    import comfy.options
    comfy.options.enable_args_parsing()


def load_gguf(runtime):
    folder = runtime / 'repos' / 'ComfyUI-GGUF'
    spec = importlib.util.spec_from_file_location('comfy_gguf', folder / '__init__.py',
                                                  submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return importlib.import_module('comfy_gguf.nodes')


def stage(work, name):
    print(f'UltraTex: {name}', flush=True)
    (work / 'stage.txt').write_text(name, encoding='utf-8')


def as_image(tensor):
    import numpy as np
    from PIL import Image

    pixels = tensor.detach().cpu().numpy()[0]
    return Image.fromarray(np.clip(pixels * 255 + .5, 0, 255).astype(np.uint8))


def preserve_alpha(base, document, binary):
    from PIL import Image
    from glb_data import image

    primitive = document['meshes'][0]['primitives'][0]
    materials = document.setdefault('materials', [{}])
    pbr = materials[primitive.get('material', 0)].get('pbrMetallicRoughness', {})
    base_factor = pbr.get('baseColorFactor', [1., 1., 1., 1.])
    texture = pbr.get('baseColorTexture')
    if texture:
        if texture.get('texCoord', 0) != 0 or 'KHR_texture_transform' in texture.get('extensions', {}):
            raise ValueError('UltraTex requires base color mapped directly to UV set 0.')
        texture_id = document['textures'][texture['index']]['source']
        alpha = image(document, binary, texture_id).convert('RGBA').getchannel('A')
        if alpha.size != base.size:
            alpha = alpha.resize(base.size, Image.Resampling.BILINEAR)
    else:
        alpha = Image.new('L', base.size, 255)
    if base_factor[3] != 1.:
        alpha = alpha.point(lambda value: round(value * base_factor[3]))
    base.putalpha(alpha)
    return base


def bake(runtime, work, model, reference, seed):
    import numpy as np
    import torch
    from PIL import Image
    from comfy import model_management
    from comfy_api.latest import Types
    import nodes
    from UltraTex.core.contracts import RuntimePolicy
    from UltraTex.core.cpu import configure_cpu
    from UltraTex.extension import TextEncode
    from UltraTex.fast_baker import run_fast_bake
    from UltraTex.simple import GenerateTextureViews, PrepareTexture
    from retexture_worker import append_textures

    if not torch.cuda.is_available():
        raise ValueError('The UltraTex preview requires a CUDA GPU.')
    configure_cpu()
    start = perf_counter()
    source_hash, reference_hash = file_sha(model), file_sha(reference)
    document, binary, vertices, faces, uvs, normals, valid = load_surface(model)
    report = dict(triangles=len(faces), ignored_bake_triangles=int(len(faces) - valid.sum()),
                  seed=seed, steps=recipe.STEPS, view_count=recipe.VIEW_COUNT, view_resolution=recipe.VIEW_SIZE)
    mesh = Types.MESH(vertices=torch.from_numpy(vertices).unsqueeze(0),
                      faces=torch.from_numpy(faces[valid]).unsqueeze(0),
                      uvs=torch.from_numpy(uvs).unsqueeze(0),
                      normals=torch.from_numpy(normals).unsqueeze(0) if normals is not None else None)
    with Image.open(reference) as source:
        pixels = np.asarray(source.convert('RGBA'), dtype=np.float32) / 255
    reference_image = torch.from_numpy(pixels).unsqueeze(0)
    policy = RuntimePolicy(str(work / 'spill'), gpu_headroom_mb=1300)
    stage(work, 'prepare')
    prepared = PrepareTexture.execute(mesh, reference_image, alignment='front', mask_polarity='foreground',
                                      normal_mode='preserve', normal_view_resolution=recipe.VIEW_SIZE,
                                      runtime=policy).result[0]
    if not (np.array_equal(prepared.context.uvs, uvs) and np.array_equal(prepared.context.faces, faces[valid])):
        raise ValueError('UltraTex preparation changed the expected triangle or UV layout.')
    gguf = load_gguf(runtime)
    clip = gguf.CLIPLoaderGGUF().load_clip('Qwen3-8B-Q6_K.gguf', 'flux2')[0]
    prompt = TextEncode.execute(clip, '').result[0]
    model_management.unload_all_models()
    del clip
    model_management.soft_empty_cache()
    diffusion = gguf.UnetLoaderGGUF().load_unet('flux-2-klein-base-9b-Q4_0.gguf')[0]
    vae = nodes.VAELoader().load_vae('flux2-vae.safetensors')[0]
    branches = {}
    for task, name, adapter in (
        ('albedo', 'albedo', 'ultratex_flux2.safetensors'),
        ('mr', 'materials', 'ultratex_flux2_mr.safetensors'),
    ):
        stage(work, name)
        views, _, _, setup = GenerateTextureViews.execute(
            prepared, diffusion, vae, prompt, adapter, 1.0, 'ultratex_flux2_decoder.pt',
            task, recipe.VIEW_SIZE, recipe.VIEW_COUNT, seed, recipe.STEPS, 4.0, 1.0, .2,
            tiled_decode=True, fast_decode=True,
        ).result
        branches[task] = (setup, views)
        model_management.unload_all_models()
        model_management.soft_empty_cache()
    del diffusion, vae
    stage(work, 'bake')
    material, _, base, _, _, _, bake_report = run_fast_bake(
        *branches['albedo'], recipe.TEXTURE_SIZE, 'surface_fill', 'Quality', 'auto', *branches['mr'],
    )
    albedo = preserve_alpha(as_image(base), document, binary)
    metallic_roughness = as_image(material.metallic_roughness)
    expected = (recipe.TEXTURE_SIZE,) * 2
    if albedo.size != expected or metallic_roughness.size != expected:
        raise ValueError('UltraTex returned incorrect texture dimensions.')
    document.setdefault('images', [])
    document.setdefault('textures', [])
    output = work / 'output.glb'
    append_textures(output, document, binary, albedo, metallic_roughness)
    if source_hash != file_sha(model) or reference_hash != file_sha(reference):
        raise ValueError('The original GLB or reference changed during UltraTex.')
    coverage = json.loads(bake_report)['base_color']
    report.update(
        geometry_uv_equal=True, atlas=list(expected), source_sha256=source_hash,
        reference_sha256=reference_hash, output_sha256=file_sha(output),
        coverage_percent=round(100 * coverage['observed_any_fraction'], 3),
        seconds=round(perf_counter() - start, 2),
        peak_allocated_mib=round(torch.cuda.max_memory_allocated() / 2**20, 2),
    )
    write(work / 'result.json', report)


def main(model, reference, work, seed):
    work = Path(work)
    try:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
        runtime = recipe.validated_runtime(ROOT, verify_weights=True)
        setup_environment(runtime, work)
        bake(runtime, work, Path(model), Path(reference), int(seed))
    except Exception as error:
        traceback.print_exc()
        reason = str(error) if isinstance(error, ValueError) else 'The UltraTex pass failed. See the generation log.'
        write(work / 'error.json', {'reason': reason})
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
