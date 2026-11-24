"""Render matching Collection thumbnails in an isolated local Chromium process."""

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from PIL import Image

def _preview_locked(stream, acquire):
    stream.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK if acquire else msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB if acquire else fcntl.LOCK_UN)


def _profile_root():
    return Path(tempfile.gettempdir()).resolve()/'trellis-collection-previews-v1'


def cleanup_orphan_profiles():
    from studio_transfer import staging_directory
    import psutil
    root=_profile_root()
    if staging_directory(root)!=root:return
    for folder in root.glob('preview-*'):
        lease=folder/'.trellis-profile'
        if staging_directory(folder)!=folder or lease.resolve()!=lease or not lease.is_file():continue
        try:
            with lease.open('r+b') as stream:
                if stream.read(64)!=b'TRELLIS-collection-preview-v1':continue
                _preview_locked(stream,True)
                try:
                    flag='--user-data-dir='+str(folder/'browser')
                    active=any(flag in (process.info['cmdline'] or ()) for process in psutil.process_iter(['cmdline']))
                finally:
                    _preview_locked(stream,False)
            if not active:shutil.rmtree(folder)
        except (OSError,psutil.Error):continue


@contextmanager
def _preview_profile():
    from studio_transfer import staging_directory
    root=_profile_root()
    root.mkdir(exist_ok=True)
    if staging_directory(root)!=root:raise ValueError('Invalid preview cache directory.')
    with tempfile.TemporaryDirectory(prefix='preview-',dir=root,ignore_cleanup_errors=True) as temporary:
        folder=Path(temporary)
        with (folder/'.trellis-profile').open('x+b') as stream:
            stream.write(b'\0')
            stream.flush()
            _preview_locked(stream,True)
            try:
                stream.seek(0)
                stream.write(b'TRELLIS-collection-preview-v1')
                stream.flush()
                yield folder/'browser'
            finally:_preview_locked(stream,False)

ROOT = Path(__file__).resolve().parent
THREE = ROOT / 'node_modules' / 'three'
MODULES = {'collection-preview-render.js', 'collection-preview-capture.js'}
IMAGE_SIZE = (384, 310)
TIMEOUT_SECONDS = 50
MAX_IMAGE_BYTES = 1_000_000
IMPORT_MAP = '{"imports":{"three":"./vendor/build/three.module.js","three/addons/":"./vendor/examples/jsm/"}}'
IMPORT_HASH = base64.b64encode(hashlib.sha256(IMPORT_MAP.encode()).digest()).decode()
HTML = f'''<!doctype html>
<meta charset="utf-8">
<script type="importmap">{IMPORT_MAP}</script>
<script type="module" src="./collection-preview-render.js"></script>
'''.encode()
CSP = (
    f"default-src 'none'; script-src 'self' 'sha256-{IMPORT_HASH}'; "
    "img-src 'self' blob: data:; connect-src 'self' blob: data:; "
    "base-uri 'none'; frame-ancestors 'none'"
)
_JOB_BASIC_ACCOUNTING = 1
_JOB_EXTENDED_LIMIT = 9
_JOB_KILL_ON_CLOSE = 0x2000
_PROCESS_ASSIGN_ACCESS = 0x0100 | 0x0001  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
# Wait for job assignment before launching Chromium. The pipe closes without a
# permit if Studio exits during startup.
_JOB_LAUNCHER = """\
import subprocess
import sys

if sys.stdin.buffer.read(1) != b'1':
    sys.exit(1)
sys.exit(subprocess.call(sys.argv[1:]))
"""


class _JobBasicLimits(ctypes.Structure):
    _fields_ = [
        ('per_process_time', ctypes.c_int64), ('per_job_time', ctypes.c_int64),
        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
        ('max_working_set', ctypes.c_size_t), ('active_process_limit', wintypes.DWORD),
        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
        ('scheduling_class', wintypes.DWORD),
    ]


class _JobExtendedLimits(ctypes.Structure):
    _fields_ = [
        ('basic', _JobBasicLimits), ('io_counters', ctypes.c_uint64 * 6),
        ('process_memory_limit', ctypes.c_size_t), ('job_memory_limit', ctypes.c_size_t),
        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t),
    ]


