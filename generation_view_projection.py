"""Verified Texture Projection inputs from Pixal3D and TRELLIS.2 generations."""
from dataclasses import asdict
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
from time import perf_counter

import numpy as np
from PIL import Image

from generation_options import GENERATION_PRESETS
from normal_bake import checked_normalization
from pixal3d_runtime import CAMERA_FOV, camera_matrix, validate_views
from reference_preparation import PREPARED_VIEWS
from studio_workspace import write


PROVENANCE_FILE = '.generation-views.json'
UPSTREAM_REVISION = '66fd0d9d14ce004770322949a77493b33b136d08'
# Studio GLB Y-up to the Z-up conditioning frame.
STUDIO_PIXAL_FRAME = ((0, 2, 1), (1, -1, 1))
SHA256 = re.compile(r'[a-f0-9]{64}')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def generation_reference_name(role, *, staged=False):
    original = PREPARED_VIEWS[role]
    return f'projection-generation-{role}.png' if staged else original


def generation_reference(folder, role, *, staged=False):
    path = folder / generation_reference_name(role, staged=staged)
    if not path.is_file() or path.is_symlink() or path.resolve().parent != folder.resolve():
        raise ValueError('A saved generation reference is missing. Use Auto Align or Manual projection.')
    return path


def checked_generation_views(provenance):
    """Accept the fixed multi-view and estimated single-image Pixal3D cameras."""
    if (not isinstance(provenance, dict) or type(provenance.get('schema')) is not int
            or provenance['schema'] not in (1, 2) or not isinstance(provenance.get('model_sha256'), str)
            or not SHA256.fullmatch(provenance['model_sha256'])):
        raise ValueError('Invalid generation view provenance.')
    normalization = checked_normalization(provenance.get('normalization'))
    views = provenance.get('views')
    if not isinstance(views, list) or any(not isinstance(view, dict) for view in views):
        raise ValueError('Invalid saved generation views.')
    estimated = provenance['schema'] == 2
    if estimated:
        if (provenance.get('camera_model') != 'moge' or len(views) != 1 or views[0].get('role') != 'front'
                or type(views[0].get('azimuth')) not in (float, int) or views[0]['azimuth'] != 0):
            raise ValueError('Invalid saved single-image camera.')
    else:
        canonical = validate_views([{'role': view.get('role'), 'azimuth': view.get('azimuth')} for view in views])
        if [view['role'] for view in canonical] != [view['role'] for view in views]:
            raise ValueError('Saved generation views are out of order.')
    checked = []
    for view in views:
        role = view['role']
        fov = view.get('camera_angle_x')
        pose = np.asarray(view.get('transform_matrix'), dtype=np.float64)
        if not isinstance(view.get('sha256'), str) or not SHA256.fullmatch(view['sha256']) or type(fov) not in (float, int):
            raise ValueError('Invalid calibrated generation camera or reference fingerprint.')
        expected = camera_matrix(view['azimuth'])
        if estimated:
            if not math.radians(2) <= fov <= math.radians(160):
                raise ValueError('Invalid estimated field of view.')
            expected[1][3] = -.5 / math.tan(fov / 2)
        elif not math.isclose(fov, CAMERA_FOV, abs_tol=1e-6, rel_tol=0):
            raise ValueError('Invalid calibrated field of view.')
        if pose.shape != (4, 4) or not np.allclose(pose, expected, atol=1e-5 if estimated else 1e-6, rtol=0):
            raise ValueError('Invalid calibrated generation camera or reference fingerprint.')
        checked.append(dict(role=role, azimuth=view['azimuth'], sha256=view['sha256'],
                            camera_angle_x=float(fov), transform_matrix=pose.tolist()))
    result = dict(schema=provenance['schema'], model_sha256=provenance['model_sha256'],
                  normalization=normalization, views=checked)
    if estimated:
        result['camera_model'] = 'moge'
    return result


def save_generation_views(folder, normalization, views, *, camera_model=None):
    """Bind exact conditioning references and cameras to the finished, published GLB."""
    folder = Path(folder)
    provenance = dict(schema=1, model_sha256=digest(folder / 'model.glb'), normalization=normalization, views=views)
    if camera_model is not None:
        provenance.update(schema=2, camera_model=camera_model)
    provenance = checked_generation_views(provenance)
    write(folder / PROVENANCE_FILE, provenance)


def verify_generation_view_inputs(folder, source, provenance, *, staged=False):
    if digest(source) != provenance['model_sha256']:
        raise ValueError('The model differs from its calibrated export. Use Auto Align or Manual projection.')
    images = []
    for view in provenance['views']:
        path = generation_reference(folder, view['role'], staged=staged)
        with path.open('rb') as stream:
            payload = stream.read(16 * 1024**2 + 1)
        if len(payload) > 16 * 1024**2 or hashlib.sha256(payload).hexdigest() != view['sha256']:
            raise ValueError('A saved generation reference has changed. Use Auto Align or Manual projection.')
        try:
            with Image.open(BytesIO(payload)) as opened:
                estimated = provenance.get('camera_model') == 'moge'
                size_ok = (16 <= opened.width == opened.height <= 2048) if estimated else opened.size == (1024, 1024)
                if opened.format != 'PNG' or not size_ok or opened.mode != 'RGBA':
                    raise ValueError('The prepared view does not match the generation image format.')
                pixels = np.asarray(opened)
                if pixels[..., 3].max() < 128:
                    raise ValueError('The prepared view has an empty silhouette.')
                images.append(pixels)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            raise ValueError('A saved generation reference could not be read. Use Auto Align or Manual projection.') from error
    return images


