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
from facial_head_infer import aligned_portrait
from pose_surface_diagnostics import inspect_surfaces


class QualityDiagnosticsTests(unittest.TestCase):
    def test_original_edges_before_subject_framing(self):
        im=Image.new('RGBA',(160,160))
        draw=ImageDraw.Draw(im)
        draw.rectangle((70,22,90,140), fill='white');draw.rectangle((8,48,150,55), fill='white')
        self.assertEqual(reference_warnings(im,None,'trellis2'),[])
        draw.line((0,52,8,52), fill='white')
        self.assertEqual(reference_warnings(im,None,'trellis2'),['reference_edge_left'])
        draw.rectangle((76,0,80,24), fill='white')
        self.assertEqual(reference_warnings(im,None,'pixal3d'),['reference_edge_left','reference_edge_top'])

    def test_portrait_alignment_uses_body_frame(self):
        image=Image.new('RGBA',(100,100))
        ImageDraw.Draw(image).rectangle((8,8,40,40),fill='red')
        points=np.zeros((478,3))
        points[[468,473,1,61,291],:2]=[[20,30],[40,30],[30,38],[25,45],[35,45]]
        warped=aligned_portrait(image,points,points/2,(0,0,50,50),100)
        self.assertEqual(warped.getpixel((14,14)),(255,0,0,255))
        self.assertEqual(warped.getpixel((65,60)),(0,0,0,0))

    def test_optional_intersections_use_node_placement(self):
        a=trimesh.Trimesh(vertices=[(0,0,0),(2,0,0),(0,2,0)],faces=[(0,1,2)],process=False)
        b=trimesh.Trimesh(vertices=[(.4,.4,-1),(.4,.4,1),(.4,1,.8)],faces=[(0,1,2)],process=False)
        scene=trimesh.Scene()
        scene.add_geometry(a,node_name='arm');scene.add_geometry(b,node_name='shoulder')
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'model.glb'
            scene.export(destination)
            self.assertNotIn('pose_surfaces',diagnose(destination.parent))
            deep=diagnose(destination.parent,pose_surfaces=True)['pose_surfaces']
            self.assertEqual(deep['worst_crossing']['pairs'],1)
            self.assertEqual(len(deep['worst_crossing']['triangles_m']),2)
            scene.graph.update(frame_to='shoulder',matrix=trimesh.transformations.translation_matrix([4,0,0]),
                               geometry=scene.graph['shoulder'][1])
            scene.export(destination)
            self.assertNotIn('worst_crossing',diagnose(destination.parent,force=True,pose_surfaces=True)['pose_surfaces'])

    def test_worst_pose_and_invalid_weights_are_localized(self):
        raw=bytearray()
        doc=dict(nodes=[dict(name='Arm',mesh=0,skin=0),dict(name='Plate',mesh=1,translation=[4,0,0]),
                        dict(name='Wrist')],skins=[dict(joints=[2])],meshes=[],buffers=[{}],accessors=[],bufferViews=[])
        def add(values,kind,component=5126):
            values=np.asarray(values,dtype='<f4' if component==5126 else 'u1')
            raw.extend(b'\0'*(-len(raw)%4));offset=len(raw);raw.extend(values.tobytes())
            index=len(doc['accessors']);doc['bufferViews'].append(dict(buffer=0,byteOffset=offset,byteLength=values.nbytes))
            doc['accessors'].append(dict(bufferView=index,count=len(values),type=kind,componentType=component))
            return index
        for tri in [[(0,0,0),(2,0,0),(0,2,0)],[(.4,.4,-1),(.4,.4,1),(.4,1,.8)]]:
            attrs={'POSITION':add(tri,'VEC3')}
            if not doc['meshes']:
                attrs['WEIGHTS_0']=add([[1,0,0,0],[1,0,0,0],[0,0,0,0]],'VEC4')
                attrs['JOINTS_0']=add(np.zeros((3,4)),'VEC4',5121)
            doc['meshes'].append(dict(primitives=[dict(attributes=attrs)]))
        doc['animations']=[dict(name='Contact',samplers=[dict(input=add([0,1,2],'SCALAR'),output=add([[4,0,0],[0,0,0],[4,0,0]],'VEC3'))],
                                channels=[dict(sampler=0,target=dict(node=1,path='translation'))])]
        doc['buffers'][0]['byteLength']=len(raw)
        result=inspect_surfaces(doc,raw,{})
        self.assertEqual(result['weights'][0]['vertex_ids'],[2])
        self.assertEqual(result['weights'][0]['locations_m'],[[0,2,0]])
        self.assertEqual(result['worst_crossing']['clip'],'Contact')
        self.assertGreater(result['worst_crossing']['time_s'],0)
        self.assertLess(result['worst_crossing']['time_s'],2)
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
