"""Geometry controls and confidence-weighted base-color fusion for MV-Adapter.

The model's geometry, UV layout, alpha, normals and non-color material channels
are immutable. MV-Adapter contributes projected color only to supported texels.
"""
from copy import deepcopy
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

from glb_data import read
import texture_projection as projection


SIZE = 512
FRAME = [-.55, -.55, .55, .55]
ANGLES = ((-90, 0), (0, 0), (90, 0), (180, 0), (90, 89.99), (90, -89.99))
VIEW_NAMES = ('front', 'right', 'back', 'left', 'top', 'bottom')
GLTF_TO_Z_UP = np.array(((1., 0., 0.), (0., 0., -1.), (0., 1., 0.)))


class MultiviewTextureError(ValueError):
    """A model or view could not be used safely for automatic fusion."""


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _raster_impl(screen, triangles, attributes, width, height, perspective):
    """Depth maxima and perspective-correct per-vertex attributes at pixel centres."""
    depth = np.full((height, width), -np.inf, dtype=np.float32)
    result = np.zeros((height, width, attributes.shape[1]), dtype=np.float32)
    for i in range(len(triangles)):
        a, b, c = triangles[i]
        x0, y0, z0 = screen[a]
        x1, y1, z1 = screen[b]
        x2, y2, z2 = screen[c]
        left = max(0, math.ceil(min(x0, x1, x2)))
        right = min(width - 1, math.floor(max(x0, x1, x2)))
        top = max(0, math.ceil(min(y0, y1, y2)))
        bottom = min(height - 1, math.floor(max(y0, y1, y2)))
        if left > right or top > bottom:
            continue
        dx1, dy1 = x1 - x0, y1 - y0
        dx2, dy2 = x2 - x0, y2 - y0
        determinant = dx1 * dy2 - dy1 * dx2
        if abs(determinant) < 1e-12:
            continue
        for y in range(top, bottom + 1):
            for x in range(left, right + 1):
                u = ((x - x0) * dy2 - (y - y0) * dx2) / determinant
                v = (dx1 * (y - y0) - dy1 * (x - x0)) / determinant
                w = 1 - u - v
                if min(u, v, w) < -1e-7:
                    continue
                value = w * z0 + u * z1 + v * z2
                if value <= depth[y, x]:
                    continue
                depth[y, x] = value
                if perspective:
                    w, u, v = w * z0 / value, u * z1 / value, v * z2 / value
                for column in range(attributes.shape[1]):
                    result[y, x, column] = (
                        w * attributes[a, column] + u * attributes[b, column] + v * attributes[c, column])
    return depth, result


_raster_compiled = None


def _raster(screen, faces, attributes, size, perspective):
    # Load the pinned compiler only when this optional finishing step is used.
    global _raster_compiled
    if _raster_compiled is None:
        try:
            from numba import njit
        except ImportError as error:
            raise MultiviewTextureError('Install the Studio CPU geometry dependencies for multiview textures.') from error
        _raster_compiled = njit(_raster_impl)
    return _raster_compiled(screen, faces, attributes, *size, perspective)


def _camera_plane(vertices, camera):
    # The short vectors are faster as a single-threaded contraction than a BLAS
    # matrix product, particularly while evaluating hundreds of small previews.
    basis = np.asarray(camera['basis'])
    perspective = camera['projection'] == 'perspective'
    points = vertices - camera['origin'] if perspective else vertices
    plane = np.einsum('ij,kj->ik', points, basis)
    return projection._project_camera_plane(plane, perspective), basis, perspective


def _raster_plane(plane, faces, attributes, frame, size, perspective):
    screen = np.column_stack((projection._screen(plane, frame, *size), plane[:, 2]))
    return _raster(screen, faces, attributes, size, perspective)


