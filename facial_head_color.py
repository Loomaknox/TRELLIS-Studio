"""Guide visible facial texels while Studio builds the first PBR atlas."""
import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from scipy.interpolate import LinearNDInterpolator

from facial_head_geometry import _depth, _sample


# MediaPipe contours for both open eyes. The separate eye meshes supply their colours.
EYES = ((33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7),
        (263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249))
FACE_OVAL = (10,338,297,332,284,251,389,356,454,323,361,288,397,365,379,378,
             400,377,152,148,176,149,150,136,172,58,132,93,234,127,162,21,54,103,67,109)


def _smooth(low, high, values):
    t = np.clip((values - low) / (high - low), 0., 1.)
    return t*t*(3. - 2.*t)


def _face_outline(target):
    # The full MediaPipe oval includes the outer eyebrows and both temples.
    # Occlusion and skin confidence subsequently remove hair and accessories.
    return target[list(FACE_OVAL)]


def _reference_patch(subject, source_xy, target, origin, step, size):
    fit = np.linalg.lstsq(np.column_stack((target, np.ones(len(target)))), source_xy, rcond=None)[0]
    x, y = np.meshgrid(np.arange(size) * step + origin[0], np.arange(size) * step + origin[1])
    plane = np.stack((x, y), axis=-1)
    grid = plane @ fit[:2] + fit[2]
    # A remeshed eye or mouth can move separately. Map the reference through
    # the actual, locally registered landmarks rather than a global head transform.
    residual = source_xy - (target @ fit[:2] + fit[2])
    if np.abs(residual).max() > .15:
        unique, idx = np.unique(target, axis=0, return_index=True)
        grid += LinearNDInterpolator(unique, residual[idx], fill_value=0.)(plane)
    grid = grid.astype(np.float32)
    rgba = cv2.remap(np.asarray(subject.convert('RGBA')), grid, None, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT).astype(np.float32) / 255.
    skin = np.zeros((size, size), np.uint8)
    def polygon(points):
        return np.rint((target[list(points)] - origin) / step).astype(np.int32)
    cv2.fillPoly(skin, [np.rint((_face_outline(target) - origin) / step).astype(np.int32)], 1)
    eye_span = np.linalg.norm(target[33] - target[263]) / step
    weight = _smooth(0., max(3., .15*eye_span), distance_transform_edt(skin))
    openings = np.zeros_like(skin)
    cv2.fillPoly(openings, [polygon(eye) for eye in EYES], 1)
    # Remove the photographed iris from the colour field itself as well as its
    # coverage mask. Filtering near a lid must not paint a second pupil on skin.
    weight *= _smooth(.10, max(1.25, .012*eye_span), distance_transform_edt(~openings.astype(bool)))
    weight *= rgba[..., 3]
    rgb = cv2.inpaint(np.uint8(np.rint(rgba[..., :3] * 255)), openings,
                      max(1., .018*eye_span), cv2.INPAINT_TELEA).astype(np.float32) / 255.
    # The outline alone cannot exclude a strand crossing a cheek or a bright
    # metal marking. Estimate this person's skin colour on both cheeks. Protect
    # eyebrows and lips, which can naturally differ just as strongly from skin.
    swatches = np.zeros_like(skin)
    for index in (50, 205, 187, 280, 425, 411):
        point = tuple(polygon((index,))[0])
        cv2.circle(swatches, point, max(2, round(.05*eye_span)), 1, -1)
    samples = swatches.astype(bool) & (weight > .35)
    if samples.sum() >= 16:
        lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
        typical = np.median(lab[samples], axis=0)
        light = lab[..., 0] - typical[0]
        colour = np.linalg.norm(lab[..., 1:] - typical[1:], axis=-1)
        dark = _smooth(.40, .69, -light / max(24., typical[0]))
        foreign = _smooth(18., 34., colour)
        shiny = _smooth(14., 34., light) * _smooth(7., 20., colour)
        features = openings.copy()
        for group in ((70,63,105,66,107,55,65,52,53,46),
                      (300,293,334,296,336,285,295,282,283,276),
                      (70,63,105,66,107,133,173,157,158,159,160,161,246,33),
                      (300,293,334,296,336,362,398,384,385,386,387,388,466,263),
                      (61,40,37,0,267,270,291,321,314,17,84,91)):
            cv2.fillPoly(features, [polygon(group)], 1)
        outside = _smooth(0., max(1.5, .035*eye_span), distance_transform_edt(~features.astype(bool)))
        foreign = np.maximum(np.maximum(foreign, shiny), dark) * outside
        weight *= 1. - cv2.GaussianBlur(foreign, (0, 0), .8)
    # Attenuate only broad light gradients. Preserve the hue of the lips, fine
    # creases and local skin tone, and leave specular shading to the PBR renderer.
    lum = rgb @ np.array([.2126, .7152, .0722], dtype=np.float32)
    sigma = max(2., .14*eye_span)
    coverage = cv2.GaussianBlur(weight, (0, 0), sigma)
    broad = cv2.GaussianBlur(lum * weight, (0, 0), sigma) / np.maximum(coverage, 1e-5)
    valid = weight > .45
    if not valid.any():
        raise ValueError('The frontal skin colour could not be sampled from the reference.')
    gain = np.clip((np.median(broad[valid]) / np.maximum(broad, .05))**.26, .85, 1.16)
    rgb *= gain[..., None]
    return rgb.clip(0., 1.), weight


