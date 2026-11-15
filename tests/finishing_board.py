"""Isolated queue, provenance and choice checks. No inference or user data."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
from tempfile import TemporaryDirectory
from threading import Thread
import time
from unittest.mock import patch

import requests
import numpy as np
import trimesh
import uvicorn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = 'a' * 32
OTHER = 'b' * 32
SCENE = json.dumps(dict(asset={'version': '2.0'}, meshes=[{'primitives': []}])).encode()
SCENE += b' ' * (-len(SCENE) % 4)
GLB = struct.pack('<4sIIII', b'glTF', 2, 20 + len(SCENE), len(SCENE), 0x4e4f534a) + SCENE


def run():
    with TemporaryDirectory(prefix='trellis-finish-test-') as temporary:
        root = Path(temporary)
        for key, name in [('OUTPUT_DIR', 'outputs'), ('TRASH_DIR', 'trash'), ('EXPORT_DIR', 'exports'),
                          ('STATE_DIR', 'state'), ('PROFILES_FILE', 'profiles.json')]:
            os.environ['TRELLIS_' + key] = str(root / name)
        import app
        from generation_options import options_for_job
        from studio_workspace import read

        for identifier in (SOURCE, OTHER):
            folder = app.OUTPUT / identifier
            folder.mkdir()
            (folder / 'raw_state.pt').write_bytes(b'decoded cache fixture')
            (folder / 'model.glb').write_bytes(GLB)
            (folder / 'input.png').write_bytes(b'reference fixture')
            app.write_json(folder / 'settings.json', dict(name='Cached source', asset_type='object',
                           engine='pixal3d', preset='game_d', keep_finishing_source=True, triangles=28000,
                           texture_size=2048, resolution=1024, seed=117, height_m=0.6))
            app.write_json(folder / 'status.json', dict(state='done', stage='Fixture', progress=100))
        source_folder = app.OUTPUT / SOURCE
        app.write_json(source_folder / 'result.json', dict(raw_triangles=20_933_594))
        legacy_folder = app.OUTPUT / OTHER
        legacy_settings = read(legacy_folder / 'settings.json')
        legacy_settings['generation_options'] = {'pre_simplify': False}
        legacy_settings['resolution'] = 512
        app.write_json(legacy_folder / 'settings.json', legacy_settings)
        (legacy_folder / 'generation.log').write_text(
            'Original mesh: 10000 vertices, 19000 faces\nInitial mesh: 11000 vertices, 20000 faces\n',
            encoding='utf-8',
        )
        baseline = {filename: (source_folder / filename).read_bytes() for filename in
                    ('settings.json', 'model.glb', 'input.png', 'raw_state.pt')}
        calls = []

        def launch(folder, script, *, source_id):
            assert script == 'worker.py' and source_id == SOURCE, (script, source_id)
            calls.append(folder.name)
            settings = read(folder / 'settings.json')
            result = dict(triangles=settings['triangles'], texture_size=settings['texture_size'],
                          finish_source_id=source_id, neural_inferences=0)
            (folder / 'model.glb').write_bytes(GLB)
            app.write_json(folder / 'status.json', dict(state='done', stage='Fixture', progress=100, result=result))

        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app.app, host='127.0.0.1', port=port, log_level='error'))
        thread = Thread(target=server.run, daemon=True)
        url = f'http://127.0.0.1:{port}'
        route = f'/api/jobs/{SOURCE}/finishing-board'
        payload = {'variants': [
            {'triangles': 60000, 'mesh_mode': 'direct', 'repair_holes': False},
            {'triangles': 12000, 'texture_size': 1024},
        ]}

        def send(method, path, code=200, **kwargs):
            response = requests.request(method, url + path, timeout=6, **kwargs)
            assert response.status_code == code, (method, path, response.status_code, response.text)
            return response.json()

        def wait_for(identifier, expected):
            for _ in range(100):
                result = send('GET', '/api/jobs/' + identifier)
                if result['state'] == expected:
                    return result
                time.sleep(0.05)
            raise AssertionError((identifier, expected, result))

        with patch.object(app, 'launch_worker', side_effect=launch):
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                assert server.started
                board = send('GET', route)
                assert board['source_id'] == SOURCE and board['cache_bytes'] == len(baseline['raw_state.pt'])
                assert board['source_triangles'] == 20_933_594
                legacy_route = f'/api/jobs/{OTHER}/finishing-board'
                assert send('GET', legacy_route)['source_triangles'] == 19_000
                legacy_settings['generation_options']['pre_simplify'] = True
                app.write_json(legacy_folder / 'settings.json', legacy_settings)
                assert send('GET', legacy_route)['source_triangles'] is None
                assert board['selected_id'] is None
                assert send('GET', '/api/status')['default_profile'] == 'game_d'
                send('PATCH', '/api/queue', json={'paused': True})
                send('POST', route, 400, json={'variants': [{'triangles': 80000}, {'seed': 7}]})
                send('POST', route, 400, json={'variants': [{}, {}]})
                send('POST', route, 400, data='invalid json')
                with patch.object(app.STUDIO.workspace, 'save_queue', side_effect=OSError('fixture disk failure')):
                    send('POST', route, 503, json=payload)
                assert {folder.name for folder in app.OUTPUT.iterdir()} == {SOURCE, OTHER}
                assert not send('GET', '/api/queue')['items']
                response = send('POST', route, 202, json=payload)
                assert response['paused'] and response['source_id'] == SOURCE and response['count'] == 2
                for identifier in response['ids']:
                    child = app.OUTPUT / identifier
                    state = send('GET', '/api/jobs/' + identifier)
                    settings = state['settings']
                    assert state['state'] == 'queued' and settings['source_kind'] == 'refinish'
                    assert settings['parent_id'] == SOURCE and settings['finish_source_id'] == SOURCE
                    assert settings['seed'] == 117 and settings['height_m'] == 0.6
                    assert not (child / 'raw_state.pt').exists()
                    assert (child / 'input.png').read_bytes() == baseline['input.png']
                    send('PATCH', route, 409, json={'selected_id': identifier})
                send('PATCH', route, 409, json={'selected_id': OTHER})

                cache = source_folder / 'raw_state.pt'
                cache.rename(source_folder / 'raw_state.saved')
                send('PATCH', '/api/queue', json={'paused': False})
                for identifier in response['ids']:
                    assert 'Restore the source' in wait_for(identifier, 'error')['error']
                assert not calls
                (source_folder / 'raw_state.saved').rename(cache)
                for identifier in response['ids']:
                    send('PATCH', '/api/queue/' + identifier, json={'retry': True})
                    assert wait_for(identifier, 'done')['result']['neural_inferences'] == 0
                assert calls == response['ids']
                send('PATCH', '/api/queue', json={'paused': True})
                refinish_route = f'/api/jobs/{SOURCE}/refinish'
                info = send('GET', route)
                assert info['remesh_resolutions'] == [512, 768, 1024]
                assert info['hd_reconstruction'] is True
                assert info['texture_sampling_modes'] == ['trilinear', 'nearest']
                assert info['normal_sources'] == ['decoded']
                assert not info['parent_normal_source']['available']
                assert 'normalization' in info['parent_normal_source']['unavailable_reason']
                for invalid in ({'remesh_resolution': 640}, {'remesh_resolution': '768'},
                                {'remesh_resolution': True}, {'texture_sampling': 'bicubic'},
                                {'hd_reconstruction': 'true'},
                                {'hd_reconstruction': True, 'adaptive_finishing': True},
                                {'hd_reconstruction': True, 'repair_surface': True}):
                    send('POST', refinish_route, 400, json=invalid)
                reconstructed = send('POST', f'/api/v1/models/{SOURCE}/refinish', 202,
                                     json={'hd_reconstruction': True})
                settings = wait_for(reconstructed['id'], 'queued')['settings']
                assert settings['hd_reconstruction'] is True and settings['triangles'] == 1_200_000
                assert settings['finish_source_id'] == SOURCE and not settings.get('adaptive_finishing')
                options = options_for_job(settings)
                assert options['remesh_resolution'] == 768 and options['remesh_project'] == 0
                assert options['repair_holes'] and not options['pre_simplify']
                assert settings['generation_options']['remesh_resolution'] == 512
                send('POST', f'/api/jobs/{reconstructed["id"]}/cancel')
                retry = send('POST', f'/api/queue/{reconstructed["id"]}/retry', 202,
                             json={'hd_reconstruction': False})
                retry_settings = wait_for(retry['id'], 'queued')['settings']
                assert 'hd_reconstruction' not in retry_settings
                assert options_for_job(retry_settings)['remesh_resolution'] == 512
                assert not send('GET', legacy_route)['hd_reconstruction']
                send('POST', f'/api/jobs/{OTHER}/refinish', 400, json={'hd_reconstruction': True})
                send('POST', refinish_route, 400, json={'triangles': 8000001, 'adaptive_finishing': True})
                adaptive = send('POST', refinish_route, 202, json={'triangles': 8000000, 'adaptive_finishing': True})
                state = wait_for(adaptive['id'], 'queued')
                assert adaptive['queued'] and adaptive['paused']
                assert state['settings']['adaptive_finishing'] is True
                assert state['settings']['triangles'] == 8000000
                options = state['settings']['generation_options']
                assert options['mesh_mode'] == 'direct' and not options['pre_simplify'] and not options['repair_holes']
                assert 'repair_surface' not in state['settings']
                send('POST', refinish_route, 400, json={'repair_surface': 'true'})
                fixed_repair = send('POST', refinish_route, 202, json={'triangles': 75000, 'repair_surface': True})
                adaptive_repair = send('POST', refinish_route, 202, json={
                    'triangles': 250000, 'adaptive_finishing': True, 'repair_surface': True,
                    'remesh_resolution': 768, 'texture_sampling': 'nearest'})
                for repair, target, use_adaptive in ((fixed_repair, 75000, False), (adaptive_repair, 250000, True)):
                    repair_id = repair['id']
                    settings = wait_for(repair_id, 'queued')['settings']
                    assert settings['repair_surface'] is True
                    assert settings.get('adaptive_finishing', False) is use_adaptive
                    assert settings['triangles'] == target
                    assert settings['parent_id'] == settings['finish_source_id'] == SOURCE
                    assert not (app.OUTPUT / repair_id / 'raw_state.pt').exists()
                    effective = options_for_job(settings)
                    assert effective['mesh_mode'] == 'remesh' and effective['remesh_project'] == .45
                    assert effective['repair_holes'] is True and effective['pre_simplify'] is False
                    assert effective['remesh_resolution'] == (768 if use_adaptive else 512)
                    assert effective['texture_sampling'] == ('nearest' if use_adaptive else 'trilinear')
                # Donors are explicit, immutable completed parents with exact export provenance.
                send('POST', refinish_route, 400, json={'normal_source': 'parent', 'bake_normals': False})
                send('POST', refinish_route, 400, json={'normal_source': 'parent', 'bake_normals': True})
                donor_id = 'c' * 32
                donor_folder = app.OUTPUT / donor_id
                donor_folder.mkdir()
                donor_mesh = trimesh.creation.icosphere(subdivisions=1)
                donor_mesh.visual = trimesh.visual.TextureVisuals(uv=np.zeros((len(donor_mesh.vertices), 2)))
                donor_bytes = donor_mesh.export(file_type='glb', include_normals=True)
                fingerprint = hashlib.sha256(donor_bytes).hexdigest()
                transform = dict(scale=2., translation=[1., 2., 3.], coordinate_system='y_up')
                donor_result = dict(finish_source_id=SOURCE, finishing=dict(normalization=transform, model_sha256=fingerprint))
                (donor_folder / 'model.glb').write_bytes(donor_bytes)
                app.write_json(donor_folder / 'settings.json', dict(read(source_folder / 'settings.json'),
                               source_kind='refinish', finish_source_id=SOURCE, parent_id=SOURCE))
                app.write_json(donor_folder / 'result.json', donor_result)
                app.write_json(donor_folder / 'status.json', dict(state='done', result=donor_result))
                donor_route = f'/api/jobs/{donor_id}/refinish'
                donor_info = send('GET', f'/api/jobs/{donor_id}/finishing-board')
                assert donor_info['normal_sources'] == ['decoded', 'parent']
                assert donor_info['parent_normal_source'] == dict(available=True, unavailable_reason=None)
                parent_bake = send('POST', donor_route, 202, json={'bake_normals': True, 'normal_source': 'parent'})
                saved = wait_for(parent_bake['id'], 'queued')['settings']
                assert saved['normal_source'] == 'parent' and saved['normal_source_id'] == donor_id
                assert saved['normal_source_model_sha256'] == fingerprint
                assert saved['normal_source_normalization'] == transform
                assert saved['finish_source_id'] == SOURCE and saved['parent_id'] == donor_id
                decoded_bake = send('POST', donor_route, 202, json={'bake_normals': True})
                saved_decoded = wait_for(decoded_bake['id'], 'queued')['settings']
                assert saved_decoded['normal_source'] == 'decoded' and 'normal_source_id' not in saved_decoded
                (donor_folder / 'model.glb').write_bytes(donor_bytes + b'changed')
                changed = send('POST', donor_route, 400, json={'bake_normals': True, 'normal_source': 'parent'})
                assert 'changed after' in changed['detail']
                (donor_folder / 'model.glb').write_bytes(donor_bytes)
                send('PATCH', '/api/queue', json={'paused': False})
                assert wait_for(adaptive['id'], 'done')['result']['neural_inferences'] == 0
                for repair in (fixed_repair, adaptive_repair):
                    assert wait_for(repair['id'], 'done')['result']['finish_source_id'] == SOURCE
                chosen = response['ids'][1]
                assert send('PATCH', route, json={'selected_id': chosen})['selected_id'] == chosen
                child_board = send('GET', f'/api/jobs/{chosen}/finishing-board')
                assert child_board['selected_id'] == chosen and child_board['source_triangles'] == 20_933_594
                assert read(source_folder / 'finishing-choice.json')['id'] == chosen
                assert {name: (source_folder / name).read_bytes() for name in baseline} == baseline
                assert send('PATCH', route, json={'selected_id': None})['selected_id'] is None
                print('PASS: atomic batch, cached repair dispatch, cache loss/retry, persisted choice, explicit verified HD donor and original preservation')
            finally:
                server.should_exit = True
                thread.join(timeout=8)


if __name__ == '__main__':
    run()
