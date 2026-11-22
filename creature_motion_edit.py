"""CPU-only procedural clips for an existing, unchanged glTF skin.

This is a geometric motion preview, not an autorigger, learned motion model or
contact solver. Publication to the original model belongs to the host's staged
animation transaction, including its Blender companion and prepared LODs.
"""
from collections import defaultdict
import copy
import hashlib
import json
import math
from pathlib import Path
from unicodedata import category

import numpy as np
from scipy.spatial.transform import Rotation

from generated_motion import _write_atomic, append_access, gltf_rig, verify_preservation
from glb_data import accessor, read
from studio_import import animation_recipe


FPS = 30
UP = np.array([0., 1., 0.])
MOTIONS = {
    'test': ('Creature deformation', 'A small anchored deformation loop through the existing joint chains.'),
    'quadruped': ('Creature quadruped stride', 'A geometric four-leg stride preview without foot-contact locking.'),
    'serpentine': ('Creature serpentine wave', 'A length-weighted wave along one continuous articulated chain.'),
    'winged': ('Creature wing flap', 'A flap preview for two distinct lateral joint chains.'),
    'swim': ('Creature swim', 'A coordinated pulse and trailing wave for an upright bell-like radial rig.'),
}
DEFAULTS = dict(motion='test', duration_s=4., amplitude=1., cycles=2, phase_lag=.45, travel_m=0.)
LIMITS = dict(duration_s=[2., 12.], amplitude=[.1, 2.], cycles=[1, 4],
              phase_lag=[0., 1.2], travel_m=[0., .35])


def validate_creature_motion_recipe(value):
    if not isinstance(value, dict) or value.keys() - {*DEFAULTS, 'name'}:
        raise ValueError('Use the supported creature motion settings.')
    result = DEFAULTS | value
    if not isinstance(result['motion'], str) or result['motion'] not in MOTIONS:
        raise ValueError('Choose test, quadruped, serpentine, winged, or swim.')
    for key, (low, high) in LIMITS.items():
        number = result[key]
        if (type(number) not in (int, float) or not low <= number <= high
                or key == 'cycles' and type(number) is not int):
            raise ValueError(f'Creature {key} must be between {low:g} and {high:g}.')
        result[key] = int(number) if key == 'cycles' else float(number)
    if result['motion'] != 'swim' and (result['phase_lag'] != .45 or result['travel_m'] != 0):
        raise ValueError('Phase lag and vertical travel are available for swimming only.')
    if 'name' in result:
        name = result['name']
        if (not isinstance(name, str) or not name.strip() or len(name.strip()) > 80
                or any(category(char).startswith('C') for char in name)):
            raise ValueError('Use an animation name of 1 to 80 printable characters.')
        result['name'] = name.strip()
        if animation_recipe(result['name']):
            raise ValueError('TS_* names are reserved for the standard animation library.')
    return result


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _unit(vector):
    length = float(np.linalg.norm(vector))
    if not math.isfinite(length) or length < 1e-8:
        raise ValueError('The selected joint chain has coincident or invalid origins.')
    return np.asarray(vector) / length


