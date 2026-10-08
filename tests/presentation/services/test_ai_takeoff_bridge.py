import contextlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.ai_takeoff_dtos import (
    M1A_COMMAND_ARGUMENTS,
    M1A_COMMANDS,
    AiTakeoffRequestError,
    CropPlan,
    PageSnapshot,
    ok_result,
)
from ost_visualizer.mcp_takeoff.pipe_client import PipeReadTimeout, TakeoffPipeClient
from ost_visualizer.presentation.services.ai_takeoff_bridge import (
    TakeoffCommandBridge,
    ai_takeoff_session_token_path,
)
from ost_visualizer.presentation.services.ai_takeoff_write_commands import DeferredReply
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtNetwork import QLocalSocket
from shiboken6 import isValid


class FakeReadService:
    def __init__(self):
        self.calls = []
        self.threads = {}

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))
        self.threads[name] = threading.get_ident()

    def list_sheets(self, bid_uid=None, cursor=None, limit=None):
        self._record("list_sheets", bid_uid=bid_uid, cursor=cursor, limit=limit)
        return ok_result({"sheets": []})

    def get_quantities(self, bid_uid=None, group_by="condition"):
        self._record("get_quantities", bid_uid=bid_uid, group_by=group_by)
        if group_by == "level":
            raise AiTakeoffRequestError(
                "invalid_argument", "group_by must be condition or page"
            )
        return ok_result({"rows": []})

    def list_levels(self, bid_uid=None):
        self._record("list_levels", bid_uid=bid_uid)
        return ok_result({"sidecar_status": "empty", "levels": []})

    def list_assumptions(self, bid_uid=None, status=None):
        self._record("list_assumptions", bid_uid=bid_uid, status=status)
        return ok_result({"sidecar_status": "empty", "assumptions": []})

    def page_snapshot(self, page_uid):
        self._record("page_snapshot", page_uid=page_uid)
        if page_uid == "missing":
            raise AiTakeoffRequestError("not_found", "Unknown page_uid")
        if page_uid == "raster":
            return PageSnapshot(page_uid, "C:/scan.tif", 0, 0.0, 0.0, None, False)
        return PageSnapshot(page_uid, "C:/p.pdf", 0, 200.0, 100.0, 0.5, True)

    def plan_crop(self, snapshot, crop_pts=None, dpi=None):
        self._record("plan_crop", crop_pts=crop_pts, dpi=dpi)
        return CropPlan(
            snapshot.uid,
            "C:/p.pdf",
            0,
            (0.0, 0.0, 20.0, 10.0),
            1.0,
            20,
            10,
            (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
            (0.5, 0.0, 0.0, 0.5, 0.0, 0.0),
        )

    @staticmethod
    def overlay_status(overlay_ids):
        return None if overlay_ids is None else "not_supported_until_m1b"

    def list_text(self, snapshot, bbox_pts=None, query=None, cursor=None, limit=None):
        self._record("list_text", page_uid=snapshot.uid, query=query)
        return ok_result({"runs": []})

    def list_segments(self, snapshot, bbox_pts=None, cursor=None, limit=None):
        self._record("list_segments", page_uid=snapshot.uid)
        return ok_result({"segments": []})


class FakePdfSource:
    def __init__(self):
        self.render_threads = []

    def render_frame(self, file_path, page_index, scale, frame_pts):
        self.render_threads.append(threading.get_ident())
        image = QtGui.QImage(20, 10, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("white"))
        return image


class BridgeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.token_path = self.directory / "ai_takeoff" / "session.token"
        self.server_name = f"OstvTakeoffBridgeTest-{uuid.uuid4().hex[:12]}"
        self.service = FakeReadService()
        self.pdf = FakePdfSource()
        self.allowed = True
        self.tokens = iter(f"token-{index}" for index in range(100))
        self.bridge = self.make_bridge()
        self.assertTrue(self.bridge.start())
        self.addCleanup(lambda: self.bridge.cleanup())

    def make_bridge(self):
        return TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: self.allowed,
            token_path=self.token_path,
            server_name=self.server_name,
            token_factory=lambda: next(self.tokens),
        )

    def client(self, token_path=None):
        return TakeoffPipeClient(
            token_path or self.token_path,
            server_name=self.server_name,
            wait_timeout_ms=500,
        )

    def run_threaded(self, function):
        results = []
        thread = threading.Thread(target=lambda: results.append(function()))
        thread.start()
        deadline = time.monotonic() + 15
        while thread.is_alive() and time.monotonic() < deadline:
            self.wait_events()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        return results[0]

    def wait_events(self, milliseconds=5):
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    @contextlib.contextmanager
    def slot_errors(self):
        errors = []
        with patch.object(
            sys, "excepthook", lambda kind, value, trace: errors.append(value)
        ):
            yield errors

    def delete_later_now(self):
        QtCore.QCoreApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete
        )

    def call(self, command, arguments=None, token_path=None):
        client = self.client(token_path)
        return self.run_threaded(lambda: client.call(command, arguments or {}))

    def raw(self, payload: bytes):
        client = TakeoffPipeClient(
            self.token_path,
            server_name=self.server_name,
            wait_timeout_ms=500,
            read_timeout_s=5,
        )
        return json.loads(self.run_threaded(lambda: client._exchange(payload)))

    def other_token_file(self, token):
        path = self.directory / f"other-{token}.token"
        path.write_text(token, encoding="utf-8")
        return path

    def capped_bridge(self, **options):
        self.server_name = f"OstvTakeoffCapTest-{uuid.uuid4().hex[:12]}"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.token_path,
            server_name=self.server_name,
            token_factory=lambda: "capped-token",
            **options,
        )
        self.assertTrue(bridge.start())
        self.addCleanup(bridge.cleanup)
        return bridge

    def pump_until(self, condition, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.wait_events()
        self.assertTrue(condition())

    def open_raw(self):
        import win32file

        return win32file.CreateFile(
            "\\\\.\\pipe\\" + self.server_name,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )

    def write_raw(self, handle, payload):
        import win32file

        self.run_threaded(lambda: win32file.WriteFile(handle, payload))

    def read_raw_until_closed(self, handle):
        import win32file

        def read():
            chunks = []
            while True:
                try:
                    chunks.append(bytes(win32file.ReadFile(handle, 65536)[1]))
                except Exception:
                    return b"".join(chunks)

        return self.run_threaded(read)

    def read_raw(self, handle, first_write=b""):
        return json.loads(self.read_raw_bytes(handle, first_write))

    def read_raw_bytes(self, handle, first_write=b""):
        import win32file

        def read():
            if first_write:
                win32file.WriteFile(handle, first_write)
            chunks = []
            while True:
                try:
                    chunk = win32file.ReadFile(handle, 65536)[1]
                except Exception:
                    break
                chunks.append(bytes(chunk))
                if chunk.endswith(b"\n"):
                    break
            return b"".join(chunks)

        return self.run_threaded(read)


class BridgeProtocolTests(BridgeTestCase):
    def test_round_trip_passes_declared_arguments(self):
        result = self.call("list_sheets", {"limit": 5, "cursor": "c:5"})
        self.assertEqual(result, ok_result({"sheets": []}))
        self.assertEqual(
            self.service.calls,
            [("list_sheets", {"bid_uid": None, "cursor": "c:5", "limit": 5})],
        )

    def test_token_file_holds_the_current_token_only(self):
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "token-0")
        self.assertEqual(
            sorted(p.name for p in self.token_path.parent.iterdir()), ["session.token"]
        )

    def test_command_table_is_exactly_the_seven_read_only_tools(self):
        self.assertEqual(tuple(self.bridge.commands), M1A_COMMANDS)
        self.assertEqual(set(M1A_COMMAND_ARGUMENTS), set(M1A_COMMANDS))

    def test_undeclared_commands_never_reach_the_service(self):
        for command in (
            "update_assumption",
            "apply_changeset",
            "approve_changeset",
            "accept_assumption",
            "get_context",
            "page_snapshot",
            "_sidecar",
            "",
        ):
            with self.subTest(command=command):
                result = self.call(command, {"uid": "A1", "status": "accepted"})
                self.assertEqual(result["status"], "unknown_command")
        self.assertEqual(self.service.calls, [])

    def test_unknown_or_malformed_arguments_are_rejected(self):
        bad = self.call("list_assumptions", {"status": "accepted", "approve": True})
        self.assertEqual(bad["status"], "invalid_argument")
        not_object = self.raw(
            json.dumps(
                {"token": "token-0", "command": "list_sheets", "arguments": [1]}
            ).encode()
            + b"\n"
        )
        self.assertEqual(not_object["status"], "invalid_argument")
        broken = self.raw(b"{not json\n")
        self.assertEqual(broken["status"], "invalid_argument")
        self.assertEqual(self.service.calls, [])

    def test_assumption_status_is_only_a_read_filter(self):
        result = self.call("list_assumptions", {"status": "accepted"})
        self.assertTrue(result["success"])
        self.assertEqual(
            self.service.calls,
            [("list_assumptions", {"bid_uid": None, "status": "accepted"})],
        )

    def test_oversized_requests_are_refused(self):
        payload = (
            json.dumps(
                {
                    "token": "token-0",
                    "command": "list_text",
                    "arguments": {"page_uid": "p", "query": "x" * 70000},
                }
            ).encode()
            + b"\n"
        )
        self.assertEqual(self.raw(payload)["status"], "invalid_argument")
        self.assertEqual(self.service.calls, [])

    def test_results_with_lone_surrogates_are_still_delivered(self):
        self.service.list_levels = lambda bid_uid=None: ok_result(
            {"sidecar_status": "ok", "levels": [{"uid": "\ud800", "name": "x"}]}
        )
        response = self.call("list_levels")
        self.assertTrue(response["success"])
        self.assertEqual(response["data"]["levels"][0]["uid"], "\ud800")

    def test_deeply_nested_requests_get_an_error_instead_of_escaping_the_slot(self):
        for payload in (b"[" * 5000 + b"\n", b'{"token": ' + b"[" * 5000 + b"\n"):
            with self.subTest(size=len(payload)):
                self.assertEqual(self.raw(payload)["status"], "invalid_argument")
        self.assertEqual(self.service.calls, [])

    def test_a_worker_finishing_after_the_bridge_is_destroyed_raises_nothing(self):
        from shiboken6 import delete

        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.directory / "destroyed" / "session.token",
            server_name=self.server_name + "-destroyed",
        )
        delete(bridge)
        failures = []
        with patch.object(
            threading, "excepthook", lambda args: failures.append(repr(args.exc_value))
        ), self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.INFO
        ) as captured:
            worker = threading.Thread(
                target=lambda: bridge._run_worker_job(
                    None, ("list_sheets", {}), lambda: ok_result({})
                )
            )
            worker.start()
            worker.join(5)
        self.assertEqual(failures, [])
        self.assertEqual(
            captured.output,
            [
                "INFO:ost_visualizer.presentation.services.ai_takeoff_bridge:"
                "AI takeoff bridge closed before a command finished"
            ],
        )

    def test_service_errors_become_error_results(self):
        self.assertEqual(
            self.call("get_quantities", {"group_by": "level"})["status"],
            "invalid_argument",
        )
        self.assertEqual(
            self.call("list_text", {"page_uid": "missing"})["status"], "not_found"
        )