class _JobAccounting(ctypes.Structure):
    _fields_ = [
        ('total_user_time', ctypes.c_int64), ('total_kernel_time', ctypes.c_int64),
        ('period_user_time', ctypes.c_int64), ('period_kernel_time', ctypes.c_int64),
        ('page_faults', wintypes.DWORD), ('total_processes', wintypes.DWORD),
        ('active_processes', wintypes.DWORD), ('terminated_processes', wintypes.DWORD),
    ]


class _WindowsBrowserJob:
    """Keep all descendants in a disposable job owned by Studio."""

    def __init__(self, command):
        kernel = self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        handle = wintypes.HANDLE
        dword = wintypes.DWORD
        for name, result, arguments in (
            ('CreateJobObjectW', handle, (ctypes.c_void_p, wintypes.LPCWSTR)),
            ('SetInformationJobObject', wintypes.BOOL, (handle, ctypes.c_int, ctypes.c_void_p, dword)),
            ('QueryInformationJobObject', wintypes.BOOL,
             (handle, ctypes.c_int, ctypes.c_void_p, dword, ctypes.POINTER(dword))),
            ('OpenProcess', handle, (dword, wintypes.BOOL, dword)),
            ('AssignProcessToJobObject', wintypes.BOOL, (handle, handle)),
            ('TerminateJobObject', wintypes.BOOL, (handle, wintypes.UINT)),
            ('CloseHandle', wintypes.BOOL, (handle,)),
        ):
            function = getattr(kernel, name)
            function.restype = result
            function.argtypes = arguments

        self.job = kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise ctypes.WinError(ctypes.get_last_error())
        self.process = None
        try:
            limits = _JobExtendedLimits()
            limits.basic.flags = _JOB_KILL_ON_CLOSE
            if not kernel.SetInformationJobObject(
                self.job, _JOB_EXTENDED_LIMIT, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            self.process = subprocess.Popen(
                [sys.executable, '-I', '-S', '-c', _JOB_LAUNCHER, *command],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW, bufsize=0,
            )
            with self.process.stdin as permit:
                process_handle = kernel.OpenProcess(_PROCESS_ASSIGN_ACCESS, False, self.process.pid)
                if not process_handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if not kernel.AssignProcessToJobObject(self.job, process_handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    kernel.CloseHandle(process_handle)
                permit.write(b'1')
        except BaseException:
            self.close()
            raise

    def _active_processes(self):
        accounting = _JobAccounting()
        if not self.kernel.QueryInformationJobObject(
            self.job, _JOB_BASIC_ACCOUNTING, ctypes.byref(accounting), ctypes.sizeof(accounting), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return accounting.active_processes

    def poll(self):
        code = self.process.poll()
        # Chromium on Windows can hand off to another process and exit cleanly.
        return code if code is not None and self._active_processes() == 0 else None

    def close(self):
        try:
            if self.kernel.TerminateJobObject(self.job, 1):
                deadline = time.monotonic() + 3
                while self._active_processes() and time.monotonic() < deadline:
                    time.sleep(.025)
        finally:
            self.kernel.CloseHandle(self.job)
            if self.process is not None:
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)


def _find_browser():
    configured = os.environ.get('TRELLIS_PREVIEW_BROWSER')
    if configured:
        path = Path(configured)
        return path.resolve() if path.is_file() else None
    for name in ('msedge', 'chrome', 'chromium', 'chromium-browser', 'google-chrome'):
        path = shutil.which(name)
        if path:
            return Path(path)
    if os.name == 'nt':
        for root in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            directory = os.environ.get(root)
            if not directory:
                continue
            for browser in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
                path = Path(directory) / browser
                if path.is_file():
                    return path
    return None


def collection_preview_renderer_available():
    return bool(_find_browser() and (THREE / 'build' / 'three.module.js').is_file())


def _stop_browser(process):
    if os.name == 'nt':
        process.close()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=2)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def _thumbnail_server(source, token, results, finished):
    class RendererHandler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(8)

        def _path(self):
            prefix = f'/{token}/'
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}' or not self.path.startswith(prefix):
                return None
            return self.path[len(prefix):]

        def _start(self, status, content_type, length):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(length))
            self.send_header('Content-Security-Policy', CSP)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()

        def do_GET(self):
            path = self._path()
            if path == '':
                self._start(200, 'text/html; charset=utf-8', len(HTML))
                self.wfile.write(HTML)
                return
            if path == 'model.glb':
                file, mime = source, 'model/gltf-binary'
            elif path in MODULES:
                file, mime = ROOT / 'web' / path, 'text/javascript'
            elif path and path.startswith('vendor/') and path.endswith('.js'):
                file = (THREE / path.removeprefix('vendor/')).resolve()
                if not file.is_relative_to(THREE.resolve()):
                    self.send_error(404)
                    return
                mime = 'text/javascript'
            else:
                self.send_error(404)
                return
            try:
                stream = file.open('rb')
            except OSError:
                self.send_error(404)
                return
            with stream:
                try:
                    self._start(200, mime, os.fstat(stream.fileno()).st_size)
                    shutil.copyfileobj(stream, self.wfile, length=128 * 1024)
                except (ConnectionError, TimeoutError):
                    pass

        def do_POST(self):
            path = self._path()
            if path not in ('result/textured', 'result/clay', 'result/error'):
                self.send_error(404)
                return
            name = path.removeprefix('result/')
            try:
                size = int(self.headers.get('Content-Length', '0'))
                limit = 4_000 if name == 'error' else MAX_IMAGE_BYTES
                if not 0 < size <= limit:
                    raise ValueError
                payload = self.rfile.read(size)
                if len(payload) != size:
                    raise ValueError
                if name != 'error':
                    with Image.open(BytesIO(payload), formats=('WEBP',)) as image:
                        if image.size != IMAGE_SIZE:
                            raise ValueError
                        image.verify()
            except (OSError, ValueError):
                self.send_error(400)
                return
            results[name] = payload
            try:
                self._start(204, 'text/plain', 0)
            finally:
                if name == 'error' or ('textured' in results and 'clay' in results):
                    finished.set()

    return ThreadingHTTPServer(('127.0.0.1', 0), RendererHandler)


