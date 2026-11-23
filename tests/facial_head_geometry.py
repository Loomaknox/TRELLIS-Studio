"""Small regression checks for the optional geometry-first face workflow."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facial_head_eyes import append_eyes
from facial_head_generation import portrait_conditioning
from facial_head_geometry import _bounded_relief, _deformation_quality, _depth, _eye_well, _replace_skin, face_landmarks


class FacialGeometryTests(unittest.TestCase):
    def test_rebuilt_front_removes_extra_lid_and_closes_the_visible_hole(self):
        size, step = 129, .001
        origin = np.array([-.064, -.064])
        iy, ix = np.indices((size,size))
        x, y = ix*step+origin[0], iy*step+origin[1]
        original = .004*np.exp(-((x+.014)**2+(y-.020)**2)/.000013)
        donor = .003*np.exp(-(x*x+y*y)/.00005)
        vertices = np.column_stack((x.ravel(),y.ravel(),original.ravel())).astype(np.float32)
        ids = np.arange(size*size).reshape(size,size)
        a, b, c, d = [tile.ravel() for tile in (ids[:-1,:-1],ids[:-1,1:],ids[1:,1:],ids[1:,:-1])]
        triangles = np.vstack((np.column_stack((a,b,c)),np.column_stack((a,c,d)))).astype(np.int32)
        centroid = vertices[triangles].mean(1)
        hole = (centroid[:,0]+.014)**2 + (centroid[:,1]-.020)**2 < .0025**2
        triangles = triangles[~hole]
        points = np.zeros((478,2))
        points[[9,10,17,152],1] = [.020,.042,-.018,-.046]
        for sx, lid in ((-.016,(33,160,159,158,133,153,145,144)), (.016,(263,387,386,385,362,380,374,373))):
            angle = np.arange(8) * np.pi/4
            points[list(lid)] = np.column_stack((sx + .007*np.cos(angle), .010+.002*np.sin(angle)))
        repaired, faces, _, stats = _replace_skin(vertices,triangles,original,donor,origin,step,points,.057)
        original_z, before = _depth(vertices,triangles,origin,step,size)
        repaired_z, after = _depth(repaired,faces,origin,step,size)
        self.assertFalse(before[84,50])
        self.assertTrue(after[84,50])
        self.assertLess(abs(repaired_z[84,50]), .0005)
        self.assertGreater(stats['sewn_rim_fraction'], .97)
        self.assertGreater(stats['removed_skin_triangles'], 1000)
        np.testing.assert_allclose(original_z[:15], repaired_z[:15], atol=1e-6)

    def test_porosity_cannot_create_large_steps_between_neighbors(self):
        native = np.zeros((80,80), np.float32)
        native[26:34, 27:35] = -.12
        donor = np.zeros_like(native)
        mask = np.zeros_like(native, dtype=np.uint8)
        mask[10:70, 12:68] = 1
        step = .0004
        delta, _ = _bounded_relief(native, donor, mask, step, .05)
        self.assertTrue(np.all(delta[mask == 0] == 0))
        for axis in (0, 1):
            self.assertLessEqual(float(np.max(np.abs(np.diff(delta, axis=axis)))), .44 * step)

    def test_socket_preserves_winding_and_does_not_move_the_original_lid(self):
        import trimesh
        plane = trimesh.creation.box(extents=(3., 3., .4))
        for _ in range(4):
            plane = plane.subdivide()
        verts = np.ascontiguousarray(plane.vertices)
        out, faces = _eye_well(verts, plane.faces, np.array([.012,.015]), np.array([1.,0.]),
                               np.array([0.,1.]), .67, .28, .45, -.05)
        mesh = trimesh.Trimesh(out, faces, process=False)
        self.assertTrue(mesh.is_winding_consistent)
        self.assertTrue(mesh.is_watertight)
        np.testing.assert_array_equal(verts, out[:len(verts)])
        self.assertTrue((mesh.area_faces > 1e-12).all())

    def test_overstretched_facial_surface_is_rejected(self):
        vertices = np.array([[0., 0., 0.], [1.,0.,0.], [0.,1.,0.]])
        after = vertices.copy()
        after[1] = [10., 0., 0.]
        with self.assertRaisesRegex(ValueError, 'overstretch'):
            _deformation_quality(vertices, after, np.array([[0,1,2]]), np.ones(3, dtype=bool))

    def test_bad_landmarks_stop_before_moving_the_mesh(self):
        subject = Image.new('RGBA', (100, 180), 'white')
        with self.assertRaisesRegex(ValueError, 'upright'):
            face_landmarks(dict(image_size=subject.size, landmarks=[[.5, .5, 0]] * 478), subject)

    def test_closeup_changes_only_tokens_inside_the_face(self):
        import torch
        config = SimpleNamespace(patch_size=16, num_register_tokens=4)
        pipeline = SimpleNamespace(image_cond_model=SimpleNamespace(model=SimpleNamespace(config=config)))
        pipeline.get_cond = lambda *a, **k: {'cond': torch.ones(1, 5 + 32**2, 3)}
        body = torch.zeros(1, 5 + 64**2, 3)
        negative = torch.zeros_like(body)
        subject = Image.new('RGBA', (1000, 1000), 'white')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'head.png'
            subject.crop((430, 10, 570, 150)).save(path)
            result = portrait_conditioning(pipeline, dict(cond=body, neg_cond=negative),
                subject, np.array([[445, 28], [555, 130]]), {'crop_box':[430, 10, 570, 150]}, path, 1024)
        self.assertTrue(torch.all(result['cond'][:, :5] == 0))
        grid = body[0, 5:].reshape(64, 64, 3)
        self.assertGreater(float(grid[:12].max()), .5)
        self.assertEqual(float(grid[12:].abs().sum()), 0.)
        self.assertEqual(float(negative.abs().sum()), 0.)

    def test_each_eye_has_its_own_pivot_and_portable_material(self):
        import trimesh
        from glb_data import image, read
        eyes = [dict(name=name, center=[x, .4, .06], radius=.01, gaze=[.05, -.08], iris_rgb=color)
                for name, x, color in (('Eye.L', .02, [65,44,29]), ('Eye.R', -.02, [36,75,112]))]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'character.glb'
            body = trimesh.Scene()
            body.add_geometry(trimesh.creation.box(), geom_name='Body', node_name='Body')
            body.export(path)
            before, binary = read(path)
            counts = append_eyes(path, eyes, {'scale':2., 'translation':[0,1,0]})
            scene = trimesh.load_scene(path)
            doc, combined = read(path)
        self.assertEqual(binary, combined[:len(binary)])
        self.assertEqual(before['meshes'][0], doc['meshes'][0])
        self.assertEqual(set(scene.graph.nodes_geometry), {'Body','Eye.L','Eye.R'})
        self.assertEqual(counts['triangles'], len(scene.geometry['Eye.L'].faces) * 2)
        self.assertIn('KHR_materials_specular', doc['extensionsUsed'])
        for material in doc['materials']:
            if material.get('name', '').endswith(' iris'):
                self.assertLess(material['extensions']['KHR_materials_specular']['specularFactor'], .30)
                tex = material['pbrMetallicRoughness']['baseColorTexture']['index']
                iris = np.asarray(image(doc, combined, doc['textures'][tex]['source']))[24, 0, :3]
                expected = next(eye['iris_rgb'] for eye in eyes if material['name'] == eye['name'] + ' iris')
                self.assertEqual(int(iris.argmax()), int(np.argmax(expected)))
        for eye in eyes:
            transform, _ = scene.graph[eye['name']]
            np.testing.assert_allclose(transform[:3, 3], np.asarray(eye['center']) * 2 + [0,1,0])
        self.assertTrue(any('baseColorTexture' in mat.get('pbrMetallicRoughness', {}) for mat in doc['materials']))


class EyeOpeningTests(unittest.TestCase):
    def test_final_export_detects_a_globe_visible_above_the_lid(self):
        import trimesh
        from facial_head_eyes import append_eyes

        grid_x, grid_y = np.meshgrid(np.linspace(-.060, .060, 121), np.linspace(-.024, .024, 49))
        verts = np.column_stack([grid_x.ravel(), grid_y.ravel(), np.full(grid_y.size, .014)])
        corners = np.arange(grid_x.size).reshape(grid_x.shape)
        outline = [part.ravel() for part in (corners[:-1, :-1], corners[:-1, 1:],
                                             corners[1:, 1:], corners[1:, :-1])]
        a, b, c, d = outline
        triangles = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
        centers = verts[triangles].mean(axis=1)
        x = np.abs(centers[:, 0]) - .029
        y = centers[:, 1]
        main = (x / .010)**2 + (y / .003)**2 < 1
        extra = (x / .004)**2 + ((y - .008) / .0018)**2 < 1
        eyes = [dict(name=side, center=[cx, 0, 0], radius=.012, gaze=[0, 0], iris_rgb=[55, 42, 32])
                for side, cx in [('Eye.L', .029), ('Eye.R', -.029)]]
        normalization = {'scale': 1., 'translation': [0., 0., 0.]}
        with tempfile.TemporaryDirectory() as directory:
            glb = Path(directory) / 'model.glb'
            for double in (False, True):
                holes = main | extra if double else main
                shield = trimesh.Trimesh(vertices=verts, faces=triangles[~holes], process=False)
                glb.write_bytes(shield.export(file_type='glb'))
                original = glb.read_bytes()
                if double:
                    with self.assertRaisesRegex(ValueError, 'second opening'):
                        append_eyes(glb, eyes, normalization, check_openings=True)
                    self.assertEqual(glb.read_bytes(), original)
                else:
                    report = append_eyes(glb, eyes, normalization, check_openings=True)
                    for opening in report['visible_openings'].values():
                        self.assertEqual(opening['second_opening_pixels'], 0)
                        self.assertGreater(opening['largest_opening_pixels'], 60)


if __name__ == '__main__':
    unittest.main()
