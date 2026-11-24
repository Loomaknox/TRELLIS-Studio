"""Run the optional, local UltraTex experiment in a separate process."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

from retexture_runtime import file_sha


TEXTURE_SIZE = 2048
VIEW_SIZE = 1024
VIEW_COUNT = 6
STEPS = 25
LICENSE = 'FLUX Non-Commercial License v2.1'
LICENSE_URL = ('https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B/'
               'blob/8e4154e4c94c6eb08644d0761d404e1c28d325c2/LICENSE.md')
REVISIONS = {
    'comfy': '0decb39ee5b5e17c200334589fc317dbbe98310e',
    'gguf': '6ea2651e7df66d7585f6ffee804b20e92fb38b8a',
    'ultratex': '8b3715605fa5f08d4de7f858d3ba8c16f94e7b0c',
}
WEIGHTS = {
    'diffusion_models/flux-2-klein-base-9b-Q4_0.gguf':
        (5616228640, '02d4c2b55b5a6d4aca65eafd0f0eabe8c1e3837391042b6879be04eb99c7e116'),
    'text_encoders/Qwen3-8B-Q6_K.gguf':
        (6725900096, '0eaec718fdeab0f429dfa0ec481c090388811f5e63785ddb582292f4ef3c3827'),
    'vae/flux2-vae.safetensors':
        (336213556, 'd64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5'),
    'loras/ultratex_flux2.safetensors':
        (478172752, '3b1915177a81bc2ab43f501355bf39113df0128e6cbc6fedf8b8621d5e06a01c'),
    'loras/ultratex_flux2_mr.safetensors':
        (478172752, '13e94f5a30a789b1e3e76d8c96cbba5f52fb2f68411e56377f382e145da23fc1'),
    'ultratex/ultratex_flux2_decoder.pt':
        (99261764, '981dc4c52481687c6da4e6211617615a2b2bcc33456e1953ee6c5478aa00025b'),
}
STAGES = {
    'albedo': ('Generating six UltraTex albedo views', 96),
    'materials': ('Generating six UltraTex material views', 97),
    'bake': ('Baking UltraTex materials onto the existing UVs', 99),
}


def require_applied_transforms(document):
    if any(key in node for node in document.get('nodes', []) for key in
           ('matrix', 'translation', 'rotation', 'scale')):
        raise ValueError('Apply object transforms before using the UltraTex 2K preview.')


def validated_runtime(root, *, verify_weights=False):
    runtime = Path(root) / 'models' / 'ultratex'
    missing = 'Install the optional UltraTex local preview runtime.'
    try:
        config = json.loads((runtime / 'runtime.json').read_text(encoding='utf-8'))
        if config.get('schema') != 1 or config.get('revisions') != REVISIONS:
            raise ValueError('The optional UltraTex runtime has an unsupported revision.')
        if not all((runtime / path).is_file() for path in (
            'ComfyUI/comfy/options.py', 'ComfyUI/nodes.py', 'comfy-deps/comfy_kitchen/__init__.py',
            'repos/UltraTex/simple.py', 'repos/ComfyUI-GGUF/nodes.py', 'deps/gguf/__init__.py',
        )):
            raise ValueError(missing)
        for name, (size, digest) in WEIGHTS.items():
            path = runtime / name
            if path.stat().st_size != size or (verify_weights and file_sha(path) != digest):
                raise ValueError('An installed UltraTex weight file does not match the verified runtime.')
    except (OSError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError(missing) from error
    return runtime


def availability(root):
    report = dict(available=False, reason='', local_only=True, license=LICENSE, license_url=LICENSE_URL,
                  texture_sizes=[TEXTURE_SIZE], view_count=VIEW_COUNT, steps=STEPS)
    try:
        validated_runtime(root)
    except ValueError as error:
        report['reason'] = str(error)
        report['reason_code'] = 'incomplete' if (Path(root) / 'models' / 'ultratex').is_dir() else 'not_installed'
    else:
        report['available'] = True
    return report


def stop_worker(process):
    import psutil

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


def run_worker(root, model, reference, work, seed, progress, cancelled):
    command = [sys.executable, '-I', '-B', '-u', '-X', 'utf8', '-X', f'pycache_prefix={work / "bytecode"}',
               str(root / 'ultratex_worker.py'), str(model), str(reference), str(work), str(seed)]
    with subprocess.Popen(command, cwd=work, stderr=subprocess.STDOUT,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
        deadline = monotonic() + 1200
        previous = None
        try:
            while process.poll() is None:
                if cancelled():
                    return None
                if monotonic() >= deadline:
                    raise ValueError('The UltraTex pass timed out.')
                try:
                    stage = (work / 'stage.txt').read_text(encoding='utf-8').strip()
                except OSError:
                    stage = None
                if stage != previous and stage in STAGES:
                    progress(*STAGES[stage])
                    previous = stage
                try:
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    pass
            return process.returncode
        finally:
            if process.poll() is None:
                stop_worker(process)


def refine(root, model, reference, texture_size, seed, *, progress=None, cancelled=None):
    """Publish an UltraTex GLB only after verifying the unchanged geometry and UVs."""
    root, model, reference = (Path(path).resolve() for path in (root, model, reference))
    progress = progress or (lambda message, percentage: None)
    cancelled = cancelled or (lambda: False)
    if type(texture_size) is not int or texture_size != TEXTURE_SIZE:
        return dict(state='skipped', reason='UltraTex currently supports a 2K atlas.')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        return dict(state='skipped', reason='Choose a valid UltraTex seed.')
    capability = availability(root)
    if not capability['available']:
        return dict(state='skipped', reason=capability['reason'])
    if not model.is_file() or not reference.is_file():
        return dict(state='skipped', reason='UltraTex requires the finished GLB and a prepared reference image.')
    if cancelled():
        return dict(state='cancelled', reason='UltraTex was cancelled.')
    try:
        source_hash, reference_hash = file_sha(model), file_sha(reference)
        with TemporaryDirectory(prefix='.ultratex-', dir=model.parent, ignore_cleanup_errors=True) as temporary:
            work = Path(temporary)
            progress('Preparing the fixed surface for UltraTex', 95)
            status = run_worker(root, model, reference, work, seed, progress, cancelled)
            if status is None or cancelled():
                return dict(state='cancelled', reason='UltraTex was cancelled.')
            if status != 0:
                report_file = work / 'error.json'
                report = json.loads(report_file.read_text(encoding='utf-8')) if report_file.is_file() else {}
                raise ValueError(report.get('reason', 'The UltraTex pass failed. See the generation log.'))
            report = json.loads((work / 'result.json').read_text(encoding='utf-8'))
            output = work / 'output.glb'
            if (report.get('geometry_uv_equal') is not True or report.get('source_sha256') != source_hash
                    or report.get('reference_sha256') != reference_hash or report.get('atlas') != [TEXTURE_SIZE] * 2
                    or report.get('output_sha256') != file_sha(output)
                    or source_hash != file_sha(model) or reference_hash != file_sha(reference)):
                raise ValueError('UltraTex could not verify the geometry, reference, or result.')
            if cancelled():
                return dict(state='cancelled', reason='UltraTex was cancelled.')
            output.replace(model)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'UltraTex: {error}', flush=True)
        reason = str(error) if isinstance(error, ValueError) else 'UltraTex could not save the texture. See the generation log.'
        return dict(state='skipped', reason=reason)
    report['state'] = 'applied'
    report['revisions'] = dict(REVISIONS)
    return report
