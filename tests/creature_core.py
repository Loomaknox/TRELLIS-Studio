"""CPU-only creature edit, final verification and isolated worker phase tests.

WSL/Blender subprocesses are replaced only in the worker state-machine tests.
Actual Blender geometry/animation round trips are covered separately.
"""
from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creature_rig import validate_creature_bones, validate_creature_edit
from creature_verification import node_transforms, verify_creature
from generated_motion import append_access, write_glb
import studio_import


BONES = [dict(name='root', parent=None, head=[0, 0, 0], tail=[0, .5, 0]),
         dict(name='tip', parent='root', head=[0, 1, 0], tail=[0, 1.2, 0])]


def reject(callback):
    try:
        callback()
    except (ValueError, TypeError):
        return
    raise AssertionError('An invalid creature contract was accepted')


def fixture(path, *, skinned=False, bad_weights=False, moved=False):
    data = dict(asset={'version': '2.0'}, scene=0, scenes=[{'nodes': [0]}],
                nodes=[{'mesh': 0}], buffers=[{'byteLength': 0}], bufferViews=[], accessors=[])
    binary = bytearray()
    attrs = {'POSITION': append_access(data, binary, [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'VEC3')}
    if skinned:
        data['nodes'] = [{'name': 'root', 'children': [1]},
                         {'name': 'tip', 'translation': [0, 1.1 if moved else 1, 0]},
                         {'name': 'surface', 'mesh': 0, 'skin': 0}]
        data['scenes'][0]['nodes'] = [0, 2]
        data['skins'] = [{'joints': [0, 1]}]
        weights = [[.5 if bad_weights else 1, 0, 0, 0]] * 3
        attrs['WEIGHTS_0'] = append_access(data, binary, weights, 'VEC4')
        start = len(binary)
        assigned = np.zeros((3, 4), dtype='<u2')
        binary.extend(assigned.tobytes())
        view = len(data['bufferViews'])
        data['bufferViews'].append(dict(buffer=0, byteOffset=start, byteLength=assigned.nbytes))
        attrs['JOINTS_0'] = len(data['accessors'])
        data['accessors'].append(dict(bufferView=view, componentType=5123, count=3, type='VEC4'))
    data['meshes'] = [{'primitives': [{'attributes': attrs}]}]
    write_glb(path, data, binary)


def check_contract():
    assert validate_creature_bones(list(reversed(BONES))) == BONES
    for bad in ([], BONES * 300, [BONES[0], {**BONES[1], 'parent': 'absent'}],
                [BONES[0], {**BONES[1], 'parent': 'tip'}],
                [BONES[0], {**BONES[1], 'name': 'root'}],
                [{**BONES[0], 'tail': BONES[0]['head']}],
                [{**BONES[0], 'head': [False, 0, 0]}],
                [{**BONES[0], 'head': [float('nan'), 0, 0]}],
                [{**BONES[0], 'head': [10001, 0, 0]}],
                [{**BONES[0], 'name': 'x\n'}]):
        reject(lambda: validate_creature_bones(bad))
    edit = dict(revision='a'*64, bones=BONES, motion='test')
    assert validate_creature_edit(edit) == edit
    for change in ({'revision': 'bad'}, {'motion': 'swim'}, {'swim': {}}, {'extra': True}):
        reject(lambda: validate_creature_edit({**edit, **change}))
    for data in ({'nodes': [{'children': [0]}]},
                 {'nodes': [{'children': [2]}, {'children': [2]}, {}]}):
        reject(lambda: node_transforms(data)[1](0))


def check_verification(folder):
    path = folder / 'verify.glb'
    fixture(path, skinned=True)
    report = verify_creature(path, BONES)
    assert report['joint_count'] == 2 and report['vertices_checked'] == 3
    assert report['max_joint_error_m'] == 0 and report['unweighted_bones'] == ['tip']
    fixture(path, skinned=True, bad_weights=True)
    reject(lambda: verify_creature(path, BONES))
    fixture(path, skinned=True, moved=True)
    reject(lambda: verify_creature(path, BONES))


def worker(folder, phase, *, fingerprint=True, revision=True, fail_final=False):
    folder.mkdir()
    source = folder / 'source.glb'
    fixture(source)
    before = source.read_bytes()
    work = folder / 'rig-work'
    work.mkdir()
    # A stale humanoid preparation must not become a creature's source.
    (work / 'input.glb').write_bytes(b'stale humanoid preparation')
    preview = dict(aligned_to_model=True, bones=BONES)
    (folder / 'rig-preview.json').write_text(json.dumps(preview), encoding='utf-8')
    (work / 'skeleton.fbx').write_bytes(b'isolated skeleton fixture')
    digest = hashlib.sha256((folder / 'rig-preview.json').read_bytes()).hexdigest()
    (folder / 'creature-edit.json').write_text(json.dumps(dict(
        revision=digest if revision else '0'*64, bones=BONES, motion='none')), encoding='utf-8')
    (folder / 'settings.json').write_text(json.dumps(dict(
        rig_options={'mode': 'creature'}, creature_phase=phase,
        rig_source_sha256=hashlib.sha256(before).hexdigest() if fingerprint else '0'*64)), encoding='utf-8')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'wsl.exe':
            assert '--wait' in command and 'setsid' in command
            if fail_final:
                import subprocess
                (work / 'creature-error.json').write_text(json.dumps({'message': 'Edited joint is outside source bounds.'}), encoding='utf-8')
                raise subprocess.CalledProcessError(1, command)
        else:
            assert Path(command[command.index('--python')+1]).name == 'standard_animations.py'
            fixture(folder / 'model.glb', skinned=True)
            (folder / 'model.blend').write_bytes(b'isolated Blender companion fixture')
            (folder / 'result.json').write_text(json.dumps(dict(rigged=True, humanoid_mapping={},
                animation_set=[], creature_motion=dict(requested='none', applied='none'))), encoding='utf-8')

    with (patch.object(studio_import, 'find_blender', return_value=Path('fixture-blender.exe')),
          patch('subprocess.check_output', return_value='/private/fixture'),
          patch('subprocess.run', side_effect=run),
          patch.object(sys, 'argv', ['rig_worker.py', str(folder)]), redirect_stderr(io.StringIO())):
        try:
            runpy.run_path(str(ROOT / 'rig_worker.py'), run_name='__main__')
        except SystemExit as error:
            assert error.code == 0
    state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    assert source.read_bytes() == before
    if not fingerprint or not revision:
        assert state['state'] == 'error' and not calls
    elif fail_final:
        assert state['state'] == 'error' and state['error_code'] == 'creature_skeleton_invalid'
    elif phase == 'draft':
        assert len(calls) == 1 and state['state'] == 'done' and state['rig_phase'] == 'draft'
        assert state['result']['rigged'] is False and not (folder / 'model.glb').exists()
    else:
        assert len(calls) == 2 and state['state'] == 'done' and state['rig_phase'] == 'final'
        assert state['result']['creature_verification']['max_joint_error_m'] == 0


def check_unirig_orchestration(folder, phase):
    """Run the real orchestration script against private files and fake inference."""
    import yaml
    runtime = folder / 'runtime'
    tasks = runtime / 'source' / 'configs' / 'task'
    tasks.mkdir(parents=True)
    for name in ('quick_inference_skeleton_articulationxl_ar_256.yaml', 'quick_inference_unirig_skin.yaml'):
        (tasks / name).write_text(yaml.safe_dump({'components': {'model': 'fixture'}}), encoding='utf-8')
    entry = runtime / 'run-model.py'
    entry.write_bytes((ROOT / 'UniRig' / 'run-model.py').read_bytes())
    job = folder / 'job'
    (job / 'rig-work').mkdir(parents=True)
    (job / 'source.glb').write_bytes(b'private source marker')
    (job / 'rig-work' / 'input.glb').write_bytes(b'stale humanoid preparation')
    (job / 'settings.json').write_text(json.dumps(dict(rig_options={'mode': 'creature'}, creature_phase=phase)), encoding='utf-8')
    commands = []
    with (patch.dict(sys.modules, {'model_config': SimpleNamespace(prepare_skeleton_config=lambda *_: 'private-model.yaml')}),
          patch('subprocess.run', side_effect=lambda command, **_: commands.append(command)),
          patch.dict('os.environ', {'UNIRIG_COMPUTE_CAP': ''}),
          patch.object(sys, 'argv', [str(entry), str(job)])):
        try:
            runpy.run_path(str(entry), run_name='__main__')
        except SystemExit as error:
            assert phase == 'draft' and error.code == 0
    if phase == 'draft':
        assert len(commands) == 3
        assert '--input=' + str(job / 'source.glb') in commands[0]
        assert commands[1][1] == 'run.py'
        assert commands[2][1] == str(runtime / 'skeleton-preview.py')
        assert not any('skin.yaml' in argument for command in commands for argument in command)
    else:
        assert len(commands) == 5
        assert commands[0][1] == str(runtime / 'apply-creature.py')
        assert commands[2][1] == 'run.py'  # Preserve upstream inference and existing Blackwell dispatch.
        assert commands[3][-1] == 'skeleton-creature'
        assert commands[4][-2] == str(job / 'source.glb')


def main():
    check_contract()
    with TemporaryDirectory(prefix='trellis-creature-worker-') as temporary:
        folder = Path(temporary).resolve()
        check_verification(folder)
        worker(folder/'draft', 'draft')
        worker(folder/'final', 'final')
        worker(folder/'wrong-source', 'final', fingerprint=False)
        worker(folder/'stale-edit', 'final', revision=False)
        worker(folder/'invalid-skeleton', 'final', fail_final=True)
        check_unirig_orchestration(folder/'unirig-draft', 'draft')
        check_unirig_orchestration(folder/'unirig-final', 'final')
    print('PASS: creature contracts, topology-independent skin verification and isolated draft/final worker publication.')


if __name__ == '__main__':
    main()
