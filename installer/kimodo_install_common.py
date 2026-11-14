"""Verified downloads and guarded extraction for the optional CPU motion installer."""
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import tarfile
import time
import urllib.request
import uuid
import zipfile


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            value.update(block)
    return value.hexdigest()


def manifest_digest(value):
    """Stable across Git line-ending conversion and JSON formatting changes."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()


def verified(path, entry):
    return (Path(path).is_file() and not Path(path).is_symlink()
            and Path(path).stat().st_size == entry['bytes'] and sha256(path) == entry['sha256'])


def child(root, relative):
    name = PurePosixPath(relative)
    if not relative or name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe installation path.')
    root = Path(root).resolve()
    path = root.joinpath(*name.parts)
    if not path.resolve().is_relative_to(root) or path.is_symlink():
        raise ValueError('Installation paths must stay inside the selected directory.')
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Installation paths cannot traverse symbolic links.')
    return path


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Unsafe installation lock.')
    with path.open('a+b') as stream:
        if not path.stat().st_size:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError('Another installation is using this directory. Retry after it finishes.') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _fetch_once(entry, cache, reuse=None, opener=urllib.request.urlopen):
    """Resume only an exact byte range, then verify the full pinned size and digest."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    target = child(cache, entry['sha256'] + '-' + entry['filename'])
    with lock(target.with_suffix(target.suffix + '.lock')):
        if verified(target, entry):
            print('Verified cache: ' + entry['filename'], flush=True)
            return target
        if target.exists():
            raise RuntimeError('A completed cache file was modified and was preserved: ' + entry['filename'])
        partial = target.with_suffix(target.suffix + '.partial')
        if partial.is_symlink():
            raise ValueError('Unsafe partial download path.')
        if reuse:
            for relative in dict.fromkeys([target.name, entry['filename'], *entry.get('cache_candidates', [])]):
                candidate = child(reuse, relative)
                if verified(candidate, entry):
                    with candidate.open('rb') as incoming, partial.open('wb') as outgoing:
                        shutil.copyfileobj(incoming, outgoing, 8 * 1024**2)
                    break
        if partial.exists() and (partial.stat().st_size > entry['bytes'] or
                                 partial.stat().st_size == entry['bytes'] and not verified(partial, entry)):
            partial.rename(partial.with_name(partial.name + '.invalid-' + uuid.uuid4().hex))
        start = partial.stat().st_size if partial.exists() else 0
        if start < entry['bytes']:
            if not entry['url'].startswith('https://'):
                raise ValueError('Pinned downloads must use HTTPS.')
            headers = {'User-Agent': 'TRELLIS-Studio-Installer/3.4', 'Accept-Encoding': 'identity'}
            if start:
                headers['Range'] = f'bytes={start}-'
            request = urllib.request.Request(entry['url'], headers=headers)
            with opener(request, timeout=120) as response:
                status = response.status
                if status == 206:
                    expected = f'bytes {start}-{entry["bytes"] - 1}/{entry["bytes"]}'
                    if response.headers.get('Content-Range') != expected:
                        raise RuntimeError('The download server returned an unexpected byte range.')
                elif status == 200:
                    start = 0
                else:
                    raise RuntimeError('The download server did not return a complete or resumable response.')
                length = response.headers.get('Content-Length')
                if length and int(length) != entry['bytes'] - start:
                    raise RuntimeError('The download size differs from the pinned manifest.')
                total = start
                last = 0.0
                with partial.open('ab' if start else 'wb') as stream:
                    while True:
                        block = response.read(8 * 1024**2)
                        if not block:
                            break
                        total += len(block)
                        if total > entry['bytes']:
                            raise RuntimeError('The download exceeded its pinned size.')
                        stream.write(block)
                        if time.monotonic() - last > 10:
                            print(f'Downloading {entry["filename"]}: {total / 1024**2:.0f}/{entry["bytes"] / 1024**2:.0f} MiB', flush=True)
                            last = time.monotonic()
        if not verified(partial, entry):
            if partial.exists() and partial.stat().st_size == entry['bytes']:
                partial.rename(partial.with_name(partial.name + '.invalid-' + uuid.uuid4().hex))
            raise RuntimeError('Download verification failed; the partial file is preserved: ' + entry['filename'])
        partial.replace(target)
        return target


