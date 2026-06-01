import unittest
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow


class FakeMeshSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, value):
        self.emitted.append(list(value))


class FakeMeshScene:
    def __init__(self, takeoff_uids):
        self.takeoff_uids = list(takeoff_uids)
        self.selected = set()
        self.clear_calls = 0

    def mesh_count(self):
        return len(self.takeoff_uids)

    def get_takeoff_uid(self, index):
        return self.takeoff_uids[index]

    def clear_selection(self):
        self.clear_calls += 1
        self.selected.clear()

    def set_selected(self, index, selected):
        if selected:
            self.selected.add(index)
        else:
            self.selected.discard(index)


class TestMeshViewLifecycle(unittest.TestCase):
    def test_cleanup_clears_external_callback_references(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        retained = object()
        viewer._destroyed = False
        viewer._pending_data = retained
        viewer._current_bid_ref = retained
        viewer._pending_camera_reset = True
        viewer._render_suspended = False
        viewer._negative_check_fn = lambda _uids: retained
        viewer._curved_check_fn = lambda _uids: retained
        viewer._selected_context_state_fn = lambda _uids: retained
        viewer._context_menu_command_trigger = lambda _key: retained
        viewer._context_menu_action_state = lambda: retained
        viewer._context_menu_conditions_fn = lambda: {"condition": retained}
        viewer._zoom_cursor = retained
        viewer._animation_timer = None
        viewer._renderer = None
        OpenGLViewer.cleanup(viewer)
        self.assertIsNone(viewer._pending_data)
        self.assertIsNone(viewer._current_bid_ref)
        self.assertIsNone(viewer._selected_context_state_fn)
        self.assertIsNone(viewer._context_menu_command_trigger)
        self.assertIsNone(viewer._context_menu_action_state)
        self.assertIsNone(viewer._zoom_cursor)
        self.assertFalse(viewer._negative_check_fn(["uid"]))
        self.assertEqual((False, False), viewer._curved_check_fn(["uid"]))
        self.assertEqual({}, viewer._context_menu_conditions_fn())

    def test_scene_rebuild_drops_missing_selected_takeoffs(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["keep"])
        viewer._renderer = type("Renderer", (), {"scene": scene})()
        viewer._selected_takeoff_uids = ["keep", "deleted"]
        viewer.mesh_clicked = FakeMeshSignal()
        OpenGLViewer._reconcile_selected_takeoffs_with_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["keep"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [["keep"]])

    def test_scene_rebuild_reapplies_valid_cached_selection(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["keep"])
        viewer._renderer = type("Renderer", (), {"scene": scene})()
        viewer._selected_takeoff_uids = ["keep"]
        viewer.mesh_clicked = FakeMeshSignal()
        OpenGLViewer._reconcile_selected_takeoffs_with_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["keep"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_mesh_window_cleanup_clears_external_callback_references(self):
        window = MeshViewWindow.__new__(MeshViewWindow)
        retained = object()
        window._is_closing = False
        window._resize_timer = None
        window.viewer = None
        window._zoom_combo = retained
        window._context_menu_command_trigger = lambda _key: retained
        window._context_menu_action_state = lambda: retained
        window.icon_provider = retained
        window._color_service = retained
        MeshViewWindow.cleanup(window)
        self.assertIsNone(window._zoom_combo)
        self.assertIsNone(window._context_menu_command_trigger)
        self.assertIsNone(window._context_menu_action_state)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._color_service)


if __name__ == "__main__":
    unittest.main()
