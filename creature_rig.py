"""Validate an edited creature armature in the model's glTF coordinate frame."""
from collections import defaultdict, deque
import math
import re
from unicodedata import category


MAX_CREATURE_BONES = 512
MAX_CREATURE_EDIT_BYTES = 1024 * 1024
CREATURE_MOTIONS = ('none', 'test', 'quadruped', 'serpentine', 'winged', 'swim')
REVISION = re.compile(r'[a-f0-9]{64}')


def is_creature_rig(settings):
    options = settings.get('rig_options')
    return isinstance(options, dict) and options.get('mode') == 'creature'


def bone_name(value):
    if (not isinstance(value, str) or not value or value.strip() != value
            or any(category(char).startswith('C') for char in value)
            or len(value.encode('utf-8')) > 63):
        raise ValueError('Use a nonempty bone name of up to 63 UTF-8 bytes without control characters.')
    return value


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError('A bone endpoint must have three model-space coordinates.')
    if any(type(coordinate) not in (int, float) for coordinate in value):
        raise ValueError('Bone endpoints must have finite model-space coordinates.')
    try:
        coordinates = [float(coordinate) for coordinate in value]
    except OverflowError as error:
        raise ValueError('Bone endpoints must have finite model-space coordinates.') from error
    if not all(map(math.isfinite, coordinates)):
        raise ValueError('Bone endpoints must have finite model-space coordinates.')
    return coordinates


def validate_creature_bones(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_CREATURE_BONES:
        raise ValueError(f'Provide between 1 and {MAX_CREATURE_BONES} creature bones.')
    by_name = {}
    children = defaultdict(list)
    for bone in value:
        if not isinstance(bone, dict) or set(bone) != {'name', 'parent', 'head', 'tail'}:
            raise ValueError('Each creature bone needs name, parent, head and tail.')
        name = bone_name(bone['name'])
        parent = None if bone['parent'] is None else bone_name(bone['parent'])
        if name in by_name:
            raise ValueError('Use a unique name for each bone.')
        head = point(bone['head'])
        tail = point(bone['tail'])
        if not 0 < math.dist(head, tail) < math.inf:
            raise ValueError(f'Bone {name} must have two distinct, finite endpoints.')
        by_name[name] = dict(name=name, parent=parent, head=head, tail=tail)
        children[parent].append(name)
    root = children[None]
    if len(root) != 1:
        raise ValueError('A creature rig needs exactly one root bone.')
    if any(parent is not None and parent not in by_name for parent in children):
        raise ValueError('Every parent must name a bone in the same creature rig.')
    pending = deque(root)
    ordered = []
    while pending:
        name = pending.popleft()
        ordered.append(by_name[name])
        pending.extend(children.get(name, ()))
    if len(ordered) != len(by_name):
        raise ValueError('The creature bone hierarchy must be connected and free of cycles.')
    return ordered


def validate_creature_edit(value):
    if not isinstance(value, dict) or set(value) - {'revision', 'bones', 'motion', 'swim'}:
        raise ValueError('Provide a preview revision, creature bones and an optional motion.')
    revision = value.get('revision')
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError('A creature draft preview revision is required.')
    motion = value.get('motion', 'test')
    if motion not in CREATURE_MOTIONS:
        raise ValueError('Choose none, test, quadruped, serpentine, winged, or swimming motion.')
    bones = validate_creature_bones(value.get('bones'))
    result = dict(revision=revision, bones=bones, motion=motion)
    if motion == 'swim':
        from creature_swim import validate_swim_options

        if bones[0]['name'] != 'racine' or not any(bone['name'].startswith('tentacule_') for bone in bones):
            raise ValueError('Adapt the tentacles on a creature draft to enable swimming.')
        result['swim'] = validate_swim_options(value.get('swim', {}))
    elif 'swim' in value:
        raise ValueError('Choose swimming motion before setting swim options.')
    return result