def fetch(entry, cache, reuse=None, opener=urllib.request.urlopen):
    import urllib.error
    for attempt in range(3):
        try:
            return _fetch_once(entry, cache, reuse, opener)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == 2:
                raise RuntimeError('Download interrupted after three attempts; retry to resume: ' + entry['filename']) from error
            time.sleep(2 * (attempt + 1))
            print('Connection interrupted; resuming ' + entry['filename'], flush=True)


def tree_inventory(root):
    result = {}
    for path in Path(root).rglob('*'):
        if path.name in ('.archive-sha256', '.archive-files.json'):
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = {'link': os.readlink(path)}
        elif path.is_file():
            result[relative] = {'sha256': sha256(path)}
    return result


def extract(archive, destination, entry):
    """Extract under one new directory; defer safe links until regular files are written."""
    destination = Path(destination)
    marker = destination / '.archive-sha256'
    if marker.is_file() and marker.read_text() == entry['sha256']:
        inventory = destination / '.archive-files.json'
        if not inventory.is_file() or json.loads(inventory.read_text()) != tree_inventory(destination):
            raise RuntimeError('Extracted sources or tools were modified and were preserved: ' + destination.name)
        return
    if destination.exists():
        raise RuntimeError('An unrecognized source/tool directory was preserved: ' + destination.name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name('.extract-' + uuid.uuid4().hex)
    stage.mkdir()
    package = zipfile.ZipFile(archive) if entry['kind'] == 'zip' else tarfile.open(archive)
    try:
        members = package.infolist() if entry['kind'] == 'zip' else package.getmembers()
        if len(members) > 100000:
            raise ValueError('Archive has too many entries.')
        seen = set()
        links = []
        total = 0
        for member in members:
            name = member.filename if entry['kind'] == 'zip' else member.name
            parts = PurePosixPath(name).parts
            if name.startswith('/') or '..' in parts or '\\' in name or ':' in name:
                raise ValueError('Unsafe archive entry.')
            if entry.get('strip_root'):
                parts = parts[1:]
            if not parts:
                continue
            relative = '/'.join(parts)
            path = child(stage, relative)
            directory = member.is_dir() if entry['kind'] == 'zip' else member.isdir()
            if directory:
                path.mkdir(parents=True, exist_ok=True)
                continue
            if relative in seen:
                raise ValueError('Duplicate archive entry.')
            seen.add(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = member.external_attr >> 16 if entry['kind'] == 'zip' else member.mode
            islink = stat.S_ISLNK(mode) if entry['kind'] == 'zip' else member.issym()
            if islink:
                if entry['kind'] == 'zip' and member.file_size > 4096:
                    raise ValueError('Archive link is too large.')
                target = package.read(member).decode() if entry['kind'] == 'zip' else member.linkname
                if PurePosixPath(target).is_absolute() or not (path.parent / target).resolve().is_relative_to(stage.resolve()):
                    raise ValueError('Unsafe archive link.')
                links.append((path, target))
                continue
            if entry['kind'] != 'zip' and not member.isfile():
                raise ValueError('Special archive entries are not supported.')
            total += member.file_size if entry['kind'] == 'zip' else member.size
            if total > 2 * 1024**3:
                raise ValueError('Archive exceeds the expanded size limit.')
            incoming = package.open(member) if entry['kind'] == 'zip' else package.extractfile(member)
            with incoming, path.open('xb') as stream:
                shutil.copyfileobj(incoming, stream, 1024**2)
            path.chmod(0o755 if mode & 0o111 else 0o644)
        for path, target in links:
            path.symlink_to(target)
        atomic_json(stage / '.archive-files.json', tree_inventory(stage))
        (stage / '.archive-sha256').write_text(entry['sha256'])
        stage.rename(destination)
    finally:
        package.close()
        if stage.exists():
            assert stage.parent.resolve() == destination.parent.resolve() and stage.name.startswith('.extract-')
            shutil.rmtree(stage)
