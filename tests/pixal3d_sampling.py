"""Pixal3D recipe compatibility and D protection, without torch or inference."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generation_options import DEFAULT_GENERATION, DEFAULT_PROFILE, normalize_options, options_for_job
from pixal3d_runtime import SINGLE_IMAGE_MARKER, runtime_status, single_image_marker, source_path
from pixal3d_worker import prepared_single_view, prepared_views, sampling_options
from reference_preparation import frame_pixal_single

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
    single = Image.new('RGBA', (90, 60))
    single.paste((255, 115, 18, 255), (5, 7, 85, 53))
    framed = frame_pixal_single(single)
    assert framed.size == (86, 86) and framed.getchannel('A').getextrema() == (0, 255)
    framed.save(front)
    single_pixels, single_hash = prepared_single_view(folder, reviewed=True)
    assert single_pixels.shape == (86, 86, 3)
    assert all(abs(float(value) - expected / 255) < 1e-6
               for value, expected in zip(single_pixels[43, 43], (255, 115, 18), strict=True))
    assert single_hash == hashlib.sha256(front.read_bytes()).hexdigest()

# A verified multi-view install remains available independently of the optional upgrade.
with TemporaryDirectory(prefix='trellis-pixal-capability-') as directory:
    folder = Path(directory)
    runtime = folder / 'runtime'
    manifest = {
        'comfy': {'commit': 'test', 'sha256': 'source'},
        'weights_revision': 'test',
        'weights': [{'path': 'multi.bin', 'bytes': 1, 'sha256': 'multi'}],
        'single_image_weights': [{'path': 'single.bin', 'bytes': 1, 'sha256': 'single'}],
        'face_detector': {'path': 'missing', 'bytes': 1, 'sha256': 'face'},
    }
    (folder / 'installer').mkdir()
    (folder / 'installer/pixal3d-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    source = source_path(runtime, manifest)
    (source / 'comfy_extras').mkdir(parents=True)
    (source / 'comfy/ldm/moge').mkdir(parents=True)
    (runtime / 'deps/comfy_kitchen').mkdir(parents=True)
    (runtime / 'models').mkdir()
    (source / 'comfy_extras/nodes_trellis2.py').touch()
    (source / 'comfy/ldm/moge/model.py').touch()
    (runtime / 'verified.json').write_text(json.dumps({
        'schema': 1, 'source_sha256': 'source', 'model_revision': 'test',
    }), encoding='utf-8')
    (runtime / 'models/multi.bin').write_bytes(b'm')
    with patch.dict(os.environ, {'TRELLIS_PIXAL3D_RUNTIME_DIR': str(runtime)}):
        assert runtime_status(folder)['ready'] and not runtime_status(folder)['single_image']['ready']
        (runtime / 'models/single.bin').write_bytes(b's')
        (runtime / SINGLE_IMAGE_MARKER).write_text(json.dumps(single_image_marker(manifest)), encoding='utf-8')
        assert runtime_status(folder)['ready'] and runtime_status(folder)['single_image']['ready']
        (runtime / 'models/single.bin').write_bytes(b'bad')
        assert runtime_status(folder)['ready'] and not runtime_status(folder)['single_image']['ready']
assert 'torch' not in sys.modules
print('Pixal3D sampling, default D, and prepared-reference fingerprints passed without torch.')
