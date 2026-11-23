"""Transfer the visible relief of a TOPOS head to an upright TRELLIS mesh.

TOPOS and the viewer are Y-up, facing +Z. Native TRELLIS is Z-up, facing -Y.
All fitting below is in frontal coordinates (screen right, up, toward camera).
"""
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt, map_coordinates
from scipy.interpolate import LinearNDInterpolator


# MediaPipe anatomical landmark -> zero-based vertex on TOPOS's released
# 24,049-vertex template.obj. TOPOS-DiT preserves these vertex indices in its OBJ.
ANCHORS = {
    33: 14745, 133: 19228, 362: 22241, 263: 8765,       # eye corners
    159: 13759, 145: 901, 386: 7780, 374: 3972,         # eyelid margins
    1: 2922, 98: 20564, 327: 23577, 168: 2938,          # nose and bridge
    61: 13028, 291: 7056, 0: 12207, 17: 12177,          # lips
    152: 2975, 234: 20066, 454: 23079, 10: 2948,       # chin, cheeks, forehead
}
# Keep the hairline, outer temples, ears, underside of the jaw and neck outside the edit.
SKIN = (70, 63, 105, 66, 107, 9, 336, 296, 334, 293, 300,
        345, 352, 376, 377, 152, 148, 147, 123, 116)


def read_topos(path):
    vertices, triangles = [], []
    with Path(path).open(encoding='ascii') as stream:
        for line in stream:
            if line.startswith('v '):
                vertices.append(tuple(map(float, line.split()[1:4])))
            elif line.startswith('f '):
                ids = [int(token.split('/')[0]) - 1 for token in line.split()[1:]]
                triangles.extend((ids[0], ids[i], ids[i + 1]) for i in range(1, len(ids) - 1))
    points = np.array(vertices, dtype=np.float32)
    faces = np.array(triangles, dtype=np.int32)
    if (points.shape != (24049, 3) or not np.isfinite(points).all() or not faces.size
            or faces.min() < 0 or faces.max() >= len(points)):
        raise ValueError('Unexpected TOPOS head topology.')
    return points, faces


def face_landmarks(data, subject):
    landmarks = np.array(data['landmarks'], dtype=np.float64)
    if (landmarks.shape != (478, 3) or not np.isfinite(landmarks).all()
            or tuple(data['image_size']) != subject.size):
        raise ValueError('Face landmarks do not match the selected reference.')
    pixels = landmarks[:, :2] * subject.size
    span = np.linalg.norm(pixels[263] - pixels[33])
    separation = pixels[263, 0] - pixels[33, 0]
    if (separation < 12 or separation < .93 * span
            or not .28 < (pixels[1, 0] - pixels[33, 0]) / separation < .72
            or pixels[152, 1] <= pixels[1, 1]):
        raise ValueError('Face enhancement needs a clear, upright, near-frontal face.')
    return pixels


def _depth(vertices, faces, origin, step, size):
    from multiview_texture_fusion import _raster

    screen = np.array(vertices, dtype=np.float32, order='C', copy=True)
    screen[:, :2] = (screen[:, :2] - origin) / step
    attrs = np.empty((len(screen), 0), dtype=np.float32)
    depth, _ = _raster(screen, faces, attrs, (size, size), False)
    valid = np.isfinite(depth)
    if not valid.any():
        raise ValueError('The front of the generated head could not be located.')
    if not valid.all():
        nearest = distance_transform_edt(~valid, return_distances=False, return_indices=True)
        depth = depth[tuple(nearest)]
    return depth, valid


def _sample(field, plane):
    return map_coordinates(field, [plane[:, 1], plane[:, 0]], order=1, mode='nearest')


def _align_native_relief(native, estimate, mask, radius):
    # A front reference is not a calibrated TRELLIS camera. Match the existing
    # nose, eyes and mouth relief before carving sockets, or even a few millimetres
    # of framing error can leave two sets of eyelids. Suppress noisy isolated spikes.
    def detail(depth):
        smooth = cv2.GaussianBlur(depth, (0, 0), 2.)
        return smooth - cv2.GaussianBlur(smooth, (0, 0), 11.)

    x, y, w, h = cv2.boundingRect(mask)
    x0, y0 = max(0, x - radius), max(0, y - radius)
    search = detail(native)[y0:min(len(mask), y + h + radius), x0:min(len(mask), x + w + radius)]
    sample = detail(estimate)[y:y+h, x:x+w]
    use = cv2.erode(mask, np.ones((5, 5), np.uint8))[y:y+h, x:x+w]
    scores = cv2.matchTemplate(search, sample, cv2.TM_CCORR_NORMED, mask=use)
    scores[~np.isfinite(scores)] = -1
    _, best, _, location = cv2.minMaxLoc(scores)
    if best < .23:
        raise ValueError('The generated facial relief does not match the reference landmarks.')
    return np.array([location[0] + x0 - x, location[1] + y0 - y])


