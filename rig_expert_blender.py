"""Rest placement and localized skin weights for Expert and Expressive body helpers."""

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mathutils import Vector


EXPRESSIVE_TWIST_PROXIMAL = 1.0 / 3.0
EXPRESSIVE_TWIST_DISTAL = 2.0 / 3.0

EXPERT_HELPER_SOURCES = {
    'lumbar_corrective': ('root', 'spine_1', 'swing'),
    'mid_spine_corrective': ('spine_1', 'spine_2', 'swing'),
    'chest_corrective': ('spine_2', 'spine', 'swing'),
    'neck_base_corrective': ('spine', 'neck', 'swing'),
    'neck_top_corrective': ('neck', 'head', 'swing'),
}
EXPRESSIVE_HELPER_SOURCES = {}
for side in ('left', 'right'):
    EXPERT_HELPER_SOURCES.update({
        f'{side}_hip_corrective': ('root', f'{side}_leg', 'swing'),
        f'{side}_thigh_twist': (f'{side}_leg', f'{side}_shin', 'twist'),
        f'{side}_knee_corrective': (f'{side}_leg', f'{side}_shin', 'swing'),
        f'{side}_shin_twist': (f'{side}_shin', f'{side}_foot', 'twist'),
        f'{side}_ankle_corrective': (f'{side}_shin', f'{side}_foot', 'swing'),
        f'{side}_toe_corrective': (f'{side}_foot', f'{side}_toe', 'swing'),
        f'{side}_shoulder_corrective': (f'{side}_clavicle', f'{side}_arm', 'swing'),
        f'{side}_upper_arm_twist': (f'{side}_arm', f'{side}_forearm', 'twist'),
        f'{side}_elbow_corrective': (f'{side}_arm', f'{side}_forearm', 'swing'),
        f'{side}_wrist_corrective': (f'{side}_forearm', f'{side}_hand', 'swing'),
    })
    EXPRESSIVE_HELPER_SOURCES.update({
        f'{side}_expressive_scapula': (f'{side}_clavicle', f'{side}_arm', 'swing'),
        f'{side}_expressive_thorax': ('spine_2', 'spine', 'swing'),
        f'{side}_expressive_hip': ('root', f'{side}_leg', 'swing'),
        f'{side}_expressive_upper_arm_twist': (f'{side}_arm', f'{side}_forearm', 'twist'),
        f'{side}_expressive_forearm_twist': (f'{side}_forearm', f'{side}_hand', 'twist'),
        f'{side}_expressive_thigh_twist': (f'{side}_leg', f'{side}_shin', 'twist'),
        f'{side}_expressive_shin_twist': (f'{side}_shin', f'{side}_foot', 'twist'),
        f'{side}_expressive_foot_arch': (f'{side}_foot', f'{side}_toe', 'swing'),
    })


@dataclass(frozen=True)
class BodyHelper:
    name: str
    parent: str
    head: 'Vector'
    tail: 'Vector'
    radius_squared: float
    donors: tuple
    fraction: float


def expert_helpers(bones, body, *, expressive=False):
    feet = (bones[body['left_foot']].head_local + bones[body['right_foot']].head_local) * 0.5
    height = (bones[body['head']].head_local - feet).length
    helpers = {}
    for role, (parent_role, driver_role, kind) in EXPERT_HELPER_SOURCES.items():
        parent = bones[body[parent_role]]
        driver = bones[body[driver_role]]
        span = driver.head_local - parent.head_local
        if span.length_squared < 1e-12:
            raise ValueError('Expert needs separate rest positions for its body joints. Check the joint landmarks.')
        if kind == 'twist':
            head = parent.head_local + span * (EXPRESSIVE_TWIST_PROXIMAL if expressive else 0.5)
            radius = max(height * 0.045, span.length * (0.43 if expressive else 0.51))
            donors = (parent.name,)
            fraction = 0.32
        else:
            head = driver.head_local.copy()
            torso = not role.startswith(('left_', 'right_'))
            radius = max(height * (0.145 if torso else 0.095), span.length * 0.4)
            donors = (parent.name, driver.name)
            fraction = 0.30
        helpers[role] = BodyHelper(f'Studio_Expert_{role}', parent.name, head,
                                   head + span * 0.24, radius ** 2, donors, fraction)
    if expressive:
        helpers.update(_expressive_helpers(bones, body, height, feet))
    return helpers


