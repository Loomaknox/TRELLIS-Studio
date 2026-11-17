"""Pixal3D recipe compatibility and D protection, without torch or inference."""
from copy import deepcopy
import hashlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generation_options import DEFAULT_GENERATION, DEFAULT_PROFILE, normalize_options, options_for_job
from pixal3d_worker import prepared_views, sampling_options

options = normalize_options(dict(structure_steps=12, shape_steps=20, texture_steps=12))
original = deepcopy(options)
legacy = sampling_options(options, 42)
assert legacy == {
    'structure': {'seed': 56, 'steps': 12},
    'shape_low': {'seed': 42, 'steps': 20},
    'shape_high': {'seed': 42, 'steps': 12},
    'texture': {'seed': 43, 'steps': 12},
}
for version in (1, 2):
    assert sampling_options(options, 42, version) == legacy

current = sampling_options(options, 42, settings_version=3)
assert current['shape_high'] == current['shape_low'] == {'seed': 42, 'steps': 20}
assert {k: v for k, v in current.items() if k != 'shape_high'} == {
    k: v for k, v in legacy.items() if k != 'shape_high'
}
assert options == original
custom = sampling_options({**options, 'shape_steps': 28, 'texture_seed': 100}, 2**31 - 1, 3)
assert custom['shape_high']['steps'] == custom['shape_low']['steps'] == 28
assert custom['structure']['seed'] == 13
assert custom['texture'] == {'seed': 100, 'steps': 12}

assert DEFAULT_PROFILE == 'game_d'
assert DEFAULT_GENERATION == dict(preset='game_d', resolution=1024, triangles=28000, texture_size=2048)
d = options_for_job(DEFAULT_GENERATION)
assert [d[key + '_steps'] for key in ('structure', 'shape', 'texture')] == [20, 20, 20]
assert [d[key + '_guidance'] for key in ('structure', 'shape', 'texture')] == [7.5, 7.5, 2]
assert d['mesh_mode'] == 'remesh' and d['pre_simplify'] and d['repair_holes']
assert d['remesh_band'] == 1 and d['remesh_project'] == 0
assert d['qem_edge_weight'] == .01 and d['qem_skinny_weight'] == .001

# The provenance must describe the same PNG bytes and pixels passed to inference.
with TemporaryDirectory(prefix='trellis-pixal-prepared-') as directory:
    folder = Path(directory)
    front, left = folder / 'prepared.png', folder / 'prepared-left.png'
    Image.new('RGBA', (16, 16), (255, 0, 0, 128)).save(front)
    Image.new('RGBA', (16, 16), (0, 255, 0, 64)).save(left)
    views = [{'role': 'front', 'file': 'input.png'}, {'role': 'left', 'file': 'input-left.png'}]
    result = list(prepared_views(folder, views, reviewed=True))
    assert [fingerprint for _, fingerprint in result] == [hashlib.sha256(path.read_bytes()).hexdigest()
                                                          for path in (front, left)]
    assert result[0][0][0, 0, 1:].tolist() == [0, 0]
    assert abs(float(result[0][0][0, 0, 0]) - 128 / 255) < 1e-6
    assert abs(float(result[1][0][0, 0, 1]) - 64 / 255) < 1e-6
assert 'torch' not in sys.modules
print('Pixal3D sampling, default D, and prepared-reference fingerprints passed without torch.')
