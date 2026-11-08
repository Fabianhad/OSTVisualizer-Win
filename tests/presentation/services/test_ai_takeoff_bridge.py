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
from shiboken6 import delete, isValid


class FakeReadService:
    def __init__(self):
        self.calls = []
        self.threads = {}
        self.received = {}

    def _record(self, name, **kwargs):
        self.calls.append((name, kwargs))
        self.threads[name] = threading.get_ident()

    def list_sheets(self, bid_uid=None, cursor=None, limit=None, text_hints=None):
        self._record("list_sheets", bid_uid=bid_uid, cursor=cursor, limit=limit)
        self.received["list_sheets"] = dict(
            bid_uid=bid_uid, cursor=cursor, limit=limit, text_hints=text_hints
        )
        if text_hints:
            return ok_result({"sheets": [{"page_uid": "p1"}, {"page_uid": "raster"}]})
        return ok_result({"sheets": []})

    def sheet_hint_snapshots(self, result):
        self._record("sheet_hint_snapshots")
        return [
            self.page_snapshot(sheet["page_uid"]) for sheet in result["data"]["sheets"]
        ]

    def sheet_text_hints(self, result, snapshots):
        self._record("sheet_text_hints", pages=[snapshot.uid for snapshot in snapshots])
        for sheet in result["data"]["sheets"]:
            sheet["text_hints"] = {"text_extractable": False}
        return result

    def get_quantities(self, bid_uid=None, group_by="condition"):
        self._record("get_quantities", bid_uid=bid_uid, group_by=group_by)
        self.received["get_quantities"] = dict(bid_uid=bid_uid, group_by=group_by)
        if group_by == "level":
            raise AiTakeoffRequestError(
                "invalid_argument", "group_by must be condition or page"
            )
        return ok_result({"rows": []})

    def list_levels(self, bid_uid=None):
        self._record("list_levels", bid_uid=bid_uid)
        self.received["list_levels"] = dict(bid_uid=bid_uid)
        return ok_result({"sidecar_status": "empty", "levels": []})

    def list_assumptions(self, bid_uid=None, status=None):
        self._record("list_assumptions", bid_uid=bid_uid, status=status)
        self.received["list_assumptions"] = dict(bid_uid=bid_uid, status=status)
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
        self.received["plan_crop"] = dict(
            page_uid=snapshot.uid, crop_pts=crop_pts, dpi=dpi
        )
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

    def overlay_status(self, overlay_ids):
        self.received["overlay_status"] = dict(overlay_ids=overlay_ids)
        return None if overlay_ids is None else "not_supported_until_m1b"

    def list_text(self, snapshot, bbox_pts=None, query=None, cursor=None, limit=None):
        self._record("list_text", page_uid=snapshot.uid, query=query)
        self.received["list_text"] = dict(
            page_uid=snapshot.uid,
            bbox_pts=bbox_pts,
            query=query,
            cursor=cursor,
            limit=limit,
        )
        return ok_result({"runs": []})

    def list_segments(
        self, snapshot, bbox_pts=None, cursor=None, limit=None, kinds=None
    ):
        self._record("list_segments", page_uid=snapshot.uid, kinds=kinds)
        self.received["list_segments"] = dict(
            page_uid=snapshot.uid,
            bbox_pts=bbox_pts,
            cursor=cursor,
            limit=limit,
            kinds=kinds,
        )
        return ok_result({"segments": []})


class FakePdfSource:
    def __init__(self):
        self.render_threads = []

    def render_frame(self, file_path, page_index, scale, frame_pts):
        self.render_threads.append(threading.get_ident())
        image = QtGui.QImage(20, 10, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("white"))
        return image


WORKER_THREAD = "AiTakeoffBridgeWorker"
BUSY_TEXT = "OST Visualizer is busy with other AI takeoff requests. Try again shortly."


class BridgeTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.threads_before = set(threading.enumerate())
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
        self.addCleanup(lambda: self.release_bridge(self.bridge))

    def release_bridge(self, bridge):
        bridge.cleanup()
        for thread in threading.enumerate():
            if thread not in self.threads_before and thread.name == WORKER_THREAD:
                thread.join(10)
        if isValid(bridge):
            delete(bridge)

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
            read_timeout_s=20,
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
        self.addCleanup(self.release_bridge, bridge)
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


class BridgeArgumentForwardingTests(BridgeTestCase):
    """Every declared argument reaches the read service under its own name."""

    FULL_ARGUMENTS = {
        "list_sheets": {
            "bid_uid": "bid-9",
            "cursor": "c:7",
            "limit": 3,
            "text_hints": False,
        },
        "get_quantities": {"bid_uid": "bid-9", "group_by": "page"},
        "list_levels": {"bid_uid": "bid-9"},
        "list_assumptions": {"bid_uid": "bid-9", "status": "accepted"},
        "list_text": {
            "page_uid": "p1",
            "bbox_pts": [1.0, 2.0, 30.0, 40.0],
            "query": "slab",
            "cursor": "c:2",
            "limit": 4,
        },
        "list_segments": {
            "page_uid": "p1",
            "bbox_pts": [5.0, 6.0, 70.0, 80.0],
            "kinds": ["wall", "dashed"],
            "cursor": "c:3",
            "limit": 6,
        },
    }

    def test_every_read_command_forwards_each_argument_it_declares(self):
        for command, arguments in self.FULL_ARGUMENTS.items():
            with self.subTest(command=command):
                self.assertTrue(self.call(command, arguments)["success"])
                self.assertEqual(self.service.received[command], arguments)

    def test_a_render_forwards_the_page_crop_dpi_and_overlays(self):
        arguments = {
            "page_uid": "p1",
            "crop_pts": [0.0, 0.0, 20.0, 10.0],
            "dpi": 96,
            "overlay_ids": ["r1"],
        }
        self.assertTrue(self.call("render_sheet", arguments)["success"])
        self.assertEqual(
            self.service.received["plan_crop"],
            {"page_uid": "p1", "crop_pts": [0.0, 0.0, 20.0, 10.0], "dpi": 96},
        )
        self.assertEqual(
            self.service.received["overlay_status"], {"overlay_ids": ["r1"]}
        )

    def test_omitted_arguments_arrive_as_none_except_the_quantity_grouping(self):
        for command in ("list_sheets", "list_levels", "list_assumptions"):
            with self.subTest(command=command):
                self.assertTrue(self.call(command)["success"])
                self.assertEqual(set(self.service.received[command].values()), {None})
        self.assertTrue(self.call("get_quantities")["success"])
        self.assertEqual(
            self.service.received["get_quantities"],
            {"bid_uid": None, "group_by": "condition"},
        )

    def test_a_pdf_render_answers_ok_and_a_raster_page_answers_not_pdf_with_its_page(
        self,
    ):
        rendered = self.call("render_sheet", {"page_uid": "p1", "overlay_ids": []})
        self.assertEqual(rendered["status"], "ok")
        self.assertEqual(rendered["data"]["overlay_status"], "not_supported_until_m1b")
        raster = self.call("render_sheet", {"page_uid": "raster", "overlay_ids": []})
        self.assertEqual(raster["status"], "not_pdf")
        self.assertEqual(
            raster["data"],
            {
                "page_uid": "raster",
                "image": None,
                "overlay_status": "not_supported_until_m1b",
            },
        )
        plain = self.call("render_sheet", {"page_uid": "raster"})
        self.assertIsNone(plain["data"]["overlay_status"])

    def test_an_audit_outcome_is_empty_when_a_result_carries_no_status(self):
        audited = []
        self.capped_bridge(audit=lambda *entry: audited.append(entry))
        self.service.list_levels = lambda bid_uid=None: {"success": True}
        self.assertTrue(self.call("list_levels", {"bid_uid": "b1"})["success"])
        self.assertEqual(audited, [("list_levels", {"bid_uid": "b1"}, "")])


