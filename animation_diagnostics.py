"""Read-only checks of the final GLB tracks and sampled humanoid poses."""
from contextlib import contextmanager
import mmap
import struct

import numpy as np

from glb_data import accessor
from retarget_catalogue import BY_ID
from studio_import import animation_recipe, validate_glb


TRS = {'translation': 'VEC3', 'rotation': 'VEC4', 'scale': 'VEC3'}
SIDES = ('left', 'right')
MAX_SAMPLES = 1200


class UnavailableTrack(Exception):
    pass


def finding(code, message, severity, clip, **details):
    return dict(code=code, message=message, severity=severity, clip=clip, **details)


@contextmanager
def animation_buffer(path):
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as content:
        json_size = struct.unpack_from('<I', content, 12)[0]
        position = 20 + json_size
        if position + 8 > len(content):
            raise ValueError('The GLB animation data chunk is missing.')
        byte_length, kind = struct.unpack_from('<I4s', content, position)
        if kind != b'BIN\0' or position + 8 + byte_length > len(content):
            raise ValueError('The GLB animation data chunk is invalid.')
        with memoryview(content)[position + 8:position + 8 + byte_length] as binary:
            yield binary


def floats(data, binary, index, expected_type, limit, *, allow_normalized=False):
    if type(index) is not int or not 0 <= index < len(data['accessors']):
        raise ValueError('Invalid animation accessor index.')
    item = data['accessors'][index]
    if 'sparse' in item:
        raise UnavailableTrack
    component = item.get('componentType')
    floating_point = component == 5126 and not item.get('normalized')
    normalized_integer = (allow_normalized and item.get('normalized') is True
                          and component in (5120, 5121, 5122, 5123))
    if item.get('type') != expected_type or not (floating_point or normalized_integer):
        raise ValueError('Invalid animation accessor type.')
    component_size = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5126: 4}[component]
    size = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[expected_type] * component_size
    count = item['count']
    if type(count) is not int or count < 1:
        raise ValueError('An animation accessor has no keys.')
    if count > limit:
        raise UnavailableTrack
    view_index = item['bufferView']
    if type(view_index) is not int or not 0 <= view_index < len(data['bufferViews']):
        raise ValueError('Invalid animation buffer view index.')
    view = data['bufferViews'][view_index]
    if view['buffer'] != 0 or data['buffers'][0].get('uri'):
        raise UnavailableTrack
    offset, start = item.get('byteOffset', 0), view.get('byteOffset', 0)
    stride = view.get('byteStride', size)
    if (min(offset, start) < 0 or stride < size or stride % component_size or
            offset + (count - 1) * stride + size > view['byteLength'] or
            start + view['byteLength'] > len(binary)):
        raise ValueError('An animation accessor exceeds its buffer view.')
    result = accessor(data, binary, index).astype(float)
    if not np.isfinite(result).all():
        raise ValueError('The clip contains non-finite key values.')
    return result


