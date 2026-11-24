"""CPU-only reference preparation shared by previews and generation jobs."""
from collections import OrderedDict
import hashlib
import json
import math
from threading import Lock

import numpy as np
from PIL import Image, ImageDraw

from segmentation_runtime import BackgroundRemovalError, masks


PREPARED_VIEWS = {'front': 'prepared.png', 'left': 'prepared-left.png',
                  'back': 'prepared-back.png', 'right': 'prepared-right.png'}
_MASK_CACHE = OrderedDict()
_PREPARATION_LOCK = Lock()


def parse_reference_edits(raw, roles):
    if len(raw) > 128 * 1024:
        raise ValueError('Reference corrections are too large.')
    try:
        edits = json.loads(raw) if raw else {}
    except (ValueError, RecursionError) as error:
        raise ValueError('Invalid reference corrections.') from error
    if not isinstance(edits, dict) or any(role not in roles for role in edits):
        raise ValueError('Reference corrections must match the supplied views.')

    def normalized(values, count):
        return isinstance(values, list) and len(values) == count and all(
            type(value) in (int, float) and 0 <= value <= 1 for value in values)

    for edit in edits.values():
        if not isinstance(edit, dict) or edit.keys() - {'crop', 'strokes'}:
            raise ValueError('Invalid reference corrections.')
        if 'crop' in edit:
            crop = edit['crop']
            if not normalized(crop, 4) or crop[0] >= crop[2] or crop[1] >= crop[3]:
                raise ValueError('Invalid reference crop.')
        strokes = edit.get('strokes', [])
        if not isinstance(strokes, list) or len(strokes) > 48:
            raise ValueError('Use at most 48 brush strokes per view.')
        for stroke in strokes:
            if (not isinstance(stroke, dict) or stroke.keys() != {'mode', 'radius', 'points'}
                or stroke['mode'] not in ('keep', 'erase')
                or not normalized([stroke['radius']], 1) or not 0.001 <= stroke['radius'] <= 0.5
                or not isinstance(stroke['points'], list) or not 1 <= len(stroke['points']) <= 128
                or not all(normalized(point, 2) for point in stroke['points'])):
                raise ValueError('Invalid reference brush stroke.')
    return edits


def _automatic_cutouts(sources, weights, alpha_threshold, *, straight_alpha=False):
    cutouts = {}
    pending = {}
    keys = {}
    selected = {}
    for role, source in sources.items():
        if source.getchannel('A').getextrema()[0] < alpha_threshold:
            cutouts[role] = source.copy()
            continue
        try:
            key = (weights, weights.stat().st_mtime_ns, source.size, hashlib.sha256(source.tobytes()).digest())
        except OSError as error:
            raise BackgroundRemovalError('Background removal needs the Studio U2Net model. Use transparent images or reinstall Studio.') from error
        keys[role] = key
        if key in _MASK_CACHE:
            _MASK_CACHE.move_to_end(key)
            selected[key] = _MASK_CACHE[key]
        else:
            pending[key] = source
    for key, mask in zip(pending, masks(list(pending.values()), weights)):
        selected[key] = _MASK_CACHE[key] = mask
        if len(_MASK_CACHE) > 8:
            _MASK_CACHE.popitem(last=False)
    for role, key in keys.items():
        source = sources[role]
        if straight_alpha:
            cutouts[role] = source.copy()
            cutouts[role].putalpha(selected[key])
        else:
            cutouts[role] = Image.composite(source, Image.new('RGBA', source.size), selected[key])
    return {role: cutouts[role] for role in sources}


def _paint(cutout, source, strokes):
    if not strokes:
        return
    width, height = source.size
    opaque = source.copy()
    opaque.putalpha(255)
    for stroke in strokes:
        radius = max(1, round(stroke['radius'] * min(source.size)))
        points = [(round(x * (width - 1)), round(y * (height - 1))) for x, y in stroke['points']]
        brush = Image.new('L', source.size)
        draw = ImageDraw.Draw(brush)
        draw.line(points, fill=255, width=2 * radius + 1, joint='curve')
        for x, y in (points[0], points[-1]):
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
        if stroke['mode'] == 'keep':
            cutout.paste(opaque, mask=brush)
        else:
            cutout.paste((0, 0, 0, 0), (0, 0, width, height), brush)


def _crop_box(size, crop):
    width, height = size
    return (math.floor(crop[0] * width), math.floor(crop[1] * height),
            math.ceil(crop[2] * width), math.ceil(crop[3] * height))


def _cropped(image, crop, role):
    if crop is None:
        return image
    box = _crop_box(image.size, crop)
    if box[2] - box[0] < 16 or box[3] - box[1] < 16:
        raise ValueError(f'The {role} view crop must be at least 16 × 16 pixels.')
    return image.crop(box)