class BridgeRefusalTextTests(BridgeTestCase):
    """The exact text an AI client reads for each kind of refusal."""

    def test_each_refusal_carries_its_own_message_and_never_reaches_the_service(self):
        def request(**fields):
            body = {"token": "token-0", "command": "list_sheets", "arguments": {}}
            body.update(fields)
            return json.dumps(body).encode() + b"\n"

        cases = {
            "wrong token": (
                request(token="nope"),
                "unauthorized",
                "Session token rejected.",
            ),
            "missing token": (
                json.dumps({"command": "list_sheets"}).encode() + b"\n",
                "unauthorized",
                "Session token rejected.",
            ),
            "unknown command": (
                request(command="apply_it"),
                "unknown_command",
                "This command is not available.",
            ),
            "undeclared argument": (
                request(arguments={"approve": True}),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
            "arguments that are not an object": (
                request(arguments=[1]),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
            "not json": (b"{nope\n", "invalid_argument", "Malformed request."),
        }
        for label, (payload, status, message) in cases.items():
            with self.subTest(label=label):
                response = self.raw(payload)
                self.assertEqual(response["status"], status)
                self.assertEqual(response["error"]["message"], message)
        self.assertEqual(self.service.calls, [])

    def test_a_denied_feature_says_how_to_enable_it(self):
        self.allowed = False
        response = self.call("list_sheets")
        self.assertEqual(response["status"], "feature_denied")
        self.assertEqual(
            response["error"]["message"],
            "AI takeoff is not enabled or not available for the open bid.",
        )

    def test_cleanup_closes_the_listening_server_itself(self):
        server = self.bridge._server
        self.assertTrue(server.isListening())
        self.bridge.cleanup()
        self.assertFalse(server.isListening())

    def test_the_idle_timeout_has_a_floor_of_one_millisecond(self):
        bridge = self.capped_bridge(idle_timeout_ms=0)
        self.assertEqual(bridge._idle_timeout_ms, 1)
        self.assertEqual(self.capped_bridge(idle_timeout_ms=-5)._idle_timeout_ms, 1)
        self.assertEqual(self.capped_bridge(idle_timeout_ms=250)._idle_timeout_ms, 250)


class BridgeCapacityTests(BridgeTestCase):
    def test_requests_beyond_the_worker_cap_get_busy_and_capacity_returns(self):
        self.capped_bridge(max_workers=2)
        release = threading.Event()
        self.addCleanup(release.set)
        started = []

        def blocking(snapshot, bbox_pts=None, cursor=None, limit=None, kinds=None):
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
        self.assertEqual(busy["error"]["message"], BUSY_TEXT)
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
        refused = self.call("list_sheets")
        self.assertEqual(refused["status"], "busy")
        self.assertEqual(refused["error"]["message"], BUSY_TEXT)
        idle[0].Close()
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        self.assertTrue(self.call("list_sheets")["success"])
        idle[1].Close()

    def test_a_refused_connection_is_never_read_even_if_it_sent_a_request(self):
        bridge = self.capped_bridge(max_connections=1, idle_timeout_ms=60000)
        idle = self.open_raw()
        self.addCleanup(idle.Close)
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        extra = self.open_raw()
        self.addCleanup(extra.Close)
        response = self.read_raw(
            extra,
            first_write=b'{"token": "capped-token", "command": "list_levels"}' + b"\n",
        )
        self.assertEqual(response["status"], "busy")
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        self.assertEqual(len(bridge._buffers), 1)
        self.assertEqual(self.service.calls, [])

    def test_a_connection_that_never_finishes_its_request_is_closed(self):
        bridge = self.capped_bridge(idle_timeout_ms=200)
        handle = self.open_raw()
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        response = self.read_raw(
            handle, first_write=b'{"token": "capped-token", "command": "list_'
        )
        handle.Close()
        self.assertEqual(response["status"], "invalid_argument")
        self.assertEqual(
            response["error"]["message"], "No complete request was received in time."
        )
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
        self.release_bridge(self.bridge)
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
        self.assertTrue(
            self.call("list_segments", {"page_uid": "p1", "kinds": ["wall"]})["success"]
        )
        self.assertIn(
            ("list_segments", {"page_uid": "p1", "kinds": ["wall"]}), self.service.calls
        )
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

    def test_sheet_text_hints_read_the_pdf_off_the_gui_thread(self):
        gui_thread = threading.get_ident()
        result = self.call("list_sheets", {"text_hints": True})
        self.assertTrue(result["success"])
        self.assertEqual(
            [sheet["text_hints"] for sheet in result["data"]["sheets"]],
            [{"text_extractable": False}] * 2,
        )
        self.assertIn(
            ("sheet_text_hints", {"pages": ["p1", "raster"]}), self.service.calls
        )
        self.assertEqual(self.service.threads["list_sheets"], gui_thread)
        self.assertEqual(self.service.threads["page_snapshot"], gui_thread)
        self.assertEqual(self.service.threads["sheet_hint_snapshots"], gui_thread)
        self.assertNotEqual(self.service.threads["sheet_text_hints"], gui_thread)

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
        self.assertNotIn("sheet_text_hints", self.service.threads)


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

    def __call__(self, snapshot, bbox_pts=None, cursor=None, limit=None, kinds=None):
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
        self.addCleanup(self.release_bridge, bridge)
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
        self.addCleanup(self.release_bridge, bridge)
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
        self.addCleanup(self.release_bridge, bridge)
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
        self.addCleanup(self.release_bridge, bridge)
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.WARNING
        ) as captured:
            self.assertIs(bridge.start(), False)
        self.assertEqual(len(captured.output), 1)
        self.assertEqual(
            captured.output[0],
            "WARNING:ost_visualizer.presentation.services.ai_takeoff_bridge:"
            "Failed to write the AI takeoff session token: FileExistsError",
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
        self.addCleanup(self.release_bridge, bridge)
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

    def test_accepted_connections_belong_to_the_bridge_not_the_server(self):
        bridge = self.capped_bridge(max_connections=1, idle_timeout_ms=60000)
        idle = self.open_raw()
        self.addCleanup(idle.Close)
        self.pump_until(lambda: len(bridge._open_sockets) == 1)
        extra = self.open_raw()
        self.addCleanup(extra.Close)
        direct = QtCore.Qt.FindChildOption.FindDirectChildrenOnly
        self.pump_until(
            lambda: len(bridge.findChildren(QLocalSocket, options=direct)) == 2
        )

    def test_cleanup_is_quiet_when_its_own_signals_are_already_detached(self):
        import warnings

        bridge = self.bridge
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bridge._job_finished.disconnect()
            bridge.rebind_suggested.disconnect()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bridge.cleanup()
        self.assertEqual([str(item.message) for item in caught], [])

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
        self.assertEqual(
            captured.output[0].splitlines()[0],
            "ERROR:ost_visualizer.presentation.services.ai_takeoff_bridge:"
            "AI takeoff command failed: ValueError",
        )

    def test_worker_failures_are_logged_and_answered(self):
        def broken(snapshot, bbox_pts=None, cursor=None, limit=None, kinds=None):
            raise ValueError("secret detail")

        self.service.list_segments = broken
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.ERROR
        ) as captured:
            response = self.call("list_segments", {"page_uid": "p1"})
        self.assertEqual(response["status"], "unexpected_error")
        self.assertEqual(response["error"]["message"], "The command failed.")
        self.assertEqual(
            captured.output[0].splitlines()[0],
            "ERROR:ost_visualizer.presentation.services.ai_takeoff_bridge:"
            "AI takeoff worker job failed: ValueError",
        )

    def test_worker_request_errors_keep_their_code(self):
        def missing(snapshot, bbox_pts=None, cursor=None, limit=None, kinds=None):
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
        before = set(threading.enumerate())
        results = self.start_call("list_segments", {"page_uid": "p0"})
        self.pump_until(lambda: self.blocking.started == ["p0"])
        (worker,) = [
            thread
            for thread in threading.enumerate()
            if thread not in before and thread.name == "AiTakeoffBridgeWorker"
        ]
        with self.slot_errors() as errors:
            bridge.cleanup()
            self.blocking.release("p0")
            worker.join(5)
            self.assertFalse(worker.is_alive())
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


class BridgeCleanupReleaseTests(BridgeTestCase):
    def test_cleanup_drops_its_commands_and_disconnects_its_own_signals(self):
        bridge = self.bridge
        offered = []
        bridge.rebind_suggested.connect(lambda: offered.append(True))
        bridge._active_workers = 1
        bridge.cleanup()
        self.assertEqual(bridge._commands, {})
        self.assertEqual(bridge.commands, ())
        bridge.rebind_suggested.emit()
        bridge._job_finished.emit(None, (("list_sheets", {}), ok_result({})))
        self.assertEqual(offered, [])
        self.assertEqual(bridge._active_workers, 1)

    def test_cleanup_deletes_the_bridge_on_its_own_thread(self):
        bridge = self.bridge
        destroyed = []
        bridge.destroyed.connect(
            lambda *_: destroyed.append(threading.current_thread().name),
            QtCore.Qt.ConnectionType.DirectConnection,
        )
        bridge.cleanup()
        self.assertTrue(isValid(bridge))
        self.delete_later_now()
        self.assertFalse(isValid(bridge))
        self.assertEqual(destroyed, [threading.main_thread().name])

    def test_cleanup_after_the_bridge_is_deleted_raises_nothing(self):
        self.bridge.cleanup()
        self.delete_later_now()
        self.bridge.cleanup()
        self.assertIs(self.bridge.start(), False)

    def test_a_parented_bridge_is_deleted_without_its_parent(self):
        parent = QtCore.QObject()
        self.addCleanup(parent.deleteLater)
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.directory / "parented" / "session.token",
            server_name=self.server_name + "-parented",
            parent=parent,
        )
        self.assertTrue(bridge.start())
        bridge.cleanup()
        self.delete_later_now()
        self.assertFalse(isValid(bridge))
        self.assertTrue(isValid(parent))
        self.assertEqual(parent.findChildren(TakeoffCommandBridge), [])