class BridgeCapacityTests(BridgeTestCase):
    def test_requests_beyond_the_worker_cap_get_busy_and_capacity_returns(self):
        self.capped_bridge(max_workers=2)
        release = threading.Event()
        started = []

        def blocking(snapshot, bbox_pts=None, cursor=None, limit=None):
            started.append(snapshot.uid)
            release.wait(10)
            return ok_result({"segments": []})

        self.service.list_segments = blocking
        results = {}
        workers = [
            threading.Thread(
                target=lambda n=n: results.__setitem__(
                    n, self.client().call("list_segments", {"page_uid": f"p{n}"})
                )
            )
            for n in range(2)
        ]
        for worker in workers:
            worker.start()
        self.pump_until(lambda: len(started) == 2)
        busy = self.call("list_segments", {"page_uid": "p9"})
        self.assertEqual(busy["status"], "busy")
        self.assertEqual(sorted(started), ["p0", "p1"])
        self.assertTrue(self.call("list_sheets")["success"])
        release.set()
        self.pump_until(lambda: len(results) == 2)
        for worker in workers:
            worker.join(5)
        self.assertTrue(all(result["success"] for result in results.values()))
        self.assertTrue(self.call("list_segments", {"page_uid": "p3"})["success"])
        self.assertIn("p3", started)

    def test_connections_beyond_the_cap_get_busy_until_one_closes(self):
        bridge = self.capped_bridge(max_connections=2, idle_timeout_ms=60000)
        idle = [self.open_raw(), self.open_raw()]
        self.pump_until(lambda: len(bridge._open_sockets) == 2)
        self.assertEqual(self.call("list_sheets")["status"], "busy")
        idle[0].Close()
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        self.assertTrue(self.call("list_sheets")["success"])
        idle[1].Close()

    def test_a_connection_that_never_finishes_its_request_is_closed(self):
        bridge = self.capped_bridge(idle_timeout_ms=200)
        handle = self.open_raw()
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        response = self.read_raw(
            handle, first_write=b'{"token": "capped-token", "command": "list_'
        )
        handle.Close()
        self.assertEqual(response["status"], "invalid_argument")
        self.assertIn("in time", response["error"]["message"])
        self.pump_until(lambda: not bridge._open_sockets)
        self.assertEqual(self.service.calls, [])

    def test_default_caps(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        self.assertEqual(ai_takeoff_bridge.MAX_CONCURRENT_WORKERS, 2)
        self.assertEqual(ai_takeoff_bridge.MAX_OPEN_CONNECTIONS, 8)
        self.assertEqual(ai_takeoff_bridge.IDLE_REQUEST_TIMEOUT_MS, 10000)


class BridgeSecurityTests(BridgeTestCase):
    def test_wrong_or_missing_token_is_unauthorized(self):
        wrong = self.call("list_sheets", token_path=self.other_token_file("guess"))
        self.assertEqual(wrong["status"], "unauthorized")
        missing = self.raw(
            json.dumps({"command": "list_sheets", "arguments": {}}).encode() + b"\n"
        )
        self.assertEqual(missing["status"], "unauthorized")
        self.assertEqual(self.service.calls, [])

    def test_a_token_that_cannot_be_utf8_encoded_is_unauthorized(self):
        client = TakeoffPipeClient(
            self.token_path,
            server_name=self.server_name,
            wait_timeout_ms=500,
            read_timeout_s=3,
        )
        payload = b'{"token": "\\ud800", "command": "list_sheets", "arguments": {}}\n'

        def exchange():
            try:
                return json.loads(client._exchange(payload))
            except PipeReadTimeout:
                return {"status": "no answer"}

        self.assertEqual(self.run_threaded(exchange)["status"], "unauthorized")
        self.assertEqual(self.service.calls, [])
        self.assertTrue(self.call("list_sheets")["success"])

    def test_a_token_from_a_previous_session_is_stale(self):
        stale = self.other_token_file("token-0")
        self.bridge.cleanup()
        self.bridge = self.make_bridge()
        self.assertTrue(self.bridge.start())
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "token-1")
        self.assertEqual(
            self.call("list_sheets", token_path=stale)["status"], "unauthorized"
        )
        self.assertTrue(self.call("list_sheets")["success"])

    def test_feature_denied_when_ai_takeoff_is_not_allowed(self):
        self.allowed = False
        self.assertEqual(self.call("list_sheets")["status"], "feature_denied")
        self.assertEqual(self.service.calls, [])

    def test_the_token_never_appears_in_logs_responses_or_files(self):
        with self.assertLogs(level=logging.DEBUG) as captured:
            logging.getLogger("ost_visualizer").debug("log capture started")
            responses = [
                self.call("list_sheets"),
                self.call("update_assumption", {"status": "accepted"}),
                self.call("list_sheets", token_path=self.other_token_file("guess")),
                self.raw(b"{not json\n"),
            ]
        self.assertNotIn("token-0", "\n".join(captured.output))
        self.assertNotIn("token-0", json.dumps(responses))
        files = [p for p in self.directory.rglob("*") if p.is_file()]
        holders = [
            p
            for p in files
            if "token-0" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertEqual(holders, [self.token_path])

    def test_pipe_access_list_grants_only_the_current_user(self):
        import win32api
        import win32con
        import win32file
        import win32security

        process_token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
        )
        current_user = win32security.GetTokenInformation(
            process_token, win32security.TokenUser
        )[0]
        handle = win32file.CreateFile(
            "\\\\.\\pipe\\" + self.server_name,
            win32con.READ_CONTROL,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None,
        )
        try:
            descriptor = win32security.GetSecurityInfo(
                handle,
                win32security.SE_KERNEL_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
        finally:
            handle.Close()
        dacl = descriptor.GetSecurityDescriptorDacl()
        sids = [
            win32security.ConvertSidToStringSid(dacl.GetAce(index)[2])
            for index in range(dacl.GetAceCount())
        ]
        self.assertEqual(sids, [win32security.ConvertSidToStringSid(current_user)])

    def test_cleanup_removes_the_token_and_stops_listening(self):
        self.bridge.cleanup()
        self.assertFalse(self.token_path.exists())
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text("token-0", encoding="utf-8")
        self.assertEqual(self.call("list_sheets")["status"], "app_not_running")

    def test_cleanup_keeps_a_token_file_written_by_another_session(self):
        self.token_path.write_text("someone-else", encoding="utf-8")
        self.bridge.cleanup()
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "someone-else")

    def test_cleanup_keeps_a_token_file_that_is_not_text_and_still_stops(self):
        self.token_path.write_bytes(b"\xff\xfe")
        self.bridge.cleanup()
        self.assertEqual(self.token_path.read_bytes(), b"\xff\xfe")
        self.assertEqual(self.call("list_sheets")["status"], "app_not_running")


