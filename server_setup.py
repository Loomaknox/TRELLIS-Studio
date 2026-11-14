"""Configure the Windows server and complete its one-time local browser setup."""
from argparse import ArgumentParser
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import ssl
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent


def network_settings(raw):
    """Validate the listener and its public origin without opening any sockets."""
    if not isinstance(raw, dict):
        raise ValueError('Expected server preferences as a JSON object.')
    def numeric_port(value, label, minimum=1):
        if type(value) is not int and not (isinstance(value, str) and value.isascii() and value.isdecimal()):
            raise ValueError(f'Choose a whole-number {label} port.')
        value = int(value)
        if not minimum <= value <= 65535:
            raise ValueError(f'Choose a {label} port between {minimum} and 65535.')
        return value

    reverse_proxy = raw.get('reverse_proxy', False)
    if type(reverse_proxy) is not bool:
        raise ValueError('Choose whether to enable Internet access.')
    if any(key in raw and raw[key] is not None and not isinstance(raw[key], str)
           for key in ('host', 'public_url', 'tls_cert', 'tls_key', 'proxy_executable', 'proxy_storage')):
        raise ValueError('Listener address, browser address and certificate paths must be text.')
    host = (raw.get('host') or '127.0.0.1').strip()
    address = ipaddress.ip_address(host)
    if address.version != 4:
        raise ValueError('Choose an IPv4 address, 127.0.0.1 or 0.0.0.0.')
    port = numeric_port(raw.get('port', 7863 if reverse_proxy else 7862), 'backend', 1024)
    tls_cert, tls_key = (raw.get('tls_cert') or '').strip(), (raw.get('tls_key') or '').strip()
    if bool(tls_cert) != bool(tls_key):
        raise ValueError('Provide both the PEM certificate and its private key.')
    if reverse_proxy and (host != '127.0.0.1' or tls_cert or tls_key):
        raise ValueError('Internet access requires an HTTP backend on 127.0.0.1. Caddy manages HTTPS.')
    if tls_cert:
        tls_cert = str(Path(tls_cert).resolve(strict=True))
        tls_key = str(Path(tls_key).resolve(strict=True))
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(tls_cert, tls_key, password=lambda: '')
    if not address.is_loopback and not tls_cert:
        raise ValueError('Network access requires HTTPS. Choose a certificate and private key.')
    scheme = 'https' if reverse_proxy or tls_cert else 'http'
    public_url = (raw.get('public_url') or f'{scheme}://{host}:{port}').strip().rstrip('/')
    # urlsplit strips some control characters; reject those before parsing.
    if any(ord(char) <= 32 or ord(char) == 127 for char in public_url) or '\\' in public_url:
        raise ValueError('Enter a browser address without whitespace or control characters.')
    url = urlsplit(public_url)
    if (url.scheme != scheme or not url.hostname or url.username is not None or url.password is not None
            or url.path or url.query or url.fragment or url.hostname == '0.0.0.0'):
        raise ValueError('Enter the full browser address using the selected scheme, without a path.')
    public_port = numeric_port(url.port if url.port is not None else (443 if scheme == 'https' else 80), 'public')
    result = dict(host=host, port=port, tls_cert=tls_cert or None, tls_key=tls_key or None,
                  reverse_proxy=reverse_proxy)
    if reverse_proxy:
        domain = url.hostname.lower()
        labels = domain.split('.')
        if (len(domain) > 253 or len(labels) < 2
                or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels)
                or labels[-1].isdigit()):
            raise ValueError('Use a public DNS domain such as studio.example.com, not an IP address.')
        # Keep the browser origin canonical: browsers omit the default HTTPS port.
        result['public_url'] = 'https://' + domain + (f':{public_port}' if public_port != 443 else '')
        proxy_port = numeric_port(raw.get('proxy_port', 443), 'HTTPS')
        admin_port = numeric_port(raw.get('proxy_admin_port', 2019), 'proxy administration', 1024)
        if len({port, proxy_port, admin_port}) != 3:
            raise ValueError('Choose distinct backend, HTTPS and proxy administration ports.')
        result.update(proxy_port=proxy_port, proxy_admin_port=admin_port)
    else:
        if public_port != port:
            raise ValueError('The browser address must use the selected listener port.')
        if address.is_loopback and url.hostname not in ('127.0.0.1', 'localhost'):
            raise ValueError('A local-only server needs a localhost or 127.0.0.1 browser address.')
        result['public_url'] = public_url
    # Retain an existing deployment's verified executable and ACME store during migration.
    # These local paths are optional; ordinary installations keep the bundled defaults.
    for key in ('proxy_executable', 'proxy_storage'):
        value = (raw.get(key) or '').strip()
        if not value:
            continue
        if any(ord(char) < 32 or ord(char) == 127 for char in value) or any(char in value for char in '\"{}'):
            raise ValueError('Proxy paths must not contain control characters, quotes or braces.')
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError('Use an absolute local path for the proxy executable and certificate storage.')
        path = path.resolve()
        if key == 'proxy_executable':
            if path.name.casefold() != 'caddy.exe' or path.is_dir():
                raise ValueError('The proxy executable must be named caddy.exe; its checksum is verified at startup.')
        else:
            protected = [ROOT / name for name in ('outputs', 'trash', 'exports', 'models', 'engine', 'web', '.venv', '.mcp-venv')]
            if (path == Path(path.anchor) or ROOT.is_relative_to(path)
                    or any(path.is_relative_to(item) or item.is_relative_to(path) for item in protected)
                    or path.is_file()):
                raise ValueError('Choose a separate proxy certificate storage directory, not a drive root or program/library folder.')
        result[key] = str(path)
    return result


