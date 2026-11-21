"""Persistent clay and textured Collection thumbnails, derived from published GLBs."""

import asyncio
from io import BytesIO
import logging
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from threading import Event
import time
from zipfile import BadZipFile, ZipFile

from studio_workspace import ID, read


LOG = logging.getLogger('trellis.collection')
MODES = ('textured', 'clay')
RECIPE = 'v1'
ARCHIVE = re.compile(r'[a-f0-9]{32}-v[0-9]+-[a-f0-9]+-[a-f0-9]+\.zip')
MAX_WEBP_BYTES = 512 * 1024


def revision_for(folder):
    source = folder / 'model.glb'
    try:
        if folder.resolve() != folder or source.is_symlink():
            return None
        info = source.stat()
        if info.st_size > 0 and source.is_file():
            return f'{RECIPE}-{info.st_mtime_ns:x}-{info.st_size:x}'
    except OSError:
        pass
    return None


def archive_path(cache, folder, revision):
    return cache / f'{folder.name}-{revision}.zip'


def published(folder):
    try:
        return (read(folder / 'status.json', {}) or {}).get('state') == 'done'
    except (OSError, ValueError, AttributeError):
        return False


def preview_record(cache, folder):
    revision = revision_for(folder)
    if revision and archive_path(cache, folder, revision).is_file():
        prefix = f'/api/jobs/{folder.name}/collection-preview/{revision}'
        return {mode + '_url': f'{prefix}/{mode}.webp' for mode in MODES}
    return None


def preview_image(cache, folder, revision, mode):
    if mode not in MODES or revision_for(folder) != revision or not published(folder):
        return None
    try:
        path = archive_path(cache, folder, revision)
        if path.resolve() != path:
            return None
        with ZipFile(path) as archive:
            filename = mode + '.webp'
            if 0 < archive.getinfo(filename).file_size <= MAX_WEBP_BYTES:
                return archive.read(filename)
    except (OSError, ValueError, BadZipFile, KeyError):
        pass
    return None


def preview_archive(images):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for mode, image in zip(MODES, images, strict=True):
            if not (12 < len(image) <= MAX_WEBP_BYTES and image[:4] == b'RIFF' and image[8:12] == b'WEBP'):
                raise ValueError('Invalid WebP collection preview.')
            archive.writestr(mode + '.webp', image)
    return output.getvalue()


def save_preview(cache, folder, revision, content):
    if revision_for(folder) != revision or not published(folder):
        return False
    if cache.resolve() != cache:
        raise ValueError('Invalid collection preview storage.')
    cache.mkdir(parents=True, exist_ok=True)
    target = archive_path(cache, folder, revision)
    with NamedTemporaryFile(dir=cache, suffix='.tmp', delete=False) as output:
        staged = Path(output.name)
        try:
            output.write(content)
            output.close()
            staged.replace(target)
        finally:
            staged.unlink(missing_ok=True)
    for previous in cache.glob(f'{folder.name}-*.zip'):
        if previous != target and ARCHIVE.fullmatch(previous.name):
            try:
                previous.unlink()
            except OSError:
                pass  # A browser can be reading the previous revision.
    return True


def missing_previews(workspaces, failed):
    for owner, outputs, trash, cache in workspaces:
        if cache.resolve() != cache:
            continue
        for path in cache.glob('*.zip'):
            identifier = path.name[:32]
            if ARCHIVE.fullmatch(path.name) and not (outputs / identifier).exists() and not (trash / identifier).exists():
                try:
                    path.unlink()
                except OSError:
                    pass
        if not outputs.is_dir():
            continue
        for folder in outputs.iterdir():
            if not ID.fullmatch(folder.name):
                continue
            revision = revision_for(folder)
            last_revision, retry_at = failed.get(folder, (None, 0))
            if (revision and (revision != last_revision or time.monotonic() >= retry_at)
                    and not archive_path(cache, folder, revision).is_file() and published(folder)):
                yield owner, cache, folder, revision


class CollectionPreviews:
    """Run one disposable renderer at a time, only while the Studio is idle."""

    def __init__(self, workspaces, busy, pending, publish=None):
        self.workspaces = workspaces
        self.busy = busy
        self.pending = pending
        self.publish = publish
        self.task = None
        self.cancel = Event()

    def start(self):
        from collection_preview_renderer import collection_preview_renderer_available

        if collection_preview_renderer_available():
            self.task = asyncio.create_task(self.run())

    async def close(self):
        self.cancel.set()
        if self.task:
            await self.task

    async def render(self, folder):
        from collection_preview_renderer import render_collection_preview

        render_cancel = Event()
        render = asyncio.create_task(asyncio.to_thread(render_collection_preview, folder / 'model.glb', cancel=render_cancel))
        while not render.done():
            await asyncio.wait({render}, timeout=0.25)
            if self.cancel.is_set() or self.busy():
                render_cancel.set()
        if render_cancel.is_set():
            await asyncio.gather(render, return_exceptions=True)
            return None
        return preview_archive(render.result())

    async def run(self):
        failed = {}
        delay = 0.25
        while not self.cancel.is_set():
            await asyncio.sleep(delay)
            delay = 2
            if self.cancel.is_set() or self.busy():
                continue
            try:
                candidates = await asyncio.to_thread(lambda: list(missing_previews(self.workspaces(), failed)))
                ordered = sorted(candidates, key=lambda item: int(item[3].split('-')[1], 16), reverse=True)
                candidate = next((item for item in ordered if not self.pending(item[0], item[2].name)), None)
            except (OSError, ValueError):
                LOG.exception('Could not scan the Collection for missing previews.')
                delay = 20
                continue
            if not candidate or self.busy():
                continue
            owner, cache, folder, revision = candidate
            try:
                content = await self.render(folder)
                if content is None:
                    continue
                saved = (save_preview(cache, folder, revision, content) if self.publish is None
                         else await self.publish(owner, cache, folder, revision, content))
                if not saved:
                    failed[folder] = (revision, time.monotonic() + 300)
                else:
                    failed.pop(folder, None)
            except (OSError, RuntimeError, ValueError):
                LOG.exception('Could not save the Collection preview for %s.', folder.name)
                failed[folder] = (revision, time.monotonic() + 300)
            delay = 0.25
