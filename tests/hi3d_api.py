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
        from api_contract import Generation, Refinish, FinishingOptions
        from generation_options import validate_create_master_finishing
        from studio_workspace import read

        for method in ('hi3d_512', 'hi3d_1024'):
            assert Generation(upload_id='f' * 32, master_finishing=method).master_finishing == method
            assert Refinish(master_finishing=method).master_finishing == method
            validate_create_master_finishing(method, preset='dense_master', resolution=512, triangles=1_200_000)
            for change in ({'preset': 'game_d'}, {'resolution': 2048}, {'engine': 'pixal3d_single'},
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
             patch.object(app, 'find_blender', return_value=Path('fixture-blender.exe')), \
             patch.object(app, 'status', side_effect=lambda: dict(original_status(), ready=True)), \
             patch.object(app, 'generation_capabilities', return_value=([512, 1024], [1024, 2048])):
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
                    if not eligible:
                        call('POST', f'/api/v1/models/{identifiers[name]}/refinish', 400,
                             json={'master_finishing': 'hi3d_512'})
                for method in ('hi3d_512', 'hi3d_1024'):
                    route = f'/api/v1/models/{identifiers["variant"]}/refinish'
                    identifier = call('POST', route, 202, json={'master_finishing': method, 'texture_size': 2048})['id']
                    settings = read(app.OUTPUT / identifier / 'settings.json')
                    assert settings['master_finishing'] == method
                    assert settings['finish_source_id'] == identifiers['valid']
                    assert not any(settings.get(key) for key in ('adaptive_finishing', 'hd_reconstruction', 'wtivo_reconstruction'))
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
            finally:
                server.should_exit = True
                thread.join(8)
                assert not thread.is_alive()
        print('PASS Hi3D API contracts, native resolution/alpha/cache admission, linked variants and queued generation.')


if __name__ == '__main__':
    run()
