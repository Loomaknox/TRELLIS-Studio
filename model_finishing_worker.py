"""Run a CPU finishing job on a private copy of a completed model."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
import traceback

from studio_import import validate_glb
from studio_workspace import read, write


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
        with TemporaryDirectory(prefix='finish-', dir=folder) as directory:
            target = Path(directory) / 'model.glb'
            if operation == 'texture_projection':
                from texture_projection import project_texture
                reference = folder / request['reference_file']
                if reference.resolve().parent != folder:
                    raise ValueError('Invalid projection reference.')
                report = project_texture(source, reference, target, options=request['options'], progress=progress)
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
        write(folder / 'result.json', result)
        source.unlink(missing_ok=True)
        if operation == 'texture_projection':
            reference.unlink(missing_ok=True)
        status('done', completed, 100, result=result)
    except Exception as error:
        traceback.print_exc()
        (folder / 'model.glb').unlink(missing_ok=True)
        status('error', 'Finishing failed', 0,
               error=str(error) if isinstance(error, ValueError) else 'The finishing worker failed. See its log.')


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())
