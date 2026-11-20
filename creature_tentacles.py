"""Trace the appendages of a bell-up jellyfish mesh in glTF world space."""

from collections import defaultdict
from math import ceil, isfinite
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from creature_rig import MAX_CREATURE_BONES, validate_creature_bones
from glb_data import accessor, node_transforms, read


DEFAULT_SPACING = .19


def validate_tentacle_spacing(value):
    if type(value) not in (int, float) or not .05 <= value <= .50 or not isfinite(value):
        raise ValueError('Choose a joint spacing between 0.05 and 0.50 metres.')
    return float(value)


def _triangle_parts(path):
    data, binary = read(path)
    _, world = node_transforms(data)
    nodes = data.get('nodes', [])
    scenes = data.get('scenes', [])
    pending = list(scenes[data.get('scene', 0)].get('nodes', [])) if scenes else list(range(len(nodes)))
    visited = set()
    parts = []
    vertex_count = 0
    while pending:
        index = pending.pop()
        if index in visited:
            continue
        visited.add(index)
        node = nodes[index]
        pending.extend(node.get('children', []))
        if 'mesh' not in node:
            continue
        matrix = world(index)
        positions, triangles = [], []
        offset = 0
        for primitive in data['meshes'][node['mesh']]['primitives']:
            if primitive.get('mode', 4) != 4 or 'POSITION' not in primitive['attributes']:
                continue
            if 'KHR_draco_mesh_compression' in primitive.get('extensions', {}):
                raise ValueError('Tentacle detection requires uncompressed triangle geometry.')
            local = accessor(data, binary, primitive['attributes']['POSITION'])
            indices = (accessor(data, binary, primitive['indices']).ravel().astype(np.int64)
                       if 'indices' in primitive else np.arange(len(local)))
            if not len(local) or not len(indices):
                continue
            if len(indices) % 3 or indices.min() < 0 or indices.max() >= len(local):
                raise ValueError('The mesh contains invalid triangle indices.')
            vertex_count += len(local)
            if vertex_count > 2_000_000:
                raise ValueError('Simplify the mesh before detecting tentacles (maximum 2 million vertices).')
            positions.append(local @ matrix[:3, :3].T + matrix[:3, 3])
            triangles.append(indices.reshape(-1, 3) + offset)
            offset += len(local)
        if positions:
            points = np.vstack(positions)
            if not np.isfinite(points).all():
                raise ValueError('The mesh contains invalid vertex positions.')
            parts.append((points, np.vstack(triangles)))
    if not parts:
        raise ValueError('No triangle mesh was found for tentacle detection.')
    return parts


def _bell(points):
    """Find a broad continuous ring in the upper half of the model."""
    low, high = points.min(axis=0), points.max(axis=0)
    height = high[1] - low[1]
    if height <= .005:
        raise ValueError('The jellyfish mesh has no usable height.')
    highest = points[points[:, 1] > low[1] + height * .48]
    half_band = max(height / 80, .002)
    best = None
    for level in np.linspace(low[1] + height * .50, high[1] - half_band, 56):
        ring = highest[np.abs(highest[:, 1] - level) < half_band][:, [0, 2]]
        if len(ring) < 30:
            continue
        # Seam duplicates and differently tessellated parts should not skew
        # the estimate of the centre of the bell.
        scale = height * 1e-4
        ring = np.unique(np.round((ring - low[[0, 2]]) / scale), axis=0) * scale + low[[0, 2]]
        if len(ring) < 30:
            continue
        center = (np.quantile(ring, .97, axis=0) + np.quantile(ring, .03, axis=0)) * .5
        radial = ring - center
        distance = np.linalg.norm(radial, axis=1)
        radius = float(np.quantile(distance, .88))
        if radius <= height * .065:
            continue
        angular = np.arctan2(radial[:, 1], radial[:, 0])
        sectors = np.floor((angular + np.pi) * (24 / (2 * np.pi))).astype(int) % 24
        outer = distance > radius * .6
        ring_coverage = len(np.unique(sectors[outer])) / 24
        if ring_coverage < .75:
            continue
        dispersion = np.ptp(np.quantile(distance[outer], [.15, .92])) / radius
        score = radius * ring_coverage / (1 + 2.5 * dispersion)
        if best is None or score > best[0]:
            best = score, np.array([center[0], level, center[1]]), radius
    if best is None:
        raise ValueError('The bell was not detected. Orient the jellyfish with its bell above its tentacles.')
    return best[1], best[2], height


