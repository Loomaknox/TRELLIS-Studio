"""Bounded CPU unit checks for optional HD-to-game transfer; no Studio data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import io
import json
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import baked_game_copy as game


def fixture(path, change=None):
    positions = np.array([[-1, 0, 0], [1, 0, 0], [1, 2, 0], [-1, 2, 0]], '<f4')
    arrays = [positions, np.tile([0, 0, 1], (4, 1)).astype('<f4'),
              np.array([[0, 0], [1, 0], [1, 1], [0, 1]], '<f4'), np.array([0, 1, 2, 0, 2, 3], '<u4')]
    binary = bytearray()
    views, accessors = [], []
    for array, kind in zip(arrays, ['VEC3', 'VEC3', 'VEC2', 'SCALAR']):
        views.append(dict(buffer=0, byteOffset=len(binary), byteLength=array.nbytes))
        binary += array.tobytes()
        accessors.append(dict(bufferView=len(views) - 1, componentType=5125 if kind == 'SCALAR' else 5126,
                              count=len(array), type=kind))
    image = io.BytesIO()
    Image.new('RGB', (4, 4), (180, 70, 30)).save(image, format='PNG')
    views.append(dict(buffer=0, byteOffset=len(binary), byteLength=len(image.getvalue())))
    binary += image.getvalue()
    binary += b'\0' * (-len(binary) % 4)
    data = dict(asset=dict(version='2.0'), buffers=[dict(byteLength=len(binary))], bufferViews=views,
                accessors=accessors, images=[dict(bufferView=4, mimeType='image/png')], textures=[dict(source=0)],
                materials=[dict(pbrMetallicRoughness=dict(baseColorTexture=dict(index=0)))],
                meshes=[dict(primitives=[dict(attributes=dict(POSITION=0, NORMAL=1, TEXCOORD_0=2), indices=3, material=0)])],
                nodes=[dict(mesh=0)], scenes=[dict(nodes=[0])], scene=0)
    if change:
        change(data)
    descriptor = json.dumps(data).encode()
    descriptor += b' ' * (-len(descriptor) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(descriptor) + len(binary)) +
                     struct.pack('<II', len(descriptor), 0x4E4F534A) + descriptor +
                     struct.pack('<II', len(binary), 0x004E4942) + binary)


class GameCopyTests(TestCase):
    def test_defaults_and_strict_options(self):
        self.assertEqual(game.normalize_game_copy_options({})['triangles'], 28000)
        self.assertEqual(game.normalize_game_copy_options({'profile': 'humanoid'})['triangles'], 14000)
        for invalid in ({'triangles': True}, {'triangles': 4999}, {'triangles': 150001}, {'triangles': 14000.},
                        {'texture_size': 8192}, {'bake_normals': 1}, {'profile': 'quad'}, {'unexpected': 0}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                game.normalize_game_copy_options(invalid)

    def test_static_capability_and_unused_material(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'source.glb'
            fixture(path)
            result = game.inspect_baked_game_copy(path)
            self.assertTrue(result['supported'], result)
            self.assertEqual(result['triangles'], 2)
            fixture(path, lambda data: data['materials'].append({}))
            self.assertTrue(game.inspect_baked_game_copy(path)['supported'])

    def test_unsupported_features(self):
        changes = [lambda d: d.update(skins=[{}]), lambda d: d.update(animations=[{}]),
                   lambda d: d['nodes'][0].update(translation=[1, 0, 0]),
                   lambda d: d['materials'][0].update(alphaMode='BLEND'),
                   lambda d: d['materials'][0].update(occlusionTexture={'index': 0}),
                   lambda d: d['meshes'][0]['primitives'].append(d['meshes'][0]['primitives'][0].copy()),
                   lambda d: d['images'][0].update(uri='../private.png')]
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'source.glb'
            for change in changes:
                fixture(path, change)
                self.assertFalse(game.inspect_baked_game_copy(path)['supported'])

    def test_region_weights_scale_and_translation(self):
        rng = np.random.default_rng(42)
        head = rng.uniform([-.06, .85, -.04], [.06, 1, .06], (300, 3))
        left = rng.uniform([-.5, .69, -.03], [-.4, .8, .03], (300, 3))
        right = left * [-1, 1, 1]
        body = rng.uniform([-.1, 0, -.05], [.1, .8, .05], (300, 3))
        vertices = np.concatenate([head, left, right, body])
        first, report = game._region_weights(vertices, 'humanoid')
        second, _ = game._region_weights(vertices * 2.5 + [4, -2, 3], 'humanoid')
        np.testing.assert_array_equal(first, second)
        self.assertGreater(report['face_vertices'], 10)
        self.assertGreater(report['hand_vertices'], 10)
        with self.assertRaises(ValueError):
            game._region_weights(body, 'humanoid')

    def test_donor_never_overwritten_and_staging_cleans_on_failure(self):
        with TemporaryDirectory() as folder, patch.object(game, 'game_copy_dependencies', return_value={'ready': True}):
            path = Path(folder) / 'source.glb'
            fixture(path)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                game.run_baked_game_copy(path, path, options={})
            def stop(stage, fraction):
                if fraction >= .12:
                    raise RuntimeError('Intentional QA cancellation before native reduction')
            with self.assertRaisesRegex(RuntimeError, 'Intentional QA'):
                game.run_baked_game_copy(path, Path(folder) / 'output.glb', options={}, progress=stop)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_clean_removes_degenerate_and_duplicate_faces_only(self):
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [2, 0, 0]], float)
        faces = np.array([[0, 1, 2], [2, 1, 0], [0, 1, 3], [0, 0, 2]])
        np.testing.assert_array_equal(game._clean(vertices, faces), [[0, 1, 2]])


if __name__ == '__main__':
    main()