def read_tracks(data, binary, clip):
    tracks = {}
    partial = False
    nodes = data.get('nodes', [])
    samplers = clip['samplers']
    if not clip['channels'] or not samplers:
        raise ValueError('The clip has no animation channels.')
    seen = set()
    errors = []
    inputs = {}
    for channel in clip['channels']:
        target = channel['target']
        path = target['path']
        if 'node' not in target or (path not in TRS and path != 'weights'):
            partial = True
            continue
        index = target['node']
        if type(index) is not int or not 0 <= index < len(nodes):
            errors.append((None, 'An animation channel references an invalid node.'))
            continue
        bone = nodes[index].get('name', str(index))
        try:
            if (index, path) in seen or (path in TRS and 'matrix' in nodes[index]):
                raise ValueError('An animation has conflicting transform channels.')
            seen.add((index, path))
            sampler_index = channel['sampler']
            if type(sampler_index) is not int or not 0 <= sampler_index < len(samplers):
                raise ValueError('Invalid animation sampler index.')
            sampler = samplers[sampler_index]
            mode = sampler.get('interpolation', 'LINEAR')
            if mode not in ('LINEAR', 'STEP', 'CUBICSPLINE'):
                raise ValueError('Invalid animation interpolation mode.')
            input_index = sampler['input']
            if input_index not in inputs:
                inputs[input_index] = floats(data, binary, input_index, 'SCALAR', 12000).ravel()
            keys = inputs[input_index]
            if keys[0] < 0 or np.any(np.diff(keys) <= 0):
                raise ValueError('Animation key times must be ordered and non-negative.')
            factor = 3 if mode == 'CUBICSPLINE' else 1
            value_type = TRS.get(path, 'SCALAR')
            values = floats(data, binary, sampler['output'], value_type, 36000,
                            allow_normalized=path in ('rotation', 'weights'))
            if path == 'weights':
                primitives = data['meshes'][nodes[index]['mesh']]['primitives']
                morphs = len(primitives[0].get('targets', []))
                if not morphs or any(len(primitive.get('targets', [])) != morphs for primitive in primitives):
                    raise ValueError('The animation targets a mesh without matching morph targets.')
                factor *= morphs
            if len(values) != len(keys) * factor or (mode == 'CUBICSPLINE' and len(keys) < 2):
                raise ValueError('The number of animation key values does not match the times.')
            if path == 'rotation':
                rotations = values[1::3] if factor == 3 else values
                norms = np.linalg.norm(rotations, axis=1)
                if np.any(norms < 1e-6):
                    raise ValueError('The clip contains a zero-length quaternion.')
            tracks[index, path] = keys, values, mode
        except UnavailableTrack:
            partial = True
        except (IndexError, KeyError, TypeError, ValueError) as error:
            errors.append((bone, str(error)))
    return tracks, partial, errors


def normalized(rows):
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    if np.any(norms < 1e-8):
        raise ValueError('A sampled rotation has zero length.')
    return rows / norms


def interpolate(track, path, samples):
    keys, values, mode = track
    if len(keys) == 1:
        return np.broadcast_to(values[0], (len(samples), values.shape[1]))
    times = np.clip(samples, keys[0], keys[-1])
    lower = np.searchsorted(keys, times, side='right') - 1
    if mode == 'STEP':
        return values[lower]
    lower = np.minimum(lower, len(keys) - 2)
    upper = lower + 1
    duration = (keys[upper] - keys[lower])[:, None]
    u = (times - keys[lower])[:, None] / duration
    if mode == 'CUBICSPLINE':
        a, b = values[3 * lower + 1], values[3 * upper + 1]
        result = ((2 * u**3 - 3 * u**2 + 1) * a + (-2 * u**3 + 3 * u**2) * b
                  + (u**3 - 2 * u**2 + u) * duration * values[3 * lower + 2]
                  + (u**3 - u**2) * duration * values[3 * upper])
        return normalized(result) if path == 'rotation' else result
    if path != 'rotation':
        return (1 - u) * values[lower] + u * values[upper]
    a, b = normalized(values[lower]), normalized(values[upper])
    dot = (a * b).sum(axis=1, keepdims=True)
    b = np.where(dot < 0, -b, b)
    theta = np.arccos(np.clip(np.abs(dot), 0, 1))
    sine = np.sin(theta)
    aligned = (np.sin((1-u) * theta) * a + np.sin(u * theta) * b) / np.maximum(sine, 1e-8)
    return normalized(np.where(sine > 1e-6, aligned, (1-u) * a + u * b))


def angles(a, b):
    dot = np.abs((a * b).sum(axis=1))
    return np.degrees(2 * np.arccos(np.clip(dot, 0, 1)))