def _components(points, faces, tolerance):
    if not len(faces):
        return
    used, inverse = np.unique(faces, return_inverse=True)
    points = points[used]
    faces = inverse.reshape(-1, 3)
    # Match UV and normal seams when measuring, leaving source geometry intact.
    keys = np.rint((points - points.min(axis=0)) / tolerance).astype(np.int64)
    _, indices, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    points, faces = points[indices], inverse[faces]
    edges = np.vstack((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    graph = coo_matrix((np.ones(len(edges), dtype=np.uint8), (edges[:, 0], edges[:, 1])),
                       shape=(len(points), len(points))).tocsr()
    _, labels = connected_components(graph, directed=False)
    face_labels = labels[faces[:, 0]]
    for label in np.flatnonzero(np.bincount(labels) >= 12):
        component = faces[face_labels == label]
        used, inverse = np.unique(component, return_inverse=True)
        yield points[used], inverse.reshape(-1, 3)


def _sections(points, faces, radius):
    """Trace perimeter centres of horizontal triangle sections through a strand."""
    low, high = points[:, 1].min(), points[:, 1].max()
    count = int(np.clip(ceil((high - low) / (radius * .018)), 18, 110))
    triangles = points[faces]
    # Intersections are in pairs on each crossing triangle. Weight the midpoint
    # by segment length so triangle density does not pull the traced centre.
    corners = triangles[:, [1, 2, 0]]
    d = corners[:, :, 1] - triangles[:, :, 1]
    centers, widths = [], []
    for level in np.linspace(high - .003 * (high - low), low + .003 * (high - low), count):
        crossing = (triangles[:, :, 1] > level) != (corners[:, :, 1] > level)
        rows = np.sum(crossing, axis=1) == 2
        if not np.any(rows):
            continue
        starts, ends = triangles[rows][crossing[rows]], corners[rows][crossing[rows]]
        ratios = (level - starts[:, 1]) / d[rows][crossing[rows]]
        section = (starts + (ends - starts) * ratios[:, None]).reshape(-1, 2, 3)
        perimeter = np.linalg.norm(section[:, 1] - section[:, 0], axis=1)
        if perimeter.sum() <= 0:
            continue
        centers.append(np.average(section.mean(axis=1), weights=perimeter, axis=0))
        widths.append(np.linalg.norm(np.ptp(section.reshape(-1, 3)[:, [0, 2]], axis=0)))
    if len(centers) < count * .8:
        return None
    centers = np.asarray(centers)
    widths = np.asarray(widths)
    mid_width = np.median(widths[2:-2])
    if mid_width <= 0 or mid_width > radius * .15 or np.quantile(widths, .85) > mid_width * 3.5:
        return None
    # Remove section noise at triangle edges while preserving the endpoints.
    original = centers.copy()
    centers[1:-1] = (original[:-2] + 2 * original[1:-1] + original[2:]) * .25
    return centers


def _near_rim(point, center, radius):
    distance = np.linalg.norm((point - center)[[0, 2]]) / radius
    height = (point[1] - center[1]) / radius
    return .49 <= distance <= 1.26 and -.32 <= height <= .22


def _trace_component(points, faces, center, radius):
    low, high = points.min(axis=0), points.max(axis=0)
    if high[1] - low[1] < radius * .28 or not center[1] - radius * .30 < high[1] < center[1] + radius * .25:
        return None
    approx_root = points[points[:, 1] >= high[1] - radius * .045].mean(axis=0)
    if not _near_rim(approx_root, center, radius):
        return None
    path = _sections(points, faces, radius)
    if path is None or not _near_rim(path[0], center, radius):
        return None
    return path


def _mesh_paths(parts, center, radius):
    paths = []
    cut_y = center[1] - .10 * radius
    tolerance = max(radius * 1e-5, 1e-8)
    for points, faces in parts:
        for surface, triangles in _components(points, faces, tolerance):
            path = _trace_component(surface, triangles, center, radius)
            if path is not None:
                paths.append((path, 'mesh'))
                continue
            # A transverse cut can separate tentacles modelled as one surface
            # with the bell. This is a read-only analysis of the original mesh.
            if surface[:, 1].max() <= center[1] + .17 * radius or surface[:, 1].min() >= cut_y - .28 * radius:
                continue
            below = surface[:, 1] < cut_y
            selected = triangles[np.all(below[triangles], axis=1)]
            for strand, strand_faces in _components(surface, selected, tolerance):
                path = _trace_component(strand, strand_faces, center, radius)
                if path is None or path[0, 1] < cut_y - .10 * radius:
                    continue
                # Extend the first tangent back to the underside of the bell.
                head = path[0].copy()
                up = path[0] - path[1]
                if up[1] > 0:
                    extension = (center[1] - .03 * radius - head[1]) / up[1]
                    candidate = head + extension * up
                    if np.linalg.norm(candidate - head) < .22 * radius and _near_rim(candidate, center, radius):
                        path = np.vstack((candidate, path))
                paths.append((path, 'mesh'))
    return paths


def _dense_polyline(points, samples=32):
    length = np.concatenate(([0.], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))))
    if length[-1] <= 0:
        return length[-1], points[:1]
    distances = np.linspace(0., length[-1], samples)
    return float(length[-1]), np.column_stack([np.interp(distances, length, points[:, axis]) for axis in range(3)])


