"""Run optional texture refinement without changing the generation worker's environment."""
from importlib.util import find_spec
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import traceback

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from multiview_texture_views import validate_runtime
from retexture_runtime import file_sha, retexture, run_material_worker


def availability(root):
    runtime = Path(root) / 'models' / 'multiview-texture'
    if not runtime.is_dir():
        return dict(available=False, reason_code='not_installed', reason='Install the optional multiview texture component.')
    try:
        validate_runtime(runtime)
        if any(find_spec(name) is None for name in ('numba', 'numpy', 'cv2', 'scipy', 'PIL')):
            return dict(available=False, reason_code='dependencies_missing', reason='Install the local CPU texture projection dependencies.')
    except (OSError, ValueError) as error:
        return dict(available=False, reason_code='incomplete', reason=str(error))
    return dict(available=True, reason='')


def supports_single_image(settings):
    return (settings.get('source_kind') != 'refinish'
            and settings.get('engine', 'trellis2') in ('trellis2', 'pixal3d')
            and settings.get('view_mode', 'single') in (None, 'single'))


def run_stage(root, script, *args):
    command = [sys.executable, '-I', '-B', '-u', '-X', 'utf8', str(root / script),
               *(str(arg) for arg in args)]
    if run_material_worker(command, root, timeout=900):
        raise ValueError('A multiview texture stage could not produce a verified result. See the generation log.')


def refine(root, model, reference, progress, *, material_recipe=None):
    """Publish a finished GLB only after every requested texture stage succeeds."""
    root, model, reference = (Path(path).resolve() for path in (root, model, reference))
    capability = availability(root)
    if not capability['available']:
        return dict(state='skipped', reason=capability['reason'])
    if not reference.is_file():
        return dict(state='skipped', reason='The prepared reference image is unavailable.')
    source_hash = file_sha(model)
    reference_hash = file_sha(reference)
    material_report = None
    try:
        with TemporaryDirectory(prefix='.tex-', dir=model.parent, ignore_cleanup_errors=True) as temporary:
            work = Path(temporary)
            donor = model
            if material_recipe:
                donor = work / 'material.glb'
                shutil.copyfile(model, donor)
                progress('Generating materials for the final surface', 95)
                material_report = retexture(root, donor, **material_recipe)
            progress('Aligning the reference for texture refinement', 96)
            run_stage(root, 'multiview_texture_runtime.py', 'prepare', donor, reference, work)
            progress('Generating six geometry-guided texture views', 97)
            run_stage(root, 'multiview_texture_views.py', root / 'models' / 'multiview-texture',
                      reference, work / 'controls.npz', work / 'cameras.json', work / 'views')
            progress('Harmonizing colors and baking the texture', 99)
            output = work / 'result.glb'
            run_stage(root, 'multiview_texture_runtime.py', 'finish', donor, reference, work, output)
            report = json.loads((work / 'fusion-result.json').read_text(encoding='utf-8'))
            inference = json.loads((work / 'views' / 'manifest.json').read_text(encoding='utf-8'))
            report['view_generation'] = {key: inference[key] for key in (
                'engine', 'revision', 'adapter_revision', 'base_revision', 'steps', 'seed', 'guidance',
                'resolution', 'elapsed_s', 'torch_peak_allocated_mib', 'torch_peak_reserved_mib') if key in inference}
            if (report.get('output_sha256') != file_sha(output)
                    or source_hash != file_sha(model) or reference_hash != file_sha(reference)):
                raise ValueError('Multiview texture refinement inputs or output changed during verification.')
            output.replace(model)
    except Exception as error:
        # Refinement is optional. The published model still contains its original maps.
        traceback.print_exc()
        reason = str(error) if isinstance(error, ValueError) else 'The texture pass failed. See the generation log.'
        return dict(state='skipped', reason=reason)
    report.update(state='applied', source_sha256=source_hash, reference_sha256=reference_hash)
    if material_report is not None:
        report['materials_on_final_surface'] = material_report
    return report


def main(args):
    from multiview_texture_fusion import finish, prepare

    action, model, reference, work, *outputs = args
    model, reference, work = map(Path, (model, reference, work))
    if action == 'prepare' and not outputs:
        prepare(model, reference, work)
    elif action == 'finish' and len(outputs) == 1:
        output = Path(outputs[0])
        report = finish(model, reference, work, output)
        report['output_sha256'] = file_sha(output)
        (work / 'fusion-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    else:
        raise ValueError('Choose a supported multiview texture stage.')


if __name__ == '__main__':
    main(sys.argv[1:])