def _bounded_relief(native, donor, mask, step, span):
    """Transfer broad relief with a bounded spatial derivative on porous meshes."""
    def front(depth):
        return cv2.GaussianBlur(cv2.medianBlur(depth.astype(np.float32), 5), (0, 0), 2.)

    source, estimate = front(native), front(donor)
    distance = distance_transform_edt(mask) * step
    core = distance > .07 * span
    difference = estimate - source
    residual = difference - np.median(difference[core])
    if np.quantile(np.abs(residual[core]), .9) > .4 * span:
        raise ValueError('Front depth does not match a frontal humanoid face.')
    bound = span * .15
    delta = bound * np.tanh(residual / bound) * np.clip(distance / (.14 * span), 0, 1)
    # Infimal/supremal L1 envelopes bound adjacent height differences even at
    # nostrils where the z-buffer intermittently sees the back of the head.
    slope = .43
    def lower_envelope(values):
        out = values.copy()
        for axis in (0, 1):
            rows = out if axis == 0 else out.T
            for i in range(1, len(rows)):
                rows[i] = np.minimum(rows[i], rows[i-1] + step * slope)
            for i in range(len(rows) - 2, -1, -1):
                rows[i] = np.minimum(rows[i], rows[i+1] + step * slope)
        return out
    smooth = (lower_envelope(delta) - lower_envelope(-delta)) * .5
    smooth = cv2.GaussianBlur(smooth, (0, 0), 1.0)
    return np.clip(smooth, -distance * slope, distance * slope), source


def _eye_well(body, faces, eye_xy, axis, up, half_width, half_opening, radius, center_depth):
    """Split crossing triangles at the lid line and recess the inner surface.

    A true edge on each side of the rim avoids stretching thin native triangles
    between the skin and the globe. All original points retain their coordinates.
    """
    rel = body[:, :2] - eye_xy
    scaled_x = (rel @ axis) / half_width
    scaled_y = (rel @ up) / half_opening
    # A gently pointed aperture better follows a neutral human eyelid than a circle.
    signed = scaled_x**2 + scaled_y**2 / np.maximum(.52, 1 - .34 * np.abs(scaled_x)) - 1
    # The eye occupies the front of the head only.
    signed = np.maximum(signed, (center_depth - .6 * radius - body[:, 2]) / radius)
    active = np.flatnonzero((signed[faces] < 0).any(axis=1))
    if len(active) < 8:
        raise ValueError('Insufficient native geometry at the projected eyelid.')
    points = []
    def append(point):
        points.append(point)
        return len(body) + len(points) - 1
    def coord(index):
        return body[index] if index < len(body) else points[index - len(body)]
    inner, intersections, extra = {}, {}, []
    def recessed(index):
        if index not in inner:
            v = coord(index).copy()
            floor = center_depth - .15 * radius
            if v[2] <= floor:
                return index
            v[2] = floor
            inner[index] = append(v)
        return inner[index]
    def edge_point(a, b):
        edge = (min(a,b), max(a,b))
        if edge not in intersections:
            fraction = signed[a] / (signed[a] - signed[b])
            intersections[edge] = append(body[a] + fraction * (body[b] - body[a]))
        return intersections[edge]
    for tri in faces[active]:
        outside, inside = [], []
        for i in range(3):
            a, b = int(tri[i - 1]), int(tri[i])
            if (signed[a] < 0) != (signed[b] < 0):
                joint = edge_point(a,b)
                outside.append(joint)
                inside.append(joint)
                if signed[a] < 0:
                    exit_joint = joint
                else:
                    entry_joint = joint
            (inside if signed[b] < 0 else outside).append(b)
        for polygon in (outside, [recessed(i) for i in inside]):
            extra.extend((polygon[0],polygon[i],polygon[i+1]) for i in range(1,len(polygon)-1))
        if outside:
            # Reverse the border of the exterior layer while bridging to the interior.
            entry_floor, exit_floor = recessed(entry_joint), recessed(exit_joint)
            if entry_floor != entry_joint:
                extra.append((exit_joint, entry_joint, entry_floor))
            if exit_floor != exit_joint:
                extra.append((exit_joint, entry_floor, exit_floor))
    keep = np.ones(len(faces), bool)
    keep[active] = False
    return (np.concatenate((body, np.asarray(points, dtype=body.dtype))),
            np.concatenate((faces[keep], np.asarray(extra, dtype=faces.dtype))))


