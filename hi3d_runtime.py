"""Bridge to the optional, locally provisioned Windows Hi3D runtime."""

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import perf_counter


HI3D_METHODS = {'hi3d_512': 512, 'hi3d_1024': 1024}
# TRELLIS.2 may lower its 1536 cascade grid in 128-voxel steps to fit its token budget.
_SOURCE_DECODED_RESOLUTIONS = {512: (512,), 1024: (1024,), 1536: range(1024, 1537, 128)}
HI3D_PORT_REVISION = '03dea7e366ba951d7475f3f1c8a71596a87f913c'
HI3D_WEIGHT_REVISION = '23d1bace196f618265b4b0b9c90d95fa9a9b1df5'
HI3D_PORT_PYTHON_SHA256 = 'adeda18e23db59c66b34b63ecc2e7882191dd2c7a843c9a83baff77a835afdd9'
HI3D_SEED = 42
HI3D_STEPS = 25
HI3D_VOXEL_TOKENS = 90_000
HI3D_TRIANGLE_CAP = 1_000_000
HI3D_MAX_HOLE_EDGES = 10_000
HI3D_FLOATER_FACE_RATIO = 0.005
REQUIRED_PACKAGES = {'spconv-cu124': '2.3.8', 'cumm-cu124': '0.8.2', 'pyfqmr': '0.5.0'}
RUNTIME_HINT = 'Configure the optional local Hi3D component.'
SOURCE_HINT = 'Hi3D requires a native TRELLIS.2 single-image source with its prepared transparent cutout.'
OUTPUT_LIMIT_BYTES = 256 * 1024**2
WEIGHT_FILES = {
    'Hi3Dv1.0/transformer_512/model.safetensors': 3675679280,
    'Hi3Dv1.0/transformer_1024/model.safetensors': 3675679280,
    'Hi3Dv1.0/vae/model.safetensors': 376629712,
    'dinov2-large/model.safetensors': 1217522888,
    'clip-vit-large-patch14/model.safetensors': 1710540580,
    'Hi3Dv1.0/model_index.json': 224,
    'Hi3Dv1.0/scheduler/scheduler_config.json': None,
    'Hi3Dv1.0/transformer_512/config.json': 1336,
    'Hi3Dv1.0/transformer_1024/config.json': 1337,
    'Hi3Dv1.0/vae/config.json': 131,
    'dinov2-large/config.json': 549,
    'dinov2-large/preprocessor_config.json': 436,
    'clip-vit-large-patch14/config.json': 4519,
    'clip-vit-large-patch14/preprocessor_config.json': 316,
}


@dataclass(frozen=True)
class Runtime:
    python: Path
    source: Path
    weights: Path
    dependencies: tuple[Path, ...]


def _status(available, reason=''):
    return {'available': available, 'reason': reason}


