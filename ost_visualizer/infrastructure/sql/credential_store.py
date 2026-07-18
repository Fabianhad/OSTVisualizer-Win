from __future__ import annotations
import ctypes
from ctypes import wintypes
from typing import Optional

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    def __init__(self, advapi32=None) -> None:
        self._api = (
            ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            if advapi32 is None
            else advapi32
        )
        self._configure_api()

    def _configure_api(self) -> None:
        try:
            self._api.CredWriteW.argtypes = [
                ctypes.POINTER(_CREDENTIALW),
                wintypes.DWORD,
            ]
            self._api.CredWriteW.restype = wintypes.BOOL
            self._api.CredReadW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
            ]
            self._api.CredReadW.restype = wintypes.BOOL
            self._api.CredDeleteW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            self._api.CredDeleteW.restype = wintypes.BOOL
            self._api.CredFree.argtypes = [ctypes.c_void_p]
            self._api.CredFree.restype = None
        except AttributeError as exc:
            raise OSError("Windows Credential Manager is unavailable") from exc

    def write_password(self, target: str, username: str, password: str) -> None:
        _validate_target(target)
        encoded = bytearray(password, "utf-16-le")
        blob = (ctypes.c_ubyte * len(encoded)).from_buffer(encoded)
        credential = _CREDENTIALW()
        credential.Type = _CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(encoded)
        credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username
        try:
            if not self._api.CredWriteW(ctypes.byref(credential), 0):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            ctypes.memset(ctypes.addressof(blob), 0, len(encoded))

    def read_password(self, target: str) -> Optional[str]:
        _validate_target(target)
        pointer = ctypes.POINTER(_CREDENTIALW)()
        if not self._api.CredReadW(
            target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            error = ctypes.get_last_error()
            if error == _ERROR_NOT_FOUND:
                return None
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            if not credential.CredentialBlob or not credential.CredentialBlobSize:
                return ""
            value = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            )
            return value.decode("utf-16-le")
        finally:
            self._api.CredFree(pointer)

    def delete_password(self, target: str) -> None:
        _validate_target(target)
        if self._api.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != _ERROR_NOT_FOUND:
            raise ctypes.WinError(error)


def _validate_target(target: str) -> None:
    if not target or "\x00" in target:
        raise ValueError("Credential target is invalid")