def render_collection_preview(glb: Path, *, cancel: threading.Event | None = None) -> tuple[bytes, bytes]:
    """Return the textured and clay WebP bytes for one self-contained GLB."""
    browser = _find_browser()
    if not browser:
        raise RuntimeError('A local Chromium browser (Edge or Chrome) is required for Collection previews.')
    if not (THREE / 'build' / 'three.module.js').is_file():
        raise RuntimeError('The installed Three.js preview renderer is unavailable.')
    glb = glb.resolve(strict=True)
    with glb.open('rb') as stream:
        if stream.read(8) != b'glTF\x02\x00\x00\x00':
            raise ValueError('Collection previews require a glTF 2.0 GLB.')
    if cancel and cancel.is_set():
        raise RuntimeError('Collection preview cancelled.')

    token = secrets.token_urlsafe(24)
    results = {}
    finished = threading.Event()
    with _preview_profile() as profile:
        with _thumbnail_server(glb, token, results, finished) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
            worker.start()
            process = None
            try:
                command = [
                    str(browser), '--headless=new', f'--user-data-dir={profile}',
                    '--no-first-run', '--no-default-browser-check', '--no-proxy-server',
                    '--disable-background-networking', '--disable-component-update', '--disable-default-apps',
                    '--disable-extensions', '--disable-sync', '--disable-breakpad',
                    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                    f'http://127.0.0.1:{server.server_port}/{token}/',
                ]
                if os.name == 'nt':
                    process = _WindowsBrowserJob(command)
                else:
                    process = subprocess.Popen(
                        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=True,
                    )
                deadline = time.monotonic() + TIMEOUT_SECONDS
                while not finished.wait(.15):
                    if cancel and cancel.is_set():
                        raise RuntimeError('Collection preview cancelled.')
                    code = process.poll()
                    if code is not None:
                        raise RuntimeError(f'The Collection preview browser exited ({code}).')
                    if time.monotonic() >= deadline:
                        raise RuntimeError('The Collection preview render timed out.')
                if 'error' in results:
                    raise RuntimeError(results['error'].decode('utf-8', 'replace'))
                return results['textured'], results['clay']
            finally:
                try:
                    if process:
                        _stop_browser(process)
                finally:
                    server.shutdown()
                    worker.join()
