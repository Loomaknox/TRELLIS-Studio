"""Geometry and skin contract for Studio's Blender rig profiles."""

from pathlib import Path
from tempfile import TemporaryDirectory
import math
import sys

import bpy
from mathutils import Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rig_expert_blender import EXPERT_HELPER_SOURCES, EXPRESSIVE_HELPER_SOURCES, expert_helpers
from rig_profiles_blender import RigidHandsRecommended, apply_profile, validate_profile_mapping
from retarget_motions import blend_crouch_pose, body_helper_drivers, drive_body_helpers, drive_forearm_twists


def fixture(*, joined=False, split_seam=False, noisy_fingers=False, short_tip=False,
            extra_weight=False, bridge=False, body_profile=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.armature_add()
    arm = bpy.context.object
    bpy.ops.object.mode_set(mode='EDIT')
    bones = arm.data.edit_bones
    bones.remove(bones[0])
    mapping = {}

    def add(role, parent, head, tail):
        name = role + '_joint'
        bone = bones.new(name)
        bone.head, bone.tail = head, tail
        bone.parent = bones.get(mapping.get(parent, parent)) if parent else None
        mapping[role] = name
        return name

    previous = None
    for role, z in [('root', 0.9), ('spine_1', 1), ('spine_2', 1.1), ('spine', 1.25),
                    ('neck', 1.4), ('head', 1.5)]:
        add(role, previous, (0, 0, z), (0, 0, z + .075))
        previous = role
    for side, sign in [('left', 1), ('right', -1)]:
        def limb(part, previous, head, tail):
            return add(f'{side}_{part}', previous, (sign * head[0], *head[1:]), (sign * tail[0], *tail[1:]))

        limb('clavicle', 'spine', (.08, 0, 1.33), (.22, 0, 1.33))
        limb('arm', side + '_clavicle', (.22, 0, 1.33), (.44, 0, 1.32))
        limb('forearm', side + '_arm', (.44, 0, 1.32), (.68, 0, 1.32))
        limb('hand', side + '_forearm', (.68, 0, 1.32), (.75, 0, 1.32))
        limb('leg', 'root', (.12, 0, .92), (.12, 0, .54))
        limb('shin', side + '_leg', (.12, 0, .54), (.12, 0, .14))
        limb('foot', side + '_shin', (.12, 0, .14), (.12, -.12, .06))
        limb('toe', side + '_foot', (.12, -.12, .06), (.12, -.22, .06))
        for finger in range(5):
            y = (finger - 2) * .022
            step = .0185 if short_tip and side == 'right' and finger == 1 else .026
            previous = side + '_hand'
            for segment in range(3):
                role = f'{side}_finger_{finger}_{segment}'
                x = sign * (.75 + segment * step)
                add(role, previous, (x, y, 1.32), (x + sign * step, y, 1.32))
                previous = role
    if bridge:
        hint = add('arm_hint', 'left_arm', (.28, 0, 1.34), (.32, 0, 1.34))
        bones[mapping['left_forearm']].parent = bones[hint]
    add('tool', 'head', (0, 0, 1.7), (0, .1, 1.7))
    bpy.ops.object.mode_set(mode='OBJECT')

    points, faces, weights, sleeves, tips = [], [], [], {}, {}

    def ring(x, y, z, radius, assigned):
        indices = []
        for i in range(8):
            angle = i * math.tau / 8
            indices.append(len(points))
            points.append((x, y + radius * math.cos(angle), z + radius * math.sin(angle)))
            weights.append(assigned)
        return indices

    def link(first, second):
        for i in range(len(first)):
            nxt = (i + 1) % len(first)
            faces.append((first[i], first[nxt], second[nxt], second[i]))

    for side, sign in [('left', 1), ('right', -1)]:
        chain = []
        for i in range(11):
            t = i / 10
            blend = max(0., (t - .8) * 5)
            section = ring(sign * (.44 + .24 * t), 0, 1.32, .035,
                           {side + '_forearm': 1. - blend, side + '_hand': blend})
            if chain:
                link(chain[-1], section)
            chain.append(section)
        sleeves[side] = chain
        for finger in range(5):
            last = None
            for segment in range(3):
                role = f'{side}_finger_{finger}_{segment}'
                section = ring(sign * (.759 + segment * .026), (finger - 2) * .022, 1.32, .008,
                               {role: 1.})
                if noisy_fingers and finger == 1 and segment == 2:
                    for index in section[:4]:
                        weights[index] = {role: .4, f'{side}_finger_2_{segment}': .6}
                if last:
                    link(last, section)
                last = section
            if short_tip and side == 'right' and finger == 1:
                end = ring(-.829, (finger - 2) * .022, 1.32, .008, {role: 1.})
                link(section, end)
            tips[(side, finger)] = section
    if joined:
        left_tip, right_tip = tips[('left', 1)], tips[('left', 2)]
        if split_seam:
            seam = []
            for index in (*left_tip[:2], *reversed(right_tip[:2])):
                seam.append(len(points))
                points.append(points[index])
                weights.append(weights[index])
            faces.append(tuple(seam))
        else:
            link(left_tip, right_tip)
    torso = ring(0, 0, .93, .1, {'tool': 1.} if extra_weight else {
        'root': .5, 'spine_1': .2, 'spine_2': .13, 'spine': .1, 'neck': .07,
    })
    faces.append(tuple(torso))
    if body_profile:
        helpers = expert_helpers(arm.data.bones, mapping, expressive=(body_profile == 'expressive'))
        role_by_name = {name: role for role, name in mapping.items()}
        for helper in helpers.values():
            donors = [role_by_name[name] for name in helper.donors]
            assignment = dict(zip(donors, (1.,) if len(donors) == 1 else (.7, .3)))
            faces.append(tuple(ring(*helper.head, .025, assignment)))
    data = bpy.data.meshes.new('Fixture Geometry')
    data.from_pydata(points, [], faces)
    data.update()
    mesh = bpy.data.objects.new('Fixture Mesh', data)
    bpy.context.collection.objects.link(mesh)
    mesh.parent = arm
    mod = mesh.modifiers.new('Fixture Skin', 'ARMATURE')
    mod.object = arm
    data.materials.append(bpy.data.materials.new('Fixture Material'))
    uv = data.uv_layers.new(name='Fixture UVs')
    for index, item in enumerate(uv.data):
        item.uv = (index % 3 * .25, index % 2 * .5)
    groups = {role: mesh.vertex_groups.new(name=name) for role, name in mapping.items()}
    for index, row in enumerate(weights):
        for role, weight in row.items():
            if weight > 0:
                groups[role].add([index], weight, 'REPLACE')
    mapping = {role: name for role, name in mapping.items() if role != 'tool' and '_finger_' not in role}
    return arm, mesh, mapping, sleeves['left']


def skin(mesh, vertex_index):
    return {mesh.vertex_groups[entry.group].name: entry.weight
            for entry in mesh.data.vertices[vertex_index].groups}


def geometry_signature(mesh):
    return (tuple(tuple(vertex.co) for vertex in mesh.data.vertices),
            tuple(tuple(polygon.vertices) for polygon in mesh.data.polygons),
            tuple(tuple(item.uv) for item in mesh.data.uv_layers.active.data),
            tuple(material.name for material in mesh.data.materials),
            tuple(tuple(row) for row in mesh.matrix_world))


def check_body_deformation(arm, mesh, mapping, *, expressive=False):
    rest = {bone.name: (arm.matrix_world @ bone.matrix_local).to_quaternion() for bone in arm.data.bones}
    heads = {bone.name: arm.matrix_world @ bone.head_local for bone in arm.data.bones}
    sources = {**EXPERT_HELPER_SOURCES, **EXPRESSIVE_HELPER_SOURCES} if expressive else EXPERT_HELPER_SOURCES
    for role, (parent_role, source_role, kind) in sources.items():
        name = mapping[role]
        helper = arm.pose.bones[name]
        source = arm.pose.bones[mapping[source_role]]
        helper.rotation_mode = source.rotation_mode = 'QUATERNION'
        axial = (heads[source.name] - heads[mapping[parent_role]]).normalized()
        across = axial.orthogonal().normalized()
        motion, ignored = (axial, across) if kind == 'twist' else (across, axial)
        drivers = body_helper_drivers(arm, mapping, {role: name}, rest, heads, expressive=expressive)
        angle = math.radians(60.0 if kind == 'twist' else 25.0)
        fraction = 0.5
        if expressive and kind == 'twist':
            fraction = 2. / 3. if role in EXPRESSIVE_HELPER_SOURCES else 1. / 3.
            a, b = heads[mapping[parent_role]], heads[source.name]
            assert (heads[name] - a.lerp(b, fraction)).length < 1e-5, role

        source.rotation_quaternion = Quaternion(rest[source.name].inverted() @ ignored, angle)
        drive_body_helpers(drivers)
        assert abs(helper.rotation_quaternion.w) > 1. - 1e-6, role
        helper.rotation_quaternion.identity()

        source.rotation_quaternion = Quaternion(rest[source.name].inverted() @ motion, angle)
        bpy.context.view_layer.update()
        baked = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        indices = [v.index for v in mesh.data.vertices if skin(mesh, v.index).get(name, 0.) >= .005]
        before = {i: baked.data.vertices[i].co.copy() for i in indices}
        drive_body_helpers(drivers)
        expected = Quaternion(rest[name].inverted() @ motion, angle * fraction)
        assert abs(helper.rotation_quaternion.dot(expected)) > 1. - 1e-6, role
        bpy.context.view_layer.update()
        baked = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        assert before and max((baked.data.vertices[i].co - co).length for i, co in before.items()) > 1e-4, role
        source.rotation_quaternion.identity()
        helper.rotation_quaternion.identity()
    bpy.context.view_layer.update()


def check_profile(profile, articulated, expected, **kwargs):
    arm, mesh, mapping, rings = fixture(body_profile=profile if profile in ('expert', 'expressive') else None, **kwargs)
    geometry = geometry_signature(mesh)
    rest = {bone.name: bone.matrix_local.copy() for bone in arm.data.bones}
    hands = {mapping['left_hand'], mapping['right_hand']}
    tip_index = next(i for i, v in enumerate(mesh.data.vertices) if v.co.x > .805)
    old_skin = skin(mesh, tip_index)
    result, report = apply_profile(arm, [mesh], mapping, profile, articulated)
    assert len(result) == len(arm.data.bones) == report['joint_count'] == expected
    assert validate_profile_mapping(arm, result, profile) == result
    assert geometry_signature(mesh) == geometry
    for bone in arm.data.bones:
        if bone.name in rest:
            assert all((bone.matrix_local[i] - rest[bone.name][i]).length < 1e-6 for i in range(4))
    for vertex in mesh.data.vertices:
        influences = skin(mesh, vertex.index)
        assert 0 < len(influences) <= 4
        assert abs(sum(influences.values()) - 1) < 1e-6
        assert set(influences) <= set(result.values())
    if articulated:
        assert skin(mesh, tip_index) == old_skin
    else:
        assert set(skin(mesh, tip_index)) <= hands
    if profile == 'advanced':
        name = report['twists']['left']
        assert arm.data.bones[name].parent.name == mapping['left_forearm']
        assert name not in skin(mesh, rings[0][0])
        assert skin(mesh, rings[7][0])[name] > skin(mesh, rings[4][0])[name]
        assert arm.data.bones[mapping['left_hand']].parent.name == mapping['left_forearm']
    if profile in ('expert', 'expressive'):
        expressive = profile == 'expressive'
        expected_helpers = set(EXPERT_HELPER_SOURCES) | (set(EXPRESSIVE_HELPER_SOURCES) if expressive else set())
        assert set(report['body_helpers']) == expected_helpers
        assert all(result[role] == name for role, name in report['body_helpers'].items())

        # A helper must move the mesh, and it may not evict a full set of original influences.
        torso_index = next(v.index for v in mesh.data.vertices if abs(v.co.x) < .001 and abs(v.co.z - .93) < .001)
        assert set(skin(mesh, torso_index)) == {mapping[role] for role in ('root', 'spine_1', 'spine_2', 'spine')}
        check_body_deformation(arm, mesh, result, expressive=expressive)
    print(f'Validated {profile} ({expected} bones, fingers={articulated})', flush=True)
    return arm, mesh, result, rings


def set_wrist_pose(arm, mapping, degrees, twists=None, *, expressive=False):
    rest = {bone.name: (arm.matrix_world @ bone.matrix_local).to_quaternion() for bone in arm.data.bones}
    heads = {bone.name: arm.matrix_world @ bone.head_local for bone in arm.data.bones}
    wrist = arm.pose.bones[mapping['left_hand']]
    wrist.rotation_mode = 'QUATERNION'
    forearm = mapping['left_forearm']
    world_axis = (heads[wrist.name] - heads[forearm]).normalized()
    wrist.rotation_quaternion = Quaternion(rest[wrist.name].inverted() @ world_axis, math.radians(degrees))
    if twists:
        proximal = 1. / 3. if expressive else .5
        for name in twists.values():
            arm.pose.bones[name].rotation_mode = 'QUATERNION'
        drive_forearm_twists(arm, mapping, twists, rest, heads, fraction=proximal)
        tangent = world_axis.cross(Vector((0, 0, 1))).normalized()
        probes = {twists['left']: proximal}
        if expressive:
            role = 'left_expressive_forearm_twist'
            name = mapping[role]
            arm.pose.bones[name].rotation_mode = 'QUATERNION'
            drive_body_helpers(body_helper_drivers(arm, mapping, {role: name}, rest, heads, expressive=True))
            probes[name] = 2. / 3.
        for name, fraction in probes.items():
            twist = arm.pose.bones[name]
            posed = rest[name] @ (twist.rotation_quaternion @ (rest[name].inverted() @ tangent))
            expected = Quaternion(world_axis, math.radians(degrees * fraction)) @ tangent
            assert (posed - expected).length < 1e-6
            assert (heads[name] - heads[forearm].lerp(heads[wrist.name], fraction)).length < 1e-5


def pose_extension(arm, mesh, mapping, rings, degrees, twists=None, *, expressive=False):
    set_wrist_pose(arm, mapping, degrees, twists, expressive=expressive)
    bpy.context.view_layer.update()
    baked = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
    ratios = []
    for first, second in zip(rings[:-1], rings[1:]):
        for a, b in zip(first, second):
            before = mesh.data.vertices[a].co - mesh.data.vertices[b].co
            after = baked.data.vertices[a].co - baked.data.vertices[b].co
            ratios.append(after.length / before.length)
    return max(ratios)


def expect_rejection(*, message, profile='standard', **kwargs):
    arm, mesh, mapping, _ = fixture(**kwargs)
    before = len(arm.data.bones), geometry_signature(mesh), [skin(mesh, v.index) for v in mesh.data.vertices]
    try:
        apply_profile(arm, [mesh], mapping, profile, True)
    except ValueError as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('An incompatible geometry was accepted')
    assert before == (len(arm.data.bones), geometry_signature(mesh),
                      [skin(mesh, vertex.index) for vertex in mesh.data.vertices])


def check_roundtrip(arm, mapping, profile):
    twists = {side: mapping[f'{side}_forearm_twist'] for side in ('left', 'right')}
    rest = {name: arm.matrix_world @ arm.data.bones[name].head_local for name in mapping.values()}
    with TemporaryDirectory(prefix='trellis-rig-test-') as temporary:
        file = str(Path(temporary) / 'rig-profile.glb')
        bpy.ops.export_scene.gltf(filepath=file, export_format='GLB')
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=file)
        arm = next(obj for obj in bpy.context.scene.objects if obj.type == 'ARMATURE')
        mesh = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH'
                    and any(m.type == 'ARMATURE' and m.object == arm for m in obj.modifiers))
        assert validate_profile_mapping(arm, mapping, profile) == mapping
        for name, point in rest.items():
            assert (arm.matrix_world @ arm.data.bones[name].head_local - point).length < 1e-5
        for vertex in mesh.data.vertices:
            influences = skin(mesh, vertex.index)
            assert 0 < len(influences) <= 4 and abs(sum(influences.values()) - 1) < 1e-5
        for degrees in (-90, 90):
            set_wrist_pose(arm, mapping, degrees, twists, expressive=(profile == 'expressive'))
        if profile in ('expert', 'expressive'):
            for pose in arm.pose.bones:
                pose.rotation_mode = 'QUATERNION'
                pose.rotation_quaternion.identity()
            check_body_deformation(arm, mesh, mapping, expressive=(profile == 'expressive'))


