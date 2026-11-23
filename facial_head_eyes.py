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


def append_eyes(path, eyes, normalization):
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
        write_glb(pending, doc, blob)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return added
