"""Exercise opt-in face reconstruction through real API routes with the GPU worker paused."""
from io import BytesIO
import os
from pathlib import Path
import sys
import socket
from tempfile import TemporaryDirectory
from threading import Thread
import time
from unittest.mock import patch

import requests
import uvicorn
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(app, base):
    with requests.Session() as client:
        def post(path, expected, **kwargs):
            response = client.post(base + path, timeout=8, **kwargs)
            assert response.status_code == expected, (path, response.status_code, response.text[:500])
            return response.json()

        png = BytesIO()
        Image.new('RGBA', (64, 80), 'white').save(png, format='PNG')
        ref = ('reference.png', png.getvalue(), 'image/png')
        uploaded = post('/api/v1/uploads', 201, files={'file': ref})
        recipe = dict(upload_id=uploaded['id'], profile_id='dense_master', texture_method='trellis',
                      overrides=dict(asset_type='humanoid', resolution=1024))
        generate = '/api/v1/generations'
        ordinary = post(generate, 202, json=recipe)
        assert 'facial_head_enhancement' not in app.read_workspace_json(app.OUTPUT / ordinary['id'] / 'settings.json')
        enhanced = dict(recipe, facial_head_enhancement=True)
        with patch.object(app, 'facial_head_capability', return_value=dict(ready=False, reason='Install component')):
            assert (post(generate, 503, json=enhanced))['detail'] == 'Install component'
        with patch('facial_head_runtime.readiness', return_value=dict(ready=True, reason='')), \
             patch.object(app, 'detail_texturing_capability', return_value=dict(available=False, reason='Missing model')):
            assert app.facial_head_capability() == dict(ready=False, reason='Missing model')
            assert (post(generate, 503, json=enhanced))['detail'] == 'Missing model'
        with patch.object(app, 'facial_head_capability', return_value=dict(ready=True, reason='')):
            item = post(generate, 202, json=enhanced)
            folder = app.OUTPUT / item['id']
            settings = app.read_workspace_json(folder / 'settings.json')
            assert settings['facial_head_enhancement'] is True
            assert settings['profile_snapshot']['facial_head_enhancement'] is True
            for changes in (dict(engine='pixal3d_single'), dict(texture_method='multiview'),
                            dict(master_finishing='studio_768'), dict(master_finishing='hi3d_1024'),
                            dict(overrides={'asset_type': 'object'}), dict(overrides={'asset_type':'humanoid','resolution':512})):
                post(generate, 400, json={**enhanced, **changes})
            post(generate, 422, json={**enhanced, 'facial_head_enhancement': 'false'})
            post('/api/generate-multiview', 400, files={'image': ref}, data={'facial_head_enhancement':'true'})
        with patch.object(app, 'WORKSPACE_CONFIG', {'server': True}):
            assert 'desktop' in (post(generate, 503, json=enhanced))['detail']
        app.write_json(folder / 'status.json', dict(state='error', progress=0))
        retry = f"/api/v1/queue/{item['id']}/retry"
        with patch.object(app, 'facial_head_capability', return_value=dict(ready=False,reason='Install component')):
            post(retry, 503, json={})
            new = post(retry, 202, json={'facial_head_enhancement': False})
        retried = app.read_workspace_json(app.OUTPUT / new['id'] / 'settings.json')
        assert 'facial_head_enhancement' not in retried
        assert 'facial_head_enhancement' not in retried['profile_snapshot']
        assert app.read_workspace_json(folder / 'settings.json') == settings


if __name__ == '__main__':
    with TemporaryDirectory(prefix='trellis-face-api-') as temporary:
        env = {f'TRELLIS_{k}': str(Path(temporary)/v) for k,v in (
            ('OUTPUT_DIR','outputs'), ('TRASH_DIR','trash'), ('EXPORT_DIR','exports'),
            ('STATE_DIR','state'), ('PROFILES_FILE','profiles.json'))}
        with patch.dict(os.environ, env):
            import app
            with patch.object(app, 'status', return_value={'ready': True}), \
                 patch.object(app, 'generation_capabilities', return_value=([512,1024], [1024,2048])):
                with socket.socket() as port_probe:
                    port_probe.bind(('127.0.0.1', 0))
                    port = port_probe.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(app.app, host='127.0.0.1', port=port,
                                                       lifespan='off', log_level='error'))
                thread = Thread(target=server.run, daemon=True)
                thread.start()
                try:
                    for _ in range(100):
                        if server.started:
                            break
                        time.sleep(.05)
                    assert server.started
                    verify(app, f'http://127.0.0.1:{port}')
                finally:
                    server.should_exit = True
                    thread.join(10)
                    assert not thread.is_alive()
    print('PASS optional face enhancement API, validation, compatibility and reversible recipe replay.')
