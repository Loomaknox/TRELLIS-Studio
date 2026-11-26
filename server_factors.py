"""Authenticated protection for Server authenticator seeds. No secrets in configuration or logs."""
import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import stat


class FactorProtectionError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, entropy, *, decrypt):
    # CurrentUser scope, UI forbidden. Explicit signatures also work on 64-bit Windows.
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    pointer = ctypes.POINTER(_Blob)
    func.argtypes = [pointer, ctypes.c_void_p, pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, pointer]
    func.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    def blob(value):
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        return _Blob(len(value), buffer)
    source, context, result = blob(data), blob(entropy), _Blob()
    if not func(ctypes.byref(source), None, ctypes.byref(context), None, None, 1, ctypes.byref(result)):
        raise FactorProtectionError('Windows could not open the authenticator vault. Check the Server account and DPAPI profile.')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel.LocalFree(result.data)


class FactorProtector:
    def __init__(self, key_file=None):
        self.key_file = Path(key_file) if key_file else None
        if self.key_file and not self.key_file.is_absolute():
            raise FactorProtectionError('Use an absolute path to the private Server authenticator key.')

    @classmethod
    def configured(cls):
        return cls(os.environ.get('TRELLIS_SERVER_TOTP_KEY_FILE'))

    def _fernet(self):
        if not self.key_file:
            raise FactorProtectionError('Configure TRELLIS_SERVER_TOTP_KEY_FILE for this Server account.')
        try:
            from cryptography.fernet import Fernet
        except ImportError as error:
            raise FactorProtectionError('Install cryptography in the Server Python environment for file-key protection.') from error
        try:
            fd = os.open(self.key_file, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(fd, 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or (os.name != 'nt' and
                        (info.st_uid != os.geteuid() or info.st_mode & 0o077)):
                    raise FactorProtectionError('The key must be a private regular file owned by the Server account (mode 0600).')
                data = handle.read(128)
                if len(data) >= 128:
                    raise ValueError('Invalid key length.')
                return Fernet(data.strip())
        except (OSError, ValueError) as error:
            raise FactorProtectionError('The authenticator key file is unavailable or invalid. Restore the matching private key.') from error

    def seal(self, secret, user_id):
        context = b'TRELLIS/TOTP/v1/' + user_id.encode('ascii') + b'\0'
        seed = secret.encode('ascii')
        if os.name == 'nt' and self.key_file is None:
            return 'dpapi1:' + base64.b64encode(_dpapi(seed, context, decrypt=False)).decode('ascii')
        return 'fernet1:' + self._fernet().encrypt(context + seed).decode('ascii')

    def open(self, envelope, user_id):
        context = b'TRELLIS/TOTP/v1/' + user_id.encode('ascii') + b'\0'
        kind, _, content = envelope.partition(':')
        if kind == 'dpapi1' and os.name == 'nt':
            try:
                return _dpapi(base64.b64decode(content, validate=True), context, decrypt=True).decode('ascii')
            except ValueError as error:
                raise FactorProtectionError('Invalid Windows authenticator record.') from error
        if kind == 'fernet1':
            cipher = self._fernet()
            from cryptography.fernet import InvalidToken
            try:
                payload = cipher.decrypt(content.encode('ascii'))
                if payload.startswith(context):
                    return payload[len(context):].decode('ascii')
            except (InvalidToken, ValueError):
                pass
        raise FactorProtectionError('Cannot open the authenticator record with this account and key.')
