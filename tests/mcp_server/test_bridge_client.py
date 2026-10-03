import ctypes
import unittest
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

    def WaitNamedPipeW(self, path, timeout_ms):
        self.calls.append(("wait", path, timeout_ms))
        return self.wait_ok

    def CreateFileW(self, path, access, share, security, disposition, flags, template):
        self.calls.append(("create", path, access, share, disposition))
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


if __name__ == "__main__":
    unittest.main()