class BridgeThreadingTests(BridgeTestCase):
    def test_pdf_work_runs_off_the_gui_thread(self):
        gui_thread = threading.get_ident()
        self.assertTrue(
            self.call("list_text", {"page_uid": "p1", "query": "slab"})["success"]
        )
        self.assertTrue(self.call("list_segments", {"page_uid": "p1"})["success"])
        rendered = self.call(
            "render_sheet", {"page_uid": "p1", "dpi": 72, "overlay_ids": ["r1"]}
        )
        self.assertTrue(rendered["success"])
        self.assertNotEqual(self.service.threads["list_text"], gui_thread)
        self.assertNotEqual(self.service.threads["list_segments"], gui_thread)
        self.assertNotIn(gui_thread, self.pdf.render_threads)
        self.assertEqual(self.service.threads["page_snapshot"], gui_thread)
        self.assertEqual(self.service.threads["plan_crop"], gui_thread)
        data = rendered["data"]
        self.assertEqual(data["overlay_status"], "not_supported_until_m1b")
        self.assertEqual(data["image"]["width_px"], 20)
        self.assertTrue(data["image"]["png_base64"])

    def test_raster_pages_answer_not_pdf_without_planning_a_crop(self):
        result = self.call("render_sheet", {"page_uid": "raster", "overlay_ids": []})
        self.assertEqual(result["status"], "not_pdf")
        self.assertIsNone(result["data"]["image"])
        self.assertNotIn("plan_crop", [name for name, _ in self.service.calls])
        self.assertEqual(self.pdf.render_threads, [])

    def test_model_reads_stay_on_the_gui_thread(self):
        gui_thread = threading.get_ident()
        for command in (
            "list_sheets",
            "get_quantities",
            "list_levels",
            "list_assumptions",
        ):
            self.assertTrue(self.call(command)["success"])
            self.assertEqual(self.service.threads[command], gui_thread)


