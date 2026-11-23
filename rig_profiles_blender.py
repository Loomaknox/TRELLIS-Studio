"""Build detachable humanoid profile variants in Studio's Blender worker."""

from collections import Counter, defaultdict
import math

import bpy

from rig_expert_blender import (
    EXPERT_HELPER_SOURCES, EXPRESSIVE_HELPER_SOURCES, EXPRESSIVE_TWIST_PROXIMAL,
    expert_helpers, expressive_forearm_support, helpers_by_donor, transfer_body_weights,
)


_SIDES = ('left', 'right')
_BODY_HELPER_PROFILES = ('expert', 'expressive')
_TWIST_PROFILES = ('advanced', *_BODY_HELPER_PROFILES)
_PROFILES = ('simple', 'standard', *_TWIST_PROFILES)


class RigidHandsRecommended(ValueError):
    def __init__(self, message, *, side=None, joints=()):
        super().__init__(message)
        self.details = {'use_rigid_hands': True}
        if side:
            self.details['side'] = side
        if joints:
            self.details['joints'] = [
                {'side': side, 'finger': finger + 1, 'phalanx': segment + 1, 'bone': bone}
                for side, finger, segment, bone in joints
            ]


_BODY_PARENTS = {
    'root': None,
    'spine_1': 'root',
    'spine_2': 'spine_1',
    'spine': 'spine_2',
    'neck': 'spine',
    'head': 'neck',
}
for _side in _SIDES:
    _BODY_PARENTS.update({
        f'{_side}_clavicle': 'spine',
        f'{_side}_arm': f'{_side}_clavicle',
        f'{_side}_forearm': f'{_side}_arm',
        f'{_side}_hand': f'{_side}_forearm',
        f'{_side}_leg': 'root',
        f'{_side}_shin': f'{_side}_leg',
        f'{_side}_foot': f'{_side}_shin',
        f'{_side}_toe': f'{_side}_foot',
    })


def _ancestor(bone, names):
    parent = bone.parent
    while parent is not None:
        if parent.name in names:
            return parent.name
        parent = parent.parent
    return None


def _body_mapping(arm, mapping):
    body = {role: mapping.get(role) for role in _BODY_PARENTS}
    retained = set(body.values())
    bones = arm.data.bones
    if None in retained or len(retained) != len(body) or any(name not in bones for name in retained):
        raise ValueError('This profile requires 22 distinct humanoid joints. Check the joint landmarks.')
    for role, parent in _BODY_PARENTS.items():
        if _ancestor(bones[body[role]], retained) != body.get(parent):
            raise ValueError('The humanoid joint hierarchy is incompatible with this profile. Check the joint landmarks.')
    return body


def _finger_mapping(bones, body):
    fingers = {}
    for side in _SIDES:
        roots = sorted(bones[body[f'{side}_hand']].children, key=lambda bone: bone.name)
        if len(roots) != 5:
            raise RigidHandsRecommended('Articulated fingers require five separate finger chains per hand. Choose rigid hands for this model.', side=side)
        for finger, bone in enumerate(roots):
            for segment in range(3):
                if bone.length < 1e-6:
                    raise RigidHandsRecommended('A finger joint is too short to articulate. Choose rigid hands or check the rig.',
                                                joints=[(side, finger, segment, bone.name)])
                fingers[f'{side}_finger_{finger}_{segment}'] = bone.name
                if segment < 2:
                    if len(bone.children) != 1:
                        raise RigidHandsRecommended('Articulated fingers require three joints per finger. Choose rigid hands for this model.',
                                                    joints=[(side, finger, segment, bone.name)])
                    bone = bone.children[0]
    return fingers


def _finger_regions(bones, fingers):
    result = {}
    for side in _SIDES:
        for index in range(5):
            role = f'{side}_finger_{index}_'
            chain = tuple(fingers[f'{role}{segment}'] for segment in range(3))
            start = bones[chain[0]].head_local.copy()
            end = bones[chain[-1]].tail_local.copy()
            axis = end - start
            if axis.length_squared < 1e-12:
                raise RigidHandsRecommended('The finger geometry does not match the skeleton. Choose rigid hands.', side=side)
            result[(side, index)] = (chain, start, axis / axis.length_squared)
    return result


