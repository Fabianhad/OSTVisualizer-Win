import json
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.domain.entities.identity_refs import BidRef
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


if __name__ == "__main__":
    unittest.main()