def _sample_view(mesh, camera, size, projected=None):
    atlas, vertices, _, uv, triangles = mesh[4:]
    if projected is None:
        plane, _, perspective = _camera_plane(vertices, camera)
    else:
        plane, perspective = projected
    depth, coordinates = _raster_plane(plane, triangles, uv, camera['frame'], size, perspective)
    foreground = np.isfinite(depth)
    color = cv2.remap(atlas[..., :3], coordinates[..., 0] * atlas.shape[1] - .5,
                      coordinates[..., 1] * atlas.shape[0] - .5,
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    color[~foreground] = 0
    return np.dstack((color, foreground.astype(np.uint8) * 255))


def _camera_for(vertices, pose, bounds):
    yaw, pitch, roll = np.deg2rad(pose[:3])
    distance = pose[3]
    right = np.array([np.cos(yaw), 0, -np.sin(yaw)])
    outward = np.array([np.sin(yaw) * np.cos(pitch), np.sin(pitch), np.cos(yaw) * np.cos(pitch)])
    up = np.cross(outward, right)
    camera = {'view': 'custom', 'basis': np.stack([
        np.cos(roll) * right + np.sin(roll) * up,
        np.cos(roll) * up - np.sin(roll) * right,
        outward,
    ]).tolist(), 'projection': 'orthographic'}
    if distance:
        low, high = vertices.min(0), vertices.max(0)
        camera.update(projection='perspective',
                      origin=((low + high) / 2 + distance * (high - low).max() * outward).tolist())
    plane, _, perspective = _camera_plane(vertices, camera)
    low, high = plane[:, :2].min(0), plane[:, :2].max(0)
    x0, y0, x1, y1 = bounds
    scale = (high - low) / [x1 - x0, y1 - y0]
    left, bottom = low - np.array([x0, 1 - y1]) * scale
    camera['frame'] = [left, bottom, left + scale[0], bottom + scale[1]]
    return camera, plane, perspective


def _color_structure(rgb):
    r, g, b = np.moveaxis(rgb.astype(np.float32), 2, 0)
    denominator = r + g + b + 60
    return (r - g) / denominator, (2 * b - r - g) / denominator


def _reference_for_fitting(path):
    reference = projection._load_reference(path)
    alpha = reference[..., 3]
    foreground = np.count_nonzero(alpha > 96)
    transparent = np.count_nonzero(alpha < 64)
    if foreground < 16 or transparent < max(8, alpha.size * .01):
        raise MultiviewTextureError('Multiview texture needs a prepared reference with a transparent background.')
    height, width = alpha.shape
    if max(height, width) > 1536:
        scale = 1536 / max(height, width)
        reference = cv2.resize(reference, (max(1, round(width * scale)), max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
    return reference


def _fit_camera(mesh, reference):
    height, width = reference.shape[:2]
    y, x = np.nonzero(reference[..., 3] > 96)
    if not len(y) or x.max() - x.min() < 3 or y.max() - y.min() < 3:
        raise MultiviewTextureError('The reference silhouette is too small to fit a camera.')
    bounds = x.min() / width, y.min() / height, (x.max() + 1) / width, (y.max() + 1) / height
    preview_size = max(16, round(width * 96 / max(width, height))), max(16, round(height * 96 / max(width, height)))
    small = cv2.resize(reference, preview_size, interpolation=cv2.INTER_AREA)
    reference_mask = small[..., 3] > 100
    reference_colors = _color_structure(small[..., :3])
    candidates = {}

    def evaluate(pose):
        if pose not in candidates:
            camera, plane, perspective = _camera_for(mesh[5], pose, bounds)
            view = _sample_view(mesh, camera, preview_size, (plane, perspective))
            mask = view[..., 3] > 0
            shared = reference_mask & mask
            overlap = float(np.count_nonzero(shared) / max(1, np.count_nonzero(reference_mask | mask)))
            colors = _color_structure(view[..., :3])
            correlations = []
            if np.count_nonzero(shared) >= 64:
                for target, source in zip(colors, reference_colors):
                    a, b = target[shared], source[shared]
                    if min(a.std(), b.std()) >= .02:
                        correlations.append(float(np.corrcoef(a, b)[0, 1]))
            score = overlap * (.95 + .05 * (float(np.mean(correlations)) if correlations else 0.))
            candidates[pose] = dict(camera=camera, pose=pose, overlap=overlap, score=score)
        return candidates[pose]

    def best():
        return max(candidates.values(), key=lambda candidate: candidate['score'])

    initial = evaluate((0, 0, 0, 0))
    for yaw, pitch, distance in itertools.product(range(-180, 180, 30), [-40, -20, 0, 20, 40], [0, 2.0]):
        evaluate((yaw, pitch, 0, distance))
    yaw, pitch, roll, _ = best()['pose']
    for y, p, r, d in itertools.product([-10, 0, 10], [-8, 0, 8], [-5, 0, 5], [0, 1.45, 2.0, 3.5]):
        evaluate((yaw + y, pitch + p, roll + r, d))
    for radius in [4, 2, 1]:
        yaw, pitch, roll, distance = best()['pose']
        for y, p, r in itertools.product([-radius, 0, radius], repeat=3):
            evaluate((yaw + y, pitch + p, roll + r, distance))
    winner = best()
    yaw = winner['pose'][0]
    alternate = max((view for view in candidates.values() if abs((view['pose'][0] - yaw + 180) % 360 - 180) > 45),
                    key=lambda candidate: candidate['score'])
    if winner['score'] - alternate['score'] < .022 and abs(winner['overlap'] - alternate['overlap']) < .035:
        raise MultiviewTextureError('Several view angles match the reference. Select a clear front reference.')
    rendered = _sample_view(mesh, winner['camera'], (width, height))
    a, b = reference[..., 3] > 100, rendered[..., 3] > 100
    overlap = float(np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b)))
    if overlap < .63:
        raise MultiviewTextureError(f'The reference silhouette only matches {overlap:.0%} of the fitted mesh view.')
    report = dict(pose=winner['pose'], camera=winner['camera'], silhouette_overlap=overlap,
                  front_preview_overlap=initial['overlap'], candidate_count=len(candidates))
    return report, rendered


def _reference_anchor(reference, rendered):
    """Reconcile small proportion differences, then suppress unreliable correspondences."""
    height, width = reference.shape[:2]
    scale = min(1, 640 / max(width, height))
    size = round(width * scale), round(height * scale)
    target = cv2.resize(rendered, size, interpolation=cv2.INTER_AREA)
    source = cv2.resize(reference, size, interpolation=cv2.INTER_AREA)
    target_mask = target[..., 3] > 224
    source_mask = source[..., 3] > 224

    def luminance(picture, mask):
        values = cv2.cvtColor(picture[..., :3], cv2.COLOR_RGB2LAB)[..., 0]
        low, high = np.percentile(values[mask], [2, 98])
        values = np.uint8(np.clip(32 + (values.astype(float) - low) * 191 / max(1, high - low), 0, 255))
        values[~mask] = 0
        return values

    if min(size) < 16 or not source_mask.any() or not target_mask.any():
        raise MultiviewTextureError('The reference is too small for a reliable surface correspondence.')
    target_luma = luminance(target, target_mask)
    source_luma = luminance(source, source_mask)
    optical_flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    optical_flow.setUseSpatialPropagation(True)
    optical_flow.setUseMeanNormalization(True)
    forward = optical_flow.calc(target_luma, source_luma, None)
    backward = optical_flow.calc(source_luma, target_luma, None)
    columns, rows = np.meshgrid(np.arange(size[0], dtype=np.float32), np.arange(size[1], dtype=np.float32))
    mapping = np.stack((columns, rows), axis=2) + forward
    inverse = cv2.remap(backward, mapping[..., 0], mapping[..., 1], cv2.INTER_LINEAR)
    distances = np.linalg.norm(forward, axis=2)
    cycle_error = np.linalg.norm(forward + inverse, axis=2)
    max_displacement = max(size) * .042
    source_distance = cv2.distanceTransform(source_mask.astype(np.uint8), cv2.DIST_L2, 5)
    target_distance = cv2.distanceTransform(target_mask.astype(np.uint8), cv2.DIST_L2, 5)
    distance_at_match = cv2.remap(source_distance, mapping[..., 0], mapping[..., 1], cv2.INTER_LINEAR)
    edge = projection._smooth(2., 11., np.minimum(distance_at_match, target_distance))
    displacement_confidence = 1 - projection._smooth(max_displacement * .45, max_displacement, distances)
    cycle_confidence = 1 - projection._smooth(2., 7., cycle_error)
    warped_luma = cv2.remap(source_luma, mapping[..., 0], mapping[..., 1], cv2.INTER_LINEAR).astype(np.float32)
    luma = target_luma.astype(np.float32)

    def smooth(values):
        return cv2.GaussianBlur(values, (0, 0), 5)

    mean_target, mean_source = smooth(luma), smooth(warped_luma)
    var_target = np.maximum(smooth(luma * luma) - mean_target ** 2, 1)
    var_source = np.maximum(smooth(warped_luma * warped_luma) - mean_source ** 2, 1)
    correlation = (smooth(luma * warped_luma) - mean_target * mean_source) / np.sqrt(var_target * var_source)
    structure = projection._smooth(-.03, .60, correlation)
    confidence = edge * displacement_confidence * cycle_confidence * structure
    confidence = cv2.GaussianBlur(np.float32(confidence), (0, 0), 1.1) * edge
    full_forward = cv2.resize(forward, (width, height), interpolation=cv2.INTER_LINEAR) / scale
    x, y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    warped = cv2.remap(reference, x + full_forward[..., 0], y + full_forward[..., 1], cv2.INTER_LINEAR)
    full_confidence = cv2.resize(confidence, (width, height), interpolation=cv2.INTER_LINEAR)
    warped[..., 3] = np.uint8(np.rint(warped[..., 3] * full_confidence))
    return warped, dict(confident_view_fraction=float(np.count_nonzero(confidence > .5) / np.count_nonzero(target_mask)),
                        median_displacement_px=float(np.median(distances[target_mask])))


def _controls(mesh, yaw):
    _, vertices, normals, _, faces = mesh[4:]
    yaw = np.deg2rad(-yaw)
    c, s = np.cos(yaw), np.sin(yaw)
    rotation = np.array(((c, -s, 0.), (s, c, 0.), (0., 0., 1.))) @ GLTF_TO_Z_UP
    oriented = np.einsum('ij,kj->ik', vertices, rotation)
    low, high = oriented.min(0), oriented.max(0)
    center = (low + high) * .5
    scale = float((high - low).max())
    if scale <= 1e-7:
        raise MultiviewTextureError('The mesh has no usable extent for multiview texture.')
    positions = (oriented - center) / scale
    canonical_normals = np.einsum('ij,kj->ik', normals, rotation)
    fields = dict(
        positions=np.zeros((len(ANGLES), SIZE, SIZE, 3), np.float32),
        normals=np.zeros((len(ANGLES), SIZE, SIZE, 3), np.float32),
        mask=np.zeros((len(ANGLES), SIZE, SIZE), bool),
    )
    views = []
    for index, ((azimuth, elevation), name) in enumerate(zip(ANGLES, VIEW_NAMES, strict=True)):
        yaw, pitch = np.deg2rad([azimuth, elevation])
        outward = np.array((np.cos(pitch) * np.cos(yaw), np.cos(pitch) * np.sin(yaw), np.sin(pitch)))
        right = np.cross([0., 0., 1.], outward)
        right /= np.linalg.norm(right)
        basis = np.stack((right, np.cross(outward, right), outward))
        plane = np.einsum('ij,kj->ik', positions, basis)
        depth, nrm = _raster_plane(plane, faces, canonical_normals, FRAME, (SIZE, SIZE), False)
        mask = np.isfinite(depth)
        if not mask.any():
            raise MultiviewTextureError('The mesh does not cover every required geometry view.')
        ys, xs = np.nonzero(mask)
        xp = FRAME[0] + (xs + .5) * (FRAME[2] - FRAME[0]) / SIZE
        yp = FRAME[3] - (ys + .5) * (FRAME[3] - FRAME[1]) / SIZE
        fields['positions'][index][mask] = np.column_stack((xp, yp, depth[mask])) @ basis
        fields['normals'][index] = nrm / np.maximum(np.linalg.norm(nrm, axis=-1, keepdims=True), 1e-10)
        fields['mask'][index] = mask
        offset = (center @ basis.T)[:2]
        frame = (np.asarray(FRAME) * scale + np.tile(offset, 2)).tolist()
        camera = dict(view='custom', projection='orthographic', basis=(basis @ rotation).tolist(), frame=frame)
        views.append(dict(index=index, name=name, azimuth=azimuth, elevation=elevation, camera=camera,
                          foreground_pixels=int(mask.sum())))
    return fields, views


def _load_model(path):
    mesh = projection._load_mesh(path)
    if mesh[4].shape[:2] not in ((1024, 1024), (2048, 2048), (4096, 4096)):
        raise MultiviewTextureError('Multiview texture requires a square 1K, 2K or 4K color atlas.')
    return mesh


def prepare(model: Path, reference: Path, work: Path):
    """Fit the source photo and write the six 512-pixel camera controls."""
    started = perf_counter()
    model, reference, work = map(Path, (model, reference, work))
    initial_hash, reference_hash = _sha(model), _sha(reference)
    mesh = _load_model(model)
    pixels = _reference_for_fitting(reference)
    report, render = _fit_camera(mesh, pixels)
    anchor, registration = _reference_anchor(pixels, render)
    fields, views = _controls(mesh, report['pose'][0])
    if _sha(model) != initial_hash or _sha(reference) != reference_hash:
        raise MultiviewTextureError('The model or reference changed during geometry preparation.')
    work.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(work / 'controls.npz', **fields)
    anchor_path = work / 'anchor.png'
    Image.fromarray(anchor).save(anchor_path)
    receipt = dict(schema=1, views=views, pixels=SIZE, triangles=len(mesh[-1]), fit=report,
                   registration=registration, model_sha256=initial_hash, reference_sha256=reference_hash,
                   anchor_sha256=_sha(anchor_path), seconds=round(perf_counter() - started, 2))
    (work / 'cameras.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt


def _lab(image):
    return cv2.cvtColor(image[..., :3].astype(np.float32) / 255, cv2.COLOR_RGB2LAB)


def _palette_coordinates(value):
    bins = np.stack((value[..., 0] / 10, (value[..., 1] + 96) / 8, (value[..., 2] + 96) / 8))
    return np.clip(bins, 0, np.array([10, 24, 24])[:, None, None])


def _palette(atlas, rendered, anchor):
    """Learn a bounded chroma correction from matched image and albedo pairs."""
    a, b = _lab(rendered), _lab(anchor)
    confidence = anchor[..., 3].astype(np.float32) / 255
    valid = (confidence > .62) & (rendered[..., 3] > 240)
    count = int(valid.sum())
    if count < 1000:
        return atlas, dict(applied=False, registered_color_pairs=count)
    weights = confidence[valid] ** 2
    delta = np.clip((b - a)[valid, 1:], -45, 45)
    bins = np.rint(_palette_coordinates(a)[:, valid]).astype(np.intp)
    shape = (11, 25, 25)
    index = np.ravel_multi_index(bins, shape)

    def smooth(values):
        return gaussian_filter(np.bincount(index, weights=values, minlength=np.prod(shape)).reshape(shape),
                               sigma=(1.8, 1.1, 1.1))

    support = smooth(weights)
    residual = [smooth(weights * delta[:, channel]) / (support + 2) for channel in range(2)]
    picture = atlas.copy()
    # Limit conversion temporaries to a few rows on large texture atlases.
    for start in range(0, len(atlas), 256):
        tile = slice(start, start + 256)
        colors = _lab(atlas[tile])
        bins = _palette_coordinates(colors)
        fitted = np.stack([map_coordinates(r, bins, order=1, mode='nearest') for r in residual], axis=-1)
        colors[..., 1:] += np.clip(fitted, -23, 23) * .84
        rgb = cv2.cvtColor(colors, cv2.COLOR_LAB2RGB)
        picture[tile, :, :3] = np.uint8(np.rint(np.clip(rgb, 0, 1) * 255))
    return picture, dict(applied=True, registered_color_pairs=count)


def _surface_points(mesh):
    atlas, vertices, normals, uv, faces = mesh[4:]
    height, width = atlas.shape[:2]
    uv_pixels = uv * [width, height] - .5
    owner, ambiguous = projection._uv_coverage(vertices, normals, uv_pixels, faces, width, height, None, None)
    covered = owner >= 0
    ids = np.flatnonzero(covered & ~ambiguous)
    points = np.empty((len(ids), 3), np.float32)
    directions = np.empty_like(points)
    for start in range(0, len(ids), 250_000):
        part = slice(start, start + 250_000)
        y, x = np.unravel_index(ids[part], covered.shape)
        triangles = faces[owner[y, x]]
        p0, p1, p2 = uv_pixels[triangles].transpose(1, 0, 2)
        a, b = p1 - p0, p2 - p0
        d = np.stack((x, y), axis=1) - p0
        determinant = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
        u = (d[:, 0] * b[:, 1] - d[:, 1] * b[:, 0]) / determinant
        v = (a[:, 0] * d[:, 1] - a[:, 1] * d[:, 0]) / determinant
        barycentric = np.stack((1 - u - v, u, v), axis=1).astype(np.float32)
        points[part] = np.einsum('ni,niv->nv', barycentric, vertices[triangles])
        normal = np.einsum('ni,niv->nv', barycentric, normals[triangles])
        directions[part] = normal / np.linalg.norm(normal, axis=1, keepdims=True).clip(1e-6)
    if not len(ids):
        raise MultiviewTextureError('No unambiguous UV texels are available to receive the texture.')
    return covered, ids, points, directions


def _view_contribution(mesh, points, normals, camera, reference, view_weight):
    height, width = reference.shape[:2]
    baseline = _sample_view(mesh, camera, (width, height))
    vertices, _, uv, faces = mesh[5:]
    plane, basis, perspective = _camera_plane(vertices, camera)
    resolution = max(1024, min(2048, max(width, height)))
    scale = resolution / max(width, height)
    zsize = round(width * scale), round(height * scale)
    zbuffer, _ = _raster_plane(plane, faces, uv, camera['frame'], zsize, perspective)
    cloud, _, _ = _camera_plane(points, camera)
    u, v = projection._screen(cloud, camera['frame'], width, height).T
    in_frame = (u >= .5) & (u < width - 1.5) & (v >= .5) & (v < height - 1.5)
    if perspective:
        rays = np.asarray(camera['origin'], np.float32) - points
        rays /= np.maximum(1e-6, np.linalg.norm(rays, axis=1, keepdims=True))
        incidence = np.einsum('ni,ni->n', normals, rays)
    else:
        incidence = np.einsum('ij,j->i', normals, basis[2])
    candidates = np.flatnonzero(in_frame & (incidence >= .18))
    ix, iy = np.rint(projection._screen(cloud[candidates], camera['frame'], *zsize)).astype(np.int32).T
    near = zbuffer[iy.clip(0, zsize[1] - 1), ix.clip(0, zsize[0] - 1)].astype(np.float64)
    center = cloud[candidates, 2]
    gap = (1. / center) - (1. / near) if perspective else near - center
    tolerance = max(.001, float(np.ptp(vertices, axis=0).max()) * .0018)
    candidates = candidates[np.isfinite(near) & (gap <= tolerance)]
    x, y = u[candidates], v[candidates]
    alpha = np.minimum(reference[..., 3], baseline[..., 3]).astype(np.float32) / 255
    silhouette = cv2.distanceTransform((alpha > .05).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    visibility = map_coordinates(alpha, [y, x], order=1)
    distance = map_coordinates(silhouette, [y, x], order=1)
    edge = ((distance - 1.25) / (min(width, height) * .022)).clip(0, 1)
    weight = (incidence[candidates] - .16).clip(0) ** 3
    weight *= edge * edge * (3 - 2 * edge) * visibility * view_weight
    active = weight >= 1e-4
    candidates, x, y, weight = (value[active] for value in (candidates, x, y, weight))
    delta = _lab(reference) - _lab(baseline)
    sigma = max(2, min(delta.shape[:2]) / 52)
    area = cv2.GaussianBlur(alpha, (0, 0), sigma).clip(.001)
    lighting = cv2.GaussianBlur(delta[..., 0] * alpha, (0, 0), sigma) / area
    detail = delta[..., 0] - lighting
    limited = np.stack(((.7 * detail + .18 * lighting).clip(-16, 16),
                        (.38 * delta[..., 1]).clip(-10, 10), (.38 * delta[..., 2]).clip(-10, 10)), axis=-1)

    def sample(picture):
        return np.stack([map_coordinates(channel, [y, x], order=1, mode='nearest')
                         for channel in np.moveaxis(picture, -1, 0)], axis=-1)

    return candidates, weight.astype(np.float32), sample(delta), sample(limited)


def _view_inputs(work, receipt):
    directory = work / 'views'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8-sig'))
    views = manifest.get('views')
    if (manifest.get('reference_sha256') != receipt['reference_sha256'] or not isinstance(views, list)
            or len(views) != len(VIEW_NAMES) or not all(isinstance(view, dict) for view in views)):
        raise MultiviewTextureError('The generated views do not match this reference and camera set.')
    with np.load(work / 'controls.npz', allow_pickle=False) as controls:
        masks = controls['mask']
    if masks.shape != (len(VIEW_NAMES), SIZE, SIZE):
        raise MultiviewTextureError('The saved geometry masks are invalid.')
    for index, (view, expected) in enumerate(zip(views, receipt['views'], strict=True)):
        name = f'view-{index:02d}.png'
        image = directory / name
        if (view.get('image') != name or view.get('camera') != expected.get('camera')
                or image.resolve().parent != directory.resolve()):
            raise MultiviewTextureError('A generated view has invalid camera or file provenance.')
        pixels = projection._load_reference(image)
        if (pixels.shape != (SIZE, SIZE, 4)
                or not np.array_equal(pixels[..., 3], masks[index].astype(np.uint8) * 255)):
            raise MultiviewTextureError('A generated view no longer matches its geometry mask.')
        yield expected['name'], projection._camera(expected['camera']), pixels, 1.


def _fuse(mesh, views, anchor_camera):
    covered, texel_ids, points, normals = _surface_points(mesh)
    total = np.zeros((len(points), 3), np.float32)
    detail = np.zeros_like(total)
    squared = np.zeros_like(total)
    weights = np.zeros(len(points), np.float32)
    hits = np.zeros(len(points), np.uint8)
    reports = []
    for label, camera, reference, strength in views:
        ids, weight, difference, refined = _view_contribution(mesh, points, normals, camera, reference, strength)
        # Candidate ids are unique one-per-compatible texel in a single view.
        total[ids] += difference * weight[:, None]
        detail[ids] += refined * weight[:, None]
        squared[ids] += difference ** 2 * weight[:, None]
        weights[ids] += weight
        hits[ids] += 1
        reports.append(dict(label=label, visible_texels=len(ids)))
    active = weights > 1e-4
    if not active.any():
        raise MultiviewTextureError('The generated views have no reliable overlap with the UV atlas.')
    w = weights[active, None]
    fused, refined = total[active] / w, detail[active] / w
    spread = np.maximum(squared[active] / w - fused ** 2, 0)
    confidence = np.minimum(weights[active] / .32, 1) / (1 + np.sqrt(spread.mean(axis=1)) / 20)
    facing = (np.einsum('ij,j->i', normals[active], anchor_camera['basis'][2]) - .05).clip(0, .65) / .65
    protect = (facing ** 2 * (3 - 2 * facing))[:, None]
    delta = (1 - protect) * (.74 * fused) + protect * (.72 * refined)
    picture = mesh[4].copy()
    target = texel_ids[active]
    height, width = covered.shape
    lab = _lab(picture)
    lab.reshape(-1, 3)[target] += delta * confidence[:, None]
    rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    picture.reshape(-1, 4)[target, :3] = (rgb[target].clip(0, 1) * 255).round().astype(np.uint8)
    edited = np.zeros(height * width, bool)
    edited[target] = True
    edited = edited.reshape(covered.shape)
    distance, nearest = distance_transform_edt(~covered, return_indices=True)
    gutter = (~covered) & (distance <= 8) & edited[nearest[0], nearest[1]]
    picture[gutter, :3] = picture[nearest[0][gutter], nearest[1][gutter], :3]
    report = dict(view_reports=reports, coverage_percent=round(100 * active.sum() / covered.sum(), 3),
                  overlap_percent=round(100 * np.count_nonzero(hits >= 2) / covered.sum(), 3))
    return picture, report


def finish(model: Path, reference: Path, work: Path, output: Path, *, apply_palette=True):
    """Fuse the rendered views with a protected front and publish a verified GLB copy."""
    started = perf_counter()
    model, reference, work, output = map(Path, (model, reference, work, output))
    if output.exists() or not output.parent.is_dir():
        raise MultiviewTextureError('The fused texture must be written to a new model file.')
    receipt = json.loads((work / 'cameras.json').read_text(encoding='utf-8-sig'))
    initial_hash = _sha(model)
    anchor_path = work / 'anchor.png'
    if (receipt.get('schema') != 1 or receipt.get('model_sha256') != initial_hash
            or receipt.get('reference_sha256') != _sha(reference)
            or receipt.get('anchor_sha256') != _sha(anchor_path)):
        raise MultiviewTextureError('The model, reference or fitted anchor changed after view preparation.')
    original = _load_model(model)
    anchor = projection._load_reference(anchor_path)
    camera = projection._camera(receipt['fit']['camera'])
    palette = dict(applied=False)
    atlas = original[4]
    if apply_palette:
        rendered = _sample_view(original, camera, anchor.shape[:2][::-1])
        atlas, palette = _palette(atlas, rendered, anchor)
    mesh = original[:4] + (atlas,) + original[5:]
    views = itertools.chain(_view_inputs(work, receipt), [('Original anchor', camera, anchor, 1.7)])
    picture, report = _fuse(mesh, views, camera)
    with TemporaryDirectory(prefix='.multiview-', dir=output.parent) as folder:
        staged = Path(folder) / 'model.glb'
        document, binary, _, index, original_atlas = original[:5]
        projection._publish(staged, document, binary, index, picture, None)
        updated, blob = read(staged)
        materials = deepcopy(updated['materials'])
        standard = document['materials'][index]['pbrMetallicRoughness']
        materials[index]['pbrMetallicRoughness']['baseColorTexture'] = standard['baseColorTexture']
        if (not blob.startswith(binary) or materials != document['materials']
                or any(updated.get(key) != document.get(key) for key in (
                    'accessors', 'nodes', 'scenes', 'meshes', 'skins', 'animations'))
                or not np.array_equal(original_atlas[..., 3], projection._load_mesh(staged)[4][..., 3])
                or _sha(model) != initial_hash):
            raise MultiviewTextureError('Texture fusion could not preserve the mesh or non-color material data.')
        try:
            os.link(staged, output)
        except FileExistsError as error:
            raise MultiviewTextureError('A model already exists at the multiview output path.') from error
    report.update(state='applied', triangles=len(original[-1]), atlas=list(atlas.shape[:2][::-1]),
                  cameras=len(VIEW_NAMES) + 1, silhouette_overlap=receipt['fit']['silhouette_overlap'],
                  palette=palette, geometry_uv_and_other_pbr_equal=True, seconds=round(perf_counter() - started, 2),
                  input_sha256=initial_hash, output_sha256=_sha(output))
    return report
