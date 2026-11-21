"""Install the opt-in UltraTex 2K runtime for private evaluation on Windows."""

import argparse
from hashlib import sha256
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpu_runtime import load_profiles, select_gpu
from installer.setup import digest, extract, fetch
from studio_workspace import write
from ultratex_runtime import LICENSE, LICENSE_URL, REVISIONS, WEIGHTS, validated_runtime

RUNTIME = ROOT / 'models' / 'ultratex'
SOURCE_DIRS = {'comfy': 'ComfyUI', 'gguf': 'repos/ComfyUI-GGUF', 'ultratex': 'repos/UltraTex'}
LOCKS = {'comfy-deps': 'requirements-ultratex-comfy.txt', 'deps': 'requirements-ultratex-gguf.txt'}
RESERVE_BYTES = 2 * 1024**3


def load_manifest():
    manifest = json.loads((ROOT / 'installer' / 'ultratex-manifest.json').read_text(encoding='utf-8'))
    assets = {asset['path']: (asset['bytes'], asset['sha256']) for asset in manifest['assets']}
    sources = {source['id']: source for source in manifest['sources']}
    if (manifest.get('schema') != 1 or assets != WEIGHTS or len(assets) != len(manifest['assets'])
            or sources.keys() != REVISIONS.keys() or len(sources) != len(manifest['sources'])
            or any(sources[name]['destination'] != SOURCE_DIRS[name]
                   or sources[name]['revision'] != revision for name, revision in REVISIONS.items())):
        raise ValueError('The UltraTex manifest does not match the pinned runtime.')
    license_file = ROOT / 'licenses' / 'FLUX.2-klein-base-9B-LICENSE.md'
    license_sha = load_profiles(ROOT)['ultratex']['license_sha256'].lower()
    if (manifest['license']['path'] != license_file.relative_to(ROOT).as_posix()
            or manifest['license']['url'] != LICENSE_URL
            or manifest['license']['sha256'] != license_sha or digest(license_file) != license_sha):
        raise ValueError('The UltraTex model license does not match Setup.')
    return manifest


def verify_gpu():
    if os.name != 'nt' or sys.version_info[:2] != (3, 11) or sys.maxsize <= 2**32:
        raise RuntimeError('This pinned UltraTex component needs the Windows x64 Studio Python 3.11 runtime.')
    select_gpu(ROOT)
    import torch

    if torch.__version__ != '2.8.0+cu128' or not torch.cuda.is_available():
        raise RuntimeError('UltraTex requires the Studio NVIDIA CUDA 12.8 PyTorch 2.8 runtime.')
    device = torch.cuda.get_device_properties(0)
    policy = load_profiles(ROOT)['ultratex']
    capability = f'{device.major}.{device.minor}'
    if capability not in policy['compute_capabilities']:
        raise RuntimeError('UltraTex Setup supports NVIDIA compute 8.6, 8.9 and 12.0.')
    minimum = policy['minimum_vram_mib']
    if device.total_memory // 1024**2 < minimum:
        raise RuntimeError(f'UltraTex requires at least {minimum:,} MiB of dedicated VRAM.')
    if not torch.cuda.is_bf16_supported(including_emulation=False):
        raise RuntimeError('The selected CUDA GPU needs native BF16 support for UltraTex.')
    with torch.inference_mode():
        sample = torch.ones((8, 8), dtype=torch.bfloat16, device='cuda')
        if not torch.all(sample @ sample == 8).item():
            raise RuntimeError('The selected GPU did not pass the BF16 CUDA test.')


def safe_location(path):
    parts = [path, *[parent for parent in path.parents if parent != ROOT and ROOT in parent.parents]]
    if not path.resolve().is_relative_to(ROOT) or any(
            part.is_symlink() or getattr(part, 'is_junction', lambda: False)() for part in parts):
        raise RuntimeError('An UltraTex component path redirects outside the installed layout.')
    return path


def verify_source(path, entry):
    excluded = {'.studio-pixal3d-source.json'}
    files = []
    for file in path.rglob('*'):
        relative = file.relative_to(path)
        if file.is_symlink() or getattr(file, 'is_junction', lambda: False)():
            raise RuntimeError(f'Existing UltraTex source has redirected files and was preserved: {entry["id"]}.')
        if file.is_file() and '__pycache__' not in relative.parts and file.suffix != '.pyc':
            name = relative.as_posix()
            if name not in excluded:
                files.append((name, file))
    tree = sha256()
    for name, file in sorted(files):
        raw = file.read_bytes()
        try:
            raw = raw.decode('utf-8').replace('\r\n', '\n').encode('utf-8')
        except UnicodeDecodeError:
            pass
        tree.update(name.encode('utf-8') + b'\0' + sha256(raw).digest())
    if len(files) != entry['source_files'] or tree.hexdigest() != entry['source_tree_sha256']:
        raise RuntimeError(f'Existing UltraTex source differs from the pinned revision and was preserved: {entry["id"]}.')


