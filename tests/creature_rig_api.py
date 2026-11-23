"""Check the Desktop creature workflow without starting Blender or WSL."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rig_profiles_api import call, desktop_host, fixture, model_bytes


def bones(count=3):
    return [dict(name=f'bone_{index}', parent=f'bone_{index - 1}' if index else None,
                 head=[float(index), 0, 0], tail=[float(index + 1), 0, 0]) for index in range(count)]


def main():
    with TemporaryDirectory(prefix='trellis-creature-api-') as temporary:
        directory = Path(temporary).resolve()
        paths = {'TRELLIS_'+key: str(directory/name) for key, name in (
            ('OUTPUT_DIR', 'outputs'), ('TRASH_DIR', 'trash'), ('EXPORT_DIR', 'exports'),
            ('STATE_DIR', 'state'), ('PROFILES_FILE', 'profiles.json'))}
        with patch.dict(os.environ, paths):
            import app
            import creature_api

            original = fixture(app.OUTPUT, 'a'*32)
            rigged = fixture(app.OUTPUT, 'b'*32, skinned=True)
            initial = (original/'model.glb').read_bytes()
            attempts = []

            def launch(folder, worker):
                assert worker == 'rig_worker.py'
                settings = json.loads((folder/'settings.json').read_text(encoding='utf-8'))
                assert settings['rig_options'] == {'mode': 'creature'}
                assert settings['parent_id'] == original.name
                assert settings['rig_source_id'] == original.name
                assert settings['rig_source_sha256'] == hashlib.sha256(initial).hexdigest()
                assert (folder/'source.glb').read_bytes() == initial
                if settings['creature_phase'] == 'draft':
                    work = folder/'rig-work'
                    work.mkdir()
                    (work/'skeleton.fbx').write_bytes(b'fixture')
                    app.write_json(folder/'rig-preview.json', dict(bones=bones(), aligned_to_model=True))
                    app.write_json(folder/'status.json', dict(state='done', rig_phase='draft', progress=100))
                else:
                    edit = json.loads((folder/'creature-edit.json').read_text(encoding='utf-8'))
                    attempts.append(edit)
                    if len(attempts) == 1:
                        app.write_json(folder/'status.json', dict(state='error', rig_phase='draft', progress=0))
                    else:
                        (folder/'model.glb').write_bytes(model_bytes(skinned=True))
                        app.write_json(folder/'result.json', dict(rigged=True))
                        app.write_json(folder/'status.json', dict(state='done', rig_phase='final', progress=100))

            with (patch.object(app, 'components', return_value={'unirig': {'ready': True}}),
                  patch.object(app, 'find_blender', return_value=Path('fixture-blender')),
                  patch.object(app, 'launch_worker', side_effect=launch), desktop_host(app.app) as base):
                original_route = '/api/v1/models/'+original.name+'/rig'
                assert 'creature_rig' in call(base, 'GET', '/api/status').json()['features']
                assert {'creature_tentacles', 'creature_swim'} <= set(call(base, 'GET', '/api/status').json()['features'])
                call(base, 'POST', original_route, 422, json={'mode': 'creature', 'height_m': 1.7})
                call(base, 'POST', '/api/jobs/'+rigged.name+'/rig', 409, json={'mode': 'creature'})
                accepted = call(base, 'POST', original_route, 202, json={'mode': 'creature'}).json()
                draft = app.OUTPUT/accepted['id']
                legacy = '/api/jobs/'+draft.name
                typed = '/api/v1/models/'+draft.name
                assert call(base, 'GET', legacy).json()['media']['available'] is False
                preview = call(base, 'GET', typed+'/rig-preview').json()
                raw_preview = (draft/'rig-preview.json').read_bytes()
                assert preview['revision'] == hashlib.sha256(raw_preview).hexdigest()
                assert preview['bones'] == bones() and preview['max_bones'] >= 97
                assert call(base, 'GET', legacy+'/rig-preview-model').content == initial
                call(base, 'POST', '/api/exports', 409, json={'ids': [draft.name], 'target': 'blender'})
                call(base, 'POST', legacy+'/rig-complete', 409, json=dict(revision='0'*64, bones=bones()))
                assert not (draft/'creature-edit.json').exists()
                revision = preview['revision']
                call(base, 'POST', legacy+'/rig-tentacles', 409, json=dict(revision='0'*64, spacing_m=.19))
                call(base, 'POST', legacy+'/rig-tentacles', 400, json=dict(revision=revision, spacing_m=.01))
                detected = dict(bones=bones(), chains=[dict(name='tentacule_01', length_m=.72, segments=4)],
                                spacing_m=.19, warnings=[])
                with patch.object(creature_api, 'adapt_tentacles', return_value=detected):
                    proposal = call(base, 'POST', typed+'/rig-tentacles', 200,
                                    json=dict(revision=revision, spacing_m=.19)).json()
                assert proposal['bones'] == bones()
                restored = call(base, 'GET', typed+'/rig-preview').json()
                assert restored['adapted_bones'] == bones() and restored['chains'] == detected['chains']
                invalid = ([*bones()[:-1], {**bones()[-1], 'parent': 'absent'}],
                           [bones()[0], {**bones()[1], 'parent': 'bone_2'}, bones()[2]],
                           [bones()[0], {**bones()[1], 'name': 'bone_0'}],
                           [{**bones()[0], 'tail': bones()[0]['head']}],
                           [{**bones()[0], 'head': [False, 0, 0]}],
                           [{**bones()[0], 'name': 'é'*32}])
                for bad in invalid:
                    call(base, 'POST', legacy+'/rig-complete', 400, json=dict(revision=revision, bones=bad))
                    call(base, 'POST', typed+'/rig-complete', 422, json=dict(revision=revision, bones=bad))
                assert not (draft/'creature-edit.json').exists()
                edited = bones(97)
                request = dict(revision=revision, bones=list(reversed(edited)), motion='serpentine')
                call(base, 'POST', legacy+'/rig-complete', 202, json=request)
                assert attempts == [dict(revision=revision, bones=edited, motion='serpentine')]
                retry_preview = call(base, 'GET', legacy+'/rig-preview').json()
                assert retry_preview['edited_bones'] == edited and retry_preview['motion'] == 'serpentine'
                assert (draft/'rig-preview.json').read_bytes() == raw_preview
                assert call(base, 'GET', legacy).json()['media']['available'] is False
                call(base, 'POST', typed+'/rig-complete', 202, json={**request, 'motion': 'test'})
                assert len(attempts) == 2 and (original/'model.glb').read_bytes() == initial
                assert call(base, 'GET', legacy+'/files/model.glb').content == model_bytes(skinned=True)
                assert call(base, 'GET', legacy+'/rig-source').json()['id'] == original.name
                assert not call(base, 'GET', typed+'/creature-swim').json()['compatible']
                call(base, 'POST', legacy+'/creature-swim', 400, json={'duration_s': 1})
                call(base, 'POST', legacy+'/creature-swim', 409, json={'duration_s': 6})
                settings_path = draft/'settings.json'
                settings = json.loads(settings_path.read_text(encoding='utf-8'))
                del settings['rig_source_id']
                app.write_json(settings_path, settings)
                assert call(base, 'GET', legacy+'/rig-source').json()['id'] == original.name
                call(base, 'POST', legacy+'/rig-complete', 409, json=request)
                with patch.object(app, 'WORKSPACE_CONFIG', {'outputs': app.OUTPUT}):
                    features = call(base, 'GET', '/api/status').json()['features']
                    assert 'creature_rig' in features
                    assert not {'creature_tentacles', 'creature_swim'} & set(features)
                    preview = call(base, 'GET', legacy+'/rig-preview').json()
                    assert not {'adapted_bones', 'chains', 'swim'} & preview.keys()
                    call(base, 'POST', legacy+'/rig-tentacles', 404, json={'revision': revision})
                    call(base, 'GET', legacy+'/creature-swim', 404)
                    call(base, 'POST', legacy+'/creature-swim', 404, json={'duration_s': 6})
    print('PASS: creature draft provenance, graph checks, revision, retry, publication and Desktop scope')


if __name__ == '__main__':
    main()