def rotation_findings(nodes, tracks, clip, issues):
    for (index, path), (keys, values, mode) in tracks.items():
        if path != 'rotation' or len(keys) < 2 or mode == 'STEP':
            continue
        rotations = normalized(values[1::3] if mode == 'CUBICSPLINE' else values)
        adjacent = angles(rotations[:-1], rotations[1:])
        chord = angles(rotations[:-2], rotations[2:])
        # An isolated flip reverses a large rotation within two adjacent keys.
        # This avoids treating a fast but consistently authored spin as an error.
        spikes = np.flatnonzero((np.minimum(adjacent[:-1], adjacent[1:]) > 60) &
                                (keys[2:] - keys[:-2] < .15) & (chord < 35)) + 1
        for at in spikes[:4]:
            issues.append(finding('animation_rotation_jump',
                                  '{clip} · {bone} · {time} s: abrupt rotation ({degrees}°).',
                                  'warning', clip, bone=nodes[index].get('name', str(index)),
                                  time_s=float(keys[at]), degrees=round(float(adjacent[at - 1]), 1)))
        if mode == 'CUBICSPLINE':
            quarters = keys[:-1, None] + np.diff(keys)[:, None] * np.array([.25, .5, .75])
            samples = interpolate((keys, values, mode), path, quarters.ravel())
            start = np.repeat(rotations[:-1], 3, axis=0)
            end = np.repeat(rotations[1:], 3, axis=0)
            overshoot = np.minimum(angles(start, samples), angles(end, samples))
            indices = np.flatnonzero((overshoot > 60) & (np.repeat(adjacent, 3) < 35) &
                                     (np.repeat(np.diff(keys), 3) < .15))
            if len(indices):
                at = int(indices[0])
                issues.append(finding('animation_rotation_jump',
                                      '{clip} · {bone} · {time} s: abrupt rotation ({degrees}°).',
                                      'warning', clip, bone=nodes[index].get('name', str(index)),
                                      time_s=float(quarters.ravel()[at]), degrees=round(float(overshoot[at]), 1)))


