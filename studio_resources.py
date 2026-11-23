"""Resource readings shared across Desktop and Server workspaces."""
import csv
import shutil
import subprocess
from functools import lru_cache
from threading import Lock
from time import monotonic

import psutil

from gpu_runtime import saved_gpu


_gpu_readings = {}
_gpu_lock = Lock()


@lru_cache(maxsize=4)
def selected_gpu(root):
    try:
        return saved_gpu(root).get('gpu_uuid', '')
    except (OSError, ValueError, RuntimeError):
        return ''


def gpu_resources(root):
    uuid = selected_gpu(root)
    with _gpu_lock:
        previous, report = _gpu_readings.get(uuid, (float('-inf'), {}))
        if monotonic() - previous < 15:
            return report
        result = {}
        command = ['nvidia-smi', '--query-gpu=compute_cap,memory.total,memory.free',
                   '--format=csv,noheader,nounits']
        if uuid:
            command.append(f'--id={uuid}')
        try:
            output = subprocess.check_output(command, text=True, timeout=2, stderr=subprocess.DEVNULL,
                                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            compute, total, free = next(csv.reader(output.splitlines(), skipinitialspace=True))
            result = dict(compute=compute, vram_total_mib=int(total), vram_free_gib=round(int(free) / 1024, 1))
        except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
            pass
        _gpu_readings[uuid] = monotonic(), result
        return result


def resources(root, workspace):
    result = dict(ram_free_gib=round(psutil.virtual_memory().available / 1024**3, 1))
    gpu = gpu_resources(root)
    if 'vram_free_gib' in gpu:
        result['vram_free_gib'] = gpu['vram_free_gib']
    try:
        result['disk_free_gib'] = round(shutil.disk_usage(workspace).free / 1024**3, 1)
    except OSError:
        pass
    return result
