import ctypes
import unittest
from ctypes import wintypes
from unittest.mock import patch
from ost_visualizer.mcp_server import bridge_client as bridge_module
from ost_visualizer.mcp_server.bridge_client import McpBridgeClient

INVALID_HANDLE = bridge_module._INVALID_HANDLE_VALUE
FULL_READ_CHUNK = b"a" * 65536


class FakeBridgeClient(McpBridgeClient):
    def __init__(self, response):
        super().__init__(timeout_ms=10)
        self.response = response
        self.payloads = []

    def _request_windows_pipe(self, payload):
        self.payloads.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeKernel32:
    """Scripted stand-in for the Win32 pipe API; never touches a real pipe."""

    def __init__(
        self,
        wait_ok=True,
        handle=77,
        write_ok=True,
        write_count=None,
        reads=(),
    ):
        self.wait_ok = wait_ok
        self.handle = handle
        self.write_ok = write_ok
        self.write_count = write_count
        self.reads = list(reads)
        self.calls = []
        self.written = b""
        self.closed = []
        self.last_error = 0
        self.create_flags = None

    def WaitNamedPipeW(self, path, timeout_ms):
        self.calls.append(("wait", path, timeout_ms))
        return self.wait_ok

    def CreateFileW(self, path, access, share, security, disposition, flags, template):
        self.calls.append(("create", path, access, share, disposition))
        self.create_flags = flags
        return self.handle

    def WriteFile(self, handle, buffer, size, written_ref, overlapped):
        self.written = bytes(buffer.raw[:size])
        written_ref._obj.value = size if self.write_count is None else self.write_count
        return self.write_ok

    def ReadFile(self, handle, buffer, size, read_ref, overlapped):
        ok, data, error_code = self.reads.pop(0)
        ctypes.memmove(buffer, data, len(data))
        read_ref._obj.value = len(data)
        self.last_error = error_code
        return ok

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


class McpBridgeClientTests(unittest.TestCase):
    def test_returns_none_when_desktop_bridge_is_unavailable(self):
        client = McpBridgeClient(
            timeout_ms=10,
            server_name="OSTVisualizerMissingMcpBridgeForTest",
        )
        self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "bridge_unavailable")

    def test_non_windows_platform_never_opens_the_pipe(self):
        client = FakeBridgeClient(b'{"success": true, "data": {"source": "live_app"}}')
        client.last_status = "live_context"
        with patch("sys.platform", "linux"):
            self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "bridge_unavailable")
        self.assertEqual(client.payloads, [])

    def test_get_context_sends_only_the_read_only_get_context_command(self):
        client = FakeBridgeClient(b'{"success": true, "data": {}}')
        with patch("sys.platform", "win32"):
            client.get_context()
        self.assertEqual(client.payloads, [b'{"command": "get_context"}\n'])

    def test_malformed_bridge_payload_is_reported_without_crashing(self):
        client = FakeBridgeClient(b"{not-json")
        with patch("sys.platform", "win32"):
            self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "malformed_bridge_payload")

    def test_undecodable_bridge_bytes_are_reported_as_malformed(self):
        client = FakeBridgeClient(b'{"success": true, "data": {"a": "\xff\xfe"}')
        with patch("sys.platform", "win32"):
            self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "malformed_bridge_payload")

    def test_well_formed_but_unusable_payloads_are_malformed(self):
        unusable = {
            "json list": b"[1, 2]",
            "failure flag": b'{"success": false, "data": {"source": "live_app"}}',
            "missing success": b'{"data": {"source": "live_app"}}',
            "non-dict data": b'{"success": true, "data": ["live_app"]}',
            "missing data": b'{"success": true}',
        }
        for label, payload in unusable.items():
            with self.subTest(label):
                client = FakeBridgeClient(payload)
                with patch("sys.platform", "win32"):
                    self.assertIsNone(client.get_context())
                self.assertEqual(client.last_status, "malformed_bridge_payload")

    def test_pipe_errors_report_bridge_unavailable(self):
        for error in (OSError(2, "pipe missing"), RuntimeError("pipe closed")):
            with self.subTest(type(error).__name__):
                client = FakeBridgeClient(error)
                client.last_status = "live_context"
                with patch("sys.platform", "win32"):
                    self.assertIsNone(client.get_context())
                self.assertEqual(client.last_status, "bridge_unavailable")

    def test_valid_bridge_payload_reports_live_context(self):
        client = FakeBridgeClient(
            b'{"success": true, "data": {"source": "live_app", "bid_uid": "b1"}}'
        )
        with patch("sys.platform", "win32"):
            self.assertEqual(
                client.get_context(),
                {"source": "live_app", "bid_uid": "b1"},
            )
        self.assertEqual(client.last_status, "live_context")

    def test_status_is_reset_on_every_call(self):
        client = FakeBridgeClient(b'{"success": true, "data": {"source": "live_app"}}')
        with patch("sys.platform", "win32"):
            self.assertIsNotNone(client.get_context())
            self.assertEqual(client.last_status, "live_context")
            client.response = b"nope"
            self.assertIsNone(client.get_context())
            self.assertEqual(client.last_status, "malformed_bridge_payload")
            client.response = OSError(2, "gone")
            self.assertIsNone(client.get_context())
        self.assertEqual(client.last_status, "bridge_unavailable")

    def test_pipe_path_prefix_is_added_once(self):
        bare = McpBridgeClient(server_name="OstBridge")
        self.assertEqual(bare._pipe_path(), "\\\\.\\pipe\\OstBridge")
        prefixed = McpBridgeClient(server_name="\\\\.\\pipe\\OstBridge")
        self.assertEqual(prefixed._pipe_path(), "\\\\.\\pipe\\OstBridge")