class DeferredWriteCommands:
    def __init__(self):
        self.replies = []

    def handlers(self):
        return {"apply_changeset": self._apply}

    def _apply(self, arguments):
        reply = DeferredReply()
        self.replies.append(reply)
        return reply


class BlockingSegments:
    def __init__(self):
        self.started = []
        self.daemon = []
        self.releases = {}
        self.lock = threading.Lock()

    def release(self, page_uid):
        with self.lock:
            self.releases.setdefault(page_uid, threading.Event()).set()

    def __call__(self, snapshot, bbox_pts=None, cursor=None, limit=None):
        with self.lock:
            event = self.releases.setdefault(snapshot.uid, threading.Event())
        self.daemon.append(threading.current_thread().daemon)
        self.started.append(snapshot.uid)
        event.wait(10)
        return ok_result({"segments": [snapshot.uid]})


class BridgeStartupTests(BridgeTestCase):
    def test_session_token_path_lives_in_the_app_data_folder(self):
        path = ai_takeoff_session_token_path()
        self.assertEqual(
            path.relative_to(Path.home()).parts,
            (".ost_visualizer", "ai_takeoff", "session.token"),
        )

    def test_request_size_cap_is_64_kib(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        self.assertEqual(ai_takeoff_bridge.MAX_REQUEST_BYTES, 65536)

    def test_default_token_is_a_fresh_32_byte_urlsafe_secret(self):
        token_path = self.directory / "default" / "session.token"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=token_path,
            server_name=self.server_name + "-default",
        )
        self.addCleanup(bridge.cleanup)
        self.assertTrue(bridge.start())
        token = token_path.read_text(encoding="utf-8")
        self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")

    def test_start_creates_missing_parent_folders(self):
        token_path = self.directory / "deep" / "nested" / "session.token"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=token_path,
            server_name=self.server_name + "-deep",
            token_factory=lambda: "deep-token",
        )
        self.addCleanup(bridge.cleanup)
        self.assertTrue(bridge.start())
        self.assertEqual(token_path.read_text(encoding="utf-8"), "deep-token")

    def test_start_after_cleanup_reports_failure(self):
        self.bridge.cleanup()
        self.assertIs(self.bridge.start(), False)
        self.assertFalse(self.token_path.exists())

    def test_start_reports_failure_when_the_pipe_cannot_listen(self):
        token_path = self.directory / "unnamed" / "session.token"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=token_path,
            server_name="",
            token_factory=lambda: "unnamed-token",
        )
        self.addCleanup(bridge.cleanup)
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.WARNING
        ) as captured:
            self.assertIs(bridge.start(), False)
        self.assertEqual(
            captured.output,
            [
                "WARNING:ost_visualizer.presentation.services.ai_takeoff_bridge:"
                "Failed to start the AI takeoff bridge"
            ],
        )
        self.assertFalse(token_path.exists())

    def test_start_closes_the_pipe_when_the_token_cannot_be_written(self):
        blocker = self.directory / "blocker"
        blocker.write_text("not a folder", encoding="utf-8")
        name = self.server_name + "-blocked"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=blocker / "session.token",
            server_name=name,
            token_factory=lambda: "blocked-token",
        )
        self.addCleanup(bridge.cleanup)
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.WARNING
        ) as captured:
            self.assertIs(bridge.start(), False)
        self.assertEqual(len(captured.output), 1)
        self.assertIn(
            "Failed to write the AI takeoff session token", captured.output[0]
        )
        self.assertNotIn("blocked-token", captured.output[0])
        self.server_name = name
        result = self.call(
            "list_sheets", token_path=self.other_token_file("blocked-token")
        )
        self.assertEqual(result["status"], "app_not_running")

    def test_cleanup_of_a_never_started_bridge_ignores_an_unreadable_token_file(self):
        token_path = self.directory / "garbled" / "session.token"
        token_path.parent.mkdir(parents=True)
        token_path.write_bytes(b"\xff\xfe\x00garbled")
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=token_path,
            server_name=self.server_name + "-garbled",
        )
        bridge.cleanup()
        self.assertEqual(token_path.read_bytes(), b"\xff\xfe\x00garbled")


