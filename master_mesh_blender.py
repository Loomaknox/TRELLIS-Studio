"""Trim triangular dense geometry with Blender's topology-aware Collapse modifier."""

from pathlib import Path
import sys

import bpy
import numpy as np


def trim(source, output, cap):
    with np.load(source, allow_pickle=False) as saved:
        vertices, faces = saved['vertices'], saved['faces']
    mesh = bpy.data.meshes.new('Reconstructed surface')
    mesh.vertices.add(len(vertices))
    mesh.vertices.foreach_set('co', vertices.ravel())
    mesh.loops.add(faces.size)
    mesh.loops.foreach_set('vertex_index', faces.ravel())
    mesh.polygons.add(len(faces))
    mesh.polygons.foreach_set('loop_start', np.arange(0, faces.size, 3, dtype=np.int32))
    mesh.update(calc_edges=True)
    ratio = min(1.0, cap / len(faces))
    del vertices, faces

    obj = bpy.data.objects.new('HD master', mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    modifier = obj.modifiers.new('HD master trim', 'DECIMATE')
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)

    mesh = obj.data
    if len(mesh.loops) != 3 * len(mesh.polygons):
        raise ValueError('The master trim must produce triangles.')
    vertices = np.empty((len(mesh.vertices), 3), dtype=np.float32)
    faces = np.empty((len(mesh.polygons), 3), dtype=np.int32)
    mesh.vertices.foreach_get('co', vertices.ravel())
    mesh.loops.foreach_get('vertex_index', faces.ravel())
    np.savez(output, vertices=vertices, faces=faces)


if __name__ == '__main__':
    source, output, cap = sys.argv[sys.argv.index('--') + 1:]
    trim(Path(source), Path(output), int(cap))
