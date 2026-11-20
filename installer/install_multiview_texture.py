"""Install the optional multiview texture runtime using pinned local assets."""

import argparse
from hashlib import sha256 as hash_bytes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpu_runtime import load_profiles, select_gpu
from installer.setup import extract, fetch
from multiview_texture_runtime import availability
from multiview_texture_views import (
    REQUIRED_FILES, RUNTIME_VERSION, WEIGHTS, sha256, validate_runtime,
)
from studio_workspace import write

LOCK = ROOT / 'installer/requirements-multiview-texture.txt'
RUNTIME = ROOT / 'models/multiview-texture'
SOURCE_LICENSE_SHA256 = 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4'


def load_manifest():
    manifest = json.loads((ROOT / 'installer/multiview-texture-manifest.json').read_text(encoding='utf-8'))
    entries = {entry['path']: entry for entry in manifest['assets']}
    expected_paths = {*WEIGHTS, *(name for name in REQUIRED_FILES if name.startswith('weights/base/'))}
    if (manifest.get('schema') != 1 or manifest['source']['revision'] != RUNTIME_VERSION['source_revision']
            or any(manifest.get(key) != RUNTIME_VERSION[key] for key in ('adapter_revision', 'base_revision'))
            or entries.keys() != expected_paths or len(entries) != len(manifest['assets'])
            or any((entries[name]['bytes'], entries[name]['sha256']) != value for name, value in WEIGHTS.items())):
        raise ValueError('The multiview texture manifest does not match the pinned runtime.')
    return manifest


def verify_gpu():
    select_gpu(ROOT)
    import torch

    policy = load_profiles(ROOT)['multiview_texture']
    if not torch.cuda.is_available():
        raise RuntimeError('Multiview texture refinement requires a working NVIDIA CUDA GPU.')
    compute = '.'.join(map(str, torch.cuda.get_device_capability()))
    if compute not in policy['compute_capabilities']:
        raise RuntimeError('This Setup supports multiview texture refinement on NVIDIA compute 8.6 and 8.9.')
    if torch.cuda.get_device_properties(0).total_memory // 1024**2 < policy['minimum_vram_mib']:
        raise RuntimeError('Multiview texture refinement requires at least 8 GB of dedicated VRAM.')
    with torch.inference_mode():
        sample = torch.ones((8, 8), dtype=torch.float16, device='cuda')
        if not torch.all((sample @ sample) == 8).item():
            raise RuntimeError('The selected GPU did not pass the FP16 CUDA test.')


def install_source(entry):
    target = RUNTIME / 'source'
    if target.exists():
        verify_source(target)
        return
    archive = RUNTIME / 'source.zip'
    fetch(entry, archive)
    with TemporaryDirectory(prefix='source-', dir=RUNTIME) as pending:
        unpacked = Path(pending) / 'unpacked'
        staged = Path(pending) / 'source'
        extract(archive, unpacked, strip_root=True)
        staged.mkdir()
        (unpacked / 'mvadapter').rename(staged / 'mvadapter')
        for name in ('LICENSE', 'NOTICE'):
            upstream = unpacked / name
            if upstream.is_file():
                upstream.rename(staged / name)
        verify_source(staged)
        staged.rename(target)
    archive.unlink()


def verify_source(source):
    for name in ('LICENSE', 'mvadapter/pipelines/pipeline_mvadapter_i2mv_sd.py'):
        if not (source / name).is_file():
            raise RuntimeError(f'MV-Adapter source is missing its pinned {name}.')
    license_bytes = (source / 'LICENSE').read_bytes().replace(b'\r\n', b'\n')
    if hash_bytes(license_bytes).hexdigest() != SOURCE_LICENSE_SHA256:
        raise RuntimeError('The downloaded MV-Adapter source has an unexpected license file.')


def install_dependencies():
    target = RUNTIME / 'dependencies'
    if target.exists():
        missing = [name for name in REQUIRED_FILES if name.startswith('dependencies/') and not (RUNTIME / name).is_file()]
        if missing:
            raise RuntimeError('Existing multiview texture dependencies do not match the pinned setup and were preserved.')
        return
    uv = ROOT / '.tools/uv/uv.exe'
    if not uv.is_file():
        raise RuntimeError('Install TRELLIS.2 generation to prepare the native Windows runtime and uv.')
    with TemporaryDirectory(prefix='deps-', dir=RUNTIME) as pending:
        staged = Path(pending) / 'dependencies'
        command = [str(uv), 'pip', 'install', '--python', sys.executable, '--target', str(staged),
                   '--only-binary', ':all:', '--require-hashes', '--no-deps', '-r', str(LOCK)]
        with TemporaryDirectory(prefix='mv-uv-', dir=ROOT / '.tools') as cache:
            subprocess.run(command, check=True, env={**os.environ, 'UV_CACHE_DIR': cache})
        staged.rename(target)


def verify(manifest, *, verify_digests=True):
    validate_runtime(RUNTIME)
    verify_source(RUNTIME / 'source')
    for entry in manifest['assets']:
        path = RUNTIME / entry['path']
        if path.stat().st_size != entry['bytes'] or verify_digests and sha256(path) != entry['sha256']:
            raise RuntimeError(f'Installed multiview texture asset differs from the pinned file: {entry["path"]}')
    capability = availability(ROOT)
    if not capability['available']:
        raise RuntimeError(capability['reason'])


def install(manifest):
    verify_gpu()
    if (RUNTIME / 'runtime.json').is_file():
        verify(manifest)
        return
    RUNTIME.mkdir(parents=True, exist_ok=True)
    missing = sum(entry['bytes'] for entry in manifest['assets'] if not (RUNTIME / entry['path']).is_file())
    if shutil.disk_usage(RUNTIME).free < missing + 512 * 1024**2:
        raise RuntimeError('Free about 4 GB for the optional multiview texture runtime and rerun Setup.')
    install_source(manifest['source'])
    install_dependencies()
    for entry in manifest['assets']:
        fetch(entry, RUNTIME / entry['path'])
    write(RUNTIME / 'runtime.json', RUNTIME_VERSION)
    try:
        verify(manifest, verify_digests=False)
    except (OSError, RuntimeError, ValueError):
        (RUNTIME / 'runtime.json').unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--accept-model-licenses', action='store_true')
    args = parser.parse_args()
    manifest = load_manifest()
    if args.verify_only:
        verify(manifest)
    elif args.accept_model_licenses:
        install(manifest)
    else:
        raise ValueError('Read and accept the Stable Diffusion 2.1 and MV-Adapter terms before installing.')
    print('Multiview texture refinement is ready.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'MULTIVIEW TEXTURE SETUP STOPPED: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
