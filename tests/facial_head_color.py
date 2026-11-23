"""Exercise native coordinate orientation, occlusion and PBR channel isolation."""
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import torch
from facial_head_color import EYES, FACE_OVAL, apply_face_material, prepare_face_material

LAYOUT = {'base_color':slice(0,3), 'metallic':slice(3,4),'roughness':slice(4,5),'alpha':slice(5,6)}


class FacialColourTests(unittest.TestCase):
    def test_colour_guidance_hits_only_visible_skin(self):
        size = 100
        target = np.zeros((478, 2))
        def ellipse(indices, center, radius):
            angle = np.arange(len(indices)) * (2*np.pi / len(indices))
            target[list(indices)] = np.array(center) + np.stack((np.cos(angle), np.sin(angle)), axis=1) * radius
        ellipse(FACE_OVAL, (0., 0.), (.30, .37))
        for eye, x in zip(EYES, (-.11, .11)):
            ellipse(eye, (x, .09), (.053, .026))
        source = target * [size, -size] + size/2
        image = Image.new('RGBA', (size, size), (170, 89, 75, 255))
        image.paste((0, 250, 253, 255), (38, 40, 41, 42))  # A photographed iris is never baked into a lid.
        image.paste((11, 10, 10, 255), (64, 50, 74, 59))  # Hair across the right cheek
        image.paste((220, 222, 223, 255), (25, 50, 35, 59))  # A silver cheek implant
        # The source's orbital skin above the eyes must replace a dark generated patch.
        # A head with front and back faces on parallel planes.
        vertices = np.array([(x, y, z) for y in (-.105, .205) for x,z in
                             ((-.42,-.42),(.42,-.42),(.42,.42),(-.42,.42))], dtype=np.float32)
        faces = np.array([[0,1,2],[0,2,3],[4,5,6],[4,6,7]], dtype=np.int32)
        coords = np.array([(x,y,z) for y in (39,70) for x in range(100) for z in range(100)], dtype=np.int32)
        attrs = np.tile(np.array([.31,.22,.17,.4,.64,.91], dtype=np.float32), (len(coords),1))
        attrs[(coords[:,0]>32) & (coords[:,0]<49) & (coords[:,2]>60) & (coords[:,2]<66), :3] = .01
        before = attrs.copy()
        guide = prepare_face_material(vertices, faces, target, source, image)
        eye = np.rint(([-.11,.09] - guide['origin'].numpy()) / guide['step']).astype(int)
        self.assertLess(float(guide['rgb'][eye[1],eye[0],2]), .45)
        mask = torch.ones((2,10000), dtype=torch.bool)
        changed = apply_face_material(torch.from_numpy((coords.astype(np.float32)+.5)/size-.5),
                                     mask,mask,torch.from_numpy(attrs.reshape(2,10000,6)),LAYOUT,guide)
        take = lambda x,y,z: np.flatnonzero((coords == [x,y,z]).all(axis=1)).item()
        self.assertGreater(changed, 100)
        self.assertTrue(np.allclose(attrs[take(50,39,43), :3], [.67,.35,.29], atol=.085))
        self.assertGreater(attrs[take(39,39,64),0], .51)
        for x,y,z in [(39,39,59), (61,39,59), (50,70,43), (50,39,90), (90,39,50)]:
            row = take(x,y,z)
            np.testing.assert_array_equal(attrs[row], before[row])
        for x in (30, 69):
            row = take(x,39,45)
            np.testing.assert_allclose(attrs[row], before[row], atol=.022)
        np.testing.assert_array_equal(attrs[:,3:], before[:,3:])

    def test_exact_uv_positions_and_missing_material(self):
        n=32
        rgb=torch.zeros(n,n,3)
        rgb[:,:,1]=.3
        rgb[:,:15,0]=.8
        rgb[:,15:,2]=.9
        guide=dict(origin=torch.tensor([0.,0.]),step=.0001,eye_span=.02,
                   depth=torch.full((n,n),.10),weight=torch.ones(n,n),rgb=rgb)
        # Points span a sharp colour edge inside a single 1024-grid cell.
        positions=torch.tensor([[.0013,-.1,.0010],[.0017,-.1,.0010],[.0013,.1,.0010]])
        surface=torch.ones(1,3,dtype=torch.bool)
        available=torch.tensor([[True,False,False]])
        attrs=torch.zeros(1,3,6)
        count=apply_face_material(positions,surface,available,attrs,LAYOUT,guide)
        self.assertEqual(count,2)
        self.assertTrue(torch.equal(available,torch.tensor([[True,True,False]])))
        self.assertGreater(float(attrs[0,0,0]),.79)
        self.assertGreater(float(attrs[0,1,2]),.89)
        np.testing.assert_allclose(attrs[0,1,3:].numpy(),[0.,.66,1.],rtol=1e-5)
        np.testing.assert_array_equal(attrs[0,2].numpy(),np.zeros(6))

    def test_hardware_on_temple_does_not_get_a_photographic_double(self):
        n=64
        guide=dict(origin=torch.tensor([-.08,-.04]),step=.003,eye_span=.1,eye_line=torch.zeros(2),
                   depth=torch.full((n,n),.1),weight=torch.ones(n,n),rgb=torch.full((n,n,3),.65))
        points=torch.tensor([[.042,-.1,.032],[.046,-.1,.03],[.0,-.1,.0]])
        mask=torch.ones(1,3,dtype=torch.bool)
        attrs=torch.full((1,3,6),.25)
        attrs[0,0,3]=.97
        before=attrs.clone()
        count=apply_face_material(points,mask,mask,attrs,LAYOUT,guide)
        self.assertEqual(count,1)
        self.assertTrue(torch.equal(before[0,:2],attrs[0,:2]))
        self.assertGreater(float(attrs[0,2,0]),.64)


if __name__ == '__main__':
    unittest.main()
