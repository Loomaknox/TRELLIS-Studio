"""Run local U2Net in a separate CPU environment shared by Studio's image pipelines."""

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent
RUNTIME = Path('.tools/segmentation/venv') / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
MISSING_RUNTIME = ('The isolated background remover is unavailable. Repair the Studio generation '
                   'installation or use a transparent reference.')


class BackgroundRemovalError(RuntimeError):
    pass


def runtime_python():
    python = Path(os.environ.get('TRELLIS_SEGMENTATION_PYTHON') or ROOT / RUNTIME)
    if not python.is_absolute() or not python.is_file():
        raise BackgroundRemovalError(MISSING_RUNTIME)
    return python


def masks(sources, weights):
    """Return a grayscale mask per reference, sharing one CPU session across supplied views."""
    from PIL import Image

    if not sources:
        return []
    python = runtime_python()
    if not weights.is_file():
        raise BackgroundRemovalError('Background removal needs the Studio U2Net model. Use transparent images or reinstall Studio.')
    with TemporaryDirectory(prefix='studio-cutout-') as folder:
        work = Path(folder)
        for index, source in enumerate(sources):
            source.save(work / f'{index}.png', format='PNG')
        environment = dict(os.environ, CUDA_VISIBLE_DEVICES='-1', OMP_NUM_THREADS='4', OPENBLAS_NUM_THREADS='1')
        try:
            child = subprocess.run([python, '-I', '-B', Path(__file__).resolve(), weights.resolve(), str(len(sources))],
                                   cwd=work, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, timeout=120 + 45 * len(sources),
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if child.returncode:
                diagnostic = child.stderr.decode('utf-8', errors='replace').strip().splitlines()
                print('Studio background remover:', diagnostic[-1][:500] if diagnostic else child.returncode, file=sys.stderr)
                raise BackgroundRemovalError('The isolated background remover failed. Repair the Studio generation installation or use a transparent reference.')
            results = []
            for index, source in enumerate(sources):
                with Image.open(work / f'{index}-mask.png') as mask:
                    if mask.mode != 'L' or mask.size != source.size:
                        raise BackgroundRemovalError('The background remover produced an invalid mask.')
                    results.append(mask.copy())
            return results
        except subprocess.TimeoutExpired as exc:
            raise BackgroundRemovalError('Background removal timed out. Use a smaller or transparent reference.') from exc
        except OSError as exc:
            raise BackgroundRemovalError(MISSING_RUNTIME) from exc


def cutout(source, weights):
    from PIL import Image

    return Image.composite(source, Image.new('RGBA', source.size), masks([source], weights)[0])


def _worker(weights, count):
    from importlib.metadata import version
    import onnxruntime as ort
    from PIL import Image
    from rembg.sessions.u2net import U2netSession

    if version('rembg') != '2.0.88' or sys.prefix == sys.base_prefix:
        raise RuntimeError('Studio requires its pinned, isolated rembg environment.')

    class LocalU2Net(U2netSession):
        @classmethod
        def download_models(cls, *args, **kwargs):
            return weights

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = LocalU2Net('u2net', options, providers=['CPUExecutionProvider'])
    for index in range(count):
        with Image.open(f'{index}.png') as source:
            mask, = session.predict(source)
            mask.save(f'{index}-mask.png')


if __name__ == '__main__':
    _worker(Path(sys.argv[1]), int(sys.argv[2]))