class McpBridgePipeTransportTests(unittest.TestCase):
    def client(self, kernel32):
        client = McpBridgeClient(timeout_ms=25, server_name="OstBridge")
        patcher = patch.object(
            McpBridgeClient, "_kernel32", staticmethod(lambda: kernel32)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return client

    def last_error_of(self, kernel32):
        patcher = patch.object(
            ctypes, "get_last_error", side_effect=lambda: kernel32.last_error
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_request_writes_payload_reads_reply_and_closes_handle(self):
        kernel32 = FakeKernel32(reads=[(True, b'{"ok": 1}', 0)])
        reply = self.client(kernel32)._request_windows_pipe(b"ping\n")
        self.assertEqual(reply, b'{"ok": 1}')
        self.assertEqual(kernel32.written, b"ping\n")
        self.assertEqual(kernel32.closed, [77])
        self.assertEqual(kernel32.calls[0], ("wait", "\\\\.\\pipe\\OstBridge", 25))
        # Opens the existing pipe with read+write access and no sharing.
        self.assertEqual(
            kernel32.calls[1],
            ("create", "\\\\.\\pipe\\OstBridge", 0x80000000 | 0x40000000, 0, 3),
        )

    def test_unavailable_pipe_raises_without_opening_it(self):
        kernel32 = FakeKernel32(wait_ok=False)
        self.last_error_of(kernel32)
        with self.assertRaises(OSError):
            self.client(kernel32)._request_windows_pipe(b"ping\n")
        self.assertEqual([call[0] for call in kernel32.calls], ["wait"])
        self.assertEqual(kernel32.closed, [])

    def test_invalid_handle_raises_without_closing(self):
        kernel32 = FakeKernel32(handle=INVALID_HANDLE)
        self.last_error_of(kernel32)
        with self.assertRaises(OSError):
            self.client(kernel32)._request_windows_pipe(b"ping\n")
        self.assertEqual(kernel32.closed, [])

    def test_short_or_failed_write_raises_and_still_closes_handle(self):
        for label, kernel32 in (
            ("short write", FakeKernel32(write_count=2)),
            ("failed write", FakeKernel32(write_ok=False)),
        ):
            with self.subTest(label):
                self.last_error_of(kernel32)
                with self.assertRaises(OSError):
                    self.client(kernel32)._request_windows_pipe(b"ping\n")
                self.assertEqual(kernel32.closed, [77])

    def test_read_failure_without_data_raises_even_for_broken_pipe(self):
        kernel32 = FakeKernel32(reads=[(False, b"", 109)])
        self.last_error_of(kernel32)
        with self.assertRaises(OSError):
            McpBridgeClient._read_pipe(kernel32, 77)

    def test_broken_pipe_after_data_returns_what_was_read(self):
        kernel32 = FakeKernel32(reads=[(True, FULL_READ_CHUNK, 0), (False, b"", 109)])
        self.last_error_of(kernel32)
        self.assertEqual(McpBridgeClient._read_pipe(kernel32, 77), FULL_READ_CHUNK)

    def test_other_read_errors_after_data_still_raise(self):
        kernel32 = FakeKernel32(reads=[(True, FULL_READ_CHUNK, 0), (False, b"", 5)])
        self.last_error_of(kernel32)
        with self.assertRaises(OSError):
            McpBridgeClient._read_pipe(kernel32, 77)

    def test_read_joins_full_buffers_until_a_short_read(self):
        kernel32 = FakeKernel32(
            reads=[(True, FULL_READ_CHUNK, 0), (True, b"tail", 0), (True, b"unread", 0)]
        )
        data = McpBridgeClient._read_pipe(kernel32, 77)
        self.assertEqual(data, FULL_READ_CHUNK + b"tail")
        self.assertEqual(len(kernel32.reads), 1)


class McpBridgeWin32ContractTests(unittest.TestCase):
    def test_win32_constants_match_the_platform_definitions(self):
        import win32con
        import winerror

        expected = {
            "_GENERIC_READ": win32con.GENERIC_READ & 0xFFFFFFFF,
            "_GENERIC_WRITE": win32con.GENERIC_WRITE & 0xFFFFFFFF,
            "_OPEN_EXISTING": win32con.OPEN_EXISTING,
            "_FILE_ATTRIBUTE_NORMAL": win32con.FILE_ATTRIBUTE_NORMAL,
            "_ERROR_BROKEN_PIPE": winerror.ERROR_BROKEN_PIPE,
            "_INVALID_HANDLE_VALUE": ctypes.c_void_p(-1).value,
        }
        for name, value in expected.items():
            with self.subTest(constant=name):
                self.assertEqual(getattr(bridge_module, name), value)

    def test_the_pipe_is_created_with_normal_file_attributes(self):
        import win32con

        kernel32 = FakeKernel32(reads=[(True, b"{}", 0)])
        with patch.object(McpBridgeClient, "_kernel32", staticmethod(lambda: kernel32)):
            McpBridgeClient(server_name="OstBridge")._request_windows_pipe(b"x\n")
        self.assertEqual(kernel32.create_flags, win32con.FILE_ATTRIBUTE_NORMAL)

    def test_defaults_are_a_short_wait_a_module_logger_and_an_unavailable_status(self):
        import logging

        client = McpBridgeClient()
        self.assertEqual(client._timeout_ms, 150)
        self.assertIs(client._logger, logging.getLogger(bridge_module.__name__))
        self.assertEqual(client.last_status, "bridge_unavailable")
        own = logging.getLogger("custom-bridge-logger")
        self.assertIs(McpBridgeClient(logger=own)._logger, own)

    def test_the_real_kernel32_reports_the_last_error_of_a_missing_pipe(self):
        import uuid

        kernel32 = McpBridgeClient._kernel32()
        missing = "\\\\.\\pipe\\ostv-missing-" + uuid.uuid4().hex
        self.assertFalse(kernel32.WaitNamedPipeW(missing, 1))
        self.assertEqual(ctypes.get_last_error(), 2)

    def test_pipe_failures_carry_their_operation_in_the_message(self):
        waiting = FakeKernel32(wait_ok=False)
        with patch.object(McpBridgeClient, "_kernel32", staticmethod(lambda: waiting)):
            with self.assertRaises(OSError) as raised:
                McpBridgeClient(server_name="OstBridge")._request_windows_pipe(b"x")
        self.assertEqual(raised.exception.strerror, "Named pipe is unavailable")
        refused = FakeKernel32(handle=INVALID_HANDLE)
        with patch.object(McpBridgeClient, "_kernel32", staticmethod(lambda: refused)):
            with self.assertRaises(OSError) as raised:
                McpBridgeClient(server_name="OstBridge")._request_windows_pipe(b"x")
        self.assertEqual(raised.exception.strerror, "Failed to open named pipe")
        with self.assertRaises(OSError) as raised:
            McpBridgeClient._write_pipe(FakeKernel32(write_ok=False), 77, b"abc")
        self.assertEqual(raised.exception.strerror, "Failed to write named pipe")
        with self.assertRaises(OSError) as raised:
            McpBridgeClient._read_pipe(FakeKernel32(reads=[(False, b"", 5)]), 77)
        self.assertEqual(raised.exception.strerror, "Failed to read named pipe")

    def test_a_one_byte_reply_is_kept_and_an_empty_read_ends_the_reply(self):
        self.assertEqual(
            McpBridgeClient._read_pipe(FakeKernel32(reads=[(True, b"x", 0)]), 77), b"x"
        )
        self.assertEqual(
            McpBridgeClient._read_pipe(
                FakeKernel32(reads=[(True, FULL_READ_CHUNK, 0), (True, b"", 0)]), 77
            ),
            FULL_READ_CHUNK,
        )


class RecordingKernel32(FakeKernel32):
    """FakeKernel32 that also keeps every argument the client passes, verbatim."""

    def __init__(self, **options):
        super().__init__(**options)
        self.args = {}

    def WaitNamedPipeW(self, path, timeout_ms):
        self.args["wait"] = (path, timeout_ms)
        return super().WaitNamedPipeW(path, timeout_ms)

    def CreateFileW(self, *args):
        self.args["create"] = args
        return super().CreateFileW(*args)

    def WriteFile(self, handle, buffer, size, written_ref, overlapped):
        self.args["write"] = (
            handle,
            bytes(buffer.raw[:size]),
            size,
            type(written_ref._obj),
            overlapped,
        )
        return super().WriteFile(handle, buffer, size, written_ref, overlapped)

    def ReadFile(self, handle, buffer, size, read_ref, overlapped):
        self.args.setdefault("read", []).append(
            (handle, ctypes.sizeof(buffer), size, type(read_ref._obj), overlapped)
        )
        return super().ReadFile(handle, buffer, size, read_ref, overlapped)

    def CloseHandle(self, handle):
        self.args["close"] = handle
        return super().CloseHandle(handle)


class McpBridgeSecondPassTests(unittest.TestCase):
    """Argument-level and error-code contract of the pipe transport."""

    def patched(self, kernel32):
        patcher = patch.object(
            McpBridgeClient, "_kernel32", staticmethod(lambda: kernel32)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def last_error_of(self, kernel32):
        patcher = patch.object(
            ctypes, "get_last_error", side_effect=lambda: kernel32.last_error
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_win32_call_receives_exactly_the_documented_arguments(self):
        kernel32 = RecordingKernel32(reads=[(True, b"{}", 0)])
        self.patched(kernel32)
        McpBridgeClient(timeout_ms=25, server_name="OstBridge")._request_windows_pipe(
            b"ping\n"
        )
        self.assertEqual(kernel32.args["wait"], ("\\\\.\\pipe\\OstBridge", 25))
        self.assertEqual(
            kernel32.args["create"],
            ("\\\\.\\pipe\\OstBridge", 0xC0000000, 0, None, 3, 0x80, None),
        )
        self.assertEqual(
            kernel32.args["write"], (77, b"ping\n", 5, wintypes.DWORD, None)
        )
        self.assertEqual(
            kernel32.args["read"], [(77, 65536, 65536, wintypes.DWORD, None)]
        )
        self.assertEqual(kernel32.args["close"], 77)

    def test_pipe_errors_carry_the_win32_error_code_of_the_failed_call(self):
        wait = FakeKernel32(wait_ok=False)
        wait.last_error = 53
        refused = FakeKernel32(handle=INVALID_HANDLE)
        refused.last_error = 5
        write = FakeKernel32(write_ok=False)
        write.last_error = 232
        short = FakeKernel32(write_count=1)
        short.last_error = 6
        cases = (
            ("wait", wait, 53),
            ("open", refused, 5),
            ("write", write, 232),
            ("short write", short, 6),
        )
        for label, kernel32, code in cases:
            with self.subTest(label):
                self.patched(kernel32)
                self.last_error_of(kernel32)
                with self.assertRaises(OSError) as raised:
                    McpBridgeClient(server_name="OstBridge")._request_windows_pipe(
                        b"ping\n"
                    )
                self.assertEqual(raised.exception.errno, code)

    def test_read_errors_carry_the_error_code_reported_by_the_failing_read(self):
        for code in (5, 109):
            with self.subTest(code=code):
                kernel32 = FakeKernel32(reads=[(False, b"", code)])
                self.last_error_of(kernel32)
                with self.assertRaises(OSError) as raised:
                    McpBridgeClient._read_pipe(kernel32, 77)
                self.assertEqual(raised.exception.errno, code)
        kernel32 = FakeKernel32(reads=[(True, FULL_READ_CHUNK, 0), (False, b"", 5)])
        self.last_error_of(kernel32)
        with self.assertRaises(OSError) as raised:
            McpBridgeClient._read_pipe(kernel32, 77)
        self.assertEqual(raised.exception.errno, 5)

    def test_every_read_asks_for_a_full_buffer_of_the_same_handle(self):
        kernel32 = RecordingKernel32(
            reads=[(True, FULL_READ_CHUNK, 0), (True, b"tail", 0)]
        )
        McpBridgeClient._read_pipe(kernel32, 91)
        self.assertEqual(
            kernel32.args["read"],
            [(91, 65536, 65536, wintypes.DWORD, None)] * 2,
        )

    def test_invalid_utf8_inside_valid_json_is_replaced_not_rejected(self):
        # Characterisation of the explicit errors="replace" decode.
        client = FakeBridgeClient(b'{"success": true, "data": {"name": "caf\xe9"}}')
        with patch("sys.platform", "win32"):
            context = client.get_context()
        self.assertEqual(context, {"name": "caf\ufffd"})
        self.assertEqual(client.last_status, "live_context")

    def test_the_kernel32_prototypes_use_pointer_sized_handles(self):
        kernel32 = McpBridgeClient._kernel32()
        expected = {
            "WaitNamedPipeW": ((wintypes.LPCWSTR, wintypes.DWORD), wintypes.BOOL),
            "CreateFileW": (
                (
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.HANDLE,
                ),
                wintypes.HANDLE,
            ),
            "WriteFile": (
                (
                    wintypes.HANDLE,
                    wintypes.LPCVOID,
                    wintypes.DWORD,
                    wintypes.LPDWORD,
                    wintypes.LPVOID,
                ),
                wintypes.BOOL,
            ),
            "ReadFile": (
                (
                    wintypes.HANDLE,
                    wintypes.LPVOID,
                    wintypes.DWORD,
                    wintypes.LPDWORD,
                    wintypes.LPVOID,
                ),
                wintypes.BOOL,
            ),
            "CloseHandle": ((wintypes.HANDLE,), wintypes.BOOL),
        }
        for name, (argtypes, restype) in expected.items():
            with self.subTest(function=name):
                function = getattr(kernel32, name)
                self.assertEqual(tuple(function.argtypes), argtypes)
                self.assertIs(function.restype, restype)

    def test_the_real_create_file_returns_the_pointer_sized_invalid_handle(self):
        import uuid

        kernel32 = McpBridgeClient._kernel32()
        missing = "\\\\.\\pipe\\ostv-missing-" + uuid.uuid4().hex
        handle = kernel32.CreateFileW(missing, 0xC0000000, 0, None, 3, 0x80, None)
        self.assertEqual(handle, INVALID_HANDLE)
        self.assertEqual(ctypes.get_last_error(), 2)

    def test_the_default_pipe_is_the_one_the_desktop_bridge_listens_on(self):
        from ost_visualizer.application.dtos.mcp_context_dtos import (
            MCP_BRIDGE_SERVER_NAME,
        )

        client = McpBridgeClient()
        self.assertEqual(client._server_name, MCP_BRIDGE_SERVER_NAME)
        self.assertEqual(client._pipe_path(), "\\\\.\\pipe\\OSTVisualizerMcpBridge.v1")

    def test_only_pipe_and_decoding_failures_are_reported_as_statuses(self):
        # Characterisation: other exception types are programming errors and
        # must surface instead of being folded into "bridge_unavailable".
        client = FakeBridgeClient(KeyError("bug"))
        with patch("sys.platform", "win32"):
            with self.assertRaises(KeyError):
                client.get_context()

    def test_an_invalid_handle_is_recognised_by_value_not_by_identity(self):
        # The real CreateFileW hands back a fresh int equal to the constant.
        fresh = int(str(INVALID_HANDLE))
        self.assertEqual(fresh, INVALID_HANDLE)
        self.assertIsNot(fresh, INVALID_HANDLE)
        kernel32 = FakeKernel32(handle=fresh)
        with patch.object(McpBridgeClient, "_kernel32", staticmethod(lambda: kernel32)):
            with self.assertRaises(OSError) as raised:
                McpBridgeClient(server_name="OstBridge")._request_windows_pipe(b"x")
        self.assertEqual(raised.exception.strerror, "Failed to open named pipe")
        self.assertEqual(kernel32.closed, [])
        self.assertEqual([call[0] for call in kernel32.calls], ["wait", "create"])

    def test_the_real_create_file_returns_a_fresh_int_equal_to_the_constant(self):
        import uuid

        kernel32 = McpBridgeClient._kernel32()
        missing = "\\\\.\\pipe\\ostv-missing-" + uuid.uuid4().hex
        handle = kernel32.CreateFileW(missing, 0xC0000000, 0, None, 3, 0x80, None)
        self.assertEqual(handle, INVALID_HANDLE)
        self.assertIsNot(handle, INVALID_HANDLE)

    def test_a_read_one_byte_short_of_the_buffer_ends_the_reply(self):
        kernel32 = FakeKernel32(reads=[(True, b"a" * 65535, 0), (True, b"more", 0)])
        self.assertEqual(McpBridgeClient._read_pipe(kernel32, 77), b"a" * 65535)
        self.assertEqual(len(kernel32.reads), 1)

    def test_a_type_error_from_a_bad_argument_is_reported_as_malformed(self):
        """Characterisation of current behaviour. It needs a contract-violating
        argument (server_name must be str): bytes.startswith(str) raises
        TypeError inside get_context, which maps it to the same status as a
        ValueError (bad JSON)."""
        bad = McpBridgeClient(server_name=b"abc")
        for label, client in (
            ("bytes server_name (TypeError)", bad),
            ("ValueError sibling", FakeBridgeClient(ValueError("x"))),
        ):
            with self.subTest(label):
                client.last_status = "live_context"
                with patch("sys.platform", "win32"):
                    self.assertIsNone(client.get_context())
                self.assertEqual(client.last_status, "malformed_bridge_payload")


if __name__ == "__main__":
    unittest.main()
