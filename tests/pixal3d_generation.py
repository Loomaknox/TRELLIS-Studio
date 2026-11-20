
"""Reference previews, Pixal3D multipart, typed REST and queue dispatch without inference."""
from pathlib import Path
from tempfile import TemporaryDirectory
from html.parser import HTMLParser
import base64
import io
import json
import os
import re
import socket
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw
import requests

ROOT = Path(__file__).resolve().parents[1]

def png(colour=(90, 110, 120, 255)):
    stream = io.BytesIO()
    Image.new('RGBA', (36, 40), colour).save(stream, 'PNG')
    return stream.getvalue()

def upload(data=None):
    return ('reference.png', png() if data is None else data, 'image/png')


def silhouette(width, colour):
    image = Image.new('RGBA', (96, 128), (10, 20, 30, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((48 - width // 2, 16, 48 + width // 2, 111), fill=colour)
    draw.line((2, 16, 2, 111), fill=colour)
    stream = io.BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


def image_bytes(data):
    with Image.open(io.BytesIO(data)) as image:
        return np.array(image)


def preview_image(view, key):
    return image_bytes(base64.b64decode(view[key].split(',', 1)[1]))


with TemporaryDirectory(prefix='trellis-pixal-api-') as tmp:
    root = Path(tmp)
    with socket.socket() as port_probe:
        port_probe.bind(('127.0.0.1', 0))
        port = port_probe.getsockname()[1]
    env = dict(os.environ, PYTHONUTF8='1', TRELLIS_PORT=str(port))
    for key, name in [('OUTPUT_DIR','outputs'), ('TRASH_DIR','trash'), ('EXPORT_DIR','exports'),
                      ('STATE_DIR','state'), ('PROFILES_FILE','profiles.json')]:
        env['TRELLIS_'+key] = str(root / name)

    bootstrap = """
from pathlib import Path
import app
import uvicorn
original_status = app.status
app.status = lambda: dict(original_status(), ready=True)
app.generation_capabilities = lambda: ([512, 1024], [1024, 2048])
app.pixal3d_runtime_status = lambda root: {
    'ready': (app.OUTPUT.parent / 'ready').is_file(), 'message': 'Install Pixal3D.',
    'single_image': {
        'ready': (app.OUTPUT.parent / 'single-ready').is_file(), 'message': 'Install Pixal3D Single image.',
    },
    'face_projection': {
        'ready': (app.OUTPUT.parent / 'face-ready').is_file(), 'message': 'Install face detector.',
    },
}
app.create_master_finishing_capabilities = lambda: {
    'studio_768': {'available': True, 'reason': ''},
    'wtivo_1024': {'available': (app.OUTPUT.parent / 'wtivo-ready').is_file(), 'reason': 'Install WTiVo.'},
}
def launch(folder, script, **kwargs):
    app.write_json(folder / 'worker-test.json', {'script': script})
    app.write_json(folder / 'status.json', {'state': 'done', 'stage': 'Test worker completed', 'progress': 100})
app.launch_worker = launch
config = uvicorn.Config(app.app, host='127.0.0.1', port=app.PORT, log_level='warning')
app.SERVER = uvicorn.Server(config)
app.SERVER.run()
"""
    base = 'http://127.0.0.1:' + str(port)
    def request(method, route, expected=200, **kwargs):
        response = requests.request(method, base + route, timeout=8, **kwargs)
        assert response.status_code == expected, (route, response.status_code, response.text[:500])
        return response
    with (root / 'server.log').open('wb') as log:
        proc = subprocess.Popen([sys.executable, '-c', bootstrap], cwd=ROOT, env=env,
                                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(80):
                try:
                    status = request('GET', '/api/status').json()
                    break
                except requests.ConnectionError:
                    time.sleep(.1)
            else:
                raise RuntimeError((root/'server.log').read_text(encoding='utf-8'))
            assert status['default_profile'] == 'game_d' and not status['pixal3d']['ready']
            page = request('GET', '/')
            assert page.headers['cache-control'] == 'no-cache, must-revalidate'
            assert status['ui_revision'] in page.text
            # The visual refresh adds layout classes to the same source card.
            card_match = re.search(r'<section\b[^>]*class="[^"]*\breference-card\b[^"]*"[^>]*>', page.text)
            assert card_match, 'The source reference card is missing.'
            card = page.text[card_match.end():].split('</section>', 1)[0]
            class ReferenceControls(HTMLParser):
                def handle_starttag(self, tag, attrs):
                    attrs = dict(attrs)
                    if attrs.get('id'):
                        controls[attrs['id']] = (tag, attrs)
            controls = {}
            ReferenceControls().feed(card)
            image_tag, image_attrs = controls['image']
            assert image_tag == 'input' and image_attrs['type'] == 'file' and 'required' in image_attrs
            button_tag, button_attrs = controls['addReferenceView']
            assert button_tag == 'button' and button_attrs['type'] == 'button'
            assert button_attrs['aria-controls'] == 'supplementalViews'
            extra_tag, extra_attrs = controls['supplementalViews']
            assert extra_tag == 'fieldset' and 'hidden' in extra_attrs and 'disabled' in extra_attrs
            assert not status['generation_methods']['pixal3d_single']['ready']
            files = {'image': upload(), 'left_image': upload()}
            request('POST', '/api/generate-multiview', 503, files=files)
            (root/'ready').touch()
            request('POST', '/api/generate-multiview', 400, files={'image': upload()})
            request('POST', '/api/generate-multiview', 400, files=files, data={'side_angle': 45})
            request('POST', '/api/generate-multiview', 400, files={**files, 'right_image': upload(b'broken')})
            request('POST', '/api/generate-multiview', 400, files={**files, 'right_image': upload(png((0,0,0,0)))})
            denied = request('POST', '/api/generate-multiview', 503, files=files, data={'reproject_face':'true'})
            assert denied.json()['detail'] == 'Install face detector.'
            assert not any((root/'outputs').iterdir())

            request('PATCH', '/api/queue', json={'paused': True})
            front = upload(silhouette(24, (165, 98, 40, 255)))
            left = upload(silhouette(48, (70, 155, 190, 255)))
            back = upload(silhouette(30, (192, 98, 90, 255)))
            corrections = {'front': {'crop': [.12, .05, .95, .95], 'strokes': [
                {'mode': 'erase', 'radius': .04, 'points': [[.5, .5], [.5, .6]]},
                {'mode': 'keep', 'radius': .03, 'points': [[.66, .5]]},
            ]}}
            data = {'reference_edits': json.dumps(corrections)}
            single_file = {'image': front}
            mono = request('POST', '/api/reference-preview', files=single_file, data=data).json()['views'][0]
            original = preview_image(mono, 'original')
            cutout = preview_image(mono, 'cutout')
            assert tuple(original[64, 63]) == (10, 20, 30, 0)
            assert tuple(cutout[64, 63]) == (10, 20, 30, 255)
            assert original[64, 48, 3] == 255 and cutout[64, 48, 3] == 0
            mono_job = request('POST', '/api/generate', files=single_file,
                               data={**data, 'queue_only': 'true'}).json()['id']
            route = f'/api/jobs/{mono_job}'
            assert request('GET', route).json()['settings']['reference_edits'] == corrections
            assert np.array_equal(image_bytes(request('GET', route + '/files/input.png').content), original)
            assert np.array_equal(image_bytes(request('GET', route + '/files/conditioning.png').content),
                                  preview_image(mono, 'framed'))
            request('POST', route + '/cancel')
            request('POST', '/api/reference-preview', 400, files=single_file,
                    data={'reference_edits': '{"left":{}}'})
            request('POST', '/api/reference-preview', 400, files=single_file,
                    data={'reference_edits': '{"front":{"crop":[0,0,0.01,0.01]}}'})

            master = {'engine': 'pixal3d_single', 'preset': 'dense_master', 'master_finishing': 'studio_768',
                      'queue_only': 'true'}
            request('POST', '/api/generate', 503, files=single_file, data=master)
            (root/'single-ready').touch()
            assert request('GET', '/api/status').json()['generation_methods']['pixal3d_single']['ready']
            request('POST', '/api/generate', 400, files=single_file, data={**master, 'resolution': 512})
            request('POST', '/api/generate', 400, files=single_file, data={**master, 'repair_surface': 'true'})
            request('POST', '/api/generate', 503, files=single_file,
                    data={**master, 'master_finishing': 'wtivo_1024'})
            pixal_preview = request('POST', '/api/reference-preview', files=single_file,
                                    data={**data, 'engine': 'pixal3d_single'}).json()['views'][0]
            pixal_master = request('POST', '/api/generate', files=single_file, data={**data, **master}).json()['id']
            route = f'/api/jobs/{pixal_master}'
            recipe = request('GET', route).json()['settings']
            assert recipe['engine'] == 'pixal3d' and recipe['view_mode'] == 'single'
            assert recipe['pipeline_type'] == 'pixal3d_1024_monoview'
            assert recipe['triangles'] == 1_200_000 and recipe['texture_size'] == 2048
            assert recipe['master_finishing'] == 'studio_768' and recipe['hd_reconstruction']
            assert recipe['keep_finishing_source'] and not recipe.get('adaptive_finishing')
            pixels = image_bytes(request('GET', route + '/files/prepared.png').content).astype(np.float32) / 255
            assert np.array_equal((pixels[..., :3] * pixels[..., 3:4] * 255).astype(np.uint8),
                                  preview_image(pixal_preview, 'framed'))
            request('POST', route + '/cancel')
            retry = request('POST', '/api/queue/' + pixal_master + '/retry', 202, json={}).json()['id']
            retried = request('GET', f'/api/jobs/{retry}').json()['settings']
            assert retried['view_mode'] == 'single' and retried['master_finishing'] == 'studio_768'
            request('POST', f'/api/jobs/{retry}/cancel')

            multi_files = dict(image=front, left_image=left, back_image=back)
            multi = request('POST', '/api/reference-preview', files=multi_files,
                            data={**data, 'engine': 'pixal3d'}).json()['views']
            assert [view['role'] for view in multi] == ['front', 'left', 'back']
            multi_job = request('POST', '/api/generate-multiview', 202, files=multi_files, data=data).json()['id']
            route = f'/api/jobs/{multi_job}'
            assert request('GET', route).json()['settings']['reference_edits'] == corrections
            for view, filename in zip(multi, ('prepared.png', 'prepared-left.png', 'prepared-back.png')):
                pixels = image_bytes(request('GET', route + '/files/' + filename).content).astype(np.float32) / 255
                assert pixels.shape == (1024, 1024, 4)
                rgb = (pixels[..., :3] * pixels[..., 3:4] * 255).astype(np.uint8)
                assert np.array_equal(rgb, preview_image(view, 'framed'))
            request('POST', route + '/cancel')

            result = request('POST', '/api/generate-multiview', 202, data={
                'name': 'Pilot character', 'side_angle': 90, 'height_m': 1.59, 'keep_finishing_source': 'true',
            }, files={**files, 'back_image': upload(), 'right_image': upload()}).json()
            first = result['id']
            record = request('GET', '/api/jobs/' + first).json()
            s = record['settings']
            assert record['state']=='queued' and s['engine']=='pixal3d' and s['asset_type']=='humanoid'
            assert s['profile']['id']=='character_pixal' and s['triangles']==10600 and s['texture_size']==2048
            assert s['settings_version']==3
            assert s['height_m']==1.59 and s['keep_finishing_source']
            assert 'reproject_face' not in s
            assert [(v['role'],v['azimuth']) for v in s['views']]==[('front',0),('left',90),('back',180),('right',-90)]
            for view in s['views']:
                r = request('GET','/api/jobs/'+first+'/files/'+view['file'])
                assert r.headers['content-type'].startswith('image/png')
                with Image.open(io.BytesIO(r.content)) as i:
                    assert i.mode=='RGBA'
            request('GET','/api/jobs/'+first+'/files/raw_state.pt',404)

            front = request('POST','/api/v1/uploads',201,files={'file':upload()}).json()['id']
            right = request('POST','/api/v1/uploads',201,files={'file':upload()}).json()['id']
            (root/'wtivo-ready').touch()
            solo = request('POST', '/api/v1/generations', 202, json={
                'upload_id': front, 'engine': 'pixal3d_single', 'profile_id': 'dense_master',
                'master_finishing': 'wtivo_1024', 'overrides': {'triangles': 900_000, 'texture_size': 1024},
            }).json()['id']
            solo_settings = request('GET', f'/api/jobs/{solo}').json()['settings']
            assert solo_settings['master_finishing'] == 'wtivo_1024' and solo_settings['wtivo_reconstruction']
            assert solo_settings['triangles'] == 900_000 and solo_settings['texture_size'] == 1024
            request('POST', f'/api/jobs/{solo}/cancel')
            object_job = request('POST', '/api/v1/generations/multiview', 202, json={
                'upload_id': front, 'right_upload_id': right, 'profile_id': 'game_d', 'asset_type': 'object',
            }).json()['id']
            object_settings = request('GET', f'/api/jobs/{object_job}').json()['settings']
            assert object_settings['asset_type'] == 'object' and object_settings['triangles'] == 28_000
            request('POST', f'/api/jobs/{object_job}/cancel')
            (root/'face-ready').touch()
            assert request('GET','/api/status').json()['pixal3d']['face_projection']['ready']
            api = request('POST','/api/v1/generations/multiview',202,json={
                'upload_id':front, 'right_upload_id':right, 'parent_id':first, 'texture_size':1024, 'priority':2,
                'reproject_face':True,
            }).json()
            second = api['id']
            s = request('GET','/api/jobs/'+second).json()['settings']
            assert s['parent_id']==first and s['texture_size']==1024
            assert s['settings_version']==3
            assert s['reproject_face'] is True
            assert [v['azimuth'] for v in s['views']]==[0,-40]
            request('POST','/api/jobs/'+first+'/cancel',200)
            request('PATCH','/api/queue/'+first,json={'retry':True})
            request('PATCH','/api/queue',json={'paused':False})
            for ident in [second,first]:
                for _ in range(50):
                    if request('GET','/api/jobs/'+ident).json()['state']=='done':
                        break
                    time.sleep(.1)
                assert json.loads((root/'outputs'/ident/'worker-test.json').read_text())['script']=='pixal3d_worker.py'
            d = request('GET','/api/profiles').json()
            assert d['default_profile']=='game_d' and d['profiles'][0]['settings']['triangles']==28000
            print('Reference brush/crop, exact generation framing, Pixal3D readiness, face opt-in, UI revision, four views, typed API, queue retry/dispatch and default D passed.')
        finally:
            if proc.poll() is None:
                try:
                    requests.post(base+'/api/shutdown', timeout=3)
                    proc.wait(timeout=8)
                except (requests.RequestException, subprocess.TimeoutExpired):
                    proc.terminate()
                    proc.wait(timeout=8)
