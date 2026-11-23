"""Regression tests for reference and mesh review before rigging."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model_diagnostics import diagnose, suspected_intersections
from reference_preparation import reference_warnings


class QualityDiagnosticsTests(unittest.TestCase):
    def test_crop_crossing_and_small_mask_are_distinct(self):
        image = Image.new('RGBA', (128, 128))
        ImageDraw.Draw(image).rectangle((42, 30, 88, 110), fill='white')
        self.assertEqual(reference_warnings(image, [.05, .05, .95, .95], 'trellis2'), [])
        self.assertEqual(reference_warnings(image, [.5, 0, 1, 1], 'trellis2'), ['reference_crop_cut'])
        image = Image.new('RGBA', (128, 128))
        ImageDraw.Draw(image).rectangle((42, 30, 59, 32), fill='white')
        self.assertEqual(reference_warnings(image, None, 'pixal3d'), ['reference_mask_small'])
        self.assertEqual(reference_warnings(Image.new('RGBA', (128, 128), 'white'), [.5, 0, 1, 1], 'trellis2'), [])

    def test_crossing_pair_does_not_confuse_edge_adjacency(self):
        vertices = np.array([(0, 0, 0), (2, 0, 0), (0, 2, 0), (.4, .4, -1), (.4, .4, 1),
                             (.4, 1, .8), (0, -1, 0)], dtype=float)
        faces = np.array([(0, 1, 2), (3, 4, 5), (1, 0, 6)])
        self.assertEqual(suspected_intersections(vertices, faces, 2).tolist(), [[0, 1]])
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'model.glb'
            trimesh.Trimesh(vertices=vertices, faces=faces, process=False).export(source)
            report = diagnose(source.parent)
            self.assertEqual(report['summary']['suspected_crossing_pairs'], 1)
            self.assertEqual(report['summary']['boundary_edges'], 7)
            self.assertEqual(len(report['edge_overlay']['positions']['intersection']), 36)


if __name__ == '__main__':
    unittest.main()