def _distal_mesh(arm, mesh, matrix, body, regions, geometry_hits):
    """Detect actual mesh connections beyond the palm and normal finger webs."""
    from mathutils import Vector

    bones = arm.data.bones
    heel = (bones[body['left_foot']].head_local + bones[body['right_foot']].head_local) * 0.5
    height = (bones[body['head']].head_local - heel).length
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError('The finger geometry does not match the skeleton. Choose rigid hands.')
    radius = height * 0.017
    margin = height * 0.0035
    weld = 1 / (height * 1e-6)
    points = [matrix @ vertex.co for vertex in mesh.data.vertices]
    for side in _SIDES:
        digits = {}
        endpoints = []
        for finger, (chain, start, direction) in regions.items():
            if finger[0] != side:
                continue
            segments = []
            for name in chain:
                head, tail = bones[name].head_local.copy(), bones[name].tail_local.copy()
                axis = tail - head
                endpoints.extend((head, tail))
                # Imported leaf tails can fall short of the fingertip. Allow a
                # small overhang when comparing distances between neighboring digits.
                if name == chain[-1]:
                    axis += axis.normalized() * (radius * 0.5)
                segments.append((head, axis, 1 / axis.length_squared))
            digits[finger] = (start, direction, segments)
        low = Vector(min(endpoint[i] for endpoint in endpoints) - radius for i in range(3))
        high = Vector(max(endpoint[i] for endpoint in endpoints) + radius for i in range(3))
        crop = {}
        tags = {}
        for index, point in enumerate(points):
            if any(point[i] < low[i] or point[i] > high[i] for i in range(3)):
                continue
            ranked = []
            for finger, (start, direction, segments) in digits.items():
                distances = []
                for head, axis, inverse in segments:
                    delta = point - head
                    projection = min(1.0, max(0.0, delta.dot(axis) * inverse))
                    distances.append((delta - axis * projection).length)
                ranked.append((min(distances), finger, (point - start).dot(direction)))
            ranked.sort()
            nearest, finger, depth = ranked[0]
            if depth <= 0.50 or nearest > radius:
                continue
            # Include ambiguous points in the graph. They may form a real bridge
            # even when none can be confidently assigned to either digit.
            # glTF splits shared positions at UV and normal seams.
            key = tuple(round(value * weld) for value in point)
            crop[index] = key
            if depth > 0.67 and ranked[1][0] - nearest >= margin:
                tags[key] = finger
        graph = defaultdict(set)
        for edge in mesh.data.edges:
            a, b = (crop.get(index) for index in edge.vertices)
            if a is not None and b is not None and a != b:
                graph[a].add(b)
                graph[b].add(a)
        visited = set()
        for start in tags:
            if start in visited:
                continue
            stack = [start]
            visited.add(start)
            evidence = Counter()
            while stack:
                node = stack.pop()
                if node in tags:
                    evidence[tags[node]] += 1
                adjacent = graph[node] - visited
                stack.extend(adjacent)
                visited.update(adjacent)
            confirmed = {finger for finger, count in evidence.items() if count >= 3}
            if len(confirmed) > 1:
                raise RigidHandsRecommended('The hand mesh appears joined between fingers. Choose rigid hands for this model.', side=side)
            geometry_hits.update(confirmed)


def _deformation_target(bone, retained, hands, forearms):
    if bone.name in retained:
        return bone.name
    parent = _ancestor(bone, retained)
    if any(child.name in retained for child in bone.children_recursive):
        return parent
    if parent in hands:
        # Fingers and other compact hand descendants may move with the hand.
        hand = hands[parent]
        limit = max(hand.length * 4, forearms[parent].length * 1.2)
        if (bone.tail_local - hand.head_local).length <= limit:
            return parent
    return None