class RecordingSocket:
    """Stands in for an accepted QLocalSocket: records what the bridge does to it."""

    def __init__(self, incoming=b""):
        self.events = []
        self.incoming = incoming

    def readAll(self):
        data, self.incoming = self.incoming, b""
        return data

    def write(self, payload):
        self.events.append(("write", bytes(payload)))

    def flush(self):
        self.events.append(("flush",))

    def disconnectFromServer(self):
        self.events.append(("disconnect",))

    def replies(self):
        writes = [event[1] for event in self.events if event[0] == "write"]
        for payload in writes:
            assert payload.endswith(b"\n") and payload.count(b"\n") == 1, payload
        return [json.loads(payload) for payload in writes]

    def hung_up(self):
        return self.events.count(("disconnect",))


def request_line(**fields):
    body = {"token": "token-0", "command": "list_levels", "arguments": {}}
    body.update(fields)
    return json.dumps(body).encode()


class ServerSpy:
    """Delegates to the real QLocalServer and records the calls the bridge makes."""

    def __init__(self, server):
        self._server = server
        self.calls = []

    def __getattr__(self, name):
        attribute = getattr(self._server, name)
        if name not in ("removeServer", "listen", "close"):
            return attribute

        def recorded(*args):
            self.calls.append((name, args))
            return attribute(*args)

        return recorded