def prepare_face_material(vertices, faces, target, source_xy, subject):
    """Save the visibility and reference fields used by the optional first bake."""
    import torch
    size = int(np.clip(np.ptp(source_xy, axis=0).max() * 2, 320, 768))
    skin = _face_outline(target)
    extent = np.ptp(skin, axis=0).max() * 1.16
    origin = (skin.min(0) + skin.max(0) - extent) / 2
    step = extent / (size - 1)
    if not np.isfinite(step) or step <= 0:
        raise ValueError('The facial mask has no extent.')
    rgb, weight = _reference_patch(subject, source_xy, target, origin, step, size)
    body = np.ascontiguousarray(vertices[:, [0, 2, 1]])
    body[:, 2] *= -1
    local = (body[:, :2] - origin) / step
    outside = ((local[:, 0] < -1).astype(np.uint8) | ((local[:, 0] > size) << 1)
               | ((local[:, 1] < -1) << 2) | ((local[:, 1] > size) << 3)).astype(np.uint8)
    overlaps = (outside[faces[:, 0]] & outside[faces[:, 1]] & outside[faces[:, 2]]) == 0
    depth, visible = _depth(body, faces[overlaps], origin, step, size)
    # The existing surface may have tiny disconnected triangles. Use the closest
    # stable layer within the visible neighbourhood to avoid speckling the real skin behind them.
    stable = cv2.medianBlur(depth, 5)
    front = np.minimum(depth, stable)
    smooth_depth = cv2.GaussianBlur(stable, (0, 0), 2.)
    dy, dx = np.gradient(smooth_depth, step)
    frontal = 1./np.sqrt(1. + dx*dx + dy*dy)
    eye_span = float(np.linalg.norm(target[33] - target[263]))
    x = origin[0] + step*np.arange(size)
    lateral = _smooth(.50, .83, np.abs(x - target[1, 0])/eye_span)
    # An eyelid is steep but visible. Use grazing angle on the lateral cheeks
    # only; the depth test itself determines whether the central skin is visible.
    weight *= (1 - lateral[None, :] * (1 - _smooth(.18, .74, frontal))) * visible
    return dict(version=1, origin=torch.from_numpy(origin.astype(np.float32)), step=float(step),
                eye_span=eye_span, eye_line=torch.from_numpy(target[[33,263]].mean(0).astype(np.float32)),
                depth=torch.from_numpy(front.astype(np.float32)),
                weight=torch.from_numpy(weight.astype(np.float32)), rgb=torch.from_numpy(rgb))


def _peripheral_light(pos, original, reference, blend, ring, size, sigma):
    """Recover a smooth illumination/colour transition from unoccluded peripheral skin."""
    if np.count_nonzero(ring) < 20:
        return 0.
    x, y = np.rint(pos[ring]).astype(np.int32).T
    cell = y*size+x
    def blur(data):
        return cv2.GaussianBlur(data.reshape(size,size).astype(np.float32), (0,0), sigma)
    samples = np.bincount(cell, minlength=size*size)
    count = blur(samples)
    difference = (original[ring]-reference[ring]).clip(-.24,.24)
    baseline = np.median(difference, axis=0)
    bias = []
    for channel in range(3):
        total = np.bincount(cell, weights=difference[:, channel], minlength=size*size)
        field = (blur(total) + .01*baseline[channel])/(count + .01)
        bias.append(_sample(field, pos))
    return np.stack(bias, axis=1) * (.32 + .68*(1-blend)**1.5)


