import json
import threading
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.mcp_server.bridge_client import McpBridgeClient
from ost_visualizer.presentation.services import mcp_context_bridge
from ost_visualizer.presentation.services.mcp_context_bridge import McpContextBridge
from PySide6 import QtWidgets


class _FakePlanView:
    def __init__(self, uids):
        self._uids = list(uids)

    def get_selected_takeoff_uids(self):
        return list(self._uids)


class _FakeViewer:
    def __init__(self, uids):
        self._uids = list(uids)

    def get_selected_takeoff_uids(self):
        return list(self._uids)


class _FakeWindow:
    def __init__(self, viewer_uids, mesh_window=None, active_view="3d"):
        self.opengl_viewer = None if viewer_uids is None else _FakeViewer(viewer_uids)
        self._mesh_window = mesh_window
        self._active_view = active_view
        self.tab_widget = SimpleNamespace(
            currentIndex=lambda: 1, tabText=lambda index: f"Tab {index}"
        )

    def get_mesh_window(self):
        return self._mesh_window

    def get_active_takeoff_view(self):
        return self._active_view

    def is_takeoff_tab_active(self):
        return True


class _FakeSocket:
    def __init__(self, request):
        self._request = request
        self.written = []
        self.events = []

    def readAll(self):
        return self._request

    def write(self, data):
        self.events.append("write")
        self.written.append(bytes(data))

    def flush(self):
        self.events.append("flush")

    def disconnectFromServer(self):
        self.events.append("disconnect")


class McpContextBridgeSelectionTests(unittest.TestCase):
    @staticmethod
    def _app():
        return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _bridge(self, plan_uids, viewer_uids, mesh_uids=None):
        bridge = McpContextBridge.__new__(McpContextBridge)
        bridge._plan_view = _FakePlanView(plan_uids)
        mesh_window = _FakeViewer(mesh_uids or []) if mesh_uids is not None else None
        bridge._main_window = _FakeWindow(viewer_uids, mesh_window)
        return bridge

    def test_active_3d_selection_prefers_3d_viewer(self):
        bridge = self._bridge(
            plan_uids=["plan-1"], viewer_uids=["3d-1"], mesh_uids=["mesh-1"]
        )
        self.assertEqual(bridge._selected_takeoff_uids("3d"), ["3d-1"])

    def test_active_2d_selection_prefers_plan_view_over_3d_selection(self):
        bridge = self._bridge(plan_uids=["plan-1"], viewer_uids=["3d-1"])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), ["plan-1"])

    def test_active_3d_selection_falls_back_to_plan_view_when_3d_is_empty(self):
        bridge = self._bridge(
            plan_uids=["plan-1"], viewer_uids=[], mesh_uids=["mesh-1"]
        )
        self.assertEqual(bridge._selected_takeoff_uids("3d"), ["plan-1"])

    def test_active_2d_selection_falls_back_to_3d_selection(self):
        bridge = self._bridge(plan_uids=[], viewer_uids=["3d-1"], mesh_uids=["mesh-1"])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), ["3d-1"])

    def test_selection_falls_back_to_detached_mesh_window(self):
        bridge = self._bridge(plan_uids=[], viewer_uids=[], mesh_uids=["mesh-1"])
        self.assertEqual(bridge._selected_takeoff_uids("3d"), ["mesh-1"])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), ["mesh-1"])

    def test_selection_is_empty_without_embedded_viewer_or_mesh_window(self):
        bridge = self._bridge(plan_uids=[], viewer_uids=None)
        self.assertEqual(bridge._selected_takeoff_uids("3d"), [])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), [])

    def test_selection_uids_are_stringified_deduplicated_and_blank_free(self):
        bridge = self._bridge(plan_uids=[12, "12", "", "7", 7], viewer_uids=[])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), ["12", "7"])

    def test_cleanup_releases_server_and_ui_references(self):
        self._app()
        bridge_name = f"OSTVisualizerMcpBridgeTest.{uuid.uuid4().hex}"
        with patch.object(mcp_context_bridge, "MCP_BRIDGE_SERVER_NAME", bridge_name):
            bridge = McpContextBridge(
                main_window=object(),
                ui_state_manager=object(),
                project_data_service=object(),
                plan_view=object(),
            )
            bridge.start()
            server = bridge._server
            self.assertTrue(server.isListening())
            bridge.cleanup()
        self.assertFalse(server.isListening())
        self.assertIsNone(bridge._server)
        self.assertIsNone(bridge._main_window)
        self.assertIsNone(bridge._ui_state)
        self.assertIsNone(bridge._project_data)
        self.assertIsNone(bridge._plan_view)
        bridge.cleanup()
        self.assertIsNone(bridge._server)


