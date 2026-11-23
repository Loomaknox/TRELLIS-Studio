"""Use the frontal reference to guide the base colour of the first PBR volume."""
import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt

from facial_head_geometry import SKIN, _depth, _sample


# MediaPipe contours for both open eyes. The separate eye meshes supply their colours.
EYES = ((33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7),
        (263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249))


def _smooth(low, high, values):
    t = np.clip((values - low) / (high - low), 0., 1.)
    return t*t*(3. - 2.*t)


def _reference_patch(subject, source_xy, target, origin, step, size):
    # The registration is affine in the frontal plane. Fit all image landmarks so
    # that cropping or translating the supplied photograph doesn't change the result.
    fit = np.linalg.lstsq(np.column_stack((target, np.ones(len(target)))), source_xy, rcond=None)[0]
    x, y = np.meshgrid(np.arange(size) * step + origin[0], np.arange(size) * step + origin[1])
    grid = (np.stack((x, y), axis=-1) @ fit[:2] + fit[2]).astype(np.float32)
    rgba = cv2.remap(np.asarray(subject.convert('RGBA')), grid, None, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT).astype(np.float32) / 255.
    skin = np.zeros((size, size), np.uint8)
    def polygon(points):
        return np.rint((target[list(points)] - origin) / step).astype(np.int32)
    cv2.fillPoly(skin, [polygon(SKIN)], 1)
    eye_span = np.linalg.norm(target[33] - target[263]) / step
    # SKIN ends at the eyebrows and above the jaw. The hairline, temples (including
    # most implants), ears and neck retain native PBR. Fade the periphery into it.
    weight = _smooth(0., max(3., .17*eye_span), distance_transform_edt(skin))
    openings = np.zeros_like(skin)
    cv2.fillPoly(openings, [polygon(eye) for eye in EYES], 1)
    weight *= _smooth(.35, max(1.5, .021*eye_span), distance_transform_edt(~openings.astype(bool)))
    weight *= rgba[..., 3]
    rgb = rgba[..., :3].copy()
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
    gain = np.clip((np.median(broad[valid]) / np.maximum(broad, .05))**.48, .78, 1.27)
    rgb *= gain[..., None]
    return rgb.clip(0., 1.), weight


def guide_base_color(coords, attrs, layout, resolution, vertices, faces, target, source_xy, subject):
    """Guide visible skin voxels in place, leaving all other PBR channels untouched."""
    size = 224
    skin = target[list(SKIN)]
    origin = (skin.min(0) + skin.max(0)) / 2 - np.ptp(skin, axis=0).max() * .58
    step = np.ptp(skin, axis=0).max() * 1.16 / (size - 1)
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
    # A profile face receives little colour from a single frontal image, including
    # faces visible through tiny holes. Tangential surfaces fade into native colour.
    smooth_depth = cv2.GaussianBlur(depth, (0, 0), 2.)
    dy, dx = np.gradient(smooth_depth, step)
    frontal = 1./np.sqrt(1. + dx*dx + dy*dy)
    weight *= _smooth(.20, .78, frontal) * visible

    # O-Voxel stores sparse cells at their integer lower corners in [-.5, .5]^3.
    xy = (coords[:, (1, 3)].astype(np.float32) + .5) / resolution - .5
    xy -= origin
    xy /= step
    selected = np.flatnonzero(np.all((xy >= 0.) & (xy < size - 1), axis=1))
    pos = xy[selected]
    z = .5 - (coords[selected, 2].astype(np.float32) + .5) / resolution
    gap = np.abs(_sample(depth, pos) - z) * resolution
    strength = .94 * _sample(weight, pos) * (1. - _smooth(1.1, 3.6, gap))
    keep = strength > 1./255.
    selected = selected[keep]
    if not len(selected):
        raise ValueError('The facial reference does not cover visible material voxels.')
    pos, blend = pos[keep], strength[keep, None]
    reference = np.stack([_sample(rgb[..., k], pos) for k in range(3)], axis=1)
    channels = layout['base_color']
    old = attrs[selected, channels]
    attrs[selected, channels] = old + blend * (reference - old)
    return int(len(selected))