class BridgeDirectHandlerTests(BridgeTestCase):
    """The slot methods driven directly: nothing escapes, each request is answered once."""

    def test_every_refusal_is_answered_exactly_once_and_stops_there(self):
        cases = [
            ("not json", b"{nope", "invalid_argument", "Malformed request."),
            ("not utf-8", b"\xff\xfe", "invalid_argument", "Malformed request."),
            ("a list", b"[1]", "invalid_argument", "Malformed request."),
            (
                "wrong token",
                request_line(token="nope"),
                "unauthorized",
                "Session token rejected.",
            ),
            (
                "numeric token",
                request_line(token=7),
                "unauthorized",
                "Session token rejected.",
            ),
            (
                "no token",
                json.dumps({"command": "list_levels"}).encode(),
                "unauthorized",
                "Session token rejected.",
            ),
            (
                "unknown command",
                request_line(command="apply_it"),
                "unknown_command",
                "This command is not available.",
            ),
            (
                "numeric command",
                request_line(command=7),
                "unknown_command",
                "This command is not available.",
            ),
            (
                "undeclared argument",
                request_line(arguments={"approve": True}),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
            (
                "empty list as arguments",
                request_line(arguments=[]),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
            (
                "empty text as arguments",
                request_line(arguments=""),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
            (
                "list as arguments",
                request_line(arguments=["bid_uid"]),
                "invalid_argument",
                "Unknown or malformed arguments.",
            ),
        ]
        for label, line, status, message in cases:
            with self.subTest(label=label):
                socket = RecordingSocket()
                self.bridge._handle(socket, line)
                (reply,) = socket.replies()
                self.assertEqual(
                    (reply["success"], reply["status"], reply["error"]["message"]),
                    (False, status, message),
                )
                self.assertEqual(socket.hung_up(), 1)
        self.allowed = False
        socket = RecordingSocket()
        self.bridge._handle(socket, request_line())
        (reply,) = socket.replies()
        self.assertEqual(
            (reply["success"], reply["status"], reply["error"]["message"]),
            (
                False,
                "feature_denied",
                "AI takeoff is not enabled or not available for the open bid.",
            ),
        )
        self.assertEqual(socket.hung_up(), 1)
        self.assertEqual(self.service.calls, [])

    def test_a_command_that_fails_is_answered_and_audited_exactly_once(self):
        audited = []
        bridge = self.capped_bridge(
            audit=lambda tool, arguments, outcome: audited.append(
                (tool, arguments, outcome)
            )
        )
        socket = RecordingSocket()
        bridge._handle(
            socket,
            request_line(
                token="capped-token",
                command="get_quantities",
                arguments={"group_by": "level"},
            ),
        )
        (reply,) = socket.replies()
        self.assertEqual(
            (reply["status"], reply["error"]["message"]),
            ("invalid_argument", "group_by must be condition or page"),
        )
        self.assertEqual(socket.hung_up(), 1)
        self.assertEqual(
            audited, [("get_quantities", {"group_by": "level"}, "invalid_argument")]
        )

        def broken(bid_uid=None):
            raise ValueError("secret detail")

        self.service.list_levels = broken
        socket = RecordingSocket()
        audited.clear()
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.ERROR
        ):
            bridge._handle(socket, request_line(token="capped-token"))
        (reply,) = socket.replies()
        self.assertEqual(
            (reply["status"], reply["error"]["message"]),
            ("unexpected_error", "The command failed."),
        )
        self.assertEqual(socket.hung_up(), 1)
        self.assertEqual(audited, [("list_levels", {}, "unexpected_error")])

    def test_a_failed_start_leaves_no_token_that_would_be_accepted(self):
        blocker = self.directory / "blocker"
        blocker.write_text("not a folder", encoding="utf-8")
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=blocker / "session.token",
            server_name=self.server_name + "-blocked",
            token_factory=lambda: "blocked-token",
        )
        self.addCleanup(self.release_bridge, bridge)
        with self.assertLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.WARNING
        ):
            self.assertIs(bridge.start(), False)
        socket = RecordingSocket()
        bridge._handle(socket, request_line(token="blocked-token"))
        (reply,) = socket.replies()
        self.assertEqual(reply["status"], "unauthorized")
        self.assertEqual(self.service.calls, [])

    def test_a_token_with_a_lone_surrogate_is_compared_like_any_other(self):
        self.bridge._token = "tok\ud800"
        accepted = RecordingSocket()
        self.bridge._handle(accepted, request_line(token="tok\ud800"))
        self.assertTrue(accepted.replies()[0]["success"])
        rejected = RecordingSocket()
        self.bridge._handle(rejected, request_line(token="tok\ud801"))
        self.assertEqual(rejected.replies()[0]["status"], "unauthorized")
        self.assertEqual(self.service.calls, [("list_levels", {"bid_uid": None})])

    def test_the_token_is_compared_in_constant_time_on_its_utf8_bytes(self):
        import hmac
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        real = hmac.compare_digest
        with patch.object(
            ai_takeoff_bridge.hmac, "compare_digest", side_effect=real
        ) as compared:
            socket = RecordingSocket()
            self.bridge._handle(socket, request_line(token="token-x"))
        self.assertEqual(socket.replies()[0]["status"], "unauthorized")
        compared.assert_called_once_with(b"token-x", b"token-0")

    def test_only_the_first_line_of_one_read_is_a_request(self):
        socket = RecordingSocket(request_line() + b"\n" + b"not a request")
        self.bridge._buffers[id(socket)] = bytearray()
        self.bridge._on_ready_read(socket)
        (reply,) = socket.replies()
        self.assertTrue(reply["success"])
        self.assertEqual(self.service.calls, [("list_levels", {"bid_uid": None})])
        self.assertNotIn(id(socket), self.bridge._buffers)

    def test_an_idle_timer_for_a_socket_that_no_longer_exists_does_nothing(self):
        dead = QLocalSocket()
        delete(dead)
        self.bridge._buffers[id(dead)] = bytearray(b"{")
        with self.slot_errors() as errors:
            self.bridge._on_idle(dead)
        self.assertEqual(errors, [])
        self.assertNotIn(id(dead), self.bridge._buffers)

    def test_a_live_socket_that_is_idle_gets_the_timeout_answer(self):
        socket = RecordingSocket()
        self.bridge._buffers[id(socket)] = bytearray(b"{")
        self.bridge._on_idle(socket)
        (reply,) = socket.replies()
        self.assertEqual(
            (reply["status"], reply["error"]["message"]),
            ("invalid_argument", "No complete request was received in time."),
        )
        self.assertEqual(socket.hung_up(), 1)
        again = RecordingSocket()
        self.bridge._on_idle(again)
        self.assertEqual(again.events, [])

    def test_the_busy_worker_counter_stops_at_zero(self):
        dead = QLocalSocket()
        delete(dead)
        self.assertEqual(self.bridge._active_workers, 0)
        self.bridge._finish(dead, (("list_levels", {}), ok_result({})))
        self.assertEqual(self.bridge._active_workers, 0)
        self.bridge._active_workers = 3
        self.bridge._finish(dead, (("list_levels", {}), ok_result({})))
        self.assertEqual(self.bridge._active_workers, 2)

    def test_a_finished_job_is_only_answered_while_the_bridge_is_open(self):
        audited = []
        bridge = self.capped_bridge(
            audit=lambda tool, arguments, outcome: audited.append(outcome)
        )
        live = RecordingSocket()
        bridge._finish(live, (("list_levels", {}), ok_result({}, "ok")))
        self.assertEqual(len(live.replies()), 1)
        self.assertEqual(audited, ["ok"])
        bridge.cleanup()
        late = RecordingSocket()
        bridge._finish(late, (("list_levels", {}), ok_result({}, "ok")))
        self.assertEqual(late.events, [])
        self.assertEqual(audited, ["ok"])

    def test_a_connection_signal_after_cleanup_does_nothing(self):
        self.bridge.cleanup()
        with self.slot_errors() as errors:
            self.bridge._on_new_connection()
        self.assertEqual(errors, [])

    def test_a_reply_is_one_ascii_json_line_then_a_hang_up(self):
        socket = RecordingSocket()
        result = ok_result({"name": "caf\u00e9 \ud800"})
        self.bridge._respond(socket, result)
        writes = [event for event in socket.events if event[0] == "write"]
        self.assertEqual(
            writes, [("write", json.dumps(result).encode("ascii") + b"\n")]
        )
        self.assertEqual(socket.events[0][0], "write")
        self.assertEqual(socket.events[-1], ("disconnect",))
        self.assertEqual(socket.hung_up(), 1)


class BridgeStateReleaseTests(BridgeTestCase):
    """What cleanup() is expected to let go of."""

    def test_cleanup_forgets_the_session_token(self):
        self.bridge.cleanup()
        socket = RecordingSocket()
        self.bridge._handle(socket, request_line())
        (reply,) = socket.replies()
        self.assertEqual(reply["status"], "unauthorized")

    def test_cleanup_drops_request_state_even_for_sockets_it_does_not_own(self):
        self.bridge._buffers[12345] = bytearray(b"{")
        self.bridge._open_sockets.add(12345)
        self.bridge.cleanup()
        self.assertEqual(self.bridge._buffers, {})
        self.assertEqual(self.bridge._open_sockets, set())

    def test_cleanup_lets_go_of_the_read_service_and_the_pdf_source(self):
        import gc
        import weakref

        service = FakeReadService()
        pdf = FakePdfSource()
        bridge = TakeoffCommandBridge(
            read_service=service,
            pdf_source=pdf,
            access_allowed=lambda: True,
            token_path=self.directory / "release" / "session.token",
            server_name=self.server_name + "-release",
            token_factory=lambda: "release-token",
        )
        self.addCleanup(self.release_bridge, bridge)
        self.assertTrue(bridge.start())
        service_ref = weakref.ref(service)
        pdf_ref = weakref.ref(pdf)
        del service, pdf
        gc.collect()
        self.assertIsNotNone(service_ref())
        self.assertIsNotNone(pdf_ref())
        bridge.cleanup()
        gc.collect()
        self.assertIsNone(service_ref())
        self.assertIsNone(pdf_ref())

    def test_cleanup_still_releases_everything_when_the_server_is_already_gone(self):
        self.bridge._server = None
        self.bridge.cleanup()
        self.assertEqual(self.bridge._commands, {})
        self.assertFalse(self.token_path.exists())
        self.assertIsNone(self.bridge._read_service)

    def test_cleanup_still_closes_the_server_when_the_command_table_is_empty(self):
        server = self.bridge._server
        self.bridge._commands = {}
        self.bridge.cleanup()
        self.assertFalse(server.isListening())
        self.assertFalse(self.token_path.exists())
        self.assertIsNone(self.bridge._server)

    def test_cleanup_schedules_the_deletion_of_each_connection_itself(self):
        child = QLocalSocket(self.bridge)
        self.bridge.cleanup()
        self.assertTrue(isValid(child))
        QtCore.QCoreApplication.sendPostedEvents(
            child, QtCore.QEvent.Type.DeferredDelete
        )
        self.assertFalse(isValid(child))

    def test_start_and_cleanup_both_remove_a_stale_endpoint_of_their_name(self):
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.directory / "spied" / "session.token",
            server_name=self.server_name + "-spied",
            token_factory=lambda: "spied-token",
        )
        self.addCleanup(self.release_bridge, bridge)
        spy = ServerSpy(bridge._server)
        bridge._server = spy
        self.assertTrue(bridge.start())
        name = self.server_name + "-spied"
        self.assertEqual(
            [call for call in spy.calls if call[0] in ("removeServer", "listen")],
            [("removeServer", (name,)), ("listen", (name,))],
        )
        spy.calls.clear()
        bridge.cleanup()
        self.assertEqual(
            [call for call in spy.calls if call[0] in ("close", "removeServer")],
            [("close", ()), ("removeServer", (name,))],
        )


