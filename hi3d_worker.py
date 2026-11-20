"""Isolated Hi3D inference subprocess for Studio's native decoded meshes."""

import argparse
from importlib import import_module, metadata
import json
import logging
from pathlib import Path
import sys
from types import ModuleType


def load_pipeline(source, weights, triangle_target, options):
    import torch

    import hi3d_attention
    from hi3d_runtime import REQUIRED_PACKAGES, verify_port_source

    verify_port_source(source)
    if not torch.cuda.is_available():
        raise ValueError('The optional Hi3D runtime requires a working NVIDIA CUDA GPU.')
    for name, version in REQUIRED_PACKAGES.items():
        if metadata.version(name) != version:
            raise ValueError(f'The verified Hi3D runtime requires {name} {version}.')

    # Import the port without loading ComfyUI's node registration.
    package = ModuleType('studio_hi3d_port')
    package.__path__ = [str(source)]
    sys.modules[package.__name__] = package
    port = import_module('studio_hi3d_port.hi3d_pipeline')
    # Use the tested PyTorch implementation of the two packed attention calls on Windows.
    attention = import_module('sparc3d.nn.sparse.attention.full_attn')
    blocks = import_module('sparc3d.models.autoencoders.blocks')
    attention._flash_attn = lambda: hi3d_attention
    blocks._flash_attn = lambda: hi3d_attention
    pipeline = port.ComfyHi3DPipeline.from_pretrained(
        weights / 'Hi3Dv1.0', local_files_only=True,
        dino_model_id=weights / 'dinov2-large', clip_model_id=weights / 'clip-vit-large-patch14',
    )
    pipeline.setup_device(torch.device('cuda'), 'model_swap')
    pipeline.configure(port.RefineOptions(
        scheduler=options['hi3d_scheduler'], target_face_count=triangle_target, reduce_faces=True,
        guidance_strength=options['hi3d_guidance_strength'], guidance_cutoff=options['hi3d_guidance_cutoff'],
        voxel_budget_scale=options['hi3d_voxel_budget_scale'], tiled_decode=options['hi3d_tiled_decode'],
        remove_floaters=options['hi3d_remove_floaters'], floater_face_ratio=options['hi3d_floater_face_ratio'],
        fill_holes_max_edges=options['hi3d_fill_holes_max_edges'],
    ))
    return pipeline


def refine(args):
    import numpy as np
    from PIL import Image
    import torch
    import trimesh

    from hi3d_runtime import HI3D_VOXEL_TOKENS, check_mesh

    torch.set_num_threads(4)
    native = np.load('vertices.npy', allow_pickle=False)
    faces = np.load('faces.npy', allow_pickle=False)
    check_mesh(native, faces)

    # TRELLIS.2's native tuple is Z-up. The Hi3D input frame matches the original prepared image.
    world = native[:, [0, 2, 1]].astype(np.float64)
    world[:, 2] *= -1
    coarse = trimesh.Trimesh(vertices=world, faces=faces, process=False)
    options = args.refinement_options
    steps = options['hi3d_steps']
    pipeline = load_pipeline(args.source, args.weights, args.triangles, options)

    def progress(event):
        if event.step == 1 or event.step % 5 == 0:
            print(f'Hi3D pass {event.pass_index + 1} step {event.step}/{steps}', flush=True)

    pipeline.progress_callback = progress
    torch.cuda.reset_peak_memory_stats()
    with Image.open('source.png') as image:
        if image.mode != 'RGBA':
            raise ValueError('The Hi3D source needs a prepared RGBA cutout.')
        result = pipeline(image, coarse, resolution=args.resolution, num_inference_steps=steps,
                          seed=options['hi3d_seed'], max_tokens=HI3D_VOXEL_TOKENS).mesh
    torch.cuda.synchronize()

    # Undo the port's unit-radius normalization before the native voxel material transfer.
    check_mesh(result.vertices, result.faces)
    scale = float(coarse.extents.max() / result.extents.max())
    translation = coarse.bounds.mean(axis=0) - result.bounds.mean(axis=0) * scale
    restored = result.vertices * scale + translation
    vertices = np.ascontiguousarray(restored[:, [0, 2, 1]], dtype=np.float32)
    vertices[:, 1] *= -1
    faces = np.ascontiguousarray(result.faces, dtype=np.int32)
    check_mesh(vertices, faces)
    np.save('refined-vertices.npy', vertices, allow_pickle=False)
    np.save('refined-faces.npy', faces, allow_pickle=False)
    Path('result.json').write_text(json.dumps(dict(
        peak_vram_gib=round(torch.cuda.max_memory_allocated() / 1024**3, 3),
        peak_reserved_gib=round(torch.cuda.max_memory_reserved() / 1024**3, 3),
    ), allow_nan=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--dependency', action='append', default=[])
    parser.add_argument('--resolution', type=int, choices=(512, 1024), required=True)
    parser.add_argument('--triangles', type=int, required=True)
    parser.add_argument('--refinement-options', type=json.loads)
    args = parser.parse_args()
    # The Python executable runs with -I; only the bridge and configured dependency roots are added.
    sys.path[:0] = [str(Path(__file__).resolve().parent), *args.dependency]
    sys.pycache_prefix = str(Path.cwd() / 'python-cache')

    from generation_options import hi3d_refinement_options

    args.refinement_options = hi3d_refinement_options(args.refinement_options)
    logging.basicConfig(level=logging.INFO)
    try:
        refine(args)
    except RuntimeError as error:
        if 'out of memory' not in str(error).lower():
            raise
        print('HI3D_GPU_MEMORY_LIMIT', flush=True)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
