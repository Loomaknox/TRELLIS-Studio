"""Real Blender retarget and append checks, using installed Quaternius assets."""
from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import os
import runpy
import shutil
import struct
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rig_profiles_blender import validate_profile_mapping
from studio_import import validate_glb
import retarget_motions

fixture = runpy.run_path(str(ROOT/'tests'/'rig_profiles_blender.py'))['fixture']
retarget_motions.ROOT = Path(os.environ.get('TRELLIS_ANIMATION_ASSET_ROOT', ROOT))
for recipe in retarget_motions.BY_ID.values():
    if recipe['id'] in ('idle', 'climb_ledge_1m'):
        assert (retarget_motions.ROOT/recipe['source_model']).is_file(), 'Installed Quaternius assets are required.'


def run_worker(job, settings):
    (job/'settings.json').write_text(json.dumps(settings), encoding='utf-8')
    previous = sys.argv
    try:
        sys.argv = [str(ROOT/'standard_animations.py'), '--', str(job)]
        runpy.run_path(str(ROOT/'standard_animations.py'), run_name='__main__')
    finally:
        sys.argv = previous
    return json.loads((job/'result.json').read_text(encoding='utf-8'))


def add_existing_names(path, names):
    raw = path.read_bytes()
    length = struct.unpack_from('<I', raw, 12)[0]
    data = json.loads(raw[20:20+length])
    for name in names:
        clip = copy.deepcopy(data['animations'][0])
        clip['name'] = name
        data['animations'].append(clip)
    descriptor = json.dumps(data, ensure_ascii=False).encode()
    descriptor += b' ' * (-len(descriptor)%4)
    tail = raw[20+length:]
    path.write_bytes(struct.pack('<4sIIII', b'glTF', 2, 20+len(descriptor)+len(tail),
                                len(descriptor), 0x4e4f534a)+descriptor+tail)


with TemporaryDirectory(prefix='trellis-advanced-pipeline-') as temporary:
    folder = Path(temporary)
    for articulated, count in ((False, 24), (True, 54)):
        arm, mesh, mapping, _ = fixture()
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        arm.data.edit_bones.remove(arm.data.edit_bones['tool_joint'])
        bpy.ops.object.mode_set(mode='OBJECT')
        # Include the character's full height in the mesh bounds used by inference.
        bounds_data = bpy.data.meshes.new('Height fixture')
        bounds_data.from_pydata([(0, 0, 0), (.05, 0, 0), (0, 0, 1.6)], [], [(0, 1, 2)])
        bounds_mesh = bpy.data.objects.new('Height fixture', bounds_data)
        bpy.context.collection.objects.link(bounds_mesh)
        bounds_mesh.parent = arm
        modifier = bounds_mesh.modifiers.new('Skin', 'ARMATURE')
        modifier.object = arm
        bounds_mesh.vertex_groups.new(name=mapping['root']).add([0, 1, 2], 1., 'REPLACE')
        source = folder/str(count)
        (source/'rig-work').mkdir(parents=True)
        bpy.ops.export_scene.gltf(filepath=str(source/'rig-work'/'rigged.glb'), export_format='GLB')
        settings = dict(rig_options=dict(profile='advanced', articulated_fingers=articulated),
                        animation_clips=[dict(id='idle', duration=1.)])
        result = run_worker(source, settings)
        first = validate_glb(source/'model.glb')
        assert len(first['skins'][0]['joints']) == result['rig_profile']['joint_count'] == count
        assert {clip['name'] for clip in first['animations']} == {'TS_idle_1.0s'}
        names = ['Generated_fixture_'+('long_'*14), 'Generated_'+('é'*40)]
        add_existing_names(source/'model.glb', names)
        append = folder/(str(count)+'-append')
        (append/'rig-work').mkdir(parents=True)
        shutil.copy2(source/'model.glb', append/'rig-work'/'rigged.glb')
        settings.update(existing_rig_profile=result['rig_profile'],
                        existing_humanoid_mapping=result['humanoid_mapping'],
                        previous_animation_set=result['animation_set'],
                        animation_clips=[dict(id='idle', duration=1.), dict(id='climb_ledge_1m', duration=1.)],
                        regenerate_ids=['climb_ledge_1m'])
        updated = run_worker(append, settings)
        after = validate_glb(append/'model.glb')
        assert {clip['name'] for clip in after['animations']} == {'TS_idle_1.0s', 'TS_climb_ledge_1m_1.0s', *names}
        assert len(after['skins'][0]['joints']) == count
        assert updated['rig_profile'] == result['rig_profile']
        assert updated['humanoid_mapping'] == result['humanoid_mapping']
        assert updated['humanoid_mapping']['head'] == 'head_joint'
        assert set(names) <= {action.get('studio_original_clip_name') for action in bpy.data.actions}
        validate_profile_mapping(next(obj for obj in bpy.context.scene.objects if obj.type=='ARMATURE'),
                                 updated['humanoid_mapping'], 'advanced')
        for side, name in updated['rig_profile']['twists'].items():
            node = next(i for i, node in enumerate(after['nodes']) if node.get('name')==name)
            for clip in after['animations']:
                assert any(channel['target']==dict(node=node,path='rotation') for channel in clip['channels'])
        assert (append/'model.blend').is_file()
        print(f'PASS: Advanced {count}, UAL1 idle, UAL2 traversal, preserved long/UTF-8 clips and helper channels', flush=True)