def _read_json(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('The configuration is too large.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Expected a configuration object.')
    return value


def _absolute_path(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('Hi3D runtime paths must be absolute.')
    return Path(value).resolve(strict=True)


def _read_runtime(root):
    if sys.platform != 'win32':
        raise ValueError('The verified Hi3D runtime requires Windows and an NVIDIA CUDA GPU.')
    try:
        config = _read_json(Path(root) / 'config' / 'hi3d-runtime.json', 16 * 1024)
        if set(config) != {'python', 'source', 'weights', 'dependencies'}:
            raise ValueError('Expected Python, source, weights and dependencies paths.')
        dependencies = config['dependencies']
        if not isinstance(dependencies, list):
            raise ValueError('Expected a list of local Hi3D dependency directories.')
        runtime = Runtime(
            python=_absolute_path(config['python']), source=_absolute_path(config['source']),
            weights=_absolute_path(config['weights']), dependencies=tuple(map(_absolute_path, dependencies)),
        )
    except (OSError, ValueError) as error:
        raise ValueError(RUNTIME_HINT) from error
    if runtime.python.name.lower() != 'python.exe' or not runtime.python.is_file():
        raise ValueError('Hi3D requires a local Python executable.')
    if not runtime.source.is_dir() or not (runtime.source / 'hi3d_pipeline.py').is_file():
        raise ValueError('The pinned Hi3D port is missing from the configured source directory.')
    if any(not directory.is_dir() for directory in runtime.dependencies):
        raise ValueError('An optional Hi3D dependency directory is missing.')
    site_packages = 'Lib/site-packages'
    package_roots = [*runtime.dependencies, runtime.python.parent / site_packages,
                     runtime.python.parent.parent / site_packages]
    for name, version in REQUIRED_PACKAGES.items():
        distribution = next(metadata.distributions(name=name, path=package_roots), None)
        if distribution is None or distribution.version != version:
            raise ValueError(f'The optional Hi3D component requires {name} {version}.')
    try:
        for name, expected_size in WEIGHT_FILES.items():
            path = runtime.weights / name
            if not path.is_file() or (expected_size is not None and path.stat().st_size != expected_size):
                raise ValueError('Missing or incomplete pinned model file.')
    except (OSError, ValueError) as error:
        raise ValueError('The optional Hi3D runtime is missing verified model weights or configuration files.') from error
    return runtime


def hi3d_status(root):
    """Check local files without importing PyTorch or waking the GPU."""
    try:
        _read_runtime(root)
    except ValueError as error:
        return _status(False, str(error))
    return _status(True)


def hi3d_source_status(source_folder, source_resolution=None, *, require_cache=True):
    """Check native generation provenance and the prepared image on a trusted source folder."""
    from PIL import Image

    folder = Path(source_folder)
    settings = folder / 'settings.json'
    cache = folder / 'raw_state.pt'
    reference = folder / 'prepared.png'
    try:
        if require_cache and (cache.is_symlink() or not cache.is_file()):
            raise ValueError('Missing native decoded cache.')
        if any(path.is_symlink() for path in (settings, reference)):
            raise ValueError('Invalid native generation files.')
        saved = _read_json(settings, 128 * 1024)
        requested = saved.get('resolution')
        decoded_resolutions = _SOURCE_DECODED_RESOLUTIONS.get(requested, ()) if type(requested) is int else ()
        if (saved.get('engine', 'trellis2') != 'trellis2'
                or saved.get('source_kind') not in (None, 'generation')
                or saved.get('view_mode', 'single') != 'single'
                or not decoded_resolutions
                or (source_resolution is not None
                    and (type(source_resolution) is not int or source_resolution not in decoded_resolutions))):
            raise ValueError('Incompatible native generation.')
        with Image.open(reference) as image:
            if image.format != 'PNG' or image.mode != 'RGBA':
                raise ValueError('A prepared RGBA PNG is required.')
            low, high = image.getchannel('A').getextrema()
        if low == 255 or high == 0:
            raise ValueError('The cutout needs both a visible foreground and transparency.')
    except (OSError, ValueError, Image.DecompressionBombError):
        return _status(False, SOURCE_HINT)
    return _status(True)


def verify_port_source(root):
    """Verify the exact bundled Python code before importing the external port."""
    source = Path(root).resolve()
    candidates = [source / 'hi3d_pipeline.py', source / 'tiled_decode.py']
    candidates.extend((source / 'Hi3D-1.0' / 'sparc3d').rglob('*.py'))
    digest = hashlib.sha256()
    for path in sorted(candidates, key=lambda item: item.relative_to(source).as_posix()):
        if path.resolve(strict=True) != path:
            raise ValueError('Hi3D source files must remain inside the configured checkout.')
        digest.update(path.relative_to(source).as_posix().encode('utf-8') + b'\0')
        digest.update(hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).digest())
    if digest.hexdigest() != HI3D_PORT_PYTHON_SHA256:
        raise ValueError('The Hi3D source does not match the verified port revision.')


def check_mesh(vertices, faces):
    import numpy as np

    if (vertices.ndim != 2 or vertices.shape[1] != 3 or vertices.dtype.kind != 'f'
            or faces.ndim != 2 or faces.shape[1] != 3 or faces.dtype.kind not in 'iu'
            or not len(vertices) or not len(faces) or not np.isfinite(vertices).all()
            or faces.min() < 0 or faces.max() >= len(vertices)
            or float(np.ptp(vertices, axis=0).max()) <= 0):
        raise ValueError('Hi3D requires finite vertices and valid indexed triangles.')


def _run(runtime, work, resolution, triangle_target):
    command = [
        str(runtime.python), '-I', '-B', '-u', '-X', 'utf8',
        str(Path(__file__).resolve().with_name('hi3d_worker.py')),
        '--source', str(runtime.source), '--weights', str(runtime.weights),
        '--resolution', str(resolution), '--triangles', str(triangle_target),
    ]
    for directory in runtime.dependencies:
        command.extend(('--dependency', str(directory)))
    env = {
        **os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
        'CUMM_DISABLE_JIT': '1', 'TEMP': str(work), 'TMP': str(work),
        'HF_HOME': str(work / 'hf'), 'TORCH_HOME': str(work / 'torch'),
        'CUDA_CACHE_PATH': str(work / 'cuda'), 'TRITON_CACHE_DIR': str(work / 'triton'),
    }
    try:
        process = subprocess.run(
            command, cwd=work, env=env, timeout=1800, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError('Hi3D refinement timed out. Choose a smaller refinement resolution.') from error
    except OSError as error:
        raise ValueError('Unable to start the configured Hi3D runtime.') from error
    log = process.stdout
    for path in (work, runtime.source, runtime.weights, runtime.python.parent.parent, *runtime.dependencies):
        log = log.replace(str(path), path.name).replace(path.as_posix(), path.name)
    if log:
        print(log.rstrip(), flush=True)
    if process.returncode == 2 and 'HI3D_GPU_MEMORY_LIMIT' in process.stdout:
        retry = 'Choose Detail Refinement (512) or free GPU memory.' if resolution == 1024 else 'Free GPU memory and retry.'
        raise ValueError(f'Hi3D exceeded available GPU memory. {retry}')
    if process.returncode:
        raise ValueError('Hi3D refinement failed. See the generation log for details.')


def reconstruct(root, job, reference, vertices, faces, resolution, triangle_ceiling, *, source_resolution):
    """Refine a copy and return valid replacement geometry in decoded TRELLIS.2 coordinates."""
    import numpy as np

    if (resolution not in HI3D_METHODS.values() or type(triangle_ceiling) is not int or triangle_ceiling < 1000
            or type(source_resolution) is not int
            or not any(source_resolution in allowed for allowed in _SOURCE_DECODED_RESOLUTIONS.values())):
        raise ValueError('Invalid Hi3D refinement settings.')
    check_mesh(vertices, faces)
    runtime = _read_runtime(root)
    input_bytes = (vertices.size + faces.size) * 4
    if shutil.disk_usage(job).free < input_bytes + OUTPUT_LIMIT_BYTES:
        raise ValueError('Free disk space for the Hi3D working mesh.')
    started = perf_counter()
    ceiling = min(triangle_ceiling, HI3D_TRIANGLE_CAP)
    with TemporaryDirectory(prefix='.hi3d-', dir=job) as directory:
        work = Path(directory)
        np.save(work / 'vertices.npy', np.ascontiguousarray(vertices, dtype=np.float32), allow_pickle=False)
        np.save(work / 'faces.npy', np.ascontiguousarray(faces, dtype=np.int32), allow_pickle=False)
        shutil.copyfile(reference, work / 'source.png')
        _run(runtime, work, resolution, ceiling)
        try:
            v_out, f_out = work / 'refined-vertices.npy', work / 'refined-faces.npy'
            if v_out.stat().st_size + f_out.stat().st_size > OUTPUT_LIMIT_BYTES:
                raise ValueError('The Hi3D result exceeds the mesh size limit.')
            rebuilt_vertices = np.load(v_out, allow_pickle=False)
            rebuilt_faces = np.load(f_out, allow_pickle=False)
            check_mesh(rebuilt_vertices, rebuilt_faces)
            telemetry = _read_json(work / 'result.json', 8 * 1024)
            allocated = float(telemetry['peak_vram_gib'])
            reserved = float(telemetry['peak_reserved_gib'])
            if not np.isfinite([allocated, reserved]).all() or not 0 < allocated <= reserved:
                raise ValueError('Invalid Hi3D memory report.')
        except (OSError, ValueError, EOFError, KeyError, TypeError) as error:
            raise ValueError('Hi3D returned an invalid reconstructed mesh.') from error
    report = dict(
        engine='Hi3D', port_revision=HI3D_PORT_REVISION, weights_revision=HI3D_WEIGHT_REVISION,
        source_resolution=source_resolution, resolution=resolution, steps=HI3D_STEPS, seed=HI3D_SEED,
        scheduler='heun', voxel_token_limit=HI3D_VOXEL_TOKENS, triangle_target=ceiling,
        extracted_triangles=len(rebuilt_faces), fill_holes_max_edges=HI3D_MAX_HOLE_EDGES,
        floater_face_ratio=HI3D_FLOATER_FACE_RATIO, tiled_decode=True, vram_mode='model_swap',
        peak_vram_gib=allocated, peak_reserved_gib=reserved, seconds=round(perf_counter() - started, 3),
    )
    return rebuilt_vertices, rebuilt_faces, report