def reference_warnings(cutout, crop, engine):
    """Describe the mask sent for framing, without changing the approved reference."""
    width, height = cutout.size
    left, top, right, bottom = _crop_box(cutout.size, crop) if crop else (0, 0, width, height)
    alpha = cutout.getchannel('A')
    threshold = 128 if engine == 'pixal3d' else 205
    selection = alpha.crop((left, top, right, bottom))
    visible = sum(selection.histogram()[threshold:])
    warnings = []
    if visible < max(64, (right - left) * (bottom - top) * .01):
        warnings.append('reference_mask_small')
    if alpha.getextrema()[0] < threshold:
        # Compare both sides of each new crop edge. An intentional trim of
        # transparent margins should not be reported as a cut silhouette.
        mask = np.asarray(alpha) >= threshold
        crosses = (
            left > 0 and np.any(mask[top:bottom, left - 1] & mask[top:bottom, left]),
            right < width and np.any(mask[top:bottom, right - 1] & mask[top:bottom, right]),
            top > 0 and np.any(mask[top - 1, left:right] & mask[top, left:right]),
            bottom < height and np.any(mask[bottom - 1, left:right] & mask[bottom, left:right]),
        )
        if any(crosses):
            warnings.append('reference_crop_cut')
    return warnings


def _trellis_frame(image):
    # Match the pinned TRELLIS.2 preprocessing used by unreviewed jobs.
    scale = min(1, 1024 / max(image.size))
    if scale < 1:
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                             Image.Resampling.LANCZOS)
    bounds = image.getchannel('A').point(lambda value: 255 if value > 204 else 0).getbbox()
    if bounds is None:
        raise ValueError('No usable silhouette in the front view. Restore the foreground or change the crop.')
    left, top, right, bottom = bounds
    right -= 1
    bottom -= 1
    half = max(right - left, bottom - top) // 2
    if half == 0:
        raise ValueError('The front silhouette is too small.')
    x, y = (left + right) / 2, (top + bottom) / 2
    return Image.fromarray((premultiplied_rgb(image.crop((x - half, y - half, x + half, y + half))) * 255).astype(np.uint8))


def pixal_silhouette(image, role):
    bounds = image.getchannel('A').point(lambda value: 255 if value >= 128 else 0).getbbox()
    if bounds is None or bounds[2] - bounds[0] < 16 or bounds[3] - bounds[1] < 16:
        raise ValueError(f'No usable silhouette in the {role} view.')
    return image.crop(bounds)


def frame_pixal(silhouettes):
    # All views share body height even when one silhouette is wider.
    height = min(920, min(944 * image.height // image.width for image in silhouettes.values()))
    if height < 128:
        raise ValueError('The reference silhouette is too wide. Use a full-body character image.')
    frames = {}
    for role, image in silhouettes.items():
        width = max(1, round(image.width * height / image.height))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (1024, 1024))
        canvas.paste(image, ((1024 - width) // 2, (1024 - height) // 2))
        frames[role] = canvas
    return frames


def frame_pixal_single(image):
    # Match the single-image conditioning crop used by the MoGe comparison.
    scale = min(1., 1024 / max(image.size))
    if scale < 1:
        image = image.resize(tuple(max(1, int(edge * scale)) for edge in image.size), Image.Resampling.LANCZOS)
    bounds = image.getchannel('A').point(lambda value: 255 if value > 204 else 0).getbbox()
    if bounds is None:
        raise ValueError('No usable silhouette in the reference. Restore the foreground or change the crop.')
    left, top, right, bottom = bounds
    right -= 1
    bottom -= 1
    half = int(1.1 * max(right - left, bottom - top)) // 2
    if half < 8:
        raise ValueError('The reference silhouette is too small.')
    x, y = (left + right) / 2, (top + bottom) / 2
    return image.crop((x - half, y - half, x + half, y + half))


def premultiplied_rgb(image):
    rgba = np.asarray(image, dtype=np.float32) / 255
    return rgba[..., :3] * rgba[..., 3:4]


def prepare_references(sources, edits, engine, remove_bg, weights):
    with _PREPARATION_LOCK:
        single_pixal = engine == 'pixal3d_single'
        threshold = 128 if engine == 'pixal3d' or single_pixal else (255 if remove_bg else 256)
        cutouts = _automatic_cutouts(sources, weights, threshold, straight_alpha=single_pixal)
        cropped = {}
        for role, cutout in cutouts.items():
            edit = edits.get(role, {})
            _paint(cutout, sources[role], edit.get('strokes', []))
            cropped[role] = _cropped(cutout, edit.get('crop'), role)
        if engine == 'pixal3d':
            frames = frame_pixal({role: pixal_silhouette(image, role) for role, image in cropped.items()})
        elif single_pixal:
            frames = {'front': frame_pixal_single(cropped['front'])}
        else:
            frames = {'front': _trellis_frame(cropped['front'])}
        return cutouts, frames
