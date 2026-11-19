"""Install the optional Hi3D runtime into isolated dependency and asset directories."""

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpu_runtime import load_profiles, select_gpu
from hi3d_runtime import (HI3D_PORT_REVISION, WEIGHT_FILES, Runtime,
                          _compiler_workspace, _read_json, _read_runtime, _verify_runtime,
                          verify_port_source)
from installer.setup import digest, extract, fetch
from studio_workspace import write

INSTALLER = ROOT / 'installer'
COMPONENT = ROOT / '.tools' / 'hi3d'
LOCK = INSTALLER / 'requirements-hi3d.txt'
LICENSE = ROOT / 'licenses' / 'Hi3D-1.0-LICENSE.md'


def load_manifest():
    manifest = json.loads((INSTALLER / 'hi3d-manifest.json').read_text(encoding='utf-8'))
    entries = {asset['path']: asset for asset in manifest['weights']}
    if (manifest.get('schema') != 1 or manifest['source']['revision'] != HI3D_PORT_REVISION
            or set(entries) != set(WEIGHT_FILES)
            or len(entries) != len(manifest['weights'])
            or any(entries[name]['bytes'] != size for name, size in WEIGHT_FILES.items() if size is not None)):
        raise ValueError('Hi3D manifest does not match the pinned runtime.')
    return manifest


def verify_source(source):
    verify_port_source(source)
    for name in ('LICENSE', 'NOTICE', 'THIRD_PARTY_LICENSES.md'):
        if not (source / name).is_file():
            raise RuntimeError(f'Hi3D source is missing the upstream {name} file.')
    if (source / 'LICENSE').read_bytes().replace(b'\r\n', b'\n') != LICENSE.read_bytes().replace(b'\r\n', b'\n'):
        raise RuntimeError('Hi3D source license does not match the reviewed agreement.')


def install_source(entry):
    source = COMPONENT / 'source'
    if source.exists():
        verify_source(source)
        return source
    archive = COMPONENT / 'source.zip'
    fetch(entry, archive)
    with tempfile.TemporaryDirectory(prefix='source-', dir=COMPONENT) as pending:
        staged = Path(pending) / 'source'
        extract(archive, staged, strip_root=True)
        verify_source(staged)
        staged.rename(source)
    return source


def install_dependencies():
    target = COMPONENT / 'dependencies'
    marker = target / '.studio-hi3d-deps.json'
    lock = {'sha256': digest(LOCK)}
    if target.exists():
        if marker.is_file() and json.loads(marker.read_text(encoding='utf-8')) == lock:
            return target
        raise RuntimeError(f'An unrecognized Hi3D dependency directory was preserved: {target}')
    uv = ROOT / '.tools' / 'uv' / 'uv.exe'
    if not uv.is_file():
        raise RuntimeError('Prepare TRELLIS.2 generation first to provision uv and its CUDA environment.')
    with tempfile.TemporaryDirectory(prefix='deps-', dir=COMPONENT) as pending:
        staged = Path(pending) / 'dependencies'
        command = [str(uv), 'pip', 'install', '--python', sys.executable, '--target', str(staged),
                   '--only-binary', ':all:', '--no-deps', '-r', str(LOCK)]
        subprocess.run(command, check=True, env={**os.environ, 'UV_CACHE_DIR': str(COMPONENT / 'uv-cache')})
        write(staged / marker.name, lock)
        staged.rename(target)
    return target


def gpu_smoke(source, dependencies):
    sys.path[:0] = [*(str(path) for path in dependencies), str(source / 'Hi3D-1.0')]
    select_gpu(ROOT)
    import torch
    from importlib.metadata import version
    from hi3d_runtime import REQUIRED_PACKAGES

    if not torch.cuda.is_available():
        raise RuntimeError('Hi3D needs a working NVIDIA CUDA GPU.')
    architecture = '.'.join(map(str, torch.cuda.get_device_capability()))
    hardware = load_profiles(ROOT)['hi3d']
    if architecture not in hardware['compute_capabilities']:
        raise RuntimeError('This Setup supports Hi3D on NVIDIA compute capabilities 8.6 and 8.9.')
    memory = torch.cuda.get_device_properties(0).total_memory // 1024**2
    if memory < hardware['minimum_vram_mib']:
        raise RuntimeError('This Setup requires an NVIDIA GPU with at least 8 GB VRAM for Hi3D.')
    for name, expected in REQUIRED_PACKAGES.items():
        if version(name) != expected:
            raise RuntimeError(f'Hi3D requires {name} {expected}.')
    import pyfqmr
    import spconv.pytorch as spconv
    from sparc3d.ops.voxelize import MeshVoxelizer
    from transformers import AutoImageProcessor, CLIPVisionModel, Dinov2Model

    if not all((pyfqmr.Simplify, AutoImageProcessor, CLIPVisionModel, Dinov2Model)):
        raise RuntimeError('Hi3D model dependencies could not be loaded.')
    with torch.inference_mode():
        features = torch.ones((1, 8), device='cuda', dtype=torch.float16)
        indices = torch.tensor([[0, 1, 1, 1]], device='cuda', dtype=torch.int32)
        volume = spconv.SparseConvTensor(features, indices, [4, 4, 4], 1)
        convolution = spconv.SubMConv3d(8, 8, 3, padding=1).to(device='cuda', dtype=torch.float16)
        result = convolution(volume)
        vertices = torch.tensor([[0, 0, 0], [0.4, 0, 0], [0, 0.4, 0]], device='cuda')
        faces = torch.tensor([[0, 1, 2]], dtype=torch.int32, device='cuda')
        voxels = MeshVoxelizer(vertices, faces, resolution=16).voxelize()['voxel_coords']
        if result.features.numel() != 8 or not torch.isfinite(result.features).all() or not voxels.numel():
            raise RuntimeError('Hi3D sparse convolution or voxelization did not produce a valid output.')
        torch.cuda.synchronize()
    print('Verified Hi3D CUDA sparse convolution and Triton voxelization.', flush=True)


