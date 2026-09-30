from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from PySide6.QtCore import QPointF, QRectF, Qt
from ost_visualizer.presentation.scene.plan_view_z_order import (
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.application.dtos.hotlink_dto import HotlinkDto
from types import SimpleNamespace
import unittest
import os
import math
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from tests.presentation.visualization.exporters.oval_support import (
    _rotated_oval_position as _oval_support__rotated_oval_position,
)
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    PolygonControlPointTarget,
    SelectionManagerMixin,
)
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QBrush, QColor, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QMenu,
)
from tests.presentation.components.plan_view.components.interaction_support import (
    AREA_CP_HOLE_ORIGINAL_POSITION as _interaction_support_AREA_CP_HOLE_ORIGINAL_POSITION,
    AREA_CP_ORIGINAL_POSITION as _interaction_support_AREA_CP_ORIGINAL_POSITION,
    BaseKeyHandler as _interaction_support_BaseKeyHandler,
    FakeCoordinateSystem as _interaction_support_FakeCoordinateSystem,
    FakeCursorViewport as _interaction_support_FakeCursorViewport,
    FakeItem as _interaction_support_FakeItem,
    FakeMouseEvent as _interaction_support_FakeMouseEvent,
    FakeSceneBuilder as _interaction_support_FakeSceneBuilder,
    FakeSignal as _interaction_support_FakeSignal,
    InputHandlerHarness as _interaction_support_InputHandlerHarness,
    _FakeSignal as _interaction_support__FakeSignal,
    _app as _interaction_support__app,
)
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
from ost_visualizer.presentation.components.plan_view.view import TakeoffPlanView
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
    QStyleOptionGraphicsItem,
)
from shiboken6 import delete
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeCoordinateSystem,
    FakeDebouncer,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakePageItem,
    FakePageSizeProvider,
    FakeRenderingService,
    FakeScene,
    FakeScrollBar,
    FakeSignal,
    FakeSizedViewport,
    FakeTakeoffRenderer,
    FakeTransform,
    FakeViewport,
    RecordingPathTakeoffRenderer,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete, isValid
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    FakeTakeoffRenderer,
)
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from tests.presentation.components.plan_view.overlay_support import (
    FakeAnnotationRenderer,
    FakeColorService,
    FakeLinearGeometry,
    FakeLoadCoordinator,
    FakeRenderingService,
    RecordingPathTakeoffRenderer,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeCoordinateSystem:
    def update_page_info(self, _page_info):
        pass

    def transform_vertices_to_2d(self, values):
        return list(values)

    def transform_to_2d(self, x, y):
        return x, y

    def pdf_points_to_screen_pixels(self, value):
        return value

    def ost_to_screen_pixels(self, value):
        return value


class _SelectionHarness(SelectionManagerMixin):
    def __init__(self, scene, takeoffs, annotations, conditions):
        self._scene = scene
        self._current_takeoffs = takeoffs
        self._current_annotations = annotations
        self._current_conditions = conditions
        self._hidden_layer_uids = set()
        self._annotation_only_selection = False
        self._uid_to_items = {}
        self._pending_mutation_uids = set()

    def transform(self):
        return SimpleNamespace(m11=lambda: 1.0)


class SelectionManagerZOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_hidden_layer_linear_annotation_is_not_geometrically_selectable(self):
        annotation = BidAnnotation(
            uid="line-1",
            annotation_type="line",
            page_uid="page-1",
            layer_uid="hidden",
            position=[0.0, 0.0, 100.0, 0.0],
        )
        selection = _SelectionHarness(
            QGraphicsScene(),
            takeoffs={},
            annotations={"line-1": annotation},
            conditions={},
        )
        selection._hidden_layer_uids = {"hidden"}
        selection._scene_builder = SimpleNamespace(
            get_coordinate_system=lambda: FakeCoordinateSystem()
        )
        selection._current_page_transform = lambda: None
        self.assertIsNone(selection.find_linear_annotation_near(QPointF(50.0, 0.0)))

    def test_hidden_layer_text_annotation_is_not_hit_testable(self):
        annotation = BidAnnotation(
            uid="text-1",
            annotation_type="text",
            page_uid="page-1",
            layer_uid="hidden",
            position=[0.0, 0.0, 100.0, 30.0],
            properties={"Text": "Hidden note"},
        )
        scene = QGraphicsScene()
        item = QGraphicsTextItem("Hidden note")
        item.setData(0, annotation.uid)
        scene.addItem(item)
        selection = _SelectionHarness(
            scene,
            takeoffs={},
            annotations={annotation.uid: annotation},
            conditions={},
        )
        selection._hidden_layer_uids = {"hidden"}
        selection._uid_to_items = {annotation.uid: [item]}
        self.assertIsNone(selection.find_text_annotation_at(QPointF(1.0, 1.0)))

    def test_hidden_layer_hotlink_annotation_is_not_hit_testable(self):
        annotation = BidAnnotation(
            uid="hotlink-1",
            annotation_type="hotlink",
            page_uid="page-1",
            layer_uid="hidden",
            position=[10.0, 10.0, 5.0],
        )
        scene = QGraphicsScene()
        item = QGraphicsRectItem(5.0, 5.0, 10.0, 10.0)
        scene.addItem(item)
        link = HotlinkDto(
            uid=annotation.uid,
            bid_page_uid="page-1",
            target_view_uid="view-1",
            center_x=10.0,
            center_y=10.0,
            radius=5.0,
        )
        selection = _SelectionHarness(
            scene,
            takeoffs={},
            annotations={annotation.uid: annotation},
            conditions={},
        )
        selection._hidden_layer_uids = {"hidden"}
        selection._hotlink_items = [(item, link)]
        self.assertIsNone(selection.find_hotlink_at(QPointF(10.0, 10.0)))

    def test_annotation_hit_order_still_prefers_lowered_highlight_over_takeoff(self):
        scene = QGraphicsScene()
        takeoff_item = QGraphicsRectItem(QRectF(0.0, 0.0, 20.0, 20.0))
        takeoff_item.setData(0, "t1")
        takeoff_item.setZValue(TAKEOFF_BODY_Z)
        scene.addItem(takeoff_item)
        highlight_item = QGraphicsRectItem(QRectF(0.0, 0.0, 20.0, 20.0))
        highlight_item.setData(0, "h1")
        highlight_item.setZValue(PAPER_HIGHLIGHT_Z)
        scene.addItem(highlight_item)
        harness = _SelectionHarness(
            scene=scene,
            takeoffs={"t1": Takeoff(uid="t1", condition_uid="c1")},
            annotations={
                "h1": BidAnnotation(
                    uid="h1",
                    annotation_type="highlight",
                    page_uid="p1",
                    position=[0.0, 0.0, 20.0, 20.0],
                )
            },
            conditions={"c1": Condition(uid="c1", condition_type=Condition.TYPE_AREA)},
        )
        self.assertEqual(harness.find_takeoff_at(QPointF(10.0, 10.0)), "h1")


class OvalSelectionHandleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_handles_use_the_same_canonical_rotated_geometry(self):
        annotation = BidAnnotation(
            uid="oval",
            annotation_type="oval",
            position=_oval_support__rotated_oval_position(
                200.0, 150.0, 120.0, 40.0, 30.0
            ),
        )
        actual = SelectionManagerMixin._get_ann_corners_ost(annotation)
        angle = math.radians(30.0)
        expected = []
        for dx, dy in ((-60.0, -20.0), (60.0, -20.0), (60.0, 20.0), (-60.0, 20.0)):
            expected.extend(
                [
                    200.0 + dx * math.cos(angle) - dy * math.sin(angle),
                    150.0 + dx * math.sin(angle) + dy * math.cos(angle),
                ]
            )
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value)


class CtrlDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _make_view(self, selected_uids=None):
        view = _interaction_support_InputHandlerHarness()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._current_bid_ref = None
        view._current_page = None
        view._cursor_mode = "select"
        view._selection_enabled = True
        view._ctrl_held = False
        view._use_full_window_crosshairs = False
        view._zoom_press_ctrl = False
        view._select_band_origin = None
        view._select_band_active = False
        view._select_band_dragged = False
        view._press_changed_selection = False
        view._rotation_drag_active = False
        view._rotate_cursor = Qt.CursorShape.CrossCursor
        view._rotate_handle_item = None
        view._panning = False
        view._right_pan_active = False
        view._point_annotation_release_pending = False
        view._last_pan_point = None
        view._drag_plan_item_uid = None
        view._drag_handle_index = -2
        view._drag_orig_position = []
        view._drag_handle_corner_count = 0
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._keyboard_move_dirty = False
        view._selected_uids = set({"t1"} if selected_uids is None else selected_uids)
        view.plan_item_selection_changed = _interaction_support__FakeSignal()
        view.takeoff_selection_changed = _interaction_support__FakeSignal()
        view._handle_infos = []
        view._selection_items = []
        view._current_takeoffs = {
            "t1": Takeoff(
                uid="t1",
                position=[0.0, 0.0, 10.0, 0.0],
                condition_uid="c",
            ),
            "t2": Takeoff(
                uid="t2",
                position=[20.0, 0.0, 30.0, 0.0],
                condition_uid="c",
            ),
        }
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_conditions = {}
        view._scene = None
        view._uid_to_items = {
            "t1": [_interaction_support_FakeItem(1.0, 2.0)],
            "t2": [_interaction_support_FakeItem(3.0, 4.0)],
        }
        view._takeoff_items = []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        view.find_takeoff_at = lambda _scene_pos: "t1"
        view.find_takeoffs_at = lambda _scene_pos: ["t1"]
        view._flush_dirty_positions = lambda: None
        view.update_selection_visuals = lambda *args, **_call_options: None
        view._rubber_band_origin = None
        view._rubber_band = None
        view._update_cursor = lambda *args, **_call_options: None
        view._snap_increments = 1.0
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view.ost_to_scene_delta = lambda dx, dy: (dx, dy)
        return view

    def _make_area_control_point_view(self, selected_uids=None, include_hole=False):
        view = self._make_view(set() if selected_uids is None else selected_uids)
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._annotation_only_selection = False
        view._hidden_layer_uids = set()
        view._current_page = None
        view._current_conditions = {
            "area": Condition(
                uid="area",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "linear": Condition(
                uid="linear",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            ),
        }
        view._current_takeoffs = {
            "area1": Takeoff(
                uid="area1",
                condition_uid="area",
                page_uid="page-1",
                position=list(_interaction_support_AREA_CP_ORIGINAL_POSITION),
            ),
            "linear1": Takeoff(
                uid="linear1",
                condition_uid="linear",
                page_uid="page-1",
                position=[200.0, 0.0, 300.0, 0.0],
            ),
        }
        if include_hole:
            view._current_takeoffs["hole1"] = Takeoff(
                uid="hole1",
                condition_uid="area",
                page_uid="page-1",
                parent_uid="area1",
                position=list(_interaction_support_AREA_CP_HOLE_ORIGINAL_POSITION),
            )
        area_path = QPainterPath()
        area_path.moveTo(0.0, 0.0)
        area_path.lineTo(100.0, 0.0)
        area_path.lineTo(100.0, 100.0)
        area_path.lineTo(0.0, 100.0)
        area_path.closeSubpath()
        area_item = QGraphicsPathItem(area_path)
        area_item.setData(0, "area1")
        area_item.setZValue(0.5)
        items_by_uid = {"area1": [area_item]}
        if include_hole:
            hole_path = QPainterPath()
            hole_path.moveTo(20.0, 20.0)
            hole_path.lineTo(40.0, 20.0)
            hole_path.lineTo(40.0, 40.0)
            hole_path.lineTo(20.0, 40.0)
            hole_path.closeSubpath()
            hole_item = QGraphicsPathItem(hole_path)
            hole_item.setData(0, "hole1")
            hole_item.setZValue(0.6)
            view._scene.addItem(hole_item)
            items_by_uid["hole1"] = [hole_item]
        linear_path = QPainterPath()
        linear_path.moveTo(200.0, 0.0)
        linear_path.lineTo(300.0, 0.0)
        linear_item = QGraphicsPathItem(linear_path)
        linear_item.setData(0, "linear1")
        linear_item.setZValue(0.5)
        view._scene.addItem(area_item)
        view._scene.addItem(linear_item)
        items_by_uid["linear1"] = [linear_item]
        view._uid_to_items = items_by_uid
        view._current_annotations = {}
        view._hotlink_items = []
        view._current_page_transform = lambda: None
        view._pt_to_scene = lambda x, y: QtCore.QPointF(float(x), float(y))
        view._scene_pos_to_ost = lambda point: QtCore.QPointF(point)
        view.transform = lambda: QTransform()
        view.mapToScene = lambda point: QtCore.QPointF(point)
        view.mapFromScene = lambda point: QtCore.QPoint(int(point.x()), int(point.y()))
        del view.find_takeoff_at
        del view.find_takeoffs_at
        view._position_before_edit = {}
        view._dirty_positions = {}
        view._dirty_ann_positions = {}
        view._ann_db_uid_map = {}
        view._refreshing_overlays = False
        view.positions_flushed = _interaction_support_FakeSignal()
        view.rebuild_count = 0
        view.selection_update_count = 0
        view.snap_invalidations = 0

        def rebuild_current_overlays_from_model():
            view.rebuild_count += 1

        def update_selection_visuals(*_args, **_options):
            view.selection_update_count += 1

        def invalidate_snap_index():
            view.snap_invalidations += 1

        view._rebuild_current_overlays_from_model = rebuild_current_overlays_from_model
        view.update_selection_visuals = update_selection_visuals
        view._invalidate_snap_index = invalidate_snap_index

        def flush_dirty_positions():
            if view._refreshing_overlays:
                return
            if not view._dirty_positions and not view._dirty_ann_positions:
                return
            if view._dirty_positions:
                view._invalidate_snap_index()
            dirty = dict(view._dirty_positions)
            ann_dirty = dict(view._dirty_ann_positions)
            prev = dict(view._position_before_edit)
            view._dirty_positions.clear()
            view._dirty_ann_positions.clear()
            view._position_before_edit.clear()
            takeoff_changes = [
                (uid, prev.get(uid, []), pos) for uid, pos in dirty.items()
            ]
            ann_changes = [
                (view._ann_db_uid_map.get(uid, uid), ann_type, prev.get(uid, []), pos)
                for uid, (ann_type, pos) in ann_dirty.items()
            ]
            view.positions_flushed.emit(takeoff_changes, ann_changes)

        view._flush_dirty_positions = flush_dirty_positions
        view._add_common_context_submenus = lambda _menu: (0, None, None)
        view._add_context_clipboard_actions = lambda _menu: None
        view._add_context_page_actions = lambda _menu, **_options: None
        view._context_menu_command_trigger = None
        view._context_menu_action_state = lambda _key: {"enabled": True}
        view._suppress_next_context_menu = False
        view.reset_ctrl_held = lambda: None
        return view

    def test_area_control_point_target_returns_edge_near_boundary(self):
        view = self._make_area_control_point_view()
        target = view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "area1")
        self.assertEqual(target.edge_index, 0)
        self.assertEqual(target.insert_point, (50.0, 0.0))

    def test_area_control_point_target_ignores_fill_click(self):
        view = self._make_area_control_point_view()
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(50.0, 50.0))
        )

    def test_area_control_point_target_prefers_vertex_over_edge(self):
        view = self._make_area_control_point_view()
        target = view.polygon_control_point_target_at(QtCore.QPointF(0.0, 0.0))
        self.assertEqual(target.kind, "vertex")
        self.assertEqual(target.plan_item_uid, "area1")
        self.assertEqual(target.vertex_index, 0)

    def test_area_control_point_target_ignores_non_area_takeoffs(self):
        view = self._make_area_control_point_view()
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(250.0, 0.0))
        )

    def test_area_control_point_target_supports_parent_with_child_holes(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(50.0, 0.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "area1")

    def test_hole_control_point_target_returns_edge_near_boundary(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        self.assertEqual(target.kind, "edge")
        self.assertEqual(target.plan_item_uid, "hole1")
        self.assertEqual(target.edge_index, 0)
        self.assertEqual(target.insert_point, (30.0, 20.0))

    def test_hole_control_point_target_prefers_vertex_over_edge(self):
        view = self._make_area_control_point_view(include_hole=True)
        target = view.polygon_control_point_target_at(QtCore.QPointF(20.0, 20.0))
        self.assertEqual(target.kind, "vertex")
        self.assertEqual(target.plan_item_uid, "hole1")
        self.assertEqual(target.vertex_index, 0)

    def test_hole_control_point_target_ignores_fill_click(self):
        view = self._make_area_control_point_view(include_hole=True)
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 30.0))
        )

    def test_hole_control_point_target_rejects_missing_parent(self):
        view = self._make_area_control_point_view(include_hole=True)
        view._current_takeoffs["hole1"].parent_uid = "missing-parent"
        self.assertIsNone(
            view.polygon_control_point_target_at(QtCore.QPointF(30.0, 20.0))
        )

    def _make_hotlink_view(self, *, selected: bool):
        view = self._make_view({"h1"} if selected else set())
        view.hotlink_clicked = _interaction_support_FakeSignal()
        view._current_takeoffs = {}
        view._current_annotations = {
            "h1": BidAnnotation(
                uid="h1",
                annotation_type="hotlink",
                position=[10.0, 10.0],
                properties={"BidPageViewUID": "view-1"},
            )
        }
        path = QPainterPath()
        path.addEllipse(QtCore.QPointF(10.0, 10.0), 5.0, 5.0)
        item = QGraphicsPathItem(path)
        item.setData(0, "h1")
        view._uid_to_items = {"h1": [item]}
        view._hotlink_items = [
            (
                item,
                HotlinkDto(
                    uid="h1",
                    bid_page_uid="page-1",
                    target_view_uid="view-1",
                    center_x=10.0,
                    center_y=10.0,
                    radius=5.0,
                ),
            )
        ]
        view.find_takeoff_at = lambda _scene_pos, cycle_from_uid=None: None
        view.find_takeoffs_at = lambda _scene_pos: []
        view.mapToScene = lambda _point: QtCore.QPointF(10.0, 10.0)
        return view

    def test_pending_hotlink_collision_uses_scene_key_for_hit_testing(self):
        view = self._make_hotlink_view(selected=False)
        item, hotlink = view._hotlink_items[0]
        hotlink.uid = "shared"
        item.setData(0, "shared_hotlink")
        view._uid_to_items = {"shared_hotlink": [item]}
        view._current_conditions = {
            "c": Condition(
                uid="c",
                condition_type=Condition.TYPE_COUNT,
                layer_visible=True,
            )
        }
        view._current_takeoffs = {
            "shared": Takeoff(uid="shared", condition_uid="c", position=[10.0, 10.0])
        }
        view._current_annotations = {
            "shared_hotlink": BidAnnotation(
                uid="shared",
                annotation_type="hotlink",
                position=[10.0, 10.0],
                properties={"BidPageViewUID": "view-1"},
            )
        }
        view._pending_mutation_uids = {"shared_hotlink"}
        self.assertIsNone(view.find_hotlink_at(QtCore.QPointF(10.0, 10.0)))

    def test_hotlink_placement_release_skips_hotlink_hit_testing(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        view.annotation_place_release_consumed = True
        calls = []
        view.find_hotlink_at = lambda _scene_pos: calls.append("hit-test") or None
        release = _interaction_support_FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
        view.mouseReleaseEvent(release)
        self.assertTrue(release.accepted)
        self.assertEqual(calls, [])
        self.assertEqual(view.hotlink_clicked.emitted, [])

    def test_hotlink_placement_press_does_not_fall_through_to_hit_testing(self):
        view = self._make_hotlink_view(selected=False)
        view._cursor_mode = "annotation_place"
        view._annotation_place_type = "hotlink"
        press_calls = []
        hit_test_calls = []

        def _place_press(event):
            press_calls.append(event.pos())
            event.accept()
            return True

        view.handle_annotation_place_press = _place_press
        view.find_hotlink_at = lambda _scene_pos: hit_test_calls.append("hit") or None
        press = _interaction_support_FakeMouseEvent()
        view.mousePressEvent(press)
        self.assertTrue(press.accepted)
        self.assertEqual(len(press_calls), 1)
        self.assertEqual(hit_test_calls, [])
        self.assertEqual(view.hotlink_clicked.emitted, [])

    def test_repeated_hotlink_placements_do_not_navigate_but_later_clicks_do(self):
        view = self._make_hotlink_view(selected=False)
        hit_test_calls = []

        def _place_press(event):
            event.accept()
            view.annotation_place_release_consumed = True
            return True

        view.handle_annotation_place_press = _place_press
        view.find_hotlink_at = lambda _scene_pos: hit_test_calls.append("hit") or "h1"
        for expected_clicks in (1, 2):
            view._cursor_mode = "annotation_place"
            view._annotation_place_type = "hotlink"
            calls_before_placement = len(hit_test_calls)
            view.mousePressEvent(_interaction_support_FakeMouseEvent())
            placement_release = _interaction_support_FakeMouseEvent(
                buttons=Qt.MouseButton.NoButton
            )
            view.mouseReleaseEvent(placement_release)
            self.assertTrue(placement_release.accepted)
            self.assertEqual(len(view.hotlink_clicked.emitted), expected_clicks - 1)
            self.assertEqual(len(hit_test_calls), calls_before_placement)
            view._cursor_mode = "select"
            calls_before_click = len(hit_test_calls)
            view.mousePressEvent(_interaction_support_FakeMouseEvent())
            view.mouseReleaseEvent(
                _interaction_support_FakeMouseEvent(buttons=Qt.MouseButton.NoButton)
            )
            self.assertEqual(len(view.hotlink_clicked.emitted), expected_clicks)
            self.assertGreater(len(hit_test_calls), calls_before_click)

    def test_programmatic_sql_selection_refreshes_cursor_without_mouse_move(self):
        # Authoritative SQL hydration may rebuild the selected item while keeping
        # the same UID, so the idempotent selection projection must also refresh.
        view = self._make_view({"t1"})
        view._annotation_only_selection = False
        view._current_conditions = {
            "c": Condition(
                uid="c",
                condition_type=Condition.TYPE_LINEAR,
                layer_visible=True,
            )
        }
        viewport = _interaction_support_FakeCursorViewport()
        view.viewport = lambda: viewport
        view._last_mouse_vp_pos = QtCore.QPoint(10, 10)
        view.find_selected_movable_at = lambda _scene_pos: (
            "t1" if "t1" in view._selected_uids else None
        )
        view._update_cursor = lambda vp_pos=None: InputHandlerMixin._update_cursor(
            view, vp_pos
        )
        SelectionManagerMixin.set_selected_uids(view, {"t1"})
        self.assertEqual(viewport.cursor, Qt.CursorShape.SizeAllCursor)
        SelectionManagerMixin.clear_selection(view)
        self.assertEqual(viewport.cursor, Qt.CursorShape.ArrowCursor)

    def _make_named_view_resize_view(self):
        view = _interaction_support_InputHandlerHarness()
        view._snap_increments = 0
        ann = BidAnnotation(
            uid="nv1",
            annotation_type="namedview",
            position=[100.0, 80.0, 10.0, 20.0, 100.0, 20.0, 10.0, 80.0, 0.0],
            color="#008000",
        )
        return view, ann

    def test_named_view_handles_use_normalized_edit_corner_order(self):
        _view, ann = self._make_named_view_resize_view()
        self.assertEqual(
            SelectionManagerMixin._get_ann_corners_ost(ann),
            [10.0, 20.0, 100.0, 20.0, 100.0, 80.0, 10.0, 80.0],
        )


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_text_annotation_toolbar_hides_when_selection_clears(self):
        view = self._make_plan_view()
        _annotation, _item = self._add_text_annotation(view, text="Before")
        view._selected_uids = {"a1"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.clear_selection()
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_deleted_text_target_clears_toolbar_and_keeps_remaining_selection(self):
        view = self._make_plan_view()
        annotation_1, item_1 = self._add_text_annotation(view, uid="a1", text="First")
        annotation_2, item_2 = self._add_text_annotation(view, uid="a2", text="Second")
        view._current_annotations = {"a1": annotation_1, "a2": annotation_2}
        view._uid_to_items = {"a1": [item_1], "a2": [item_2]}
        view._selected_uids = {"a1", "a2"}
        self.assertTrue(view._select_text_annotation_label("a1"))
        view._current_annotations.pop("a1")
        view._uid_to_items.pop("a1")
        view._scene.removeItem(item_1)
        view.update_selection_visuals()
        self.assertEqual(view.get_selected_uids(), ["a2"])
        self.assertIsNone(view._selected_text_item)
        self.assertIsNone(view._selected_text_annotation_uid)
        self.assertTrue(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_deleting_unselected_annotation_keeps_valid_text_toolbar_target(self):
        view = self._make_plan_view()
        annotation_1, item_1 = self._add_text_annotation(view, uid="a1", text="First")
        annotation_2, item_2 = self._add_text_annotation(view, uid="a2", text="Second")
        view._current_annotations = {"a1": annotation_1, "a2": annotation_2}
        view._uid_to_items = {"a1": [item_1], "a2": [item_2]}
        view._selected_uids = {"a2"}
        self.assertTrue(view._select_text_annotation_label("a2"))
        view._current_annotations.pop("a1")
        view._uid_to_items.pop("a1")
        view._scene.removeItem(item_1)
        view.update_selection_visuals()
        self.assertEqual(view.get_selected_uids(), ["a2"])
        self.assertIs(view._selected_text_item, item_2)
        self.assertEqual(view._selected_text_annotation_uid, "a2")
        self.assertFalse(view._condition_text_toolbar.isHidden())
        view.cleanup()

    def test_text_annotation_selection_outline_uses_resize_box_bounds(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[500.0, 500.0, 300.0, 200.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setPos(20, 30)
        item.setTextWidth(80)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        outline = self._first_selection_outline(view)
        outline_rect = outline.polygon().boundingRect()
        self.assertEqual(outline.pen().style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(outline.pen().color(), QColor(128, 128, 128))
        self.assertEqual(outline_rect, QtCore.QRectF(350.0, 400.0, 300.0, 200.0))
        self.assertNotEqual(
            outline_rect, item.mapToScene(item.boundingRect()).boundingRect()
        )
        view.cleanup()

    def test_inline_text_annotation_edit_outline_uses_resize_box_bounds(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        item.setTextWidth(20)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        self.assertTrue(view._begin_text_annotation_edit("a1"))
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        outline = self._first_selection_outline(view)
        self.assertEqual(outline.pen().style(), QtCore.Qt.PenStyle.DashLine)
        self.assertEqual(outline.pen().color(), QColor(128, 128, 128))
        self.assertEqual(
            outline.polygon().boundingRect(),
            QtCore.QRectF(60.0, 80.0, 80.0, 40.0),
        )
        self.assertNotEqual(
            outline.polygon().boundingRect(),
            item.mapToScene(item.boundingRect()).boundingRect(),
        )
        view.cleanup()

    def test_clipped_text_annotation_hitbox_excludes_hidden_overflow(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 20.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem(
            "Line 1\nLine 2\nLine 3",
            QtCore.QRectF(0.0, 0.0, 80.0, 20.0),
        )
        item.setData(0, "a1")
        item.setTextWidth(80.0)
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selection_enabled = True
        self.assertIn("a1", view.find_takeoffs_at(QtCore.QPointF(5.0, 5.0)))
        self.assertNotIn("a1", view.find_takeoffs_at(QtCore.QPointF(5.0, 40.0)))
        view.cleanup()

    def test_select_objects_in_current_area_uses_visible_takeoff_rules(self):
        view = self._make_plan_view()
        view._current_bid_page_uid = "page-1"
        view._current_conditions = {
            "visible-condition": Condition(
                uid="visible-condition",
                condition_type=Condition.TYPE_AREA,
                layer_visible=True,
            ),
            "hidden-condition": Condition(
                uid="hidden-condition",
                condition_type=Condition.TYPE_AREA,
                layer_visible=False,
            ),
        }
        view._current_takeoffs = {
            "visible-area": Takeoff(
                uid="visible-area",
                condition_uid="visible-condition",
                page_uid="page-1",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            ),
            "hidden-area": Takeoff(
                uid="hidden-area",
                condition_uid="hidden-condition",
                page_uid="page-1",
                area_uid="area-1",
                position=[30.0, 0.0, 50.0, 0.0, 50.0, 20.0],
            ),
            "other-area": Takeoff(
                uid="other-area",
                condition_uid="visible-condition",
                page_uid="page-1",
                area_uid="area-2",
                position=[0.0, 30.0, 20.0, 30.0, 20.0, 50.0],
            ),
            "other-page": Takeoff(
                uid="other-page",
                condition_uid="visible-condition",
                page_uid="page-2",
                area_uid="area-1",
                position=[30.0, 30.0, 50.0, 30.0, 50.0, 50.0],
            ),
        }
        view._current_annotations = {}
        view._uid_to_items = {}
        view._selection_enabled = True
        view._cursor_mode = "select"
        for uid in view._current_takeoffs:
            item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
            item.setData(0, uid)
            view._scene.addItem(item)
            view._uid_to_items[uid] = [item]
        view.select_takeoffs_in_area("area-1")
        self.assertEqual(view._selected_uids, {"visible-area"})
        self.assertTrue(view._selection_items)
        view.cleanup()

    def test_select_objects_in_current_area_allows_reenabled_layer(self):
        view = self._make_plan_view()
        view._current_bid_page_uid = "page-1"
        condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            layer_visible=False,
        )
        view._current_conditions = {condition.uid: condition}
        view._current_takeoffs = {
            "area-takeoff": Takeoff(
                uid="area-takeoff",
                condition_uid=condition.uid,
                page_uid="page-1",
                area_uid="area-1",
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            )
        }
        view._current_annotations = {}
        item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        item.setData(0, "area-takeoff")
        view._scene.addItem(item)
        view._uid_to_items = {"area-takeoff": [item]}
        view._selection_enabled = True
        view._cursor_mode = "select"
        view.select_takeoffs_in_area("area-1")
        self.assertEqual(view._selected_uids, set())
        condition.layer_visible = True
        view.select_takeoffs_in_area("area-1")
        self.assertEqual(view._selected_uids, {"area-takeoff"})
        view.cleanup()

    def test_hidden_layer_prunes_existing_takeoff_selection(self):
        view = self._make_plan_view()
        condition = Condition(
            uid="area-condition",
            condition_type=Condition.TYPE_AREA,
            layer_visible=True,
        )
        view._current_conditions = {condition.uid: condition}
        view._current_takeoffs = {
            "area": Takeoff(
                uid="area",
                condition_uid=condition.uid,
                position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0],
            )
        }
        view._current_annotations = {}
        item = QGraphicsRectItem(0.0, 0.0, 10.0, 10.0)
        item.setData(0, "area")
        view._scene.addItem(item)
        view._uid_to_items = {"area": [item]}
        emitted = []
        view.takeoff_selection_changed.connect(lambda uids: emitted.append(list(uids)))
        view.set_selected_uids({"area"})
        self.assertEqual(view._selected_uids, {"area"})
        condition.layer_visible = False
        view.update_selection_visuals()
        self.assertEqual(view._selected_uids, set())
        self.assertEqual(view._selection_items, [])
        self.assertEqual(emitted[-1], [])
        view.cleanup()

    def _add_text_annotation(
        self,
        view,
        *,
        uid="a1",
        text="Text",
        page_uid="",
        position=None,
        font_size=12,
    ):
        if position is None:
            position = [0.0, 0.0, 80.0, 24.0]
        annotation = BidAnnotation(
            uid=uid,
            annotation_type="text",
            page_uid=page_uid,
            position=list(position),
            properties={
                "Text": text,
                "FontName": "Arial",
                "FontColor": 0,
                "FontSize": font_size,
                "FontBold": False,
                "FontItalic": False,
                "FontUnderline": False,
                "TextAlign": 0,
            },
        )
        item = QGraphicsTextItem(text)
        item.setData(0, uid)
        item.setFont(QFont("Arial", font_size))
        item.setTextWidth(position[2])
        view._scene.addItem(item)
        view._uid_to_items = {uid: [item]}
        view._current_annotations = {uid: annotation}
        view._selection_enabled = True
        return annotation, item

    def _make_plan_view(self, *, load_coordinator=None, annotation_renderer=None):
        view = TakeoffPlanView(
            color_service=FakeColorService(),
            rendering_service=FakeRenderingService(),
            load_coordinator=load_coordinator or FakeLoadCoordinator(),
            takeoff_renderer=FakeTakeoffRenderer(),
            annotation_renderer=annotation_renderer or FakeAnnotationRenderer(),
            linear_geometry=FakeLinearGeometry(),
        )
        # Release test-owned windows before another test enters a native popup
        # loop. cleanup() releases services, but does not destroy the Qt widget.
        owned = [view]
        view.destroyed.connect(lambda: owned.clear())

        def release_view():
            if owned:
                delete(owned[0])

        self.addCleanup(release_view)
        # Production window composition projects access immediately after
        # constructing the view. Tests exercising edit workflows must model
        # that contract explicitly.
        view.set_editing_enabled(True)
        return view

    def _first_selection_outline(self, view):
        return next(
            item
            for item in view._selection_items
            if isinstance(item, QGraphicsPolygonItem)
        )
