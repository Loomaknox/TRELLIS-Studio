"""Install or verify the pinned HTTPS proxy without starting it or changing networking."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup import fetch

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified(destination, manifest):
    executable = destination / 'caddy.exe'
    return (executable.is_file() and not executable.is_symlink()
            and executable.stat().st_size == manifest['executable_bytes']
            and sha256(executable) == manifest['executable_sha256'])


def install(destination, manifest, archive):
    destination.mkdir(parents=True, exist_ok=True)
    if verified(destination, manifest):
        return
    if (destination / 'caddy.exe').exists():
        raise RuntimeError('Existing Caddy differs from the pinned version and was preserved. Run Studio Setup to update it.')
    fetch(manifest, archive)
    # Copy only the named executable and notices, never arbitrary archive paths.
    with zipfile.ZipFile(archive) as package:
        executable = package.read('caddy.exe')
        if (len(executable) != manifest['executable_bytes']
                or hashlib.sha256(executable).hexdigest() != manifest['executable_sha256']):
            raise RuntimeError('Caddy executable checksum mismatch.')
        payload = {'caddy.exe': executable, 'LICENSE': package.read('LICENSE'), 'README.md': package.read('README.md')}
    for name, content in payload.items():
        target = destination / name
        if target.exists():
            if target.read_bytes() != content:
                raise RuntimeError('Existing Caddy file was preserved: ' + name)
            continue
        with tempfile.NamedTemporaryFile(dir=destination, prefix='.caddy-', delete=False) as temporary:
            stage = Path(temporary.name)
            temporary.write(content)
        try:
            stage.replace(target)
        finally:
            stage.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ensure', action='store_true')
    group.add_argument('--check', action='store_true')
    parser.add_argument('--destination', type=Path, default=ROOT / 'bin' / 'caddy')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'installer/caddy-manifest.json').read_text(encoding='utf-8'))
    if args.ensure:
        install(args.destination, manifest, ROOT / '.downloads' / f"caddy_{manifest['version']}_windows_amd64.zip")
    if not verified(args.destination, manifest):
        raise RuntimeError('The pinned Caddy binary is missing or changed. Run the installer with --ensure.')
    print('Caddy ' + manifest['version'] + ' verified.')


if __name__ == '__main__':
    main()