def check_finger_transition():
    def joint(degrees):
        return dict(rotation=Quaternion((0, 0, 1), math.radians(degrees)), head=Vector())

    def angle(rotation):
        return math.degrees(2 * math.acos(min(1, abs(rotation.normalized().w))))

    idle = dict(middle=joint(0), distal=joint(0))
    crouched = dict(middle=joint(170), distal=joint(200))
    legacy = blend_crouch_pose(idle, crouched, .5)
    revised = blend_crouch_pose(idle, crouched, .5, [('distal', 'middle')])
    legacy_local = legacy['middle']['rotation'].inverted() @ legacy['distal']['rotation']
    revised_local = revised['middle']['rotation'].inverted() @ revised['distal']['rotation']
    assert angle(legacy_local) > 160
    assert abs(angle(revised_local) - 15) < 1e-3
    assert revised['middle']['rotation'] == legacy['middle']['rotation']


def check_twist_continuity():
    arm, mesh, mapping, _ = fixture()
    mapping, profile = apply_profile(arm, [mesh], mapping, 'advanced', False)
    rest = {b.name: (arm.matrix_world @ b.matrix_local).to_quaternion() for b in arm.data.bones}
    heads = {b.name: arm.matrix_world @ b.head_local for b in arm.data.bones}
    hand = arm.pose.bones[mapping['left_hand']]
    helper = arm.pose.bones[profile['twists']['left']]
    axis = (heads[hand.name] - heads[mapping['left_forearm']]).normalized()
    for sign in (-1, 1):
        previous = {}
        for degrees in (170, 179, 181, 190):
            hand.rotation_quaternion = Quaternion(rest[hand.name].inverted() @ axis, math.radians(sign*degrees))
            drive_forearm_twists(arm, mapping, profile['twists'], rest, heads, previous=previous)
            expected = Quaternion(rest[helper.name].inverted() @ axis, math.radians(sign*degrees*.5))
            assert abs(helper.rotation_quaternion.dot(expected)) > 1-1e-6


