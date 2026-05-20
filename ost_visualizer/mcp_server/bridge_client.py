import json
import logging
import sys
import ctypes
from ctypes import wintypes
from typing import Optional
from ..application.dtos.mcp_context_dtos import MCP_BRIDGE_SERVER_NAME

_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_ERROR_BROKEN_PIPE = 109
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class McpBridgeClient:
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        timeout_ms: int = 150,
        server_name: str = MCP_BRIDGE_SERVER_NAME,
    ):
        self._logger = logger or logging.getLogger(__name__)
        self._timeout_ms = timeout_ms
        self._server_name = server_name

    def get_context(self) -> Optional[dict]:
        if sys.platform != "win32":
            return None
        try:
            payload = json.dumps({"command": "get_context"}).encode("utf-8") + b"\n"
            response = self._request_windows_pipe(payload).decode(
                "utf-8", errors="replace"
            )
            data = json.loads(response)
            if not isinstance(data, dict) or not data.get("success"):
                return None
            context = data.get("data")
            return context if isinstance(context, dict) else None
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            self._logger.debug("MCP live context bridge unavailable: %s", exc)
            return None

    def _request_windows_pipe(self, payload: bytes) -> bytes:
        pipe_path = self._pipe_path()
        kernel32 = self._kernel32()
        if not kernel32.WaitNamedPipeW(pipe_path, self._timeout_ms):
            raise OSError(ctypes.get_last_error(), "Named pipe is unavailable")
        handle = kernel32.CreateFileW(
            pipe_path,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), "Failed to open named pipe")
        try:
            self._write_pipe(kernel32, handle, payload)
            return self._read_pipe(kernel32, handle)
        finally:
            kernel32.CloseHandle(handle)

    def _pipe_path(self) -> str:
        if self._server_name.startswith("\\\\.\\pipe\\"):
            return self._server_name
        return "\\\\.\\pipe\\" + self._server_name

    @staticmethod
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
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        return kernel32

    @staticmethod
    def _write_pipe(kernel32, handle, payload: bytes) -> None:
        buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD()
        ok = kernel32.WriteFile(
            handle,
            buffer,
            len(payload),
            ctypes.byref(written),
            None,
        )
        if not ok or written.value != len(payload):
            raise OSError(ctypes.get_last_error(), "Failed to write named pipe")

    @staticmethod
    def _read_pipe(kernel32, handle) -> bytes:
        chunks = []
        while True:
            buffer = ctypes.create_string_buffer(65536)
            bytes_read = wintypes.DWORD()
            ok = kernel32.ReadFile(
                handle,
                buffer,
                len(buffer),
                ctypes.byref(bytes_read),
                None,
            )
            if not ok:
                error_code = ctypes.get_last_error()
                if error_code == _ERROR_BROKEN_PIPE and chunks:
                    break
                raise OSError(error_code, "Failed to read named pipe")
            if bytes_read.value == 0:
                break
            chunks.append(buffer.raw[: bytes_read.value])
            if bytes_read.value < len(buffer):
                break
        return b"".join(chunks)
