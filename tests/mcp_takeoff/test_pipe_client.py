import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.mcp_takeoff import pipe_client
from ost_visualizer.mcp_takeoff.pipe_client import (
    BUSY_RETRY_SECONDS,
    TakeoffPipeClient,
    read_session_token,
)


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

    def test_lone_surrogates_in_arguments_reach_the_app_as_ascii_json(self):
        client, result = self.call(
            b'{"success": true, "status": "ok", "data": {}}\n',
            command="list_text",
            arguments={"query": "\udc00 \u2265"},
        )
        payload = client.payloads[0]
        self.assertTrue(payload.isascii())
        self.assertEqual(json.loads(payload)["arguments"], {"query": "\udc00 \u2265"})
        self.assertTrue(result["success"])

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

    def test_the_token_is_read_again_on_every_call(self):
        client = ScriptedPipeClient(
            self.token_path, b'{"success": true, "status": "ok", "data": {}}\n'
        )
        with patch("sys.platform", "win32"):
            client.call("list_sheets", {})
            self.token_path.write_text("secret-token-2\n", encoding="utf-8")
            client.call("list_sheets", {})
        self.assertEqual(
            [json.loads(payload)["token"] for payload in client.payloads],
            ["secret-token-1", "secret-token-2"],
        )

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
        self.assertLess(elapsed, 1.0)
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


