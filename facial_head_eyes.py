"""Portable eye nodes with local rotation pivots and a small procedural iris material."""
import io
import json
from pathlib import Path
import struct
import numpy as np
from PIL import Image
import trimesh


def _globe(eye):
    radius = eye['radius']
    # Rings about the gaze axis make the circular iris independent of the UV seam.
    latitude, longitude = np.mgrid[0:25, 0:33]
    polar = latitude * np.pi / 24
    azimuth = longitude * np.pi / 16
    normals = np.column_stack((np.ravel(np.sin(polar) * np.cos(azimuth)),
                               np.ravel(np.sin(polar) * np.sin(azimuth)), np.cos(polar).ravel()))
    indices = np.arange(latitude.size).reshape(latitude.shape)
    a, b, c, d = [q.ravel() for q in (indices[:-1, :-1], indices[1:, :-1], indices[1:, 1:], indices[:-1, 1:])]
    faces = np.concatenate((np.column_stack((a, b, c))[a // 33 < 23],
                            np.column_stack((a, c, d))[a // 33 > 0]))
    phi, theta = np.mgrid[0:256, 0:64]
    angle = phi * np.pi / 255
    rgb = np.empty((256, 64, 3), np.uint8)
    rgb[:] = [193, 185, 174]
    iris = np.array(eye['iris_rgb'])
    variation = .92 + .08 * np.cos(theta * np.pi * 9 / 32) * np.cos(angle * 14)
    iris_angle = eye.get('iris_angle', .45)
    rgb[angle < iris_angle] = (iris * variation[angle < iris_angle, None]).astype(np.uint8)
    rgb[(angle >= .92 * iris_angle) & (angle < iris_angle)] = np.rint(iris * .70).astype(np.uint8)
    rgb[angle < .44 * iris_angle] = [9, 8, 7]
    mat = trimesh.visual.material.PBRMaterial(name=eye['name'] + ' iris',
        baseColorTexture=Image.fromarray(rgb), metallicFactor=0., roughnessFactor=.49)
    uv = np.column_stack((longitude.ravel() / 32, 1 - latitude.ravel() / 24))
    return trimesh.Trimesh(vertices=normals * radius, faces=faces, vertex_normals=normals, process=False,
                           visual=trimesh.visual.TextureVisuals(uv=uv, material=mat))


def eye_openings(doc, blob):
    """Measure disconnected views of either globe through the final, simplified skin."""
    import cv2
    from glb_data import accessor, node_transforms
    from multiview_texture_fusion import _raster

    _, matrix = node_transforms(doc)
    eyes = {n['name']: matrix(i)[:3, 3] for i, n in enumerate(doc['nodes'])
            if n.get('name') in ('Eye.R', 'Eye.L') and 'mesh' in n}
    if len(eyes) != 2:
        raise ValueError('The exported face is missing an eye.')
    span = np.linalg.norm(eyes['Eye.L'] - eyes['Eye.R'])
    if not np.isfinite(span) or span <= 0:
        raise ValueError('The exported eye spacing is invalid.')
    center = (eyes['Eye.R'] + eyes['Eye.L']) / 2
    width, height = 480, 192
    scale = 220 / span
    body = np.full((height, width), -np.inf, np.float32)
    globes = {eye: np.full_like(body, -np.inf) for eye in eyes}
    for i, node in enumerate(doc['nodes']):
        if 'mesh' not in node:
            continue
        transform = matrix(i)
        surface = globes.get(node.get('name'), body)
        for prim in doc['meshes'][node['mesh']]['primitives']:
            points = accessor(doc, blob, prim['attributes']['POSITION']) @ transform[:3, :3].T + transform[:3, 3]
            points[:, :2] = (points[:, :2] - center[:2])*[scale, -scale] + [width/2, height/2]
            tris = accessor(doc, blob, prim['indices']).reshape(-1, 3)
            bounds = ((points[:, 0] < 0).astype(np.uint8) + 2*(points[:, 0] >= width)
                      + 4*(points[:, 1] < 0) + 8*(points[:, 1] >= height))
            tris = tris[(bounds[tris[:, 0]] & bounds[tris[:, 1]] & bounds[tris[:, 2]]) == 0]
            depths, _ = _raster(points.astype(np.float32), tris, np.empty((len(points), 0), np.float32),
                                (width, height), False)
            np.maximum(surface, depths, out=surface)
    report = {}
    for name, depth in globes.items():
        visible = (depth > body).astype(np.uint8)
        # Bridge subpixel cracks and fine strands in this fixed, eye-scaled view.
        joined = cv2.morphologyEx(visible, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        _, labels = cv2.connectedComponents(joined)
        areas = np.bincount(labels[visible != 0])
        ordered = sorted(areas[1:].tolist(), reverse=True)
        report[name] = dict(visible_pixels=int(visible.sum()), largest_opening_pixels=ordered[0] if ordered else 0,
                            second_opening_pixels=ordered[1] if len(ordered) > 1 else 0)
    return report


def append_eyes(path, eyes, normalization, *, check_openings=False):
    """Append both eyes after body-only finishing; retain UVs, tangents and maps."""
    from glb_data import read
    from generated_motion import write_glb

    scene = trimesh.Scene()
    added = dict(triangles=0, vertices=0)
    for eye in eyes:
        globe = _globe(eye)
        globe.apply_scale(normalization['scale'])
        gaze = np.asarray(eye['gaze'])
        normal = np.array([*gaze, np.sqrt(1. - np.dot(gaze, gaze))])
        transform = trimesh.geometry.align_vectors([0., 0., 1.], normal)
        transform[:3, 3] = np.asarray(eye['center']) * normalization['scale'] + normalization['translation']
        scene.add_geometry(globe, geom_name=eye['name'], node_name=eye['name'], transform=transform)
        added['triangles'] += len(globe.faces)
        added['vertices'] += len(globe.vertices)
    # The miniature scene is created above, so every reference has a known layout.
    # Keep the original body binary intact, including any baked tangent normal map.
    stream = io.BytesIO(scene.export(file_type='glb'))
    stream.seek(12)
    length, kind = struct.unpack('<II', stream.read(8))
    if kind != 0x4e4f534a:
        raise ValueError('Invalid eye mesh descriptor.')
    eye_doc = json.loads(stream.read(length))
    length, kind = struct.unpack('<II', stream.read(8))
    if kind != 0x004e4942:
        raise ValueError('Invalid eye geometry buffer.')
    path = Path(path)
    doc, original = read(path)
    blob = bytearray(original)
    blob.extend(b'\0' * (-len(blob) % 4))
    byte_offset = len(blob)
    blob.extend(stream.read(length))
    array_names = ('bufferViews','accessors','images','textures','materials','meshes','nodes')
    offsets = {name:len(doc.get(name, [])) for name in array_names}
    for view in eye_doc['bufferViews']:
        view['byteOffset'] = view.get('byteOffset', 0) + byte_offset
    for accessor in eye_doc['accessors']:
        accessor['bufferView'] += offsets['bufferViews']
    for resource in eye_doc['images']:
        resource['bufferView'] += offsets['bufferViews']
    for texture in eye_doc['textures']:
        texture['source'] += offsets['images']
    for material in eye_doc['materials']:
        material['pbrMetallicRoughness']['baseColorTexture']['index'] += offsets['textures']
        # Single-surface eyes combine the iris with corneal reflections. A modest
        # dielectric reflection keeps dark irises legible under the studio HDRI.
        material.setdefault('extensions', {})['KHR_materials_specular'] = {'specularFactor': .18}
    extensions = doc.setdefault('extensionsUsed', [])
    if 'KHR_materials_specular' not in extensions:
        extensions.append('KHR_materials_specular')
    for mesh in eye_doc['meshes']:
        for primitive in mesh['primitives']:
            primitive['attributes'] = {k:v + offsets['accessors'] for k,v in primitive['attributes'].items()}
            primitive['indices'] += offsets['accessors']
            primitive['material'] += offsets['materials']
    for node in eye_doc['nodes']:
        if 'mesh' in node:
            node['mesh'] += offsets['meshes']
        if 'children' in node:
            node['children'] = [n + offsets['nodes'] for n in node['children']]
    roots = doc['scenes'][doc.get('scene', 0)]['nodes']
    for name in array_names:
        doc.setdefault(name, []).extend(eye_doc[name])
    roots.extend(n + offsets['nodes'] for n in eye_doc['scenes'][eye_doc.get('scene', 0)]['nodes'])
    pending = path.with_name('facial-eyes.pending.glb')
    try:
        if check_openings:
            openings = eye_openings(doc, blob)
            for stats in openings.values():
                largest = stats['largest_opening_pixels']
                if largest < 60 or stats['second_opening_pixels'] > max(12, .025 * largest):
                    raise ValueError('The exported eye is obscured or visible through a second opening in the eyelid.')
            added['visible_openings'] = openings
        write_glb(pending, doc, blob)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return added
