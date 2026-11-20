"""Author a loop on a TRELLIS jellyfish rig without opening Blender."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from scipy.spatial.transform import Rotation

from generated_motion import _write_atomic, append_access, gltf_rig
from glb_data import read


SWIM_CLIP_NAME = 'Méduse · Nage'
SWIM_DEFAULTS = {
    'duration_s': 5.2,
    'pulses': 2,
    'bell_amplitude': 16.0,
    'tentacle_amplitude': 12.0,
    'phase_lag': .45,
    'body_travel_m': .17,
}
SWIM_LIMITS = {
    'duration_s': (2, 12),
    'pulses': (1, 4),
    'bell_amplitude': (0, 26),
    'tentacle_amplitude': (0, 22),
    'phase_lag': (0, 1.2),
    'body_travel_m': (0, .35),
}
FPS = 30
SWIM_VERSION = 1
SWIM_EXTRA = 'trellis_swim'
INCOMPATIBLE = 'Adapt the tentacles on a creature rig before adding jellyfish swim.'
TENTACLE = re.compile(r'tentacule_(\d{2,3})_(\d{2,3})')
UP = np.array([0.0, 1.0, 0.0])


def validate_swim_options(value=None):
    """Normalize a partial set of control values, using degrees and metres."""
    if value is None:
        value = {}
    if not isinstance(value, dict) or value.keys() - SWIM_DEFAULTS.keys():
        raise ValueError('Use the supported jellyfish swim settings.')
    settings = SWIM_DEFAULTS | value
    for key, (low, high) in SWIM_LIMITS.items():
        setting = settings[key]
        if (type(setting) not in (int, float) or not low <= setting <= high
                or (key == 'pulses' and type(setting) is not int)):
            raise ValueError(f'Swim {key} must be between {low} and {high}.')
        if key != 'pulses':
            settings[key] = float(setting)
    return settings


def managed_swim(clip):
    extras = clip.get('extras')
    metadata = extras.get(SWIM_EXTRA) if isinstance(extras, dict) else None
    return metadata if isinstance(metadata, dict) and metadata.get('version') == SWIM_VERSION else None


def swim_options(data):
    for clip in data.get('animations', []):
        if metadata := managed_swim(clip):
            try:
                return validate_swim_options(metadata.get('options'))
            except ValueError:
                break
    return dict(SWIM_DEFAULTS)


def swim_rig(data):
    """Resolve radial bell bones and consecutive tentacle segments from a GLB."""
    skins = data.get('skins', [])
    nodes = data.get('nodes', [])
    if not skins:
        raise ValueError(INCOMPATIBLE)
    joints = set(skins[0].get('joints', []))
    if (not joints or len(joints) > 512 or any(set(skin.get('joints', [])) != joints for skin in skins)
            or any(type(index) is not int or not 0 <= index < len(nodes) for index in joints)):
        raise ValueError('Jellyfish swim requires a single shared creature skeleton.')
    names = {nodes[index].get('name'): index for index in joints}
    if len(names) != len(joints) or 'racine' not in names:
        raise ValueError(INCOMPATIBLE)
    segments = {}
    for name, index in names.items():
        if isinstance(name, str) and (match := TENTACLE.fullmatch(name)):
            branch, step = map(int, match.groups())
            numbered = segments.setdefault(branch, {})
            if step in numbered:
                raise ValueError(INCOMPATIBLE)
            numbered[step] = index
    if len(segments) < 2:
        raise ValueError(INCOMPATIBLE)

    parents, local, world, rest_rotation, _ = gltf_rig(data)
    root = names['racine']
    if parents.get(root) in joints:
        raise ValueError(INCOMPATIBLE)
    chains = {}
    rays = {}
    animated = {root}
    for branch, numbered in sorted(segments.items()):
        bell = names.get(f'ombrelle_{branch:02d}')
        if bell is None or parents.get(bell) != root or set(numbered) != set(range(1, len(numbered) + 1)):
            raise ValueError(INCOMPATIBLE)
        ordered = [numbered[step] for step in range(1, len(numbered) + 1)]
        if any(parents.get(index) != parent for index, parent in zip(ordered, [bell, *ordered[:-1]])):
            raise ValueError(INCOMPATIBLE)
        ray = world[ordered[0]][:3, 3] - world[root][:3, 3]
        ray -= UP * np.dot(ray, UP)
        radius = float(np.linalg.norm(ray))
        if radius < 1e-6:
            raise ValueError('The bell needs a radial attachment point for each tentacle.')
        rays[branch] = (ray / radius, radius)
        chains[branch] = (bell, ordered)
        animated.update([bell, *ordered])
    if any('matrix' in nodes[index] for index in animated):
        raise ValueError('Swim needs glTF translation, rotation and scale on the animated bones.')
    return root, chains, rays, parents, local, world, rest_rotation


def swim_compatible(data):
    try:
        swim_rig(data)
    except (ValueError, TypeError, KeyError, IndexError, np.linalg.LinAlgError):
        return False
    return True


def smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x**3 * (10.0 + x * (-15.0 + 6.0 * x))


def pulse(phase):
    phase = phase % 1.0
    return np.where(phase < .26, smooth(phase / .26), 1.0 - smooth((phase - .26) / .55))


def axis_rotation(axis, radians):
    return Rotation.from_rotvec(radians[:, None] * axis).as_matrix()


def closed(values):
    values[-1] = values[0]
    return values


def local_quaternions(parent_orientation, desired_orientation):
    local = np.swapaxes(parent_orientation, -1, -2) @ desired_orientation
    result = Rotation.from_matrix(local).as_quat()
    for frame in range(1, len(result)):
        if np.dot(result[frame - 1], result[frame]) < 0:
            result[frame] *= -1
    return closed(result)


def chain_distances(joints, world, radius):
    heads = np.asarray([world[index][:3, 3] for index in joints])
    segments = np.linalg.norm(np.diff(heads, axis=0), axis=1)
    # glTF stores joint origins, so the leaf's tail has no separate transform.
    # Estimate its length from the preceding chord at the tip of the chain.
    last = segments[-1] if len(segments) else radius * .35
    lengths = np.r_[segments, last]
    if (lengths <= 1e-7).any():
        raise ValueError('Tentacle joints must be spaced along their chain.')
    return np.cumsum(lengths) - .5 * lengths


def solve_swim(data, options):
    root, chains, rays, parents, local, world, rest = swim_rig(data)
    duration = options['duration_s']
    frames = round(duration * FPS)
    times = np.linspace(0.0, duration, frames + 1)
    progress = (np.arange(frames + 1) % frames) / frames
    phase = progress * options['pulses']
    slow = progress * math.tau
    moving = min(1.0, (options['bell_amplitude'] / 16 + options['tentacle_amplitude'] / 12
                       + options['body_travel_m'] / .17) / 3)
    drift = (axis_rotation(UP, moving * .10 * np.sin(slow + .31))
             @ axis_rotation([0., 0., 1.], moving * .08 * np.sin(slow - .48))
             @ axis_rotation([1., 0., 0.], moving * .07 * np.cos(slow + .16)))
    root_orientation = drift @ rest[root]
    parent = parents.get(root)
    root_parent = rest[parent] if parent is not None else np.eye(3)
    parent_transform = world[parent][:3, :3] if parent is not None else np.eye(3)
    rotations = {root: local_quaternions(root_parent, root_orientation)}
    transfer = options['body_travel_m']
    rise = np.sin(math.tau * phase - .71) + .24 * np.sin(2 * math.tau * phase - .91)
    rise = (rise - rise.min()) / np.ptp(rise)
    sway = transfer * np.column_stack([.27 * np.sin(slow), rise, .13 * (np.cos(slow) - 1)])
    translations = {root: closed(local[root][:3, 3] + sway @ np.linalg.inv(parent_transform).T)}
    travel = {branch: chain_distances(joints, world, rays[branch][1])
              for branch, (_, joints) in chains.items()}
    longest = max(distance[-1] for distance in travel.values())
    root_scale = np.linalg.norm(world[root][:3, 0])
    bell_amplitude = math.radians(options['bell_amplitude'])
    wave_amplitude = math.radians(options['tentacle_amplitude'])

    for branch, (bell, joints) in chains.items():
        radial, radius = rays[branch]
        tangent = np.cross(UP, radial)
        angle = math.atan2(radial[2], radial[0])
        bias = .023 * np.sin(slow + angle)
        contraction = pulse(phase + bias)
        bell_rotation = axis_rotation(tangent, bell_amplitude * contraction)
        body_and_bell = drift @ bell_rotation
        desired_bell = body_and_bell @ rest[bell]
        rotations[bell] = local_quaternions(root_orientation, desired_bell)
        inward = -.075 * (options['bell_amplitude'] / 16) * radius * contraction[:, None] * radial
        # Drift acts on both the attachment motion and root frame, and cancels
        # when converting the inward bell motion to the posed parent's space.
        translations[bell] = closed(local[bell][:3, 3] + inward @ rest[root] / root_scale)
        orientation = desired_bell
        for index, distance in zip(joints, travel[branch]):
            along = distance / longest
            delay = along * options['phase_lag'] * options['pulses'] / duration
            shifted = phase - delay + bias
            freedom = smooth(along / .73)
            bend = wave_amplitude * freedom * (
                .72 * np.sin(math.tau * shifted + .42 * math.cos(angle))
                + .28 * (pulse(shifted) - contraction)
            )
            lateral = .78 * wave_amplitude * freedom * np.sin(slow - 2.6 * along + .57 * math.sin(angle))
            wave = axis_rotation(tangent, bend) @ axis_rotation(radial, lateral)
            desired = body_and_bell @ wave @ rest[index]
            rotations[index] = local_quaternions(orientation, desired)
            orientation = desired
    return times, rotations, translations


def signature(data):
    packed = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(packed).hexdigest()


def remove_previous_swim(data, binary):
    """Replace the managed clip, reclaiming its terminal payload when untouched."""
    clips = data.get('animations', [])
    matches = [index for index, clip in enumerate(clips)
               if clip.get('name') == SWIM_CLIP_NAME or managed_swim(clip) is not None]
    if len(matches) > 1:
        raise ValueError('The model contains several jellyfish swim clips with the same name.')
    if not matches:
        return data, binary, len(clips)
    index = matches[0]
    clip = clips.pop(index)
    if not clips:
        data.pop('animations')
    metadata = managed_swim(clip)
    payload = metadata.get('payload') if metadata else None
    if isinstance(payload, dict):
        starts = [payload.get(key) for key in ('accessors', 'bufferViews', 'bytes')]
        extents = [len(data['accessors']), len(data['bufferViews']), len(binary)]
        if all(type(start) is int and 0 <= start < end for start, end in zip(starts, extents)):
            original = copy.deepcopy(data)
            original['accessors'] = original['accessors'][:starts[0]]
            original['bufferViews'] = original['bufferViews'][:starts[1]]
            original['buffers'][0]['byteLength'] = starts[2]
            if signature(original) == payload.get('signature'):
                return original, binary[:starts[2]], index
    return data, binary, index


def write_swim(source_path, destination_path, options=None):
    """Atomically add or update only the generated jellyfish swim animation."""
    options = validate_swim_options(options)
    source = Path(source_path)
    before = source.stat()
    data, binary = read(source)
    if not binary or len(data.get('buffers', [])) != 1 or data['buffers'][0].get('uri'):
        raise ValueError('Jellyfish swim requires one embedded GLB buffer.')
    times, rotations, translations = solve_swim(data, options)
    data, binary, index = remove_previous_swim(data, binary)
    data['buffers'][0]['byteLength'] = len(binary)
    payload = {'accessors': len(data['accessors']), 'bufferViews': len(data['bufferViews']),
               'bytes': len(binary), 'signature': signature(data)}
    binary = bytearray(binary)
    samplers = []
    channels = []
    time_index = append_access(data, binary, times, 'SCALAR')
    for path, tracks, kind in (('rotation', rotations, 'VEC4'), ('translation', translations, 'VEC3')):
        for node, values in tracks.items():
            output = append_access(data, binary, values, kind)
            channels.append({'sampler': len(samplers), 'target': {'node': node, 'path': path}})
            samplers.append({'input': time_index, 'output': output, 'interpolation': 'LINEAR'})
    clip = {'name': SWIM_CLIP_NAME, 'samplers': samplers, 'channels': channels,
            'extras': {SWIM_EXTRA: {'version': SWIM_VERSION, 'options': options, 'payload': payload}}}
    data.setdefault('animations', []).insert(index, clip)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('The model changed while the swim animation was being prepared.')
    _write_atomic(destination_path, data, binary)
    return {'clip': SWIM_CLIP_NAME, 'duration_s': options['duration_s'], 'fps': FPS,
            'bones': len(rotations), 'options': options}