class BridgeDefaultsTests(BridgeTestCase):
    """What a caller that passes no options gets."""

    def unstarted(self, **options):
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.directory / "defaults" / "session.token",
            **options,
        )
        # never started: deleted directly so the real pipe name is never touched
        self.addCleanup(lambda: delete(bridge) if isValid(bridge) else None)
        return bridge

    def test_the_limits_and_pipe_name_default_to_the_module_values(self):
        bridge = self.unstarted()
        self.assertEqual(
            (
                bridge._max_workers,
                bridge._max_connections,
                bridge._idle_timeout_ms,
                bridge._server_name,
            ),
            (2, 8, 10000, "OSTVisualizerTakeoffBridge.v1"),
        )
        self.assertIsNone(bridge.parent())

    def test_a_token_path_given_as_text_is_accepted(self):
        path = self.directory / "as-text" / "session.token"
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=str(path),
            server_name=self.server_name + "-as-text",
            token_factory=lambda: "text-token",
        )
        self.addCleanup(self.release_bridge, bridge)
        self.assertTrue(bridge.start())
        self.assertEqual(path.read_text(encoding="utf-8"), "text-token")
        bridge.cleanup()
        self.assertFalse(path.exists())

    def test_the_limits_are_whole_numbers(self):
        bridge = self.unstarted(
            max_workers=2.9, max_connections=3.9, idle_timeout_ms=250.9
        )
        self.assertEqual(
            (bridge._max_workers, bridge._max_connections, bridge._idle_timeout_ms),
            (2, 3, 250),
        )
        for value in (
            bridge._max_workers,
            bridge._max_connections,
            bridge._idle_timeout_ms,
        ):
            self.assertIs(type(value), int)

    def test_default_tokens_differ_between_sessions(self):
        tokens = []
        for index in range(2):
            path = self.directory / f"fresh-{index}" / "session.token"
            bridge = TakeoffCommandBridge(
                read_service=self.service,
                pdf_source=self.pdf,
                access_allowed=lambda: True,
                token_path=path,
                server_name=f"{self.server_name}-fresh-{index}",
            )
            self.addCleanup(self.release_bridge, bridge)
            self.assertTrue(bridge.start())
            tokens.append(path.read_text(encoding="utf-8"))
        self.assertEqual(len(set(tokens)), 2)
        for token in tokens:
            self.assertRegex(token, r"^[A-Za-z0-9_-]{43}$")

    def test_the_default_audit_accepts_a_reply_without_complaint(self):
        bridge = self.unstarted()
        socket = RecordingSocket()
        with self.assertNoLogs(
            "ost_visualizer.presentation.services.ai_takeoff_bridge", logging.DEBUG
        ):
            bridge._reply(socket, "list_levels", {}, ok_result({"levels": []}))
        self.assertEqual(len(socket.replies()), 1)


