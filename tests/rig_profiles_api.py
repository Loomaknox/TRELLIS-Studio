"""Exercise profile selection, verified source provenance and Server publication in isolation."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import struct
import sys
from tempfile import TemporaryDirectory
import threading
from unittest.mock import patch

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server_lan import account, call, eventually, login, serve, totp, PASSWORD, MIB
from studio_workspace import write


def model_bytes(*, skinned=False, clips=(), label='Fixture'):
    model = dict(asset={'version': '2.0'}, meshes=[{'name': label, 'primitives': []}])
    if skinned:
        model['skins'] = [{'joints': [0]}]
    if clips:
        model['animations'] = [{'name': name} for name in clips]
    data = json.dumps(model).encode()
    data += b' ' * (-len(data) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20 + len(data), len(data), 0x4e4f534a) + data


def fixture(output, identifier, *, skinned=False, clips=(), source=None, **settings):
    path = output / identifier
    path.mkdir(parents=True)
    (path / 'model.glb').write_bytes(model_bytes(skinned=skinned, clips=clips))
    if source is not None:
        (path / 'source.glb').write_bytes(source)
    write(path / 'settings.json', dict(name='Fixture', asset_type='imported', **settings))
    write(path / 'metadata.json', {'display_name': 'Fixture'})
    write(path / 'status.json', {'state': 'done', 'stage': 'Fixture'})
    return path


@contextmanager
def desktop_host(app):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        eventually(lambda: server.started)
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(8)
        assert not thread.is_alive()


def desktop_test():
    with TemporaryDirectory(prefix='trellis-rig-profiles-') as temporary:
        directory = Path(temporary).resolve()
        paths = {
            'TRELLIS_' + key: str(directory / path)
            for key, path in [
                ('OUTPUT_DIR', 'outputs'), ('TRASH_DIR', 'trash'), ('EXPORT_DIR', 'exports'),
                ('STATE_DIR', 'state'), ('PROFILES_FILE', 'profiles.json')
            ]
        }
        with patch.dict(os.environ, {**paths, 'TRELLIS_RIG_PROFILES': ''}):
            import app
            root = fixture(app.OUTPUT, 'a'*32, height_m=1.79)
            data = (root / 'model.glb').read_bytes()
            rigged = fixture(app.OUTPUT, 'b'*32, skinned=True,
                             clips=('TS_run_2.5s', 'My imported motion', 'TS_unknown_3s', 'TS_idle_2.75s'),
                             source=data, source_kind='unirig', parent_id=root.name,
                             rig_options={'rotation': [0, 90, 0], 'height_m': 1.82, 'offset_m': 0.02})
            isolated = fixture(app.OUTPUT, 'c'*32, skinned=True, parent_id=root.name)
            saved = {}

            def launch(job, worker):
                assert worker == 'rig_worker.py'
                saved[job.name] = json.loads((job / 'settings.json').read_text(encoding='utf-8'))

            with (
                patch.object(app, 'require_idle'),
                patch.object(app, 'components', return_value={'unirig': {'ready': True}}),
                patch.object(app, 'find_blender', return_value=Path('fixture-blender')),
                patch.object(app, 'launch_worker', side_effect=launch),
                desktop_host(app.app) as base,
            ):
                legacy = '/api/jobs/' + root.name + '/rig'
                auto_base = call(base, 'POST', legacy, 201, json={}).json()['id']
                auto_explicit = call(base, 'POST', legacy, 201, json={'profile': 'auto'}).json()['id']
                typed_auto = call(base, 'POST', '/api/v1/models/' + root.name + '/rig', 202,
                                  json={'profile': 'auto'}).json()['id']
                assert saved[auto_base]['rig_options'] == saved[auto_explicit]['rig_options'] == saved[typed_auto]['rig_options']
                assert 'rig_profile_version' not in saved[auto_explicit]
                auto_skinned = call(base, 'POST', '/api/jobs/' + isolated.name + '/rig', 201, json={}).json()['id']
                assert (app.OUTPUT / auto_skinned / 'source.glb').read_bytes() == (isolated / 'model.glb').read_bytes()
                assert call(base, 'GET', '/api/status').json()['rig_profiles'] == []
                call(base, 'POST', legacy, 409, json={'profile': 'simple'})
                call(base, 'POST', legacy, 409, json={'profile': 'expert'})
                call(base, 'POST', legacy, 409, json={'profile': 'expressive'})

                with patch.dict(os.environ, {'TRELLIS_RIG_PROFILES': 'expert,expressive,advanced, simple,standard,unknown'}):
                    assert call(base, 'GET', '/api/v1/status').json()['rig_profiles'] == [
                        'simple', 'standard', 'advanced', 'expert', 'expressive',
                    ]
                    call(base, 'POST', legacy, 400, json={'profile': 'simple', 'articulated_fingers': True})
                    call(base, 'POST', legacy, 400, json={'profile': 'unknown'})
                    call(base, 'POST', '/api/v1/models/' + root.name + '/rig', 422,
                         json={'profile': 'expert', 'articulated_fingers': 'false'})
                    call(base, 'POST', '/api/v1/models/' + root.name + '/rig', 422,
                         json={'profile': 'expressive', 'articulated_fingers': 'false'})
                    simple = call(base, 'POST', legacy, 201, json={'profile': 'simple'}).json()['id']
                    assert saved[simple]['rig_options']['articulated_fingers'] is False
                    assert saved[simple]['rig_options']['height_m'] == 1.79
                    assert (app.OUTPUT / simple / 'source.glb').read_bytes() == data
                    route = '/api/v1/models/' + rigged.name
                    resolved = call(base, 'GET', route + '/rig-source').json()
                    assert resolved['id'] == root.name and resolved['rig_options']['rotation'] == [0, 90, 0]
                    advanced = call(base, 'POST', route + '/rig', 202,
                                    json={'profile': 'advanced', 'articulated_fingers': False}).json()['id']
                    options = saved[advanced]['rig_options']
                    assert options['profile'] == 'advanced' and options['articulated_fingers'] is False
                    assert options['height_m'] == 1.82 and options['offset_m'] == .02
                    assert saved[advanced]['rig_source_id'] == root.name
                    assert saved[advanced]['rig_source_sha256'] == app.rig_source_digest(root / 'model.glb')
                    assert saved[advanced]['parent_id'] == rigged.name
                    assert saved[advanced]['animation_clips'] == [{'id': 'run', 'duration': 2.5}]
                    assert saved[advanced]['rig_skipped_clips'] == ['My imported motion', 'TS_unknown_3s', 'TS_idle_2.75s']
                    standard = call(base, 'POST', route + '/rig', 202, json={'profile': 'standard'}).json()['id']
                    assert saved[standard]['rig_options']['articulated_fingers'] is True
                    expert = call(base, 'POST', '/api/jobs/' + rigged.name + '/rig', 201,
                                  json={'profile': 'expert'}).json()['id']
                    assert saved[expert]['rig_options'] == {**options, 'profile': 'expert', 'articulated_fingers': True}
                    assert saved[expert]['rig_source_id'] == root.name and saved[expert]['parent_id'] == rigged.name
                    assert saved[expert]['animation_clips'] == saved[advanced]['animation_clips']
                    expert_rigid = call(base, 'POST', route + '/rig', 202,
                                        json={'profile': 'expert', 'articulated_fingers': False}).json()['id']
                    assert saved[expert_rigid]['rig_options'] == {**options, 'profile': 'expert'}
                    expressive = call(base, 'POST', route + '/rig', 202, json={'profile': 'expressive'}).json()['id']
                    assert saved[expressive]['rig_options'] == {
                        **options, 'profile': 'expressive', 'articulated_fingers': True,
                    }
                    for field in ('rig_source_id', 'rig_source_sha256', 'parent_id', 'animation_clips', 'rig_skipped_clips'):
                        assert saved[expressive][field] == saved[advanced][field]
                    expressive_rigid = call(base, 'POST', '/api/jobs/' + rigged.name + '/rig', 201,
                                             json={'profile': 'expressive', 'articulated_fingers': False}).json()['id']
                    assert saved[expressive_rigid]['rig_options'] == {**options, 'profile': 'expressive'}
                    call(base, 'POST', '/api/jobs/' + isolated.name + '/rig', 409, json={'profile': 'simple'})
                    call(base, 'GET', '/api/jobs/' + isolated.name + '/rig-source', 409)
                    child = app.OUTPUT / advanced
                    (child / 'model.glb').write_bytes(model_bytes(skinned=True))
                    write(child / 'status.json', {'state': 'done', 'stage': 'Fixture'})
                    remade = call(base, 'POST', '/api/jobs/' + advanced + '/rig', 201,
                                  json={'profile': 'simple'}).json()['id']
                    assert saved[remade]['parent_id'] == advanced
                    assert saved[remade]['rig_source_id'] == root.name
                    assert saved[remade]['rig_options']['height_m'] == 1.82
                    assert (app.OUTPUT / remade / 'source.glb').read_bytes() == data
                    # A changed source invalidates the provenance of both old and profiled children.
                    (root / 'model.glb').write_bytes(model_bytes(label='Changed'))
                    call(base, 'GET', route + '/rig-source', 409)
                    call(base, 'GET', '/api/jobs/' + advanced + '/rig-source', 409)


def server_test():
    flags = {'TRELLIS_RIG_PROFILES': 'simple,standard,expert,expressive', 'TRELLIS_SERVER_RIG_PROFILES': ''}
    with TemporaryDirectory(prefix='trellis-rig-profiles-server-') as temporary, patch.dict(os.environ, flags):
        data = Path(temporary).resolve()
        with serve(data, 'local-fixture') as (base, _):
            call(base, 'POST', '/server/api/setup', 201, json={**account('admin'), 'token': 'local-fixture'})
        with serve(data) as (base, state):
            admin, _ = login(base, 'admin')
            secret = call(base, 'POST', '/server/api/mfa/setup', client=admin, json={'password': PASSWORD}).json()['secret']
            codes = call(base, 'POST', '/server/api/mfa/enable', client=admin,
                         json={'code': totp(secret)}).json()['recovery_codes']
            admin, _ = login(base, 'admin', codes[0])
            call(base, 'PATCH', '/server/api/admin/queue', client=admin, json={'paused': True})
            for name in ('alice', 'bob'):
                call(base, 'POST', '/server/api/register', 201, json=account(name))
            users = {user['email']: user['id'] for user in call(base, 'GET', '/server/api/admin/users', client=admin).json()['users']}
            for name in ('alice', 'bob'):
                call(base, 'PATCH', '/server/api/admin/users/' + users[name + '@example.test'],
                     client=admin, json={'status': 'active', 'disk_limit_bytes': 128 * MIB})
            alice, _ = login(base, 'alice')
            bob, _ = login(base, 'bob')
            alice_id = users['alice@example.test']
            assert call(base, 'GET', '/api/status', client=alice).json()['rig_profiles'] == []
            workspace = state.runtime.workspaces[alice_id]
            root = fixture(workspace.outputs, '1'*32)
            route = '/api/v1/models/' + root.name
            payload = {'profile': 'simple'}
            with (
                patch.dict(os.environ, {'TRELLIS_SERVER_RIG_PROFILES': 'simple'}),
                patch.object(workspace.studio, 'components', return_value={'unirig': {'ready': True}}),
                patch.object(workspace.studio, 'find_blender', return_value=Path('fixture-blender')),
            ):
                assert call(base, 'GET', '/api/v1/status', client=alice).json()['rig_profiles'] == ['simple']
                call(base, 'GET', route + '/rig-source', 404, bob)
                call(base, 'POST', route + '/rig', 404, bob, json=payload)
                call(base, 'PATCH', '/server/api/admin/users/' + alice_id, client=admin,
                     json={'disk_limit_bytes': 8 * MIB})
                before = set(workspace.outputs.iterdir())
                call(base, 'POST', route + '/rig', 413, alice, json=payload)
                assert set(workspace.outputs.iterdir()) == before
                call(base, 'PATCH', '/server/api/admin/users/' + alice_id, client=admin,
                     json={'disk_limit_bytes': 128 * MIB})
                result = call(base, 'POST', route + '/rig', 202, alice, json=payload).json()
                assert result['state'] == 'queued'
                result_path = result['status_url']
                assert call(base, 'GET', result_path, client=alice).json()['settings']['rig_source_id'] == root.name
                call(base, 'GET', result_path, 404, bob)
                job = next(row for row in state.store.jobs(alice_id) if row['id'] == result['id'])
                assert job['state'] == 'reserved' and job['credit_cost'] == 0
                call(base, 'POST', result_path + '/cancel', client=alice)
                call(base, 'POST', route + '/rig', 409, alice, json={'profile': 'expert'})
                call(base, 'POST', route + '/rig', 409, alice, json={'profile': 'expressive'})
                with patch.dict(os.environ, {'TRELLIS_SERVER_RIG_PROFILES': 'simple,expert'}):
                    assert call(base, 'GET', '/api/v1/status', client=alice).json()['rig_profiles'] == ['simple', 'expert']
                    expert = call(base, 'POST', route + '/rig', 202, alice, json={'profile': 'expert'}).json()
                    settings = call(base, 'GET', expert['status_url'], client=alice).json()['settings']
                    assert settings['rig_options']['articulated_fingers'] is True
                    call(base, 'GET', expert['status_url'], 404, bob)
                    call(base, 'POST', expert['status_url'] + '/cancel', client=alice)
                with patch.dict(os.environ, {'TRELLIS_SERVER_RIG_PROFILES': 'expressive'}):
                    assert call(base, 'GET', '/api/v1/status', client=alice).json()['rig_profiles'] == ['expressive']
                    options = {'profile': 'expressive', 'articulated_fingers': False}
                    expressive = call(base, 'POST', route + '/rig', 202, alice, json=options).json()
                    settings = call(base, 'GET', expressive['status_url'], client=alice).json()['settings']
                    assert settings['rig_options']['articulated_fingers'] is False
                    call(base, 'GET', expressive['status_url'], 404, bob)
                    call(base, 'POST', expressive['status_url'] + '/cancel', client=alice)
                assert (root / 'model.glb').read_bytes() == model_bytes()


if __name__ == '__main__':
    desktop_test()
    server_test()
    print('PASS: rig profiles, legacy Auto, recipe replay, source checks, Server isolation and disk quota.')
