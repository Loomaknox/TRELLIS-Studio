"""Install the CPU-only U2Net interpreter independently of the generation stack."""

import argparse
from importlib.metadata import distributions
from pathlib import Path
import subprocess
import sys

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))

from installer.native_workflow_install_common import safe_path, verify_packages
from segmentation_runtime import RUNTIME


LOCK = Path(__file__).with_name('requirements-segmentation.txt')


def verify(root):
    python = safe_path(root, RUNTIME)
    verify_packages(python.parent.parent / 'Lib/site-packages', LOCK)
    subprocess.run([python, '-I', '-B', '-c',
                    'import sys, onnxruntime as ort; from importlib.metadata import version; '
                    'assert sys.prefix != sys.base_prefix and sys.version_info[:2] == (3, 11); '
                    'assert version("rembg") == "2.0.88" and "CPUExecutionProvider" in ort.get_available_providers()'],
                   stdin=subprocess.DEVNULL, check=True, timeout=60)
    return python


def install(root, uv=None, base=None):
    root = root.resolve()
    uv = uv or safe_path(root, '.tools/uv/uv.exe')
    base = base or safe_path(root, '.venv/Scripts/python.exe')
    python = safe_path(root, RUNTIME)
    if not python.is_file():
        subprocess.run([uv, 'venv', '--no-config', '--python', base, python.parent.parent], check=True)
    subprocess.run([uv, 'pip', 'sync', '--no-config', '--only-binary', ':all:', '--require-hashes',
                    '--python', python, LOCK], check=True)
    return verify(root)


def retire_previous_rembg(root, uv, python, relative_site, version):
    """Remove only Studio's former pin after its replacement has been validated."""
    site = safe_path(root, relative_site)
    if any(dist.metadata.get('Name', '').lower() == 'rembg' and dist.version == version
           for dist in distributions(path=[str(site)])):
        subprocess.run([uv, 'pip', 'uninstall', '--no-config', '--python', python, '--target', site, 'rembg'],
                       check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=SOURCE)
    parser.add_argument('--uv', type=Path)
    parser.add_argument('--base-python', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        verify(args.root)
    else:
        install(args.root, args.uv, args.base_python)