def _expressive_helpers(bones, body, height, feet):
    def head(role):
        return bones[body[role]].head_local

    shoulders = head('left_arm') - head('right_arm')
    hips = head('left_leg') - head('right_leg')
    up = (head('head') - feet).normalized()
    left = shoulders - up * shoulders.dot(up)
    if left.length_squared < 1e-12 or up.length_squared < 1e-12:
        raise ValueError('Expressive needs distinct shoulder and foot landmarks to place the body helpers.')
    left.normalize()
    forward = left.cross(up).normalized()
    toe_direction = head('left_toe') + head('right_toe') - feet * 2.0
    if forward.dot(toe_direction) < 0.0:
        forward.negate()

    helpers = {}
    for role, (parent_role, driver_role, kind) in EXPRESSIVE_HELPER_SOURCES.items():
        side, part = role.split('_expressive_')
        parent, driver = bones[body[parent_role]], bones[body[driver_role]]
        span = driver.head_local - parent.head_local
        start = parent.head_local
        if kind == 'twist':
            center = start + span * EXPRESSIVE_TWIST_DISTAL
            radius = max(height * 0.058, span.length * 0.43)
            donors = (parent.name,)
            fraction = 0.32
        else:
            outward = left if side == 'left' else -left
            if part == 'scapula':
                center = start + span * 0.60 - forward * (shoulders.length * 0.20) - up * (shoulders.length * 0.065)
                radius = max(shoulders.length * 0.40, height * 0.075)
            elif part == 'thorax':
                center = start + span * 0.64 + outward * (shoulders.length * 0.26)
                radius = max(shoulders.length * 0.35, height * 0.087)
            elif part == 'hip':
                center = driver.head_local - forward * (hips.length * 0.44) + outward * (hips.length * 0.09)
                radius = max(hips.length * 0.72, height * 0.08)
            else:  # Foot arch
                center = start + span * 0.55 - up * (span.length * 0.15)
                radius = max(span.length * 0.67, height * 0.046)
            donors = (parent.name, driver.name)
            fraction = 0.30
        helpers[role] = BodyHelper(f'Studio_Expressive_{side}_{part}', parent.name, center,
                                   center + span * 0.24, radius ** 2, donors, fraction)
    return helpers


def expressive_forearm_support(twists):
    """Use the same local skin split for both forearm twist segments."""
    return {
        f'{side}_forearm_twist': BodyHelper(name, parent, start + span * EXPRESSIVE_TWIST_PROXIMAL,
                                           start + span * 0.56, (span.length * 0.46) ** 2, (parent,), 0.32)
        for side, (name, parent, start, span) in twists.items()
    }


def helpers_by_donor(helpers):
    by_donor = defaultdict(list)
    for helper in helpers.values():
        for donor in helper.donors:
            by_donor[donor].append(helper)
    return by_donor


def transfer_body_weights(weights, point, by_donor):
    original = {name: weight for name, weight in weights.items() if weight > 1e-8}
    slots = 4 - len(original)
    if slots <= 0:
        return
    candidates = {helper.name: helper for donor in original for helper in by_donor.get(donor, ())}
    proposals = []
    for helper in candidates.values():
        proximity = 1.0 - (point - helper.head).length_squared / helper.radius_squared
        if proximity <= 0:
            continue
        fraction = helper.fraction * proximity ** 2
        amount = sum(original.get(donor, 0.0) * fraction for donor in helper.donors)
        if amount > 1e-8:
            proposals.append((amount, helper.name, helper, fraction))
    for amount, name, helper, fraction in sorted(proposals, key=lambda row: (-row[0], row[1]))[:slots]:
        # At most three helpers can split a vertex's original influences.
        for donor in helper.donors:
            if donor in original:
                weights[donor] -= original[donor] * fraction
        weights[name] = amount
