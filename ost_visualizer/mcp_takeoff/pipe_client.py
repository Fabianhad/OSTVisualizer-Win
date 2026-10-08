import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Optional
from ..application.dtos.ai_takeoff_dtos import (
    AI_TAKEOFF_BRIDGE_SERVER_NAME,
    ERROR_APP_NOT_RUNNING,
    ERROR_APP_TIMEOUT,
    ERROR_BUSY,
    ERROR_MALFORMED_RESPONSE,
    PIPE_READ_TIMEOUT_SECONDS,
    error_result,
)

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_ERROR_BROKEN_PIPE = 109
_ERROR_SEM_TIMEOUT = 121
_ERROR_PIPE_BUSY = 231
_ERROR_MORE_DATA = 234
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
_MAX_TOKEN_CHARS = 200
_READ_CHUNK_BYTES = 65536
_POLL_INTERVAL_SECONDS = 0.01
BUSY_RETRY_SECONDS = 2.0
_BUSY_MESSAGE = (
    "OST Visualizer is busy with other AI takeoff requests. Try again in a moment."
)
_APP_NOT_RUNNING_MESSAGE = (
    "OST Visualizer is not running with AI takeoff enabled. Open the app, open a "
    "bid and enable AI takeoff in Tools > Options > MCP Setup."
)


class PipeReadTimeout(Exception):
    """Raised when OST Visualizer does not answer within the read timeout."""


class PipeBusy(Exception):
    """Raised when every pipe instance stays in use for the whole retry window."""


def read_session_token(token_path: Path) -> Optional[str]:
    try:
        text = Path(token_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not text or len(text) > _MAX_TOKEN_CHARS:
        return None
    return text


class TakeoffPipeClient:
    def __init__(
        self,
        token_path: Path,
        server_name: str = AI_TAKEOFF_BRIDGE_SERVER_NAME,
        wait_timeout_ms: int = 500,
        read_timeout_s: float = PIPE_READ_TIMEOUT_SECONDS,
        busy_retry_s: float = BUSY_RETRY_SECONDS,
    ):
        self._token_path = Path(token_path)
        self._server_name = server_name
        self._wait_timeout_ms = wait_timeout_ms
        self.read_timeout_s = float(read_timeout_s)
        self.busy_retry_s = float(busy_retry_s)

    def call(self, command: str, arguments: dict) -> dict:
        if sys.platform != "win32":
            return error_result(ERROR_APP_NOT_RUNNING, _APP_NOT_RUNNING_MESSAGE)
        token = read_session_token(self._token_path)
        if token is None:
            return error_result(ERROR_APP_NOT_RUNNING, _APP_NOT_RUNNING_MESSAGE)
        payload = (
            json.dumps(
                {"token": token, "command": command, "arguments": arguments}
            ).encode("ascii")
            + b"\n"
        )
        try:
            raw = self._exchange(payload)
        except PipeReadTimeout:
            return error_result(
                ERROR_APP_TIMEOUT,
                f"OST Visualizer did not answer within {self.read_timeout_s:g} seconds. "
                "It may be busy with a large page or a dialog; try again, or use a "
                "smaller crop or bounding box.",
            )
        except PipeBusy:
            return error_result(ERROR_BUSY, _BUSY_MESSAGE)
        except OSError:
            return error_result(ERROR_APP_NOT_RUNNING, _APP_NOT_RUNNING_MESSAGE)
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            response = None
        if not isinstance(response, dict) or not isinstance(
            response.get("success"), bool
        ):
            return error_result(
                ERROR_MALFORMED_RESPONSE,
                "OST Visualizer returned an unreadable response.",
            )
        return response

    def _exchange(self, payload: bytes) -> bytes:
        kernel32 = _kernel32()
        pipe_path = "\\\\.\\pipe\\" + self._server_name
        handle = self._open(kernel32, pipe_path)
        try:
            _write_all(kernel32, handle, payload)
            return _read_line(kernel32, handle, time.monotonic() + self.read_timeout_s)
        finally:
            kernel32.CloseHandle(handle)

    def _open(self, kernel32, pipe_path: str):
        deadline = time.monotonic() + self.busy_retry_s
        while True:
            if kernel32.WaitNamedPipeW(pipe_path, self._wait_timeout_ms):
                handle = kernel32.CreateFileW(
                    pipe_path,
                    _GENERIC_READ | _GENERIC_WRITE,
                    0,
                    None,
                    _OPEN_EXISTING,
                    _FILE_ATTRIBUTE_NORMAL,
                    None,
                )
                if handle != _INVALID_HANDLE_VALUE:
                    return handle
                error_code = ctypes.get_last_error()
                if error_code != _ERROR_PIPE_BUSY:
                    raise OSError(error_code, "Failed to open named pipe")
            else:
                error_code = ctypes.get_last_error()
                if error_code != _ERROR_SEM_TIMEOUT:
                    raise OSError(error_code, "Named pipe is unavailable")
            if time.monotonic() >= deadline:
                raise PipeBusy()


def _write_all(kernel32, handle, payload: bytes) -> None:
    buffer = ctypes.create_string_buffer(payload)
    written = wintypes.DWORD()
    ok = kernel32.WriteFile(handle, buffer, len(payload), ctypes.byref(written), None)
    if not ok or written.value != len(payload):
        raise OSError(ctypes.get_last_error(), "Failed to write named pipe")


def _wait_for_data(kernel32, handle, deadline: float) -> None:
    available = wintypes.DWORD()
    while True:
        ok = kernel32.PeekNamedPipe(
            handle, None, 0, None, ctypes.byref(available), None
        )
        if not ok or available.value:
            return
        if time.monotonic() >= deadline:
            raise PipeReadTimeout()
        time.sleep(_POLL_INTERVAL_SECONDS)


def _read_line(kernel32, handle, deadline: float) -> bytes:
    chunks = []
    while True:
        _wait_for_data(kernel32, handle, deadline)
        buffer = ctypes.create_string_buffer(_READ_CHUNK_BYTES)
        bytes_read = wintypes.DWORD()
        ok = kernel32.ReadFile(
            handle, buffer, len(buffer), ctypes.byref(bytes_read), None
        )
        if bytes_read.value:
            chunks.append(buffer.raw[: bytes_read.value])
        if not ok:
            error_code = ctypes.get_last_error()
            if error_code == _ERROR_MORE_DATA:
                continue
            if error_code == _ERROR_BROKEN_PIPE and chunks:
                break
            raise OSError(error_code, "Failed to read named pipe")
        if bytes_read.value == 0 or chunks[-1].endswith(b"\n"):
            break
    return b"".join(chunks)


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
    ]
    kernel32.PeekNamedPipe.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32
