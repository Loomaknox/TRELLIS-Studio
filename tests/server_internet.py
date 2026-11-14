"""Internet origin, proxy settings and role-based MFA regressions; no public service."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_app import app_for
from server_app import main as server_main
from server_setup import network_settings, settings
from server_store import Store, StoreError


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'An isolated fixture password 41'
ORIGIN = 'https://studio.example.test'


def preferences(folder):
    return dict(data_dir=str(folder / 'data'), host='127.0.0.1', port=7863,
                reverse_proxy=True, proxy_port=443, proxy_admin_port=2019,
                public_url=ORIGIN, autostart=False)


def rejected(raw, config):
    try:
        settings(raw, config)
    except (ValueError, TypeError, OSError):
        return
    raise AssertionError(f'Unexpected accepted preferences: {raw}')


def configuration_checks(folder):
    config = folder / 'config.json'
    raw = preferences(folder)
    selected = settings(raw, config)
    assert selected['host'] == '127.0.0.1' and selected['tls_cert'] is None
    assert selected['proxy_port'] == 443 and selected['proxy_admin_port'] == 2019
    assert not Path(raw['data_dir']).exists(), 'Validation must not create the data folder.'
    canonical = settings({**raw, 'public_url': 'https://STUDIO.EXAMPLE.TEST:443/'}, config)
    assert canonical['public_url'] == ORIGIN
    nat = settings({**raw, 'public_url': ORIGIN + ':8443', 'proxy_port': 7862}, config)
    assert nat['public_url'] == ORIGIN + ':8443' and nat['proxy_port'] == 7862
    direct = settings({**raw, 'reverse_proxy': False, 'port': 7862, 'public_url': 'http://127.0.0.1:7862'}, config)
    assert not direct['reverse_proxy'] and 'proxy_port' not in direct
    existing_proxy = folder / 'existing proxy' / 'caddy.exe'
    existing_store = folder / 'existing certificates'
    migrated = settings({**raw, 'proxy_executable': str(existing_proxy), 'proxy_storage': str(existing_store)}, config)
    assert migrated['proxy_executable'] == str(existing_proxy.resolve())
    assert migrated['proxy_storage'] == str(existing_store.resolve())
    assert not existing_proxy.exists() and not existing_store.exists(), 'Path validation must not write migration files.'
    direct_migrated = settings({**direct, 'proxy_executable': str(existing_proxy), 'proxy_storage': str(existing_store)}, config)
    assert direct_migrated['proxy_storage'] == migrated['proxy_storage'], 'Temporarily disabling Internet must retain ACME storage selection.'
    for change in (
        {'host': '0.0.0.0'}, {'host': '127.0.0.2'}, {'host': '::1'},
        {'tls_cert': 'unused.pem', 'tls_key': 'unused.key'},
        {'reverse_proxy': 'false'}, {'port': True}, {'port': 7863.2},
        {'port': 0}, {'port': 65536}, {'proxy_port': 7863},
        {'proxy_admin_port': 443}, {'proxy_port': True},
        {'proxy_port': 65536}, {'proxy_admin_port': 0},
        {'public_url': 'http://studio.example.test'},
        {'public_url': 'https://127.0.0.1'}, {'public_url': 'https://localhost'},
        {'public_url': 'https://studio.example.test:0'},
        {'public_url': 'https://studio.example.test:65536'},
        {'public_url': 'https://user:password@studio.example.test'},
        {'public_url': 'https://studio.example.test/path'},
        {'public_url': 'https://studio.example.test?option=1'},
        {'public_url': 'https://studio.example.test\nheader'},
        {'public_url': 'https://studio.example.test\\path'},
        {'public_url': 'https://*.example.test'},
        {'public_url': 'https://-bad.example.test'},
        {'public_url': 'https://bad..example.test'},
        {'public_url': 'https://bad_name.example.test'},
        {'public_url': 'https://example.test.'},
        {'public_url': 'https://' + 'a' * 64 + '.example.test'},
        {'data_dir': str(ROOT / 'config' / 'unsafe')},
        {'data_dir': str(ROOT)},
        {'proxy_executable': 'caddy.exe'},
        {'proxy_executable': str(folder / 'untrusted.exe')},
        {'proxy_executable': True},
        {'proxy_storage': 'relative-store'},
        {'proxy_storage': str(ROOT)},
        {'proxy_storage': str(Path(folder.anchor))},
        {'proxy_storage': str(ROOT / 'engine' / 'store')},
        {'proxy_storage': str(folder / 'data' / 'certificates')},
        {'proxy_storage': str(folder / 'bad\nstore')},
        {'proxy_storage': str(folder / 'bad{store}')},
        {'proxy_storage': str(folder / 'bad"store')},
    ):
        rejected({**raw, **change}, config)
    config.write_text(json.dumps(selected), encoding='utf-8')
    rejected({**raw, 'data_dir': str(folder / 'different-data')}, config)
    # The GUI's preflight has no account setup, disk writes or browser launch.
    process = subprocess.run([sys.executable, '-B', str(ROOT / 'server_setup.py'), '--config',
                              str(config), '--validate-only'], input=json.dumps(raw), text=True,
                             capture_output=True, timeout=15)
    assert process.returncode == 0, process.stderr
    assert not Path(raw['data_dir']).exists()
    process = subprocess.run([sys.executable, '-B', str(ROOT / 'server_setup.py'), '--config',
                              str(config), '--validate-only'], input=json.dumps({**raw, 'host': '0.0.0.0'}),
                             text=True, capture_output=True, timeout=15)
    assert process.returncode != 0 and not Path(raw['data_dir']).exists()


async def forwarded_header_checks():
    # Exercise the actual Uvicorn middleware with precisely the runtime trust setting.
    observed = []
    async def inspect(scope, receive, send):
        observed.append((scope['client'], scope['scheme']))
    proxy = ProxyHeadersMiddleware(inspect, trusted_hosts='127.0.0.1')
    for peer in ('127.0.0.1', '198.51.100.8'):
        await proxy(dict(type='http', client=(peer, 1234), scheme='http',
                         headers=[(b'x-forwarded-for', b'203.0.113.10'),
                                  (b'x-forwarded-proto', b'https')]), None, None)
    assert observed == [(('203.0.113.10', 0), 'https'), (('198.51.100.8', 1234), 'http')]


def profile(name):
    return dict(first_name=name, last_name='Fixture', email=name + '@example.test')


async def account_checks(folder):
    store = Store(folder / 'data' / 'server.sqlite3')
    admin = store.bootstrap_admin(profile('admin'), PASSWORD)['id']
    user = store.register(profile('artist'), PASSWORD)['id']
    store.update_user(admin, user, {'status': 'active'})
    app = app_for(folder / 'data', ORIGIN)
    transport = httpx.ASGITransport(app=app, client=('198.51.100.8', 12345))
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN,
                                headers={'X-Trellis-Request': '1'}) as client:
        async def call(method, path, expected=200, **kwargs):
            response = await client.request(method, path, **kwargs)
            assert response.status_code == expected, (path, response.status_code, response.text)
            return response
        await call('GET', '/api/v1/models', 401)
        await call('POST', '/server/api/setup', 404, json={})
        await call('GET', '/server/api/health', 400, headers={'Host': 'unrelated.example.test'})
        await call('POST', '/server/api/login', 403, headers={'Origin': 'https://unrelated.example.test'}, json={})
        response = await call('POST', '/server/api/login', json=dict(email='artist@example.test', password=PASSWORD))
        cookie = response.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert response.json()['user']['mfa_required'] is False
        await call('GET', '/server/api/credits')  # Ordinary accounts work without MFA.
        secret = (await call('POST', '/server/api/mfa/setup', json={'password': PASSWORD})).json()['secret']
        assert secret
        with patch('server_store.totp_step', return_value=2):
            codes = (await call('POST', '/server/api/mfa/enable', json={'code': '123456'})).json()['recovery_codes']
        await call('GET', '/server/api/credits', 401)  # Enabling MFA revokes old sessions.
        response = await call('POST', '/server/api/login', 401, json=dict(email='artist@example.test', password=PASSWORD))
        assert response.json()['code'] == 'mfa_required'
        await call('POST', '/server/api/login', json=dict(email='artist@example.test', password=PASSWORD, code=codes[0]))
        await call('POST', '/server/api/mfa/disable', json={'password': PASSWORD, 'code': codes[1]})
        assert not store.get_user(user)['totp_enabled']
        await call('POST', '/server/api/login', json=dict(email='artist@example.test', password=PASSWORD))
        credential = store.create_api_token(user, 'Fixture token')['token']
        store.update_user(admin, user, {'role': 'admin'})
        await call('GET', '/server/api/credits', 401)  # Promotion revokes sessions and API tokens.
        try:
            store.authenticate_api(credential)
        except StoreError as error:
            assert error.status == 401
        else:
            raise AssertionError('Promoted user retained a pre-promotion API token.')
        promoted = (await call('POST', '/server/api/login', json=dict(email='artist@example.test', password=PASSWORD))).json()['user']
        assert promoted['mfa_required'] and promoted['mfa_setup_required']
        response = await call('GET', '/server/api/credits', 403)
        assert response.json()['code'] == 'mfa_setup_required'
        await call('POST', '/server/api/tokens', 403, json={'label': 'Rejected'})
        response = await call('GET', '/', 307)
        assert response.headers['location'] == '/server/account#security'
        await call('POST', '/server/api/mfa/setup', json={'password': PASSWORD})
        with patch('server_store.totp_step', return_value=3):
            codes = (await call('POST', '/server/api/mfa/enable', json={'code': '123456'})).json()['recovery_codes']
        await call('POST', '/server/api/login', json=dict(email='artist@example.test', password=PASSWORD, code=codes[0]))
        await call('GET', '/server/api/admin/users')
        await call('POST', '/server/api/mfa/disable', 403, json={'password': PASSWORD, 'code': codes[1]})
        try:
            store.disable_totp(user, PASSWORD, codes[1])
        except StoreError as error:
            assert error.status == 403 and error.code == 'mfa_required'
        else:
            raise AssertionError('Admin MFA was disabled through the account store.')
        assert Store(store.path).get_user(user)['totp_enabled'], 'Existing enrollment must survive reopening.'


def offline_recovery_check(folder):
    config = folder / 'unavailable-certificate.json'
    config.write_text(json.dumps({**preferences(folder), 'reverse_proxy': False,
                                  'host': '0.0.0.0', 'port': 7862,
                                  'public_url': 'https://192.0.2.10:7862',
                                  'tls_cert': str(folder / 'missing.pem'),
                                  'tls_key': str(folder / 'missing.key')}), encoding='utf-8')
    replacement = 'Offline recovery fixture password 51'
    with patch('sys.argv', ['server_app.py', '--config', str(config), '--recover-admin', 'admin@example.test']), \
            patch('server_app.getpass', return_value=replacement), patch('builtins.print'), \
            patch('server_app.uvicorn.Server', side_effect=AssertionError('Offline recovery must not start a listener.')):
        server_main()
    result = Store(folder / 'data' / 'server.sqlite3').login('admin@example.test', replacement)
    assert result['user']['mfa_required'] and not result['user']['totp_enabled']


def run():
    with TemporaryDirectory(prefix='trellis-internet-test-') as name:
        folder = Path(name).resolve()
        configuration_checks(folder)
        asyncio.run(forwarded_header_checks())
        asyncio.run(account_checks(folder))
        offline_recovery_check(folder)
    print('PASS: validated Internet settings, trusted proxy origin, secure cookies and role-based MFA')


if __name__ == '__main__':
    run()