class Rig:
    def __init__(self, data, binary):
        skins = data.get('skins', [])
        if len(skins) != 1:
            raise ValueError('Creature motion requires one existing skin.')
        self.joints = list(skins[0].get('joints', []))
        if (not 2 <= len(self.joints) <= 512 or len(set(self.joints)) != len(self.joints)
                or any(type(index) is not int or not 0 <= index < len(data['nodes']) for index in self.joints)):
            raise ValueError('Use a skin with 2 to 512 distinct valid joints.')
        self.parents, self.local, self.world, self.rest, self.order = gltf_rig(data)
        joint_set = set(self.joints)
        names = [data['nodes'][i].get('name') for i in self.joints]
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
            raise ValueError('The rig joints need distinct nonempty names.')
        self.names = dict(zip(self.joints, names))
        self.parent, self.children = {}, defaultdict(list)
        for index in self.joints:
            parent = self.parents.get(index)
            while parent is not None and parent not in joint_set:
                parent = self.parents.get(parent)
            self.parent[index] = parent
            self.children[parent].append(index)
        roots = self.children[None]
        if len(roots) != 1:
            raise ValueError('The skin needs one connected joint root.')
        self.root = roots[0]
        self.heads = {i: self.world[i][:3, 3] for i in self.joints}
        self.vectors = {}
        for index in self.joints:
            children = self.children[index]
            if children:
                child = max(children, key=lambda i: np.linalg.norm(self.heads[i] - self.heads[index]))
                vector = self.heads[child] - self.heads[index]
            else:
                parent = self.parent[index]
                vector = self.heads[index] - self.heads[parent]
            self.vectors[index] = vector
        points = np.array([self.heads[i] for i in self.joints] +
                          [self.heads[i] + self.vectors[i] for i in self.joints])
        self.low, self.high = points.min(axis=0), points.max(axis=0)
        self.size = self.high - self.low
        if max(self.size) < 1e-6:
            raise ValueError('The rig has no usable joint extent.')
        self.center = (self.low + self.high) * .5
        weighted = set()
        for mesh in data.get('meshes', []):
            for primitive in mesh.get('primitives', []):
                attrs = primitive.get('attributes', {})
                if 'JOINTS_0' not in attrs:
                    continue
                sets = sorted(key.split('_')[1] for key in attrs if key.startswith('JOINTS_'))
                total = None
                for number in sets:
                    if 'WEIGHTS_' + number not in attrs:
                        raise ValueError('The skin has incomplete joint/weight attributes.')
                    if data['accessors'][attrs['JOINTS_' + number]]['componentType'] not in (5121, 5123):
                        raise ValueError('The skin joint indices must use unsigned integers.')
                    indices = accessor(data, binary, attrs['JOINTS_' + number]).astype(int)
                    weights = accessor(data, binary, attrs['WEIGHTS_' + number])
                    if (indices.shape != weights.shape or indices.shape[1] != 4
                            or not np.isfinite(weights).all() or (weights < 0).any()
                            or (indices < 0).any() or (indices >= len(self.joints)).any()):
                        raise ValueError('The rig has invalid skin weights.')
                    total = weights.sum(axis=1) if total is None else total + weights.sum(axis=1)
                    weighted.update(indices[weights > 0].tolist())
                if total is None or not np.allclose(total, 1, atol=.002):
                    raise ValueError('The existing skin weights must be normalized.')
        if not weighted:
            raise ValueError('The model has no weighted skin surface.')
        self.weighted = {self.joints[i] for i in weighted}
        self.influential = set(self.weighted)
        for index in self.weighted:
            parent = self.parent[index]
            while parent is not None:
                self.influential.add(parent)
                parent = self.parent[parent]

    def chain(self, start, eligible=lambda _: True):
        pending, distance, following = [(start, False)], {}, {}
        while pending:
            index, visited = pending.pop()
            children = [child for child in self.children[index] if eligible(child)]
            if not visited:
                pending.append((index, True))
                pending.extend((child, False) for child in reversed(children))
                continue
            child = max(children, key=lambda i: distance[i], default=None)
            following[index] = child
            distance[index] = np.linalg.norm(self.vectors[index]) + (distance[child] if child is not None else 0)
        result, index = [], start
        while index is not None:
            result.append(index)
            index = following[index]
        return result


def _deformation(rig):
    motions, pending = {}, [(rig.root, 0, 0.)]
    while pending:
        index, depth, phase = pending.pop()
        if depth and np.linalg.norm(rig.vectors[index]) > 1e-8:
            direction = _unit(rig.vectors[index])
            reference = UP if abs(direction @ UP) < .9 else np.array([1., 0., 0.])
            motions[index] = (_unit(np.cross(direction, reference)), 18. / (1 + depth * .45), phase, False)
        pending.extend((child, depth + 1, phase + .12 + order * .17)
                       for order, child in enumerate(rig.children[index]))
    if not motions:
        raise ValueError('No articulated chain is available for a deformation loop.')
    return motions


def _quadruped(rig):
    def descends(index):
        vector = rig.vectors[index]
        return vector[1] < -max(.2 * np.linalg.norm(vector), .015 * rig.size[1])
    legs = []
    for index in rig.joints:
        parent = rig.parent[index]
        if parent is None or not descends(index) or parent != rig.root and descends(parent):
            continue
        chain = rig.chain(index, descends)
        end = rig.heads[chain[-1]] + rig.vectors[chain[-1]]
        if len(chain) >= 2 and end[1] <= rig.low[1] + .17 * rig.size[1] and rig.heads[index][1]-end[1] > .24 * rig.size[1]:
            legs.append(chain)
    if len(legs) != 4:
        raise ValueError('Four distinct downward supporting leg chains were not recognized.')
    heads = np.array([rig.heads[chain[0]] for chain in legs])[:, [0, 2]]
    pairs = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]
    ranked = sorted((sum(np.linalg.norm(heads[a]-heads[b]) for a, b in pairing), pairing) for pairing in pairs)
    if ranked[-1][0] <= 1.04 * ranked[-2][0]:
        raise ValueError('The four leg attachments do not form a clear diagonal pairing.')
    _, vectors = np.linalg.eigh(np.cov(heads.T))
    forward = np.array([vectors[0, -1], 0., vectors[1, -1]])
    axis = _unit(np.cross(UP, forward))
    motions = {}
    for pair_index, pair in enumerate(ranked[-1][1]):
        for index in pair:
            hip, knee = legs[index][:2]
            motions[hip] = (axis, 16., pair_index*.5, False)
            motions[knee] = (axis, -19., pair_index*.5+.16, True)
    return motions