def _guide_points(points, attrs, layout, guide, supported=None):
    """Project at each original UV texel's exact native 3D position."""
    channels = layout['base_color']
    rgb, depth, weight = [np.asarray(guide[k]) for k in ('rgb', 'depth', 'weight')]
    xy = (points[:, (0, 2)] - np.asarray(guide['origin'])) / guide['step']
    inside = np.all((xy >= 0.) & (xy < len(depth)-1), axis=1) & np.isfinite(points[:, 1])
    ids = np.flatnonzero(inside)
    pos = xy[ids]
    gap = (_sample(depth, pos) + points[ids, 1]) / guide['eye_span']
    strength = _sample(weight, pos) * (1. - _smooth(.022, .065, gap))
    if 'eye_line' in guide:
        # A metal implant may sit several millimetres away from its photograph.
        # Protect a neighbourhood around the actual front-facing hardware to
        # avoid painting its photographic double on adjacent forehead skin.
        eye_xy = np.asarray(guide['eye_line'])
        local = (points[ids][:, (0, 2)] - eye_xy) / guide['eye_span']
        temple = (np.abs(local[:, 0]) > .30) & (local[:, 1] > .19) & (gap < .04)
        old = attrs[ids, channels]
        metallic = attrs[ids, layout['metallic']].reshape(-1)
        accent = (old.max(1) > .70) & (np.ptp(old, axis=1) > .46)
        hardware = temple & ((metallic > .45) | accent)
        if supported is not None:
            hardware &= supported[ids]
        if np.any(hardware):
            obstacle = np.zeros_like(weight, dtype=bool)
            x, y = np.rint(pos[hardware]).astype(np.int32).T
            obstacle[y, x] = True
            dist = distance_transform_edt(~obstacle) * guide['step'] / guide['eye_span']
            strength *= _smooth(.105, .205, _sample(dist, pos))
    keep = strength > 1./255.
    if supported is not None:
        # Unsupported texels elsewhere are inpainted by the standard bake.
        keep &= supported[ids] | (strength > .80)
    selected, pos, blend = ids[keep], pos[keep], strength[keep, None]
    reference = np.stack([_sample(rgb[..., k], pos) for k in range(3)], axis=1)
    result = attrs[selected].copy()
    original = result[:, channels].astype(np.float32)
    # Match the peripheral skin to the existing material under the same light.
    # Limit offsets in the core to preserve eyebrow, eyelid and lip contrast.
    ring = (blend[:, 0] > .12) & (blend[:, 0] < .80)
    if supported is not None:
        ring &= supported[selected]
    reference += _peripheral_light(pos, original, reference, blend, ring, len(depth),
                                   max(2., .20*guide['eye_span']/guide['step']))
    result[:, channels] = np.clip(original + blend * (reference - original), 0., 1.)
    if supported is not None:
        missing = ~supported[selected]
        result[missing, channels] = reference[missing].clip(0., 1.)
        for field, value in [('alpha', 1.), ('metallic', 0.), ('roughness', .66)]:
            result[missing, layout[field]] = value
    return selected, result


def apply_face_material(positions, surface_mask, material_mask, attrs, layout, guide):
    """Update the initial UV samples. Both rasterizers emit points in surface-mask order."""
    import torch
    origin = torch.as_tensor(guide['origin'], device=positions.device)
    size = len(guide['depth'])
    span = (size - 1) * guide['step']
    uv_rows = torch.nonzero(surface_mask.reshape(-1), as_tuple=True)[0]
    albedo = attrs.reshape(-1, attrs.shape[-1])
    supported = material_mask.reshape(-1)
    related = ((positions[:,0] >= origin[0]) & (positions[:,0] < origin[0] + span)
               & (positions[:,2] >= origin[1]) & (positions[:,2] < origin[1] + span))
    rows = uv_rows[related]
    indices, values = _guide_points(positions[related].detach().cpu().numpy(),
                                   albedo[rows].detach().cpu().numpy(), layout, guide,
                                   supported[rows].detach().cpu().numpy())
    if not len(indices):
        raise ValueError('The facial reference does not cover visible material texels.')
    target = rows[torch.as_tensor(indices, device=rows.device)]
    albedo[target] = torch.as_tensor(values, dtype=attrs.dtype, device=attrs.device)
    material_mask.reshape(-1)[target] = True
    return len(indices)
