"""Portable settings; account/proxy secrets encrypted with Windows DPAPI."""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

def protect(data: bytes, *, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise RuntimeError('This application stores secrets using Windows DPAPI')
    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)

class SettingsStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'settings.json'

    def load(self):
        if not self.path.exists():
            return {'sites': [], 'accounts': [], 'engine': '', 'stealth': False}
        data = json.loads(self.path.read_text(encoding='utf-8'))
        sealed = data.pop('accounts_encrypted', None)
        data['accounts'] = json.loads(protect(base64.b64decode(sealed), decrypt=True)) if sealed else []
        return data

    def save(self, settings):
        self.directory.mkdir(parents=True, exist_ok=True)
        data = {k:v for k,v in settings.items() if k != 'accounts'}
        encoded = json.dumps(settings['accounts'], ensure_ascii=False).encode()
        data['accounts_encrypted'] = base64.b64encode(protect(encoded)).decode('ascii')
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(self.path)
