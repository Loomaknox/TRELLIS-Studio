"""Run with Blender background: test creature clips and rig/mesh round-trip."""

import json
from pathlib import Path
import runpy
import struct
import sys
from tempfile import TemporaryDirectory

import bpy
from mathutils import Matrix, Quaternion, Vector


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from studio_import import validate_glb


def skeleton(kind):
    bones = []

    def add(name, parent, head, tail):
        bones.append(dict(name=name, parent=parent,
                          head=[head[0], head[2], -head[1]],
                          tail=[tail[0], tail[2], -tail[1]]))

    if kind == 'serpentine':
        y = 0.0
        add('root', None, (0, y, .2), (0, y + .2, .2))
        y += .2
        for index in range(7):
            length = .25 + .04 * index
            add(f'body_{index}', f'body_{index-1}' if index else 'root',
                (0, y, .2), (0, y + length, .2))
            y += length
    else:
        add('root', None, (0, .1, 1), (0, .5, 1))
        if kind == 'quadruped':
            for side in (-1, 1):
                for front in (-1, 1):
                    prefix = f'leg_{side}_{front}'
                    x, y = side * .4, front * .7
                    add(prefix, 'root', (x, y, .9), (x, y + .1, .45))
                    add(prefix + '_shin', prefix, (x, y + .1, .45), (x, y, .1))
        elif kind == 'winged':
            for side in (-1, 1):
                prefix = f'wing_{side}'
                add(prefix, 'root', (side * .2, .1, 1.1), (side * .7, .1, 1.15))
                add(prefix + '_outer', prefix, (side * .7, .1, 1.15), (side * 1.4, .3, 1.2))
        else:
            add('jaw', 'root', (0, .5, 1), (0, .7, .9))
    return bones