def _prediction_paths(predicted, surface, center, radius):
    if not predicted:
        return
    children = defaultdict(list)
    for bone in predicted:
        children[bone.get('parent')].append(bone)
    tree = cKDTree(surface)
    for start in predicted:
        origin = np.asarray(start['head'], dtype=float)
        if not _near_rim(origin, center, radius):
            continue
        nodes = [origin]
        bone = start
        visited = set()
        while bone['name'] not in visited:
            visited.add(bone['name'])
            tip = np.asarray(bone['tail'], dtype=float)
            nodes.append(tip)
            following = children[bone['name']]
            if len(following) != 1:
                break
            child = following[0]
            head = np.asarray(child['head'], dtype=float)
            if np.linalg.norm(head - tip) > .12 * radius:
                break
            bone = child
        path = np.asarray(nodes)
        if path[0, 1] - path[-1, 1] < .28 * radius:
            continue
        _, dense = _dense_polyline(path)
        distance, _ = tree.query(dense)
        if np.quantile(distance, .9) < .09 * radius and distance[-1] < .13 * radius:
            yield path, 'prediction'


def _separate(paths, center, radius):
    """Keep independently rooted chains, preferring traced surface geometry."""
    accepted = []
    for path, method in paths:
        angle = np.arctan2(path[0, 2] - center[2], path[0, 0] - center[0])
        if any(np.linalg.norm(path[0, [0, 2]] - prior[0, [0, 2]]) < .16 * radius
               or (method == 'prediction' and abs((angle - prior_angle + np.pi) % (2 * np.pi) - np.pi) < .24)
               for prior_angle, prior, _ in accepted):
            continue
        accepted.append((angle, path, method))
    return [(path, method) for _, path, method in sorted(accepted, key=lambda item: item[0] % (2 * np.pi))]


def adapt_tentacles(source: Path, predicted_bones: list[dict], spacing_m: float):
    """Propose one editable bell/tentacle skeleton and report its measured chains."""
    spacing = validate_tentacle_spacing(spacing_m)
    parts = _triangle_parts(source)
    surface = np.vstack([points for points, _ in parts])
    center, radius, height = _bell(surface)
    paths = _mesh_paths(parts, center, radius)
    accepted = _separate(paths + list(_prediction_paths(predicted_bones, surface, center, radius)), center, radius)
    if len(accepted) < 2:
        raise ValueError('Fewer than two independent tentacles were detected. Separate the tentacles or edit the predicted skeleton.')
    chains, bones = [], []
    root = center + [0., .065 * radius, 0.]
    bones.append(dict(name='racine', parent=None, head=root.tolist(),
                      tail=(root + [0., min(.34 * radius, .16 * height), 0.]).tolist()))
    for index, (path, method) in enumerate(accepted, 1):
        length = _dense_polyline(path, 2)[0]
        count = max(2, ceil(length / spacing))
        if len(bones) + count + 1 > MAX_CREATURE_BONES:
            raise ValueError('The spacing produces too many bones. Increase the distance between joints.')
        _, points = _dense_polyline(path, count + 1)
        bell = f'ombrelle_{index:02d}'
        inner = root + (points[0] - root) * .085
        bones.append(dict(name=bell, parent='racine', head=inner.tolist(), tail=points[0].tolist()))
        parent = bell
        name = f'tentacule_{index:02d}'
        for segment, (head, tail) in enumerate(zip(points, points[1:]), 1):
            bone_name = f'{name}_{segment:02d}'
            bones.append(dict(name=bone_name, parent=parent, head=head.tolist(), tail=tail.tolist()))
            parent = bone_name
        chains.append(dict(name=name, length_m=round(length, 5), segments=count, method=method))
    warnings = []
    if any(chain['method'] == 'prediction' for chain in chains):
        warnings.append('Some tentacle lengths were estimated from the predicted skeleton. Check their roots and tips.')
    peripheral = surface[(surface[:, 1] < center[1] - radius * .25)
                         & (np.linalg.norm((surface - center)[:, [0, 2]], axis=1) > radius * .46)]
    if len(peripheral):
        traced = np.vstack([_dense_polyline(path, 48)[1] for path, _ in accepted])
        gaps = cKDTree(traced).query(peripheral)[0] > .19 * radius
        if int(gaps.sum()) > max(30, len(gaps) * .035):
            warnings.append('Some peripheral geometry was not assigned to a tentacle. Check the proposed chains.')
    return dict(bones=validate_creature_bones(bones), chains=chains, spacing_m=spacing, warnings=warnings)
