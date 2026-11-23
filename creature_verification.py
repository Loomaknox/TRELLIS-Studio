"""Verify the final GLB still represents the edited creature and its skin."""
import numpy as np

from glb_data import accessor, read


def node_transforms(data):
    """Evaluate the exported rest hierarchy without importing Blender or SciPy."""
    nodes = data.get('nodes', [])
    parents, world, active = {}, {}, set()
    for index, node in enumerate(nodes):
        for child in node.get('children', []):
            if type(child) is not int or not 0 <= child < len(nodes) or child in parents:
                raise ValueError('The creature export has an invalid node hierarchy.')
            parents[child] = index

    def matrix(index):
        if index in world:
            return world[index]
        if index in active:
            raise ValueError('The creature export has a cyclic node hierarchy.')
        active.add(index)
        node = nodes[index]
        if 'matrix' in node:
            local = np.asarray(node['matrix'], dtype=float).reshape(4, 4).T
        else:
            x, y, z, w = node.get('rotation', [0, 0, 0, 1])
            local = np.eye(4)
            local[:3, :3] = np.array([
                [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
            ]) @ np.diag(node.get('scale', [1, 1, 1]))
            local[:3, 3] = node.get('translation', [0, 0, 0])
        if not np.isfinite(local).all():
            raise ValueError('The creature export has a non-finite node transform.')
        world[index] = matrix(parents[index]) @ local if index in parents else local
        active.remove(index)
        return world[index]

    return parents, matrix


def verify_creature(path, bones):
    data, binary = read(path)
    nodes = data.get('nodes', [])
    skins = data.get('skins', [])
    if len(skins) != 1:
        raise ValueError('The creature export must have exactly one skin.')
    joint_indices = skins[0]['joints']
    if (len(set(joint_indices)) != len(joint_indices)
            or any(type(index) is not int or not 0 <= index < len(nodes) for index in joint_indices)):
        raise ValueError('The creature export has invalid skin joint indices.')
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
            if (not {'POSITION', 'JOINTS_0', 'WEIGHTS_0'} <= attributes.keys()
                    or {'JOINTS_1', 'WEIGHTS_1'} & attributes.keys()):
                raise ValueError('The creature must use up to four skin weights per vertex.')
            if data['accessors'][attributes['JOINTS_0']]['componentType'] not in (5121, 5123):
                raise ValueError('The creature skin joint indices must use unsigned integers.')
            assignments = accessor(data, binary, attributes['JOINTS_0']).astype(int)
            weights = accessor(data, binary, attributes['WEIGHTS_0'])
            vertex_count += len(weights)
            if (weights.shape != assignments.shape or weights.ndim != 2 or weights.shape[1] != 4
                    or len(weights) != data['accessors'][attributes['POSITION']]['count']
                    or not np.isfinite(weights).all()
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
