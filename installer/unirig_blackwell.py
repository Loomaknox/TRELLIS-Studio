"""Build an isolated sm_120 UniRig stack from pinned upstream sources.

This profile is experimental until its CUDA operator checks and a real rigging
job pass on the target device. It requires the CUDA 12.8 toolkit (not a driver).
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

SOURCES = {
    'cumm': ('https://github.com/FindDefinition/cumm.git', '4c77b38d1ab57d5d1c157adddf67dad93f3a446b'),
    'spconv': ('https://github.com/traveller59/spconv.git', '263d6b47425ef843c82f997b12d8b714013d216c'),
    'flash-attention': ('https://github.com/Dao-AILab/flash-attention.git', '060c9188beec3a8b62b33a3bfa6d5d2d44975fab'),
}


FLASH_WHEEL = {
    'filename': 'flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl',
    'sha256': '3d41b2fc55753faa7f45d6568ea73a96b96afb48b82994ab9b49bcbcb6c87588',
}
FLASH_WHEEL['url'] = ('https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3/'
                      + FLASH_WHEEL['filename'].replace('+', '%2B'))


def flash_wheel(environment, python):
    # This exact upstream artifact contains native sm_120 kernels. Its ABI is
    # intentionally narrow; a different interpreter/torch must use a source build.
    abi = json.loads(subprocess.check_output([str(python), '-c',
        'import json,platform,sys,torch; print(json.dumps([list(sys.version_info[:2]),'
        'platform.system(),platform.machine(),torch.__version__,torch._C._GLIBCXX_USE_CXX11_ABI]))'], text=True))
    if abi != [[3, 11], 'Linux', 'x86_64', '2.8.0+cu128', True]:
        raise RuntimeError('The pinned FlashAttention wheel requires Linux x86_64, Python 3.11 and '
                           'torch 2.8.0+cu128 with CXX11 ABI. Set TRELLIS_UNIRIG_FLASH_SOURCE=1 to build from source.')
    cache = environment / 'cache/downloads'
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / FLASH_WHEEL['filename']
    def verify(path):
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != FLASH_WHEEL['sha256']:
            raise RuntimeError('FlashAttention wheel SHA-256 mismatch; cached file preserved: ' + str(path))
    if target.exists():
        verify(target)
        return target
    pending = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, suffix='.download', delete=False) as output:
            pending = Path(output.name)
            with urllib.request.urlopen(FLASH_WHEEL['url'], timeout=300) as response:
                shutil.copyfileobj(response, output)
        verify(pending)
        pending.replace(target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return target


def repair_bpy_metadata():
    """Correct the known cp39 WHEEL typo in bpy's cp311 Linux 4.2.0 wheel."""
    import base64
    import csv
    import io
    from importlib.metadata import distribution

    package = distribution('bpy')
    if package.version != '4.2.0' or package.metadata['Requires-Python'] != '==3.11.*':
        raise RuntimeError('Unknown bpy package metadata preserved.')
    if sys.version_info[:2] != (3, 11) or sys.platform != 'linux':
        raise RuntimeError('The bpy metadata repair targets Python 3.11 on Linux only.')
    wheel_name = 'bpy-4.2.0.dist-info/WHEEL'
    wheel = Path(package.locate_file(wheel_name))
    original = wheel.read_bytes()
    expected = (b'Wheel-Version: 1.0\nGenerator: bdist_wheel (0.38.4)\n'
                b'Root-Is-Purelib: false\nTag: cp39-cp39-manylinux_2_28_x86_64\n\n')
    corrected = expected.replace(b'cp39-cp39', b'cp311-cp311')
    if original not in (expected, corrected):
        raise RuntimeError('Unknown bpy WHEEL metadata preserved.')
    record = Path(package.locate_file('bpy-4.2.0.dist-info/RECORD'))
    rows = list(csv.reader(io.StringIO(record.read_text(encoding='utf-8'))))
    matches = [row for row in rows if row[0] == wheel_name]
    if len(matches) != 1:
        raise RuntimeError('Unknown bpy RECORD layout preserved.')
    matches[0][1:] = ['sha256=' + base64.urlsafe_b64encode(hashlib.sha256(corrected).digest()).rstrip(b'=').decode(), str(len(corrected))]
    output = io.StringIO(newline='')
    csv.writer(output, lineterminator='\n').writerows(rows)
    wheel_pending = wheel.with_suffix('.trellis-tmp')
    record_pending = record.with_suffix('.trellis-tmp')
    wheel_pending.write_bytes(corrected)
    record_pending.write_text(output.getvalue(), encoding='utf-8', newline='\n')
    wheel_pending.replace(wheel)
    record_pending.replace(record)
    print('Corrected bpy 4.2.0 WHEEL tag to match its Python 3.11 package and updated RECORD.')


def detect_profile():
    selected = os.environ.get('TRELLIS_UNIRIG_PROFILE', 'auto')
    if selected not in ('auto', 'legacy', 'blackwell'):
        raise RuntimeError('TRELLIS_UNIRIG_PROFILE must be auto, legacy or blackwell.')
    if selected != 'auto':
        return selected
    output = subprocess.check_output(
        ['nvidia-smi', '--query-gpu=compute_cap', '--format=csv,noheader'], text=True)
    capabilities = [float(line.strip()) for line in output.splitlines() if line.strip()]
    if not capabilities:
        raise RuntimeError('No NVIDIA GPU found for UniRig.')
    # The stack targets GeForce Blackwell sm_120. Do not assume other future
    # architectures share its kernels. Multiple different GPUs need review.
    if any(value >= 10 for value in capabilities):
        if set(capabilities) != {12.0}:
            raise RuntimeError('This UniRig profile targets sm_120 only; review the detected GPU capabilities.')
        return 'blackwell'
    return 'legacy'


