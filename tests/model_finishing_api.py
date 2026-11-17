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
from api_contract import PROTECTED_REGION_LIMIT
from generation_view_projection import digest, generation_reference_name, save_generation_views
from pixal3d_runtime import CAMERA_FOV, camera_matrix
from server_lan import account, call, login, PASSWORD, serve
from studio_workspace import read, write


def fixture_glb():
    payload = json.dumps({'asset': {'version': '2.0'}, 'meshes': [{'primitives': []}]}).encode()
    payload += b' ' * (-len(payload) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20 + len(payload), len(payload), 0x4e4f534a) + payload


def calibrate(source):
    views = []
    for role, azimuth in (('front', 0), ('left', 40), ('back', 180), ('right', -40)):
        name = generation_reference_name(role)
        Image.new('RGBA', (1024, 1024), '#776644ff').save(source / name)
        views.append(dict(role=role, azimuth=azimuth, sha256=digest(source / name), camera_angle_x=CAMERA_FOV,
                          transform_matrix=camera_matrix(azimuth)))
    save_generation_views(source, dict(scale=1.5, translation=[0, .75, 0], coordinate_system='y_up'), views)
    return views


def run():
    support = lambda _: {'supported': True, 'reason': None}
    prototype = {
        'texture_projection': SimpleNamespace(MAX_REFERENCE_PIXELS=16_777_216,
                                              inspect_texture_projection=support,
                                              normalize_projection_options=lambda options: options),
        'baked_game_copy': SimpleNamespace(inspect_baked_game_copy=lambda _: {
                                               **support(None), 'protected_region_limit': PROTECTED_REGION_LIMIT},
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
            write(source / 'settings.json', dict(name='Witness', asset_type='humanoid', keep_finishing_source=True,
                                                 hd_reconstruction=True))
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
            assert 'back' in projection['views'] and 'custom' in projection['views']
            assert projection['camera_projections'] == ['orthographic', 'perspective']
            assert projection['max_views'] == 2
            schema = call(base, 'GET', '/api/openapi.json', client=alice).json()
            post = schema['paths']['/api/v1/models/{identifier}/texture-projection']['post']
            recipes = post['requestBody']['content']['application/json']['schema']['anyOf']
            assert {item['$ref'].rsplit('/', 1)[-1] for item in recipes} == {
                'TextureProjection', 'MultiViewTextureProjection', 'GenerationViewTextureProjection',
                'GenerationReferenceTextureProjection'}
            views = schema['components']['schemas']['MultiViewTextureProjection']['properties']['views']
            assert views['minItems'] == views['maxItems'] == 2
            assert not projection['generation_views']['supported'] and not projection['generation_views']['views']
            assert not projection['generation_reference']['supported']
            generation = {'method': 'generation_views'}
            projection_url = url + '/' + routes[0]
            call(base, 'POST', projection_url, 400, alice, json=generation)
            game_url = url + '/' + routes[1]
            game_support = call(base, 'GET', game_url, client=alice).json()
            assert game_support['default_triangles'] == 14000
            assert game_support['protected_region_limit'] == PROTECTED_REGION_LIMIT
            regions = schema['components']['schemas']['BakedGameCopy']['properties']['protected_regions']
            assert regions['maxItems'] == PROTECTED_REGION_LIMIT
            region = dict(center=[0, .8, .1], radius=.18, strength=.8)
            for invalid in ([region] * (PROTECTED_REGION_LIMIT + 1), [{**region, 'center': [0, 1]}],
                            [{**region, 'radius': 0}], [{**region, 'strength': True}]):
                call(base, 'POST', game_url, 422, alice, json={'protected_regions': invalid})
            call(base, 'POST', game_url, 404, bob, json={'protected_regions': [region]})
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
            oblique = {**linked, 'camera': dict(view='custom', projection='perspective',
                       frame=[-.5, -.5, .5, .5], origin=[2.4, 0, -3.2],
                       basis=[[-.8, 0, -.6], [0, 1, 0], [.6, 0, -.8]])}
            upload_by_alice = call(base, 'POST', '/api/v1/uploads', 201, alice,
                                   files={'file': ('ref.png', stream.getvalue(), 'image/png')}).json()
            side = {**oblique, 'reference': None, 'upload_id': upload_by_alice['id']}
            multiview = {'views': [options, side]}
            for invalid in ({'views': [options]}, {'views': [options, side, side]},
                            {**options, **multiview}, {'views': [options, {**side, 'reference': 'input'}]}):
                call(base, 'POST', url + '/' + routes[0], 422, alice, json=invalid)
            call(base, 'POST', url + '/' + routes[0], 400, alice,
                 json={'views': [options, {**side, 'upload_id': upload['id']}]})
            call(base, 'POST', url + '/' + routes[0], 400, alice,
                 json={'views': [options, {**options, 'reference': 'prepared'}]})
            call(base, 'POST', url + '/' + routes[0], 404, bob, json=multiview)
            oversized = io.BytesIO()
            Image.new('1', (4097, 4096)).save(oversized, format='PNG')
            oversized_upload = call(base, 'POST', '/api/v1/uploads', 201, alice,
                                    files={'file': ('large.png', oversized.getvalue(), 'image/png')}).json()
            rejected = call(base, 'POST', url + '/' + routes[0], 400, alice,
                            json={'views': [options, {**side, 'upload_id': oversized_upload['id']}]})
            assert 'view 2' in rejected.json()['detail']
            operations = [(routes[0], options), (routes[0], linked), (routes[0], oblique),
                          (routes[0], multiview),
                          (routes[1], dict(profile='humanoid', triangles=14000, protected_regions=[region]))]
            for endpoint, recipe in operations:
                queued = call(base, 'POST', url + '/' + endpoint, 202, alice, json=recipe).json()
                child = source.parent / queued['id']
                settings = read(child / 'settings.json')
                assert settings['parent_id'] == identifier and 'keep_finishing_source' not in settings
                assert 'hd_reconstruction' not in settings
                assert (child / 'source.glb').read_bytes() == glb
                assert read(child / 'server-work.json')['script'] == 'model_finishing_worker.py'
                request = read(child / 'finishing-request.json')
                if recipe is multiview:
                    first, second = request['views']
                    assert 'options' not in request and 'reference_file' not in request
                    assert [first['reference_file'], second['reference_file']] == ['projection-source-1.png', 'projection-source-2.png']
                    assert (child / first['reference_file']).read_bytes() == (source / 'input.png').read_bytes()
                    assert (child / second['reference_file']).read_bytes() == stream.getvalue()
                    assert first['options']['camera']['view'] == 'front' and second['options']['camera'] == side['camera']
                    assert second['options']['source_polygon'] == outline
                    assert all('reference' not in item['options'] and 'upload_id' not in item['options']
                               for item in request['views'])
                elif endpoint == routes[0]:
                    assert request['reference_file'] == 'projection-source.png' and 'views' not in request
                else:
                    assert request['options']['protected_regions'] == [region]
                if recipe in (linked, oblique):
                    saved = request['options']
                    assert saved['linked_selection'] and saved['source_polygon'] == outline
                    if recipe is oblique:
                        assert saved['camera'] == recipe['camera']
                status = call(base, 'GET', queued['status_url'], client=alice).json()
                assert status['state'] == 'queued' and not status['media']['available']
                call(base, 'GET', queued['status_url'], 404, bob)
                assert (source / 'model.glb').read_bytes() == glb
            assert len(state.store.jobs(users[0]['id'])) == 5
            settings = read(source / 'settings.json')
            write(source / 'settings.json', {**settings, 'engine': 'pixal3d'})
            assert not call(base, 'GET', projection_url, client=alice).json()['generation_views']['supported']
            calibrated = calibrate(source)
            projection = call(base, 'GET', projection_url, client=alice).json()
            assert projection['generation_views'] == dict(supported=True, reason='', views=['front', 'left', 'back', 'right'])
            assert not projection['generation_reference']['supported']
            call(base, 'POST', projection_url, 422, alice, json={**generation, **options})
            call(base, 'POST', projection_url, 422, alice, json={**generation, **multiview})
            call(base, 'POST', projection_url, 404, bob, json=generation)
            queued = call(base, 'POST', projection_url, 202, alice, json=generation).json()
            child = source.parent / queued['id']
            request = read(child / 'finishing-request.json')
            assert request['generation_views']['views'] == calibrated
            assert 'options' not in request and 'reference_file' not in request and 'views' not in request
            assert not (child / '.generation-views.json').exists()
            for view in calibrated:
                assert digest(child / generation_reference_name(view['role'], staged=True)) == view['sha256']
            Image.new('RGBA', (1024, 1024), 'white').save(source / 'prepared-left.png')
            projection = call(base, 'GET', projection_url, client=alice).json()
            assert projection['supported'] and not projection['generation_views']['supported']
            call(base, 'POST', projection_url, 400, alice, json=generation)
            source_settings = {**settings, 'preset': 'dense_master'}
            write(source / 'settings.json', source_settings)
            aligned = {key: value for key, value in oblique.items() if key != 'reference'}
            aligned['method'] = 'generation_reference'
            call(base, 'POST', projection_url, 400, alice, json=aligned)  # Opaque saved reference.
            prepared = source / 'prepared.png'
            cutout = Image.new('RGBA', (128, 96), (0, 0, 0, 0))
            cutout.paste('#776644', (16, 8, 112, 88))
            cutout.save(prepared)
            cap = call(base, 'GET', projection_url, client=alice).json()
            assert cap['generation_reference'] == dict(supported=True, reason='', reference='prepared')
            assert not cap['generation_views']['supported']
            call(base, 'POST', projection_url, 422, alice, json={**aligned, 'reference': 'input'})
            call(base, 'POST', projection_url, 422, alice, json={**aligned, 'upload_id': upload_by_alice['id']})
            call(base, 'POST', projection_url, 404, bob, json=aligned)
            queued = call(base, 'POST', projection_url, 202, alice, json=aligned).json()
            child = source.parent / queued['id']
            request = read(child / 'finishing-request.json')
            assert request['generation_reference'] == dict(source_sha256=digest(source / 'model.glb'),
                                                            reference_sha256=digest(prepared))
            assert (child / request['reference_file']).read_bytes() == prepared.read_bytes()
            assert request['options']['camera'] == aligned['camera']
            assert 'generation_views' not in request and 'method' not in request['options']
            assert (source / 'model.glb').read_bytes() == glb
            write(source / 'settings.json', {**source_settings, 'source_kind': 'refinish'})
            assert call(base, 'GET', projection_url, client=alice).json()['generation_reference']['supported']
            write(source / 'settings.json', {**source_settings, 'source_kind': 'baked_game_copy'})
            assert not call(base, 'GET', projection_url, client=alice).json()['generation_reference']['supported']
            call(base, 'POST', projection_url, 400, alice, json=aligned)
            assert state.store.get_user(users[0]['id'])['credits'] == 0
    print('PASS: local derived model requests, source preservation, parent links, queue, credits and isolation.')


if __name__ == '__main__':
    run()
