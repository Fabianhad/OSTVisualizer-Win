import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.mcp_takeoff.pipe_client import TakeoffPipeClient, read_session_token


class ScriptedPipeClient(TakeoffPipeClient):
    def __init__(self, token_path, response):
        super().__init__(token_path, wait_timeout_ms=10)
        self.response = response
        self.payloads = []

    def _exchange(self, payload):
        self.payloads.append(payload)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class PipeClientTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.token_path = Path(directory.name) / "session.token"
        self.token_path.write_text("secret-token-1\n", encoding="utf-8")

    def call(self, response, command="list_sheets", arguments=None):
        client = ScriptedPipeClient(self.token_path, response)
        with patch("sys.platform", "win32"):
            result = client.call(command, arguments or {})
        return client, result

    def test_sends_one_json_line_with_token_command_and_arguments(self):
        client, result = self.call(
            b'{"success": true, "status": "ok", "data": {}}\n',
            arguments={"limit": 5},
        )
        self.assertEqual(len(client.payloads), 1)
        payload = client.payloads[0]
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(
            json.loads(payload),
            {
                "token": "secret-token-1",
                "command": "list_sheets",
                "arguments": {"limit": 5},
            },
        )
        self.assertEqual(result, {"success": True, "status": "ok", "data": {}})

    def test_missing_or_empty_token_means_the_app_is_not_running(self):
        for content in (None, "", "   \n"):
            with self.subTest(content=content):
                if content is None:
                    self.token_path.unlink(missing_ok=True)
                else:
                    self.token_path.write_text(content, encoding="utf-8")
                client, result = self.call(b"{}")
                self.assertEqual(client.payloads, [])
                self.assertEqual(result["status"], "app_not_running")
                self.assertFalse(result["success"])

    def test_pipe_errors_mean_the_app_is_not_running(self):
        _client, result = self.call(OSError(2, "pipe missing"))
        self.assertEqual(result["status"], "app_not_running")

    def test_malformed_responses_are_reported_without_echoing_the_token(self):
        for response in (b"not json", b"[1]", b'{"data": 1}', b"\xff\xfe"):
            with self.subTest(response=response):
                _client, result = self.call(response)
                self.assertEqual(result["status"], "malformed_bridge_response")
                self.assertNotIn("secret-token-1", json.dumps(result))

    def test_bridge_errors_pass_through(self):
        _client, result = self.call(
            b'{"success": false, "status": "unauthorized", '
            b'"error": {"code": "unauthorized", "message": "Session token rejected."}}'
        )
        self.assertEqual(result["status"], "unauthorized")

    def test_non_windows_platform_never_opens_the_pipe(self):
        client = ScriptedPipeClient(self.token_path, b"{}")
        with patch("sys.platform", "linux"):
            result = client.call("list_sheets", {})
        self.assertEqual(client.payloads, [])
        self.assertEqual(result["status"], "app_not_running")

    def test_real_pipe_that_does_not_exist_is_app_not_running(self):
        client = TakeoffPipeClient(
            self.token_path,
            server_name="OSTVisualizerMissingTakeoffBridgeForTest",
            wait_timeout_ms=10,
        )
        self.assertEqual(client.call("list_sheets", {})["status"], "app_not_running")


class HungAppTests(unittest.TestCase):
    def setUp(self):
        import uuid

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.token_path = Path(directory.name) / "session.token"
        self.token_path.write_text("secret-token-1", encoding="utf-8")
        self.server_name = f"OstvTakeoffHungTest-{uuid.uuid4().hex[:12]}"

    def serve(self, reply=None, reply_after_s=0.0):
        import threading
        import time
        import win32file
        import win32pipe

        handle = win32pipe.CreateNamedPipe(
            "\\\\.\\pipe\\" + self.server_name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_BYTE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT,
            1,
            65536,
            65536,
            0,
            None,
        )
        received = []
        released = threading.Event()

        def run():
            win32pipe.ConnectNamedPipe(handle, None)
            received.append(win32file.ReadFile(handle, 65536)[1])
            if reply is not None:
                time.sleep(reply_after_s)
                win32file.WriteFile(handle, reply)
            released.wait(10)
            handle.Close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(lambda: (released.set(), thread.join(5)))
        return received

    def test_an_app_that_never_answers_times_out_with_a_clear_error(self):
        import time

        received = self.serve()
        client = TakeoffPipeClient(
            self.token_path, server_name=self.server_name, read_timeout_s=0.3
        )
        started = time.monotonic()
        result = client.call("list_sheets", {})
        elapsed = time.monotonic() - started
        self.assertEqual(result["status"], "app_timeout")
        self.assertIn("did not answer", result["error"]["message"])
        self.assertNotIn("secret-token-1", json.dumps(result))
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 3.0)
        self.assertIn(b'"command": "list_sheets"', received[0])

    def test_a_slow_answer_within_the_timeout_is_returned(self):
        self.serve(
            reply=b'{"success": true, "status": "ok", "data": {"n": 1}}\n',
            reply_after_s=0.2,
        )
        client = TakeoffPipeClient(
            self.token_path, server_name=self.server_name, read_timeout_s=2.0
        )
        self.assertEqual(client.call("list_sheets", {})["data"], {"n": 1})

    def test_the_default_timeout_is_the_configurable_constant(self):
        from ost_visualizer.application.dtos.ai_takeoff_dtos import (
            PIPE_READ_TIMEOUT_SECONDS,
        )

        self.assertEqual(PIPE_READ_TIMEOUT_SECONDS, 120.0)
        client = TakeoffPipeClient(self.token_path)
        self.assertEqual(client.read_timeout_s, PIPE_READ_TIMEOUT_SECONDS)


class ReadSessionTokenTests(unittest.TestCase):
    def test_reads_and_strips_the_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.token"
            path.write_text("  abc \r\n", encoding="utf-8")
            self.assertEqual(read_session_token(path), "abc")
            path.write_text("x" * 600, encoding="utf-8")
            self.assertIsNone(read_session_token(path))
            self.assertIsNone(read_session_token(Path(directory) / "missing"))
            self.assertIsNone(read_session_token(Path(directory)))


if __name__ == "__main__":
    unittest.main()
