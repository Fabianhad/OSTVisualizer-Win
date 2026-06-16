import unittest
from PySide6 import QtCore
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshGeometry
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.visualization.utils.mesh import meshes_to_geometries
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow


class FakeColorService:
    def as_hex_with_opacity(self, color_entry):
        if isinstance(color_entry, dict):
            return color_entry["color"], color_entry["opacity"]
        return color_entry, 1.0


class FakeMeshSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, value):
        self.emitted.append(list(value))


class FakeMeshScene:
    def __init__(self, takeoff_uids, condition_uids=None):
        self.takeoff_uids = list(takeoff_uids)
        self.condition_uids = list(condition_uids or ["condition"] * len(takeoff_uids))
        self.selected = set()
        self.clear_calls = 0

    def mesh_count(self):
        return len(self.takeoff_uids)

    def get_takeoff_uid(self, index):
        return self.takeoff_uids[index]

    def get_condition_uid(self, index):
        return self.condition_uids[index]

    def clear_selection(self):
        self.clear_calls += 1
        self.selected.clear()

    def set_selected(self, index, selected):
        if selected:
            self.selected.add(index)
        else:
            self.selected.discard(index)

    def clear(self):
        self.takeoff_uids = []
        self.selected.clear()


class FakeMeshCamera:
    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


class FakeMeshRenderer:
    def __init__(self, scene):
        self.scene = scene
        self.camera = FakeMeshCamera()
        self.suspend_calls = 0

    def suspend(self):
        self.suspend_calls += 1


class FakePickingMeshRenderer(FakeMeshRenderer):
    def __init__(self, scene, pick_index):
        super().__init__(scene)
        self.pick_index = pick_index

    def pick(self, _px, _py):
        return self.pick_index


class FakeSourceMesh:
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2)]


class TestMeshViewLifecycle(unittest.TestCase):
    def test_meshes_to_geometries_returns_typed_mesh_geometry(self):
        geometries, _bounds = meshes_to_geometries(
            [FakeSourceMesh()],
            {
                "mesh_0": {
                    "color": "#112233",
                    "opacity": 0.5,
                    "condition_uid": "condition-1",
                    "takeoff_uid": "takeoff-1",
                }
            },
            FakeColorService(),
        )
        self.assertEqual(1, len(geometries))
        geometry = geometries[0]
        self.assertIsInstance(geometry, MeshGeometry)
        self.assertEqual("#112233", geometry.color)
        self.assertEqual(0.5, geometry.opacity)
        self.assertEqual("condition-1", geometry.condition_uid)
        self.assertEqual("takeoff-1", geometry.takeoff_uid)
        self.assertEqual([0, 1, 2], geometry.indices)

    def test_mesh_buffer_length_mismatch_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "matching lengths"):
            OpenGLViewer._validate_mesh_buffer_lengths(
                [[0.0, 0.0, 0.0]],
                [],
                [[0, 1, 2]],
                [{"color": "#ffffff", "opacity": 1.0}],
                ["condition-1"],
                ["takeoff-1"],
            )

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

    def test_scene_rebuild_drops_missing_selected_takeoffs_without_broadcasting(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["keep"])
        viewer._renderer = type("Renderer", (), {"scene": scene})()
        viewer._selected_takeoff_uids = ["keep", "deleted"]
        viewer.mesh_clicked = FakeMeshSignal()
        OpenGLViewer._reconcile_selected_takeoffs_with_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["keep"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

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

    def test_programmatic_clear_scene_does_not_broadcast_empty_mesh_selection(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["selected"])
        renderer = FakeMeshRenderer(scene)
        viewer._renderer = renderer
        viewer._selected_takeoff_uids = ["selected"]
        viewer._pending_data = object()
        viewer._current_bid_ref = object()
        viewer._pending_camera_reset = False
        viewer._render_suspended = False
        viewer._zoom_reference_distance = 3.0
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.update = lambda: None
        OpenGLViewer._do_clear(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertEqual(viewer.mesh_clicked.emitted, [])
        self.assertEqual(renderer.camera.reset_calls, 1)
        self.assertEqual(renderer.suspend_calls, 1)

    def test_user_mesh_pick_broadcasts_selected_takeoff(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["selected"])
        viewer._renderer = FakePickingMeshRenderer(scene, 0)
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.devicePixelRatioF = lambda: 1.0
        viewer.update = lambda: None
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(10, 20), ctrl=False)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["selected"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [["selected"]])

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
