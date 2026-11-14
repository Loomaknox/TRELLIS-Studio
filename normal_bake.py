"""Bake a tangent-space normal map for a finished variant of a decoded master."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

from glb_data import accessor, read
from normal_glb import embed_normal_map
from studio_import import find_blender


def checked_normalization(value):
    """Validate an exporter transform without coercing malformed provenance."""
    if not isinstance(value, dict) or value.get('coordinate_system') != 'y_up':
        raise ValueError('The selected HD model has no compatible saved normalization. Create a new finishing variant or choose the decoded source.')
    scale, translation = value.get('scale'), value.get('translation')
    if (type(scale) not in (int, float) or not np.isfinite(scale) or scale <= 0
            or not isinstance(translation, (list, tuple)) or len(translation) != 3
            or any(type(number) not in (int, float) or not np.isfinite(number) for number in translation)):
        raise ValueError('The selected HD model has invalid normalization provenance.')
    return dict(scale=float(scale), translation=[float(number) for number in translation], coordinate_system='y_up')


def has_parent_normal_provenance(result):
    """Cheap capability check; submission still validates the complete artifact."""
    if not isinstance(result, dict) or not isinstance(result.get('finishing'), dict):
        return False
    try:
        finishing = result['finishing']
        checked_normalization(finishing.get('normalization'))
        return isinstance(finishing.get('model_sha256'), str) and bool(re.fullmatch(r'[a-f0-9]{64}', finishing['model_sha256']))
    except (ValueError, KeyError, TypeError):
        return False


def parent_normal_capability(result):
    """Describe provenance availability without loading a large donor on each UI refresh."""
    finishing = result.get('finishing') if isinstance(result, dict) else None
    try:
        checked_normalization(finishing.get('normalization') if isinstance(finishing, dict) else None)
        if not has_parent_normal_provenance(result):
            raise ValueError('This model has no verified export fingerprint. Create a new finishing variant to use it as an HD donor.')
    except ValueError as error:
        return dict(available=False, unavailable_reason=str(error))
    return dict(available=True, unavailable_reason=None)


def _parent_normal_data(output_directory, identifier, decoded_source_id):
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        raise ValueError('Choose a valid HD model from this collection.')
    root = Path(output_directory).resolve()
    folder = root / identifier
    paths = [folder / name for name in ('result.json', 'model.glb', 'status.json')]
    if folder.is_symlink() or folder.resolve().parent != root or any(
            path.is_symlink() or path.resolve().parent != folder.resolve() for path in paths):
        raise ValueError('The selected HD model is outside this collection.')
    try:
        result = json.loads(paths[0].read_text(encoding='utf-8'))
        status = json.loads(paths[2].read_text(encoding='utf-8'))
        if not isinstance(result, dict) or not isinstance(status, dict):
            raise ValueError('The selected HD donor has invalid provenance.')
        if status.get('state') != 'done':
            raise ValueError('Wait for the selected HD model to finish.')
        if result.get('finish_source_id', identifier) != decoded_source_id:
            raise ValueError('The HD model and target must share the same decoded source.')
        finishing = result.get('finishing', {})
        if not isinstance(finishing, dict):
            raise ValueError('The selected HD donor has invalid finishing provenance.')
        normalization = checked_normalization(finishing.get('normalization'))
        if not has_parent_normal_provenance(result):
            raise ValueError('The selected HD model has no verified export fingerprint. Create a new finishing variant or choose the decoded source.')
        with paths[1].open('rb') as stream:
            fingerprint = hashlib.file_digest(stream, 'sha256').hexdigest()
        if fingerprint != finishing['model_sha256']:
            raise ValueError('The HD model changed after its normalization was recorded. Create a new finishing variant or choose the decoded source.')
        document, binary = read(paths[1])
        if len(document.get('meshes', [])) != 1 or document.get('skins') or document.get('animations'):
            raise ValueError('Choose a static, single-mesh HD finishing model as the normal donor.')
        primitives = document['meshes'][0]['primitives']
        if len(primitives) != 1 or primitives[0].get('mode', 4) != 4 or primitives[0].get('targets'):
            raise ValueError('The HD donor must contain one static triangle primitive.')
        mesh_nodes = 0
        for node in document.get('nodes', []):
            if 'mesh' in node:
                mesh_nodes += 1
                if node['mesh'] != 0:
                    raise ValueError('The HD donor has unsupported mesh instances.')
            for name, identity in (('matrix', np.eye(4).ravel()), ('translation', [0, 0, 0]),
                                   ('rotation', [0, 0, 0, 1]), ('scale', [1, 1, 1])):
                if name in node and not np.array_equal(np.asarray(node[name]), np.asarray(identity)):
                    raise ValueError('The HD donor has transformed nodes. Choose an unmodified finishing model.')
        if mesh_nodes != 1:
            raise ValueError('The HD donor must contain one mesh instance.')
        primitive = primitives[0]
        positions = accessor(document, binary, primitive['attributes']['POSITION'])
        normals = accessor(document, binary, primitive['attributes']['NORMAL'])
        corners = accessor(document, binary, primitive['indices']).reshape(-1, 3)
        if (positions.ndim != 2 or positions.shape[1] != 3 or normals.shape != positions.shape
                or not len(corners) or corners.dtype.kind not in ('i', 'u')
                or corners.min() < 0 or corners.max() >= len(positions)
                or not np.isfinite(positions).all() or not np.isfinite(normals).all()
                or (np.linalg.norm(normals, axis=1) < .1).any()):
            raise ValueError('The HD donor has invalid positions, normals or triangles.')
        with paths[1].open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != fingerprint:
                raise ValueError('The HD model changed during validation. Retry after editing finishes.')
    except OSError as error:
        raise ValueError('The selected HD donor is unavailable. Restore it or choose the decoded source.') from error
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError('The selected HD donor has incomplete geometry or provenance.') from error
    info = dict(kind='parent', id=identifier, model_sha256=fingerprint, normalization=normalization,
                decoded_source_id=decoded_source_id)
    return dict(vertices=positions, faces=corners, vertex_normals=normals), info


def inspect_parent_normal_source(output_directory, identifier, decoded_source_id):
    """Check and fingerprint a library-scoped donor before queuing a variant."""
    _, info = _parent_normal_data(output_directory, identifier, decoded_source_id)
    return info


def prepare_parent_normal_source(output_directory, identifier, decoded_source_id, target_normalization,
                                 voxel_size, expected_fingerprint, expected_normalization):
    """Remap a verified HD donor into the exact target frame; no geometry is rewritten."""
    source, info = _parent_normal_data(output_directory, identifier, decoded_source_id)
    if info['model_sha256'] != expected_fingerprint or info['normalization'] != checked_normalization(expected_normalization):
        raise ValueError('The selected HD donor changed after this variant was queued.')
    target = checked_normalization(target_normalization)
    parent = info['normalization']
    ratio = target['scale'] / parent['scale']
    offset = np.asarray(target['translation']) - ratio * np.asarray(parent['translation'])
    source['vertices'] = (source['vertices'].astype(np.float64) * ratio + offset).astype(np.float32)
    source['faces'] = source['faces'].astype(np.int32)
    source['vertex_normals'] = source['vertex_normals'].astype(np.float32)
    source['voxel_size'] = float(np.min(voxel_size)) * target['scale']
    source['coordinate_system'] = 'y_up'
    if not np.isfinite(source['vertices']).all() or not np.isfinite(source['voxel_size']) or source['voxel_size'] <= 0:
        raise ValueError('The HD donor transform or voxel size is invalid.')
    return source, dict(info, target_normalization=target, alignment='exact saved export transforms')


def cpu_array(value):
    return value.detach().cpu().numpy() if hasattr(value, 'detach') else np.asarray(value)


def bake_master_normals(destination, source, scale, translation, texture_size):
    blender = find_blender()
    if blender is None:
        raise RuntimeError("Install Blender to bake detail from the master, or retry without the normal map.")

    document, binary = read(destination)
    primitive, = document["meshes"][0]["primitives"]
    attributes = {key: accessor(document, binary, index)
                  for key, index in primitive["attributes"].items()}
    corners = accessor(document, binary, primitive["indices"]).reshape(-1, 3)
    voxel_m = float(np.min(source["voxel_size"])) * scale
    if not np.isfinite(voxel_m) or voxel_m <= 0:
        raise ValueError("The saved master has an invalid voxel size for normal baking.")
    script = Path(__file__).with_name("normal_bake_blender.py")
    with TemporaryDirectory(prefix=".normal-bake-", dir=destination.parent) as temporary:
        directory = Path(temporary)
        np.save(directory / "master-positions.npy", cpu_array(source['vertices']), allow_pickle=False)
        np.save(directory / "master-faces.npy", cpu_array(source['faces']), allow_pickle=False)
        if 'vertex_normals' in source:
            np.save(directory / 'master-normals.npy', cpu_array(source['vertex_normals']), allow_pickle=False)
        np.savez(directory / "bake-input.npz", positions=attributes["POSITION"],
                 normals=attributes["NORMAL"], uv=attributes["TEXCOORD_0"], faces=corners,
                 scale=scale, translation=translation, voxel_m=voxel_m,
                 master_y_up=source.get("coordinate_system") == "y_up")
        command = [str(blender), "--background", "--factory-startup", "--disable-autoexec",
                   "--python-exit-code", "1", "--python", str(script), "--", str(directory), str(texture_size)]
        try:
            subprocess.run(command, check=True, timeout=600, stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.CalledProcessError as error:
            raise RuntimeError("Blender could not bake the normal map. See the job log for details.") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Normal baking timed out. Retry with a smaller texture size or triangle target.") from error
        report = embed_normal_map(destination, document, binary, primitive, attributes, corners,
                                  np.load(directory / "tangents.npy", allow_pickle=False),
                                  directory / "unfiltered.png")
    return dict(report, state="applied", source_triangles=len(source["faces"]))
