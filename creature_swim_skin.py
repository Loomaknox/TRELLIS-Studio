"""Keep newly rigged bell surfaces from inheriting lower tentacle motion."""
from collections import Counter
from pathlib import Path

import numpy as np

from creature_swim import swim_rig
from generated_motion import _write_atomic, append_access
from glb_data import accessor, read


def append_joint_indices(data, binary, assignments):
    binary.extend(b'\0' * (-len(binary) % 4))
    start = len(binary)
    binary.extend(np.asarray(assignments, dtype='<u2').tobytes())
    view = len(data['bufferViews'])
    data['bufferViews'].append({'buffer': 0, 'byteOffset': start, 'byteLength': len(binary) - start,
                                'target': 34962})
    index = len(data['accessors'])
    data['accessors'].append({'bufferView': view, 'componentType': 5123, 'type': 'VEC4',
                              'count': len(assignments)})
    return index


def corrected_weights(positions, indices, weights, destinations, attachments, clearance):
    y = positions[:, 1]
    mounts = attachments[indices]
    planes = mounts[:, :, 1]
    margin = clearance[indices]
    above = y[:, None] > planes + margin
    dx = positions[:, None, 0] - mounts[:, :, 0]
    dz = positions[:, None, 2] - mounts[:, :, 2]
    near_stem = (dx * dx + dz * dz < (3 * margin)**2) & (y[:, None] < planes + 4 * margin)
    # Detached bell layers and rim decorations can straddle the narrow
    # attachment band. Do not use this shortcut for a downward appendage.
    at_bell = (y.min() >= planes - 2 * margin) & (y.max() > planes + 3 * margin)
    move = (destinations[indices] != indices) & (weights > 0) & ((above & ~near_stem) | at_bell)
    changed = move.any(axis=1)
    if not changed.any():
        return None, None, 0
    corrected_indices = indices.copy()
    corrected = weights.copy()
    selected = np.where(move[changed], destinations[indices[changed]], indices[changed])
    values = weights[changed].copy()
    for first in range(selected.shape[1]):
        for other in range(first + 1, selected.shape[1]):
            matches = selected[:, first] == selected[:, other]
            values[matches, first] += values[matches, other]
            values[matches, other] = 0.0
    values /= values.sum(axis=1, keepdims=True)
    corrected_indices[changed] = selected
    corrected[changed] = values
    return corrected_indices, corrected, int(changed.sum())


def stabilize_swim_skin(source_path, destination_path):
    """Transfer upper-surface tentacle weights to the corresponding bell bones.

    Only run this once on a freshly generated swim rig. A later animation
    edit should keep the prepared skin. Other binary data are kept verbatim.
    """
    source = Path(source_path)
    data, binary = read(source)
    if not binary or len(data.get('buffers', [])) != 1 or data['buffers'][0].get('uri'):
        raise ValueError('Jellyfish swim requires one embedded GLB buffer.')
    _, chains, rays, _, _, world, _ = swim_rig(data)
    mesh_instances = Counter(node['mesh'] for node in data['nodes'] if 'mesh' in node)
    poses = {index: (bell, world[chain[0]][:3, 3], max(.0001, rays[branch][1] * .022))
             for branch, (bell, chain) in chains.items() for index in chain}
    prepared = bytearray(binary)
    changed_vertices = 0
    shared_meshes = set()
    for index, node in enumerate(data['nodes']):
        if 'mesh' not in node or 'skin' not in node:
            continue
        mesh = node['mesh']
        if mesh_instances[mesh] > 1:
            shared_meshes.add(mesh)
            continue
        joints = data['skins'][node['skin']]['joints']
        local = {joint: slot for slot, joint in enumerate(joints)}
        destinations = np.arange(len(joints))
        attachments = np.zeros((len(joints), 3))
        margins = np.zeros(len(joints))
        for joint, (bell, attachment, margin) in poses.items():
            slot = local[joint]
            destinations[slot] = local[bell]
            attachments[slot] = attachment
            margins[slot] = margin
        for primitive in data['meshes'][mesh]['primitives']:
            attributes = primitive['attributes']
            if 'JOINTS_0' not in attributes or 'WEIGHTS_0' not in attributes or 'WEIGHTS_1' in attributes:
                raise ValueError('Jellyfish swimming requires up to four skin weights per vertex.')
            positions = accessor(data, binary, attributes['POSITION'])
            if not len(positions):
                continue
            indices = accessor(data, binary, attributes['JOINTS_0']).astype(int)
            weights = accessor(data, binary, attributes['WEIGHTS_0']).astype(float)
            transform = world[index]
            positions = positions @ transform[:3, :3].T + transform[:3, 3]
            j, w, count = corrected_weights(positions, indices, weights, destinations, attachments, margins)
            if count:
                attributes['JOINTS_0'] = append_joint_indices(data, prepared, j)
                attributes['WEIGHTS_0'] = append_access(data, prepared, w, 'VEC4')
                weight_view = data['accessors'][attributes['WEIGHTS_0']]['bufferView']
                data['bufferViews'][weight_view]['target'] = 34962
                changed_vertices += count
    if changed_vertices or source.resolve() != Path(destination_path).resolve():
        _write_atomic(destination_path, data, prepared)
    return {'stabilized_vertices': changed_vertices, 'skipped_shared_meshes': len(shared_meshes)}