class McpContextBridgeRequestTests(unittest.TestCase):
    def _bridge(self, active_view="2d"):
        bridge = McpContextBridge.__new__(McpContextBridge)
        bridge._plan_view = _FakePlanView(["plan-1", "plan-1"])
        bridge._main_window = _FakeWindow(["3d-1"], active_view=active_view)
        bid_ref = BidRef("C:/jobs/a.mdb", "bid-1")
        bridge._ui_state = SimpleNamespace(
            get_selected_bid_ref=lambda: bid_ref,
            get_selected_bid_refs=lambda: [
                bid_ref,
                BidRef("C:/jobs/a.mdb", "bid-2"),
            ],
            selected_file_path="C:/jobs/a.mdb",
            active_page_uid="page-1",
            is_database_selected=lambda: True,
            selected_project_uid="project-1",
            selected_project_uids=["project-1"],
            selected_page_uids=["page-1", "page-2"],
            highlighted_condition_uids={"c2", "c1"},
            place_condition_uid="c1",
            place_condition_uids=["c1"],
            selected_area_uid="area-1",
        )
        bridge._project_data = SimpleNamespace(
            get_current_bid_ref=lambda: None,
            is_current_bid_locked=lambda: False,
        )
        return bridge

    def test_get_context_request_replies_with_live_snapshot_then_disconnects(self):
        bridge = self._bridge()
        socket = _FakeSocket(b'{"command": "get_context"}')
        bridge._handle_request(socket)
        response = json.loads(socket.written[0].decode("utf-8"))
        self.assertTrue(response["success"])
        data = response["data"]
        self.assertEqual(data["source"], "live_app")
        self.assertEqual(data["active_tab_index"], 1)
        self.assertEqual(data["active_tab_name"], "Tab 1")
        self.assertEqual(data["active_view"], "2d")
        self.assertTrue(data["is_takeoff_tab_active"])
        self.assertEqual(
            data["selected_bid_ref"],
            {"file_path": "C:/jobs/a.mdb", "bid_uid": "bid-1"},
        )
        self.assertEqual(
            data["selected_bid_refs"],
            [
                {"file_path": "C:/jobs/a.mdb", "bid_uid": "bid-1"},
                {"file_path": "C:/jobs/a.mdb", "bid_uid": "bid-2"},
            ],
        )
        self.assertIsNone(data["current_bid_ref"])
        self.assertFalse(data["current_bid_locked"])
        self.assertEqual(data["selected_page_uids"], ["page-1", "page-2"])
        self.assertEqual(data["mesh_page_uids"], ["page-1", "page-2"])
        self.assertEqual(data["highlighted_condition_uids"], ["c1", "c2"])
        self.assertEqual(data["selected_area_uid"], "area-1")
        self.assertEqual(data["selected_takeoff_uids"], ["plan-1"])
        self.assertEqual(socket.events, ["write", "flush", "disconnect"])

    def test_unsupported_command_is_rejected_without_building_snapshot(self):
        bridge = self._bridge()
        bridge._ui_state = None
        socket = _FakeSocket(b'{"command": "delete_everything"}')
        bridge._handle_request(socket)
        self.assertEqual(
            json.loads(socket.written[0].decode("utf-8")),
            {"success": False, "error": "unsupported_command"},
        )
        self.assertEqual(socket.events, ["write", "flush", "disconnect"])

    def test_malformed_request_returns_error_response(self):
        bridge = self._bridge()
        socket = _FakeSocket(b"{not json")
        bridge._handle_request(socket)
        response = json.loads(socket.written[0].decode("utf-8"))
        self.assertFalse(response["success"])
        self.assertTrue(response["error"])
        self.assertEqual(socket.events, ["write", "flush", "disconnect"])

    def test_empty_request_is_treated_as_unsupported_command(self):
        bridge = self._bridge()
        socket = _FakeSocket(b"")
        bridge._handle_request(socket)
        self.assertEqual(
            json.loads(socket.written[0].decode("utf-8")),
            {"success": False, "error": "unsupported_command"},
        )


class McpContextBridgePipeTests(unittest.TestCase):
    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.server_name = f"OSTVisualizerMcpBridgeTest.{uuid.uuid4().hex}"
        fixture = McpContextBridgeRequestTests._bridge(self)
        with patch.object(
            mcp_context_bridge, "MCP_BRIDGE_SERVER_NAME", self.server_name
        ):
            self.bridge = McpContextBridge(
                main_window=fixture._main_window,
                ui_state_manager=fixture._ui_state,
                project_data_service=fixture._project_data,
                plan_view=fixture._plan_view,
            )
            self.bridge.start()
            self.addCleanup(self._cleanup)
        self.assertTrue(self.bridge._server.isListening())

    def _cleanup(self):
        with patch.object(
            mcp_context_bridge, "MCP_BRIDGE_SERVER_NAME", self.server_name
        ):
            self.bridge.cleanup()

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
        self.assertNotIn("S-1-1-0", sids)
        self.assertNotIn("S-1-5-7", sids)

    def test_read_server_client_of_the_same_user_still_gets_live_context(self):
        client = McpBridgeClient(timeout_ms=1000, server_name=self.server_name)
        results = []
        thread = threading.Thread(target=lambda: results.append(client.get_context()))
        thread.start()
        deadline = time.monotonic() + 15
        while thread.is_alive() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(client.last_status, "live_context")
        self.assertEqual(results[0]["source"], "live_app")
        self.assertEqual(results[0]["selected_takeoff_uids"], ["plan-1"])


if __name__ == "__main__":
    unittest.main()
