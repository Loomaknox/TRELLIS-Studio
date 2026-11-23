"""Exercise native coordinate orientation, occlusion and PBR channel isolation."""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facial_head_color import EYES, SKIN, guide_base_color


class FacialColourTests(unittest.TestCase):
    def test_colour_guidance_hits_only_visible_skin(self):
        size = 100
        target = np.zeros((478, 2))
        def ellipse(indices, center, radius):
            angle = np.arange(len(indices)) * (2*np.pi / len(indices))
            target[list(indices)] = np.array(center) + np.stack((np.cos(angle), np.sin(angle)), axis=1) * radius
        ellipse(SKIN, (0., 0.), (.30, .34))
        for eye, x in zip(EYES, (-.11, .11)):
            ellipse(eye, (x, .09), (.053, .026))
        source = target * [size, -size] + size/2
        image = Image.new('RGBA', (size, size), (170, 89, 75, 255))
        image.paste((11, 10, 10, 255), (64, 50, 74, 59))  # Hair across the right cheek
        image.paste((220, 222, 223, 255), (25, 50, 35, 59))  # A silver cheek implant
        # A head with front and back faces on parallel planes.
        vertices = np.array([(x, y, z) for y in (-.105, .205) for x,z in
                             ((-.42,-.42),(.42,-.42),(.42,.42),(-.42,.42))], dtype=np.float32)
        faces = np.array([[0,1,2],[0,2,3],[4,5,6],[4,6,7]], dtype=np.int32)
        coords = np.array([(0,x,y,z) for y in (39,70) for x in range(100) for z in range(100)], dtype=np.int32)
        attrs = np.tile(np.array([.31,.22,.17,.4,.64,.91], dtype=np.float16), (len(coords),1))
        before = attrs.copy()
        changed = guide_base_color(coords, attrs, {'base_color':slice(0,3)}, size,
                                   vertices, faces, target, source, image)
        take = lambda x,y,z: np.flatnonzero((coords[:,1:] == [x,y,z]).all(axis=1)).item()
        self.assertGreater(changed, 100)
        self.assertTrue(np.allclose(attrs[take(50,39,43), :3], [.67,.35,.29], atol=.04))
        for x,y,z in [(39,39,59), (61,39,59), (50,70,43), (50,39,90), (90,39,50)]:
            row = take(x,y,z)
            np.testing.assert_array_equal(attrs[row], before[row])
        for x in (30, 69):
            row = take(x,39,45)
            np.testing.assert_allclose(attrs[row], before[row], atol=.022)
        np.testing.assert_array_equal(attrs[:,3:], before[:,3:])


if __name__ == '__main__':
    unittest.main()
