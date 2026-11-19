"""Local fixed-mesh material refinement, isolated from the generation worker."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ENCODER = 'ckpts/shape_enc_next_dc_f16c32_fp16'
ENCODER_FILES = {
    '.json': (653, '5a960a5c419d70f8d4a7a6b6e52ae689cd948c88bd7ed92346adfbf82cd12007'),
    '.safetensors': (708797208, 'f37c5ff5b983b68e9946060000f09bc131f3e84318a2c8b7430a81e4b4636c41'),
}
MATERIAL_MODELS = ('tex_slat_decoder', 'tex_slat_flow_model_1024')
MATERIAL_RESOLUTION = 1024


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pipeline_config(root, *, verify_encoder=False):
    source = (Path(root) / 'models' / 'trellis2').resolve()
    config = json.loads((source / 'pipeline.json').read_text(encoding='utf-8'))
    entries = config['args']['models']
    selected = dict(shape_slat_encoder=ENCODER, **{key: entries[key] for key in MATERIAL_MODELS})
    for name, value in selected.items():
        prefix = (source / value).resolve()
        if not prefix.is_relative_to(source):
            raise ValueError('Material weights must be installed in the local TRELLIS.2 model directory.')
        for suffix, (size, digest) in ENCODER_FILES.items():
            file = Path(str(prefix) + suffix)
            if not file.is_file():
                raise ValueError('Install the local TRELLIS.2 shape encoder and 1024 material weights.')
            if name == 'shape_slat_encoder' and (file.stat().st_size != size
                    or verify_encoder and file_sha(file) != digest):
                raise ValueError('The installed TRELLIS.2 shape encoder does not match the verified version.')
        selected[name] = str(prefix)
    config['args']['models'] = selected
    config['args']['low_vram'] = True
    return config


def availability(root):
    try:
        pipeline_config(root)
    except ValueError as error:
        if isinstance(error, json.JSONDecodeError):
            return dict(available=False, reason='The installed TRELLIS.2 model configuration is invalid.')
        return dict(available=False, reason=str(error))
    except (OSError, TypeError, KeyError):
        return dict(available=False, reason='Install the local TRELLIS.2 shape encoder and 1024 material weights.')
    return dict(available=True, reason='')


def checked_recipe(texture_size, seed, sampler):
    steps = sampler['steps']
    guidance = sampler['guidance_strength']
    rescale = sampler['guidance_rescale']
    rescale_t = sampler['rescale_t']
    if (type(texture_size) is not int or texture_size not in (1024, 2048, 4096)
            or type(seed) is not int or not 0 <= seed <= 2147483647
            or type(steps) is not int or not 1 <= steps <= 50
            or not all(type(value) in (float, int) and math.isfinite(value) for value in (guidance, rescale, rescale_t))
            or not (0 <= guidance <= 10 and 0 <= rescale <= 1 and 1 <= rescale_t <= 6)):
        raise ValueError('Invalid material refinement settings.')
    return dict(texture_size=texture_size, seed=seed, sampler=dict(
        steps=steps, guidance_strength=guidance, guidance_rescale=rescale, rescale_t=rescale_t))


def run_material_worker(command, cwd, timeout=1200):
    import psutil

    with subprocess.Popen(command, cwd=cwd, stdout=sys.stdout, stderr=subprocess.STDOUT,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # The Windows venv executable can be a launcher for a second process.
            try:
                children = psutil.Process(process.pid).children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                children = []
            for child in reversed(children):
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            process.kill()
            process.wait()
            psutil.wait_procs(children, timeout=5)
            raise


def retexture(root, model, reference, texture_size, seed, sampler):
    """Replace a finished GLB only after the child verifies its geometry and materials."""
    recipe = checked_recipe(texture_size, seed, sampler)
    root, model, reference = (Path(path).resolve() for path in (root, model, reference))
    if not reference.is_file():
        raise ValueError('The saved TRELLIS.2 conditioning image is missing.')
    initial_hash = file_sha(model)
    with TemporaryDirectory(prefix='.materials-', dir=model.parent) as directory:
        work = Path(directory)
        (work / 'recipe.json').write_text(json.dumps(recipe), encoding='utf-8')
        try:
            returncode = run_material_worker([
                sys.executable, '-I', '-B', '-u', '-X', 'utf8',
                str(root / 'retexture_worker.py'), str(model), str(reference), str(work),
            ], cwd=root / 'engine')
        except subprocess.TimeoutExpired as error:
            raise ValueError('Material refinement timed out.') from error
        except OSError as error:
            raise ValueError('Unable to start the material refinement worker.') from error
        if returncode == 2:
            raise ValueError('Material refinement exceeded available GPU memory.')
        if returncode:
            raise ValueError('Material refinement failed. See the generation log for details.')
        try:
            report = json.loads((work / 'result.json').read_text(encoding='utf-8'))
            output = work / 'output.glb'
            if (report['geometry_binary_unchanged'] is not True or report['input_sha256'] != initial_hash
                    or report['output_sha256'] != file_sha(output) or initial_hash != file_sha(model)):
                raise ValueError('Material refinement returned an invalid result.')
            output.replace(model)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError('Material refinement could not verify and save its result.') from error
    return dict(state='done', **report)
