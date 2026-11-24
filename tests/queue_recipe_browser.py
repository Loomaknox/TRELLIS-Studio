"""Run the queue and preflight checks in disposable Windows browser jobs."""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory, TemporaryFile
from threading import Event, Thread
from time import monotonic
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collection_preview_renderer import _find_browser, _WindowsBrowserJob

PAGE = b"""<!doctype html><meta charset="utf-8">
<span id="queueCount"></span><select id="assetType">
<option value="object">Objet</option><option value="humanoid">Humanoide</option></select>
<script type="module">
const report = body => fetch('/result', {method:'POST',body});
try {
  const {run} = await import('/tests/queue_recipe_browser.js');
  await run();
  await report('PASS');
} catch (error) {
  await report(String(error.stack || error));
}
</script>"""


class FixtureServer(ThreadingHTTPServer):
    request_queue_size = 32


def browser_candidates():
    first = _find_browser()
    if os.environ.get('TRELLIS_PREVIEW_BROWSER'):
        return [first] if first else []
    # Prefer native installations over command-line shims on hosted Windows.
    candidates = []
    for base in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        if os.environ.get(base):
            for exe in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe'):
                path = Path(os.environ[base]) / exe
                if path.is_file():
                    candidates.append(path.resolve())
    if first:
        candidates.append(first.resolve())
    return list(dict.fromkeys(candidates))


def check_browser(browser, language, profile):
    done = Event()
    navigated = Event()
    results = []
    requests = deque(maxlen=40)

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/':
                navigated.set()
                data, mime = PAGE, 'text/html; charset=utf-8'
            elif path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            else:
                file = (ROOT / path.lstrip('/')).resolve()
                if (file.parent != ROOT / 'web' and file != ROOT / 'tests/queue_recipe_browser.js') or not file.is_file():
                    requests.append('404 '+path)
                    self.send_error(404)
                    return
                data = file.read_bytes()
                mime = 'text/javascript; charset=utf-8' if file.suffix == '.js' else 'image/svg+xml'
            requests.append('200 '+path)
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != '/result':
                self.send_error(404)
                return
            results.append(self.rfile.read(min(int(self.headers['Content-Length']), 8192)).decode())
            self.send_response(204)
            self.end_headers()
            done.set()

    with FixtureServer(('127.0.0.1', 0), Fixture) as server, TemporaryFile() as console:
        address = f'http://127.0.0.1:{server.server_port}/?lang={language}'
        print(f'Queue fixture ({language}): {browser.name} on local port {server.server_port}', flush=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            job = _WindowsBrowserJob([str(browser), '--headless=new', '--disable-gpu', '--disable-extensions',
                '--no-proxy-server', '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
                '--enable-logging=stderr', '--window-size=1280,900', '--force-device-scale-factor=2',
                '--user-data-dir=' + str(profile), address], stderr=console)
            try:
                deadline = monotonic() + 60
                while not done.wait(.25):
                    code = job.poll()
                    if code is not None or monotonic() >= deadline:
                        outcome = 'timed out' if code is None else f'exited with code {code}'
                        break
                else:
                    if results != ['PASS']:
                        raise AssertionError(f'{browser.name} ({language}): {results}. Requests: {list(requests)}')
                    return
            finally:
                job.close()
        finally:
            server.shutdown()
            thread.join(5)
        console.seek(max(console.seek(0, 2)-4096, 0))
        detail = console.read().decode('utf-8', 'replace').strip()
        message = f'{browser.name} ({language}) {outcome}. Requests: {list(requests)}. Browser stderr: {detail}'
        if not navigated.is_set():
            raise ConnectionError(message)
        raise AssertionError(message)


def main():
    browsers = browser_candidates()
    assert browsers, 'Install Edge or Chrome for this regression.'
    with TemporaryDirectory(prefix='trellis-queue-browser-') as tmp:
        for lang in ('fr', 'en'):
            for index, browser in enumerate(browsers):
                try:
                    check_browser(browser, lang, Path(tmp)/f'{lang}-{index}')
                except ConnectionError as error:
                    print(error, file=sys.stderr, flush=True)
                    if index+1 == len(browsers):
                        raise
                else:
                    break
    print('PASS real browser in French and English at 2x device scale: two recipes, restored focus and export diagnostics.')


if __name__ == '__main__':
    main()
