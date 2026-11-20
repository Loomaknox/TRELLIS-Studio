"""Run a CPU finishing job on a private copy of a completed model."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import traceback

from studio_import import validate_glb
from studio_workspace import read, write


def staged_reference(folder, name):
    path = folder / name
    if path.parent != folder or path.resolve().parent != folder:
        raise ValueError('Invalid projection reference.')
    return path


def retain_generation_views(folder, source, provenance, report, operation):
    """Rebind verified views after a frame-preserving bake or color-only projection."""
    from generation_view_projection import (
        checked_generation_views, digest, save_generation_views, verify_generation_view_inputs,
    )

    provenance = checked_generation_views(provenance)
    verify_generation_view_inputs(folder, source, provenance)
    if operation == 'baked_game_copy':
        if report['source_sha256'] != provenance['model_sha256'] or report['model_sha256'] != digest(folder / 'model.glb'):
            raise ValueError('The baked export differs from the verified generation source.')
    save_generation_views(folder, provenance['normalization'], provenance['views'],
                          camera_model=provenance.get('camera_model'))


def run(folder):
    request = read(folder / 'finishing-request.json')
    operation = request['operation']
    source = folder / 'source.glb'
    started = time.monotonic()

    def status(state, label, progress, **extra):
        write(folder / 'status.json', dict(state=state, stage=label, operation=operation,
              progress=progress, elapsed=round(time.monotonic() - started, 1), **extra))

    def progress(stage, fraction):
        status('running', stage, min(97, max(1, round(fraction * 96))))
        print(stage, flush=True)

    try:
        progress('Reading the selected model', .03)
        references = []
        with TemporaryDirectory(prefix='finish-', dir=folder) as directory:
            target = Path(directory) / 'model.glb'
            if operation == 'texture_projection':
                from texture_projection import project_texture, project_texture_views
                if 'generation_views' in request:
                    from generation_view_projection import generation_reference_name, project_generation_texture
                    report = project_generation_texture(folder, source, target, request['generation_views'], progress=progress)
                    references = [folder / generation_reference_name(view['role'], staged=True) for view in report['views']]
                elif 'views' in request:
                    views = [(staged_reference(folder, view['reference_file']), view['options']) for view in request['views']]
                    references = [reference for reference, _ in views]
                    if len({reference.resolve() for reference in references}) != 2:
                        raise ValueError('Expected two staged projection references.')
                    report = project_texture_views(source, views, target, progress=progress)
                else:
                    reference = staged_reference(folder, request['reference_file'])
                    references = [reference]
                    cutout = request.get('generation_reference')
                    if cutout is not None:
                        from generation_view_projection import digest
                        if digest(source) != cutout['source_sha256'] or digest(reference) != cutout['reference_sha256']:
                            raise ValueError('The model or saved generation cutout changed before projection.')
                    report = project_texture(source, reference, target, options=request['options'], progress=progress)
                    if cutout is not None:
                        if (report['source_sha256'] != cutout['source_sha256']
                                or digest(reference) != cutout['reference_sha256']):
                            raise ValueError('The model or saved generation cutout changed during projection.')
                        report.update(method='generation_reference', alignment='supplied_camera', reference='prepared',
                                      reference_sha256=cutout['reference_sha256'], model_sha256=digest(target))
                completed = 'Texture projection ready'
            elif operation == 'baked_game_copy':
                from baked_game_copy import run_baked_game_copy
                report = run_baked_game_copy(source, target, options=request['options'], progress=progress)
                completed = 'Baked game copy ready'
            else:
                raise ValueError('Unsupported finishing operation.')
            validate_glb(target)
            target.replace(folder / 'model.glb')
        result = {**request['result'], 'revision': time.time_ns(), operation: report}
        if operation == 'baked_game_copy':
            result.update(triangles=report['triangles'], vertices=report['vertices'],
                          texture_size=request['options']['texture_size'])
        if 'retained_generation_views' in request:
            try:
                retain_generation_views(folder, source, request['retained_generation_views'], report, operation)
                report['generation_views_retained'] = True
            except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
                print(f'Could not retain the saved generation views ({type(error).__name__}).', flush=True)
                report['generation_views_retained'] = False
        write(folder / 'result.json', result)
        source.unlink(missing_ok=True)
        for reference in references:
            reference.unlink(missing_ok=True)
        status('done', completed, 100, result=result)
    except Exception as error:
        traceback.print_exc()
        (folder / 'model.glb').unlink(missing_ok=True)
        status('error', 'Finishing failed', 0,
               error=str(error) if isinstance(error, ValueError) else 'The finishing worker failed. See its log.')


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