class RealPipeTests(unittest.TestCase):
    def setUp(self):
        import uuid

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.token_path = Path(directory.name) / "session.token"
        self.token_path.write_text("secret-token-1", encoding="utf-8")
        self.server_name = f"OstvTakeoffPipeTest-{uuid.uuid4().hex[:12]}"

    def create_pipe(self, access=None, in_buffer=65536):
        import win32pipe

        handle = win32pipe.CreateNamedPipe(
            "\\\\.\\pipe\\" + self.server_name,
            win32pipe.PIPE_ACCESS_DUPLEX if access is None else access,
            win32pipe.PIPE_TYPE_BYTE
            | win32pipe.PIPE_READMODE_BYTE
            | win32pipe.PIPE_WAIT,
            1,
            65536,
            in_buffer,
            0,
            None,
        )
        self.addCleanup(handle.Close)
        return handle

    def serve(self, script, read_request=True, in_buffer=65536):
        import threading
        import win32file
        import win32pipe

        handle = self.create_pipe(in_buffer=in_buffer)
        events = []
        finished = threading.Event()

        def run():
            try:
                win32pipe.ConnectNamedPipe(handle, None)
                if read_request:
                    events.append(win32file.ReadFile(handle, 65536)[1])
                script(handle, events)
            finally:
                finished.set()

        threading.Thread(target=run, daemon=True).start()
        return handle, events, finished

    def call(self):
        import threading

        client = TakeoffPipeClient(
            self.token_path, server_name=self.server_name, read_timeout_s=5.0
        )
        results = []
        caller = threading.Thread(
            target=lambda: results.append(client.call("list_sheets", {})),
            daemon=True,
        )
        caller.start()
        caller.join(10)
        self.assertFalse(caller.is_alive(), "the pipe client never returned")
        return results[0]

    def test_a_reply_longer_than_one_read_chunk_is_read_whole(self):
        import win32file

        text = "x" * 200000

        def reply(handle, _events):
            win32file.WriteFile(
                handle,
                b'{"success": true, "status": "ok", "data": "'
                + text.encode("ascii")
                + b'"}\n',
            )
            win32file.FlushFileBuffers(handle)

        _handle, _events, finished = self.serve(reply)
        self.assertEqual(self.call()["data"], text)
        self.assertTrue(finished.wait(5))

    def test_a_reply_written_in_pieces_is_joined(self):
        import win32file

        def reply(handle, events):
            for piece in (b"{", b'"success": true, "status": "ok", "data": 7}\n'):
                win32file.WriteFile(handle, piece)
                win32file.FlushFileBuffers(handle)
                events.append(piece)

        _handle, events, finished = self.serve(reply)
        self.assertEqual(self.call()["data"], 7)
        self.assertTrue(finished.wait(5))
        self.assertEqual(len(events), 3)

    def test_a_reply_without_a_newline_is_used_when_the_app_closes_the_pipe(self):
        import win32file

        def reply(handle, _events):
            win32file.WriteFile(handle, b'{"success": true, "status": "ok", "data": 3}')
            win32file.FlushFileBuffers(handle)
            handle.Close()

        _handle, _events, finished = self.serve(reply)
        self.assertEqual(self.call()["data"], 3)
        self.assertTrue(finished.wait(5))

    def test_an_app_that_closes_without_replying_is_not_running(self):
        _handle, _events, finished = self.serve(lambda handle, _events: handle.Close())
        result = self.call()
        self.assertEqual(result["status"], "app_not_running")
        self.assertTrue(finished.wait(5))

    def test_a_request_the_app_never_accepts_is_not_running(self):
        import win32file

        def reply_and_close(handle, _events):
            win32file.WriteFile(
                handle, b'{"success": true, "status": "ok", "data": 5}\n'
            )
            handle.Close()

        _handle, _events, finished = self.serve(
            reply_and_close, read_request=False, in_buffer=0
        )
        result = self.call()
        self.assertEqual(result["status"], "app_not_running")
        self.assertTrue(finished.wait(5))

    def test_the_client_closes_its_end_of_the_pipe_after_each_call(self):
        import pywintypes
        import win32file
        import win32pipe

        def reply(handle, _events):
            win32file.WriteFile(
                handle, b'{"success": true, "status": "ok", "data": 1}\n'
            )

        handle, _events, finished = self.serve(reply)
        self.assertEqual(self.call()["data"], 1)
        self.assertTrue(finished.wait(5))
        with self.assertRaises(pywintypes.error) as raised:
            win32pipe.PeekNamedPipe(handle, 0)
        self.assertEqual(raised.exception.winerror, 109)

    def hold_the_only_instance(self):
        import threading
        import win32file
        import win32pipe

        handle = self.create_pipe()
        connected = threading.Event()

        def accept():
            win32pipe.ConnectNamedPipe(handle, None)
            connected.set()

        threading.Thread(target=accept, daemon=True).start()
        holder = win32file.CreateFile(
            "\\\\.\\pipe\\" + self.server_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        self.assertTrue(connected.wait(5))
        return handle, holder

    def busy_client(self, busy_retry_s):
        return TakeoffPipeClient(
            self.token_path,
            server_name=self.server_name,
            wait_timeout_ms=100,
            read_timeout_s=5.0,
            busy_retry_s=busy_retry_s,
        )

    def test_a_pipe_whose_instances_are_all_in_use_is_busy_not_missing(self):
        import time

        _handle, holder = self.hold_the_only_instance()
        self.addCleanup(holder.Close)
        client = self.busy_client(0.5)
        started = time.monotonic()
        result = self.call_in_thread(client)
        elapsed = time.monotonic() - started
        self.assertEqual(result["status"], "busy")
        self.assertIn("busy", result["error"]["message"])
        self.assertNotIn("not running", result["error"]["message"])
        self.assertGreaterEqual(elapsed, 0.5)
        self.assertLess(elapsed, 2.0)

    def test_a_busy_pipe_that_frees_up_during_the_retry_is_answered(self):
        import threading
        import win32file
        import win32pipe

        handle, holder = self.hold_the_only_instance()
        answered = threading.Event()

        def release_then_answer():
            holder.Close()
            win32pipe.DisconnectNamedPipe(handle)
            win32pipe.ConnectNamedPipe(handle, None)
            win32file.ReadFile(handle, 65536)
            win32file.WriteFile(
                handle, b'{"success": true, "status": "ok", "data": 4}\n'
            )
            win32file.FlushFileBuffers(handle)
            answered.set()

        client = self.busy_client(5.0)
        results = []
        caller = threading.Thread(
            target=lambda: results.append(client.call("list_sheets", {})), daemon=True
        )
        caller.start()
        caller.join(0.3)
        self.assertTrue(caller.is_alive())
        threading.Thread(target=release_then_answer, daemon=True).start()
        caller.join(10)
        self.assertFalse(caller.is_alive())
        self.assertTrue(answered.wait(5))
        self.assertEqual(results[0]["data"], 4)

    def test_the_default_busy_retry_is_two_seconds(self):
        self.assertEqual(TakeoffPipeClient(self.token_path).busy_retry_s, 2.0)
        self.assertEqual(BUSY_RETRY_SECONDS, 2.0)

    def test_an_instance_taken_between_wait_and_open_is_retried(self):
        import ctypes
        import win32pipe

        server = self.create_pipe()
        real = pipe_client._kernel32()
        attempts = []

        class RacingKernel32:
            def __getattr__(self, name):
                return getattr(real, name)

            def CreateFileW(self, *arguments):
                attempts.append(arguments[0])
                if len(attempts) == 1:
                    ctypes.set_last_error(231)
                    return pipe_client._INVALID_HANDLE_VALUE
                return real.CreateFileW(*arguments)

        import threading
        import pywintypes
        import win32file

        finished = threading.Event()

        def answer():
            try:
                win32pipe.ConnectNamedPipe(server, None)
                win32file.ReadFile(server, 65536)
                win32file.WriteFile(
                    server, b'{"success": true, "status": "ok", "data": 6}\n'
                )
                win32file.FlushFileBuffers(server)
            except pywintypes.error:
                pass
            finally:
                finished.set()

        def release_a_pending_accept():
            if finished.is_set():
                return
            try:
                win32file.CreateFile(
                    "\\\\.\\pipe\\" + self.server_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0,
                    None,
                    win32file.OPEN_EXISTING,
                    0,
                    None,
                ).Close()
            except pywintypes.error:
                pass
            finished.wait(5)

        self.addCleanup(release_a_pending_accept)
        threading.Thread(target=answer, daemon=True).start()
        with patch.object(pipe_client, "_kernel32", RacingKernel32):
            result = self.call_in_thread(self.busy_client(5.0))
        self.assertEqual(result["data"], 6)
        self.assertEqual(len(attempts), 2)

    def test_an_instance_that_stays_taken_after_every_wait_is_busy(self):
        import ctypes

        self.create_pipe()
        real = pipe_client._kernel32()

        class AlwaysTakenKernel32:
            def __getattr__(self, name):
                return getattr(real, name)

            def CreateFileW(self, *_arguments):
                ctypes.set_last_error(231)
                return pipe_client._INVALID_HANDLE_VALUE

        with patch.object(pipe_client, "_kernel32", AlwaysTakenKernel32):
            result = self.call_in_thread(self.busy_client(0.3))
        self.assertEqual(result["status"], "busy")

    def call_in_thread(self, client):
        import threading

        results = []
        caller = threading.Thread(
            target=lambda: results.append(client.call("list_sheets", {})), daemon=True
        )
        caller.start()
        caller.join(10)
        self.assertFalse(caller.is_alive(), "the pipe client never returned")
        return results[0]

    def test_no_server_is_still_app_not_running_without_waiting_for_busy(self):
        import time

        client = self.busy_client(5.0)
        started = time.monotonic()
        self.assertEqual(client.call("list_sheets", {})["status"], "app_not_running")
        self.assertLess(time.monotonic() - started, 1.0)

    def test_a_pipe_the_client_may_not_open_is_app_not_running(self):
        import win32pipe

        self.create_pipe(access=win32pipe.PIPE_ACCESS_INBOUND)
        self.assertEqual(self.call()["status"], "app_not_running")


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

    def test_tokens_of_up_to_two_hundred_characters_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.token"
            path.write_text(" " + "t" * 200 + "\n", encoding="utf-8")
            self.assertEqual(read_session_token(path), "t" * 200)
            path.write_text("t" * 201, encoding="utf-8")
            self.assertIsNone(read_session_token(path))


if __name__ == "__main__":
    unittest.main()
