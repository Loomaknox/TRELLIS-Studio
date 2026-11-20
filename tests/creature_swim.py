"""Pure-Python jellyfish swim regression checks.

Run python tests/creature_swim.py [additional rigged GLB].
"""
import copy
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creature_swim import (SWIM_CLIP_NAME, SWIM_DEFAULTS, swim_compatible,
                           swim_options, validate_swim_options, write_swim)
from creature_swim_skin import corrected_weights, stabilize_swim_skin
from generated_motion import append_access, write_glb
from glb_data import accessor, read


def reject(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError('Invalid swim settings or anatomy were accepted.')


def fixture(path, legacy_swim=False):
    nodes = [
        {'name': 'racine', 'translation': [0, 1, 0], 'children': [1, 5]},
        {'name': 'ombrelle_01', 'children': [2]},
        {'name': 'tentacule_01_01', 'translation': [.45, 0, 0], 'children': [3]},
        {'name': 'tentacule_01_02', 'translation': [.08, -.22, 0], 'children': [4]},
        {'name': 'tentacule_01_03', 'translation': [.08, -.22, 0]},
        {'name': 'ombrelle_02', 'children': [6]},
        {'name': 'tentacule_02_01', 'translation': [-.45, 0, 0], 'children': [7]},
        {'name': 'tentacule_02_02', 'translation': [-.03, -.16, .02]},
        {'mesh': 0, 'skin': 0},
    ]
    data = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0, 8]}],
        'nodes': nodes, 'skins': [{'joints': list(range(8))}],
        'buffers': [{'byteLength': 0}], 'bufferViews': [], 'accessors': [],
    }
    binary = bytearray()
    pos = append_access(data, binary, [[0, .3, 0], [.1, .3, 0], [0, .4, 0]], 'VEC3')
    data['accessors'][pos].update(min=[0, .3, 0], max=[.1, .4, 0])
    joints = append_access(data, binary, np.zeros((3, 4)), 'VEC4')
    view = data['bufferViews'][data['accessors'][joints]['bufferView']]
    view['byteLength'] = 12
    data['accessors'][joints]['componentType'] = 5121
    weights = append_access(data, binary, [[1, 0, 0, 0]] * 3, 'VEC4')
    data['meshes'] = [{'primitives': [{'attributes': {'POSITION': pos, 'JOINTS_0': joints, 'WEIGHTS_0': weights}}]}]
    time = append_access(data, binary, [0, 1], 'SCALAR')
    move = append_access(data, binary, [[0, 1, 0], [0, .95, 0]], 'VEC3')
    prior = {'name': 'Manual movement', 'samplers': [{'input': time, 'output': move}],
             'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'translation'}}]}
    data['animations'] = [prior]
    if legacy_swim:
        data['animations'].insert(0, {**copy.deepcopy(prior), 'name': SWIM_CLIP_NAME})
    write_glb(path, data, binary)


def check_clip(data, binary, requested):
    clips = [clip for clip in data['animations'] if clip['name'] == SWIM_CLIP_NAME]
    assert len(clips) == 1
    assert swim_options(data) == requested
    clip = clips[0]
    moving_rotations = 0
    for channel in clip['channels']:
        sampler = clip['samplers'][channel['sampler']]
        times = accessor(data, binary, sampler['input']).ravel()
        values = accessor(data, binary, sampler['output'])
        assert len(times) == round(requested['duration_s'] * 30) + 1
        assert times[0] == 0 and math.isclose(float(times[-1]), requested['duration_s'], abs_tol=1e-6)
        assert np.all(np.diff(times) > 0) and np.isfinite(values).all()
        assert np.array_equal(values[0], values[-1])
        if channel['target']['path'] == 'rotation':
            assert np.allclose(np.linalg.norm(values, axis=1), 1.0, atol=1e-6)
            assert np.all(np.sum(values[1:] * values[:-1], axis=1) > 0)
            moving_rotations += int(np.max(np.abs(values - values[0])) > 1e-4)
    assert moving_rotations >= 3


def check_attachment_band():
    positions = np.array([[.45, .80, 0], [.45, 1.015, 0], [.53, 1.12, 0]])
    indices = np.tile([2, 1, 0, 0], (3, 1))
    weights = np.tile([.6, .3, .1, 0.0], (3, 1))
    corrected_indices, corrected, count = corrected_weights(
        positions, indices, weights, np.array([0, 1, 1]),
        np.array([[0, 0, 0], [0, 0, 0], [.45, 1, 0]]), np.array([0., 0., .01]),
    )
    assert count == 1
    assert np.array_equal(corrected[:2], weights[:2])
    assert np.array_equal(corrected_indices[:2], indices[:2])
    assert np.array_equal(corrected_indices[2], [1, 1, 0, 0])
    assert np.allclose(corrected[2], [.9, 0, .1, 0])


def check_demo_skin(source, output):
    before, before_bin = read(source)
    report = stabilize_swim_skin(source, output)
    after, after_bin = read(output)
    assert after_bin.startswith(before_bin)
    for key in ('skins', 'nodes', 'materials', 'images', 'textures'):
        assert after.get(key) == before.get(key)
    for node in before['nodes']:
        if 'mesh' not in node:
            continue
        index = node['mesh']
        for left, right in zip(before['meshes'][index]['primitives'], after['meshes'][index]['primitives']):
            previous = left['attributes']
            current = right['attributes']
            if node.get('name', '').startswith('Tentacule_'):
                assert previous == current
            assert {k: v for k, v in previous.items() if k not in ('JOINTS_0', 'WEIGHTS_0')} == {
                k: v for k, v in current.items() if k not in ('JOINTS_0', 'WEIGHTS_0')}
            assert np.allclose(accessor(after, after_bin, current['WEIGHTS_0']).sum(axis=1), 1, atol=1e-6)
    print(f'Bell stabilized on {report["stabilized_vertices"]} vertices without altering the tentacles.')


def main():
    check_attachment_band()
    for invalid in ({'pulses': 2.5}, {'bell_amplitude': True}, {'phase_lag': float('nan')},
                    {'duration_s': 0}, {'unknown': 1}, {'body_travel_m': .36}):
        reject(lambda: validate_swim_options(invalid))
    with TemporaryDirectory(prefix='trellis-swim-test-') as temporary:
        source, output, rewritten = (Path(temporary) / name for name in ('source.glb', 'out.glb', 'reapplied.glb'))
        fixture(source, legacy_swim=True)
        data, source_binary = read(source)
        assert swim_compatible(data)
        for key, value in (('name', 'unrelated'), ('matrix', np.eye(4).reshape(-1).tolist())):
            incompatible = copy.deepcopy(data)
            incompatible['nodes'][2][key] = value
            # Breaking a branch or adding a matrix to an animated node must
            # keep incompatible imports out of the swim controls.
            assert not swim_compatible(incompatible)
        report = write_swim(source, output)
        first, first_binary = read(output)
        for preserved in ('asset', 'nodes', 'scenes', 'scene', 'meshes', 'skins'):
            assert data[preserved] == first[preserved]
        assert first['animations'][1] == data['animations'][1]
        assert first_binary.startswith(source_binary)
        check_clip(first, first_binary, SWIM_DEFAULTS)
        assert report['bones'] == 8

        options = validate_swim_options({'duration_s': 2.5, 'pulses': 3, 'phase_lag': .25})
        write_swim(output, rewritten, options)
        after, after_binary = read(rewritten)
        check_clip(after, after_binary, options)
        assert after['animations'][1] == data['animations'][1]
        assert after_binary.startswith(source_binary) and len(after_binary) < len(first_binary)
        bytes_before = rewritten.read_bytes()
        write_swim(rewritten, rewritten, options)
        assert rewritten.read_bytes() == bytes_before
        reject(lambda: write_swim(rewritten, rewritten, {'duration_s': -1}))
        assert rewritten.read_bytes() == bytes_before

        # A later author can append another clip. Its data must survive even
        # when the previous swim is no longer the final buffer section.
        appended, prefix = read(rewritten)
        payload = bytearray(prefix)
        time = append_access(appended, payload, [0, 1], 'SCALAR')
        translate = append_access(appended, payload, [[0, 1, 0], [0, 1.1, 0]], 'VEC3')
        later = {'name': 'New motion', 'samplers': [{'input': time, 'output': translate}],
                 'channels': [{'sampler': 0, 'target': {'node': 0, 'path': 'translation'}}]}
        appended['animations'].append(later)
        write_glb(rewritten, appended, payload)
        write_swim(rewritten, rewritten, options)
        appended, append_binary = read(rewritten)
        assert appended['animations'][-1] == later
        assert append_binary.startswith(payload)
        assert np.allclose(accessor(appended, append_binary, translate), [[0, 1, 0], [0, 1.1, 0]])
        size = rewritten.stat().st_size
        write_swim(rewritten, rewritten, options)
        assert rewritten.stat().st_size == size

        if len(sys.argv) > 1:
            demo = Path(sys.argv[1])
            before, before_bin = read(demo)
            assert swim_compatible(before)
            write_swim(demo, rewritten)
            after, after_bin = read(rewritten)
            check_clip(after, after_bin, SWIM_DEFAULTS)
            for key in ('meshes', 'skins', 'nodes', 'materials', 'images', 'textures'):
                assert after.get(key) == before.get(key)
            assert after_bin.startswith(before_bin)
            print(f'Original GLB assets preserved across {len(before["skins"][0]["joints"])} joints.')
            check_demo_skin(demo, rewritten)
    print('PASS: native swim controls, loop, clip preservation, replacement, and atomic writes')


if __name__ == '__main__':
    main()
