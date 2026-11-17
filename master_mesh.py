"""Headless Blender trim and pre-UV diagnostics for dense cached meshes."""

import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np

from studio_import import find_blender


def edge_counts(faces, vertex_count):
    edges = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        first, second = faces[:, i], faces[:, j]
        edges.append(np.minimum(first, second).astype(np.uint64) * vertex_count + np.maximum(first, second).astype(np.uint64))
    _, counts = np.unique(np.concatenate(edges), return_counts=True)
    return dict(boundary_edges=int(np.count_nonzero(counts == 1)), nonmanifold_edges=int(np.count_nonzero(counts > 2)))


def master_topology(vertices, faces):
    indexed = edge_counts(faces, len(vertices))
    welded, mapping = np.unique(vertices, axis=0, return_inverse=True)
    return dict(indexed=indexed, position_welded=edge_counts(mapping[faces], len(welded)),
                vertex_count=len(vertices), unique_positions=len(welded))


def trim_wtivo_master(root, job, vertices, faces, cap):
    """Collapse toward the ceiling without rebuilding the indexed WTiVo surface."""
    if len(faces) <= cap:
        return vertices, faces, dict(method='none', input_triangles=len(faces), output_triangles=len(faces))
    blender = find_blender()
    if not blender:
        raise ValueError('Install Blender for WTiVo HD Master Finishing or choose Studio 768.')
    bytes_required = vertices.nbytes + faces.nbytes + cap * 24 + 32 * 1024**2
    if shutil.disk_usage(job).free < bytes_required:
        raise ValueError('Free disk space for the Blender master trim or choose Studio 768.')

    started = perf_counter()
    with TemporaryDirectory(prefix='.master-trim-', dir=job) as work:
        work = Path(work)
        source, output = work / 'source.npz', work / 'trimmed.npz'
        np.savez(source, vertices=vertices, faces=faces)
        command = [str(blender), '--background', '--factory-startup', '--disable-autoexec', '--threads', '6',
                   '--python-exit-code', '1', '--python', str(root / 'master_mesh_blender.py'),
                   '--', str(source), str(output), str(cap)]
        try:
            process = subprocess.run(command, cwd=work, timeout=900, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8', errors='replace',
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                     env={**os.environ, 'TEMP': str(work), 'TMP': str(work)})
        except subprocess.TimeoutExpired as error:
            raise ValueError('Blender timed out while trimming the master. Try Studio 768.') from error
        except OSError as error:
            raise ValueError('Unable to start Blender for the master trim.') from error
        print(process.stdout.replace(str(work), work.name).replace(work.as_posix(), work.name), flush=True)
        if process.returncode != 0 or not output.is_file():
            raise ValueError('Blender could not trim this master. Check the log or try Studio 768.')
        with np.load(output, allow_pickle=False) as saved:
            trim_vertices, trim_faces = saved['vertices'], saved['faces']

    if (trim_vertices.ndim != 2 or trim_vertices.shape[1] != 3 or trim_faces.ndim != 2 or trim_faces.shape[1] != 3
            or trim_vertices.dtype != np.float32 or trim_faces.dtype != np.int32
            or not len(trim_vertices) or not 0 < len(trim_faces) <= cap or not np.isfinite(trim_vertices).all()
            or trim_faces.min() < 0 or trim_faces.max() >= len(trim_vertices)):
        raise ValueError('Blender returned invalid master geometry.')
    margin = 4 / 1024
    if (np.any(trim_vertices.min(axis=0) < vertices.min(axis=0) - margin)
            or np.any(trim_vertices.max(axis=0) > vertices.max(axis=0) + margin)):
        raise ValueError('The Blender trim exceeded the reconstructed master bounds.')
    return trim_vertices, trim_faces, dict(method='Blender Decimate Collapse', input_triangles=len(faces),
                                           output_triangles=len(trim_faces), seconds=round(perf_counter() - started, 3))