def _serpentine(rig):
    if any(len(rig.children[i]) > 1 for i in rig.joints):
        raise ValueError('Serpentine motion requires one continuous, unbranched body chain.')
    chain = rig.chain(rig.root)[1:]
    if len(chain) < 4:
        raise ValueError('At least four articulated body joints are needed after the root.')
    lengths = [np.linalg.norm(rig.vectors[i]) for i in chain]
    total = sum(lengths)
    if total < .8 * max(rig.size):
        raise ValueError('The body chain does not span the rig.')
    horizontal = sum(np.linalg.norm(rig.vectors[i][[0, 2]]) for i in chain)
    axis = UP if horizontal > total*.5 else np.array([1., 0., 0.])
    motions, distance = {}, 0.
    for index, length in zip(chain, lengths):
        position = (distance + length*.5) / total
        motions[index] = (axis, min(17., 77.*length/total)*(.5+.5*position), -1.1*position, False)
        distance += length
    return motions


def _winged(rig):
    found = []
    for side in (-1, 1):
        def extends(index):
            vector = rig.vectors[index]
            return side*vector[0] > .4*np.linalg.norm(vector) and abs(vector[1]) <= .65*np.linalg.norm(vector)
        choices = []
        for index in rig.joints:
            parent = rig.parent[index]
            if parent is None or not extends(index) or parent != rig.root and extends(parent):
                continue
            head = rig.heads[index]
            if abs(head[0]-rig.center[0]) > .23*rig.size[0] or head[1] < rig.low[1]+.3*rig.size[1]:
                continue
            chain = rig.chain(index, extends)
            end = rig.heads[chain[-1]] + rig.vectors[chain[-1]]
            reach = side*(end[0]-head[0])
            if len(chain) >= 2 and reach > .19*rig.size[0]:
                choices.append((reach, chain))
        found.append(max(choices, default=(0., [])))
    (left_reach, left), (right_reach, right) = found
    if not left or not right or min(left_reach, right_reach) < .45*max(left_reach, right_reach):
        raise ValueError('Two sufficiently long, paired lateral chains were not recognized.')
    if abs(rig.heads[left[0]][1]-rig.heads[right[0]][1]) > .25*rig.size[1]:
        raise ValueError('The lateral chain attachments have incompatible heights.')
    motions, axis = {}, np.array([0., 0., 1.])
    for side, chain in ((-1, left), (1, right)):
        motions[chain[0]] = (axis, side*31., 0., False)
        for index in chain[1:]:
            motions[index] = (axis, side*18./(len(chain)-1), -.13, False)
    return motions


PLANNERS = dict(test=_deformation, quadruped=_quadruped, serpentine=_serpentine, winged=_winged)


def _swimmer(rig):
    hubs = [i for i in rig.joints if len(rig.children[i]) >= 3]
    if hubs != [rig.root] or len(rig.joints) < 7:
        raise ValueError('Swimming needs an upright radial rig with one branching body hub at its root.')
    hub = rig.root
    height = float(np.ptp(np.array(list(rig.heads.values()))[:, 1]))
    if height < 1e-5:
        raise ValueError('Orient the swimmer upright in Y-up coordinates before generating a clip.')
    upper, lower, rim, radial_chains = [], [], [], []
    for child in rig.children[hub]:
        chain = rig.chain(child)
        delta = rig.heads[child]-rig.heads[hub]
        radial = float(np.linalg.norm(delta[[0, 2]]))
        end = rig.heads[chain[-1]]
        if delta[1] > height*.12:
            upper.append(chain)
        elif len(chain) >= 2 and end[1] < rig.heads[hub][1]-height*.20:
            lower.append(chain)
            if len(chain) >= 3 and np.linalg.norm((rig.heads[chain[1]]-rig.heads[hub])[[0, 2]]) > height*.03:
                radial_chains.append(chain)
        elif len(chain) == 1 and radial > height*.035 and abs(delta[1]) < height*.20:
            rim.append(child)
    hybrid = bool(upper and len(lower) >= 2 and len(rim) >= 2)
    radial = len(radial_chains) >= 3 and not upper
    if not (hybrid or radial):
        raise ValueError('The rig lacks a distinguishable bell/upper support and independent trailing branches.')
    return dict(hub=hub, upper=upper, lower=lower, rim=rim, radial=radial,
                description='Geometric bell-up heuristic: one root hub, upper bell support and trailing branches; no mesh repair or new tentacle joints.',
                warnings=['Short branches have limited articulation; this clip cannot create joints or fix skin weights.'])


