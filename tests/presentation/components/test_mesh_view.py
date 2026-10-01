from ost_visualizer.presentation.components.mesh_view import OpenGLViewer
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer, ost_renderer
from ost_visualizer.presentation.modes.cursor import (
    CURSOR_MODE_DEFAULT,
    CURSOR_MODE_PAN,
)
from ost_visualizer.presentation.visualization.native_page_plane import (
    NativePageImagePlaneData,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.components.mesh_support import (
    FailingInitializationRenderer as _mesh_support_FailingInitializationRenderer,
    FakeColorService as _mesh_support_FakeColorService,
    FakeMeshCamera as _mesh_support_FakeMeshCamera,
    FakeMeshRenderer as _mesh_support_FakeMeshRenderer,
    FakeMeshScene as _mesh_support_FakeMeshScene,
    FakeMeshSignal as _mesh_support_FakeMeshSignal,
    FakePickingMeshRenderer as _mesh_support_FakePickingMeshRenderer,
)
from PySide6 import QtCore, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class _Camera:
    aspect_ratio = 1.0


class _Renderer:
    def __init__(self):
        self.resize_calls = []
        self.camera = _Camera()

    def resize(self, width_px, height_px):
        self.resize_calls.append((width_px, height_px))
        self.camera.aspect_ratio = width_px / height_px


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def disconnect(self, callback):
        self.callbacks.remove(callback)


class _Screen:
    def __init__(self):
        self.logicalDotsPerInchChanged = _Signal()


class _Window:
    def __init__(self, screen):
        self.screenChanged = _Signal()
        self._screen = screen

    def screen(self):
        return self._screen


class _Timer:
    def __init__(self):
        self.active = False
        self.starts = 0

    def isActive(self):
        return self.active

    def start(self, _interval):
        self.active = True
        self.starts += 1


class MeshViewRenderSurfaceTests(unittest.TestCase):
    @staticmethod
    def _viewer(logical_size=(640, 480), dpr=1.0, visible=True):
        state = {
            "logical_size": logical_size,
            "dpr": dpr,
            "visible": visible,
        }
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._renderer = _Renderer()
        viewer._render_surface_size = None
        viewer.width = lambda: state["logical_size"][0]
        viewer.height = lambda: state["logical_size"][1]
        viewer.devicePixelRatioF = lambda: state["dpr"]
        viewer.isVisible = lambda: state["visible"]
        return viewer, viewer._renderer, state

    def test_resize_maximize_restore_and_splitter_sizes_update_renderer(self):
        viewer, renderer, state = self._viewer(dpr=1.5)
        for logical_size in ((640, 480), (1600, 900), (900, 700), (731, 700)):
            state["logical_size"] = logical_size
            self.assertTrue(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(
            renderer.resize_calls,
            [(960, 720), (2400, 1350), (1350, 1050), (1097, 1050)],
        )
        self.assertAlmostEqual(renderer.camera.aspect_ratio, 1097 / 1050)

    def test_repeated_resize_does_not_apply_scale_twice(self):
        viewer, renderer, _state = self._viewer((800, 600), dpr=1.5)
        OpenGLViewer._resize_render_surface(viewer)
        OpenGLViewer._resize_render_surface(viewer)
        self.assertEqual(renderer.resize_calls, [(1200, 900)])

    def test_monitor_dpr_change_reallocates_at_new_physical_size(self):
        viewer, renderer, state = self._viewer((800, 600), dpr=1.25)
        OpenGLViewer._resize_render_surface(viewer)
        state["dpr"] = 1.75
        connected_screens = []
        screen = object()
        viewer._connect_surface_screen = connected_screens.append
        viewer._queue_surface_metrics_refresh = lambda: (
            OpenGLViewer._resize_render_surface(viewer)
        )
        OpenGLViewer._on_surface_screen_changed(viewer, screen)
        self.assertEqual(connected_screens, [screen])
        self.assertEqual(renderer.resize_calls, [(1000, 750), (1400, 1050)])

    def test_hidden_or_zero_sized_widget_does_not_resize_renderer(self):
        viewer, renderer, state = self._viewer(visible=False, dpr=2.0)
        self.assertFalse(OpenGLViewer._resize_render_surface(viewer))
        state["visible"] = True
        state["logical_size"] = (0, 480)
        self.assertFalse(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(renderer.resize_calls, [])
        state["logical_size"] = (640, 480)
        self.assertTrue(OpenGLViewer._resize_render_surface(viewer))
        self.assertEqual(renderer.resize_calls, [(1280, 960)])

    def test_surface_notification_subscriptions_are_unique_and_released(self):
        viewer, _renderer, _state = self._viewer()
        screen = _Screen()
        window = _Window(screen)
        top_level = type(
            "TopLevel",
            (),
            {
                "isWindow": lambda _self: True,
                "isVisible": lambda _self: True,
                "windowHandle": lambda _self: window,
            },
        )()
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer.window = lambda: top_level
        OpenGLViewer._connect_surface_notifications(viewer)
        OpenGLViewer._connect_surface_notifications(viewer)
        self.assertEqual(len(window.screenChanged.callbacks), 1)
        self.assertEqual(len(screen.logicalDotsPerInchChanged.callbacks), 1)
        OpenGLViewer._disconnect_surface_notifications(viewer)
        self.assertEqual(window.screenChanged.callbacks, [])
        self.assertEqual(screen.logicalDotsPerInchChanged.callbacks, [])
        self.assertIsNone(viewer._surface_window)
        self.assertIsNone(viewer._surface_screen)

    def test_surface_notifications_move_to_the_new_top_level_window(self):
        viewer, _renderer, _state = self._viewer()
        first_screen = _Screen()
        first_window = _Window(first_screen)
        second_screen = _Screen()
        second_window = _Window(second_screen)
        current = {"window": first_window}
        top_level = type(
            "TopLevel",
            (),
            {
                "isWindow": lambda _self: True,
                "isVisible": lambda _self: True,
                "windowHandle": lambda _self: current["window"],
            },
        )()
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer.window = lambda: top_level
        OpenGLViewer._connect_surface_notifications(viewer)
        current["window"] = second_window
        OpenGLViewer._connect_surface_notifications(viewer)
        self.assertEqual(first_window.screenChanged.callbacks, [])
        self.assertEqual(first_screen.logicalDotsPerInchChanged.callbacks, [])
        self.assertEqual(len(second_window.screenChanged.callbacks), 1)
        self.assertEqual(len(second_screen.logicalDotsPerInchChanged.callbacks), 1)
        self.assertIs(viewer._surface_window, second_window)
        self.assertIs(viewer._surface_screen, second_screen)

    def test_invisible_top_level_does_not_request_native_window_handle(self):
        viewer, _renderer, _state = self._viewer()
        top_level = type(
            "HiddenTopLevel",
            (),
            {
                "isWindow": lambda _self: True,
                "isVisible": lambda _self: False,
                "windowHandle": lambda _self: (_ for _ in ()).throw(
                    AssertionError("native handle requested before show")
                ),
            },
        )()
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer.window = lambda: top_level
        OpenGLViewer._connect_surface_notifications(viewer)
        self.assertIsNone(viewer._surface_window)
        self.assertIsNone(viewer._surface_screen)

    def test_surface_metric_refresh_requests_are_coalesced_and_stop_after_cleanup(self):
        viewer, _renderer, _state = self._viewer()
        viewer._destroyed = False
        viewer._surface_metrics_timer = _Timer()
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        self.assertEqual(viewer._surface_metrics_timer.starts, 1)
        viewer._destroyed = True
        viewer._surface_metrics_timer.active = False
        OpenGLViewer._queue_surface_metrics_refresh(viewer)
        self.assertEqual(viewer._surface_metrics_timer.starts, 1)


class TestMeshViewLifecycle(unittest.TestCase):
    @staticmethod
    def _app():
        return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @staticmethod
    def _page_texture(page_uid="p1", visible=True, plane_z=-0.01):
        return NativePageImagePlaneData(
            page_uid=page_uid,
            pixels_rgba=b"\x01\x02\x03\x04",
            width_px=1,
            height_px=1,
            page_width=10.0,
            page_height=20.0,
            plane_x=-5.0,
            plane_y=10.0,
            plane_z=plane_z,
            opacity=1.0,
            visible=visible,
            flip_u=True,
            flip_v=False,
        )

    def _make_page_plane_viewer(self, textures):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._scene_content_emits = []
        viewer.scene_content_changed = SimpleNamespace(
            emit=lambda: viewer._scene_content_emits.append(True)
        )
        renderer = _mesh_support_FakeMeshRenderer(_mesh_support_FakeMeshScene([]))
        viewer._destroyed = False
        viewer._renderer = renderer
        viewer._ensure_renderer = lambda: True
        viewer._current_bid_ref = BidRef("a.mdb", "bid-1")
        viewer._displayed_scene_page_uids = ("page-1",)
        viewer._loading_bid_ref = None
        viewer._accepted_scene_bid_ref = viewer._current_bid_ref
        viewer._requested_scene_page_uids = ("page-1",)
        viewer._page_floor_elevations = {"page-1": 0.0}
        viewer._latest_scene_generation = 0
        viewer._scene_refresh_pending = False
        viewer._camera_initialized_for_scene = True
        viewer._saved_camera_states = {}
        viewer._right_button_press_pos = None
        viewer._right_button_dragged = False
        viewer._suppress_next_context_menu = False
        viewer._selected_takeoff_uids = []
        viewer._current_plan_texture = self._page_texture("existing")
        viewer._has_visible_plan_texture = True
        viewer._render_suspended = False
        viewer._surface_hidden = False
        viewer._zoom_reference_distance = 77.0
        viewer._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1, 1, 1, 1)
        )
        texture_iter = iter(textures)
        viewer._plan_texture_provider = lambda _scene_pages, _elevations: next(
            texture_iter
        )
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.zoom_changed = SimpleNamespace(emit=lambda _value: None)
        viewer.update = lambda: None
        return viewer, renderer

    @staticmethod
    def _scene_identity(bid_ref, generation, page_uids=("page-1",)):
        return MeshSceneIdentity(bid_ref, tuple(page_uids), generation)

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

    def test_mesh_buffer_length_mismatch_raises_clear_error(self):
        valid = {
            "vertices_list": [[0.0, 0.0, 0.0]],
            "normals_list": [[0.0, 0.0, 1.0]],
            "indices_list": [[0, 1, 2]],
            "colors": [{"color": "#ffffff", "opacity": 1.0}],
            "condition_uids": ["condition-1"],
            "takeoff_uids": ["takeoff-1"],
        }
        OpenGLViewer._validate_mesh_buffer_lengths(**valid)
        OpenGLViewer._validate_mesh_buffer_lengths(
            **{**valid, "condition_uids": None, "takeoff_uids": None}
        )
        for name in (
            "normals_list",
            "indices_list",
            "colors",
            "condition_uids",
            "takeoff_uids",
        ):
            with self.subTest(buffer=name):
                short_name = {
                    "normals_list": "normals",
                    "indices_list": "indices",
                }.get(name, name)
                with self.assertRaisesRegex(
                    ValueError,
                    rf"matching lengths: vertices=1, {short_name}=0",
                ):
                    OpenGLViewer._validate_mesh_buffer_lengths(**{**valid, name: []})

    def test_cleanup_clears_external_callback_references(self):
        self._app()
        viewer = OpenGLViewer(None, SimpleNamespace())
        retained = object()
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
        viewer.cleanup()
        self.assertIsNone(viewer._current_bid_ref)
        self.assertIsNone(viewer._selected_context_state_fn)
        self.assertIsNone(viewer._context_menu_command_trigger)
        self.assertIsNone(viewer._context_menu_action_state)
        self.assertIsNone(viewer._zoom_cursor)
        self.assertIsNone(viewer._surface_metrics_timer)
        self.assertFalse(viewer._negative_check_fn(["uid"]))
        self.assertEqual((False, False), viewer._curved_check_fn(["uid"]))
        self.assertEqual({}, viewer._context_menu_conditions_fn())
        self.assertTrue(viewer._destroyed)
        self.assertIsNone(viewer._animation_timer)
        self.assertIsNone(viewer._plan_texture_provider)
        self.assertEqual(viewer._saved_camera_states, {})
        self.assertFalse(viewer._pending_camera_reset)
        with patch(
            "ost_visualizer.presentation.components.mesh_view.ost_renderer.Renderer"
        ) as renderer_class:
            self.assertFalse(viewer._ensure_renderer())
        renderer_class.assert_not_called()
        viewer.cleanup()

    def test_mesh_context_command_rejects_replaced_scene_generation(self):
        self._app()
        viewer = OpenGLViewer(None, SimpleNamespace())
        viewer._current_bid_ref = BidRef("a.mdb", "bid-1")
        viewer._displayed_scene_page_uids = ("page-1",)
        viewer._latest_scene_generation = 1
        triggered = []
        viewer._context_menu_command_trigger = triggered.append
        viewer._context_menu_action_state = lambda _key: {"enabled": True}
        menu = QtWidgets.QMenu()
        viewer._add_context_command(menu, "Delete", "delete")
        menu.actions()[0].trigger()
        self.assertEqual(triggered, ["delete"])
        viewer._latest_scene_generation = 2
        menu.actions()[0].trigger()
        self.assertEqual(triggered, ["delete"])
        viewer.cleanup()

    def test_mesh_context_action_rejects_edit_access_loss(self):
        app = self._app()
        for revoke_access in (False, True):
            with self.subTest(revoke_access=revoke_access):
                viewer = OpenGLViewer(None, SimpleNamespace())
                viewer._pick_enabled = True
                viewer._selected_takeoff_uids = ["takeoff-1"]
                viewer._selected_context_state_fn = lambda _uids: SimpleNamespace(
                    takeoff_uids=["takeoff-1"],
                    show_assign=True,
                    show_negative=False,
                    show_curved=False,
                    all_negative=False,
                    all_curved=False,
                    reassign_geometry_type=None,
                )
                access = {"enabled": True}
                viewer._context_menu_action_state = lambda _key: dict(access)
                emitted = []
                viewer.assign_to_area_requested.connect(
                    lambda uids: emitted.append(list(uids))
                )
                menu_base = QtWidgets.QMenu

                class RevokingMenu(menu_base):
                    def exec(self, _pos):
                        if revoke_access:
                            access["enabled"] = False
                        return next(
                            action
                            for action in self.actions()
                            if action.text() == "Assign to Current Area"
                        )

                event = SimpleNamespace(
                    globalPos=lambda: QtCore.QPoint(),
                    accept=lambda: None,
                )
                with patch(
                    "ost_visualizer.presentation.components.mesh_view.QtWidgets.QMenu",
                    RevokingMenu,
                ):
                    viewer.contextMenuEvent(event)
                app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
                app.processEvents()
                self.assertEqual(emitted, [] if revoke_access else [["takeoff-1"]])
                viewer.cleanup()

    def test_mesh_context_action_rejects_scene_replaced_while_menu_is_open(self):
        app = self._app()
        viewer = OpenGLViewer(None, SimpleNamespace())
        viewer._pick_enabled = True
        viewer._current_bid_ref = BidRef("a.mdb", "bid-1")
        viewer._latest_scene_generation = 1
        viewer._selected_takeoff_uids = ["takeoff-1"]
        viewer._selected_context_state_fn = lambda _uids: SimpleNamespace(
            takeoff_uids=["takeoff-1"],
            show_assign=True,
            show_negative=False,
            show_curved=False,
            all_negative=False,
            all_curved=False,
            reassign_geometry_type=None,
        )
        viewer._context_menu_action_state = lambda _key: {"enabled": True}
        emitted = []
        viewer.assign_to_area_requested.connect(lambda uids: emitted.append(list(uids)))
        menu_base = QtWidgets.QMenu

        class ReplacingMenu(menu_base):
            def exec(self, _pos):
                viewer._latest_scene_generation = 2
                return next(
                    action
                    for action in self.actions()
                    if action.text() == "Assign to Current Area"
                )

        event = SimpleNamespace(
            globalPos=lambda: QtCore.QPoint(),
            accept=lambda: None,
        )
        with patch(
            "ost_visualizer.presentation.components.mesh_view.QtWidgets.QMenu",
            ReplacingMenu,
        ):
            viewer.contextMenuEvent(event)
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()
        self.assertEqual(emitted, [])
        viewer.cleanup()

    def test_cleanup_releases_viewer_ownership_when_renderer_shutdown_fails(self):
        self._app()
        viewer = OpenGLViewer(None, SimpleNamespace())
        renderer = SimpleNamespace(
            shutdown=lambda: (_ for _ in ()).throw(RuntimeError("shutdown failed"))
        )
        viewer._renderer = renderer
        with self.assertLogs(
            "ost_visualizer.presentation.components.mesh_view", level="ERROR"
        ) as logs:
            viewer.cleanup()
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to shut down ost_renderer during cleanup",
        )
        self.assertTrue(viewer._destroyed)
        self.assertIsNone(viewer._renderer)
        self.assertIsNone(viewer._animation_timer)
        self.assertIsNone(viewer._surface_metrics_timer)

    def test_failed_renderer_initialization_releases_partial_renderer(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._destroyed = False
        viewer._renderer = None
        viewer._render_surface_size = (640, 480)
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
            renderer = _mesh_support_FailingInitializationRenderer(window_handle)
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
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].shutdown_calls, 1)

    def test_renderer_constructor_failure_leaves_viewer_without_renderer(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._destroyed = False
        viewer._renderer = None
        viewer._render_surface_size = None
        viewer._surface_window = None
        viewer._surface_screen = None
        viewer._pending_camera_reset = True
        viewer.winId = lambda: 123
        with patch(
            "ost_visualizer.presentation.components.mesh_view.ost_renderer.Renderer",
            side_effect=RuntimeError("device lost"),
        ), self.assertLogs(
            "ost_visualizer.presentation.components.mesh_view", level="ERROR"
        ):
            self.assertFalse(OpenGLViewer._ensure_renderer(viewer))
        self.assertIsNone(viewer._renderer)
        self.assertTrue(viewer._pending_camera_reset)

    def test_scene_rebuild_drops_missing_selected_takeoffs_without_broadcasting(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = _mesh_support_FakeMeshScene(["other", "keep", "tail"])
        viewer._renderer = type("Renderer", (), {"scene": scene})()
        viewer._selected_takeoff_uids = ["keep", "deleted"]
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        OpenGLViewer._reconcile_selected_takeoffs_with_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["keep"])
        self.assertEqual(scene.selected, {1})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_scene_rebuild_reapplies_valid_cached_selection(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = _mesh_support_FakeMeshScene(["stale", "keep-a", "other", "keep-b"])
        scene.set_selected(0, True)
        viewer._renderer = type("Renderer", (), {"scene": scene})()
        viewer._selected_takeoff_uids = ["keep-a", "keep-b"]
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        OpenGLViewer._reconcile_selected_takeoffs_with_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["keep-a", "keep-b"])
        self.assertEqual(scene.selected, {1, 3})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_programmatic_clear_scene_does_not_broadcast_empty_mesh_selection(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer.scene_content_changed = SimpleNamespace(emit=lambda: None)
        viewer._destroyed = False
        scene = _mesh_support_FakeMeshScene(["selected"])
        renderer = _mesh_support_FakeMeshRenderer(scene)
        viewer._renderer = renderer
        viewer._selected_takeoff_uids = ["selected"]
        viewer._current_bid_ref = object()
        viewer._loading_bid_ref = None
        viewer._camera_initialized_for_scene = True
        viewer._saved_camera_states = {}
        viewer._right_button_press_pos = None
        viewer._right_button_dragged = False
        viewer._suppress_next_context_menu = False
        viewer._pending_camera_reset = False
        viewer._render_suspended = False
        viewer._zoom_reference_distance = 3.0
        viewer._click_pos = QtCore.QPointF(1.0, 2.0)
        viewer._last_mouse_pos = QtCore.QPointF(1.0, 2.0)
        viewer._dragged = True
        viewer._camera_moving = True
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.update = lambda: None
        OpenGLViewer.clear_scene(viewer)
        self.assertIsNone(viewer._click_pos)
        self.assertIsNone(viewer._last_mouse_pos)
        self.assertFalse(viewer._dragged)
        self.assertFalse(viewer._camera_moving)
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertEqual(viewer.mesh_clicked.emitted, [])
        self.assertEqual(renderer.camera.reset_calls, 1)
        self.assertEqual(renderer.suspend_calls, 1)
        self.assertTrue(scene.empty())
        self.assertEqual(scene.scene_clear_calls, 1)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertIsNone(viewer._current_bid_ref)
        self.assertEqual(viewer._zoom_reference_distance, 0.0)
        self.assertTrue(viewer._render_suspended)

    def test_same_bid_scene_update_preserves_camera_without_fit_or_reset(self):
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("p2")])
        before = self._camera_state(viewer, renderer)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(BidRef("a.mdb", "bid-1"), 1),
            {"page-1": 0.0},
        )
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)
        self.assertEqual(len(renderer.plan_texture_calls), 1)
        self.assertEqual(viewer._scene_content_emits, [True])

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
        self.assertEqual(viewer._scene_content_emits, [True, True])
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_active_page_texture_refresh_reuses_authoritative_page_elevations(self):
        viewer, renderer = self._make_page_plane_viewer([])
        bid_ref = BidRef("a.mdb", "bid-1")
        requested_elevations = []
        renderer.scene.bounds = SimpleNamespace(
            min=SimpleNamespace(x=-100.0, y=-100.0, z=-100.0),
            max=SimpleNamespace(x=100.0, y=100.0, z=100.0),
        )

        def build_texture(_scene_pages, elevations):
            requested_elevations.append(dict(elevations))
            return self._page_texture(
                "page-a",
                plane_z=elevations["page-a"] - 0.01,
            )

        viewer._plan_texture_provider = build_texture
        OpenGLViewer.prepare_scene_refresh(
            viewer,
            bid_ref,
            ["page-a", "page-b"],
        )
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 1, ("page-a", "page-b")),
            {"page-a": 10.0, "page-b": 20.0},
        )
        camera_state = self._camera_state(viewer, renderer)
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(
            requested_elevations,
            [
                {"page-a": 10.0, "page-b": 20.0},
                {"page-a": 10.0, "page-b": 20.0},
            ],
        )
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(
            [call[7] for call in renderer.plan_texture_calls],
            [9.99, 9.99],
        )
        self.assertEqual(renderer.scene.get_bounds_calls, 0)

    def test_missing_page_texture_update_clears_without_camera_reset(self):
        viewer, renderer = self._make_page_plane_viewer([None])
        before = self._camera_state(viewer, renderer)
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertIsNone(viewer._current_plan_texture)
        self.assertFalse(viewer._has_visible_plan_texture)
        self.assertTrue(viewer._render_suspended)
        self.assertEqual(viewer._scene_content_emits, [True])
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_initial_page_plane_creation_still_frames_camera(self):
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("p1")])
        viewer._current_bid_ref = None
        viewer._current_plan_texture = None
        viewer._has_visible_plan_texture = False
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(BidRef("a.mdb", "bid-1"), 2),
            {"page-1": 0.0},
        )
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(renderer.camera.reset_calls, 0)
        self.assertTrue(viewer._camera_initialized_for_scene)
        self.assertEqual(renderer.suspend_calls, 1)
        self.assertEqual(renderer.resume_calls, 1)
        self.assertFalse(viewer._render_suspended)
        self.assertEqual(viewer._scene_content_emits, [True])

    def test_bid_load_hides_scene_and_defers_plan_until_authoritative_elevation(self):
        old_ref = BidRef("a.mdb", "bid-old")
        new_ref = BidRef("a.mdb", "bid-new")
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._current_bid_ref = old_ref
        requested_elevations = []

        def build_texture(scene_pages, page_elevations):
            requested_elevations.append((tuple(scene_pages), dict(page_elevations)))
            return self._page_texture("p-new")

        viewer._plan_texture_provider = build_texture
        renderer.scene.takeoff_uids = ["old-takeoff"]
        renderer.scene.condition_uids = ["old-condition"]
        OpenGLViewer.begin_scene_load(viewer, new_ref)
        self.assertTrue(renderer.scene.empty())
        self.assertEqual(renderer.scene.scene_clear_calls, 1)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertIsNone(viewer._current_plan_texture)
        self.assertFalse(viewer._has_visible_plan_texture)
        self.assertEqual(viewer._displayed_scene_page_uids, ())
        self.assertEqual(viewer._page_floor_elevations, {})
        self.assertEqual(viewer._scene_content_emits, [True])
        OpenGLViewer.prepare_scene_refresh(viewer, new_ref, ["page-new"])
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(requested_elevations, [])
        self.assertEqual(viewer._scene_content_emits, [True])
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertTrue(viewer._render_suspended)
        self.assertEqual(renderer.clear_frame_calls, 1)
        self.assertEqual(renderer.resume_calls, 0)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(new_ref, 7, ("page-new",)),
            {"page-new": 10.0},
        )
        self.assertEqual(
            requested_elevations,
            [(("page-new",), {"page-new": 10.0})],
        )
        self.assertFalse(viewer._scene_refresh_pending)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(renderer.resume_calls, 1)
        self.assertEqual(viewer._scene_content_emits, [True, True])

    def test_stale_bid_mesh_result_cannot_reveal_or_move_loading_scene(self):
        viewer, renderer = self._make_page_plane_viewer([])
        stale_ref = BidRef("a.mdb", "bid-stale")
        active_ref = BidRef("a.mdb", "bid-active")
        previous_ref = viewer._current_bid_ref
        OpenGLViewer.begin_scene_load(viewer, active_ref)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(stale_ref, 4, ()),
            {},
            ["condition-stale"],
            ["takeoff-stale"],
        )
        self.assertEqual(viewer._loading_bid_ref, active_ref)
        self.assertEqual(viewer._current_bid_ref, previous_ref)
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertTrue(renderer.scene.empty())
        self.assertEqual(viewer._latest_scene_generation, 0)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.resume_calls, 0)

    def test_switching_bids_during_mesh_load_accepts_only_latest_bid(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-new")
        )
        first_ref = BidRef("a.mdb", "bid-first")
        second_ref = BidRef("a.mdb", "bid-second")
        OpenGLViewer.begin_scene_load(viewer, first_ref)
        OpenGLViewer.begin_scene_load(viewer, second_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, second_ref, ["page-new"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(first_ref, 8, ("page-new",)),
            {"page-new": 5.0},
        )
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertNotEqual(viewer._current_bid_ref, first_ref)
        self.assertEqual(viewer._latest_scene_generation, 0)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(second_ref, 9, ("page-new",)),
            {"page-new": 5.0},
        )
        self.assertEqual(viewer._current_bid_ref, second_ref)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)

    def test_saved_bid_camera_is_restored_while_new_bid_is_initially_framed(self):
        first_ref = BidRef("a.mdb", "bid-first")
        second_ref = BidRef("a.mdb", "bid-second")
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-current")
        )
        viewer._current_bid_ref = first_ref
        saved_state = self._camera_state(viewer, renderer)[:7]
        OpenGLViewer.begin_scene_load(viewer, second_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, second_ref, ["page-current"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(second_ref, 10, ("page-current",)),
            {"page-current": 6.0},
        )
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        OpenGLViewer.begin_scene_load(viewer, first_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, first_ref, ["page-current"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(first_ref, 11, ("page-current",)),
            {"page-current": 6.0},
        )
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(self._camera_state(viewer, renderer)[:7], saved_state)
        self.assertEqual(len(renderer.camera.restore_state_calls), 1)

    def test_empty_mesh_bid_does_not_invent_an_origin_elevation_page_plane(self):
        viewer, renderer = self._make_page_plane_viewer([])
        provider_calls = []
        viewer._plan_texture_provider = lambda _scene_pages, elevations: (
            provider_calls.append(dict(elevations))
            or (self._page_texture("p-empty") if elevations else None)
        )
        new_ref = BidRef("a.mdb", "empty-bid")
        OpenGLViewer.begin_scene_load(viewer, new_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, new_ref, ["page-empty"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(new_ref, 12, ("page-empty",)),
            {},
        )
        self.assertEqual(provider_calls, [{}])
        self.assertEqual(renderer.plan_texture_calls, [])
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 1)
        self.assertFalse(viewer._camera_initialized_for_scene)
        self.assertTrue(viewer._render_suspended)

    def test_bid_with_no_mesh_or_plan_remains_suspended_without_camera_fit(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._plan_texture_provider = lambda _scene_pages, _elevations: None
        new_ref = BidRef("a.mdb", "contentless-bid")
        OpenGLViewer.begin_scene_load(viewer, new_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, new_ref, ["page-empty"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(new_ref, 13, ("page-empty",)),
            {},
        )
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(renderer.camera.reset_calls, 1)
        self.assertFalse(viewer._camera_initialized_for_scene)
        self.assertEqual(renderer.resume_calls, 0)
        self.assertTrue(viewer._render_suspended)

    def test_failed_initial_scene_stays_hidden_until_retry_frames_final_scene(self):
        viewer, renderer = self._make_page_plane_viewer([])
        requested_elevations = []
        viewer._plan_texture_provider = lambda _scene_pages, elevations: (
            requested_elevations.append(dict(elevations))
            or self._page_texture("page-a")
        )
        previous_ref = viewer._current_bid_ref
        bid_ref = BidRef("a.mdb", "bid-failure")
        OpenGLViewer.begin_scene_load(viewer, bid_ref)
        saved_previous_camera = viewer._saved_camera_states[previous_ref]
        renderer.camera.position.x = 999.0
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-a"])
        OpenGLViewer.apply_scene_failure(
            viewer,
            self._scene_identity(bid_ref, 14, ("page-a",)),
        )
        self.assertEqual(requested_elevations, [])
        self.assertEqual(renderer.plan_texture_calls, [])
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertTrue(viewer._render_suspended)
        self.assertFalse(viewer._camera_initialized_for_scene)
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertEqual(
            viewer._saved_camera_states[previous_ref], saved_previous_camera
        )
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(requested_elevations, [])
        self.assertEqual(renderer.plan_texture_calls, [])
        self.assertEqual(renderer.camera.show_object_calls, [])
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-a"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 15, ("page-a",)),
            {"page-a": 10.0},
        )
        self.assertEqual(requested_elevations, [{"page-a": 10.0}])
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(renderer.resume_calls, 1)

    def test_failed_same_bid_refresh_keeps_last_accepted_scene_visible(self):
        viewer, renderer = self._make_page_plane_viewer([])
        authoritative_texture = viewer._current_plan_texture
        viewer._plan_texture_provider = lambda _pages, _floors: authoritative_texture
        renderer.scene.takeoff_uids = ["takeoff-existing"]
        renderer.scene.condition_uids = ["condition-existing"]
        bid_ref = viewer._current_bid_ref
        camera_state = self._camera_state(viewer, renderer)
        texture = viewer._current_plan_texture
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer.apply_scene_failure(
            viewer,
            self._scene_identity(bid_ref, 14, ("page-1",)),
        )
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-existing"])
        self.assertEqual(renderer.scene.scene_clear_calls, 0)
        self.assertEqual(renderer.clear_plan_texture_calls, 0)
        self.assertIs(viewer._current_plan_texture, texture)
        self.assertEqual(viewer._page_floor_elevations, {"page-1": 0.0})
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertFalse(viewer._render_suspended)
        self.assertFalse(viewer._scene_refresh_pending)
        self.assertEqual(viewer._scene_content_emits, [True])

    def test_failed_different_page_refresh_does_not_retain_stale_page_scene(self):
        viewer, renderer = self._make_page_plane_viewer([])
        renderer.scene.takeoff_uids = ["takeoff-existing"]
        renderer.scene.condition_uids = ["condition-existing"]
        bid_ref = viewer._current_bid_ref
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-2"])
        OpenGLViewer.apply_scene_failure(
            viewer,
            self._scene_identity(bid_ref, 14, ("page-2",)),
        )
        self.assertEqual(renderer.scene.takeoff_uids, [])
        self.assertEqual(renderer.scene.scene_clear_calls, 1)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertTrue(viewer._render_suspended)
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertEqual(viewer._displayed_scene_page_uids, ())
        self.assertEqual(viewer._page_floor_elevations, {})
        self.assertEqual(viewer._scene_content_emits, [True])

    def test_failed_same_page_refresh_without_renderable_content_stays_pending(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._current_plan_texture = None
        viewer._has_visible_plan_texture = False
        bid_ref = viewer._current_bid_ref
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer.apply_scene_failure(
            viewer, self._scene_identity(bid_ref, 14, ("page-1",))
        )
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertEqual(renderer.scene.scene_clear_calls, 1)
        self.assertEqual(renderer.clear_plan_texture_calls, 1)
        self.assertTrue(viewer._render_suspended)
        self.assertEqual(viewer._displayed_scene_page_uids, ())

    def test_failed_scene_for_new_bid_drops_previous_selection_and_camera_state(self):
        viewer, renderer = self._make_page_plane_viewer([])
        new_ref = BidRef("a.mdb", "bid-new")
        viewer._selected_takeoff_uids = ["takeoff-old"]
        OpenGLViewer.prepare_scene_refresh(viewer, new_ref, ["page-new"])
        OpenGLViewer.apply_scene_failure(
            viewer, self._scene_identity(new_ref, 9, ("page-new",))
        )
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertFalse(viewer._camera_initialized_for_scene)
        self.assertEqual(viewer._current_bid_ref, new_ref)
        self.assertEqual(viewer._latest_scene_generation, 9)
        self.assertTrue(viewer._scene_refresh_pending)

    def test_duplicate_scene_generation_is_not_published_to_renderer_twice(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-final")
        )
        bid_ref = BidRef("a.mdb", "bid-1")
        OpenGLViewer.begin_scene_load(viewer, bid_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-final"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 20, ("page-final",)),
            {"page-final": 2.0},
        )
        first_counts = (
            len(renderer.plan_texture_calls),
            len(renderer.camera.show_object_calls),
            renderer.resume_calls,
        )
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 20, ("page-final",)),
            {"page-final": 999.0},
        )
        self.assertEqual(viewer._page_floor_elevations, {"page-final": 2.0})
        self.assertEqual(
            (
                len(renderer.plan_texture_calls),
                len(renderer.camera.show_object_calls),
                renderer.resume_calls,
            ),
            first_counts,
        )

    def test_late_other_bid_result_after_final_scene_cannot_move_camera(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-final")
        )
        active_ref = BidRef("a.mdb", "active")
        stale_ref = BidRef("a.mdb", "stale")
        OpenGLViewer.begin_scene_load(viewer, active_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, active_ref, ["page-final"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(active_ref, 30, ("page-final",)),
            {"page-final": 2.0},
        )
        camera_state = self._camera_state(viewer, renderer)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(stale_ref, 31, ("page-final",)),
            {"page-final": 999.0},
        )
        self.assertEqual(viewer._current_bid_ref, active_ref)
        self.assertEqual(viewer._page_floor_elevations, {"page-final": 2.0})
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)

    def test_terminal_clear_rejects_a_previously_unseen_queued_scene(self):
        viewer, renderer = self._make_page_plane_viewer([])
        bid_ref = BidRef("a.mdb", "bid-1")
        OpenGLViewer.begin_scene_load(viewer, bid_ref)
        OpenGLViewer.clear_scene(viewer)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(bid_ref, 99, ()),
            {},
        )
        self.assertTrue(renderer.scene.empty())
        self.assertIsNone(viewer._current_bid_ref)
        self.assertIsNone(viewer._accepted_scene_bid_ref)
        self.assertIsNone(viewer._requested_scene_page_uids)
        self.assertEqual(viewer._latest_scene_generation, 0)
        self.assertFalse(viewer._camera_initialized_for_scene)

    def test_scene_clear_is_ignored_after_viewer_cleanup(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._destroyed = True
        camera_state = self._camera_state(viewer, renderer)
        OpenGLViewer.clear_scene(viewer)
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertEqual(renderer.suspend_calls, 0)
        self.assertEqual(renderer.clear_plan_texture_calls, 0)

    def test_queued_animation_callback_is_ignored_after_viewer_cleanup(self):
        class UntouchableRenderer:
            @property
            def camera(self):
                raise AssertionError("destroyed viewer must not touch the renderer")

        timer = _Timer()
        timer.stop = lambda: self.fail("destroyed viewer must not touch the timer")
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._destroyed = True
        viewer._renderer = UntouchableRenderer()
        viewer._animation_timer = timer
        viewer.update = lambda: self.fail("destroyed viewer must not repaint")
        OpenGLViewer._on_animation_frame(viewer)

    def test_animation_frame_repaints_only_while_camera_is_moving_or_coasting(self):
        class Camera:
            def __init__(self):
                self.velocity = False

            def has_velocity(self):
                return self.velocity

        class Timer:
            def __init__(self):
                self.stop_calls = 0

            def stop(self):
                self.stop_calls += 1

        camera = Camera()
        updates = []
        timer = Timer()
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._destroyed = False
        viewer._renderer = SimpleNamespace(camera=camera)
        viewer._animation_timer = timer
        viewer._camera_moving = False
        viewer.update = lambda: updates.append(True)
        OpenGLViewer._on_animation_frame(viewer)
        self.assertEqual((timer.stop_calls, len(updates)), (1, 0))
        viewer._camera_moving = True
        OpenGLViewer._on_animation_frame(viewer)
        self.assertEqual((timer.stop_calls, len(updates)), (1, 1))
        viewer._camera_moving = False
        camera.velocity = True
        OpenGLViewer._on_animation_frame(viewer)
        self.assertEqual((timer.stop_calls, len(updates)), (1, 2))
        viewer._renderer = None
        OpenGLViewer._on_animation_frame(viewer)
        self.assertEqual((timer.stop_calls, len(updates)), (2, 2))

    def test_terminally_rejected_scene_does_not_initialize_renderer(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._accepted_scene_bid_ref = None
        viewer._requested_scene_page_uids = None
        viewer._latest_scene_generation = 0
        renderer_initializations = []
        viewer._ensure_renderer = lambda: renderer_initializations.append(True) or True
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(BidRef("a.mdb", "bid-1"), 100, ("page-a",)),
            {"page-a": 0.0},
        )
        self.assertEqual(renderer_initializations, [])

    def test_mesh_conversion_failure_does_not_claim_scene_generation(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([None])
        renderer.scene.takeoff_uids = ["old-takeoff"]
        renderer.scene.condition_uids = ["old-condition"]
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-new"])
        viewer._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (_ for _ in ()).throw(
                ValueError("invalid color")
            )
        )
        with self.assertRaisesRegex(ValueError, "invalid color"):
            OpenGLViewer._do_apply_mesh_data(
                viewer,
                [[0.0, 0.0, 0.0]],
                [[0.0, 0.0, 1.0]],
                [[0]],
                ["bad"],
                self._scene_identity(bid_ref, 70, ("page-new",)),
                {"page-new": 0.0},
                ["condition-new"],
                ["takeoff-new"],
            )
        self.assertEqual(viewer._latest_scene_generation, 0)
        self.assertTrue(viewer._scene_refresh_pending)
        self.assertEqual(renderer.scene.takeoff_uids, ["old-takeoff"])
        viewer._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1.0, 1.0, 1.0, 1.0)
        )
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(bid_ref, 71, ("page-new",)),
            {"page-new": 0.0},
            ["condition-new"],
            ["takeoff-new"],
        )
        self.assertEqual(viewer._latest_scene_generation, 71)
        self.assertFalse(viewer._scene_refresh_pending)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-new"])

    def test_scene_apply_clears_selection_for_new_bid_and_reconciles_for_same_bid(
        self,
    ):
        for new_bid in (True, False):
            with self.subTest(new_bid=new_bid):
                viewer, renderer = self._make_page_plane_viewer([None])
                viewer._selected_takeoff_uids = ["t1", "gone"]
                bid_ref = BidRef("a.mdb", "bid-new" if new_bid else "bid-1")
                OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
                OpenGLViewer._do_apply_mesh_data(
                    viewer,
                    [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                    [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
                    [[0], [0]],
                    ["#ffffff", "#ffffff"],
                    self._scene_identity(bid_ref, 5),
                    {"page-1": 0.0},
                    ["c0", "c1"],
                    ["t0", "t1"],
                )
                if new_bid:
                    self.assertEqual(viewer.get_selected_takeoff_uids(), [])
                    self.assertEqual(renderer.scene.selected, set())
                else:
                    self.assertEqual(viewer.get_selected_takeoff_uids(), ["t1"])
                    self.assertEqual(renderer.scene.selected, {1})
                self.assertEqual(renderer.scene.takeoff_uids, ["t0", "t1"])
                self.assertEqual(renderer.scene.condition_uids, ["c0", "c1"])
                self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_empty_geometry_entries_are_skipped_and_uids_stay_aligned(self):
        viewer, renderer = self._make_page_plane_viewer([None])
        bid_ref = BidRef("a.mdb", "bid-1")
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
            [[], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
            [[], [0], []],
            ["#ffffff", "#ffffff", "#ffffff"],
            self._scene_identity(bid_ref, 5),
            {"page-1": 0.0},
            ["c0", "c1", "c2"],
            ["t0", "t1", "t2"],
        )
        self.assertEqual(renderer.scene.takeoff_uids, ["t1"])
        self.assertEqual(renderer.scene.condition_uids, ["c1"])

    def test_scene_elevations_must_belong_to_request_and_be_finite(self):
        for elevations, message in (
            ({"other-page": 1.0}, "belong to the scene request"),
            ({"page-1": float("nan")}, "must be finite"),
            ({"page-1": float("inf")}, "must be finite"),
        ):
            with self.subTest(elevations=elevations):
                viewer, renderer = self._make_page_plane_viewer([None])
                renderer.scene.takeoff_uids = ["old-takeoff"]
                bid_ref = BidRef("a.mdb", "bid-1")
                OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
                with self.assertRaisesRegex(ValueError, message):
                    OpenGLViewer._do_apply_mesh_data(
                        viewer,
                        [],
                        [],
                        [],
                        [],
                        self._scene_identity(bid_ref, 5),
                        elevations,
                    )
                self.assertEqual(viewer._latest_scene_generation, 0)
                self.assertTrue(viewer._scene_refresh_pending)
                self.assertEqual(viewer._page_floor_elevations, {"page-1": 0.0})
                self.assertEqual(renderer.scene.takeoff_uids, ["old-takeoff"])

    def test_scene_load_does_not_save_uninitialized_or_invalid_camera_state(self):
        valid = ((10.0, 20.0, 30.0), (1.0, 2.0, 3.0), 37.0)
        for label, initialized, position, target, fov in (
            ("uninitialized", False, *valid),
            ("nan position", True, (float("nan"), 0.0, 1.0), valid[1], valid[2]),
            ("zero distance", True, valid[1], valid[1], valid[2]),
            ("fov too small", True, valid[0], valid[1], 1.0),
            ("fov too large", True, valid[0], valid[1], 179.0),
            ("valid", True, *valid),
        ):
            with self.subTest(label):
                viewer, renderer = self._make_page_plane_viewer([])
                viewer._camera_initialized_for_scene = initialized
                camera = renderer.camera
                camera.position = SimpleNamespace(
                    x=position[0], y=position[1], z=position[2]
                )
                camera.target = SimpleNamespace(x=target[0], y=target[1], z=target[2])
                camera.fov = fov
                previous_ref = viewer._current_bid_ref
                OpenGLViewer.begin_scene_load(viewer, BidRef("a.mdb", "bid-next"))
                if label == "valid":
                    self.assertEqual(
                        viewer._saved_camera_states,
                        {previous_ref: (*position, *target, fov)},
                    )
                else:
                    self.assertEqual(viewer._saved_camera_states, {})

    def test_show_event_resumes_renderer_only_for_accepted_renderable_scene(self):
        class RenderingRenderer(_mesh_support_FakeMeshRenderer):
            def __init__(self, scene):
                super().__init__(scene)
                self.render_calls = 0

            def render(self):
                self.render_calls += 1

        self._app()
        for label, pending, has_content, resumes in (
            ("pending refresh", True, True, False),
            ("no content", False, False, False),
            ("accepted scene", False, True, True),
        ):
            with self.subTest(label):
                viewer = OpenGLViewer(None, SimpleNamespace())
                renderer = RenderingRenderer(
                    _mesh_support_FakeMeshScene(["takeoff-1"] if has_content else [])
                )
                viewer._renderer = renderer
                viewer._scene_refresh_pending = pending
                viewer._render_suspended = True
                viewer._surface_hidden = True
                OpenGLViewer.showEvent(viewer, QtGui.QShowEvent())
                self.assertFalse(viewer._surface_hidden)
                self.assertEqual(viewer._render_suspended, not resumes)
                self.assertEqual(renderer.resume_calls, 1 if resumes else 0)
                self.assertEqual(renderer.render_calls, 1 if resumes else 0)
                self.assertEqual(renderer.suspend_calls, 0 if resumes else 1)
                viewer._renderer = None
                viewer.cleanup()

    def test_camera_cache_can_evict_one_bid_or_one_database(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        first = BidRef("C:/Projects/A.mdb", "bid-1")
        second = BidRef("c:\\projects\\a.mdb", "bid-2")
        other = BidRef("C:/Projects/B.mdb", "bid-1")
        state = (1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 45.0)
        viewer._saved_camera_states = {first: state, second: state, other: state}
        OpenGLViewer.discard_saved_camera_states(viewer, bid_ref=first)
        self.assertEqual(set(viewer._saved_camera_states), {second, other})
        OpenGLViewer.discard_saved_camera_states(
            viewer, file_path="C:\\PROJECTS\\A.mdb"
        )
        self.assertEqual(set(viewer._saved_camera_states), {other})

    def test_camera_cache_eviction_rejects_ambiguous_scope_and_ignores_empty_scope(
        self,
    ):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        first = BidRef("A.mdb", "bid-1")
        state = (1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 45.0)
        viewer._saved_camera_states = {first: state}
        with self.assertRaisesRegex(ValueError, "either bid_ref or file_path"):
            OpenGLViewer.discard_saved_camera_states(
                viewer, bid_ref=first, file_path="A.mdb"
            )
        OpenGLViewer.discard_saved_camera_states(viewer)
        OpenGLViewer.discard_saved_camera_states(viewer, file_path="")
        OpenGLViewer.discard_saved_camera_states(
            viewer, bid_ref=BidRef("A.mdb", "missing")
        )
        self.assertEqual(viewer._saved_camera_states, {first: state})

    def test_page_recheck_after_empty_selection_accepts_current_bid_scene(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer(
            [self._page_texture("page-a"), self._page_texture("page-a")]
        )
        OpenGLViewer.begin_scene_load(viewer, bid_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-a"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 40, ("page-a",)),
            {"page-a": 0.0},
        )
        camera_state = self._camera_state(viewer, renderer)
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, [])
        OpenGLViewer._do_apply_mesh_data(
            viewer, [], [], [], [], self._scene_identity(bid_ref, 41, ()), {}
        )
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-a"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 42, ("page-a",)),
            {"page-a": 0.0},
        )
        self.assertEqual(viewer._current_bid_ref, bid_ref)
        self.assertFalse(viewer._render_suspended)
        self.assertEqual(len(renderer.plan_texture_calls), 2)
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)

    def test_obsolete_page_scene_is_rejected_without_moving_camera(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer(
            [self._page_texture("page-a"), self._page_texture("page-b")]
        )
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-a"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 50, ("page-a",)),
            {"page-a": 10.0},
        )
        camera_state = self._camera_state(viewer, renderer)
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-b"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 51, ("page-a",)),
            {"page-a": 999.0},
        )
        self.assertEqual(viewer._page_floor_elevations, {"page-a": 10.0})
        self.assertEqual(len(renderer.plan_texture_calls), 1)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 52, ("page-b",)),
            {"page-b": 20.0},
        )
        self.assertEqual(len(renderer.plan_texture_calls), 2)
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)

    def test_page_meshes_reappear_after_uncheck_switch_and_recheck(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([None, None, None])

        def publish(page_uid, takeoff_uid, generation):
            page_uids = [page_uid] if page_uid else []
            OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, page_uids)
            has_mesh = bool(takeoff_uid)
            OpenGLViewer._do_apply_mesh_data(
                viewer,
                [[0.0, 0.0, 0.0]] if has_mesh else [],
                [[0.0, 0.0, 1.0]] if has_mesh else [],
                [[0]] if has_mesh else [],
                ["#ffffff"] if has_mesh else [],
                self._scene_identity(bid_ref, generation, page_uids),
                {page_uid: float(generation)} if has_mesh else {},
                ["condition-1"] if has_mesh else [],
                [takeoff_uid] if has_mesh else [],
            )

        OpenGLViewer.begin_scene_load(viewer, bid_ref)
        publish("page-a", "takeoff-a", 60)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-a"])
        camera_state = self._camera_state(viewer, renderer)
        self.assertFalse(viewer._render_suspended)
        suspend_calls = renderer.suspend_calls
        publish("", "", 61)
        self.assertTrue(renderer.scene.empty())
        self.assertTrue(viewer._render_suspended)
        self.assertEqual(renderer.suspend_calls, suspend_calls + 1)
        publish("page-b", "takeoff-b", 62)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-b"])
        publish("", "", 63)
        publish("page-a", "takeoff-a", 64)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-a"])
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertEqual(renderer.camera.reset_calls, 0)

    def test_two_3d_surfaces_keep_independent_saved_cameras(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        other_ref = BidRef("a.mdb", "bid-2")
        main_viewer, main_renderer = self._make_page_plane_viewer([])
        detached_viewer, detached_renderer = self._make_page_plane_viewer([])
        main_viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-main")
        )
        detached_viewer._plan_texture_provider = (
            lambda _scene_pages, _elevations: self._page_texture("p-detached")
        )
        main_renderer.camera.position.x = 101.0
        detached_renderer.camera.position.x = 202.0
        OpenGLViewer.begin_scene_load(main_viewer, other_ref)
        OpenGLViewer.begin_scene_load(detached_viewer, other_ref)
        OpenGLViewer.prepare_scene_refresh(main_viewer, other_ref, ["page-other"])
        OpenGLViewer.prepare_scene_refresh(detached_viewer, other_ref, ["page-other"])
        OpenGLViewer._do_apply_mesh_data(
            main_viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(other_ref, 13, ("page-other",)),
            {"page-other": 0.0},
        )
        OpenGLViewer._do_apply_mesh_data(
            detached_viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(other_ref, 13, ("page-other",)),
            {"page-other": 0.0},
        )
        OpenGLViewer.begin_scene_load(main_viewer, bid_ref)
        OpenGLViewer.begin_scene_load(detached_viewer, bid_ref)
        OpenGLViewer.prepare_scene_refresh(main_viewer, bid_ref, ["page-current"])
        OpenGLViewer.prepare_scene_refresh(detached_viewer, bid_ref, ["page-current"])
        OpenGLViewer._do_apply_mesh_data(
            main_viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 14, ("page-current",)),
            {"page-current": 0.0},
        )
        OpenGLViewer._do_apply_mesh_data(
            detached_viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 14, ("page-current",)),
            {"page-current": 0.0},
        )
        self.assertEqual(main_renderer.camera.position.x, 101.0)
        self.assertEqual(detached_renderer.camera.position.x, 202.0)

    def test_explicit_reset_view_still_fits_current_content(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._get_camera_distance = lambda: 123.0
        zoom_changes = []
        viewer.zoom_changed = SimpleNamespace(emit=zoom_changes.append)
        OpenGLViewer.reset_view(viewer)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(viewer._zoom_reference_distance, 123.0)
        self.assertEqual(zoom_changes, [1.0])

    def test_reset_view_without_renderable_content_leaves_camera_untouched(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._has_visible_plan_texture = False
        viewer._get_camera_distance = lambda: self.fail("no content to measure")
        zoom_changes = []
        viewer.zoom_changed = SimpleNamespace(emit=zoom_changes.append)
        before = self._camera_state(viewer, renderer)
        OpenGLViewer.reset_view(viewer)
        self.assertEqual(renderer.camera.show_object_calls, [])
        self.assertEqual(self._camera_state(viewer, renderer), before)
        self.assertEqual(zoom_changes, [])
        viewer._renderer = None
        OpenGLViewer.reset_view(viewer)
        self.assertEqual(zoom_changes, [])

    def test_user_mesh_pick_broadcasts_selected_takeoff(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = _mesh_support_FakeMeshScene(["selected"])
        viewer._renderer = _mesh_support_FakePickingMeshRenderer(scene, 0)
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer._pending_mutation_uids = set()
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.width = lambda: 100
        viewer.height = lambda: 100
        viewer.devicePixelRatioF = lambda: 1.0
        viewer.update = lambda: None
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(10, 20), additive=False)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["selected"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [["selected"]])

    def test_user_mesh_pick_uses_current_fractional_device_pixel_ratio(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        renderer = _mesh_support_FakePickingMeshRenderer(
            _mesh_support_FakeMeshScene(["selected"]), 0
        )
        viewer._renderer = renderer
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer._pending_mutation_uids = set()
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.width = lambda: 801
        viewer.height = lambda: 603
        viewer.devicePixelRatioF = lambda: 1.25
        viewer.update = lambda: None
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(13, 17), additive=False)
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(14, 19), additive=False)
        self.assertEqual(renderer.pick_calls, [(16, 21), (17, 23)])

    def _pick_viewer(self, takeoff_uids, pick_index, selected=()):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = _mesh_support_FakeMeshScene(takeoff_uids)
        for uid in selected:
            scene.set_selected(takeoff_uids.index(uid), True)
        renderer = _mesh_support_FakePickingMeshRenderer(scene, pick_index)
        viewer._renderer = renderer
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = list(selected)
        viewer._pending_mutation_uids = set()
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.width = lambda: 100
        viewer.height = lambda: 100
        viewer.devicePixelRatioF = lambda: 1.0
        viewer.update = lambda: None
        return viewer, scene, renderer

    def test_pick_on_empty_space_clears_selection_unless_additive(self):
        for pick_index in (-1, 5):
            with self.subTest(pick_index=pick_index, additive=False):
                viewer, scene, _renderer = self._pick_viewer(
                    ["a", "b"], pick_index, selected=["a"]
                )
                OpenGLViewer._handle_pick(viewer, QtCore.QPoint(1, 1), additive=False)
                self.assertEqual(viewer.get_selected_takeoff_uids(), [])
                self.assertEqual(scene.selected, set())
                self.assertEqual(viewer.mesh_clicked.emitted, [[]])
        viewer, scene, _renderer = self._pick_viewer(["a", "b"], -1, selected=["a"])
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(1, 1), additive=True)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["a"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_additive_pick_toggles_an_already_selected_takeoff_off(self):
        viewer, scene, _renderer = self._pick_viewer(["a", "b"], 1, selected=["a", "b"])
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(1, 1), additive=True)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["a"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [["a"]])

    def test_pick_ignores_disabled_picking_and_takeoffs_with_pending_mutations(self):
        viewer, scene, renderer = self._pick_viewer(["a", "b"], 1, selected=["a"])
        viewer._pick_enabled = False
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(1, 1), additive=False)
        self.assertEqual(renderer.pick_calls, [])
        viewer._pick_enabled = True
        viewer._pending_mutation_uids = {"b"}
        OpenGLViewer._handle_pick(viewer, QtCore.QPoint(1, 1), additive=False)
        self.assertEqual(renderer.pick_calls, [(1, 1)])
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["a"])
        self.assertEqual(scene.selected, {0})
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_mesh_shift_release_adds_to_existing_selection(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = _mesh_support_FakeMeshScene(["existing", "selected"])
        scene.set_selected(0, True)
        viewer._renderer = _mesh_support_FakePickingMeshRenderer(scene, 1)
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = ["existing"]
        viewer._pending_mutation_uids = set()
        viewer.mesh_clicked = _mesh_support_FakeMeshSignal()
        viewer.width = lambda: 100
        viewer.height = lambda: 100
        viewer.devicePixelRatioF = lambda: 1.0
        viewer.update = lambda: None
        viewer._cursor_mode = CURSOR_MODE_DEFAULT
        viewer._click_pos = QtCore.QPointF(1.0, 2.0)
        viewer._dragged = False
        viewer._last_mouse_pos = None
        viewer._camera_moving = False
        event = SimpleNamespace(
            button=lambda: QtCore.Qt.MouseButton.LeftButton,
            position=lambda: QtCore.QPointF(1.0, 2.0),
            modifiers=lambda: QtCore.Qt.KeyboardModifier.ShiftModifier,
            accept=lambda: None,
        )
        OpenGLViewer.mouseReleaseEvent(viewer, event)
        self.assertEqual(viewer.get_selected_takeoff_uids(), ["existing", "selected"])
        self.assertEqual(scene.selected, {0, 1})
        self.assertEqual(viewer.mesh_clicked.emitted, [["existing", "selected"]])

    def test_mouse_release_after_a_drag_does_not_pick(self):
        viewer, scene, renderer = self._pick_viewer(["a"], 0)
        viewer._cursor_mode = CURSOR_MODE_DEFAULT
        viewer._click_pos = QtCore.QPointF(1.0, 2.0)
        viewer._dragged = True
        viewer._last_mouse_pos = QtCore.QPointF(9.0, 9.0)
        viewer._camera_moving = True
        event = SimpleNamespace(
            button=lambda: QtCore.Qt.MouseButton.LeftButton,
            position=lambda: QtCore.QPointF(9.0, 9.0),
            modifiers=lambda: QtCore.Qt.KeyboardModifier.NoModifier,
            accept=lambda: None,
        )
        OpenGLViewer.mouseReleaseEvent(viewer, event)
        self.assertEqual(renderer.pick_calls, [])
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertEqual(scene.selected, set())
        self.assertEqual(viewer.mesh_clicked.emitted, [])
        self.assertIsNone(viewer._click_pos)
        self.assertFalse(viewer._camera_moving)

    def test_scene_load_cancels_pointer_interaction_started_on_previous_scene(self):
        viewer, _renderer = self._make_page_plane_viewer([])
        viewer._click_pos = QtCore.QPointF(1.0, 2.0)
        viewer._last_mouse_pos = QtCore.QPointF(1.0, 2.0)
        viewer._dragged = True
        viewer._camera_moving = True
        viewer._right_button_press_pos = QtCore.QPointF(3.0, 4.0)
        OpenGLViewer.begin_scene_load(viewer, BidRef("a.mdb", "bid-2"))
        self.assertIsNone(viewer._click_pos)
        self.assertIsNone(viewer._last_mouse_pos)
        self.assertFalse(viewer._dragged)
        self.assertFalse(viewer._camera_moving)
        self.assertIsNone(viewer._right_button_press_pos)
        self.assertTrue(viewer._suppress_next_context_menu)

    def test_scene_replacement_cancels_click_started_on_previous_geometry(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        renderer.pick = lambda _x, _y: 0
        viewer._pick_enabled = True
        viewer._pending_mutation_uids = set()
        viewer._cursor_mode = CURSOR_MODE_DEFAULT
        viewer.width = lambda: 100
        viewer.height = lambda: 100
        viewer.devicePixelRatioF = lambda: 1.0
        viewer._click_pos = QtCore.QPointF(10.0, 20.0)
        viewer._last_mouse_pos = QtCore.QPointF(10.0, 20.0)
        viewer._dragged = False
        viewer._camera_moving = True
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
            ["condition-new"],
            ["takeoff-new"],
        )
        event = SimpleNamespace(
            button=lambda: QtCore.Qt.MouseButton.LeftButton,
            position=lambda: QtCore.QPointF(10.0, 20.0),
            modifiers=lambda: QtCore.Qt.KeyboardModifier.NoModifier,
            accept=lambda: None,
        )
        OpenGLViewer.mouseReleaseEvent(viewer, event)
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertEqual(viewer.mesh_clicked.emitted, [])

    def test_scene_replacement_cancels_camera_drag_from_previous_geometry(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        viewer._cursor_mode = CURSOR_MODE_DEFAULT
        viewer._last_mouse_pos = QtCore.QPointF(10.0, 20.0)
        viewer._click_pos = QtCore.QPointF(10.0, 20.0)
        viewer._dragged = True
        viewer._camera_moving = True
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
            ["condition-new"],
            ["takeoff-new"],
        )
        event = SimpleNamespace(
            position=lambda: QtCore.QPointF(30.0, 40.0),
            buttons=lambda: QtCore.Qt.MouseButton.LeftButton,
            accept=lambda: None,
            ignore=lambda: None,
        )
        OpenGLViewer.mouseMoveEvent(viewer, event)
        self.assertEqual(renderer.camera.rotate_calls, [])
        self.assertEqual(renderer.camera.pan_calls, [])

    def test_scene_replacement_stops_native_camera_inertia_without_moving_pose(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        renderer.camera = ost_renderer.Camera()
        renderer.camera.rotate(100.0, -50.0)
        self.assertTrue(renderer.camera.has_velocity())
        before = self._camera_state(viewer, renderer)[:7]
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
        )
        self.assertFalse(renderer.camera.has_velocity())
        self.assertEqual(self._camera_state(viewer, renderer)[:7], before)

    def test_hidden_view_stays_suspended_when_pending_scene_completes(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        viewer._render_suspended = True
        viewer._surface_hidden = True
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
        )
        self.assertEqual(renderer.resume_calls, 0)
        self.assertTrue(viewer._render_suspended)

    def test_resume_rendering_requires_visible_surface_and_renderable_content(self):
        viewer, renderer = self._make_page_plane_viewer([])
        viewer._render_suspended = True
        viewer._surface_hidden = True
        OpenGLViewer.resume_rendering(viewer)
        self.assertEqual(renderer.resume_calls, 0)
        self.assertTrue(viewer._render_suspended)
        viewer._surface_hidden = False
        viewer._has_visible_plan_texture = False
        OpenGLViewer.resume_rendering(viewer)
        self.assertEqual(renderer.resume_calls, 0)
        self.assertTrue(viewer._render_suspended)
        viewer._has_visible_plan_texture = True
        OpenGLViewer.resume_rendering(viewer)
        self.assertEqual(renderer.resume_calls, 1)
        self.assertFalse(viewer._render_suspended)

    def test_hidden_view_stays_suspended_when_same_scene_refresh_fails(self):
        viewer, renderer = self._make_page_plane_viewer([])
        authoritative_texture = viewer._current_plan_texture
        viewer._plan_texture_provider = lambda _pages, _floors: authoritative_texture
        renderer.scene.takeoff_uids = ["takeoff-existing"]
        renderer.scene.condition_uids = ["condition-existing"]
        bid_ref = viewer._current_bid_ref
        viewer._render_suspended = True
        viewer._surface_hidden = True
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer.apply_scene_failure(
            viewer,
            self._scene_identity(bid_ref, 15, ("page-1",)),
        )
        self.assertEqual(renderer.resume_calls, 0)
        self.assertTrue(viewer._render_suspended)
        self.assertFalse(viewer._scene_refresh_pending)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-existing"])

    def test_begin_scene_load_stops_native_camera_inertia_while_suspended(self):
        viewer, renderer = self._make_page_plane_viewer([])
        renderer.camera = ost_renderer.Camera()
        renderer.camera.rotate(100.0, -50.0)
        self.assertTrue(renderer.camera.has_velocity())
        before = self._camera_state(viewer, renderer)[:7]
        OpenGLViewer.begin_scene_load(viewer, BidRef("a.mdb", "bid-2"))
        self.assertFalse(renderer.camera.has_velocity())
        self.assertEqual(self._camera_state(viewer, renderer)[:7], before)

    def test_hiding_view_stops_native_camera_inertia_without_moving_pose(self):
        self._app()
        viewer = OpenGLViewer(None, _mesh_support_FakeColorService())
        renderer = _mesh_support_FakeMeshRenderer(_mesh_support_FakeMeshScene([]))
        renderer.camera = ost_renderer.Camera()
        viewer._renderer = renderer
        renderer.camera.rotate(100.0, -50.0)
        self.assertTrue(renderer.camera.has_velocity())
        before = self._camera_state(viewer, renderer)[:7]
        OpenGLViewer.hideEvent(viewer, QtGui.QHideEvent())
        self.assertFalse(renderer.camera.has_velocity())
        self.assertEqual(self._camera_state(viewer, renderer)[:7], before)
        self.assertEqual(renderer.suspend_calls, 1)
        self.assertTrue(viewer._surface_hidden)
        self.assertTrue(viewer._render_suspended)
        viewer._renderer = None
        viewer.cleanup()

    def test_scene_camera_notifications_distinguish_fit_from_preserved_pose(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, _renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        emitted = []
        viewer.zoom_changed = SimpleNamespace(emit=emitted.append)
        viewer._camera_initialized_for_scene = False
        OpenGLViewer._initialize_camera_for_current_scene(viewer)
        self.assertEqual(emitted, [1.0])
        emitted.clear()
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
        )
        self.assertEqual(emitted, [])

    def test_scene_replacement_suppresses_context_menu_from_previous_geometry(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        viewer, _renderer = self._make_page_plane_viewer([self._page_texture("page-1")])
        viewer._right_button_press_pos = QtCore.QPointF(10.0, 20.0)
        viewer._right_button_dragged = False
        viewer._suppress_next_context_menu = False
        OpenGLViewer.prepare_scene_refresh(viewer, bid_ref, ["page-1"])
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [[0.0, 0.0, 0.0]],
            [[0.0, 0.0, 1.0]],
            [[0]],
            ["#ffffff"],
            self._scene_identity(bid_ref, 1),
            {"page-1": 0.0},
            ["condition-new"],
            ["takeoff-new"],
        )
        accepted = []
        event = SimpleNamespace(accept=lambda: accepted.append(True))
        with patch(
            "ost_visualizer.presentation.components.mesh_view.QtWidgets.QMenu",
            side_effect=AssertionError("stale context menu must not open"),
        ):
            OpenGLViewer.contextMenuEvent(viewer, event)
        self.assertEqual(accepted, [True])
        self.assertFalse(viewer._suppress_next_context_menu)

    def test_orbit_keeps_fractional_qt_delta_in_logical_coordinates(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        renderer = _mesh_support_FakeMeshRenderer(_mesh_support_FakeMeshScene([]))
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

    def test_drag_buttons_map_to_rotate_or_pan_by_cursor_mode(self):
        left = QtCore.Qt.MouseButton.LeftButton
        right = QtCore.Qt.MouseButton.RightButton
        for cursor_mode, button, expected in (
            (CURSOR_MODE_DEFAULT, left, "rotate"),
            (CURSOR_MODE_DEFAULT, right, "pan"),
            (CURSOR_MODE_PAN, left, "pan"),
            (CURSOR_MODE_PAN, right, "rotate"),
        ):
            with self.subTest(cursor_mode=cursor_mode, button=button):
                viewer = OpenGLViewer.__new__(OpenGLViewer)
                renderer = _mesh_support_FakeMeshRenderer(
                    _mesh_support_FakeMeshScene([])
                )
                viewer._renderer = renderer
                viewer._cursor_mode = cursor_mode
                viewer._last_mouse_pos = QtCore.QPointF(10.0, 20.0)
                viewer._click_pos = None
                viewer._right_button_press_pos = None
                viewer.update = lambda: None
                event = SimpleNamespace(
                    position=lambda: QtCore.QPointF(14.0, 23.0),
                    buttons=lambda button=button: button,
                    accept=lambda: None,
                    ignore=lambda: None,
                )
                OpenGLViewer.mouseMoveEvent(viewer, event)
                if expected == "rotate":
                    self.assertEqual(renderer.camera.rotate_calls, [(4.0, 3.0)])
                    self.assertEqual(renderer.camera.pan_calls, [])
                else:
                    self.assertEqual(renderer.camera.pan_calls, [(4.0, 3.0)])
                    self.assertEqual(renderer.camera.rotate_calls, [])
                self.assertEqual(viewer._last_mouse_pos, QtCore.QPointF(14.0, 23.0))


class MeshViewNativeSurfaceOwnerTests(unittest.TestCase):
    def test_native_surface_notifications_use_real_top_level_without_qt_warning(self):
        messages = []

        def handler(_message_type, _context, message):
            messages.append(message)

        app = _app()
        host = QtWidgets.QMainWindow()
        container = QtWidgets.QWidget(host)
        viewer = OpenGLViewer(container, SimpleNamespace())
        viewer.hide()
        host.setCentralWidget(container)
        previous = QtCore.qInstallMessageHandler(handler)
        try:
            host.show()
            app.processEvents()
            viewer._connect_surface_notifications()
            self.assertIs(viewer._surface_window, host.windowHandle())
        finally:
            QtCore.qInstallMessageHandler(previous)
            viewer.cleanup()
            host.close()
            app.processEvents()
        self.assertFalse(
            any("QWidgetWindow must be a top level window" in msg for msg in messages)
        )


class MeshViewNativeWindowTests(unittest.TestCase):
    def test_opengl_viewer_keeps_production_stack_and_splitter_ancestors_alien(self):
        app = _app()
        window = QtWidgets.QMainWindow()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        viewer_container = QtWidgets.QWidget(splitter)
        container_layout = QtWidgets.QVBoxLayout(viewer_container)
        view_stack = QtWidgets.QStackedWidget(viewer_container)
        viewer_frame = QtWidgets.QFrame(view_stack)
        viewer_layout = QtWidgets.QVBoxLayout(viewer_frame)
        viewer = OpenGLViewer(
            viewer_frame,
            SimpleNamespace(get_rgb=lambda _color: (0, 0, 0)),
        )
        viewer_layout.addWidget(viewer)
        view_stack.addWidget(viewer_frame)
        container_layout.addWidget(view_stack)
        splitter.addWidget(viewer_container)
        window.setCentralWidget(splitter)
        try:
            with patch.object(OpenGLViewer, "_ensure_renderer", return_value=False):
                window.show()
                app.processEvents()
            self.assertTrue(
                viewer.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
            )
            self.assertIsNotNone(window.windowHandle())
            self.assertIsNotNone(viewer.windowHandle())
            self.assertIsNot(viewer.windowHandle(), window.windowHandle())
            self.assertIsNone(viewer_frame.windowHandle())
            self.assertIsNone(view_stack.windowHandle())
            self.assertIsNone(viewer_container.windowHandle())
            self.assertIsNone(splitter.windowHandle())
        finally:
            viewer.cleanup()
            window.close()
            app.processEvents()

    def test_opengl_context_menu_uses_a_real_top_level_window_owner(self):
        app = _app()
        window = QtWidgets.QMainWindow()
        host = QtWidgets.QWidget(window)
        layout = QtWidgets.QVBoxLayout(host)
        viewer = OpenGLViewer(
            host,
            SimpleNamespace(get_rgb=lambda _color: (0, 0, 0)),
        )
        layout.addWidget(viewer)
        window.setCentralWidget(host)
        created_menus = []

        class TrackedMenu(QtWidgets.QMenu):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_menus.append(self)

            def exec(self, *args, **kwargs):
                return None

        try:
            with patch.object(OpenGLViewer, "_ensure_renderer", return_value=False):
                window.show()
                app.processEvents()
            with patch.object(QtWidgets, "QMenu", TrackedMenu):
                local_pos = QtCore.QPoint(2, 2)
                event = QtGui.QContextMenuEvent(
                    QtGui.QContextMenuEvent.Reason.Mouse,
                    local_pos,
                    viewer.mapToGlobal(local_pos),
                )
                viewer.contextMenuEvent(event)
            app.processEvents()
        finally:
            viewer.cleanup()
            window.close()
            app.processEvents()
        self.assertGreaterEqual(len(created_menus), 1)
        self.assertIs(created_menus[0].parent(), window)
        self.assertTrue(created_menus[0].parentWidget().isWindow())
