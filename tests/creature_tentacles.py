"""Geometry-driven jellyfish rig tests with independent GLB fixtures."""

import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creature_tentacles import adapt_tentacles, validate_tentacle_spacing
from generated_motion import append_access, write_glb


HEIGHT = 1.37
RADIUS = .60
LENGTHS = (.45, .82, 1.19)


def quads(rows, columns):
    return np.asarray([
        face for row in range(rows - 1) for col in range(columns)
        for face in ((row * columns + col, row * columns + (col + 1) % columns, (row + 1) * columns + col),
                     (row * columns + (col + 1) % columns, (row + 1) * columns + (col + 1) % columns,
                      (row + 1) * columns + col))
    ])


def surfaces():
    phases = np.linspace(0, math.tau, 48, endpoint=False)
    levels = np.linspace(math.pi / 16, math.pi / 2, 25)
    parts = [(np.asarray([
        (RADIUS * math.sin(level) * math.cos(angle), HEIGHT + .45 * math.cos(level),
         RADIUS * math.sin(level) * math.sin(angle))
        for level in levels for angle in phases
    ]), quads(len(levels), len(phases)))]
    small_phases = np.linspace(0, math.tau, 14, endpoint=False)
    steps = np.linspace(0, 1, 45)
    for angle, length in zip((0, math.tau / 3, 2 * math.tau / 3, math.pi), (*LENGTHS, .63)):
        radial = .57 if angle != math.pi else .15
        parts.append((np.asarray([
            ((radial + .03 * (1 - .55 * t) * math.cos(phi)) * math.cos(angle)
             - (.05 * math.sin(math.tau * t) + .03 * (1 - .55 * t) * math.sin(phi)) * math.sin(angle),
             HEIGHT - t * length,
             (radial + .03 * (1 - .55 * t) * math.cos(phi)) * math.sin(angle)
             + (.05 * math.sin(math.tau * t) + .03 * (1 - .55 * t) * math.sin(phi)) * math.cos(angle))
            for t in steps for phi in small_phases
        ]), quads(len(steps), len(small_phases))))
    return parts


def fixture(path, *, attached=False, scale=1., single_strand=False):
    parts = surfaces()
    if single_strand:
        parts = parts[1:2]
    if attached:
        points, triangles = [], []
        size = 0
        for positions, indices in parts:
            points.extend(positions)
            triangles.extend(indices + size)
            size += len(positions)
        parts = [(np.asarray(points), np.asarray(triangles))]
    data = dict(asset={'version': '2.0'}, bufferViews=[], accessors=[], buffers=[{'byteLength': 0}],
                scene=0, scenes=[{'nodes': [0]}], nodes=[{'children': [], 'scale': [scale] * 3,
                                                       'translation': [.63, -.04, .38],
                                                       'rotation': [0., .5, 0., math.sqrt(.75)]}], meshes=[])
    binary = bytearray()
    for index, (points, triangles) in enumerate(parts):
        # Non-indexed sections with duplicated vertices are legal. Write both
        # halves as separate primitives to exercise welded material seams.
        primitives = []
        for section in np.array_split(triangles, 2):
            coordinates = append_access(data, binary, points[section.ravel()], 'VEC3')
            primitives.append({'attributes': {'POSITION': coordinates}})
        data['nodes'][0]['children'].append(len(data['nodes']))
        data['nodes'].append({'mesh': index, 'name': f'Surface {index}'})
        data['meshes'].append({'primitives': primitives})
    write_glb(path, data, binary)


class TentacleAdaptation(unittest.TestCase):
    def test_separate_tubes_scale_and_spacing(self):
        with TemporaryDirectory() as temporary:
            mesh = Path(temporary) / 'jellyfish.glb'
            fixture(mesh, scale=1.35)
            fine = adapt_tentacles(mesh, [], .16)
            coarse = adapt_tentacles(mesh, [], .36)
            self.assertEqual(len(fine['chains']), 3)
            self.assertEqual(len(coarse['chains']), 3)
            self.assertEqual({chain['method'] for chain in fine['chains']}, {'mesh'})
            self.assertGreater(len(fine['bones']), len(coarse['bones']))
            fine_lengths = sorted(chain['length_m'] for chain in fine['chains'])
            np.testing.assert_allclose(fine_lengths, np.asarray(LENGTHS) * 1.35, atol=.16)
            self.assertEqual([chain['segments'] for chain in fine['chains']],
                             [math.ceil(chain['length_m'] / .16) for chain in fine['chains']])
            self.assertEqual(len(fine['bones']), 1 + len(fine['chains'])
                             + sum(chain['segments'] for chain in fine['chains']))
            self.assertEqual(fine['bones'][0]['name'], 'racine')
            np.testing.assert_allclose(np.asarray(fine['bones'][0]['head'])[[0, 2]], [.63, .38], atol=.04)

    def test_tubes_joined_at_bell_surface(self):
        with TemporaryDirectory() as temporary:
            mesh = Path(temporary) / 'joined.glb'
            fixture(mesh, attached=True)
            result = adapt_tentacles(mesh, [], .19)
            self.assertEqual(len(result['chains']), 3)
            self.assertEqual({chain['method'] for chain in result['chains']}, {'mesh'})
            np.testing.assert_allclose(sorted(chain['length_m'] for chain in result['chains']), LENGTHS, atol=.12)

    def test_reject_missing_bell_and_invalid_spacing(self):
        for value in (False, None, -1, .04, .51, float('nan'), float('inf')):
            with self.subTest(spacing=value), self.assertRaises(ValueError):
                validate_tentacle_spacing(value)
        with TemporaryDirectory() as temporary:
            mesh = Path(temporary) / 'tube.glb'
            fixture(mesh, single_strand=True)
            with self.assertRaisesRegex(ValueError, 'bell|tentacles'):
                adapt_tentacles(mesh, [], .19)


if __name__ == '__main__':
    unittest.main()