def fixture(job, bones):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.armature_add()
    armature = bpy.context.object
    bpy.ops.object.mode_set(mode='EDIT')
    edit = armature.data.edit_bones
    edit.remove(edit[0])
    vertices, faces = [], []
    for bone in bones:
        node = edit.new(bone['name'])
        x, y, z = bone['head']
        node.head = (x, -z, y)
        x, y, z = bone['tail']
        node.tail = (x, -z, y)
        if bone['parent']:
            node.parent = edit[bone['parent']]
        center = (node.head + node.tail) / 2
        origin = len(vertices)
        for offset in ((-.06, 0, -.06), (.06, 0, -.06), (.06, 0, .06), (-.06, 0, .06)):
            vertices.append(center + Vector(offset))
        faces.append(tuple(range(origin, origin + 4)))
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = bpy.data.meshes.new('Creature surface')
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new('Creature surface', mesh)
    bpy.context.collection.objects.link(obj)
    for index, bone in enumerate(bones):
        group = obj.vertex_groups.new(name=bone['name'])
        group.add(list(faces[index]), 1.0, 'REPLACE')
    modifier = obj.modifiers.new('Skin', 'ARMATURE')
    modifier.object = armature
    obj.parent = armature
    uv = mesh.uv_layers.new(name='UVMap')
    for polygon in mesh.polygons:
        for index, coords in zip(polygon.loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
            uv.data[index].uv = coords
    material = bpy.data.materials.new('Textured PBR')
    if material.node_tree is None:
        material.use_nodes = True
    texture = material.node_tree.nodes.new('ShaderNodeTexImage')
    texture.image = bpy.data.images.new('Creature atlas', 4, 4)
    texture.image.generated_color = (.1, .4, .7, 1.0)
    texture.image.pack()
    shader = material.node_tree.nodes.get('Principled BSDF')
    material.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    obj.data.materials.append(material)
    work = job / 'rig-work'
    work.mkdir(parents=True)
    source = work / 'rigged.glb'
    bpy.ops.export_scene.gltf(filepath=str(source), export_format='GLB', export_animations=False)
    return source


def graph(data):
    nodes = data['nodes']
    parents = {child: index for index, node in enumerate(nodes) for child in node.get('children', [])}

    def world(index):
        node = nodes[index]
        if 'matrix' in node:
            raw = node['matrix']
            matrix = Matrix(tuple(raw[i:i + 4] for i in range(0, 16, 4))).transposed()
        else:
            x, y, z, w = node.get('rotation', [0, 0, 0, 1])
            matrix = Matrix.LocRotScale(node.get('translation', [0, 0, 0]), Quaternion((w, x, y, z)),
                                        node.get('scale', [1, 1, 1]))
        return world(parents[index]) @ matrix if index in parents else matrix

    joints = set(data['skins'][0]['joints'])
    return {nodes[i]['name']: (nodes[parents[i]]['name'] if parents.get(i) in joints else None,
                              world(i).translation) for i in joints}


def binary_part(path):
    raw = path.read_bytes()
    json_length, = struct.unpack_from('<I', raw, 12)
    return raw[28 + json_length:]


def float_values(data, binary, accessor_index):
    accessor = data['accessors'][accessor_index]
    view = data['bufferViews'][accessor['bufferView']]
    width = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
    start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
    assert accessor['componentType'] == 5126
    return list(struct.iter_unpack('<' + 'f' * width,
                                   binary[start:start + accessor['count'] * width * 4]))


def verify_loop(data, binary, reported):
    clip, = data['animations']
    assert clip['name'] == reported['clip']
    animated = 0
    for channel in clip['channels']:
        if channel['target']['path'] != 'rotation':
            continue
        sampler = clip['samplers'][channel['sampler']]
        times = float_values(data, binary, sampler['input'])
        rotations = float_values(data, binary, sampler['output'])
        assert abs(times[0][0]) < 1e-6
        assert abs(times[-1][0] - reported['duration_s']) < 1e-5
        dot = sum(a * b for a, b in zip(rotations[0], rotations[-1]))
        assert abs(dot) > .999999
        if any(abs(sum(a * b for a, b in zip(rotations[0], pose))) < .9999 for pose in rotations):
            animated += 1
    return animated


def mesh_corners(data, binary):
    attrs = data['meshes'][0]['primitives'][0]['attributes']
    positions = float_values(data, binary, attrs['POSITION'])
    uvs = float_values(data, binary, attrs['TEXCOORD_0'])
    return sorted(tuple(round(component, 5) for component in position + uv)
                  for position, uv in zip(positions, uvs))


def run_fixture(job, kind, requested, applied, animated_bones):
    bones = skeleton(kind)
    source = fixture(job, bones)
    (job / 'settings.json').write_text(json.dumps({'rig_options': {'mode': 'creature'}}), encoding='utf-8')
    (job / 'creature-edit.json').write_text(json.dumps(dict(bones=bones, motion=requested)), encoding='utf-8')
    old_argv = sys.argv
    try:
        sys.argv = ['standard_animations.py', '--', str(job)]
        runpy.run_path(str(ROOT / 'standard_animations.py'))
    except SystemExit as error:
        assert error.code == 0, error.code
    finally:
        sys.argv = old_argv
    result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
    assert result['bones'] == len(bones) and result['humanoid_mapping'] == {}
    assert result['vertices'] == 4 * len(bones) and result['triangles'] == 2 * len(bones), result
    report = result['creature_motion']
    assert (report['requested'], report['applied'], report['animated_bones']) == (requested, applied, animated_bones), report
    assert bool(result['animation_warning']) == (requested != applied)
    assert (job / 'model.blend').stat().st_size > 0
    output = job / 'model.glb'
    before, after = validate_glb(source), validate_glb(output)
    expected, actual = graph(before), graph(after)
    assert actual.keys() == expected.keys() == {bone['name'] for bone in bones}
    for name, (parent, position) in expected.items():
        got_parent, got_position = actual[name]
        assert got_parent == parent and (got_position - position).length < 1e-5, (name, got_position, position)
    for data in (before, after):
        assert len(data['meshes']) == 1, 'Bone display meshes or duplicate geometry leaked into the GLB.'
        primitive, = data['meshes'][0]['primitives']
        assert {'POSITION', 'TEXCOORD_0', 'JOINTS_0', 'WEIGHTS_0'} <= set(primitive['attributes'])
        assert len(data['images']) == 1
        pbr = data['materials'][primitive['material']]['pbrMetallicRoughness']
        assert 'baseColorTexture' in pbr
    binary = binary_part(output)
    assert mesh_corners(before, binary_part(source)) == mesh_corners(after, binary)
    if applied != 'none':
        assert verify_loop(after, binary, result['animation_set'][0]) >= animated_bones
    else:
        assert not result['animation_set'] and not after.get('animations')


with TemporaryDirectory(prefix='trellis-creature-motion-') as folder:
    root = Path(folder)
    for kind, requested, applied, animated_bones in [
        ('quadruped', 'quadruped', 'quadruped', 8),
        ('serpentine', 'serpentine', 'serpentine', 7),
        ('winged', 'winged', 'winged', 4),
        ('quadruped', 'test', 'test', 8),
        ('incompatible', 'winged', 'test', 1),
        ('incompatible', 'none', 'none', 0),
    ]:
        run_fixture(root / f'{kind}-{requested}', kind, requested, applied, animated_bones)
print('Creature animation fixtures passed.')
