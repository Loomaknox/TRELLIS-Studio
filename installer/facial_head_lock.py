"""Serialize local installation, removal and use of the optional face model."""
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path


@contextmanager
def component_lock(root):
    if os.name != 'nt':
        raise RuntimeError('This experimental component currently targets Windows Desktop.')
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    location = os.path.normcase(str(Path(root).resolve()))
    key = hashlib.sha256(location.encode('utf-8')).hexdigest()
    handle = kernel.CreateMutexW(None, False, 'Local\\TRELLIS-FacialHead-' + key)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait == 258:
            raise RuntimeError('The face component is busy. Wait for the current operation to finish.')
        if wait not in (0, 128):  # A previous owner may have exited unexpectedly.
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)