def _deformation_quality(before, after, faces, changed):
    active = faces[changed[faces].any(axis=1)]
    if not len(active):
        raise ValueError('No front-facing facial surface could be fitted.')
    edges, normals = [], []
    for vertices in (before, after):
        triangles = vertices[active].astype(np.float64)
        edge = np.roll(triangles, -1, axis=1) - triangles
        edges.append(np.linalg.norm(edge, axis=2))
        normals.append(np.cross(edge[:, 0], edge[:, 1]))
    valid = edges[0] > 1e-8
    if not valid.any():
        raise ValueError('No front-facing facial surface could be fitted.')
    stretch = edges[1][valid] / edges[0][valid]
    turned = np.einsum('ij,ij->i', *normals) < 0
    nondegenerate = np.linalg.norm(normals[0], axis=1) > 1e-13
    flips = int(np.count_nonzero(turned & nondegenerate))
    p99 = float(np.quantile(stretch, .99))
    maximum = float(stretch.max())
    if flips > .002 * nondegenerate.sum() or p99 > 1.8 or maximum > 2.5:
        raise ValueError('The facial deformation would fold or overstretch the original mesh.')
    return dict(tested_faces=len(active), flipped_normals=flips, edge_stretch_p99=p99, edge_stretch_max=maximum)


