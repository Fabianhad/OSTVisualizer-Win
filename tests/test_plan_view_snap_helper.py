import importlib
import math
import sys
import types
import unittest
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsPathItem
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.config import Config

SNAP_MODULE_NAME = (
    "ost_visualizer.presentation.components.plan_view.components.snap_index"
)
SCREEN_PX_PER_OST = 8.0
GEOMETRY_MODULE_NAME = (
    "ost_visualizer.presentation.components.plan_view.components.geometry_utils"
)
HANDLE_STYLE_MODULE_NAME = (
    "ost_visualizer.presentation.components.plan_view.components.handle_style"
)
OST_PDF_MODULE_NAME = "ost_visualizer.presentation.visualization.pdf.ost_pdf"
PLACEMENT_MODULE_NAME = (
    "ost_visualizer.presentation.components.plan_view.components.placement_mode"
)
_ORIGINAL_MODULES = {
    name: sys.modules.get(name)
    for name in (
        SNAP_MODULE_NAME,
        GEOMETRY_MODULE_NAME,
        HANDLE_STYLE_MODULE_NAME,
        OST_PDF_MODULE_NAME,
        PLACEMENT_MODULE_NAME,
    )
}


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


def _install_fake_native_modules():
    snap_module = types.ModuleType(SNAP_MODULE_NAME)
    snap_module.NONE = 0
    snap_module.GRID = 1
    snap_module.ENDPOINT = 2
    snap_module.MIDPOINT = 3
    snap_module.PERPENDICULAR = 4
    snap_module.SnapIndex = FakeSnapIndex
    sys.modules[SNAP_MODULE_NAME] = snap_module
    geometry_module = types.ModuleType(GEOMETRY_MODULE_NAME)
    geometry_module.HandleInfo = type("HandleInfo", (), {})
    geometry_module.segments_intersect = lambda *_args: False
    geometry_module.polygon_is_valid = lambda _points: True
    geometry_module.polyline_self_intersects = lambda _points: False
    geometry_module.point_to_segment_distance = lambda *_args: 0.0
    geometry_module.signed_area = lambda _points: 1.0
    geometry_module.resize_cursor_for_edge = lambda *_args: None
    geometry_module.cursor_for_direction = lambda *_args: None
    geometry_module.polygon_centroid = lambda _pos, _n: (0.0, 0.0)
    geometry_module.rotate_position_coords = lambda pos, *_args, **_call_options: list(
        pos
    )
    geometry_module.rotate_points_around = lambda pos, *_args: list(pos)
    sys.modules[GEOMETRY_MODULE_NAME] = geometry_module
    handle_style_module = types.ModuleType(HANDLE_STYLE_MODULE_NAME)

    def handle_colors_for_background(background):
        luminance = (
            0.299 * background.red()
            + 0.587 * background.green()
            + 0.114 * background.blue()
        )
        if luminance < 128.0:
            return QColor(255, 255, 255, 224), QColor(0, 0, 0)
        return QColor(0, 0, 0, 224), QColor(255, 255, 255)

    handle_style_module.handle_colors_for_background = handle_colors_for_background
    handle_style_module.apply_takeoff_handle_style = (
        lambda *_args, **_call_options: None
    )
    sys.modules[HANDLE_STYLE_MODULE_NAME] = handle_style_module
    pdf_module = types.ModuleType(OST_PDF_MODULE_NAME)
    pdf_module.PDFRenderer = FakePDFRenderer
    sys.modules[OST_PDF_MODULE_NAME] = pdf_module
    pdf_package = sys.modules.get("ost_visualizer.presentation.visualization.pdf")
    if pdf_package is not None:
        pdf_package.ost_pdf = pdf_module


_install_fake_native_modules()
sys.modules.pop(PLACEMENT_MODULE_NAME, None)
placement_mode = importlib.import_module(PLACEMENT_MODULE_NAME)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff


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
    def int_to_hex(self, _value):
        return "#808080"


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
        self._current_color_map = {}
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