def install_source(entry):
    target = safe_location(RUNTIME / entry['destination'])
    if target.exists():
        verify_source(target, entry)
        return
    archive = safe_location(ROOT / '.downloads' / f'ultratex-{entry["id"]}-{entry["revision"]}.zip')
    safe_location(archive.with_suffix('.zip.part'))
    fetch(entry, archive)
    with TemporaryDirectory(prefix='source-', dir=RUNTIME) as temporary:
        staged = Path(temporary) / 'source'
        extract(archive, staged, strip_root=True)
        verify_source(staged, entry)
        # The published node archive includes Python cache files. Install from source.
        for file in staged.rglob('*.pyc'):
            file.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        staged.rename(target)


def package_versions(path):
    return {re.sub(r'[-_.]+', '-', item.metadata['Name']).lower(): item.version
            for item in distributions(path=[str(path)])}


def verify_dependencies(path, lock):
    expected = {}
    for line in lock.read_text(encoding='ascii').splitlines():
        name, version = line.split()[0].split('==', 1)
        expected[name] = version
    if package_versions(path) != expected:
        raise RuntimeError(f'Existing UltraTex dependencies differ from {lock.name} and were preserved.')


def install_dependencies(directory, lock_name):
    target = safe_location(RUNTIME / directory)
    lock = ROOT / 'installer' / lock_name
    if target.exists():
        verify_dependencies(target, lock)
        return
    uv = ROOT / '.tools' / 'uv' / 'uv.exe'
    if not uv.is_file():
        raise RuntimeError('Install TRELLIS.2 generation to prepare the native Windows runtime and uv.')
    with TemporaryDirectory(prefix='deps-', dir=RUNTIME) as temporary:
        staged = Path(temporary) / 'packages'
        subprocess.run([str(uv), 'pip', 'install', '--python', sys.executable, '--target', str(staged),
                        '--no-config', '--only-binary', ':all:', '--require-hashes', '--no-deps', '-r', str(lock)],
                       check=True, env={**os.environ, 'UV_CACHE_DIR': str(Path(temporary) / 'cache')})
        verify_dependencies(staged, lock)
        staged.rename(target)


def smoke_dependencies():
    # Keep the isolated package paths and offline policy identical to the inference subprocess.
    script = """import sys
from pathlib import Path
root, runtime, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))
from ultratex_worker import load_gguf, setup_environment
setup_environment(runtime, work)
import triton
import nodes
from comfy_api.latest import Types
from UltraTex.core.contracts import RuntimePolicy
from UltraTex.extension import TextEncode
from UltraTex.fast_baker import run_fast_bake
from UltraTex.simple import GenerateTextureViews, PrepareTexture
module = load_gguf(runtime)
assert all(callable(item) for item in (Types.MESH, RuntimePolicy, run_fast_bake, TextEncode.execute,
                                       GenerateTextureViews.execute, PrepareTexture.execute,
                                       module.UnetLoaderGGUF, module.CLIPLoaderGGUF))
print('UltraTex compute dependencies loaded offline.', flush=True)
"""
    with TemporaryDirectory(prefix='ultratex-smoke-') as temporary:
        subprocess.run([sys.executable, '-I', '-B', '-X', f'pycache_prefix={temporary}/bytecode',
                        '-c', script, str(ROOT), str(RUNTIME), temporary],
                       cwd=temporary, check=True, timeout=120)


def verify(manifest):
    for entry in manifest['sources']:
        verify_source(safe_location(RUNTIME / entry['destination']), entry)
    for directory, lock in LOCKS.items():
        verify_dependencies(safe_location(RUNTIME / directory), ROOT / 'installer' / lock)
    for path in WEIGHTS:
        safe_location(RUNTIME / path)
    validated_runtime(ROOT, verify_weights=True)


def install(manifest):
    verify_gpu()
    runtime = safe_location(RUNTIME)
    runtime.mkdir(parents=True, exist_ok=True)
    marker = safe_location(runtime / 'runtime.json')
    for entry in manifest['sources']:
        install_source(entry)
    for directory, lock in LOCKS.items():
        install_dependencies(directory, lock)
    smoke_dependencies()
    downloads = []
    missing = 0
    for entry in manifest['assets']:
        path = safe_location(runtime / entry['path'])
        part = safe_location(path.with_name(path.name + '.part'))
        if not path.is_file():
            present = part.stat().st_size if part.is_file() else 0
            missing += max(0, entry['bytes'] - present)
        downloads.append((entry, path))
    if missing and shutil.disk_usage(runtime).free < missing + RESERVE_BYTES:
        raise RuntimeError('Free about 16 GiB for a fresh optional UltraTex installation, then rerun Setup.')
    for entry, path in downloads:
        fetch(entry, path)
    if not marker.exists():
        write(marker, dict(schema=1, revisions=REVISIONS, license=LICENSE))
    validated_runtime(ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument('--verify-only', action='store_true')
    options.add_argument('--accept-model-licenses', action='store_true',
                         help=f'Accept terms for private evaluation, including {LICENSE_URL}')
    args = parser.parse_args()
    manifest = load_manifest()
    if args.verify_only:
        verify(manifest)
    else:
        install(manifest)
    print('UltraTex 2K is ready for private, non-production evaluation.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f'ULTRATEX SETUP STOPPED: {error}', file=sys.stderr, flush=True)
        sys.exit(1)