def _check_mesh(arm, mesh):
    modifiers = [modifier for modifier in mesh.modifiers if modifier.type == 'ARMATURE']
    if (len(modifiers) != 1 or modifiers[0].object != arm or not modifiers[0].use_vertex_groups
            or modifiers[0].use_bone_envelopes or modifiers[0].vertex_group):
        raise ValueError('Profiles require each mesh to follow one armature through its vertex weights.')
    if mesh.data.users > 1:
        raise ValueError('Profiles require an independent mesh for each skin. Duplicate shared mesh data before rigging.')


def _twist_specs(bones, body):
    specs = {}
    for side in _SIDES:
        forearm = bones[body[f'{side}_forearm']]
        hand = bones[body[f'{side}_hand']]
        head = forearm.head_local.copy()
        axis = hand.head_local - head
        if axis.length_squared < 1e-12:
            raise ValueError('The elbow and wrist coincide. Check the joint landmarks.')
        if len(forearm.name.encode('utf-8')) > 45:
            name = f'Studio_{side}_forearm_twist'
        else:
            name = f'{forearm.name}_StudioTwist'
        if name in bones:
            raise ValueError('The source armature already contains a Studio twist bone.')
        specs[side] = (name, forearm.name, head, axis)
    return specs


def _transfer_twist(weights, point, spec):
    name, forearm, start, axis = spec
    t = (point - start).dot(axis) / axis.length_squared
    factor = min(1.0, max(0.0, (t - 0.15) / 0.75))
    factor = factor * factor * (3.0 - 2.0 * factor)
    if factor <= 0.0:
        return
    redistributed = weights[forearm] * factor
    weights[name] = redistributed
    weights[forearm] -= redistributed


def _plan_mesh(arm, mesh, body, destinations, twist_specs, finger_regions, finger_hits, geometry_hits, body_donors):
    _check_mesh(arm, mesh)
    groups = {group.index: group.name for group in mesh.vertex_groups}
    bones = arm.data.bones
    deform = {bone.name for bone in bones if bone.use_deform}
    bone_groups = [name for name in groups.values() if name in bones]
    matrix = arm.matrix_world.inverted_safe() @ mesh.matrix_world
    finger_names = {name for chain, _, _ in finger_regions.values() for name in chain}
    if finger_regions:
        _distal_mesh(arm, mesh, matrix, body, finger_regions, geometry_hits)
    plan = []
    for vertex in mesh.data.vertices:
        weights = {}
        for entry in vertex.groups:
            name = groups[entry.group]
            if name not in deform:
                continue
            if not math.isfinite(entry.weight) or entry.weight < 0:
                raise ValueError('The source contains invalid skin weights.')
            if entry.weight <= 0:
                continue
            keep = destinations[name]
            if keep is None:
                raise ValueError(
                    f'The weighted bone {name} belongs to an unsupported branch. Use Auto to preserve it.'
                )
            weights[keep] = weights.get(keep, 0.0) + entry.weight
        for spec in twist_specs.values():
            if spec[1] in weights:
                _transfer_twist(weights, matrix @ vertex.co, spec)
        if body_donors:
            transfer_body_weights(weights, matrix @ vertex.co, body_donors)
        largest = sorted(
            ((name, weight) for name, weight in weights.items() if weight > 1e-8),
            key=lambda pair: (-pair[1], pair[0]),
        )[:4]
        total = sum(weight for _, weight in largest)
        if not math.isfinite(total) or total <= 0:
            raise ValueError('Every skinned vertex needs at least one usable bone weight. Check the source rig.')
        vertex_plan = tuple((name, weight / total) for name, weight in largest)
        if finger_names:
            finger_hits.update(name for name, weight in vertex_plan if name in finger_names and weight >= .12)
        plan.append(vertex_plan)
    return mesh, bone_groups, plan


def _edit_hierarchy(arm, retained, additional):
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        bones = arm.data.edit_bones
        parents = {name: _ancestor(bones[name], retained) for name in retained}
        for name, parent in parents.items():
            bone = bones[name]
            if (bone.parent.name if bone.parent else None) != parent:
                head, tail, roll = bone.head.copy(), bone.tail.copy(), bone.roll
                bone.use_connect = False
                bone.parent = bones.get(parent) if parent else None
                bone.head, bone.tail, bone.roll = head, tail, roll
        for bone in list(bones):
            if bone.name not in retained:
                bones.remove(bone)
        for name, parent, head, tail in additional:
            bone = bones.new(name)
            bone.head = head
            bone.tail = tail
            bone.parent = bones[parent]
            bone.use_connect = False
            bone.use_deform = True
    finally:
        bpy.ops.object.mode_set(mode='OBJECT')