class SnapSegmentCacheTests(unittest.TestCase):
    def setUp(self):
        FakeSnapIndex.instances.clear()
        FakeSnapIndex.query_result = None
        FakePDFRenderer.open_calls = 0
        FakePDFRenderer.open_paths = []
        FakePDFRenderer.extract_calls = 0
        FakePDFRenderer.page_info_calls = 0
        FakePDFRenderer.open_ok = True
        FakePDFRenderer.raw_segments = [(1.0, 2.0, 3.0, 4.0)]
        FakePDFRenderer.page_width = 200.0
        FakePDFRenderer.page_height = 100.0
        FakePDFRenderer.media_width = 200.0
        FakePDFRenderer.media_height = 100.0
        FakePDFRenderer.crop_width = 0.0
        FakePDFRenderer.crop_height = 0.0
        FakePDFRenderer.intrinsic_rotation = 0

    def test_pdf_segments_are_cached_across_takeoff_rebuilds(self):
        harness = PlacementHarness()
        harness._ensure_pdf_snap_index()
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[10.0, 20.0, 30.0, 40.0],
        )
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        takeoff_snap_index = harness._ensure_takeoff_snap_index()
        self.assertEqual(FakePDFRenderer.extract_calls, 1)
        self.assertEqual(
            takeoff_snap_index.build_calls[-1],
            [
                (
                    9.646446609406727,
                    20.353553390593273,
                    29.646446609406727,
                    40.35355339059328,
                ),
                (
                    10.353553390593273,
                    19.646446609406727,
                    30.353553390593273,
                    39.64644660940672,
                ),
            ],
        )

    def test_linear_takeoff_snap_uses_border_segments_not_centerline(self):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 2.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 1.0, 10.0, 1.0),
                (0.0, -1.0, 10.0, -1.0),
            ],
        )

    def test_area_takeoff_snap_uses_polygon_border_segments(self):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._current_takeoffs["a1"] = Takeoff(
            uid="a1",
            condition_uid="area",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 5.0, 0.0, 5.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 0.0, 10.0, 0.0),
                (10.0, 0.0, 10.0, 5.0),
                (10.0, 5.0, 0.0, 5.0),
                (0.0, 5.0, 0.0, 0.0),
            ],
        )

    def test_count_square_snap_uses_shape_border_segments(self):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["count"] = Condition(
            uid="count",
            condition_type=Condition.TYPE_COUNT,
            layer_visible=True,
            shape=shapes.SQUARE,
            width=4.0,
            depth=4.0,
            display_size=100.0,
        )
        harness._current_takeoffs["c1"] = Takeoff(
            uid="c1",
            condition_uid="count",
            position=[10.0, 20.0],
            rotation=0.0,
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (8.0, 18.0, 12.0, 18.0),
                (12.0, 18.0, 12.0, 22.0),
                (12.0, 22.0, 8.0, 22.0),
                (8.0, 22.0, 8.0, 18.0),
            ],
        )

    def test_count_circle_snap_uses_approximated_border_segments(self):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["count"] = Condition(
            uid="count",
            condition_type=Condition.TYPE_COUNT,
            layer_visible=True,
            shape=shapes.CIRCLE,
            width=4.0,
            depth=4.0,
            display_size=100.0,
        )
        harness._current_takeoffs["c1"] = Takeoff(
            uid="c1",
            condition_uid="count",
            position=[0.0, 0.0],
            rotation=0.0,
        )
        segments = harness._build_takeoff_snap_segments()
        self.assertEqual(len(segments), 32)
        self.assertEqual(segments[0][0], 2.0)
        self.assertEqual(segments[0][1], 0.0)

    def test_linear_takeoff_snap_skips_degenerate_segments(self):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 2.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[5.0, 5.0, 5.0, 5.0],
        )
        self.assertEqual(harness._build_takeoff_snap_segments(), [])

    def test_linear_takeoff_snap_uses_default_border_for_non_positive_thickness(
        self,
    ):
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._current_conditions["linear"].thickness = 0.0
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        self.assertEqual(
            harness._build_takeoff_snap_segments(),
            [
                (0.0, 0.5, 10.0, 0.5),
                (0.0, -0.5, 10.0, -0.5),
            ],
        )

    def test_pdf_extraction_failure_is_cached_for_same_page(self):
        FakePDFRenderer.open_ok = False
        harness = PlacementHarness()
        with self.assertLogs(placement_mode.logger, level="WARNING"):
            harness._ensure_pdf_snap_index()
        harness._invalidate_snap_index()
        harness._ensure_pdf_snap_index()
        self.assertEqual(FakePDFRenderer.open_calls, 1)
        self.assertEqual(FakePDFRenderer.extract_calls, 0)

    def test_pdf_snap_waits_until_page_load_geometry_is_ready(self):
        harness = PlacementHarness()
        harness._load_geometry_ready = False
        self.assertIsNone(harness._query_pdf_line_snap(10.0, 20.0, 8))
        self.assertEqual(FakePDFRenderer.open_calls, 0)
        self.assertTrue(harness._pdf_snap_index_dirty)
        harness._load_geometry_ready = True
        harness._ensure_pdf_snap_index()
        self.assertEqual(FakePDFRenderer.extract_calls, 1)
        self.assertFalse(harness._pdf_snap_index_dirty)

    def test_pdf_snap_waits_for_current_page_uid_to_match_page(self):
        harness = PlacementHarness()
        harness._current_bid_page_uid = "previous-page"
        self.assertIsNone(harness._query_pdf_line_snap(10.0, 20.0, 8))
        self.assertEqual(FakePDFRenderer.open_calls, 0)
        self.assertTrue(harness._pdf_snap_index_dirty)
        harness._current_bid_page_uid = harness._current_page.uid
        harness._ensure_pdf_snap_index()
        self.assertEqual(FakePDFRenderer.extract_calls, 1)
        self.assertFalse(harness._pdf_snap_index_dirty)

    def test_pdf_snap_extraction_uses_shared_pdfium_lock(self):
        class RecordingLock:
            def __init__(self):
                self.entered = 0
                self.exited = 0

            def __enter__(self):
                self.entered += 1

            def __exit__(self, _exc_type, _exc, _tb):
                self.exited += 1

        lock = RecordingLock()
        original_lock = placement_mode.pdfium_lock
        placement_mode.pdfium_lock = lock
        try:
            PlacementHarness()._ensure_pdf_snap_index()
        finally:
            placement_mode.pdfium_lock = original_lock
        self.assertEqual(lock.entered, 2)
        self.assertEqual(lock.exited, 2)

    def test_grid_fallback_still_rounds_when_snap_index_is_empty(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._current_page.image_path = None
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10, 21))
        self.assertEqual(snap_kind, placement_mode.GRID)

    def test_snap_priority_uses_takeoffs_before_pdf_and_grid(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._query_takeoff_snap = lambda *_args: (
            1.0,
            2.0,
            placement_mode.ENDPOINT,
            0,
        )
        harness._query_pdf_line_snap = lambda *_args: self.fail(
            "PDF snap should not run after takeoff hit"
        )
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (1.0, 2.0))
        self.assertEqual(snap_kind, placement_mode.ENDPOINT)

    def test_snap_priority_uses_pdf_before_grid_when_takeoff_misses(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._query_takeoff_snap = lambda *_args: None
        harness._query_pdf_line_snap = lambda *_args: (
            3.0,
            4.0,
            placement_mode.PERPENDICULAR,
            0,
        )
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (3.0, 4.0))
        self.assertEqual(snap_kind, placement_mode.PERPENDICULAR)

    def test_disabling_snap_sources_returns_unsnapped_cursor_position(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_to_grid_enabled = False
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)

    def test_zero_grid_threshold_disables_grid_snap(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        harness._snap_to_pdf_lines_enabled = False
        harness._snap_to_grid_threshold_px = 0
        ost_x, ost_y, _cx, _cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual(snap_kind, placement_mode.NONE)

    def test_takeoff_snap_threshold_is_screen_pixel_based(self):
        from PySide6 import QtCore

        harness = PlacementHarness()
        harness._snap_to_takeoffs_threshold_px = 16
        harness._placement_snap_from_scene(QtCore.QPointF(10.4, 20.6))
        takeoff_snap_index = FakeSnapIndex.instances[0]
        self.assertEqual(takeoff_snap_index.query_calls[-1], (10.4, 20.6, 2.0))

    def test_native_line_hit_returns_exact_hit_without_increment_quantizing(self):
        from PySide6 import QtCore

        FakeSnapIndex.query_result = (10.4, 20.6, placement_mode.PERPENDICULAR, 0)
        harness = PlacementHarness()
        harness._current_page.image_path = None
        harness._snap_to_takeoffs_enabled = False
        ost_x, ost_y, cx, cy, snap_kind = harness._placement_snap_from_scene(
            QtCore.QPointF(10.4, 20.6)
        )
        self.assertEqual((ost_x, ost_y), (10.4, 20.6))
        self.assertEqual((cx, cy), (5.2, 10.3))
        self.assertEqual(snap_kind, placement_mode.PERPENDICULAR)

    def test_angle_snap_distance_increment_applies_only_to_grid_snap(self):
        harness = PlacementHarness()
        grid_x, grid_y = harness._snap_angle_for_placement(
            0.0, 0.0, 10.4, 0.0, placement_mode.GRID
        )
        line_x, line_y = harness._snap_angle_for_placement(
            0.0, 0.0, 10.4, 0.0, placement_mode.PERPENDICULAR
        )
        self.assertEqual((grid_x, grid_y), (10.0, 0.0))
        self.assertEqual((line_x, line_y), (10.4, 0.0))

    def test_default_mouse_snap_angles_are_15_unpressed_and_off_when_pressed(self):
        from PySide6.QtCore import Qt

        harness = PlacementHarness()
        x, y = harness._snap_angle(0.0, 0.0, 10.0, 3.0)
        length = (10.0**2 + 3.0**2) ** 0.5
        self.assertAlmostEqual(x, length * 0.9659258263, places=5)
        self.assertAlmostEqual(y, length * 0.2588190451, places=5)
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            self.assertEqual(
                harness._snap_angle(0.0, 0.0, 10.0, 3.0),
                (10.0, 3.0),
            )
        finally:
            placement_mode.QGuiApplication = original

    def test_zero_mouse_snap_angle_disables_angle_snap(self):
        harness = PlacementHarness()
        harness._mouse_unpressed_snap_angle = 0
        self.assertEqual(harness._snap_angle(0.0, 0.0, 10.0, 3.0), (10.0, 3.0))

    def test_configured_pressed_mouse_snap_angle_uses_shift_state(self):
        from PySide6.QtCore import Qt

        harness = PlacementHarness()
        harness._mouse_pressed_snap_angle = 90
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            x, y = harness._snap_angle(0.0, 0.0, 3.0, 10.0)
        finally:
            placement_mode.QGuiApplication = original
        self.assertAlmostEqual(x, 0.0, places=5)
        self.assertAlmostEqual(y, (3.0**2 + 10.0**2) ** 0.5, places=5)

    def test_right_angle_target_uses_first_point_axis_when_snap_enabled(self):
        harness = PlacementHarness()
        harness._snap_to_right_angle_enabled = True
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertTrue(active)
        self.assertEqual((x, y), (10.0, 20.0))

    def test_right_angle_snap_threshold_controls_target_distance(self):
        harness = PlacementHarness()
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 0
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (10.5, 20.0))

    def test_right_angle_target_disabled_when_snap_is_off(self):
        harness = PlacementHarness()
        harness._place_points = [(10.0, 10.0)]
        x, y, active = harness._right_angle_target_from_first_point(10.5, 20.0)
        self.assertFalse(active)
        self.assertEqual((x, y), (10.5, 20.0))

    def test_right_angle_snap_disabled_uses_area_angle_snap(self):
        from PySide6 import QtCore

        harness = PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = False
        harness.snap_result = (10.5, 20.0, 10.5, 20.0, placement_mode.NONE)
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        expected = harness._snap_angle(20.0, 10.0, 10.5, 20.0)
        endpoint_handle = harness.handle_points[2]
        self.assertAlmostEqual(endpoint_handle[0], expected[0], places=5)
        self.assertAlmostEqual(endpoint_handle[1], expected[1], places=5)
        self.assertNotEqual(endpoint_handle[:2], (10.0, 20.0))

    def test_snap_to_right_angle_can_snap_area_point_to_first_point_axis(self):
        from PySide6 import QtCore

        harness = PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        harness.snap_result = (10.5, 20.0, 10.5, 20.0, placement_mode.NONE)
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        endpoint_handle = harness.handle_points[2]
        self.assertEqual(endpoint_handle[:2], (10.0, 20.0))

    def test_snap_to_right_angle_hides_indicator_when_final_endpoint_is_not_right_angle(
        self,
    ):
        from PySide6 import QtCore

        harness = _area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 16.0, 10.5, 16.0, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(10.5, 16.0))
        endpoint_handle = harness.handle_points[2]
        self.assertNotEqual(
            (round(endpoint_handle[0], 5), round(endpoint_handle[1], 5)),
            (10.0, 16.0),
        )
        self.assertEqual(_indicator_lines(harness), [])

    def test_snap_to_right_angle_indicator_shows_for_final_x_axis_alignment(self):
        from PySide6 import QtCore

        harness = _area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 20.0, 10.5, 20.0, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        indicator_lines = _indicator_lines(harness)
        self.assertEqual(len(indicator_lines), 1)
        endpoint_handle = harness.handle_points[2]
        self.assertEqual(endpoint_handle[:2], (10.0, 20.0))
        indicator = indicator_lines[0].line()
        self.assertAlmostEqual(indicator.x2(), endpoint_handle[0])
        self.assertAlmostEqual(indicator.y2(), endpoint_handle[1])

    def test_snap_to_right_angle_indicator_shows_for_final_y_axis_alignment(self):
        from PySide6 import QtCore

        harness = _area_preview_harness(
            points=[(10.0, 10.0), (10.0, 20.0)],
            snap_result=(20.0, 10.5, 20.0, 10.5, placement_mode.NONE),
        )
        harness.update_place_preview(QtCore.QPointF(20.0, 10.5))
        indicator_lines = _indicator_lines(harness)
        self.assertEqual(len(indicator_lines), 1)
        endpoint_handle = harness.handle_points[2]
        self.assertAlmostEqual(endpoint_handle[0], 20.0)
        self.assertAlmostEqual(endpoint_handle[1], 10.0)
        indicator = indicator_lines[0].line()
        self.assertAlmostEqual(indicator.x2(), endpoint_handle[0])
        self.assertAlmostEqual(indicator.y2(), endpoint_handle[1])

    def test_snap_to_right_angle_disabled_hides_indicator(self):
        from PySide6 import QtCore

        harness = _area_preview_harness(
            points=[(10.0, 10.0), (20.0, 10.0)],
            snap_result=(10.5, 20.0, 10.5, 20.0, placement_mode.NONE),
        )
        harness._snap_to_right_angle_enabled = False
        harness.update_place_preview(QtCore.QPointF(10.5, 20.0))
        self.assertEqual(_indicator_lines(harness), [])

    def test_snap_to_right_angle_candidate_still_uses_mouse_angle_snap(self):
        harness = PlacementHarness()
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        endpoint = harness._area_final_endpoint_for_placement(
            20.0, 10.0, 10.5, 16.0, placement_mode.NONE
        )
        expected = harness._snap_angle(20.0, 10.0, 10.0, 16.0)
        self.assertTrue(endpoint.right_angle_candidate_active)
        self.assertFalse(endpoint.right_angle_indicator_active)
        self.assertAlmostEqual(endpoint.final_x, expected[0], places=5)
        self.assertAlmostEqual(endpoint.final_y, expected[1], places=5)
        self.assertNotEqual(
            (round(endpoint.final_x, 5), round(endpoint.final_y, 5)), (10.0, 16.0)
        )

    def test_snap_to_right_angle_respects_zero_pressed_mouse_snap_angle(self):
        from PySide6.QtCore import Qt

        harness = PlacementHarness()
        harness._place_points = [(10.0, 10.0), (20.0, 10.0)]
        harness._snap_to_right_angle_enabled = True
        harness._snap_to_right_angle_threshold_px = 1
        harness._mouse_pressed_snap_angle = 0
        original = placement_mode.QGuiApplication
        try:
            placement_mode.QGuiApplication = type(
                "FakeGuiApplication",
                (),
                {
                    "keyboardModifiers": staticmethod(
                        lambda: Qt.KeyboardModifier.ShiftModifier
                    )
                },
            )
            endpoint = harness._area_final_endpoint_for_placement(
                20.0, 10.0, 10.5, 16.0, placement_mode.NONE
            )
        finally:
            placement_mode.QGuiApplication = original
        self.assertTrue(endpoint.right_angle_candidate_active)
        self.assertTrue(endpoint.right_angle_indicator_active)
        self.assertEqual((endpoint.final_x, endpoint.final_y), (10.0, 16.0))

    def test_odd_length_takeoff_position_is_ignored_safely(self):
        harness = PlacementHarness()
        harness._current_takeoffs["t1"] = Takeoff(
            uid="t1",
            condition_uid="linear",
            position=[1.0, 2.0, 3.0],
        )
        self.assertEqual(harness._build_takeoff_snap_segments(), [])

    def test_rotated_pdf_segments_are_mapped_to_rendered_page_coordinates(self):
        FakePDFRenderer.raw_segments = [(1031.58, 1792.26, 1143.0, 1774.26)]
        FakePDFRenderer.page_width = 2592.0
        FakePDFRenderer.page_height = 1728.0
        FakePDFRenderer.media_width = 2592.0
        FakePDFRenderer.media_height = 1728.0
        FakePDFRenderer.crop_width = 1728.0
        FakePDFRenderer.crop_height = 2592.0
        FakePDFRenderer.intrinsic_rotation = 270
        harness = PlacementHarness()
        harness._pdf_width_pts = 2592.0
        harness._pdf_height_pts = 1728.0
        harness._ensure_pdf_snap_index()
        snap_index = FakeSnapIndex.instances[-1]
        self.assertEqual(
            snap_index.build_calls[-1][0],
            (
                (2592.0 - 1792.26) * 2.0,
                (1728.0 - 1031.58) * 2.0,
                (2592.0 - 1774.26) * 2.0,
                (1728.0 - 1143.0) * 2.0,
            ),
        )

    def test_pdf_raw_point_rotation_mapping(self):
        harness = PlacementHarness()
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 0),
            (10.0, 180.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 90),
            (20.0, 10.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 180),
            (90.0, 20.0),
        )
        self.assertEqual(
            harness._pdf_raw_point_to_page_point(10.0, 20.0, 100.0, 200.0, 270),
            (180.0, 90.0),
        )

    def test_pdf_snap_cache_key_includes_rendered_pdf_width(self):
        harness = PlacementHarness()
        first_key = harness._pdf_snap_cache_key()
        harness._pdf_width_pts = 300.0
        second_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(first_key, second_key)

    def test_pdf_snap_cache_key_includes_overlay_coordinate_calibration(self):
        harness = PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 1
        first_key = harness._pdf_snap_cache_key()
        harness._current_page.scale_factor1 = 0.125
        second_key = harness._pdf_snap_cache_key()
        self.assertNotEqual(first_key, second_key)

    def test_overlay_pdf_snap_points_map_through_overlay_rect_scale_and_rotation(self):
        harness = PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 2
        harness._current_page.width_pts = 200.0
        harness._current_page.overlay_offset_x = 999.0
        harness._current_page.overlay_offset_y = -999.0
        harness._current_page.overlay_rotation = math.pi / 2.0
        harness._current_page.overlay_rect = (
            64.0,
            32.0,
            200.0 / 72.0 * 64.0,
            100.0 / 72.0 * 64.0,
        )
        mapped = harness._pdf_intelligence_point_to_page_point(
            "overlay",
            10.0,
            20.0,
            100.0,
            50.0,
        )
        self.assertAlmostEqual(mapped[0], 32.0)
        self.assertAlmostEqual(mapped[1], 56.0)

    def test_composite_pdf_snap_uses_overlay_source(self):
        harness = PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.pdf"
        harness._current_page.image_show_mode = 2
        harness._ensure_pdf_snap_index()
        self.assertEqual(FakePDFRenderer.open_paths, ["overlay.pdf"])

    def test_raster_overlay_falls_back_to_main_pdf_snap_source(self):
        harness = PlacementHarness()
        harness._current_page.overlay_image_path = "overlay.tif"
        harness._current_page.image_show_mode = 2
        harness._ensure_pdf_snap_index()
        self.assertEqual(FakePDFRenderer.open_paths, ["drawing.pdf"])

    def test_linear_preview_adds_start_and_current_endpoint_handles(self):
        from PySide6 import QtCore

        harness = PreviewHarness()
        harness._place_points = [(0.0, 0.0)]
        harness._place_linear_dragging = True
        harness.snap_result = (10.0, 0.0, 10.0, 0.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(10.0, 0.0))
        self.assertIn((0.0, 0.0, 4.0), harness.handle_points)
        self.assertIn((10.0, 0.0, 4.0), harness.handle_points)
        self.assertEqual(harness.pattern_angles, [0.0])

    def test_diagonal_linear_preview_passes_line_direction_to_pattern(self):
        from PySide6 import QtCore

        harness = PreviewHarness()
        harness._place_points = [(0.0, 0.0)]
        harness._place_linear_dragging = True
        harness.snap_result = (10.0, 10.0, 10.0, 10.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(10.0, 10.0))
        self.assertAlmostEqual(harness.pattern_angles[0], math.pi / 4.0)

    def test_area_preview_adds_current_endpoint_handle(self):
        from PySide6 import QtCore

        harness = PreviewHarness()
        harness._current_conditions["area"] = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        harness._place_session_uid = "area"
        harness._place_points = [(0.0, 0.0), (5.0, 0.0)]
        harness.snap_result = (5.0, 5.0, 5.0, 5.0, placement_mode.GRID)
        harness.update_place_preview(QtCore.QPointF(5.0, 5.0))
        self.assertIn((0.0, 0.0, 4.0), harness.handle_points)
        self.assertIn((5.0, 0.0, 4.0), harness.handle_points)
        self.assertIn((5.0, 5.0, 4.0), harness.handle_points)

    def test_display_pattern_while_drawing_off_uses_outline_only_preview(self):
        harness = PlacementHarness()
        harness._scene = RecordingScene()
        harness._scene_builder = PatternPreviewSceneBuilder()
        harness._place_preview_items = []
        path = QPainterPath()
        path.addRect(0.0, 0.0, 12.0, 12.0)
        item = QGraphicsPathItem(path)
        condition = Condition(
            uid="area",
            condition_type=Condition.TYPE_AREA,
            display_grid_while_drawing=False,
        )
        harness._apply_pattern_preview(
            item,
            path,
            condition,
            QColor("#123456"),
            0.5,
            None,
        )
        self.assertEqual(harness._scene_builder.pattern_fill_calls, 0)
        self.assertEqual(harness._place_preview_items, [item])
        self.assertEqual(item.brush().style(), Qt.BrushStyle.NoBrush)

    def test_linear_preview_uses_pattern_even_without_display_pattern_flag(self):
        harness = PlacementHarness()
        harness._scene = RecordingScene()
        harness._scene_builder = PatternPreviewSceneBuilder()
        harness._place_preview_items = []
        path = QPainterPath()
        path.addRect(0.0, 0.0, 12.0, 4.0)
        item = QGraphicsPathItem(path)
        condition = Condition(
            uid="linear",
            condition_type=Condition.TYPE_LINEAR,
            display_grid_while_drawing=False,
        )
        harness._apply_pattern_preview(
            item,
            path,
            condition,
            QColor("#123456"),
            0.5,
            None,
        )
        self.assertEqual(harness._scene_builder.pattern_fill_calls, 1)
        self.assertEqual(len(harness._place_preview_items), 2)
        self.assertIs(harness._place_preview_items[0], item)

    def test_snap_cursor_marker_remains_line_snap_only(self):
        harness = PreviewHarness()
        harness._add_snap_cursor_marker(1.0, 2.0, placement_mode.GRID)
        self.assertEqual(harness.handle_points, [])
        harness._add_snap_cursor_marker(1.0, 2.0, placement_mode.ENDPOINT)
        self.assertEqual(harness.handle_points, [(1.0, 2.0, 4.0)])
        harness._add_snap_cursor_marker(3.0, 4.0, placement_mode.MIDPOINT)
        self.assertEqual(
            harness.handle_points,
            [(1.0, 2.0, 4.0), (3.0, 4.0, 4.0)],
        )


def tearDownModule():
    for name, module in _ORIGINAL_MODULES.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
