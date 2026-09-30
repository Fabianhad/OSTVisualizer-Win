import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.page_image_plane_transform import (
    resolve_page_floor_elevations,
)
from ost_visualizer.presentation.components.mesh_view import OpenGLViewer, ost_renderer
from ost_visualizer.presentation.managers.shortcut_manager import ShortcutManager
from ost_visualizer.presentation.modes.cursor import CURSOR_MODE_DEFAULT
from ost_visualizer.presentation.visualization.native_page_plane import (
    NativePageImagePlaneData,
)
from ost_visualizer.presentation.visualization.utils.mesh import meshes_to_geometries
from ost_visualizer.presentation.windows.mesh_view_window import MeshViewWindow
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest


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
        self.scene_clear_calls = 0
        self.get_bounds_calls = 0
        self.bounds = ost_renderer.Box3()
        self.bounds.min = ost_renderer.Vec3(0.0, 0.0, 0.0)
        self.bounds.max = ost_renderer.Vec3(1.0, 1.0, 1.0)

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
        self.scene_clear_calls += 1
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

    def has_velocity(self):
        return False


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

    def set_plan_texture(
        self,
        pixels_rgba,
        width_px,
        height_px,
        page_width,
        page_height,
        plane_x,
        plane_y,
        plane_z,
        opacity,
        visible,
        flip_u,
        flip_v,
    ):
        self.plan_texture_calls.append(
            (
                pixels_rgba,
                width_px,
                height_px,
                page_width,
                page_height,
                plane_x,
                plane_y,
                plane_z,
                opacity,
                visible,
                flip_u,
                flip_v,
            )
        )

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