def verify_gpu(runtime):
    verify_source(runtime.source)
    command = [str(runtime.python), '-I', '-B', '-X', 'utf8', str(Path(__file__).resolve()),
               '--check-gpu', str(runtime.source), *map(str, runtime.dependencies)]
    with _compiler_workspace(ROOT) as directory:
        env = {**os.environ, 'CUMM_DISABLE_JIT': '1', 'TEMP': directory, 'TMP': directory,
               'TRITON_HOME': directory, 'TRITON_CACHE_DIR': str(Path(directory) / 'triton'),
               'CUDA_CACHE_PATH': str(Path(directory) / 'cuda')}
        subprocess.run(command, cwd=directory, env=env, check=True, timeout=180)


def verify_weights(weights, manifest):
    for entry in manifest['weights']:
        path = weights / entry['path']
        if not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise RuntimeError(f'Existing Hi3D asset differs from the pinned download: {entry["path"]}')


def verify_existing(manifest):
    runtime = _read_runtime(ROOT)
    verify_weights(runtime.weights, manifest)
    verify_gpu(runtime)


def check_migration_path(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f'Expected a regular path for Hi3D migration: {path}')


def migrate_weights(root, manifest):
    """Relocate the default Hi3D store while Desktop and Server are stopped."""
    root = Path(root).resolve()
    legacy = root / '.tools' / 'hi3d' / 'weights'
    target = root / 'models' / 'hi3d'
    config_path = root / 'config' / 'hi3d-runtime.json'
    for path in (legacy.parent.parent, legacy.parent, legacy,
                 target.parent, target, config_path.parent, config_path):
        check_migration_path(path)
    config = _read_json(config_path, 16 * 1024)
    if set(config) != {'python', 'source', 'weights', 'dependencies'} or not isinstance(config['weights'], str):
        raise ValueError('Expected a valid Hi3D runtime configuration.')
    configured = Path(config['weights'])
    if configured not in (legacy, target):
        raise ValueError('This Hi3D runtime uses a custom weight directory. Its path was preserved.')
    if legacy.exists() and target.exists():
        raise ValueError('Both Hi3D weight directories exist. Their contents were preserved.')
    source = target if target.exists() else legacy
    if not source.is_dir() or (configured == target and source != target):
        raise ValueError('The configured Hi3D model store is missing.')
    for folder, directories, files in os.walk(source):
        for name in (*directories, *files):
            check_migration_path(Path(folder) / name)
    verify_weights(source, manifest)
    if configured == target:
        return target
    if _read_json(config_path, 16 * 1024) != config:
        raise RuntimeError('The Hi3D runtime configuration changed during verification.')
    moved = source == legacy
    if moved:
        target.parent.mkdir(exist_ok=True)
        legacy.rename(target)
    try:
        write(config_path, {**config, 'weights': str(target)})
    except Exception:
        if moved:
            target.rename(legacy)
        raise
    return target


def default_weights_path(root):
    target = root / 'models' / 'hi3d'
    legacy = root / '.tools' / 'hi3d' / 'weights'
    # Resume an older, unfinished download from the directory that already contains it.
    return legacy if legacy.is_dir() and not target.exists() else target


def install(manifest):
    # Test kernels before starting the larger weight downloads.
    source = install_source(manifest['source'])
    dependencies = install_dependencies()
    weights = default_weights_path(ROOT)
    runtime = Runtime(Path(sys.executable).resolve(), source, weights, (dependencies,))
    verify_gpu(runtime)
    weights.parent.mkdir(parents=True, exist_ok=True)
    missing = sum(entry['bytes'] for entry in manifest['weights'] if not (weights / entry['path']).is_file())
    if shutil.disk_usage(weights if weights.is_dir() else weights.parent).free < missing + 512 * 1024**2:
        raise RuntimeError('Free about 11 GB for the optional Hi3D weights and rerun Setup.')
    for entry in manifest['weights']:
        fetch(entry, weights / entry['path'])
    config = {
        'python': str(runtime.python), 'source': str(source), 'weights': str(weights),
        'dependencies': [str(dependencies)],
    }
    _verify_runtime(runtime)
    write(ROOT / 'config' / 'hi3d-runtime.json', config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify-only', action='store_true')
    mode.add_argument('--migrate-weights', action='store_true',
                      help='Move the verified default weight store while Studio and Server are stopped.')
    parser.add_argument('--accept-model-licenses', action='store_true')
    mode.add_argument('--check-gpu', nargs='+', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.check_gpu:
        gpu_smoke(args.check_gpu[0], args.check_gpu[1:])
        return
    manifest = load_manifest()
    if args.migrate_weights:
        weights = migrate_weights(ROOT, manifest)
        print(f'Hi3D weights are ready at {weights.relative_to(ROOT)}.', flush=True)
        return
    if args.verify_only:
        verify_existing(manifest)
    else:
        if not args.accept_model_licenses:
            raise RuntimeError('Read and accept the Hi3D, DINOv2 and CLIP terms before installing this component.')
        if (ROOT / 'config' / 'hi3d-runtime.json').exists():
            verify_existing(manifest)
        else:
            install(manifest)
    print('Hi3D Detail Refinement is ready.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(f'HI3D SETUP STOPPED: {error}')