def world_positions(nodes, tracks, indices, samples, offsets=None):
    parents = {child: parent for parent, node in enumerate(nodes) for child in node.get('children', [])}
    cache = {}

    def local(index, path, default):
        track = tracks.get((index, path))
        if track is not None:
            return interpolate(track, path, samples)
        return np.broadcast_to(nodes[index].get(path, default), (len(samples), len(default)))

    def world(index, visiting=()):
        if index in visiting:
            raise ValueError('The animation skeleton contains a cycle.')
        if index not in cache:
            node = nodes[index]
            if 'matrix' in node:
                transform = np.asarray(node['matrix']).reshape(4, 4).T
            else:
                x, y, z, w = local(index, 'rotation', [0, 0, 0, 1]).T
                transform = np.broadcast_to(np.eye(4), (len(samples), 4, 4)).copy()
                transform[:, :3, :3] = np.array([
                    [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                    [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                    [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]
                ]).transpose(2, 0, 1) * local(index, 'scale', [1, 1, 1])[:, None, :]
                transform[:, :3, 3] = local(index, 'translation', [0, 0, 0])
            if index in parents:
                transform = world(parents[index], (*visiting, index)) @ transform
            cache[index] = np.broadcast_to(transform, (len(samples), 4, 4))
        return cache[index]

    points = {}
    for role,index in indices.items():
        m = world(index)
        points[role] = m[:,:3,3]
        if offsets and role in offsets:
            points[role] = points[role] + m[:,:3,:3] @ np.asarray(offsets[role])
    return points


def pose_findings(nodes, tracks, clip, mapping, rate, issues):
    recipe = animation_recipe(clip)
    if not tracks or not recipe or not mapping:
        return {}
    known = BY_ID.get(recipe['id'], {})
    if recipe['id'] != 'crouch' and not known.get('loop'):
        return {}
    end = max(key[-1] for key, _, _ in tracks.values())
    keys = np.unique(np.concatenate(list({id(keys): keys for keys, _, _ in tracks.values()}.values())))
    if len(keys) <= MAX_SAMPLES:
        count = min(int(np.ceil(end * rate)) + 1, MAX_SAMPLES - len(keys))
        samples = np.union1d(keys, np.linspace(0, end, count))
    else:
        samples = np.union1d(np.linspace(0, end, MAX_SAMPLES), np.array([0., end]))
    by_name = {node.get('name'): index for index, node in enumerate(nodes)}
    wanted = ('leg', 'shin', 'foot', 'toe')
    indices = {role: by_name[mapping[role]] for side in SIDES for joint in wanted
               if (role := side + '_' + joint) in mapping and mapping[role] in by_name}
    if mapping.get('root') in by_name:
        indices['root'] = by_name[mapping['root']]
    points = world_positions(nodes, tracks, indices, samples)
    result = dict(samples=len(samples))
    travel = np.zeros(3)
    if 'root' in points:
        travel = points['root'][-1] - points['root'][0]
        travel[1] = 0
    for side in SIDES:
        for joint in ('foot', 'toe'):
            role = side + '_' + joint
            if role not in points:
                continue
            location = points[role]
            if recipe['id'] == 'crouch':
                distance = np.linalg.norm(location - location[0], axis=1)
                index = int(distance.argmax())
                result[role + '_drift_m'] = round(float(distance[index]), 6)
                if distance[index] > .035:
                    issues.append(finding('animation_foot_drift',
                                          '{clip} · {bone} · {time} s: foot moved {distance} cm during the crouch.',
                                          'warning', clip, bone=mapping[role], time_s=float(samples[index]),
                                          distance_cm=round(float(distance[index] * 100), 1)))
            else:
                distance = float(np.linalg.norm(location[-1] - location[0] - travel))
                result[role + '_seam_m'] = round(distance, 6)
                if distance > .06:
                    issues.append(finding('animation_loop_seam',
                                          '{clip} · {bone} · {time} s: foot moved {distance} cm across the loop.',
                                          'warning', clip, bone=mapping[role], time_s=float(samples[-1]),
                                          distance_cm=round(distance * 100, 1)))
    return result


def require_valid_animation(path, *, clips, mapping=None):
    """Jobs report a translatable error and retain the reason in their private log."""
    try:
        return inspect_animation(path, clips=clips, mapping=mapping, strict=True)
    except ValueError as error:
        raise ValueError('The final animation file contains an invalid track. See the generation log for details.') from error


def inspect_animation(path, *, clips=None, mapping=None, strict=False, rate=48):
    """Check selected output clips without copying large embedded textures or skinning every vertex."""
    data = validate_glb(path)
    selected = [(index, item) for index, item in enumerate(data.get('animations', []))
                if clips is None or item.get('name') in clips]
    issues = []
    measurements = []
    if strict and clips is not None and clips != {item.get('name') for _, item in selected}:
        raise ValueError('An expected animation clip is missing from the GLB.')
    if not selected:
        return dict(issues=issues, clips=measurements)
    with animation_buffer(path) as binary:
        for index, item in selected:
            clip = item.get('name', f'Animation {index + 1}')
            try:
                tracks, partial, errors = read_tracks(data, binary, item)
                rotation_findings(data.get('nodes', []), tracks, clip, issues)
                details = pose_findings(data.get('nodes', []), tracks, clip, mapping, rate, issues)
                measurements.append(dict(clip=clip, checked_tracks=len(tracks), **details))
            except (IndexError, KeyError, TypeError, ValueError, RecursionError) as error:
                partial, errors = False, [(None, str(error))]
            if partial:
                issues.append(finding('animation_partial_scan', '{clip}: some animation channels could not be measured.',
                                      'info', clip))
            for bone, reason in errors:
                if strict:
                    raise ValueError(f'{clip} · {bone or "animation"}: {reason}')
                issues.append(finding('animation_invalid_track', '{clip} · {bone}: invalid animation track.',
                                      'error', clip, bone=bone or '—', detail=reason))
    return dict(issues=issues, clips=measurements)
