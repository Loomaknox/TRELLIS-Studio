"""Exercise derived model admission, private queues and ownership without running inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import io
import json
import struct
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server_lan import account, call, login, PASSWORD, serve
from studio_workspace import read, write


def fixture_glb():
    payload = json.dumps({'asset': {'version': '2.0'}, 'meshes': [{'primitives': []}]}).encode()
    payload += b' ' * (-len(payload) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20 + len(payload), len(payload), 0x4e4f534a) + payload


def run():
    support = lambda _: {'supported': True, 'reason': None}
    prototype = {
        'texture_projection': SimpleNamespace(inspect_texture_projection=support,
                                              normalize_projection_options=lambda options: options),
        'baked_game_copy': SimpleNamespace(inspect_baked_game_copy=support,
                                           normalize_game_copy_options=lambda options: options),
    }
    with TemporaryDirectory(prefix='trellis-model-finishing-') as directory, patch.dict(sys.modules, prototype):
        root = Path(directory)
        def profile(name):
            return {key: value for key, value in account(name).items() if key != 'password'}
        setup_token = 'local-finishing-fixture-only'
        with serve(root, setup_token) as (base, _):
            admin = call(base, 'POST', '/server/api/setup', 201,
                         json={**account('admin'), 'token': setup_token}).json()['user']
        with serve(root) as (base, state):
            users = [state.store.register(profile(name), PASSWORD) for name in ('alice', 'bob')]
            for user in users:
                state.store.update_user(admin['id'], user['id'], dict(status='active'))
            state.runtime.paused = True
            alice, _ = login(base, 'alice')
            bob, _ = login(base, 'bob')
            identifier = 'd' * 32
            source = root / 'users' / users[0]['id'] / 'outputs' / identifier
            source.mkdir(parents=True)
            glb = fixture_glb()
            (source / 'model.glb').write_bytes(glb)
            Image.new('RGB', (16, 16), '#776644').save(source / 'input.png')
            write(source / 'settings.json', dict(name='Witness', asset_type='humanoid', keep_finishing_source=True))
            write(source / 'metadata.json', dict(display_name='Witness', favorite=True))
            write(source / 'status.json', dict(state='done', progress=100))
            routes = ['texture-projection', 'baked-game-copy']
            url = f'/api/v1/models/{identifier}'
            call(base, 'GET', url + '/' + routes[0], 401)
            for endpoint in routes:
                call(base, 'GET', url + '/' + endpoint, 404, bob)
            projection = call(base, 'GET', url + '/' + routes[0], client=alice).json()
            assert [item['id'] for item in projection['references']] == ['input']
            assert projection['linked_selection'] and 'polygon' in projection['mask_shapes']
            assert call(base, 'GET', url + '/' + routes[1], client=alice).json()['default_triangles'] == 14000
            options = dict(camera=dict(view='front', frame=[-1, -1, 1, 1]), source_rect=[0, 0, 1, 1],
                           target_rect=[0, 0, 1, 1], reference='input')
            call(base, 'POST', url + '/' + routes[0], 422, alice, json={**options, 'reference': None})
            call(base, 'POST', url + '/' + routes[0], 403, alice,
                 json=options, headers={'Origin': 'https://other.example.test'})
            stream = io.BytesIO()
            Image.new('RGB', (16, 16), 'white').save(stream, format='PNG')
            upload = call(base, 'POST', '/api/v1/uploads', 201, bob,
                          files={'file': ('ref.png', stream.getvalue(), 'image/png')}).json()
            call(base, 'POST', url + '/' + routes[0], 400, alice,
                 json={**options, 'reference': None, 'upload_id': upload['id']})
            outline = [[.35, .25], [.65, .28], [.54, .58], [.37, .55]]
            linked = {**options, 'linked_selection': True, 'mask_shape': 'polygon', 'source_polygon': outline}
            call(base, 'POST', url + '/' + routes[0], 422, alice, json={**linked, 'source_polygon': outline * 33})
            operations = [(routes[0], options), (routes[0], linked),
                          (routes[1], dict(profile='humanoid', triangles=14000))]
            for endpoint, recipe in operations:
                queued = call(base, 'POST', url + '/' + endpoint, 202, alice, json=recipe).json()
                child = source.parent / queued['id']
                settings = read(child / 'settings.json')
                assert settings['parent_id'] == identifier and 'keep_finishing_source' not in settings
                assert (child / 'source.glb').read_bytes() == glb
                assert read(child / 'server-work.json')['script'] == 'model_finishing_worker.py'
                if recipe is linked:
                    saved = read(child / 'finishing-request.json')['options']
                    assert saved['linked_selection'] and saved['source_polygon'] == outline
                status = call(base, 'GET', queued['status_url'], client=alice).json()
                assert status['state'] == 'queued' and not status['media']['available']
                call(base, 'GET', queued['status_url'], 404, bob)
                assert (source / 'model.glb').read_bytes() == glb
            assert len(state.store.jobs(users[0]['id'])) == 3
            assert state.store.get_user(users[0]['id'])['credits'] == 0
    print('PASS: local derived model requests, source preservation, parent links, queue, credits and isolation.')


if __name__ == '__main__':
    run()
