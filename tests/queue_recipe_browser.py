"""Run the French batch and preflight regression in a disposable Windows browser job."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collection_preview_renderer import _find_browser, _WindowsBrowserJob


def main():
    done, results = Event(), []
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/':
                data = (b'<meta charset="utf-8"><span id="queueCount"></span><select id="assetType">'
                        b'<option value="object">Objet</option><option value="humanoid">Humanoide</option></select>'
                        b'<script type="module" src="/tests/queue_recipe_browser.js"></script>')
                mime = 'text/html'
            else:
                file = (ROOT / path.lstrip('/')).resolve()
                if (file.parent != ROOT / 'web' and file != ROOT / 'tests/queue_recipe_browser.js') or not file.is_file():
                    self.send_error(404)
                    return
                data = file.read_bytes()
                mime = 'text/javascript' if file.suffix == '.js' else 'image/svg+xml'
            self.send_response(200)
            self.send_header('Content-Type', mime)
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

    browser = _find_browser()
    assert browser, 'Install Edge or Chrome for this regression.'
    with TemporaryDirectory(prefix='trellis-queue-browser-') as tmp, ThreadingHTTPServer(('127.0.0.1', 0), Fixture) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            job = _WindowsBrowserJob([str(browser), '--headless=new', '--disable-gpu', '--disable-extensions',
                '--disable-background-networking', '--no-first-run', '--no-default-browser-check',
                '--user-data-dir=' + tmp, f'http://127.0.0.1:{server.server_port}/?lang=fr'])
            try:
                assert done.wait(35), 'Browser fixture did not complete'
                assert results == ['PASS'], results
            finally:
                job.close()
        finally:
            server.shutdown()
            thread.join(5)
    print('PASS real browser: two batch recipes, French export diagnostics, isolated browser closed.')


if __name__ == '__main__':
    main()