class BridgeTokenFileTests(BridgeTestCase):
    def test_the_token_file_is_replaced_atomically_from_a_sibling_temporary(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        path = self.directory / "atomic" / "session.token"
        path.parent.mkdir()
        path.write_text("old-token", encoding="utf-8")
        seen = []
        real_replace = os.replace

        def spy(source, destination):
            seen.append(
                (
                    Path(source),
                    Path(destination),
                    Path(source).read_text(encoding="utf-8"),
                    Path(destination).read_text(encoding="utf-8"),
                )
            )
            real_replace(source, destination)

        with patch.object(ai_takeoff_bridge.os, "replace", spy):
            ai_takeoff_bridge._stage_token(path, "new-token")
            ai_takeoff_bridge._publish_token(path)
        self.assertEqual(len(seen), 1)
        source, destination, source_text, destination_text = seen[0]
        self.assertEqual(destination, path)
        self.assertNotEqual(source, path)
        self.assertEqual(source.parent, path.parent)
        self.assertEqual((source_text, destination_text), ("new-token", "old-token"))
        self.assertEqual(path.read_text(encoding="utf-8"), "new-token")
        self.assertEqual([p.name for p in path.parent.iterdir()], ["session.token"])


class BridgeRenderPayloadTests(BridgeTestCase):
    def test_a_render_hands_the_crop_plan_to_the_pdf_and_returns_a_real_png(self):
        import base64

        frames = []
        original = self.pdf.render_frame

        def recording(file_path, page_index, scale, frame_pts):
            frames.append((file_path, page_index, scale, frame_pts))
            return original(file_path, page_index, scale, frame_pts)

        self.pdf.render_frame = recording
        response = self.call("render_sheet", {"page_uid": "p1"})
        self.assertEqual(response["status"], "ok")
        self.assertEqual(frames, [("C:/p.pdf", 0, 1.0, (0.0, 0.0, 20.0, 10.0))])
        data = response["data"]
        self.assertEqual(
            {key: data[key] for key in data if key != "image"},
            {
                "page_uid": "p1",
                "frame_pts": [0.0, 0.0, 20.0, 10.0],
                "px_to_page_pts": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                "page_pts_to_ost": [0.5, 0.0, 0.0, 0.5, 0.0, 0.0],
                "overlay_status": None,
                "render_status": "ok",
            },
        )
        image = QtGui.QImage.fromData(base64.b64decode(data["image"]["png_base64"]))
        self.assertEqual((image.width(), image.height()), (20, 10))
        self.assertEqual(
            image.pixelColor(10, 5).getRgb(), QtGui.QColor("white").getRgb()
        )
        self.assertEqual(
            (data["image"]["width_px"], data["image"]["height_px"]), (20, 10)
        )


class FaultyServer:
    """Delegates to the real QLocalServer; named calls can run a hook or fail once."""

    def __init__(
        self, server, hooks=None, fail_before=None, fail_after=None, attributes=None
    ):
        self._server = server
        self.calls = []
        self._attributes = dict(attributes or {})
        self._hooks = dict(hooks or {})
        self._fail_before = dict(fail_before or {})
        self._fail_after = dict(fail_after or {})

    def __getattr__(self, name):
        if name in self._attributes:
            return self._attributes[name]
        attribute = getattr(self._server, name)
        if name not in ("removeServer", "listen", "close"):
            return attribute

        def faulty(*args):
            self.calls.append(name)
            if name in self._hooks:
                self._hooks.pop(name)()
            if name in self._fail_before:
                raise self._fail_before.pop(name)
            outcome = attribute(*args)
            if name in self._fail_after:
                raise self._fail_after.pop(name)
            return outcome

        return faulty


class BridgeStartAbortTests(BridgeTestCase):
    """start() either ends up listening with a published token or leaves nothing behind."""

    LOGGER = "ost_visualizer.presentation.services.ai_takeoff_bridge"

    def unstarted(self, token_factory, suffix, token_path=None):
        self.start_name = f"{self.server_name}-{suffix}"
        self.start_token_path = token_path or (
            self.directory / suffix / "session.token"
        )
        bridge = TakeoffCommandBridge(
            read_service=self.service,
            pdf_source=self.pdf,
            access_allowed=lambda: True,
            token_path=self.start_token_path,
            server_name=self.start_name,
            token_factory=token_factory,
        )
        self.addCleanup(self.release_bridge, bridge)
        return bridge

    def files_left(self):
        parent = self.start_token_path.parent
        return sorted(path.name for path in parent.iterdir()) if parent.exists() else []

    def assert_nothing_listening(self, bridge):
        self.assertFalse(bridge._server.isListening())
        self.assertIsNone(bridge._token)
        self.assertEqual(self.files_left(), [])
        self.server_name = self.start_name
        result = self.call("list_sheets", token_path=self.other_token_file("any"))
        self.assertEqual(result["status"], "app_not_running")

    def test_a_token_factory_that_fails_leaves_nothing_listening(self):
        def factory():
            raise ValueError("factory failed")

        bridge = self.unstarted(factory, "factory")
        with self.assertRaises(ValueError):
            bridge.start()
        self.assert_nothing_listening(bridge)

    def test_a_token_that_cannot_be_encoded_leaves_nothing_listening(self):
        bridge = self.unstarted(lambda: "tok\ud800", "surrogate")
        with self.assertRaises(UnicodeEncodeError):
            bridge.start()
        self.assert_nothing_listening(bridge)
        socket = RecordingSocket()
        bridge._handle(socket, request_line(token="tok\ud800"))
        self.assertEqual(socket.replies()[0]["status"], "unauthorized")
        self.assertEqual(self.service.calls, [])

    def test_a_token_factory_with_an_os_error_is_a_failed_start(self):
        def factory():
            raise PermissionError("secret detail")

        bridge = self.unstarted(factory, "oserror")
        with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
            self.assertIs(bridge.start(), False)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:"
                "Failed to write the AI takeoff session token: PermissionError"
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_the_token_is_written_before_the_pipe_listens_and_published_after(self):
        """Characterisation of the order: staged token, then listen, then publish."""
        seen = []
        bridge = self.unstarted(lambda: "ordered-token", "ordered")
        parent = self.start_token_path.parent

        def at_listen():
            seen.append(
                {
                    path.name: path.read_text(encoding="utf-8")
                    for path in (parent.iterdir() if parent.exists() else [])
                }
            )

        bridge._server = FaultyServer(bridge._server, hooks={"listen": at_listen})
        self.assertTrue(bridge.start())
        self.assertEqual(seen, [{"session.token.tmp": "ordered-token"}])
        self.assertEqual(self.files_left(), ["session.token"])
        self.assertEqual(
            self.start_token_path.read_text(encoding="utf-8"), "ordered-token"
        )

    def test_a_failed_listen_leaves_the_token_of_another_instance_alone(self):
        path = self.directory / "shared" / "session.token"
        path.parent.mkdir()
        path.write_text("other-instance-token", encoding="utf-8")
        bridge = self.unstarted(lambda: "mine", "shared", token_path=path)
        bridge._server_name = ""
        with self.assertLogs(self.LOGGER, logging.WARNING):
            self.assertIs(bridge.start(), False)
        self.assertEqual(path.read_text(encoding="utf-8"), "other-instance-token")
        self.assertEqual(self.files_left(), ["session.token"])
        self.assertIsNone(bridge._token)

    def test_a_token_that_cannot_be_published_closes_the_pipe_again(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        bridge = self.unstarted(lambda: "unpublished", "publish")
        with patch.object(
            ai_takeoff_bridge.os, "replace", side_effect=PermissionError("denied")
        ):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                self.assertIs(bridge.start(), False)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:"
                "Failed to write the AI takeoff session token: PermissionError"
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_an_interrupt_during_start_leaves_nothing_listening(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        for interrupt in (KeyboardInterrupt, SystemExit):
            for where in (
                "factory",
                "before listen",
                "after listen",
                "publish",
                "after publish",
            ):
                with self.subTest(interrupt=interrupt.__name__, where=where):
                    raised = interrupt()

                    def factory(where=where, raised=raised):
                        if where == "factory":
                            raise raised
                        return "interrupted"

                    bridge = self.unstarted(
                        factory, f"{interrupt.__name__}-{where}".replace(" ", "-")
                    )
                    if where in ("before listen", "after listen"):
                        key = (
                            "fail_before" if where == "before listen" else "fail_after"
                        )
                        bridge._server = FaultyServer(
                            bridge._server, **{key: {"listen": raised}}
                        )
                    with contextlib.ExitStack() as stack:
                        if where == "publish":
                            stack.enter_context(
                                patch.object(
                                    ai_takeoff_bridge.os, "replace", side_effect=raised
                                )
                            )
                        if where == "after publish":
                            real_publish = ai_takeoff_bridge._publish_token

                            def publish_then_interrupt(path, raised=raised):
                                real_publish(path)
                                raise raised

                            stack.enter_context(
                                patch.object(
                                    ai_takeoff_bridge,
                                    "_publish_token",
                                    publish_then_interrupt,
                                )
                            )
                        with self.assertRaises(interrupt) as caught:
                            bridge.start()
                    self.assertIs(caught.exception, raised)
                    self.assert_nothing_listening(bridge)

    def test_an_error_while_cleaning_up_a_failed_start_never_masks_the_interrupt(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        raised = KeyboardInterrupt()
        bridge = self.unstarted(lambda: "interrupted", "masked")
        bridge._server = FaultyServer(
            bridge._server, fail_after={"close": RuntimeError("secret detail")}
        )
        with patch.object(ai_takeoff_bridge.os, "replace", side_effect=raised):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    bridge.start()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: RuntimeError"
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_starting_a_second_time_does_not_disturb_the_running_pipe(self):
        self.assertIs(self.bridge.start(), False)
        self.assertTrue(self.bridge._server.isListening())
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "token-0")
        self.assertEqual(
            [path.name for path in self.token_path.parent.iterdir()],
            ["session.token"],
        )
        self.assertEqual(self.call("list_levels")["status"], "ok")

    def test_a_second_start_whose_token_factory_fails_leaves_the_running_pipe_alone(
        self,
    ):
        def factory():
            raise ValueError("factory failed")

        self.bridge._token_factory = factory
        with self.assertRaises(ValueError):
            self.bridge.start()
        self.assertTrue(self.bridge._server.isListening())
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "token-0")
        self.assertEqual(self.call("list_levels")["status"], "ok")

    def test_a_failed_listen_names_a_cleanup_error_without_hiding_the_failed_start(
        self,
    ):
        bridge = self.unstarted(lambda: "mine", "listen-cleanup")
        bridge._server_name = ""
        with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                self.assertIs(bridge.start(), False)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:Failed to start the AI takeoff bridge",
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after a failed listen: PermissionError",
            ],
        )
        self.assertIsNone(bridge._token)

    def test_a_token_with_non_ascii_text_is_published_as_utf8(self):
        token = "tok\u00e9\u4e2d"
        bridge = self.unstarted(lambda: token, "utf8")
        self.assertTrue(bridge.start())
        self.assertEqual(self.start_token_path.read_bytes(), token.encode("utf-8"))

    def test_a_cleanup_error_after_an_os_error_names_that_os_error(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        bridge = self.unstarted(lambda: "named", "named")
        bridge._server = FaultyServer(
            bridge._server, fail_after={"close": RuntimeError("secret detail")}
        )
        with patch.object(
            ai_takeoff_bridge.os, "replace", side_effect=PermissionError("denied")
        ):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                self.assertIs(bridge.start(), False)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:"
                "Failed to write the AI takeoff session token: PermissionError",
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after PermissionError: RuntimeError",
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_an_interrupt_during_the_cleanup_after_an_os_error_is_still_raised(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        raised = KeyboardInterrupt()
        bridge = self.unstarted(lambda: "named", "os-then-interrupt")
        bridge._server = FaultyServer(bridge._server, fail_after={"close": raised})
        with patch.object(
            ai_takeoff_bridge.os, "replace", side_effect=PermissionError("denied")
        ):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    bridge.start()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:"
                "Failed to write the AI takeoff session token: PermissionError"
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_an_interrupt_during_the_cleanup_after_a_failed_listen_is_still_raised(
        self,
    ):
        raised = SystemExit()
        bridge = self.unstarted(lambda: "mine", "listen-then-interrupt")
        bridge._server_name = ""
        with patch.object(Path, "unlink", side_effect=raised):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                with self.assertRaises(SystemExit) as caught:
                    bridge.start()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [f"WARNING:{self.LOGGER}:Failed to start the AI takeoff bridge"],
        )

    def test_an_interrupt_during_the_cleanup_replaces_an_earlier_ordinary_error(self):
        def factory():
            raise ValueError("secret detail")

        raised = KeyboardInterrupt()
        bridge = self.unstarted(factory, "ordinary-then-interrupt")
        with patch.object(Path, "unlink", side_effect=raised):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    bridge.start()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: ValueError"
            ],
        )
        self.assert_nothing_listening(bridge)

    def test_the_first_of_two_interrupts_during_start_is_the_one_raised(self):
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        first = KeyboardInterrupt()
        bridge = self.unstarted(lambda: "twice", "two-interrupts")
        bridge._server = FaultyServer(
            bridge._server, fail_after={"close": SystemExit()}
        )
        with patch.object(ai_takeoff_bridge.os, "replace", side_effect=first):
            with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                with self.assertRaises(KeyboardInterrupt) as caught:
                    bridge.start()
        self.assertIs(caught.exception, first)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: SystemExit"
            ],
        )
        self.assert_nothing_listening(bridge)


