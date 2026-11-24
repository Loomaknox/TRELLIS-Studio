"""Exercise the real STDIO bridge against two local Server accounts."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def client(request):
    from mcp import Client, StdioServerParameters
    env = dict(os.environ, TRELLIS_API_URL=request['url'], TRELLIS_API_TOKEN=request['token'])
    params = StdioServerParameters(command=sys.executable, args=['-B', str(ROOT / 'trellis_mcp.py')], cwd=ROOT, env=env)
    async with Client(params) as connection:
        if request['mode'] == 'edit':
            result = await connection.call_tool('create_folder', {'folder': {'name': 'First user collection'}})
            assert not result.is_error
        result = await connection.call_tool('get_workspace')
        assert not result.is_error
        assert ('First user collection' in json.dumps(result.structured_content)) == (request['mode'] != 'other')
        if request['mode'] != 'edit':
            result = await connection.call_tool('create_folder', {'folder': {'name': 'Read-only test'}})
            assert result.is_error and '403' in str(result.content)


def run(python):
    from server_lan import serve, account, PASSWORD
    from server_store import Store
    with TemporaryDirectory() as directory:
        data = Path(directory)
        store = Store(data / 'server.sqlite3')
        def profile(name):
            return {key: value for key, value in account(name).items() if key != 'password'}
        admin = store.bootstrap_admin(profile('admin'), PASSWORD)['id']
        users = []
        for name in ('first', 'other'):
            user = store.register(profile(name), PASSWORD)['id']
            store.update_user(admin, user, {'status': 'active'})
            users.append(user)
        with serve(data) as (url, _):
            for mode, owner, scope in [('edit', users[0], 'edit'), ('read', users[0], 'read'), ('other', users[1], 'read')]:
                key = store.create_api_token(owner, 'MCP test', scope, 1)
                request = json.dumps(dict(url=url, token=key['token'], mode=mode))
                subprocess.run([python, '-B', __file__, '--client'], input=request, text=True, check=True, timeout=90)
                store.revoke_api_token(owner, key['id'])
    print('PASS: STDIO MCP, two separate libraries, read and edit permissions')


if __name__ == '__main__':
    if sys.argv[1:] == ['--client']:
        asyncio.run(client(json.load(sys.stdin)))
    else:
        run(os.environ.get('TRELLIS_TEST_MCP_PYTHON', str(ROOT / '.mcp-venv/Scripts/python.exe')))
