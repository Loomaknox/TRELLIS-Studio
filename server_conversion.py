"""Supervise private import/export workers and their converter subprocesses."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from studio_workspace import write

ROOT = Path(__file__).resolve().parent
CONVERTERS = {'import_worker.py': 300, 'export_worker.py': 900, 'print_worker.py': 600}
MEMORY_LIMIT = 8 * 1024**3
PROCESS_LIMIT = 12


def supervise(command, seconds, *, memory=MEMORY_LIMIT, processes=PROCESS_LIMIT):
    import psutil

    owner = psutil.Process(os.getppid())
    if os.name == 'nt':
        from collection_preview_renderer import _WindowsBrowserJob
        group = _WindowsBrowserJob(command, memory_limit=memory, process_limit=processes,
                                   stdout=None, stderr=None)
        process = group.process
    else:
        import resource
        def restrict():
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
            resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
        process = subprocess.Popen(command, start_new_session=True, preexec_fn=restrict, stdin=subprocess.DEVNULL)
        group = None
    deadline = time.monotonic() + seconds
    try:
        while True:
            code = group.poll() if group else process.poll()
            if code is not None:
                return code
            if not owner.is_running() or time.monotonic() >= deadline:
                raise RuntimeError('The Server conversion was interrupted or reached its time limit.')
            if group is None:
                try:
                    parent = psutil.Process(process.pid)
                    members = [parent, *parent.children(recursive=True)]
                    rss = sum(p.memory_info().rss for p in members)
                    if len(members) > processes or rss > memory:
                        raise RuntimeError('The Server conversion exceeded its process or memory budget.')
                except psutil.NoSuchProcess:
                    pass
            time.sleep(.1)
    finally:
        if group:
            group.close()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=10)


def run(script, folder):
    if script not in CONVERTERS:
        raise ValueError('Unknown Server converter.')
    # Fail closed if limits cannot be established. The scheduler settles the
    # terminal job and releases its reserved quota before admitting the next one.
    try:
        from server_import_limits import check_model
        if script == 'import_worker.py':
            check_model(folder / 'original.glb')
        elif script == 'print_worker.py':
            check_model(folder / 'source.glb')
        else:
            from studio_workspace import read
            if read(folder / 'request.json', {}).get('target') in ('unity', 'unreal', 'blender'):
                for asset in (folder / 'sources').iterdir():
                    check_model(asset / 'model.glb')
                    for lod in (asset / 'LODs').glob('*.glb'):
                        check_model(lod)
        command = [sys.executable, '-B', '-u', str(ROOT / script), str(folder)]
        code = supervise(command, CONVERTERS[script])
        if code:
            raise RuntimeError('The converter stopped before finishing. Check the Server resource limits and log.')
    except Exception as error:
        write(folder / 'status.json', {'state': 'error', 'stage': 'Server conversion stopped',
                                       'progress': 0, 'error': str(error)})
        raise


if __name__ == '__main__':
    run(sys.argv[1], Path(sys.argv[2]).resolve(strict=True))
