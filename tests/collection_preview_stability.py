"""Regression checks for preview process ownership and queue retries."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collection_preview import (
    MAX_ATTEMPTS, STALE_STAGE_SECONDS, missing_previews, revision_for,
)
import collection_preview_renderer as renderer


DELEGATE = """
import subprocess
import sys

subprocess.Popen([sys.executable, '-I', '-S', '-c', sys.argv[1], sys.argv[2]])
"""
DESCENDANT = """
import os
from pathlib import Path
import sys
import time

Path(sys.argv[1]).write_text(str(os.getpid()))
time.sleep(45)
"""


def delegated_command(pid_path):
    return [sys.executable, '-I', '-S', '-c', DELEGATE, DESCENDANT, str(pid_path)]


def wait_pid(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            return int(path.read_text())
        except (OSError, ValueError):
            time.sleep(.025)
    raise RuntimeError('The test child did not report its PID.')


def write_glb(path):
    points = [-1, 0, -1, 1, 0, -1, 0, 0, 1, 0, 2, 0]
    faces = [0, 1, 2, 0, 3, 1, 1, 3, 2, 2, 3, 0]
    binary = struct.pack('<12f12H', *points, *faces)
    document = {
        'asset': {'version': '2.0'},
        'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': 48, 'target': 34962},
            {'buffer': 0, 'byteOffset': 48, 'byteLength': 24, 'target': 34963},
        ],
        'accessors': [
            {'bufferView': 0, 'componentType': 5126, 'count': 4, 'type': 'VEC3',
             'min': [-1, 0, -1], 'max': [1, 2, 1]},
            {'bufferView': 1, 'componentType': 5123, 'count': 12, 'type': 'SCALAR'},
        ],
    }
    payload = json.dumps(document).encode()
    payload += b' ' * (-len(payload) % 4)
    chunks = (struct.pack('<I4s', len(payload), b'JSON') + payload
              + struct.pack('<I4s', len(binary), b'BIN\0') + binary)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks)


class PreviewQueue(unittest.TestCase):
    def test_limits_retries_and_prunes_only_owned_staging_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output, trash, cache = (root / name for name in ('output', 'trash', 'previews'))
            folder = output / ('a' * 32)
            folder.mkdir(parents=True)
            cache.mkdir()
            (folder / 'model.glb').write_bytes(b'source')
            (folder / 'status.json').write_text('{"state":"done"}')
            revision = revision_for(folder)
            workspace = [('local', output, trash, cache)]
            cutoff = time.time() - STALE_STAGE_SECONDS - 60
            stale = cache / 'preview-expired.tmp'
            other = cache / 'other.tmp'
            fresh = cache / 'preview-fresh.tmp'
            for file in (stale, other, fresh):
                file.write_bytes(b'data')
            for file in (stale, other):
                os.utime(file, (cutoff, cutoff))

            self.assertFalse(list(missing_previews(workspace, {folder: (revision, 1, time.monotonic() + 60)})))
            self.assertFalse(list(missing_previews(workspace, {folder: (revision, MAX_ATTEMPTS, 0)})))
            self.assertEqual(len(list(missing_previews(workspace, {folder: (revision, 1, 0)}))), 1)
            self.assertEqual(len(list(missing_previews(workspace, {folder: ('older', MAX_ATTEMPTS, 0)}))), 1)
            self.assertFalse(stale.exists())
            self.assertTrue(other.exists())
            self.assertTrue(fresh.exists())
            self.assertEqual((folder / 'model.glb').read_bytes(), b'source')


@unittest.skipUnless(os.name == 'nt', 'Windows Job Objects')
class WindowsPreviewJob(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, result, arguments in (
            ('OpenProcess', wintypes.HANDLE, (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)),
            ('WaitForSingleObject', wintypes.DWORD, (wintypes.HANDLE, wintypes.DWORD)),
            ('CloseHandle', wintypes.BOOL, (wintypes.HANDLE,)),
        ):
            function = getattr(self.kernel, name)
            function.restype = result
            function.argtypes = arguments

    def descendant_handle(self, path):
        handle = self.kernel.OpenProcess(0x00100000, False, wait_pid(path))  # SYNCHRONIZE
        self.assertTrue(handle)
        self.addCleanup(self.kernel.CloseHandle, handle)
        return handle

    def test_delegated_browser_is_owned_after_bootstrap_exits(self):
        pid_path = self.root / 'child.pid'
        sibling = subprocess.Popen(
            [sys.executable, '-I', '-S', '-c', 'import time; time.sleep(40)'],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            job = renderer._WindowsBrowserJob(delegated_command(pid_path))
            try:
                handle = self.descendant_handle(pid_path)
                self.assertEqual(job.process.wait(timeout=10), 0)
                self.assertIsNone(job.poll())
            finally:
                job.close()
            self.assertEqual(self.kernel.WaitForSingleObject(handle, 3000), 0)
            self.assertIsNone(sibling.poll())
        finally:
            sibling.kill()
            sibling.wait(timeout=5)

    def test_close_on_studio_process_exit(self):
        pid_path = self.root / 'child.pid'
        parent = subprocess.Popen(
            [sys.executable, '-B', '-c',
             'import sys, time; from collection_preview_renderer import _WindowsBrowserJob; '
             'job = _WindowsBrowserJob(sys.argv[1:]); time.sleep(40)',
             *delegated_command(pid_path)],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            handle = self.descendant_handle(pid_path)
        finally:
            parent.kill()
            parent.wait(timeout=5)
        self.assertEqual(self.kernel.WaitForSingleObject(handle, 3000), 0)

    def test_render_timeout_and_cancellation_close_the_process_tree(self):
        glb = self.root / 'test.glb'
        write_glb(glb)
        real_job = renderer._WindowsBrowserJob
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                pid_path = self.root / f'{cancelled}.pid'
                handles = []
                event = threading.Event()

                def launch(_command):
                    job = real_job(delegated_command(pid_path))
                    try:
                        handles.append(self.descendant_handle(pid_path))
                        job.process.wait(timeout=10)
                        if cancelled:
                            event.set()
                        return job
                    except BaseException:
                        job.close()
                        raise

                with (patch.object(renderer, '_WindowsBrowserJob', side_effect=launch),
                      patch.object(renderer, '_find_browser', return_value=Path(sys.executable)),
                      patch.object(renderer, 'TIMEOUT_SECONDS', .1)):
                    with self.assertRaisesRegex(RuntimeError, 'cancelled' if cancelled else 'timed out'):
                        renderer.render_collection_preview(glb, cancel=event)
                self.assertEqual(self.kernel.WaitForSingleObject(handles[0], 3000), 0)


@unittest.skipUnless(os.environ.get('TRELLIS_TEST_PREVIEW_BROWSER') == '1', 'Optional real browser test')
class RealPreviewBrowser(unittest.TestCase):
    def test_twenty_previews(self):
        with tempfile.TemporaryDirectory() as directory:
            glb = Path(directory) / 'test.glb'
            write_glb(glb)
            for iteration in range(20):
                with self.subTest(iteration=iteration):
                    textured, clay = renderer.render_collection_preview(glb)
                    self.assertEqual(textured[8:12], b'WEBP')
                    self.assertEqual(clay[8:12], b'WEBP')


if __name__ == '__main__':
    unittest.main()