class BridgeConnectionLifecycleTests(BridgeTestCase):
    def test_handling_connections_raises_nothing_in_qt_slots(self):
        with self.slot_errors() as errors:
            self.assertTrue(self.call("list_sheets")["success"])
            self.assertTrue(self.call("list_levels")["success"])
        self.assertEqual(errors, [])

    def test_the_bridge_hangs_up_after_answering(self):
        bridge = self.capped_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        response = self.read_raw(
            handle,
            first_write=b'{"token": "capped-token", "command": "list_sheets"}\n',
        )
        self.assertTrue(response["success"])
        self.pump_until(lambda: not bridge._open_sockets, timeout=5)

    def test_a_client_that_hangs_up_mid_request_is_forgotten_and_deleted(self):
        bridge = self.capped_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.write_raw(handle, b'{"token": "capped-token", "comm')
        self.pump_until(lambda: any(bridge._buffers.values()))
        handle.Close()
        self.pump_until(lambda: not bridge._open_sockets)
        self.assertEqual(bridge._buffers, {})
        self.delete_later_now()
        self.assertEqual(bridge.findChildren(QLocalSocket), [])
        self.assertEqual(self.service.calls, [])

    def test_a_refused_extra_connection_is_deleted_once_the_client_leaves(self):
        bridge = self.capped_bridge(max_connections=1, idle_timeout_ms=60000)
        idle = self.open_raw()
        self.addCleanup(idle.Close)
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        self.assertEqual(self.call("list_sheets")["status"], "busy")

        def only_the_idle_socket_remains():
            self.delete_later_now()
            return len(bridge.findChildren(QLocalSocket)) == 1

        self.pump_until(only_the_idle_socket_remains, timeout=5)

    def test_cleanup_aborts_open_connections_and_drops_their_state(self):
        bridge = self.capped_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        self.write_raw(handle, b'{"token": "capped-token"')
        self.pump_until(lambda: any(bridge._buffers.values()))
        sockets = bridge.findChildren(QLocalSocket)
        self.assertEqual(len(sockets), 1)
        bridge.cleanup()
        self.assertEqual(
            sockets[0].state(), QLocalSocket.LocalSocketState.UnconnectedState
        )
        self.assertEqual(bridge._buffers, {})
        self.assertEqual(bridge._open_sockets, set())
        self.delete_later_now()
        self.assertFalse(isValid(sockets[0]))

    def test_cleanup_tolerates_a_connection_signal_that_is_already_detached(self):
        self.bridge._server.newConnection.disconnect(self.bridge._on_new_connection)
        with self.assertWarns(RuntimeWarning):
            self.bridge.cleanup()
        self.assertFalse(self.token_path.exists())
        self.assertEqual(self.call("list_sheets")["status"], "app_not_running")

    def test_connection_cap_has_a_floor_of_one(self):
        bridge = self.capped_bridge(max_connections=0, idle_timeout_ms=60000)
        idle = self.open_raw()
        self.addCleanup(idle.Close)
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        self.assertEqual(self.call("list_sheets")["status"], "busy")


