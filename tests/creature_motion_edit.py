"""CPU tests for procedural clips on unchanged existing skins and source assets."""
import base64
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from creature_motion_edit import (creature_motion_capabilities, validate_creature_motion_recipe,
                                  write_creature_clip)
from generated_motion import append_access, append_clip, write_glb
from glb_data import accessor, read


def reject(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError('Unsupported creature motion was accepted')


def skeleton(kind):
    rows = [('root', None, [0, 1, 0])]
    if kind == 'quadruped':
        for side in (-1, 1):
            for end in (-1, 1):
                name = f'leg_{side}_{end}'
                rows.extend([(name, 'root', [side*.4, .9, end*.7]),
                             (name+'_knee', name, [side*.4, .45, end*.7])])
    elif kind == 'winged':
        for side in (-1, 1):
            name = f'wing_{side}'
            rows.extend([(name, 'root', [side*.2, 1.1, 0]),
                         (name+'_outer', name, [side*.7, 1.1, .1])])
    elif kind == 'swim':
        rows.extend([('top', 'root', [0, 1.3, 0]), ('crown', 'top', [0, 1.6, 0])])
        for side in (-1, 1):
            name = f'lower_{side}'
            rows.extend([(name, 'root', [side*.05, .8, 0]),
                         (name+'_end', name, [side*.1, .4, .05])])
        rows.extend([('rim_a', 'root', [.25, .97, 0]), ('rim_b', 'root', [-.25, .97, 0]),
                     ('rim_c', 'root', [0, .97, .25])])
    else:
        rows = [('root', None, [0, .2, 0])]
        for index in range(6):
            rows.append((f'body_{index}', f'body_{index-1}' if index else 'root', [0, .2, (index+1)*.3]))
    return rows


def fixture(path, kind, *, rotated=False, scale=1.):
    rows = skeleton(kind)
    ids = {row[0]: index for index, row in enumerate(rows)}
    nodes = []
    for name, parent, head in rows:
        position = np.asarray(head) - np.asarray(rows[ids[parent]][2]) if parent else np.asarray(head)
        nodes.append(dict(name=name, translation=position.tolist()))
        if parent:
            nodes[ids[parent]].setdefault('children', []).append(ids[name])
    mesh_index = len(nodes)
    nodes.append(dict(name='surface', mesh=0, skin=0))
    wrapper = len(nodes)
    nodes.append(dict(name='asset transform', children=[0, mesh_index], scale=[scale]*3,
                      rotation=Rotation.from_euler('y', 37, degrees=True).as_quat().tolist() if rotated else [0, 0, 0, 1]))
    data = dict(asset={'version': '2.0'}, nodes=nodes, scene=0, scenes=[{'nodes': [wrapper]}],
                buffers=[{'byteLength': 0}], bufferViews=[], accessors=[])
    binary = bytearray()
    positions, joints = [], []
    for index, (_, _, head) in enumerate(rows):
        positions.extend((np.asarray(head) + corner).tolist() for corner in ([0, 0, 0], [.02, 0, 0], [0, .02, 0]))
        joints.extend([[index, 0, 0, 0]]*3)
    attrs = {'POSITION': append_access(data, binary, positions, 'VEC3'),
             'NORMAL': append_access(data, binary, [[0, 0, 1]]*len(positions), 'VEC3'),
             'TEXCOORD_0': append_access(data, binary, [[0, 0], [1, 0], [0, 1]]*len(rows), 'VEC2'),
             'WEIGHTS_0': append_access(data, binary, [[1, 0, 0, 0]]*len(positions), 'VEC4')}
    assigned = np.asarray(joints, dtype='<u2')
    start, view = len(binary), len(data['bufferViews'])
    binary.extend(assigned.tobytes())
    data['bufferViews'].append(dict(buffer=0, byteOffset=start, byteLength=assigned.nbytes))
    attrs['JOINTS_0'] = len(data['accessors'])
    data['accessors'].append(dict(bufferView=view, componentType=5123, count=len(assigned), type='VEC4'))
    inverse = np.tile(np.eye(4), (len(rows), 1, 1))
    inverse[:, :3, 3] = -np.array([row[2] for row in rows])
    bind = append_access(data, binary, inverse.transpose(0, 2, 1).reshape(len(rows), 16), 'MAT4')
    data['skins'] = [dict(joints=list(range(len(rows))), inverseBindMatrices=bind)]
    data['meshes'] = [dict(primitives=[dict(attributes=attrs, material=0)])]
    # A valid opaque asset payload must remain untouched, including image bytes.
    png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX2kAAAAASUVORK5CYII=')
    view, start = len(data['bufferViews']), len(binary)
    binary.extend(png)
    data['bufferViews'].append(dict(buffer=0, byteOffset=start, byteLength=len(png)))
    data['images'] = [dict(bufferView=view, mimeType='image/png')]
    data['textures'] = [dict(source=0)]
    data['materials'] = [dict(name='Original PBR', pbrMetallicRoughness=dict(baseColorTexture={'index': 0}))]
    append_clip(data, binary, 'Original imported clip', [0, 1], {0: [[0, 0, 0, 1], [0, 0, 0, 1]]},
                [rows[0][2], rows[0][2]], 0, {'original': True})
    write_glb(path, data, binary)


def inspect_clip(source, target, expected):
    before, old = read(source)
    data, binary = read(target)
    assert data['animations'][:-1] == before['animations']
    assert binary.startswith(old)
    for key in ('nodes', 'meshes', 'skins', 'materials', 'textures', 'images', 'scenes', 'scene'):
        assert data.get(key) == before.get(key), key
    clip = data['animations'][-1]
    assert clip['extras']['trellis_creature_motion']['effective_motion'] == expected
    moving = 0
    for channel in clip['channels']:
        sampler = clip['samplers'][channel['sampler']]
        times = accessor(data, binary, sampler['input']).ravel()
        values = accessor(data, binary, sampler['output'])
        assert np.all(np.diff(times) > 0) and times[0] == 0 and times[-1] == 4
        assert np.isfinite(values).all() and np.array_equal(values[0], values[-1])
        if channel['target']['path'] == 'rotation':
            assert np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-6)
            assert np.all(np.sum(values[1:]*values[:-1], axis=1) >= 0)
            moving += int(np.max(np.abs(values-values[:1])) > .001)
    assert moving > 0