def _continuous(values):
    values = np.asarray(values, dtype=float)
    for index in range(1, len(values)):
        if values[index-1] @ values[index] < 0:
            values[index] *= -1
    values[-1] = values[0]
    if (not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-6)
            or np.any(np.sum(values[1:]*values[:-1], axis=1) < 0)):
        raise ValueError('The procedural rotation sequence is not finite and continuous.')
    return values.astype('<f4')


def _rotation(rig, index, axis, angle):
    local = rig.local[index][:3, :3]
    base = local / np.linalg.norm(local, axis=0)
    delta = Rotation.from_rotvec(angle[:, None] * (rig.rest[index].T @ _unit(axis))).as_matrix()
    return _continuous(Rotation.from_matrix(base @ delta).as_quat())


def _pulse(phase):
    p = phase % 1
    def smooth(value):
        value = np.clip(value, 0, 1)
        return value**3 * (10 + value*(-15+6*value))
    return np.where(p < .26, smooth(p/.26), 1-smooth((p-.26)/.55))


def _solve(rig, options):
    frames = round(options['duration_s']*FPS)
    computations = np.arange(frames+1, dtype=float)
    phase = (computations % frames) / frames
    times = np.linspace(0, options['duration_s'], frames+1, dtype='<f4')
    rotations, translations = {}, {}
    if options['motion'] != 'swim':
        for index, (axis, degrees, offset, lift) in PLANNERS[options['motion']](rig).items():
            wave = np.sin(math.tau*(phase*options['cycles']+offset))
            if lift:
                wave = np.maximum(0, wave)**2
            rotations[index] = _rotation(rig, index, axis, math.radians(degrees*options['amplitude'])*wave)
        return times, rotations, translations, {}

    topology = _swimmer(rig)
    hub = topology['hub']
    slow, pulse_phase = phase*math.tau, phase*options['cycles']
    contraction = _pulse(pulse_phase)
    amplitude = options['amplitude']
    drift = (Rotation.from_rotvec(np.outer(.035*amplitude*np.sin(slow), [1, 0, 0])).as_matrix()
             @ Rotation.from_rotvec(np.outer(.045*amplitude*(np.sin(slow+.5)-math.sin(.5)), [0, 0, 1])).as_matrix())
    parent = rig.parents.get(hub)
    parent_rest = rig.rest[parent] if parent is not None else np.eye(3)
    rotations[hub] = _continuous(Rotation.from_matrix(parent_rest.T @ drift @ rig.rest[hub]).as_quat())
    if options['travel_m']:
        travel = options['travel_m'] * np.column_stack([.12*np.sin(slow), .5*(1-np.cos(math.tau*pulse_phase)), .08*(np.cos(slow)-1)])
        linear = rig.world[parent][:3, :3] if parent is not None else np.eye(3)
        translations[hub] = (rig.local[hub][:3, 3] + travel @ np.linalg.inv(linear).T).astype('<f4')
        translations[hub][-1] = translations[hub][0]
    for index in topology['rim']:
        radial = rig.heads[index]-rig.heads[hub]
        radial[1] = 0
        rotations[index] = _rotation(rig, index, np.cross(UP, _unit(radial)), math.radians(12*amplitude)*contraction)
    longest = max(sum(np.linalg.norm(rig.vectors[i]) for i in chain) for chain in topology['lower'])
    for branch, chain in enumerate(topology['lower']):
        radial = rig.heads[chain[-1]]-rig.heads[hub]
        radial[1] = 0
        if np.linalg.norm(radial) < longest*.02:
            radial = np.array([math.cos(branch*math.tau/len(topology['lower'])), 0., math.sin(branch*math.tau/len(topology['lower']))])
        axis = np.cross(UP, _unit(radial))
        distance = 0.
        total = sum(np.linalg.norm(rig.vectors[i]) for i in chain)
        for step, index in enumerate(chain):
            length = np.linalg.norm(rig.vectors[index])
            along = (distance + length*.5)/max(longest, 1e-8)
            delay = along*options['phase_lag']*options['cycles']/options['duration_s']
            wave = np.sin(math.tau*(pulse_phase-delay)+branch*.55)
            freedom = (.25+.75*along)*min(1., math.sqrt(length/max(total, 1e-8))*2)
            angle = math.radians(14*amplitude)*freedom*wave
            if topology['radial'] and step == 0:
                angle = math.radians(12*amplitude)*contraction
            rotations[index] = _rotation(rig, index, axis, angle)
            distance += length
    return times, rotations, translations, dict(swim_topology=topology['description'],
        trailing_branches=len(topology['lower']), radial_short_branches=len(topology['rim']), warnings=topology['warnings'])