def _apply_weights(arm, mesh, bone_groups, plan):
    for name in bone_groups:
        mesh.vertex_groups.remove(mesh.vertex_groups[name])
    used = {name for weights in plan for name, _ in weights}
    groups = {name: mesh.vertex_groups.new(name=name) for name in sorted(used)}
    for name in used:
        arm.data.bones[name].use_deform = True
    for index, weights in enumerate(plan):
        for name, weight in weights:
            groups[name].add([index], weight, 'REPLACE')


def validate_profile_mapping(arm, mapping, profile):
    """Check the persisted role map against a reimported profiled rig."""
    if profile not in _PROFILES or not isinstance(mapping, dict):
        raise ValueError('The stored rig profile mapping is invalid.')
    if any(not isinstance(name, str) or not name for name in mapping.values()):
        raise ValueError('The stored rig profile contains an invalid bone name.')
    body = _body_mapping(arm, mapping)
    bones = arm.data.bones
    expected = set(body)
    finger_roles = {
        f'{side}_finger_{finger}_{segment}'
        for side in _SIDES for finger in range(5) for segment in range(3)
    }
    has_fingers = bool(finger_roles & mapping.keys())
    if (profile == 'simple' and has_fingers) or (profile == 'standard' and not has_fingers):
        raise ValueError('The stored finger mapping is incompatible with this profile.')
    if has_fingers:
        expected.update(finger_roles)
    expressive = profile == 'expressive'
    if profile in _TWIST_PROFILES:
        expected.update(f'{side}_forearm_twist' for side in _SIDES)
    if profile in _BODY_HELPER_PROFILES:
        expected.update(EXPERT_HELPER_SOURCES)
    if expressive:
        expected.update(EXPRESSIVE_HELPER_SOURCES)
    if set(mapping) != expected or len(mapping) != len(bones) or set(mapping.values()) != {bone.name for bone in bones}:
        raise ValueError('The stored profile does not match the bones in this model.')
    for side in _SIDES:
        hand = bones[body[f'{side}_hand']]
        if has_fingers:
            for finger in range(5):
                parent = hand
                for segment in range(3):
                    bone = bones[mapping[f'{side}_finger_{finger}_{segment}']]
                    if bone.parent != parent:
                        raise ValueError('The stored profile contains an invalid finger hierarchy.')
                    parent = bone
        if profile in _TWIST_PROFILES:
            forearm = bones[body[f'{side}_forearm']]
            twist = bones[mapping[f'{side}_forearm_twist']]
            span = hand.head_local - forearm.head_local
            anchor = forearm.head_local + span * (EXPRESSIVE_TWIST_PROXIMAL if expressive else 0.5)
            if (twist.parent != forearm or span.length_squared < 1e-12
                    or (twist.head_local - anchor).length > span.length * 0.02):
                raise ValueError('The stored profile contains an invalid forearm twist joint.')
    if profile in _BODY_HELPER_PROFILES:
        for role, helper in expert_helpers(bones, body, expressive=expressive).items():
            bone = bones[mapping[role]]
            tolerance = (helper.tail - helper.head).length / 12.0
            if (bone.name != helper.name or bone.parent != bones[helper.parent]
                    or (bone.head_local - helper.head).length > tolerance):
                raise ValueError(f'The stored profile contains an invalid {profile.title()} body helper.')
    return dict(mapping)


