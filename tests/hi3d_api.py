"""Validate Hi3D admission and cache provenance through real isolated HTTP routes."""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
import io
import json
import os
import socket
import sys
import time

from PIL import Image
import requests
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def png(mode='RGBA'):
    image = Image.new(mode, (32, 32), (100, 140, 170, 0) if mode == 'RGBA' else (100, 140, 170))
    if mode == 'RGBA':
        for y in range(8, 24):
            for x in range(8, 24):
                image.putpixel((x, y), (100, 140, 170, 255))
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def run():
    with TemporaryDirectory(prefix='trellis-hi3d-api-') as temporary:
        private = Path(temporary)
        for key, name in (('OUTPUT_DIR', 'outputs'), ('TRASH_DIR', 'trash'), ('EXPORT_DIR', 'exports'),
                          ('STATE_DIR', 'state'), ('PROFILES_FILE', 'profiles.json')):
            os.environ['TRELLIS_' + key] = str(private / name)
        import app
        import studio_api
        from api_contract import Generation, MultiViewGeneration, Refinish, FinishingOptions
        from generation_options import validate_create_master_finishing
        from studio_workspace import read

        for method in ('hi3d_512', 'hi3d_1024'):
            assert Generation(upload_id='f' * 32, master_finishing=method).master_finishing == method
            assert Refinish(master_finishing=method).master_finishing == method
            validate_create_master_finishing(method, preset='dense_master', resolution=512, triangles=1_200_000)
            for change in ({'preset': 'missing'}, {'resolution': 2048}, {'engine': 'pixal3d_single'},
                           {'hd_reconstruction': True}, {'repair_surface': True}):
                options = dict(preset='dense_master', resolution=512, triangles=1_200_000)
                try:
                    validate_create_master_finishing(method, **{**options, **change})
                except ValueError:
                    pass
                else:
                    raise AssertionError(change)

        identifiers = {name: char * 32 for name, char in (
            ('valid', 'a'), ('high', 'b'), ('pixal', 'c'), ('opaque', 'd'), ('variant', 'e'))}
        for name, identifier in identifiers.items():
            directory = app.OUTPUT / identifier
            directory.mkdir()
            settings = dict(name=name, preset='dense_master', resolution=512, seed=42, height_m=1,
                            triangles=1_200_000, texture_size=2048, keep_finishing_source=True,
                            remove_bg=False)
            if name == 'high':
                settings['resolution'] = 1024
            if name == 'pixal':
                settings.update(engine='pixal3d', view_mode='single')
            if name == 'variant':
                settings.update(source_kind='refinish', finish_source_id=identifiers['valid'])
                settings['generation_options'] = dict(hi3d_steps=31, hi3d_seed=23)
                settings['profile_snapshot'] = dict(generation_options=settings['generation_options'])
            app.write_json(directory / 'settings.json', settings)
            app.write_json(directory / 'status.json', dict(state='done', progress=100))
            (directory / 'model.glb').write_bytes(b'completed model fixture')
            (directory / 'raw_state.pt').write_bytes(b'cache fixture')
            (directory / 'input.png').write_bytes(png())
            (directory / 'prepared.png').write_bytes(png('RGB' if name == 'opaque' else 'RGBA'))

        app.STUDIO.workspace.queue['paused'] = True
        app.STUDIO.workspace.save_queue()
        original_status = app.status
        ready = dict(available=True, reason='')
        unavailable = dict(available=False, reason='Install the optional Hi3D component.')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        server = uvicorn.Server(uvicorn.Config(app.app, host='127.0.0.1', port=port, log_level='error'))
        thread = Thread(target=server.run, daemon=True)

        def call(method, route, code=200, **kwargs):
            response = requests.request(method, base + route, timeout=8, **kwargs)
            assert response.status_code == code, (route, response.status_code, response.text[:500])
            return response.json()

        with patch.object(app, 'hi3d_status', return_value=ready), \
             patch.object(studio_api, 'hi3d_status', return_value=ready), \
             patch.object(app, 'detail_texturing_capability', return_value=ready), \
             patch.object(app, 'wtivo_capability', return_value=(True, '')), \
             patch.object(app, 'find_blender', return_value=Path('fixture-blender.exe')), \
             patch.object(app, 'status', side_effect=lambda: dict(original_status(), ready=True)), \
             patch.object(app, 'generation_capabilities', return_value=([512, 1024], [1024, 2048, 4096])):
            thread.start()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(.05)
                assert server.started
                methods = call('GET', '/api/status')['create_master_finishing']
                assert methods['hi3d_512']['available'] and methods['hi3d_1024']['available']
                schema = call('GET', '/api/openapi.json')['components']['schemas']
                assert 'hi3d_512' in schema['Generation']['properties']['master_finishing']['anyOf'][0]['enum']
                for name in ('valid', 'high', 'pixal', 'opaque', 'variant'):
                    route = f'/api/v1/models/{identifiers[name]}/finishing-board'
                    info = call('GET', route)
                    FinishingOptions.model_validate(info)
                    eligible = name in ('valid', 'high', 'variant')
                    assert info['master_finishing']['methods']['hi3d_512']['available'] == eligible, (name, info)
                    assert (info['hi3d_options'] is not None) is eligible
                    if eligible:
                        assert info['hi3d_options']['hi3d_steps'] == (31 if name == 'variant' else 25)
                    if not eligible:
                        call('POST', f'/api/v1/models/{identifiers[name]}/refinish', 400,
                             json={'master_finishing': 'hi3d_512'})
                for method in ('hi3d_512', 'hi3d_1024'):
                    route = f'/api/v1/models/{identifiers["variant"]}/refinish'
                    identifier = call('POST', route, 202, json={'master_finishing': method, 'texture_size': 2048,
                                      'hi3d_options': {'hi3d_seed': 180, 'hi3d_scheduler': 'euler'}})['id']
                    settings = read(app.OUTPUT / identifier / 'settings.json')
                    assert settings['master_finishing'] == method
                    assert settings['finish_source_id'] == identifiers['valid']
                    assert not any(settings.get(key) for key in ('adaptive_finishing', 'hd_reconstruction', 'wtivo_reconstruction'))
                    assert settings['generation_options']['hi3d_steps'] == 31
                    assert settings['generation_options']['hi3d_seed'] == 180
                    assert settings['generation_options']['hi3d_scheduler'] == 'euler'
                    assert settings['profile_snapshot']['generation_options'] == settings['generation_options']
                recipe = {'master_finishing': 'hi3d_1024', 'texture_size': 2048}
                board_route = f'/api/v1/models/{identifiers["variant"]}/finishing-board'
                batch = call('POST', board_route, 202, json={'variants': [
                    {**recipe, 'hi3d_options': {'hi3d_steps': 18}},
                    {**recipe, 'hi3d_options': {'hi3d_steps': 32}},
                ]})
                assert batch['source_id'] == identifiers['valid']
                for identifier, steps in zip(batch['ids'], (18, 32), strict=True):
                    folder = app.OUTPUT / identifier
                    settings = read(folder / 'settings.json')
                    assert settings['finish_source_id'] == identifiers['valid']
                    assert settings['generation_options']['hi3d_steps'] == steps
                    assert settings['generation_options']['hi3d_seed'] == 23
                    assert not (folder / 'raw_state.pt').exists()
                app.write_json(folder / 'status.json', dict(state='error', progress=0))
                retried = call('POST', f'/api/v1/queue/{identifier}/retry', 202, json={})['id']
                retry_settings = read(app.OUTPUT / retried / 'settings.json')
                assert retry_settings['finish_source_id'] == identifiers['valid']
                assert retry_settings['generation_options'] == settings['generation_options']
                call('POST', board_route, 400, json={'variants': [recipe, {**recipe, 'hi3d_options': {'hi3d_steps': 31}}]})
                for controls in ({'hi3d_steps': 0}, {'hi3d_tiled_decode': 'false'}, {'shape_steps': 20}):
                    call('POST', route, 422, json={**recipe, 'hi3d_options': controls})
                    call('POST', f'/api/jobs/{identifiers["variant"]}/refinish', 400,
                         json={**recipe, 'hi3d_options': controls})
                call('POST', route, 422, json={'master_finishing': 'studio_768', 'hi3d_options': {'hi3d_steps': 20}})
                call('POST', route, 422, json={'mesh_mode': 'direct', 'hi3d_options': {'hi3d_steps': 20}})
                original = app.OUTPUT / identifiers['valid']
                assert (original / 'raw_state.pt').read_bytes() == b'cache fixture'
                missing = app.OUTPUT / identifiers['valid'] / 'prepared.png'
                cutout = missing.read_bytes()
                missing.unlink()
                try:
                    route = f'/api/v1/models/{identifiers["valid"]}'
                    assert not call('GET', route + '/finishing-board')['master_finishing']['methods']['hi3d_512']['available']
                    call('POST', route + '/refinish', 400, json={'master_finishing': 'hi3d_1024'})
                finally:
                    missing.write_bytes(cutout)
                with patch.object(studio_api, 'hi3d_status', return_value=unavailable):
                    route = f'/api/v1/models/{identifiers["valid"]}'
                    assert not call('GET', route + '/finishing-board')['master_finishing']['methods']['hi3d_512']['available']
                    call('POST', route + '/refinish', 503, json={'master_finishing': 'hi3d_512'})
                upload = call('POST', '/api/v1/uploads', 201,
                              files={'file': ('cutout.png', png(), 'image/png')})['id']
                generation = dict(upload_id=upload, profile_id='dense_master', master_finishing='hi3d_512',
                                  overrides=dict(resolution=512, remove_bg=False))
                identifier = call('POST', '/api/v1/generations', 202, json=generation)['id']
                settings = read(app.OUTPUT / identifier / 'settings.json')
                assert settings['keep_finishing_source'] and settings['master_finishing'] == 'hi3d_512'
                assert settings['resolution'] == 512 and settings['remove_bg'] is False
                assert not any(settings.get(key) for key in ('adaptive_finishing', 'hd_reconstruction', 'wtivo_reconstruction'))
                app.write_json(app.OUTPUT / identifier / 'status.json', dict(state='error', progress=0))
                retried = call('POST', f'/api/v1/queue/{identifier}/retry', 202,
                               json={'resolution': 1024, 'texture_size': 1024})['id']
                retry_settings = read(app.OUTPUT / retried / 'settings.json')
                assert retry_settings['master_finishing'] == 'hi3d_512' and retry_settings['resolution'] == 1024
                call('POST', '/api/v1/generations', 202,
                     json={**generation, 'overrides': {'resolution': 1024}})
                call('POST', '/api/v1/generations', 400, json={**generation, 'engine': 'pixal3d_single'})
                call('POST', '/api/v1/generations/multiview', 400,
                     json=dict(upload_id=upload, left_upload_id=upload, profile_id='dense_master',
                               master_finishing='hi3d_1024'))
                study = next(p for p in call('GET', '/api/v1/profiles')['profiles'] if p['id'] == 'detail_study')
                recipe = study['settings']
                custom = call('POST', '/api/profiles', 201, json=dict(name='Detail Study copy', settings=recipe))
                assert custom['settings'] == recipe
                study_request = dict(upload_id=upload, profile_id='detail_study')
                identifier = call('POST', '/api/v1/generations', 202, json=study_request)['id']
                folder = app.OUTPUT / identifier
                settings = read(folder / 'settings.json')
                assert settings['master_finishing'] == 'hi3d_1024'
                assert settings['texture_size'] == 4096 and settings['triangles'] == 1_000_000
                assert settings['retexture_after_refinement'] is settings['profile_snapshot']['retexture_after_refinement'] is True
                options = settings['generation_options']
                assert [options[f'{phase}_steps'] for phase in ('structure', 'shape', 'texture')] == [12, 24, 12]
                assert options['texture_guidance'] == 1 and options['hi3d_steps'] == 25
                app.write_json(folder / 'status.json', dict(state='error', progress=0))
                call('POST', f'/api/v1/queue/{identifier}/retry', 400, json={'resolution': 512})
                retry = call('POST', f'/api/v1/queue/{identifier}/retry', 202, json={'texture_size': 2048})['id']
                assert read(app.OUTPUT / retry / 'settings.json')['retexture_after_refinement'] is True
                identifier = call('POST', '/api/v1/generations', 202, json={
                    **study_request, 'retexture_after_refinement': False,
                    'overrides': dict(advanced_settings={**recipe['advanced'], 'hi3d_steps': 18}),
                })['id']
                settings = read(app.OUTPUT / identifier / 'settings.json')
                assert 'retexture_after_refinement' not in settings and settings['generation_options']['hi3d_steps'] == 18
                call('POST', '/api/v1/generations', 400,
                     json={**study_request, 'overrides': {'resolution': 512}})
                with patch.object(app, 'detail_texturing_capability', return_value=unavailable):
                    call('POST', '/api/v1/generations', 503, json=study_request)
                game = next(p for p in call('GET', '/api/v1/profiles')['profiles'] if p['id'] == 'game_d')
                custom_game = call('POST', '/api/profiles', 201, json=dict(name='Custom Game with Hi3D', settings={
                    **game['settings'], 'master_finishing': 'hi3d_1024', 'retexture_after_refinement': True,
                }))
                for method in ('studio_768', 'wtivo_1024', 'hi3d_512', 'hi3d_1024'):
                    identifier = call('POST', '/api/v1/generations', 202, json=dict(
                        upload_id=upload, profile_id='game_d', master_finishing=method))['id']
                    settings = read(app.OUTPUT / identifier / 'settings.json')
                    assert settings['master_finishing'] == method and settings['keep_finishing_source'] is True
                    assert settings['preset'] == 'game_d' and settings['triangles'] == 28000
                identifier = call('POST', '/api/v1/generations', 202,
                                  json=dict(upload_id=upload, profile_id=custom_game['id']))['id']
                settings = read(app.OUTPUT / identifier / 'settings.json')
                assert settings['preset'] == 'game_d' and settings['profile']['id'] == custom_game['id']
                assert settings['master_finishing'] == 'hi3d_1024' and settings['retexture_after_refinement'] is True
                profile_path = '/api/profiles/' + custom_game['id']
                call('DELETE', '/api/profiles/game_d', 403)
                assert call('DELETE', profile_path) == {'id': custom_game['id'], 'deleted': True}
                call('DELETE', profile_path, 404)
                assert read(app.OUTPUT / identifier / 'settings.json') == settings
                assert methods['none']['available']
                assert MultiViewGeneration(upload_id=upload, master_finishing='none').master_finishing == 'none'
                for profile_id in ('game_d', 'dense_master'):
                    identifier = call('POST', '/api/v1/generations', 202, json=dict(
                        upload_id=upload, profile_id=profile_id, master_finishing='none',
                        overrides=dict(resolution=512, keep_finishing_source=False)))['id']
                    settings = read(app.OUTPUT / identifier / 'settings.json')
                    assert settings['master_finishing'] == 'none' and settings['keep_finishing_source'] is True
                    assert not any(settings.get(key) for key in ('adaptive_finishing', 'hd_reconstruction', 'wtivo_reconstruction'))
                    assert settings['generation_options']['mesh_mode'] == 'direct'
                    assert not any(settings['generation_options'][key] for key in ('pre_simplify', 'repair_holes'))
                no_finish = call('POST', '/api/profiles', 201, json=dict(name='Decoded source', settings={
                    **game['settings'], 'master_finishing': 'none', 'triangles': 4_000_000,
                }))
                identifier = call('POST', '/api/v1/generations', 202,
                                  json=dict(upload_id=upload, profile_id=no_finish['id']))['id']
                folder = app.OUTPUT / identifier
                assert read(folder / 'settings.json')['master_finishing'] == 'none'
                app.write_json(folder / 'status.json', dict(state='error', progress=0))
                retried = call('POST', f'/api/v1/queue/{identifier}/retry', 202, json={'resolution': 512})['id']
                assert read(app.OUTPUT / retried / 'settings.json')['master_finishing'] == 'none'
                app.write_json(folder / 'status.json', dict(state='done', progress=100))
                (folder / 'prepared.png').write_bytes(png())
                (folder / 'raw_state.pt').write_bytes(b'decoded mesh fixture')
                (folder / 'model.glb').write_bytes(b'completed model fixture')
                variant = call('POST', f'/api/v1/models/{identifier}/refinish', 202,
                               json={'master_finishing': 'hi3d_1024'})['id']
                variant_settings = read(app.OUTPUT / variant / 'settings.json')
                assert variant_settings['master_finishing'] == 'hi3d_1024' and variant_settings['finish_source_id'] == identifier
                assert read(folder / 'settings.json')['master_finishing'] == 'none'
                call('POST', '/api/v1/generations', 400, json=dict(upload_id=upload, master_finishing='none',
                                                                 retexture_after_refinement=True))
                call('POST', f'/api/v1/models/{identifiers["valid"]}/refinish', 422, json={'master_finishing': 'none'})
            finally:
                server.should_exit = True
                thread.join(8)
                assert not thread.is_alive()
        print('PASS Hi3D API contracts, native resolution/alpha/cache admission, linked variants and queued generation.')


if __name__ == '__main__':
    run()
