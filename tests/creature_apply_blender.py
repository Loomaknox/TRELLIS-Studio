"""Blender FBX/GLB edit-frame roundtrip; only UniRig's fitted affine is a fixture."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def points(scene):
    return np.array([list(obj.matrix_world @ vertex.co) for obj in scene.objects
                     if obj.type == 'MESH' for vertex in obj.data.vertices])


def main():
    with TemporaryDirectory(prefix='trellis-creature-frame-') as temporary:
        job = Path(temporary)
        work = job / 'rig-work'
        work.mkdir()
        # Nonidentity scale and offset isolate the edited model/normalized-FBX
        # frame boundary without loading UniRig or any inference dependencies.
        transform = np.eye(4)
        transform[:3, :3] *= 2.5
        transform[:3, 3] = [1.1, -.4, .3]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=2)
        surface = bpy.context.object
        for vertex in surface.data.vertices:
            vertex.co = tuple(np.asarray(vertex.co) * 2.5 + transform[:3, 3])
        bpy.ops.export_scene.gltf(filepath=str(job / 'source.glb'), export_format='GLB', export_animations=False)
        before = hashlib.sha256((job / 'source.glb').read_bytes()).hexdigest()

        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.mesh.primitive_cube_add(size=2)
        bpy.ops.object.armature_add()
        armature = bpy.context.object
        bpy.ops.object.mode_set(mode='EDIT')
        root = armature.data.edit_bones[0]
        root.name = 'root'
        root.head, root.tail = [0, 0, 0], [0, 0, .5]
        old = armature.data.edit_bones.new('old_tip')
        old.head, old.tail, old.parent = [0, 0, .5], [0, 0, 1], root
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.export_scene.fbx(filepath=str(work / 'skeleton.fbx'), add_leaf_bones=False,
                                bake_anim=False, object_types={'ARMATURE', 'MESH'})
        skeleton_before = hashlib.sha256((work / 'skeleton.fbx').read_bytes()).hexdigest()
        preview = json.dumps({'bones': [], 'aligned_to_model': True}).encode('utf-8')
        (job / 'rig-preview.json').write_bytes(preview)

        def gltf(point):
            model = np.asarray(point) * 2.5 + transform[:3, 3]
            return [float(model[0]), float(model[2]), float(-model[1])]

        bones = [dict(name='root', parent=None, head=gltf([0, 0, 0]), tail=gltf([0, 0, .5])),
                 dict(name='edited_tip', parent='root', head=gltf([0, 0, .5]), tail=gltf([.2, 0, .9]))]
        edit = dict(revision=hashlib.sha256(preview).hexdigest(), bones=bones, motion='test')
        (job / 'creature-edit.json').write_text(json.dumps(edit), encoding='utf-8')
        sys.modules['skeleton_alignment'] = SimpleNamespace(
            align=lambda *_: (np.empty((0, 6)), transform), mesh_points=points)
        spec = importlib.util.spec_from_file_location('apply_creature_fixture', ROOT / 'UniRig' / 'apply-creature.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        entry.apply_creature(job)
        assert hashlib.sha256((job / 'source.glb').read_bytes()).hexdigest() == before
        assert hashlib.sha256((work / 'skeleton.fbx').read_bytes()).hexdigest() == skeleton_before
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.fbx(filepath=str(work / 'skeleton-creature.fbx'), use_image_search=False)
        armature, = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']
        assert set(armature.data.bones.keys()) == {'root', 'edited_tip'}
        assert armature.data.bones['edited_tip'].parent.name == 'root'
        for bone in bones:
            actual = armature.data.bones[bone['name']]
            endpoints = []
            for local in (actual.head_local, actual.tail_local):
                normalized = np.asarray(armature.matrix_world @ local)
                model = normalized @ transform[:3, :3].T + transform[:3, 3]
                endpoints.append(model[[0, 2, 1]] * [1, 1, -1])
            assert np.allclose(endpoints[0], bone['head'], atol=1e-4)
            # FBX leaf-tail length is display metadata inferred on reimport;
            # joint origin and its local orientation must remain exact.
            axis = endpoints[1] - endpoints[0]
            expected = np.asarray(bone['tail']) - bone['head']
            assert np.allclose(axis / np.linalg.norm(axis), expected / np.linalg.norm(expected), atol=1e-4)
        edit['revision'] = '0'*64
        (job / 'creature-edit.json').write_text(json.dumps(edit), encoding='utf-8')
        try:
            entry.apply_creature(job)
        except ValueError as error:
            assert 'current prediction' in str(error)
        else:
            raise AssertionError('A stale edited preview was accepted')
    print('PASS: edited Creature hierarchy and nonidentity model/FBX frame roundtrip; source snapshots unchanged.')


if __name__ == '__main__':
    main()