class BridgeCleanupInterruptTests(BridgeTestCase):
    """cleanup() lets go of everything it can and raises what went wrong first."""

    LOGGER = "ost_visualizer.presentation.services.ai_takeoff_bridge"

    def faulty_bridge(self, bridge, **faults):
        bridge._server = FaultyServer(bridge._server, **faults)
        return bridge

    def assert_released(self, bridge):
        self.assertIsNone(bridge._server)
        self.assertIsNone(bridge._token)
        self.assertIsNone(bridge._read_service)
        self.assertEqual(bridge._commands, {})
        self.assertFalse(self.token_path.exists())

    def test_an_interrupt_during_cleanup_still_releases_everything_then_is_raised(
        self,
    ):
        for interrupt in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt.__name__):
                raised = interrupt()
                bridge = self.faulty_bridge(
                    self.capped_bridge(),
                    fail_after={
                        "close": raised,
                        "removeServer": RuntimeError("secret detail"),
                    },
                )
                with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
                    with self.assertRaises(interrupt) as caught:
                        bridge.cleanup()
                self.assertIs(caught.exception, raised)
                self.assertEqual(
                    captured.output,
                    [
                        f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step "
                        f"failed after {interrupt.__name__}: RuntimeError"
                    ],
                )
                self.assert_released(bridge)

    def test_an_interrupt_while_removing_the_token_still_stops_the_server(self):
        bridge = self.bridge
        server = bridge._server
        raised = KeyboardInterrupt()
        with patch.object(Path, "unlink", side_effect=raised):
            with self.assertRaises(KeyboardInterrupt) as caught:
                bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assertFalse(server.isListening())
        self.assertIsNone(bridge._server)
        self.assertIsNone(bridge._token)
        self.assertEqual(bridge._commands, {})

    def test_an_interrupt_while_aborting_one_connection_still_aborts_the_others(self):
        bridge = self.bridge
        raised = KeyboardInterrupt()
        aborted = []

        class Tracking(QLocalSocket):
            def __init__(self, parent, label, fail):
                super().__init__(parent)
                self.label = label
                self.fail = fail

            def abort(self):
                aborted.append(self.label)
                if self.fail:
                    raise raised

        first = Tracking(bridge, "first", True)
        second = Tracking(bridge, "second", False)
        with self.assertRaises(KeyboardInterrupt) as caught:
            bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assertEqual(sorted(aborted), ["first", "second"])
        self.assert_released(bridge)
        self.assertTrue(isValid(first) and isValid(second))
        self.delete_later_now()
        self.assertFalse(isValid(first) or isValid(second))

    def test_an_interrupt_while_detaching_the_connection_slot_still_closes_the_server(
        self,
    ):
        class Failing:
            def disconnect(self, *args):
                raise raised

        raised = KeyboardInterrupt()
        server = self.bridge._server
        bridge = self.faulty_bridge(
            self.bridge, attributes={"newConnection": Failing()}
        )
        with self.assertRaises(KeyboardInterrupt) as caught:
            bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assertFalse(server.isListening())
        self.assert_released(bridge)

    def test_an_interrupt_while_disconnecting_one_signal_still_disconnects_the_other(
        self,
    ):
        class Failing:
            def disconnect(self, *args):
                raise raised

        raised = KeyboardInterrupt()
        offered = []
        self.bridge.rebind_suggested.connect(lambda: offered.append(True))
        self.bridge._job_finished = Failing()
        with self.assertRaises(KeyboardInterrupt) as caught:
            self.bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assert_released(self.bridge)
        self.bridge.rebind_suggested.emit()
        self.assertEqual(offered, [])
        self.assertTrue(isValid(self.bridge))
        self.delete_later_now()
        self.assertFalse(isValid(self.bridge))

    def test_an_interrupt_after_an_ordinary_cleanup_error_is_still_raised(self):
        raised = KeyboardInterrupt()
        bridge = self.faulty_bridge(
            self.bridge,
            fail_after={"close": RuntimeError("secret detail"), "removeServer": raised},
        )
        with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
            with self.assertRaises(KeyboardInterrupt) as caught:
                bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: RuntimeError"
            ],
        )
        self.assert_released(bridge)

    def test_the_first_of_two_interrupts_during_cleanup_is_the_one_raised(self):
        first = KeyboardInterrupt()
        bridge = self.faulty_bridge(
            self.bridge, fail_after={"close": first, "removeServer": SystemExit()}
        )
        with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
            with self.assertRaises(KeyboardInterrupt) as caught:
                bridge.cleanup()
        self.assertIs(caught.exception, first)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: SystemExit"
            ],
        )
        self.assert_released(bridge)

    def test_an_error_after_an_interrupt_that_replaced_an_error_names_the_interrupt(
        self,
    ):
        class Failing:
            def disconnect(self, *args):
                raise ValueError("first")

        raised = KeyboardInterrupt()
        bridge = self.faulty_bridge(
            self.bridge,
            attributes={"newConnection": Failing()},
            fail_after={"close": raised, "removeServer": RuntimeError("third")},
        )
        with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
            with self.assertRaises(KeyboardInterrupt) as caught:
                bridge.cleanup()
        self.assertIs(caught.exception, raised)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: ValueError",
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after KeyboardInterrupt: RuntimeError",
            ],
        )
        self.assert_released(bridge)

    def test_two_ordinary_cleanup_errors_raise_the_first_and_log_the_second(self):
        first = RuntimeError("first")
        bridge = self.faulty_bridge(
            self.bridge,
            fail_after={"close": first, "removeServer": ValueError("second")},
        )
        with self.assertLogs(self.LOGGER, logging.WARNING) as captured:
            with self.assertRaises(RuntimeError) as caught:
                bridge.cleanup()
        self.assertIs(caught.exception, first)
        self.assertEqual(
            captured.output,
            [
                f"WARNING:{self.LOGGER}:An AI takeoff bridge cleanup step failed "
                "after RuntimeError: ValueError"
            ],
        )
        self.assert_released(bridge)

    def test_an_ordinary_error_in_one_cleanup_step_is_raised_after_the_rest_ran(self):
        error = RuntimeError("close failed")
        bridge = self.faulty_bridge(self.bridge, fail_after={"close": error})
        with self.assertRaises(RuntimeError) as caught:
            bridge.cleanup()
        self.assertIs(caught.exception, error)
        self.assert_released(bridge)

    def test_cleanup_ignores_a_token_path_that_cannot_be_read(self):
        self.bridge._token_path = self.directory / "bad\0name"
        self.bridge.cleanup()
        self.assertIsNone(self.bridge._token)
        self.assertIsNone(self.bridge._server)

    def test_cleanup_removes_a_token_file_that_ends_with_a_newline(self):
        self.token_path.write_text("token-0\n", encoding="utf-8")
        self.bridge.cleanup()
        self.assertFalse(self.token_path.exists())

    def test_cleanup_keeps_a_token_file_written_by_someone_else(self):
        self.token_path.write_text("token-1\n", encoding="utf-8")
        self.bridge.cleanup()
        self.assertEqual(self.token_path.read_text(encoding="utf-8"), "token-1\n")


