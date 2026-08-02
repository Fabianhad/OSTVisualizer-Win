import unittest
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtCore, QtWidgets
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.page_image_plane_transform import (
    resolve_page_floor_elevations,
)
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer, ost_renderer
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
        self.get_bounds_calls = 0
        self.bounds = SimpleNamespace(
            min=SimpleNamespace(x=0.0, y=0.0, z=0.0),
            max=SimpleNamespace(x=1.0, y=1.0, z=1.0),
        )

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
        self.condition_uids = []
        self.selected.clear()

    def empty(self):
        return not self.takeoff_uids

    def add_mesh(self, mesh):
        self.takeoff_uids.append(mesh.takeoff_uid)
        self.condition_uids.append(mesh.condition_uid)

    def get_bounds(self):
        self.get_bounds_calls += 1
        return self.bounds


class FakeMeshCamera:
    def __init__(self):
        self.reset_calls = 0
        self.show_object_calls = []
        self.position = SimpleNamespace(x=10.0, y=20.0, z=30.0)
        self.target = SimpleNamespace(x=1.0, y=2.0, z=3.0)
        self.fov = 37.0
        self.rotate_calls = []
        self.pan_calls = []
        self.restore_state_calls = []

    def reset(self):
        self.reset_calls += 1

    def show_object(self, bounds):
        self.show_object_calls.append(bounds)
        self.position = SimpleNamespace(x=100.0, y=200.0, z=300.0)
        self.target = SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.fov = 45.0

    def restore_state(self, position, target, fov, bounds):
        self.restore_state_calls.append((position, target, fov, bounds))
        self.position = SimpleNamespace(x=position.x, y=position.y, z=position.z)
        self.target = SimpleNamespace(x=target.x, y=target.y, z=target.z)
        self.fov = fov

    def rotate(self, delta_x, delta_y):
        self.rotate_calls.append((delta_x, delta_y))

    def pan(self, delta_x, delta_y):
        self.pan_calls.append((delta_x, delta_y))


