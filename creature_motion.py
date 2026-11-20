"""Generate looped deformation previews for user-edited creature skeletons."""

from collections import defaultdict
from dataclasses import dataclass
import math

import bpy
from mathutils import Quaternion, Vector


CLIPS = {
    'test': ('creature_test', 'Creature · Deformation check', 2.0),
    'quadruped': ('creature_quadruped', 'Creature · Quadruped stride preview', 1.6),
    'serpentine': ('creature_serpentine', 'Creature · Serpentine undulation', 2.4),
    'winged': ('creature_winged', 'Creature · Wing flap preview', 2.0),
}
UP = Vector((0, 0, 1))


@dataclass(frozen=True)
class Rotation:
    axis: Vector
    degrees: float
    phase: float = 0.0
    lift_only: bool = False

    def at(self, phase, local_axis):
        wave = math.sin(math.tau * (phase + self.phase))
        if self.lift_only:
            wave = max(0.0, wave) ** 2
        return Quaternion(local_axis, math.radians(self.degrees * wave))


def blender_vector(point):
    x, y, z = point
    return Vector((x, -z, y))


class Skeleton:
    def __init__(self, bones):
        self.heads = {bone['name']: blender_vector(bone['head']) for bone in bones}
        self.tails = {bone['name']: blender_vector(bone['tail']) for bone in bones}
        self.parents = {bone['name']: bone['parent'] for bone in bones}
        self.children = defaultdict(list)
        for bone, parent in self.parents.items():
            self.children[parent].append(bone)
        self.vectors = {bone: self.tails[bone] - head for bone, head in self.heads.items()}
        all_points = [*self.heads.values(), *self.tails.values()]
        self.low = Vector(tuple(min(point[i] for point in all_points) for i in range(3)))
        self.high = Vector(tuple(max(point[i] for point in all_points) for i in range(3)))
        self.size = self.high - self.low
        self.center = (self.high + self.low) / 2

    def chain_length(self, chain):
        return sum(self.vectors[bone].length for bone in chain)

    def longest_chain(self, start, eligible):
        candidates = [
            self.longest_chain(child, eligible)
            for child in self.children[start] if eligible(child)
        ]
        return [start, *max(candidates, key=self.chain_length, default=[])]


def deformation_check(rig):
    motions = {}
    # Keep the root anchored. Limit cumulative bending even on very long chains.
    pending = [(root, 0, 0.0) for root in rig.children[None]]
    while pending:
        bone, depth, phase = pending.pop()
        if depth and rig.vectors[bone].length > 1e-6:
            direction = rig.vectors[bone].normalized()
            reference = UP if abs(direction.dot(UP)) < .9 else Vector((1, 0, 0))
            axis = direction.cross(reference).normalized()
            motions[bone] = Rotation(axis, 18.0 / (1 + depth * .45), phase)
        for index, child in enumerate(rig.children[bone]):
            pending.append((child, depth + 1, phase + .12 + index * .17))
    return motions


def horizontal_principal_axis(points):
    center = sum(points, Vector((0, 0, 0))) / len(points)
    deltas = [point - center for point in points]
    xx = sum(point.x ** 2 for point in deltas)
    yy = sum(point.y ** 2 for point in deltas)
    xy = sum(point.x * point.y for point in deltas)
    if math.hypot(xx - yy, 2 * xy) <= .05 * (xx + yy):
        return Vector((0, -1, 0))
    angle = .5 * math.atan2(2 * xy, xx - yy)
    return Vector((math.cos(angle), math.sin(angle), 0))


def quadruped(rig):
    if rig.size.z <= 1e-6:
        return {}

    def descends(bone):
        vector = rig.vectors[bone]
        return vector.z < -max(.2 * vector.length, .015 * rig.size.z)

    legs = []
    for bone, parent in rig.parents.items():
        if parent is None or not descends(bone) or descends(parent):
            continue
        chain = rig.longest_chain(bone, descends)
        end = rig.tails[chain[-1]]
        if (len(chain) >= 2 and end.z <= rig.low.z + .17 * rig.size.z
                and rig.heads[bone].z - end.z > .24 * rig.size.z):
            legs.append(chain)
    if len(legs) != 4:
        return {}

    hips = [rig.heads[chain[0]] for chain in legs]

    def planar_distance(i, j):
        delta = hips[i] - hips[j]
        return math.hypot(delta.x, delta.y)

    possible_pairs = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
    ranked = sorted((sum(planar_distance(*pair) for pair in pairs), pairs)
                    for pairs in possible_pairs)
    if ranked[-1][0] <= 1.04 * ranked[-2][0]:
        return {}
    axis = UP.cross(horizontal_principal_axis(hips))
    motions = {}
    for pair_index, pair in enumerate(ranked[-1][1]):
        phase = .5 * pair_index
        for index in pair:
            hip, knee, *_ = legs[index]
            motions[hip] = Rotation(axis, 16, phase)
            motions[knee] = Rotation(axis, -19, phase + .16, lift_only=True)
    return motions