def _inspect(path):
    data, binary = read(path)
    if len(data.get('buffers', [])) != 1 or data['buffers'][0].get('uri') or not binary:
        raise ValueError('Creature motion requires a GLB with one embedded binary buffer.')
    rig = Rig(data, binary)
    return data, binary, rig


def creature_motion_capabilities(source):
    result = dict(available=False, reason='', motions=[], defaults=dict(DEFAULTS), limits=copy.deepcopy(LIMITS))
    try:
        data, binary, rig = _inspect(Path(source))
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, np.linalg.LinAlgError) as error:
        result['reason'] = str(error)
        return result
    except OSError:
        result['reason'] = 'The completed rig GLB is unavailable.'
        return result
    result.update(joint_count=len(rig.joints), source_sha256=_digest(source))
    for motion, (name, description) in MOTIONS.items():
        try:
            plan = _swimmer(rig) if motion == 'swim' else PLANNERS[motion](rig)
            animated = set(plan['rim']) | {plan['hub']} | {i for chain in plan['lower'] for i in chain} if motion == 'swim' else set(plan)
            if any('matrix' in data['nodes'][i] for i in animated):
                raise ValueError('Animated joints need translation/rotation/scale, not matrix transforms.')
            if not animated & rig.influential:
                raise ValueError('The selected chains have no skin influence.')
            reason = ''
        except ValueError as error:
            reason = str(error)
        result['motions'].append(dict(id=motion, name=name, description=description, available=not reason, reason=reason))
    result['available'] = any(item['available'] for item in result['motions'])
    if not result['available']:
        result['reason'] = 'No supported articulated motion was recognized on this rig.'
    return result


def write_creature_clip(source, destination, recipe):
    options = validate_creature_motion_recipe(recipe)
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError('Write the creature animation to a new staged GLB, preserving the source.')
    source_hash = _digest(source)
    before, oldbin, rig = _inspect(source)
    times, rotations, translations, details = _solve(rig, options)
    if any('matrix' in before['nodes'][index] for index in rotations.keys() | translations.keys()):
        raise ValueError('Animated joints need translation/rotation/scale, not matrix transforms.')
    if not rotations.keys() & rig.influential:
        raise ValueError('The selected chains have no skin influence.')
    existing = {clip.get('name') for clip in before.get('animations', [])}
    name = options.get('name') or MOTIONS[options['motion']][0]
    if 'name' in options and name in existing:
        raise ValueError('This animation name already exists on the model.')
    if 'name' not in options:
        base, count = name, 2
        while name in existing:
            name, count = f'{base} {count}', count+1
    data, binary = copy.deepcopy(before), bytearray(oldbin)
    time_index = append_access(data, binary, times, 'SCALAR')
    samplers, channels = [], []
    for path, tracks, kind in (('rotation', rotations, 'VEC4'), ('translation', translations, 'VEC3')):
        for index, values in tracks.items():
            value_index = append_access(data, binary, values, kind)
            samplers.append(dict(input=time_index, output=value_index, interpolation='LINEAR'))
            channels.append(dict(sampler=len(samplers)-1, target=dict(node=index, path=path)))
    saved_recipe = {**options, 'name': name}
    data.setdefault('animations', []).append(dict(name=name, samplers=samplers, channels=channels,
        extras={'trellis_creature_motion': dict(version=1, recipe=saved_recipe, effective_motion=options['motion'])}))
    data['buffers'][0]['byteLength'] = len(binary)
    preservation = verify_preservation(before, oldbin, data, binary)
    if _digest(source) != source_hash:
        raise ValueError('The source model changed while the creature clip was being prepared.')
    _write_atomic(destination, data, binary)
    final, saved_binary = read(destination)
    verify_preservation(before, oldbin, final, saved_binary)
    return dict(clip=name, duration_s=options['duration_s'], effective_motion=options['motion'],
        animated_bones=len(rotations), fps=FPS, frames=len(times), recipe=saved_recipe,
        root_motion='looped_vertical_drift' if translations else 'in_place',
        source_sha256=source_hash, output_sha256=_digest(destination),
        preservation=preservation, **details,
        limitations='Procedural preview: review deformation. Existing topology, weights and joint count are unchanged; no contact or collision correction.')