class BridgeRequestEdgeTests(BridgeTestCase):
    def padded_request(self, total_bytes):
        base = {
            "token": "token-0",
            "command": "list_text",
            "arguments": {"page_uid": "p", "query": ""},
        }
        overhead = len(json.dumps(base).encode()) + 1
        base["arguments"]["query"] = "q" * (total_bytes - overhead)
        payload = json.dumps(base).encode() + b"\n"
        self.assertEqual(len(payload), total_bytes)
        return payload

    def test_a_request_of_exactly_the_size_cap_is_accepted(self):
        self.assertTrue(self.raw(self.padded_request(65536))["success"])
        self.assertEqual(
            self.raw(self.padded_request(65537))["status"], "invalid_argument"
        )
        self.assertEqual(
            [name for name, _ in self.service.calls], ["page_snapshot", "list_text"]
        )

    def test_an_oversized_request_is_answered_exactly_once(self):
        bridge = self.capped_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        with self.slot_errors() as errors:
            self.write_raw(handle, b"x" * 65537)
            self.pump_until(lambda: not bridge._buffers)
            try:
                self.write_raw(handle, b"y" * 1024 + b"\n")
            except Exception:
                pass
            response = self.read_raw_until_closed(handle)
        self.assertEqual(errors, [])
        self.assertEqual(response.count(b"\n"), 1)
        self.assertEqual(json.loads(response)["error"]["message"], "Request too large.")

    def test_well_formed_json_that_is_not_an_object_is_malformed(self):
        for payload in (b"[1]\n", b"null\n", b'"list_sheets"\n', b"7\n"):
            with self.subTest(payload=payload):
                response = self.raw(payload)
                self.assertEqual(response["status"], "invalid_argument")
                self.assertEqual(response["error"]["message"], "Malformed request.")
        self.assertEqual(self.service.calls, [])

    def test_missing_arguments_mean_no_arguments(self):
        response = self.raw(b'{"token": "token-0", "command": "list_levels"}\n')
        self.assertTrue(response["success"])
        self.assertEqual(self.service.calls, [("list_levels", {"bid_uid": None})])

    def test_unexpected_gui_thread_failures_are_logged_and_answered(self):
        def broken(**_kwargs):
            raise ValueError("secret detail")

        self.service.list_sheets = broken
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.ERROR
        ) as captured:
            response = self.call("list_sheets")
        self.assertEqual(response["status"], "unexpected_error")
        self.assertEqual(response["error"]["message"], "The command failed.")
        self.assertIn("AI takeoff command failed: ValueError", captured.output[0])

    def test_worker_failures_are_logged_and_answered(self):
        def broken(snapshot, bbox_pts=None, cursor=None, limit=None):
            raise ValueError("secret detail")

        self.service.list_segments = broken
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.ERROR
        ) as captured:
            response = self.call("list_segments", {"page_uid": "p1"})
        self.assertEqual(response["status"], "unexpected_error")
        self.assertIn("AI takeoff worker job failed: ValueError", captured.output[0])

    def test_worker_request_errors_keep_their_code(self):
        def missing(snapshot, bbox_pts=None, cursor=None, limit=None):
            raise AiTakeoffRequestError("not_found", "No such segment page")

        self.service.list_segments = missing
        response = self.call("list_segments", {"page_uid": "p1"})
        self.assertEqual(response["status"], "not_found")
        self.assertEqual(response["error"]["message"], "No such segment page")

    def test_a_failed_render_reports_the_render_status(self):
        self.pdf.render_frame = lambda *args: None
        response = self.call("render_sheet", {"page_uid": "p1"})
        self.assertEqual(response["status"], "unavailable")
        self.assertIsNone(response["data"]["image"])

    def test_a_failing_audit_is_logged_and_the_reply_still_arrives(self):
        def audit(tool, arguments, outcome):
            raise ValueError("disk full")

        self.capped_bridge(audit=audit)
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.WARNING
        ) as captured:
            self.assertTrue(self.call("list_sheets")["success"])
        self.assertEqual(
            captured.output,
            [
                "WARNING:ost_visualizer.presentation.services.ai_takeoff_bridge:"
                "AI takeoff audit failed: ValueError"
            ],
        )

    def test_rebind_is_suggested_only_for_rebind_required_results(self):
        emitted = []
        self.bridge.rebind_suggested.connect(lambda: emitted.append(True))
        self.assertTrue(self.call("list_levels")["success"])
        self.assertTrue(self.call("list_sheets")["success"])
        self.assertEqual(emitted, [])
        self.service.list_levels = lambda bid_uid=None: ok_result(
            {"sidecar_status": "rebind_required", "levels": []}
        )
        self.assertTrue(self.call("list_levels")["success"])
        self.assertEqual(emitted, [True])

    def test_data_that_is_not_an_object_never_suggests_a_rebind(self):
        emitted = []
        self.bridge.rebind_suggested.connect(lambda: emitted.append(True))
        self.service.list_sheets = lambda **_kwargs: ok_result(["rebind_required"])
        with self.slot_errors() as errors:
            self.assertTrue(self.call("list_sheets")["success"])
        self.assertEqual(errors, [])
        self.assertEqual(emitted, [])


