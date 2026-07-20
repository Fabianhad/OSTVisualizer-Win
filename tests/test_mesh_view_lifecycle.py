import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtCore
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.dtos.mesh_geometry_dto import MeshGeometry
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_DEFAULT
from ost_visualizer.presentation.visualization.native_page_plane import (
    NativePageImagePlaneData,
)
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

    def empty(self):
        return not self.takeoff_uids


class FakeMeshCamera:
    def __init__(self):
        self.reset_calls = 0
        self.show_object_calls = []
        self.position = SimpleNamespace(x=10.0, y=20.0, z=30.0)
        self.target = SimpleNamespace(x=1.0, y=2.0, z=3.0)
        self.fov = 37.0
        self.rotate_calls = []
        self.pan_calls = []

    def reset(self):
        self.reset_calls += 1

    def show_object(self, bounds):
        self.show_object_calls.append(bounds)
        self.position = SimpleNamespace(x=100.0, y=200.0, z=300.0)
        self.target = SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.fov = 45.0

    def rotate(self, delta_x, delta_y):
        self.rotate_calls.append((delta_x, delta_y))

    def pan(self, delta_x, delta_y):
        self.pan_calls.append((delta_x, delta_y))


class FakeMeshRenderer:
    def __init__(self, scene):
        self.scene = scene
        self.camera = FakeMeshCamera()
        self.suspend_calls = 0
        self.plan_texture_calls = []
        self.plan_texture_visibility_calls = []
        self.clear_plan_texture_calls = 0
        self.resize_calls = []
        self.clear_frame_calls = 0

    def suspend(self):
        self.suspend_calls += 1

    def resume(self):
        pass

    def resize(self, width_px, height_px):
        self.resize_calls.append((width_px, height_px))
        self.camera.aspect_ratio = width_px / height_px

    def clear_frame(self):
        self.clear_frame_calls += 1

    def clear_plan_texture(self):
        self.clear_plan_texture_calls += 1

    def set_plan_texture(self, *args):
        self.plan_texture_calls.append(args)

    def set_plan_texture_visibility(self, visible):
        self.plan_texture_visibility_calls.append(bool(visible))


class FakePickingMeshRenderer(FakeMeshRenderer):
    def __init__(self, scene, pick_index):
        super().__init__(scene)
        self.pick_index = pick_index
        self.pick_calls = []

    def pick(self, px, py):
        self.pick_calls.append((px, py))
        return self.pick_index


class FailingInitializationRenderer:
    def __init__(self, _window_handle):
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1


class FakeSourceMesh:
    vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    faces = [(0, 1, 2)]


