"""Render matching Collection thumbnails in an isolated local Chromium process."""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import threading
import time

from PIL import Image

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
    if process.poll() is not None:
        return
    if os.name == 'nt':
        try:
            taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
            subprocess.run(
                [str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=3)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=3)
        except ProcessLookupError:
            process.wait(timeout=2)


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
    with tempfile.TemporaryDirectory(prefix='trellis-preview-', ignore_cleanup_errors=True) as profile:
        with _thumbnail_server(glb, token, results, finished) as server:
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
            worker.start()
            process = None
            try:
                options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
                process = subprocess.Popen([
                    str(browser), '--headless=new', f'--user-data-dir={profile}',
                    '--no-first-run', '--no-default-browser-check', '--no-proxy-server',
                    '--disable-background-networking', '--disable-component-update', '--disable-default-apps',
                    '--disable-extensions', '--disable-sync', '--disable-breakpad',
                    '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                    f'http://127.0.0.1:{server.server_port}/{token}/',
                ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
                deadline = time.monotonic() + TIMEOUT_SECONDS
                while not finished.wait(.15):
                    if cancel and cancel.is_set():
                        raise RuntimeError('Collection preview cancelled.')
                    if process.poll() is not None:
                        raise RuntimeError(f'The Collection preview browser exited ({process.returncode}).')
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