def fit_relief(vertices, faces, donor, donor_faces, reference_pixels, subject, iris_rgb):
    """Move only the visible facial surface. Return native vertices and eye pivots."""
    alpha_box = subject.getchannel('A').point(lambda value: 255 if value >= 205 else 0).getbbox()
    if alpha_box is None:
        raise ValueError('The face reference needs a visible silhouette.')
    left, top, right, bottom = alpha_box
    body = np.ascontiguousarray(vertices[:, [0, 2, 1]], dtype=np.float32)
    body[:, 2] *= -1
    height = float(np.ptp(body[:, 1]))
    factor = height / max(bottom - top - 1, 1)
    target = (reference_pixels - [(left + right - 1) / 2, top]) * [factor, -factor]
    target += [(body[:, 0].min() + body[:, 0].max()) / 2, body[:, 1].max()]
    span = np.linalg.norm(target[263] - target[33])
    # Plausibility checks prevent applying the face to a sideways character or to clothing.
    if not .025 < span / height < .13 or target[1, 1] < body[:, 1].max() - .25 * height:
        raise ValueError('The reference must show an upright full-body humanoid with a visible head.')
    original_xy = donor[list(ANCHORS.values()), :2]
    aligned_xy = target[list(ANCHORS)]
    scale = span / np.linalg.norm(donor[8765, :2] - donor[14745, :2])
    transform = np.linalg.lstsq(np.column_stack((original_xy, np.ones(len(original_xy)))), aligned_xy, rcond=None)[0]
    if np.linalg.det(transform[:2, :]) <= 0:
        raise ValueError('The predicted head faces away from the reference.')
    projected = np.column_stack((donor[:, :2], np.ones(len(donor)))) @ transform
    residual = aligned_xy - projected[list(ANCHORS.values())]
    if np.max(np.linalg.norm(residual, axis=1)) > .36 * span:
        raise ValueError('TOPOS facial features could not be registered reliably.')
    # The fixed correspondence also aligns the shape and opening of each eyelid.
    projected += LinearNDInterpolator(original_xy, residual, fill_value=0.)(donor[:, :2])
    head = np.column_stack((projected, donor[:, 2] * scale))
    size = 224
    center = (target[list(SKIN)].min(0) + target[list(SKIN)].max(0)) / 2
    extent = np.ptp(target[list(SKIN)], axis=0).max() * 1.50
    step = extent / (size - 1)
    origin = center - extent / 2
    local = (body[:, :2] - origin) / step
    region = np.all((local >= -2) & (local < size + 2), axis=1)
    nearby_faces = faces[region[faces].any(axis=1)]
    if len(nearby_faces) < 80:
        raise ValueError('Too few triangles overlap the predicted face.')
    body_depth, body_visible = _depth(body, nearby_faces, origin, step, size)
    donor_depth, donor_visible = _depth(head, donor_faces, origin, step, size)
    mask = np.zeros((size, size), np.uint8)
    pol = np.rint((target[list(SKIN)] - origin) / step).astype(np.int32)
    cv2.fillPoly(mask, [pol], 1)
    radius = int(.23 * span / step)
    shift = _align_native_relief(body_depth, donor_depth, mask, radius)
    eye_region = mask.copy()
    y = int(np.min(pol[:, 1]) + .65 * np.ptp(pol[:, 1]))
    eye_region[:y] = 0
    try:
        eye_shift = _align_native_relief(body_depth, donor_depth, eye_region, radius)
    except ValueError:
        eye_shift = shift
    translation = (.35 * shift + .65 * eye_shift) * step
    origin += translation
    target += translation
    local = (body[:, :2] - origin) / step
    region = np.all((local >= -2) & (local < size + 2), axis=1)
    body_depth, body_visible = _depth(body, faces[region[faces].any(axis=1)], origin, step, size)
    if (mask.astype(bool) & body_visible & donor_visible).sum() < .90 * mask.sum():
        raise ValueError('The generated head and the reference face have insufficient overlap.')
    delta, source = _bounded_relief(body_depth, donor_depth, mask, step, span)
    indices = np.flatnonzero(region)
    pos = local[indices]
    level = np.median(source[mask != 0])
    layer = np.clip((body[indices, 2] - level + span) / (.72 * span), 0, 1)
    body[indices, 2] += _sample(delta, pos) * (layer**2 * (3 - 2 * layer))
    displaced = np.abs(body[:, 2] + vertices[:, 1]) > 1e-7
    before = np.ascontiguousarray(vertices[:, [0, 2, 1]])
    before[:, 2] *= -1
    quality = _deformation_quality(before, body, nearby_faces, displaced)
    changed = int(np.count_nonzero(displaced))
    eyes = []
    for side, (outer, inner, upper, lower, pupil) in enumerate(((33, 133, 159, 145, 468), (263, 362, 386, 374, 473))):
        corners = target[[outer, inner]]
        middle = corners.mean(0)
        axis = corners[1] - corners[0]
        width = np.linalg.norm(axis)
        axis /= width
        up = np.array([-axis[1], axis[0]])
        if up[1] < 0:
            up *= -1
        opening = float((target[upper] - target[lower]) @ up)
        if not .08 < opening / width < .68:
            raise ValueError('Both eyelids must be open and clearly visible.')
        middle += up * ((target[[upper, lower]].mean(0) - middle) @ up)
        radius = .54 * width
        margin_points = (target[[outer, inner, upper, lower]] - origin) / step
        center_depth = float(np.quantile(_sample(source + delta, margin_points), .30) - .96 * radius)
        body, faces = _eye_well(body, faces, middle, axis, up, .48 * width, .49 * opening, radius, center_depth)
        rgb = np.asarray(iris_rgb[side], dtype=float)
        if rgb.shape != (3,) or not np.isfinite(rgb).all() or np.any((rgb < 0) | (rgb > 255)):
            raise ValueError('Invalid reference iris colour.')
        gaze = np.clip((target[pupil] - middle) / radius, -.26, .26)
        iris_diameter = np.linalg.norm(target[pupil + 1] - target[pupil + 3])
        iris_angle = np.arcsin(np.clip(iris_diameter / (2 * radius), .38, .54))
        eyes.append(dict(name='Eye.R' if side == 0 else 'Eye.L',
                         center=[float(middle[0]), float(middle[1]), center_depth], radius=float(radius),
                         gaze=gaze.tolist(), iris_rgb=rgb.astype(int).tolist(), iris_angle=float(iris_angle)))
    output = np.ascontiguousarray(body[:, [0,2,1]])
    output[:, 1] *= -1
    return output, faces, eyes, changed, target, quality