def prerequisites():
    for name in ('git', 'g++', 'nvcc'):
        if not shutil.which(name):
            raise RuntimeError('Blackwell UniRig needs git, g++ and the CUDA 12.8 toolkit inside WSL. '
                               'No Linux NVIDIA display driver should be installed. Missing: ' + name)
    version = subprocess.check_output(['nvcc', '--version'], text=True)
    if not re.search(r'release 12\.8\b', version):
        raise RuntimeError('Use the CUDA 12.8 toolkit for the pinned torch 2.8.0+cu128 build.')


def checkout(base, name):
    url, commit = SOURCES[name]
    path = base / name
    if not path.exists():
        path.mkdir(parents=True)
        subprocess.run(['git', 'init', str(path)], check=True)
        subprocess.run(['git', '-C', str(path), 'remote', 'add', 'origin', url], check=True)
    origin = subprocess.check_output(['git', '-C', str(path), 'remote', 'get-url', 'origin'], text=True).strip()
    if origin != url:
        raise RuntimeError('Unrecognized build source preserved: ' + str(path))
    try:
        head = subprocess.check_output(['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'],
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        head = None
    if head is None:
        subprocess.run(['git', '-C', str(path), 'fetch', '--depth', '1', 'origin', commit], check=True)
        subprocess.run(['git', '-C', str(path), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    elif head != commit:
        raise RuntimeError('Different build source revision preserved: ' + str(path))
    subprocess.run(['git', '-C', str(path), 'submodule', 'update', '--init', '--recursive'], check=True)
    return path


def patch_spconv_metadata(path):
    # cumm 0.8.2 adds the upstream sm_120 compiler flags. Spconv 2.3.8's
    # metadata still caps cumm below 0.8. Keep the narrow override explicit.
    setup = path / 'setup.py'
    text = setup.read_text(encoding='utf-8')
    before, after = '>=0.7.11, <0.8.0', '>=0.8.2, <0.9.0'
    if text.count(after) == 2 and before not in text:
        return
    if text.count(before) != 2 or after in text:
        raise RuntimeError('Unexpected spconv dependency metadata; source preserved.')
    setup.write_text(text.replace(before, after), encoding='utf-8')


def common_requirements(source):
    # Keep the legacy application pins, but let the CUDA 12.8 torch wheel
    # supply its matching NVIDIA libraries, sympy and Triton transitives.
    excluded = {'torch', 'torchvision', 'torch-cluster', 'torch-scatter', 'flash-attn',
                'spconv-cu120', 'cumm-cu120', 'sympy', 'triton'}
    return '\n'.join(line for line in source.splitlines()
                     if not line.startswith('nvidia-')
                     and re.split(r'[= @<>]', line, 1)[0] not in excluded) + '\n'


def install(uv, environment):
    prerequisites()
    python = environment / 'venv/bin/python'
    def pip(*args):
        subprocess.run([str(uv), 'pip', 'install', '--python', str(python), *map(str, args)], check=True)
    pip('torch==2.8.0', 'torchvision==0.23.0', '--index-url', 'https://download.pytorch.org/whl/cu128')
    requirements = environment / 'requirements-application.txt'
    requirements.write_text(common_requirements((Path(__file__).parent / 'requirements-unirig.txt').read_text()), encoding='utf-8')
    pip('-r', requirements, 'wheel==0.45.1', '--extra-index-url', 'https://download.pytorch.org/whl/cu128',
        '--index-strategy', 'unsafe-best-match')
    pip('torch-scatter==2.1.2+pt28cu128', 'torch-cluster==1.6.3+pt28cu128', '--no-deps',
        '--no-index', '--find-links', 'https://data.pyg.org/whl/torch-2.8.0+cu128.html')
    os.environ.update(CUMM_CUDA_VERSION='12.8', CUMM_CUDA_ARCH_LIST='12.0',
                      CUMM_DISABLE_JIT='1', SPCONV_DISABLE_JIT='1',
                      FLASH_ATTENTION_FORCE_BUILD='TRUE', FLASH_ATTN_CUDA_ARCHS='120',
                      TORCH_CUDA_ARCH_LIST='12.0', MAX_JOBS=os.environ.get('MAX_JOBS', '1'),
                      NVCC_THREADS=os.environ.get('NVCC_THREADS', '1'))
    os.environ['CUDA_HOME'] = str(Path(shutil.which('nvcc')).resolve().parents[1])
    for name in SOURCES:
        if name == 'flash-attention' and os.environ.get('TRELLIS_UNIRIG_FLASH_SOURCE') != '1':
            pip('--no-deps', flash_wheel(environment, python))
            continue
        source = checkout(environment / 'sources', name)
        if name == 'spconv':
            patch_spconv_metadata(source)
        # Build against the installed torch/CUDA ABI, never an isolated CPU torch.
        pip('--no-build-isolation', '--no-deps', source)
    subprocess.run([str(python), str(Path(__file__).resolve()), '--repair-bpy-metadata'], check=True)
    subprocess.run([str(uv), 'pip', 'check', '--python', str(python)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-bpy-metadata', action='store_true')
    parser.add_argument('--detect', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--uv', type=Path)
    parser.add_argument('--environment', type=Path)
    args = parser.parse_args()
    if args.repair_bpy_metadata:
        repair_bpy_metadata()
    elif args.detect:
        print(detect_profile())
    elif args.preflight:
        prerequisites()
    elif args.uv and args.environment:
        install(args.uv, args.environment)
    else:
        parser.error('Specify --detect, --preflight, or --uv and --environment.')