def apply_profile(arm, meshes, mapping, profile, articulated_fingers):
    """Adapt a private, newly skinned humanoid while retaining its rest geometry."""
    if profile not in _PROFILES:
        raise ValueError('Unknown configurable rig profile.')
    if not meshes:
        raise ValueError('A rig profile needs a skinned humanoid mesh.')
    if arm.animation_data and (arm.animation_data.action or arm.animation_data.nla_tracks):
        raise ValueError('Create a new profile from an unanimated source mesh, then retarget its motions.')
    if type(articulated_fingers) is not bool:
        raise ValueError('The articulated fingers option must be boolean.')
    articulated = profile == 'standard' or (profile in _TWIST_PROFILES and articulated_fingers)
    expressive = profile == 'expressive'
    body = _body_mapping(arm, mapping)
    bones = arm.data.bones
    fingers = _finger_mapping(bones, body) if articulated else {}
    roles = {**body, **fingers}
    retained = set(roles.values())
    hands = {body[f'{side}_hand']: bones[body[f'{side}_hand']] for side in _SIDES}
    forearms = {body[f'{side}_hand']: bones[body[f'{side}_forearm']] for side in _SIDES}
    destinations = {bone.name: _deformation_target(bone, retained, hands, forearms) for bone in bones}
    twist_specs = _twist_specs(bones, body) if profile in _TWIST_PROFILES else {}
    if any(mesh.vertex_groups.get(spec[0]) for mesh in meshes for spec in twist_specs.values()):
        raise ValueError('A Studio twist bone name conflicts with a source vertex group.')
    helpers = expert_helpers(bones, body, expressive=expressive) if profile in _BODY_HELPER_PROFILES else {}
    body_helpers = {role: helper.name for role, helper in helpers.items()}
    if any(name in bones or any(mesh.vertex_groups.get(name) for mesh in meshes) for name in body_helpers.values()):
        raise ValueError(f'An {profile.title()} body helper name conflicts with a source bone or vertex group.')
    supported_helpers = {**helpers, **expressive_forearm_support(twist_specs)} if expressive else helpers
    body_donors = helpers_by_donor(supported_helpers)
    regions = _finger_regions(bones, fingers) if articulated else {}
    hits = set()
    geometry_hits = set()
    wrist_twist_specs = {} if expressive else twist_specs
    plans = [_plan_mesh(arm, mesh, body, destinations, wrist_twist_specs, regions, hits, geometry_hits, body_donors)
             for mesh in meshes]
    missing_regions = sorted(regions.keys() - geometry_hits)
    if missing_regions:
        raise RigidHandsRecommended('Five separate finger regions could not be confirmed in the mesh. Choose rigid hands for this model.',
                                    side=missing_regions[0][0])
    missing_weights = []
    for role, bone in fingers.items():
        if bone not in hits:
            side, _, finger, segment = role.split('_')
            missing_weights.append((side, int(finger), int(segment), bone))
    if missing_weights:
        raise RigidHandsRecommended('Each finger joint needs usable mesh weights. Choose rigid hands for this model.',
                                    joints=missing_weights)
    if supported_helpers:
        names = {helper.name for helper in supported_helpers.values()}
        weighted = {name for _, _, plan in plans for weights in plan for name, value in weights
                    if name in names and value >= 0.005}
        if names - weighted:
            missing = ', '.join(role for role, helper in supported_helpers.items() if helper.name not in weighted)
            fallback = 'Expert' if expressive else 'Advanced'
            raise ValueError(f'The mesh lacks local weights for {profile.title()} body helpers: {missing}. '
                             f'Choose {fallback} or check the landmarks.')
    additional = [(name, parent, head + axis * 0.5, head + axis * 0.9)
                  for name, parent, head, axis in wrist_twist_specs.values()]
    additional.extend((helper.name, helper.parent, helper.head, helper.tail) for helper in supported_helpers.values())
    _edit_hierarchy(arm, retained, additional)
    twists = {side: spec[0] for side, spec in twist_specs.items()}
    roles.update({f'{side}_forearm_twist': name for side, name in twists.items()})
    roles.update(body_helpers)
    for mesh, groups, weights in plans:
        _apply_weights(arm, mesh, groups, weights)
    bpy.context.view_layer.update()
    return validate_profile_mapping(arm, roles, profile), {
        'profile': profile,
        'articulated_fingers': bool(articulated),
        'joint_count': len(arm.data.bones),
        'max_influences': 4,
        'twists': twists,
        **({'body_helpers': body_helpers} if helpers else {}),
    }
