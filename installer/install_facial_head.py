"""Install, verify or remove the opt-in local facial geometry component on Windows."""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.facial_head_lock import component_lock
from installer.kimodo_install_common import atomic_json, verified
from installer.setup import extract, fetch

OWNER = 'trellis-studio/facial-head/v1\n'
INSTALLER = Path(__file__).resolve().parent


def reparse(path):
    try:
        return bool(path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (FileNotFoundError, AttributeError):
        return path.is_symlink()


def location(root):
    root = Path(root).resolve(strict=True)
    folder = root / '.tools' / 'facial-head'
    if reparse(folder.parent) or reparse(folder) or folder.resolve() != folder:
        raise RuntimeError('The face component directory must be inside this installation.')
    return folder


def claim(folder):
    if not folder.exists():
        folder.mkdir(parents=True)
        (folder / 'ownership.txt').write_text(OWNER, encoding='ascii')
    check_owner(folder)


def check_owner(folder):
    marker = folder / 'ownership.txt'
    if reparse(marker) or not marker.is_file() or marker.read_text(encoding='ascii') != OWNER:
        raise RuntimeError('This directory does not belong to the face installer: ' + str(folder))


def check_tree(folder):
    # Reinstallation and removal must both stay inside the owned component.
    for parent, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs + files:
            if reparse(Path(parent) / name):
                raise RuntimeError('Unexpected filesystem link in the face runtime: ' + str(Path(parent) / name))


def remove(root):
    folder = location(root)
    if not folder.exists():
        return False
    check_owner(folder)
    check_tree(folder)
    shutil.rmtree(folder)
    return True


def install_assets(folder):
    manifest = json.loads((INSTALLER / 'facial-head-manifest.json').read_text(encoding='utf-8'))
    downloads = folder / 'downloads'
    for asset in manifest['assets']:
        destination = folder / asset['destination']
        archive = downloads / asset['filename']
        if asset.get('archive'):
            fetch(asset, archive, root=folder)
            extract(archive, destination, strip_root=True)
        elif not verified(destination, asset):
            if destination.exists():
                raise RuntimeError('Unexpected file at ' + str(destination))
            fetch(asset, archive, root=folder)
            destination.parent.mkdir(parents=True, exist_ok=True)
            archive.replace(destination)
    return manifest


def environment(folder):
    # Pip writes only to the private venv. The installed Studio torch/CUDA binaries
    # are appended to its module search path, avoiding a second GPU distribution.
    base_packages = Path(sysconfig.get_path('purelib')).resolve()
    if not (base_packages / 'torch' / '__init__.py').is_file():
        raise RuntimeError('Run this installer with the Python from your working TRELLIS Studio .venv.')
    target = folder / 'venv'
    interpreter = target / 'Scripts/python.exe'
    if not interpreter.is_file():
        venv.EnvBuilder(with_pip=True, symlinks=False).create(target)
    (target / 'Lib/site-packages/trellis-base.pth').write_text(str(base_packages) + '\n', encoding='utf-8')
    work_env = dict(os.environ, PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK='1',
                    PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    with tempfile.TemporaryDirectory(dir=folder, prefix='pip-') as temp:
        work_env.update(TEMP=temp, TMP=temp, TMPDIR=temp)
        subprocess.run([str(interpreter), '-I', '-m', 'pip', '--isolated', 'install',
                        '--no-cache-dir', '--only-binary=:all:', '--require-hashes', '--no-deps', '-r',
                        str(INSTALLER / 'locks/facial-head-win-cp311.txt')], check=True, env=work_env)


def install(root):
    from retexture_runtime import pipeline_config
    # This component uses the existing Studio encoder for its single material pass.
    pipeline_config(root, verify_encoder=True)
    folder = location(root)
    claim(folder)
    check_tree(folder)
    receipt = folder / 'installed.json'
    receipt.unlink(missing_ok=True)
    manifest = install_assets(folder)
    environment(folder)
    subprocess.run([sys.executable, '-B', str(ROOT / 'facial_head_runtime.py'),
                    '--self-test', str(root)], check=True)
    atomic_json(receipt, {'schema': 1, 'validated': True, 'topos_revision': manifest['topos_revision']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'remove', 'status'))
    args = parser.parse_args()
    if args.action == 'status':
        from facial_head_runtime import readiness
        print(json.dumps(readiness(ROOT), ensure_ascii=False))
    else:
        with component_lock(ROOT):
            if args.action == 'install':
                install(ROOT)
                print('Face reconstruction is ready.')
            else:
                print('Face component removed.' if remove(ROOT) else 'Face component already absent.')


if __name__ == '__main__':
    main()