class BridgeWorkerLifecycleTests(BridgeTestCase):
    def setUp(self):
        super().setUp()
        self.blocking = BlockingSegments()
        self.service.list_segments = self.blocking
        self.audited = []
        self.addCleanup(self.release_all)

    def release_all(self):
        for page in range(10):
            self.blocking.release(f"p{page}")

    def audited_bridge(self, **options):
        return self.capped_bridge(
            audit=lambda tool, arguments, outcome: self.audited.append((tool, outcome)),
            **options,
        )

    def start_call(self, command, arguments):
        results = []
        client = self.client()
        thread = threading.Thread(
            target=lambda: results.append(client.call(command, arguments))
        )
        thread.start()
        self.addCleanup(thread.join, 10)
        return results

    def test_workers_are_daemon_threads(self):
        self.audited_bridge()
        results = self.start_call("list_segments", {"page_uid": "p0"})
        self.pump_until(lambda: self.blocking.started == ["p0"])
        self.blocking.release("p0")
        self.pump_until(lambda: len(results) == 1)
        self.assertTrue(results[0]["success"])
        self.assertEqual(self.blocking.daemon, [True])

    def test_a_single_worker_slot_is_freed_after_each_job(self):
        self.audited_bridge(max_workers=1)
        for page in ("p0", "p1", "p2"):
            self.blocking.release(page)
            self.assertTrue(self.call("list_segments", {"page_uid": page})["success"])
        self.assertEqual(self.blocking.started, ["p0", "p1", "p2"])

    def test_worker_cap_has_a_floor_of_one(self):
        self.audited_bridge(max_workers=0)
        results = self.start_call("list_segments", {"page_uid": "p0"})
        self.pump_until(lambda: self.blocking.started == ["p0"])
        self.assertEqual(
            self.call("list_segments", {"page_uid": "p1"})["status"], "busy"
        )
        self.blocking.release("p0")
        self.pump_until(lambda: len(results) == 1)

    def test_one_finished_worker_frees_exactly_one_slot(self):
        self.audited_bridge(max_workers=2)
        first = self.start_call("list_segments", {"page_uid": "p0"})
        second = self.start_call("list_segments", {"page_uid": "p1"})
        self.pump_until(lambda: sorted(self.blocking.started) == ["p0", "p1"])
        self.blocking.release("p0")
        self.pump_until(lambda: len(first) == 1)
        third = self.start_call("list_segments", {"page_uid": "p2"})
        self.pump_until(lambda: "p2" in self.blocking.started)
        self.assertEqual(
            self.call("list_segments", {"page_uid": "p3"})["status"], "busy"
        )
        self.assertNotIn("p3", self.blocking.started)
        self.blocking.release("p1")
        self.blocking.release("p2")
        self.pump_until(lambda: len(second) == 1 and len(third) == 1)

    def test_the_idle_timer_leaves_a_request_that_is_being_worked_on_alone(self):
        self.audited_bridge(idle_timeout_ms=50)
        results = self.start_call("list_segments", {"page_uid": "p0"})
        self.pump_until(lambda: self.blocking.started == ["p0"])
        self.wait_events(300)
        self.blocking.release("p0")
        self.pump_until(lambda: len(results) == 1)
        self.assertEqual(results[0], ok_result({"segments": ["p0"]}))
        self.assertEqual(self.audited, [("list_segments", "ok")])

    def test_bytes_after_a_complete_request_are_ignored(self):
        self.audited_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        with self.slot_errors() as errors:
            self.write_raw(
                handle,
                b'{"token": "capped-token", "command": "list_segments", '
                b'"arguments": {"page_uid": "p0"}}\n',
            )
            self.pump_until(lambda: self.blocking.started == ["p0"])
            self.write_raw(
                handle,
                b'{"token": "capped-token", "command": "list_segments", '
                b'"arguments": {"page_uid": "p1"}}\n',
            )
            self.wait_events(200)
            self.blocking.release("p0")
            response = self.read_raw(handle)
        self.assertEqual(errors, [])
        self.assertEqual(response, ok_result({"segments": ["p0"]}))
        self.assertEqual(self.blocking.started, ["p0"])

    def test_a_worker_finishing_after_cleanup_is_not_answered_or_audited(self):
        bridge = self.audited_bridge()
        results = self.start_call("list_segments", {"page_uid": "p0"})
        self.pump_until(lambda: self.blocking.started == ["p0"])
        with self.slot_errors() as errors:
            bridge.cleanup()
            self.blocking.release("p0")
            self.pump_until(lambda: bridge._active_workers == 0)
            self.pump_until(lambda: len(results) == 1)
        self.assertEqual(errors, [])
        self.assertEqual(self.audited, [])
        self.assertFalse(results[0]["success"])

    def test_a_worker_finishing_after_the_client_left_is_not_answered(self):
        bridge = self.audited_bridge(idle_timeout_ms=60000)
        handle = self.open_raw()
        self.write_raw(
            handle,
            b'{"token": "capped-token", "command": "list_segments", '
            b'"arguments": {"page_uid": "p0"}}\n',
        )
        self.pump_until(lambda: self.blocking.started == ["p0"])
        handle.Close()
        self.pump_until(lambda: not bridge._open_sockets)
        self.delete_later_now()
        self.assertEqual(bridge.findChildren(QLocalSocket), [])
        with self.slot_errors() as errors:
            self.blocking.release("p0")
            self.pump_until(lambda: bridge._active_workers == 0)
        self.assertEqual(errors, [])
        self.assertEqual(self.audited, [])