def check_missing_phalanx():
    arm, mesh, mapping, _ = fixture()
    bone = 'right_finger_1_2_joint'
    group = mesh.vertex_groups[bone]
    vertices = [vertex.index for vertex in mesh.data.vertices if any(v.group == group.index for v in vertex.groups)]
    assert vertices
    mesh.vertex_groups['right_finger_1_1_joint'].add(vertices, 1., 'REPLACE')
    group.remove(vertices)
    try:
        apply_profile(arm, [mesh], mapping, 'standard', True)
    except RigidHandsRecommended as error:
        assert error.details == {'use_rigid_hands': True, 'joints': [
            {'side': 'right', 'finger': 2, 'phalanx': 3, 'bone': bone},
        ]}
    else:
        raise AssertionError('A finger without a weighted tip was accepted')
    _, report = apply_profile(arm, [mesh], mapping, 'simple', False)
    assert report['joint_count'] == 22


def main():
    check_finger_transition()
    check_missing_phalanx()
    check_twist_continuity()
    check_profile('simple', False, 22, bridge=True)
    standard, bare, basic, hand = check_profile('standard', True, 52)
    baseline = {sign: pose_extension(standard, bare, basic, hand, sign) for sign in (-90, 90)}
    check_profile('standard', True, 52, noisy_fingers=True)
    check_profile('standard', True, 52, short_tip=True)
    advanced, mesh, mapping, rings = check_profile('advanced', False, 24)
    twists = {side: mapping[f'{side}_forearm_twist'] for side in ('left', 'right')}
    for sign, extension in baseline.items():
        corrected = pose_extension(advanced, mesh, mapping, rings, sign, twists)
        print(f'{sign:+} degrees: forearm edge stretch {extension:.3f} to {corrected:.3f}', flush=True)
        assert corrected < extension
    advanced, _, mapping, _ = check_profile('advanced', True, 54)
    check_roundtrip(advanced, mapping, 'advanced')
    check_profile('expert', False, 49)
    expert, _, mapping, _ = check_profile('expert', True, 79)
    check_roundtrip(expert, mapping, 'expert')
    expressive, mesh, mapping, rings = check_profile('expressive', False, 65)
    twists = {side: mapping[f'{side}_forearm_twist'] for side in ('left', 'right')}
    for sign, extension in baseline.items():
        corrected = pose_extension(expressive, mesh, mapping, rings, sign, twists, expressive=True)
        print(f'{sign:+} degrees: Expressive forearm edge stretch {extension:.3f} to {corrected:.3f}', flush=True)
        assert corrected < extension
    expressive, _, mapping, _ = check_profile('expressive', True, 95)
    check_roundtrip(expressive, mapping, 'expressive')
    expect_rejection(joined=True, message='appears joined between fingers')
    expect_rejection(joined=True, split_seam=True, message='appears joined between fingers')
    expect_rejection(extra_weight=True, message='unsupported branch')
    expect_rejection(profile='expert', message='lacks local weights for Expert body helpers')
    expect_rejection(profile='expressive', message='lacks local weights for Expressive body helpers')


if __name__ == '__main__':
    main()