class FakeMeshRenderer:
    def __init__(self, scene):
        self.scene = scene
        self.camera = FakeMeshCamera()
        self.suspend_calls = 0
        self.resume_calls = 0
        self.plan_texture_calls = []
        self.plan_texture_visibility_calls = []
        self.clear_plan_texture_calls = 0
        self.resize_calls = []
        self.clear_frame_calls = 0

    def suspend(self):
        self.suspend_calls += 1

    def resume(self):
        self.resume_calls += 1

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
        renderer = FakeMeshRenderer(FakeMeshScene([]))
        viewer._destroyed = False
        viewer._renderer = renderer
        viewer._ensure_renderer = lambda: True
        viewer._current_bid_ref = BidRef("a.mdb", "bid-1")
        viewer._loading_bid_ref = None
        viewer._accepted_scene_bid_ref = viewer._current_bid_ref
        viewer._requested_scene_page_uids = ("page-1",)
        viewer._page_floor_elevations = {"page-1": 0.0}
        viewer._latest_scene_generation = 0
        viewer._scene_refresh_pending = False
        viewer._camera_initialized_for_scene = True
        viewer._saved_camera_states = {}
        viewer._selected_takeoff_uids = []
        viewer._current_plan_texture = self._page_texture("existing")
        viewer._has_visible_plan_texture = True
        viewer._render_suspended = False
        viewer._zoom_reference_distance = 77.0
        viewer._color_service = SimpleNamespace(
            convert_to_rgba=lambda _color: (1, 1, 1, 1)
        )
        texture_iter = iter(textures)
        viewer._plan_texture_provider = lambda _scene_pages, _elevations: next(
            texture_iter
        )
        viewer.mesh_clicked = FakeMeshSignal()
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

    def test_meshes_to_geometries_returns_typed_mesh_geometry(self):
        geometries = meshes_to_geometries(
            [FakeSourceMesh()],
            {
                "mesh_0": {
                    "color": "#112233",
                    "opacity": 0.5,
                    "condition_uid": "condition-1",
                    "takeoff_uid": "takeoff-1",
                    "page_uid": "page-1",
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
        self.assertEqual("page-1", geometry.page_uid)
        self.assertEqual([0, 1, 2], geometry.indices)

    def test_page_floor_elevations_are_grouped_by_geometry_page_identity(self):
        geometries = [
            MeshGeometry(
                vertices=[0.0, 0.0, 12.0, 1.0, 1.0, 10.0],
                normals=[],
                indices=[],
                color="#ffffff",
                opacity=1.0,
                page_uid="page-a",
                condition_uid="condition-a",
                takeoff_uid="takeoff-a",
            ),
            MeshGeometry(
                vertices=[0.0, 0.0, 25.0, 1.0, 1.0, 20.0],
                normals=[],
                indices=[],
                color="#ffffff",
                opacity=1.0,
                page_uid="page-b",
                condition_uid="condition-b",
                takeoff_uid="takeoff-b",
            ),
        ]
        self.assertEqual(
            resolve_page_floor_elevations(
                (geometry.page_uid, geometry.vertices[2::3]) for geometry in geometries
            ),
            {"page-a": 10.0, "page-b": 20.0},
        )

    def test_scene_identity_constructor_canonicalizes_order_and_duplicates(self):
        bid_ref = BidRef("a.mdb", "bid-1")
        identity = MeshSceneIdentity(
            bid_ref=bid_ref,
            page_uids=("page-b", "page-a", "page-b", ""),
            generation="7",
        )
        self.assertEqual(identity.bid_ref, bid_ref)
        self.assertEqual(identity.page_uids, ("page-a", "page-b"))
        self.assertEqual(identity.generation, 7)

    def test_native_camera_restore_clears_motion_and_sets_saved_pose_atomically(self):
        camera = ost_renderer.Camera()
        camera.rotate(100.0, -50.0)
        self.assertTrue(camera.has_velocity())
        bounds = ost_renderer.Box3()
        bounds.min = ost_renderer.Vec3(-10.0, -20.0, -1.0)
        bounds.max = ost_renderer.Vec3(10.0, 20.0, 5.0)
        camera.restore_state(
            ost_renderer.Vec3(4.0, 5.0, 6.0),
            ost_renderer.Vec3(1.0, 2.0, 3.0),
            38.0,
            bounds,
        )
        self.assertFalse(camera.has_velocity())
        self.assertEqual(
            (camera.position.x, camera.position.y, camera.position.z),
            (4.0, 5.0, 6.0),
        )
        self.assertEqual(
            (camera.target.x, camera.target.y, camera.target.z),
            (1.0, 2.0, 3.0),
        )
        self.assertEqual(camera.fov, 38.0)

    def test_native_mesh_vectors_reject_incomplete_coordinates(self):
        mesh = ost_renderer.MeshData()
        with self.assertRaisesRegex(ValueError, "vertex array length"):
            mesh.set_vertices([0.0, 1.0])
        with self.assertRaisesRegex(ValueError, "normal array length"):
            mesh.set_normals([0.0, 0.0, 1.0, 1.0])

    def test_native_scene_rejects_invalid_indices_before_gl_upload(self):
        mesh = ost_renderer.MeshData()
        mesh.set_vertices(
            [
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
            ]
        )
        scene = ost_renderer.Scene()
        mesh.indices = [0, 1]
        with self.assertRaisesRegex(ValueError, "index array length"):
            scene.add_mesh(mesh)
        mesh.indices = [0, 1, 3]
        with self.assertRaisesRegex(ValueError, "outside the vertex array"):
            scene.add_mesh(mesh)

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

    def test_cleanup_releases_viewer_ownership_when_renderer_shutdown_fails(self):
        self._app()
        viewer = OpenGLViewer(None, SimpleNamespace())
        renderer = SimpleNamespace(
            shutdown=lambda: (_ for _ in ()).throw(RuntimeError("shutdown failed"))
        )
        viewer._renderer = renderer
        with self.assertLogs(
            "ost_visualizer.presentation.components.mesh_view", level="ERROR"
        ):
            viewer.cleanup()
        self.assertTrue(viewer._destroyed)
        self.assertIsNone(viewer._renderer)
        self.assertIsNone(viewer._animation_timer)
        self.assertIsNone(viewer._surface_metrics_timer)

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
        viewer._destroyed = False
        scene = FakeMeshScene(["selected"])
        renderer = FakeMeshRenderer(scene)
        viewer._renderer = renderer
        viewer._selected_takeoff_uids = ["selected"]
        viewer._current_bid_ref = object()
        viewer._loading_bid_ref = None
        viewer._camera_initialized_for_scene = True
        viewer._saved_camera_states = {}
        viewer._pending_camera_reset = False
        viewer._render_suspended = False
        viewer._zoom_reference_distance = 3.0
        viewer.mesh_clicked = FakeMeshSignal()
        viewer.update = lambda: None
        OpenGLViewer.clear_scene(viewer)
        self.assertEqual(viewer.get_selected_takeoff_uids(), [])
        self.assertEqual(viewer.mesh_clicked.emitted, [])
        self.assertEqual(renderer.camera.reset_calls, 1)
        self.assertEqual(renderer.suspend_calls, 1)

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
        OpenGLViewer.begin_scene_load(viewer, new_ref)
        OpenGLViewer.prepare_scene_refresh(viewer, new_ref, ["page-new"])
        OpenGLViewer.update_plan_texture(viewer)
        self.assertEqual(requested_elevations, [])
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

    def test_stale_bid_mesh_result_cannot_reveal_or_move_loading_scene(self):
        viewer, renderer = self._make_page_plane_viewer([])
        stale_ref = BidRef("a.mdb", "bid-stale")
        active_ref = BidRef("a.mdb", "bid-active")
        OpenGLViewer.begin_scene_load(viewer, active_ref)
        OpenGLViewer._do_apply_mesh_data(
            viewer,
            [],
            [],
            [],
            [],
            self._scene_identity(stale_ref, 4, ()),
            {},
        )
        self.assertEqual(viewer._loading_bid_ref, active_ref)
        self.assertTrue(viewer._scene_refresh_pending)
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
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        viewer._destroyed = True
        viewer._renderer = None
        viewer._animation_timer = None
        OpenGLViewer._on_animation_frame(viewer)

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
        publish("", "", 61)
        self.assertTrue(renderer.scene.empty())
        publish("page-b", "takeoff-b", 62)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-b"])
        publish("", "", 63)
        publish("page-a", "takeoff-a", 64)
        self.assertEqual(renderer.scene.takeoff_uids, ["takeoff-a"])
        self.assertEqual(self._camera_state(viewer, renderer), camera_state)
        self.assertEqual(
            len(renderer.camera.show_object_calls)
            + len(renderer.camera.restore_state_calls),
            1,
        )

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
        OpenGLViewer.reset_view(viewer)
        self.assertEqual(len(renderer.camera.show_object_calls), 1)
        self.assertEqual(viewer._zoom_reference_distance, 123.0)

    def test_user_mesh_pick_broadcasts_selected_takeoff(self):
        viewer = OpenGLViewer.__new__(OpenGLViewer)
        scene = FakeMeshScene(["selected"])
        viewer._renderer = FakePickingMeshRenderer(scene, 0)
        viewer._pick_enabled = True
        viewer._selected_takeoff_uids = []
        viewer._pending_mutation_uids = set()
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
        viewer._pending_mutation_uids = set()
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
        cleanup_calls = []
        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=lambda: cleanup_calls.append("timer-stop"),
            timeout=SimpleNamespace(disconnect=lambda _callback: None),
            deleteLater=lambda: cleanup_calls.append("timer-delete"),
        )
        window.viewer = SimpleNamespace(
            blockSignals=lambda _blocked: cleanup_calls.append("viewer-block"),
            cleanup=lambda: cleanup_calls.append("viewer-cleanup"),
        )
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
        self.assertEqual(
            cleanup_calls,
            ["timer-stop", "timer-delete", "viewer-block", "viewer-cleanup"],
        )

    def test_mesh_window_cleanup_continues_after_resource_failures(self):
        window = MeshViewWindow.__new__(MeshViewWindow)
        retained = object()
        cleanup_calls = []

        def fail_timer_stop():
            cleanup_calls.append("timer-stop")
            raise RuntimeError("timer stop failed")

        def fail_viewer_block(_blocked):
            cleanup_calls.append("viewer-block")
            raise RuntimeError("viewer already deleted")

        def fail_viewer_cleanup():
            cleanup_calls.append("viewer-cleanup")
            raise RuntimeError("viewer cleanup failed")

        window._is_closing = False
        window._resize_timer = SimpleNamespace(
            stop=fail_timer_stop,
            timeout=SimpleNamespace(disconnect=lambda _callback: None),
            deleteLater=lambda: cleanup_calls.append("timer-delete"),
        )
        window.viewer = SimpleNamespace(
            blockSignals=fail_viewer_block,
            cleanup=fail_viewer_cleanup,
        )
        window._zoom_combo = retained
        window._context_menu_command_trigger = lambda _key: retained
        window._context_menu_action_state = lambda: retained
        window.icon_provider = retained
        window._color_service = retained
        with self.assertLogs(
            "ost_visualizer.presentation.windows.mesh_view_window",
            level="ERROR",
        ) as captured:
            MeshViewWindow.cleanup(window)
        self.assertIsNone(window._resize_timer)
        self.assertIsNone(window.viewer)
        self.assertIsNone(window._zoom_combo)
        self.assertIsNone(window._context_menu_command_trigger)
        self.assertIsNone(window._context_menu_action_state)
        self.assertIsNone(window.icon_provider)
        self.assertIsNone(window._color_service)
        self.assertEqual(
            cleanup_calls,
            ["timer-stop", "timer-delete", "viewer-block", "viewer-cleanup"],
        )
        self.assertEqual(len(captured.records), 3)


if __name__ == "__main__":
    unittest.main()