def main():
    for bad in ({'motion': []}, {'motion': 'none'}, {'amplitude': False}, {'amplitude': float('nan')},
                {'cycles': 2.0}, {'duration_s': 1}, {'travel_m': .1}, {'phase_lag': .2},
                {'name': 'TS_idle_2s'}, {'unknown': True}, {'name': '\n'}, {'amplitude': 10**400}):
        reject(lambda: validate_creature_motion_recipe(bad))
    with TemporaryDirectory(prefix='trellis-creature-tracks-') as temporary:
        root = Path(temporary)
        for motion, kind in [('test', 'serpentine'), ('quadruped', 'quadruped'),
                             ('serpentine', 'serpentine'), ('winged', 'winged'), ('swim', 'swim')]:
            source, target = root/f'{motion}.glb', root/f'{motion}-animated.glb'
            fixture(source, kind)
            original = source.read_bytes()
            caps = creature_motion_capabilities(source)
            assert next(item for item in caps['motions'] if item['id'] == motion)['available'], caps
            recipe = dict(motion=motion, name='A named loop')
            if motion == 'swim':
                recipe['travel_m'] = .1
            report = write_creature_clip(source, target, recipe)
            assert report['effective_motion'] == motion and report['preservation']['asset_descriptors_identical']
            assert source.read_bytes() == original
            inspect_clip(source, target, motion)
            reject(lambda: write_creature_clip(target, root/f'{motion}-duplicate.glb', recipe))
            reject(lambda: write_creature_clip(source, source, recipe))
            named = root/f'{motion}-auto.glb'
            write_creature_clip(target, named, {'motion': motion})
            again = root/f'{motion}-auto2.glb'
            write_creature_clip(named, again, {'motion': motion})
            assert len({clip['name'] for clip in read(again)[0]['animations']}) == 4
        # Axis/rest conversion and metres of travel must respect the whole asset frame.
        source, output = root/'rotated-scaled.glb', root/'rotated-scaled-swim.glb'
        fixture(source, 'swim', rotated=True, scale=2)
        write_creature_clip(source, output, dict(motion='swim', travel_m=.12))
        inspect_clip(source, output, 'swim')
        data, binary = read(source)
        data['nodes'][-1]['scale'] = [1, 2, 1]
        write_glb(root/'nonuniform.glb', data, binary)
        assert not creature_motion_capabilities(root/'nonuniform.glb')['available']
        reject(lambda: write_creature_clip(root/'nonuniform.glb', root/'invalid.glb', {'motion': 'swim'}))
        reject(lambda: write_creature_clip(root/'serpentine.glb', root/'wrong-topology.glb', {'motion': 'swim'}))
    print('PASS: five procedural modes, exact asset/clip preservation, loops, naming, frame conversion and topology guards.')


if __name__ == '__main__':
    main()
