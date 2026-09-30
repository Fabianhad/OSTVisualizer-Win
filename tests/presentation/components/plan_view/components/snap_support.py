import math
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.config import Config
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem

SCREEN_PX_PER_OST = 8.0


class FakeSnapIndex:
    instances = []
    query_result = None

    def __init__(self):
        self.build_calls = []
        self.query_calls = []
        FakeSnapIndex.instances.append(self)

    def build(self, segments):
        self.build_calls.append(list(segments))

    def query(self, x, y, radius):
        self.query_calls.append((x, y, radius))
        return FakeSnapIndex.query_result

    def size(self):
        return len(self.build_calls[-1]) if self.build_calls else 0


class FakePDFRenderer:
    open_calls = 0
    open_paths = []
    extract_calls = 0
    page_info_calls = 0
    open_ok = True
    raw_segments = [(1.0, 2.0, 3.0, 4.0)]
    page_width = 200.0
    page_height = 100.0
    media_width = 200.0
    media_height = 100.0
    crop_width = 0.0
    crop_height = 0.0
    intrinsic_rotation = 0

    def open(self, path):
        FakePDFRenderer.open_calls += 1
        FakePDFRenderer.open_paths.append(path)
        return FakePDFRenderer.open_ok

    def extract_path_segments(self, _page_index):
        FakePDFRenderer.extract_calls += 1
        return list(FakePDFRenderer.raw_segments)

    def page_info(self, _page_index):
        FakePDFRenderer.page_info_calls += 1
        return SimpleNamespace(
            effective_width_pts=FakePDFRenderer.page_width,
            effective_height_pts=FakePDFRenderer.page_height,
            media_width_pts=FakePDFRenderer.media_width,
            media_height_pts=FakePDFRenderer.media_height,
            crop_width_pts=FakePDFRenderer.crop_width,
            crop_height_pts=FakePDFRenderer.crop_height,
            intrinsic_rotation=FakePDFRenderer.intrinsic_rotation,
        )

    def close(self):
        pass


from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components import placement_mode


class FakeCoordinateSystem:
    scale_ratio = 144.0
    view_scale = 1.0
    page_info = {"view_scale": 1.0}

    def transform_vertices_to_2d(self, vertices):
        return list(vertices)

    def ost_to_pdf_points(self, value):
        return value


class FakeSceneBuilder:
    def get_coordinate_system(self):
        return FakeCoordinateSystem()


class PlacementHarness(placement_mode.PlacementModeMixin):
    def __init__(self):
        self._current_page = Page(
            uid="page-1",
            name="Page 1",
            image_path="drawing.pdf",
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            page_index=0,
        )
        self._current_bid_page_uid = self._current_page.uid
        self._load_geometry_ready = True
        self._pdf_height_pts = 100.0
        self._pdf_width_pts = 200.0
        self._scene_builder = FakeSceneBuilder()
        self._current_takeoffs = {}
        self._current_conditions = {
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        self._takeoff_snap_index = None
        self._pdf_snap_index = None
        self._takeoff_snap_index_dirty = True
        self._pdf_snap_index_dirty = True
        self._pdf_snap_segments_cache_key = None
        self._pdf_snap_segments_cache = []
        self._snap_increments = 1.0
        self._mouse_unpressed_snap_angle = 15
        self._mouse_pressed_snap_angle = 0
        self._snap_to_right_angle_enabled = False
        self._snap_to_right_angle_threshold_px = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._snap_to_grid_enabled = True
        self._snap_to_grid_threshold_px = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._snap_to_pdf_lines_enabled = True
        self._snap_to_pdf_lines_threshold_px = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._snap_to_takeoffs_enabled = True
        self._snap_to_takeoffs_threshold_px = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._place_points = []

    def _screen_px_to_ost_radius(self, threshold_px):
        return float(threshold_px) / SCREEN_PX_PER_OST

    def _scene_pos_to_ost(self, point):
        return point

    def _ost_to_scene_pos(self, x, y):
        from PySide6 import QtCore

        return QtCore.QPointF(x, y)

    def mapFromScene(self, point):
        return point

    def snap_ost(self, value):
        return round(float(value))


class FakeScene:
    def addItem(self, _item):
        pass

    def removeItem(self, _item):
        pass


class RecordingScene(FakeScene):
    def __init__(self):
        self.items = []

    def addItem(self, item):
        self.items.append(item)


class PatternPreviewSceneBuilder(FakeSceneBuilder):
    def __init__(self):
        self.pattern_fill_calls = 0
        self.pattern_angles = []

    def build_pattern_fill(
        self,
        path,
        _pattern_type,
        _color,
        _opacity,
        _spacing,
        _lw,
        orientation_angle=None,
    ):
        self.pattern_fill_calls += 1
        self.pattern_angles.append(orientation_angle)
        bounds = path.boundingRect()
        pattern_path = QPainterPath()
        pattern_path.moveTo(bounds.left(), bounds.center().y())
        pattern_path.lineTo(bounds.right(), bounds.center().y())
        return None, [QGraphicsPathItem(pattern_path)]


class FakeColorService:
    def as_hex_with_opacity(self, color_entry):
        return color_entry


class PreviewHarness(PlacementHarness):
    def __init__(self):
        super().__init__()
        self._scene = FakeScene()
        self._place_preview_items = []
        self._place_flashing = False
        self._backout_orig_parent_path = None
        self._backout_parent_uid = None
        self._backout_active_uid = None
        self._place_session_uid = "linear"
        self._place_linear_dragging = False
        self._place_area_rect_dragging = False
        self._backout_last_valid_ost = None
        self._uid_to_items = {}
        self._current_color_map = {
            uid: ("#808080", 1.0) for uid in ("linear", "area", "count")
        }
        self._color_service = FakeColorService()
        self.handle_points = []
        self.pattern_angles = []
        self.snap_result = (10.0, 0.0, 10.0, 0.0, placement_mode.GRID)

    def _placement_snap_from_scene(self, _cursor_scene):
        return self.snap_result

    def _snap_angle_for_placement(
        self, origin_x, origin_y, target_x, target_y, _snap_kind
    ):
        return self._snap_angle(origin_x, origin_y, target_x, target_y)

    def _current_page_transform(self):
        return None

    def _apply_pattern_preview(
        self,
        item,
        _path,
        _condition,
        _qcolor,
        _preview_opacity,
        _page_transform,
        pattern_angle=None,
    ):
        self._place_preview_items.append(item)
        self.pattern_angles.append(pattern_angle)

    def _add_secondary_condition_previews(self, *_args, **_call_options):
        pass

    def _request_place_preview_repaint(self):
        pass

    def _add_place_handle(self, x, y, half=4.0):
        self.handle_points.append((x, y, half))


def _area_preview_harness(
    points: list[tuple[float, float]],
    snap_result: tuple[float, float, float, float, int],
) -> PreviewHarness:
    harness = PreviewHarness()
    harness._scene = RecordingScene()
    harness._current_conditions["area"] = Condition(
        uid="area",
        condition_type=Condition.TYPE_AREA,
        layer_visible=True,
    )
    harness._place_session_uid = "area"
    harness._place_points = points
    harness._snap_to_right_angle_enabled = True
    harness._snap_to_right_angle_threshold_px = 1
    harness.snap_result = snap_result
    return harness


def _indicator_lines(harness: PreviewHarness) -> list[QGraphicsLineItem]:
    return [
        item for item in harness._scene.items if isinstance(item, QGraphicsLineItem)
    ]
