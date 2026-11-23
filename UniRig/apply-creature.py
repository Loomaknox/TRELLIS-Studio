"""Apply the edited creature skeleton to UniRig's unskinned FBX mesh."""
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback

for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '2'

import bpy
import numpy as np
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from creature_rig import validate_creature_edit
from skeleton_alignment import align, mesh_points


def apply_creature(job):
    work = job / 'rig-work'
    edit = validate_creature_edit(json.loads((job / 'creature-edit.json').read_text(encoding='utf-8')))
    revision = hashlib.sha256((job / 'rig-preview.json').read_bytes()).hexdigest()
    if edit['revision'] != revision:
        raise ValueError('The edited skeleton does not match the current prediction.')

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(job / 'source.glb'))
    target = mesh_points(bpy.context.scene)
    if not target.size:
        raise ValueError('The source GLB has no mesh to rig.')
    low, high = target.min(axis=0), target.max(axis=0)
    size = float(np.max(high - low))
    if not np.isfinite(size) or size <= 0:
        raise ValueError('The source GLB has no usable bounds.')

    # The browser uses glTF Y-up; Blender uses Z-up. Limit corrections against
    # the actual source bounds before converting to UniRig's normalized FBX.
    requested = {}
    for bone in edit['bones']:
        points = np.asarray([[x, -z, y] for x, y, z in (bone['head'], bone['tail'])])
        if np.any(points < low - size * .5) or np.any(points > high + size * .5):
            raise ValueError(f'Bone {bone["name"]} is too far from the source mesh.')
        if np.linalg.norm(points[1] - points[0]) < size * 1e-5:
            raise ValueError(f'Bone {bone["name"]} is too short for this mesh.')
        requested[bone['name']] = points

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(work / 'skeleton.fbx'), use_image_search=False)
    arms = [obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE']
    if len(arms) != 1:
        raise ValueError('The prediction must have one armature to edit.')
    arm = arms[0]
    _, to_model = align(mesh_points(bpy.context.scene), target, np.empty((0, 6)))
    to_local = np.asarray(arm.matrix_world.inverted()) @ np.linalg.inv(to_model)

    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    bones = arm.data.edit_bones
    for bone in list(bones):
        bone.use_connect = False
        bone.parent = None
        if bone.name not in requested:
            bones.remove(bone)
    for specification in edit['bones']:
        name = specification['name']
        parent = specification['parent']
        bone = bones.get(name)
        if bone is None:
            bone = bones.new(name)
        if bone.name != name:
            raise ValueError(f'Unable to preserve the bone name {name}.')
        points = requested[name] @ to_local[:3, :3].T + to_local[:3, 3]
        bone.head, bone.tail = (Vector(point) for point in points)
        bone.parent = bones[parent] if parent is not None else None
        bone.use_deform = True
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    output = work / 'skeleton-creature.fbx'
    exported = bpy.ops.export_scene.fbx(
        filepath=str(output), use_selection=True, add_leaf_bones=False,
        bake_anim=False, object_types={'ARMATURE', 'MESH'}, path_mode='AUTO',
    )
    if 'FINISHED' not in exported:
        raise ValueError('Could not write the creature skeleton for skinning.')
    print(f'Applied {len(requested)} edited creature bones before skin inference', flush=True)


if __name__ == '__main__':
    job = Path(sys.argv[1]).resolve()
    try:
        apply_creature(job)
    except Exception as error:
        (job / 'rig-work' / 'creature-error.json').write_text(
            json.dumps({'message': str(error)}), encoding='utf-8',
        )
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    os._exit(0)
