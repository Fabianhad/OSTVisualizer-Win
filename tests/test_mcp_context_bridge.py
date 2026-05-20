import unittest
from ost_visualizer.presentation.services.mcp_context_bridge import McpContextBridge


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
    def __init__(self, viewer_uids, mesh_window=None):
        self.opengl_viewer = _FakeViewer(viewer_uids)
        self._mesh_window = mesh_window

    def get_mesh_window(self):
        return self._mesh_window


class McpContextBridgeSelectionTests(unittest.TestCase):
    def _bridge(self, plan_uids, viewer_uids, mesh_uids=None):
        bridge = McpContextBridge.__new__(McpContextBridge)
        bridge._plan_view = _FakePlanView(plan_uids)
        mesh_window = _FakeViewer(mesh_uids or []) if mesh_uids is not None else None
        bridge._main_window = _FakeWindow(viewer_uids, mesh_window)
        return bridge

    def test_active_3d_selection_prefers_3d_viewer(self):
        bridge = self._bridge(plan_uids=["plan-1"], viewer_uids=["3d-1"])
        self.assertEqual(bridge._selected_takeoff_uids("3d"), ["3d-1"])

    def test_active_2d_selection_falls_back_to_3d_selection(self):
        bridge = self._bridge(plan_uids=[], viewer_uids=["3d-1"])
        self.assertEqual(bridge._selected_takeoff_uids("2d"), ["3d-1"])

    def test_selection_falls_back_to_detached_mesh_window(self):
        bridge = self._bridge(plan_uids=[], viewer_uids=[], mesh_uids=["mesh-1"])
        self.assertEqual(bridge._selected_takeoff_uids("3d"), ["mesh-1"])


if __name__ == "__main__":
    unittest.main()
