"""Exercise the creature draft lifecycle against authenticated Server workspaces."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server_lan import MIB, PASSWORD, account, call, eventually, login, serve
from server_store import Store
from studio_workspace import write


def glb(*, skinned=False):
    document = {'asset': {'version': '2.0'}, 'meshes': [{'primitives': []}]}
    if skinned:
        document['skins'] = [{'joints': [0]}]
    chunk = json.dumps(document).encode()
    chunk += b' ' * (-len(chunk) % 4)
    return struct.pack('<4sIIII', b'glTF', 2, 20 + len(chunk), len(chunk), 0x4e4f534a) + chunk


def run():
    with TemporaryDirectory(prefix='trellis-rig-server-') as folder, ExitStack() as stack:
        data = Path(folder)
        store = Store(data / 'server.sqlite3')
        profiles = [{key: value for key, value in account(name).items() if key != 'password'}
                    for name in ('admin', 'owner', 'other')]
        admin = store.bootstrap_admin(profiles[0], PASSWORD)
        users = [store.register(profile, PASSWORD) for profile in profiles[1:]]
        for user in users:
            store.update_user(admin['id'], user['id'],
                              dict(status='active', disk_limit_bytes=512 * MIB))
        stack.enter_context(patch('collection_preview.CollectionPreviews.start'))
        base, state = stack.enter_context(serve(data))
        owner, _ = login(base, 'owner')
        other, _ = login(base, 'other')
        for client in (owner, other):
            call(base, 'GET', '/api/jobs', client=client)
        workspace = state.runtime.workspaces[users[0]['id']]
        source = workspace.outputs / ('a' * 32)
        source.mkdir()
        (source / 'model.glb').write_bytes(glb())
        for filename, value in (
            ('settings.json', dict(name='Creature fixture', asset_type='imported')),
            ('status.json', dict(state='done', stage='Fixture', progress=100)),
        ):
            write(source / filename, value)
        bones = [dict(name='body', parent=None, head=[0, 0, 0], tail=[0, 1, 0]),
                 dict(name='tail', parent='body', head=[0, 1, 0], tail=[0, 2, 0])]
        final_attempts = []

        def launch(folder, script, source_id=None):
            assert script == 'rig_worker.py'
            options = json.loads((folder / 'settings.json').read_text(encoding='utf-8'))
            if options.get('rig_options', {}).get('profile') == 'advanced':
                assert options['rig_options']['articulated_fingers'] is False
                write(folder / 'status.json', dict(state='done', result=dict(rigged=True)))
                return
            assert options['rig_source_sha256'] == hashlib.sha256(glb()).hexdigest()
            if options['creature_phase'] == 'draft':
                work = folder / 'rig-work'
                work.mkdir()
                (work / 'skeleton.fbx').write_bytes(b'synthetic skeleton')
                write(folder / 'rig-preview.json', dict(aligned_to_model=True, bones=bones))
                write(folder / 'status.json', dict(state='done', rig_phase='draft', result=dict(rigged=False)))
            else:
                final_attempts.append(json.loads((folder / 'creature-edit.json').read_text(encoding='utf-8')))
                if len(final_attempts) == 1:
                    write(folder / 'status.json', dict(state='error', rig_phase='final', error='Synthetic failure'))
                else:
                    (folder / 'model.glb').write_bytes(glb(skinned=True))
                    write(folder / 'status.json', dict(state='done', rig_phase='final', result=dict(rigged=True)))

        with (patch.object(workspace.studio, 'components', return_value={'unirig': {'ready': True}}),
              patch.object(workspace.studio, 'find_blender', return_value=Path('fixture')),
              patch.object(workspace, 'launch', side_effect=launch)):
            typed = '/api/v1/models/' + source.name
            call(base, 'POST', typed + '/rig', 422, owner, json=dict(mode='creature', height_m=1.9))
            advanced_request = call(base, 'POST', typed + '/rig', 202, owner, json=dict(profile='advanced')).json()
            assert advanced_request['id'] != source.name
            initial = call(base, 'POST', typed + '/rig', 202, owner, json=dict(mode='creature')).json()
            identifier = initial['id']
            route = '/api/jobs/' + identifier
            rest = '/api/v1/models/' + identifier
            rows = lambda: {job['id']: job for job in store.jobs(users[0]['id'])}
            eventually(lambda: rows()[identifier]['state'] == 'done')
            draft = call(base, 'GET', route, client=owner).json()
            assert draft['rig_phase'] == 'draft' and not draft['media']['available']
            preview = call(base, 'GET', rest + '/rig-preview', client=owner).json()
            assert preview['ready'] and preview['bones'] == bones and preview['max_bones'] == 512
            assert call(base, 'GET', route + '/rig-preview-model', client=owner).content == glb()
            call(base, 'GET', rest + '/rig-preview', 404, other)
            edit = dict(revision=preview['revision'], bones=bones, motion='test')
            call(base, 'POST', rest + '/rig-complete', 404, other, json=edit)
            call(base, 'POST', route + '/rig-complete', 409, owner, json={**edit, 'revision': '0' * 64})
            call(base, 'GET', route + '/files/model.glb', 404, owner)

            # Fail at the reservation step, after the request tried to requeue the draft.
            store.update_user(admin['id'], users[0]['id'], dict(disk_limit_bytes=96 * MIB))
            call(base, 'POST', rest + '/rig-complete', 413, owner, json=edit)
            assert call(base, 'GET', route, client=owner).json()['rig_phase'] == 'draft'
            assert not (workspace.outputs / identifier / 'creature-edit.json').exists()
            assert rows()[identifier]['state'] == 'done'
            store.update_user(admin['id'], users[0]['id'], dict(disk_limit_bytes=512 * MIB))

            final = call(base, 'POST', rest + '/rig-complete', 202, owner, json=edit).json()
            assert final['id'] == identifier
            eventually(lambda: rows()[identifier]['state'] == 'error')
            retry = call(base, 'GET', route + '/rig-preview', client=owner).json()
            assert retry['edited_bones'] == bones and retry['motion'] == 'test'
            call(base, 'POST', route + '/rig-complete', 202, owner, json={**edit, 'motion': 'none'})
            eventually(lambda: rows()[identifier]['state'] == 'done')
            final = call(base, 'GET', route, client=owner).json()
            assert final['rig_phase'] == 'final' and final['media']['available']
            assert call(base, 'GET', route + '/files/model.glb', client=owner).content == glb(skinned=True)
            assert final_attempts[0] == edit and final_attempts[1]['motion'] == 'none'
            assert (source / 'model.glb').read_bytes() == glb()
            assert rows()[identifier]['credit_cost'] == rows()[identifier]['reserve_bytes'] == 0
            call(base, 'POST', rest + '/rig-complete', 409, owner, json=edit)
    print('PASS: creature ownership, immutable source, stale drafts, quota rollback and same-ID retry')


if __name__ == '__main__':
    run()
