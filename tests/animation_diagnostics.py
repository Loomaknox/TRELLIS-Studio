"""Regress the sub-frame sign/baking defect and publication of bad GLB tracks."""
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from animation_diagnostics import inspect_animation, require_valid_animation


def fixture(output, times, rotations, *, mode='LINEAR'):
    key_bytes = np.asarray(times, dtype='<f4').tobytes()
    value_bytes = np.asarray(rotations, dtype='<f4').tobytes()
    descriptor = dict(
        asset={'version': '2.0'}, meshes=[{'primitives': []}], nodes=[{'name': 'knee'}],
        buffers=[{'byteLength': len(key_bytes) + len(value_bytes)}],
        bufferViews=[{'buffer': 0, 'byteLength': len(key_bytes)},
                     {'buffer': 0, 'byteOffset': len(key_bytes), 'byteLength': len(value_bytes)}],
        accessors=[{'bufferView': 0, 'count': len(times), 'type': 'SCALAR', 'componentType': 5126},
                   {'bufferView': 1, 'count': len(rotations), 'type': 'VEC4', 'componentType': 5126}],
        animations=[dict(name='TS_crouch_3.0s', samplers=[dict(input=0, output=1, interpolation=mode)],
                         channels=[dict(sampler=0, target=dict(node=0, path='rotation'))])])
    metadata = json.dumps(descriptor, separators=(',', ':')).encode()
    metadata += b' ' * (-len(metadata) % 4)
    binary = key_bytes + value_bytes
    output.write_bytes(struct.pack('<4sIIII', b'glTF', 2, 28 + len(metadata) + len(binary), len(metadata), 0x4e4f534a)
                       + metadata + struct.pack('<II', len(binary), 0x004e4942) + binary)


def run():
    identity = [0, 0, 0, 1]
    flip = [1, 0, 0, 0]
    # The old Blender output inserted both flipped keys between a 30 fps test grid.
    times = [42/60, 43/60, 44/60, 136/60, 137/60, 138/60]
    name = 'TS_crouch_3.0s'
    with TemporaryDirectory(prefix='trellis-animation-diagnostic-') as directory:
        model = Path(directory) / 'animation.glb'
        fixture(model, times, [identity, flip, identity, identity, flip, identity])
        scan = require_valid_animation(model, clips={name})
        findings = scan['issues']
        assert len(findings) == 2 and all(item['severity'] == 'warning' for item in findings), findings
        assert [(item['bone'], round(item['time_s'], 4)) for item in findings] == [('knee', .7167), ('knee', 2.2833)]
        # q and -q represent the same pose. They are legal in an imported LINEAR track.
        fixture(model, times, [identity, [0, 0, 0, -1], identity, identity, [0, 0, 0, -1], identity])
        assert not inspect_animation(model, rate=240)['issues']
        fixture(model, [0, .04], [[0, 0, 0, 0], identity])
        assert inspect_animation(model)['issues'][0]['severity'] == 'error'
        for selected in ({name}, {'missing motion'}):
            try:
                require_valid_animation(model, clips=selected)
            except ValueError as error:
                assert 'contains an invalid track' in str(error)
            else:
                raise AssertionError('An invalid or missing authored animation was accepted.')
        # Cubic endpoints may agree even when their tangents create a visible swing.
        tangent = [160, 0, 0, 0]
        zero = [0, 0, 0, 0]
        fixture(model, [0, .04], [zero, identity, tangent, [-x for x in tangent], identity, zero], mode='CUBICSPLINE')
        assert any(item['code'] == 'animation_rotation_jump' and 0 < item['time_s'] < .04
                   for item in inspect_animation(model)['issues'])
    print('Animation diagnostics: displaced keys, antipodal rotation and publication checks passed.')


if __name__ == '__main__':
    run()