def inspect_generation_views(folder, source, settings, supported, support_reason):
    """Return capability and verified provenance for a completed model in its workspace."""
    if not supported:
        return dict(supported=False, reason=support_reason, views=[]), None
    path = folder / PROVENANCE_FILE
    if settings.get('engine') != 'pixal3d' or not path.is_file():
        return dict(supported=False, reason='This model has no saved generation cameras. Use Auto Align or Manual projection.',
                    views=[]), None
    try:
        if path.is_symlink() or path.resolve().parent != folder.resolve() or path.stat().st_size > 32 * 1024:
            raise ValueError('Invalid generation view provenance.')
        provenance = checked_generation_views(json.loads(path.read_text(encoding='utf-8')))
        verify_generation_view_inputs(folder, source, provenance)
    except (OSError, ValueError, OverflowError, TypeError):
        return dict(supported=False, reason='Saved generation views could not be verified. Use Auto Align or Manual projection.',
                    views=[]), None
    capability = dict(supported=True, reason='', views=[view['role'] for view in provenance['views']])
    if 'camera_model' in provenance:
        capability['camera_model'] = provenance['camera_model']
    return capability, provenance


def inspect_generation_reference(folder, record, supported, support_reason, max_pixels):
    """Check that a completed TRELLIS.2 generation kept a usable saved cutout."""
    def unavailable(reason):
        return dict(supported=False, reason=reason, reference=None), None

    if not supported:
        return unavailable(support_reason)
    settings = record['settings']
    engine = (record.get('result') or {}).get('engine')
    configured_engine = settings.get('engine')
    preset = settings.get('preset')
    generated = engine == 'TRELLIS.2' or configured_engine == 'trellis2' or (
        isinstance(preset, str) and preset in GENERATION_PRESETS)
    compatible_engine = configured_engine in (None, 'trellis2') or (
        configured_engine == 'trellis' and engine == 'TRELLIS.2')
    if (not generated or engine not in (None, 'TRELLIS.2') or not compatible_engine
            or settings.get('source_kind') not in (None, 'refinish', 'baked_game_copy', 'texture_projection')):
        return unavailable('Choose a TRELLIS.2 generation or a linked copy with its saved cutout.')
    try:
        reference = generation_reference(folder, 'front')
        if reference.stat().st_size > 5 * max_pixels:
            return unavailable('The saved cutout exceeds the projection image limit. Use Manual with a resized cutout.')
        with Image.open(reference) as image:
            if image.format != 'PNG' or not 0 < image.width * image.height <= max_pixels:
                return unavailable('The saved cutout must be a PNG within the projection image limit.')
            alpha = image.convert('RGBA').getchannel('A')
            low, high = alpha.getextrema()
            if low >= 128 or high < 128:
                return unavailable('A saved cutout with a visible subject and transparent background is required. '
                                   'Use Manual with your own cutout.')
    except (OSError, ValueError, Image.DecompressionBombError):
        return unavailable('This model has no readable saved TRELLIS.2 cutout. Use Manual projection.')
    return dict(supported=True, reason='', reference='prepared'), reference


def project_generation_texture(folder, source, destination, provenance, *, progress):
    """Paint the verified generation views using the AssetFurnace Pixel Match defaults."""
    from texture_projection import _load_mesh, _publish
    from third_party.assetfurnace.image_to_3dlab import photo_paint

    started = perf_counter()
    provenance = checked_generation_views(provenance)
    images = verify_generation_view_inputs(folder, source, provenance, staged=True)
    model, binary, _, material, base, positions, _, uv, faces = _load_mesh(source)
    normalization = provenance['normalization']
    positions = (positions.astype(np.float64) - normalization['translation']) / normalization['scale']
    views = [photo_paint.View(pixels, np.asarray(view['transform_matrix']), view['camera_angle_x'], view['role'])
             for pixels, view in zip(images, provenance['views'], strict=True)]
    alignment = []
    progress('Projecting the saved generation views', .18)
    painted, confidence = photo_paint.paint_texture(base, positions, uv.astype(np.float64), faces, views,
                                                    frame=STUDIO_PIXAL_FRAME, align_reports=alignment)
    if not np.any(confidence > 0):
        raise ValueError('The saved generation views do not cover a visible surface. Try Manual projection.')
    if not np.array_equal(base[..., 3], painted[..., 3]):
        raise ValueError('The projection could not preserve the original texture alpha.')
    progress('Writing the texture copy', .9)
    if digest(source) != provenance['model_sha256']:
        raise ValueError('The staged model changed during texture projection.')
    _publish(destination, model, binary, material, painted, None)
    return dict(method='generation_views', algorithm='AssetFurnace Pixel Match', upstream_revision=UPSTREAM_REVISION,
                view_count=len(views), views=[dict(role=view.name, alignment=asdict(report))
                                            for view, report in zip(views, alignment, strict=True)],
                atlas=[base.shape[1], base.shape[0]], projected_texels=int((confidence > 0).sum()),
                atlas_confidence_fraction=float((confidence > 0).mean()), geometry_binary_unchanged=True,
                alpha_unchanged=True, source_sha256=provenance['model_sha256'],
                model_sha256=digest(destination), seconds=round(perf_counter() - started, 3))
