"""Verify the final GLB still represents the edited creature and its skin."""
import numpy as np

from glb_data import accessor, node_transforms, read


def verify_creature(path, bones):
    data, binary = read(path)
    nodes = data.get('nodes', [])
    skins = data.get('skins', [])
    if len(skins) != 1:
        raise ValueError('The creature export must have exactly one skin.')
    joint_indices = skins[0]['joints']
    indices = {nodes[index].get('name'): index for index in joint_indices}
    if len(joint_indices) != len(bones) or indices.keys() != {bone['name'] for bone in bones}:
        raise ValueError('The creature export changed the requested bone names or count.')

    parents, matrix = node_transforms(data)
    skin_joints = set(joint_indices)
    extent = np.ptp([point for bone in bones for point in (bone['head'], bone['tail'])], axis=0)
    tolerance = max(1e-5, float(max(extent)) * .003)
    max_error = 0.
    for bone in bones:
        index = indices[bone['name']]
        parent = parents.get(index)
        actual_parent = nodes[parent].get('name') if parent in skin_joints else None
        if actual_parent != bone['parent']:
            raise ValueError(f'The creature export changed the parent of {bone["name"]}.')
        error = float(np.linalg.norm(matrix(index)[:3, 3] - bone['head']))
        if not np.isfinite(error) or error > tolerance:
            raise ValueError(f'The creature export moved joint {bone["name"]} away from its edited position.')
        max_error = max(max_error, error)

    weights_used = np.zeros(len(joint_indices), dtype=bool)
    vertex_count = 0
    for node in nodes:
        if 'mesh' not in node:
            continue
        if node.get('skin') != 0:
            raise ValueError('A creature mesh was exported without skin weights.')
        for primitive in data['meshes'][node['mesh']]['primitives']:
            attributes = primitive['attributes']
            if not {'JOINTS_0', 'WEIGHTS_0'} <= attributes.keys() or 'WEIGHTS_1' in attributes:
                raise ValueError('The creature must use up to four skin weights per vertex.')
            assignments = accessor(data, binary, attributes['JOINTS_0']).astype(int)
            weights = accessor(data, binary, attributes['WEIGHTS_0'])
            vertex_count += len(weights)
            if (weights.shape != assignments.shape or not np.isfinite(weights).all()
                    or (weights < 0).any() or not np.allclose(weights.sum(axis=1), 1., atol=.001)
                    or (assignments < 0).any() or (assignments >= len(joint_indices)).any()):
                raise ValueError('The creature has invalid or unweighted vertices.')
            weights_used[assignments[weights > 0]] = True
    if not vertex_count:
        raise ValueError('The creature export has no skinned vertices.')

    return dict(
        joint_count=len(bones), vertices_checked=vertex_count, max_joint_error_m=max_error,
        unweighted_bones=[nodes[index]['name'] for index, used in zip(joint_indices, weights_used) if not used],
    )