class BridgeDeferredReplyTests(BridgeTestCase):
    def setUp(self):
        super().setUp()
        self.writes = DeferredWriteCommands()
        self.audited = []
        self.deferred = self.capped_bridge(
            write_commands=self.writes,
            idle_timeout_ms=60000,
            audit=lambda tool, arguments, outcome: self.audited.append((tool, outcome)),
        )

    def send_apply(self):
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        self.write_raw(
            handle,
            b'{"token": "capped-token", "command": "apply_changeset", '
            b'"arguments": {"changeset_id": "c1"}}\n',
        )
        self.pump_until(lambda: len(self.writes.replies) == 1)
        return handle

    def test_a_resolved_reply_reaches_the_waiting_client(self):
        handle = self.send_apply()
        self.writes.replies[0].resolve(ok_result({"changeset_id": "c1"}, "applied"))
        self.assertEqual(
            self.read_raw(handle), ok_result({"changeset_id": "c1"}, "applied")
        )
        self.assertEqual(self.audited, [("apply_changeset", "applied")])

    def test_a_reply_resolved_after_the_client_left_is_dropped(self):
        handle = self.send_apply()
        handle.Close()
        self.pump_until(lambda: not self.deferred._open_sockets)
        self.delete_later_now()
        self.writes.replies[0].resolve(ok_result({"changeset_id": "c1"}, "applied"))
        self.assertEqual(self.audited, [])

    def test_a_reply_resolved_after_cleanup_is_dropped(self):
        handle = self.send_apply()
        self.deferred.cleanup()
        self.writes.replies[0].resolve(ok_result({"changeset_id": "c1"}, "applied"))
        self.assertEqual(self.audited, [])
        self.assertEqual(self.read_raw_bytes(handle), b"")


if __name__ == "__main__":
    unittest.main()