def active_administrator(data_dir):
    database = data_dir / 'server.sqlite3'
    if not database.is_file():
        return False
    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        tables = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
        return bool(tables and connection.execute("SELECT 1 FROM users WHERE role='admin' AND status='active' LIMIT 1").fetchone())
    finally:
        connection.close()


def settings(raw, config_path):
    if not isinstance(raw, dict):
        raise ValueError('Expected server preferences as a JSON object.')
    directory = Path(raw['data_dir']).expanduser()
    if not directory.is_absolute():
        raise ValueError('Choose an absolute data folder on a disk of this server.')
    directory = directory.resolve()
    protected = [ROOT / name for name in ('outputs', 'trash', 'exports', 'config', 'models', 'engine', 'web', '.venv')]
    if ROOT.is_relative_to(directory) or any(directory.is_relative_to(p) or p.is_relative_to(directory) for p in protected):
        raise ValueError('Choose a data folder separate from the program and the desktop library.')
    if config_path.is_file():
        previous = Path(json.loads(config_path.read_text(encoding='utf-8-sig'))['data_dir']).resolve()
        if directory != previous:
            raise ValueError('The server is already configured. Keep its data folder to retain accounts and libraries.')
    network = network_settings(raw)
    if network.get('proxy_storage'):
        storage = Path(network['proxy_storage'])
        if storage.is_relative_to(directory) or directory.is_relative_to(storage):
            raise ValueError('Keep proxy certificate storage separate from server account and library data.')
    if (directory.exists() and not (directory / 'server.sqlite3').is_file()
            and any(path.name not in ('setup.log', 'instance.lock') for path in directory.iterdir())):
        raise ValueError('Use an empty data folder or one already initialized by TRELLIS Server.')
    return dict(data_dir=str(directory), **network, autostart=raw.get('autostart') is True)


def setup_administrator(directory):
    if active_administrator(directory):
        return
    directory.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    with NamedTemporaryFile(dir=directory, prefix='.setup-', delete=False, mode='w', encoding='utf-8') as stream:
        stream.write(token)
        token_path = Path(stream.name)
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        command = [sys.executable, '-B', str(ROOT / 'server_app.py'), '--setup-only', '--setup-token-file',
                   str(token_path), '--data-dir', str(directory), '--port', str(port)]
        with (directory / 'setup.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                until = time.monotonic() + 30
                while time.monotonic() < until and process.poll() is None:
                    try:
                        with urlopen(base + '/server/api/health', timeout=1) as response:
                            health = json.load(response)
                        if health.get('service') == 'trellis-server' and not health.get('setup_complete'):
                            break
                    except (URLError, OSError, ValueError):
                        time.sleep(.2)
                else:
                    raise RuntimeError(f'The local setup did not start. See {directory / "setup.log"}.')
                if not webbrowser.open(base + '/server/setup#token=' + token):
                    raise RuntimeError('Windows did not open the local setup page. Configure a default browser and retry.')
                print('Create the first administrator in the browser to finish installation.', flush=True)
                try:
                    result = process.wait(timeout=900)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError('Administrator setup expired. Run the server configuration again.') from error
                if result or not active_administrator(directory):
                    raise RuntimeError(f'The administrator was not created. See {directory / "setup.log"}.')
            finally:
                if process.poll() is None:
                    token_path.unlink(missing_ok=True)
                    # A Windows virtual environment can spawn the real Python interpreter.
                    # Only processes started by this setup invocation belong to this cleanup.
                    import psutil
                    try:
                        children = psutil.Process(process.pid).children(recursive=True)
                    except psutil.NoSuchProcess:
                        children = []
                    for child in reversed(children):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    process.terminate()
                    process.wait(timeout=10)
    finally:
        token_path.unlink(missing_ok=True)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Check the saved configuration and administrator.')
    parser.add_argument('--validate-only', action='store_true', help='Validate preferences from stdin without creating an account or saving settings.')
    args = parser.parse_args()
    config_path = args.config.resolve()
    try:
        if args.check:
            raw = json.loads(config_path.read_text(encoding='utf-8-sig'))
            preferences = settings(raw, config_path)
            if not active_administrator(Path(preferences['data_dir'])):
                raise ValueError('Configure the first administrator before starting the server.')
            return 0
        # Read preferences as UTF-8. The password is entered only in the browser.
        preferences = settings(json.loads(sys.stdin.buffer.read().decode('utf-8-sig')), config_path)
        if args.validate_only:
            return 0
        setup_administrator(Path(preferences['data_dir']))
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=config_path.parent, prefix='.server-', delete=False, mode='w', encoding='utf-8') as stream:
            json.dump(preferences, stream, ensure_ascii=False, indent=2)
            pending = Path(stream.name)
        try:
            os.replace(pending, config_path)
        finally:
            pending.unlink(missing_ok=True)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