class TestMeshViewLifecycle(unittest.TestCase):
    @staticmethod
    def _page_texture(page_uid="p1", visible=True):
        return NativePageImagePlaneData(
            page_uid=page_uid,
            pixels_rgba=b"\x01\x02\x03\x04",
            width_px=1,
            height_px=1,
            page_width=10.0,
            page_height=20.0,
            plane_x=-5.0,
            plane_y=10.0,
            plane_z=-0.01,
            opacity=1.0,
            visible=visible,
            flip_u=True,
            flip_v=False,
        )

    def _make_page_plane_viewer(self, textures):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        renderer = FakeMeshRenderer(FakeMeshScene([]))
        viewer._renderer = renderer
        viewer._ensure_renderer = lambda: True
        viewer._current_bid_ref = BidRef("a.mdb", "bid-1")
        viewer._selected_takeoff_uids = []
        viewer._current_plan_texture = self._page_texture("existing")
        viewer._has_visible_plan_texture = True
        viewer._render_suspended = False
        viewer._zoom_reference_distance = 77.0
        viewer._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1, 1, 1, 1)
        )
        texture_iter = iter(textures)
        viewer._plan_texture_provider = lambda _bounds: next(texture_iter)
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.zoom_changed = SimpleNamespace(emit=lambda _value: None)
        viewer.update = lambda: None
        return viewer, renderer

    @staticmethod
    def _camera_state(viewer, renderer):
        return (
            renderer.camera.position.x,
            renderer.camera.position.y,
            renderer.camera.position.z,
            renderer.camera.target.x,
            renderer.camera.target.y,
            renderer.camera.target.z,
            renderer.camera.fov,
            viewer._zoom_reference_distance,
        )

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
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer._render_surface_size = None
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

    def test_failed_renderer_initialization_releases_partial_renderer(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._renderer = None
        viewer._render_surface_size = None
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer._pending_camera_reset = False
        viewer.winId = lambda: 123
        viewer._connect_surface_notifications = lambda: (_ for _ in ()).throw(
            RuntimeError("surface setup failed")
        )
        viewer._disconnect_surface_notifications = lambda: None
        created = []

        def create_renderer(window_handle):
            renderer = FailingInitializationRenderer(window_handle)
            created.append(renderer)
            return renderer

        with patch(
            "ost_visualizer.presentation.components.mesh_view.ost_renderer.Renderer",
            create_renderer,
        ), self.assertLogs(
            "ost_visualizer.presentation.components.mesh_view", level="ERROR"
        ):
            self.assertFalse(OpenGLViewer._ensure_renderer(viewer))
        self.assertIsNone(viewer._renderer)
        self.assertIsNone(viewer._render_surface_size)
        self.assertEqual(created[0].shutdown_calls, 1)

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

    def test_visibility_only_update_uses_native_visibility_operation(self):
        viewer, renderer = self._make_page_plane_viewer([])
        OpenGLViewer.set_plan_texture_visibility(viewer, False)
        OpenGLViewer.set_plan_texture_visibility(viewer, True)
        self.assertEqual(renderer.plan_texture_visibility_calls, [False, True])
        self.assertEqual(renderer.plan_texture_calls, [])

    def test_same_bid_scene_update_preserves_camera_without_fit_or_reset(self):
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("p2")])
        before = self._camera_state(viewer, renderer)
        OpenGLViewer._do_apply_mesh_data(
            viewer, [], [], [], [], BidRef("a.mdb", "bid-1")
        )
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)
        self.assertEqual(len(renderer.plan_texture_calls), 1)

    def test_page_texture_updates_preserve_camera_and_selected_visibility(self):
        viewer, renderer = self._make_page_plane_viewer(
            [self._page_texture("p2", visible=False), self._page_texture("p1")]
        )
        before = self._camera_state(viewer, renderer)
        OpenGLViewer.update_plan_texture(viewer)
        self.assertFalse(viewer._has_visible_plan_texture)
        OpenGLViewer.update_plan_texture(viewer)
        self.assertTrue(viewer._has_visible_plan_texture)
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(renderer.plan_texture_visibility_calls, [])
        self.assertEqual(
            [call[9] for call in renderer.plan_texture_calls], [False, True]
        )
        self.assertEqual(len(renderer.plan_texture_calls), 2)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_missing_page_texture_update_clears_without_camera_reset(self):
        viewer, renderer = self._make_page_plane_viewer([None])
        before = self._camera_state(viewer, renderer)
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_initial_page_plane_creation_still_frames_camera(self):
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("p1")])
        viewer._current_bid_ref = None
        viewer._current_plan_texture = None
        viewer._has_visible_plan_texture = False
        OpenGLViewer._do_apply_mesh_data(
            viewer, [], [], [], [], BidRef("a.mdb", "bid-1")
        )
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_explicit_reset_view_still_fits_current_content(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._get_camera_distance = lambda: 123.0
        OpenGLViewer.reset_view(viewer)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(viewer._zoom_reference_distance, 123.0)

    def test_user_mesh_pick_broadcasts_selected_takeoff(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["selected"])
        viewer._renderer = FakePickingMeshRenderer(scene, 0)
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.width = lambda: 100
        viewer.height = lambda: 100
        viewer.devicePixelRatioF = lambda: 1.0
        viewer.update = lambda: None
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(10, 20), ctrl=False)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["selected"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [["selected"]])

    def test_user_mesh_pick_uses_current_fractional_device_pixel_ratio(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        renderer = FakePickingMeshRenderer(FakeMeshScene(["selected"]), 0)
        viewer._renderer = renderer
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.width = lambda: 801
        viewer.height = lambda: 603
        viewer.devicePixelRatioF = lambda: 1.25
        viewer.update = lambda: None
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(13, 17), ctrl=False)
        self.assertEqual(renderer.pick_calls, [(16, 21)])

    def test_orbit_keeps_fractional_qt_delta_in_logical_coordinates(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        renderer = FakeMeshRenderer(FakeMeshScene([]))
        viewer._renderer = renderer
        viewer._cursor_mode = CURSOR_MODE_DEFAULT
        viewer._last_mouse_pos = QtCore.QPointF(10.25, 20.25)
        viewer._click_pos = None
        viewer.update = lambda: None
        event = SimpleNamespace(
            position=lambda: QtCore.QPointF(10.75, 20.5),
            buttons=lambda: QtCore.Qt.MouseButton.LeftButton,
            accept=lambda: None,
            ignore=lambda: None,
        )
        OpenGLViewer.mouseMoveEvent(viewer, event)
        self.assertEqual(renderer.camera.rotate_calls, [(0.5, 0.25)])
        self.assertEqual(renderer.camera.pan_calls, [])

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