def serpentine(rig):
    chains = [rig.longest_chain(root, lambda name: True) for root in rig.children[None]]
    chain = max(chains, key=rig.chain_length, default=[])[1:]
    total = rig.chain_length(chain)
    if (len(chain) < 4 or total <= 1e-6
            or total < .8 * max(rig.size.x, rig.size.y, rig.size.z)):
        return {}
    horizontal_length = sum(math.hypot(rig.vectors[bone].x, rig.vectors[bone].y)
                            for bone in chain)
    axis = UP if horizontal_length > total * .5 else Vector((1, 0, 0))
    motions = {}
    distance = 0.0
    for bone in chain:
        length = rig.vectors[bone].length
        if length > 1e-6:
            position = (distance + length * .5) / total
            # An angular gradient per unit arclength keeps added segments
            # from making the motion dramatically sharper.
            degrees = min(17.0, 77.0 * length / total) * (.5 + .5 * position)
            motions[bone] = Rotation(axis, degrees, -1.1 * position)
        distance += length
    return motions


def wing(rig, side):
    def extends(bone):
        v = rig.vectors[bone]
        return side * v.x > .40 * v.length and abs(v.z) <= .65 * v.length

    choices = []
    for bone, parent in rig.parents.items():
        if parent is None or not extends(bone) or extends(parent):
            continue
        head = rig.heads[bone]
        if (abs(head.x - rig.center.x) > .23 * rig.size.x
                or head.z < rig.low.z + .30 * rig.size.z):
            continue
        chain = rig.longest_chain(bone, extends)
        reach = side * (rig.tails[chain[-1]].x - head.x)
        if len(chain) >= 2 and reach > .19 * rig.size.x:
            choices.append((reach, chain))
    return max(choices, default=(0.0, []))


def winged(rig):
    left_reach, left = wing(rig, -1)
    right_reach, right = wing(rig, 1)
    if not left or not right or min(left_reach, right_reach) < .45 * max(left_reach, right_reach):
        return {}
    if abs(rig.heads[left[0]].z - rig.heads[right[0]].z) > .25 * rig.size.z:
        return {}
    motions = {}
    axis = Vector((0, 1, 0))
    for side, chain in ((-1, left), (1, right)):
        motions[chain[0]] = Rotation(axis, side * 31.0)
        for bone in chain[1:]:
            motions[bone] = Rotation(axis, side * 18.0 / (len(chain) - 1), -.13)
    return motions


SPECIALIZED = {
    'quadruped': (quadruped, 'The skeleton did not show four distinct supporting leg chains.'),
    'serpentine': (serpentine, 'The skeleton did not show a sufficiently long continuous body chain.'),
    'winged': (winged, 'The skeleton did not show two laterally extended wing chains in the rest pose.'),
}


def author_creature_motion(scene, armature, recipe):
    requested = recipe['motion']
    report = dict(requested=requested, applied='none', warning='', animated_bones=0)
    if requested == 'none':
        return [], report

    rig = Skeleton(recipe['bones'])
    motion = requested
    if motion == 'test':
        rotations = deformation_check(rig)
    else:
        configure, warning = SPECIALIZED[motion]
        rotations = configure(rig)
        if not rotations:
            report['warning'] = warning
            motion = 'test'
            rotations = deformation_check(rig)
    if not rotations:
        report['warning'] = (report['warning'] + ' No articulated chain was available for the deformation check.').strip()
        return [], report

    clip_id, clip_name, duration = CLIPS[motion]
    frames = round(duration * scene.render.fps / scene.render.fps_base)
    armature.animation_data_create()
    action = bpy.data.actions.new(clip_name)
    action.use_fake_user = True
    armature.animation_data.action = action
    pose_tracks = []
    for name, rotation in rotations.items():
        pose = armature.pose.bones.get(name)
        if pose is None:
            raise ValueError('The skinned skeleton is missing an edited creature bone.')
        pose.rotation_mode = 'QUATERNION'
        rest_orientation = (armature.matrix_world @ pose.bone.matrix_local).to_quaternion()
        axis = (rest_orientation.inverted() @ rotation.axis).normalized()
        pose_tracks.append((pose, rotation, axis))
    for frame in range(frames + 1):
        # Sampling the exact same phase at either end gives a seamless loop.
        phase = (frame % frames) / frames
        for pose, rotation, axis in pose_tracks:
            pose.rotation_quaternion = rotation.at(phase, axis)
            pose.keyframe_insert('rotation_quaternion', frame=frame, group=pose.name)
    scene.frame_end = max(scene.frame_end, frames)
    scene.frame_set(0)
    report.update(applied=motion, animated_bones=len(pose_tracks))
    return [dict(id=clip_id, name=clip_name, clip=action.name,
                 duration_s=frames * scene.render.fps_base / scene.render.fps,
                 source='TRELLIS Studio procedural creature motion')], report