class BridgeRequestShapeTests(BridgeTestCase):
    def test_a_command_that_is_not_text_is_answered_as_unknown(self):
        for label, command in (
            ("list", ["list_levels"]),
            ("dict", {"a": 1}),
            ("null", None),
            ("boolean", True),
        ):
            with self.subTest(label=label):
                socket = RecordingSocket()
                self.bridge._handle(socket, request_line(command=command))
                (reply,) = socket.replies()
                self.assertEqual(
                    (reply["status"], reply["error"]["message"]),
                    ("unknown_command", "This command is not available."),
                )
                self.assertEqual(socket.hung_up(), 1)
        self.assertEqual(self.service.calls, [])

    def test_an_interrupt_while_a_request_is_handled_is_not_turned_into_an_answer(
        self,
    ):
        """Characterisation: an interrupt leaves the slot instead of becoming a reply."""
        from ost_visualizer.presentation.services import ai_takeoff_bridge

        def raising(error):
            def raise_it(*args, **kwargs):
                raise error

            return raise_it

        audited = []
        bridge = self.capped_bridge(
            audit=lambda tool, arguments, outcome: audited.append(outcome)
        )
        line = request_line(token="capped-token")
        for interrupt in (KeyboardInterrupt, SystemExit):
            with self.subTest(interrupt=interrupt.__name__, where="parsing"):
                socket = RecordingSocket()
                with patch.object(
                    ai_takeoff_bridge.json, "loads", side_effect=interrupt()
                ):
                    with self.assertRaises(interrupt):
                        bridge._handle(socket, line)
                self.assertEqual(socket.events, [])
            with self.subTest(interrupt=interrupt.__name__, where="command"):
                socket = RecordingSocket()
                with patch.object(self.service, "list_levels", raising(interrupt())):
                    with self.assertRaises(interrupt):
                        bridge._handle(socket, line)
                self.assertEqual(socket.events, [])
                self.assertEqual(audited, [])
            with self.subTest(interrupt=interrupt.__name__, where="audit"):
                socket = RecordingSocket()
                with patch.object(bridge, "_audit", raising(interrupt())):
                    with self.assertRaises(interrupt):
                        bridge._handle(socket, line)
                self.assertEqual(len(socket.replies()), 1)
                self.assertEqual(socket.hung_up(), 1)

    def test_a_reply_is_flushed_before_the_hang_up(self):
        socket = RecordingSocket()
        self.bridge._respond(socket, ok_result({}))
        self.assertEqual(
            [event[0] for event in socket.events], ["write", "flush", "disconnect"]
        )

    def test_the_audit_of_a_worker_command_names_the_arguments_it_received(self):
        audited = []
        self.capped_bridge(
            audit=lambda tool, arguments, outcome: audited.append(
                (tool, arguments, outcome)
            )
        )
        cases = [
            ("list_text", {"page_uid": "p1", "query": "wall"}),
            ("list_segments", {"page_uid": "p1", "kinds": ["wall"]}),
            ("render_sheet", {"page_uid": "p1", "dpi": 100}),
            ("list_sheets", {"text_hints": True, "limit": 3}),
        ]
        for command, arguments in cases:
            with self.subTest(command=command):
                audited.clear()
                self.assertTrue(self.call(command, arguments)["success"])
                self.assertEqual(audited, [(command, arguments, "ok")])

    def test_the_audit_of_a_deferred_command_names_the_arguments_it_received(self):
        audited = []
        writes = DeferredWriteCommands()
        self.capped_bridge(
            write_commands=writes,
            idle_timeout_ms=60000,
            audit=lambda tool, arguments, outcome: audited.append(
                (tool, arguments, outcome)
            ),
        )
        handle = self.open_raw()
        self.addCleanup(handle.Close)
        self.write_raw(
            handle,
            b'{"token": "capped-token", "command": "apply_changeset", '
            b'"arguments": {"changeset_id": "c1"}}\n',
        )
        self.pump_until(lambda: len(writes.replies) == 1)
        writes.replies[0].resolve(ok_result({"changeset_id": "c1"}, "applied"))
        self.assertEqual(
            self.read_raw(handle), ok_result({"changeset_id": "c1"}, "applied")
        )
        self.assertEqual(
            audited, [("apply_changeset", {"changeset_id": "c1"}, "applied")]
        )


def live_bridge_workers():
    return [
        thread
        for thread in threading.enumerate()
        if thread.name == WORKER_THREAD and thread.is_alive()
    ]


def run_recording_bridges(*tests):
    created = []
    destroyed = []
    outlived = []
    original_init = TakeoffCommandBridge.__init__

    def tracked(bridge, *args, **kwargs):
        original_init(bridge, *args, **kwargs)
        created.append(bridge)
        bridge.destroyed.connect(
            lambda *_: destroyed.append(
                (threading.current_thread().name, len(live_bridge_workers()))
            ),
            QtCore.Qt.ConnectionType.DirectConnection,
        )

    class OutlivedResult(unittest.TestResult):
        def stopTest(self, test):
            super().stopTest(test)
            if any(isValid(bridge) for bridge in created):
                outlived.append(test.id())

    result = OutlivedResult()
    suite = unittest.TestSuite(
        (
            unittest.defaultTestLoader.loadTestsFromTestCase(test)
            if isinstance(test, type)
            else test
        )
        for test in tests
    )
    with patch.object(TakeoffCommandBridge, "__init__", tracked):
        suite.run(result)
    return result, created, destroyed, outlived


class BridgeFixtureLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BridgeTestCase.setUpClass()

    def test_every_bridge_is_deleted_on_the_gui_thread_by_its_own_test(self):
        result, created, destroyed, outlived = run_recording_bridges(
            BridgeProtocolTests,
            BridgeCapacityTests,
            BridgeSecurityTests,
            BridgeThreadingTests,
            BridgeStartupTests,
            BridgeConnectionLifecycleTests,
            BridgeRequestEdgeTests,
            BridgeWorkerLifecycleTests,
            BridgeDeferredReplyTests,
            BridgeCleanupReleaseTests,
        )
        self.assertEqual(result.errors + result.failures, [])
        self.assertGreater(result.testsRun, 60)
        self.assertEqual(outlived, [])
        self.assertEqual([isValid(bridge) for bridge in created].count(True), 0)
        self.assertEqual(set(destroyed), {(threading.main_thread().name, 0)})
        self.assertEqual(len(destroyed), len(created))

    def test_a_failing_capacity_check_still_releases_its_blocked_workers(self):
        class FailingCapacity(BridgeCapacityTests):
            def call(self, command, arguments=None, token_path=None):
                if (arguments or {}).get("page_uid") == "p9":
                    return {"status": "not busy"}
                return super().call(command, arguments, token_path)

        waits = []
        real_event = threading.Event

        class RecordingEvent(real_event):
            def wait(self, timeout=None):
                released = super().wait(timeout)
                if timeout == 10:
                    waits.append(released)
                return released

        with patch.object(threading, "Event", RecordingEvent):
            result, created, destroyed, _outlived = run_recording_bridges(
                FailingCapacity(
                    "test_requests_beyond_the_worker_cap_get_busy_and_capacity_returns"
                )
            )
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(waits, [True, True])
        self.assertEqual(len(created), 2)
        self.assertEqual(destroyed, [(threading.main_thread().name, 0)] * 2)


if __name__ == "__main__":
    unittest.main()
