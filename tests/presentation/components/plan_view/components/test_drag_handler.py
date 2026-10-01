import math
import os
import unittest
from types import SimpleNamespace
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_POLYGON,
    BidAnnotation,
)
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.components.plan_view.components.drag_handler import (
    DragHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.components.plan_view.components.input_handler import (
    InputHandlerMixin,
)
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    PolygonControlPointTarget,
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    format_dimension_distance,
)
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFontMetrics,
    QPainterPath,
    QPen,
    QTransform,
)
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
    BaseKeyHandler as _interaction_support_BaseKeyHandler,
    FakeColorService as _interaction_support_FakeColorService,
    FakeCoordinateSystem as _interaction_support_FakeCoordinateSystem,
    FakeItem as _interaction_support_FakeItem,
    FakeLinearGeom as _interaction_support_FakeLinearGeom,
    FakeSceneBuilder as _interaction_support_FakeSceneBuilder,
    InputHandlerHarness as _interaction_support_InputHandlerHarness,
    _app as _interaction_support__app,
    _path_has_curve as _interaction_support__path_has_curve,
)
from PySide6.QtCore import QPointF, Qt
import tests.presentation.components.plan_view.components.test_input_handler as fixtures
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
from ost_visualizer.domain.entities.annotation import BidAnnotation
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


class CtrlDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _make_pattern_resize_view(self, condition_type):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._color_service = _interaction_support_FakeColorService()
        view._linear_geom = _interaction_support_FakeLinearGeom()
        condition = Condition(
            uid="c1",
            condition_type=condition_type,
            pattern=pattern_values.HORIZONTAL,
            spacing=4.0,
            thickness=2.0,
            color_fill=1,
        )
        position = (
            [0.0, 0.0, 10.0, 0.0]
            if condition_type == Condition.TYPE_LINEAR
            else [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        )
        takeoff = SimpleNamespace(
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            position=list(position),
            is_hole=False,
            parent_uid=None,
        )
        main_path = QPainterPath()
        main_path.addRect(0.0, 0.0, 10.0, 10.0)
        main_item = QGraphicsPathItem(main_path)
        old_pattern = QGraphicsPathItem(main_path)
        view._scene.addItem(main_item)
        view._scene.addItem(old_pattern)
        view._current_takeoffs = {"t1": takeoff}
        view._current_annotations = {}
        view._current_conditions = {"c1": condition}
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._uid_to_items = {"t1": [main_item, old_pattern]}
        view._takeoff_items = [main_item, old_pattern]
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem()) for _ in range(8)
        ]
        view._drag_handle_index = 0
        view._drag_handle_corner_count = (
            0 if condition_type == Condition.TYPE_LINEAR else 4
        )
        view._drag_last_valid_new_pos = list(position)
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._selection_items = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        view._validate_hole_position = lambda *_args: True
        view._validate_parent_contains_holes = lambda *_args: True
        view._has_child_holes = lambda *_args: False
        return view, main_item, old_pattern

    def _make_hole_resize_view(self):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._color_service = _interaction_support_FakeColorService()
        view._linear_geom = _interaction_support_FakeLinearGeom()
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            pattern=pattern_values.TRANSPARENT,
            spacing=4.0,
            thickness=2.0,
            color_fill=1,
        )
        parent = Takeoff(
            uid="parent",
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        hole = Takeoff(
            uid="hole",
            condition_uid="c1",
            page_uid="page-1",
            area_uid="area-1",
            parent_uid="parent",
            position=[4.0, 4.0, 10.0, 4.0, 10.0, 10.0, 4.0, 10.0],
        )
        parent_path = QPainterPath()
        parent_path.addRect(0.0, 0.0, 20.0, 20.0)
        parent_item = QGraphicsPathItem(parent_path)
        hole_path = QPainterPath()
        hole_path.addRect(4.0, 4.0, 6.0, 6.0)
        hole_item = QGraphicsPathItem(hole_path)
        hole_item.setPen(QPen(Qt.PenStyle.NoPen))
        hole_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        stale_hole_pattern = QGraphicsPathItem(hole_path)
        stale_hole_pattern.setPen(QPen(QColor("#ff00ff")))
        for item in (parent_item, hole_item, stale_hole_pattern):
            view._scene.addItem(item)
        view._current_takeoffs = {"parent": parent, "hole": hole}
        view._current_annotations = {}
        view._current_conditions = {"c1": condition}
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._uid_to_items = {
            "parent": [parent_item],
            "hole": [hole_item, stale_hole_pattern],
        }
        view._takeoff_items = [parent_item, hole_item, stale_hole_pattern]
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem()) for _ in range(8)
        ]
        view._drag_handle_index = 2
        view._drag_handle_corner_count = 4
        view._drag_last_valid_new_pos = list(hole.position)
        view._drag_item_orig_positions = {}
        view._drag_item_orig_paths = {}
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {}
        view._drag_multi_orig_positions = {}
        view._selection_items = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        view._validate_hole_position = lambda *_args: True
        view._validate_parent_contains_holes = lambda *_args: True
        view._has_child_holes = lambda *_args: False
        view._refresh_condition_text_labels_for_takeoff = lambda _uid: None
        return view, parent_item, hole_item, stale_hole_pattern

    def _make_dimension_resize_view(self, position=None):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_color_map = {}
        view._takeoff_items = []
        view._selection_items = []
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        ann = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            position=list(position or [0.0, 0.0, 120.0, 0.0]),
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        renderer = AnnotationItemRenderer(view._scene_builder.get_coordinate_system())
        results, uid_to_items = renderer.create_all_annotation_items([("d1", ann)])
        items = uid_to_items["d1"]
        for item, _link in results:
            view._scene.addItem(item)
            view._takeoff_items.append(item)
        view._current_annotations = {"d1": ann}
        view._uid_to_items = {"d1": items}
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem()) for _ in range(2)
        ]
        view._drag_plan_item_uid = "d1"
        view._drag_handle_index = 1
        view._drag_handle_corner_count = 0
        view._drag_orig_position = list(ann.position)
        view._drag_item_orig_positions = {id(item): item.pos() for item in items}
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path())
            for item in items
            if isinstance(item, QGraphicsPathItem)
        }
        view._drag_item_orig_text_states = {
            id(item): (
                item.toPlainText(),
                item.textWidth(),
                item.rotation(),
                item.transformOriginPoint(),
                item.font(),
                item.defaultTextColor(),
            )
            for item in items
            if isinstance(item, QGraphicsTextItem)
        }
        view._drag_uid_orig_items = {"d1": list(items)}
        return view, ann

    def _make_area_annotation_resize_view(self, annotation_type):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._current_takeoffs = {}
        view._current_conditions = {}
        view._current_color_map = {}
        view._takeoff_items = []
        view._selection_items = []
        view._drag_multi_orig_positions = {}
        view._drag_last_valid_new_pos = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        ann = BidAnnotation(
            uid="a1",
            annotation_type=annotation_type,
            position=[0.0, 0.0, 60.0, 0.0, 60.0, 40.0, 0.0, 40.0],
            color="#ff0000",
        )
        renderer = AnnotationItemRenderer(view._scene_builder.get_coordinate_system())
        results, uid_to_items = renderer.create_all_annotation_items([("a1", ann)])
        items = uid_to_items["a1"]
        for item, _link in results:
            view._scene.addItem(item)
            view._takeoff_items.append(item)
        view._current_annotations = {"a1": ann}
        view._uid_to_items = {"a1": items}
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem()) for _ in range(8)
        ]
        view._drag_plan_item_uid = "a1"
        view._drag_handle_corner_count = 4
        view._drag_orig_position = list(ann.position)
        view._drag_last_valid_new_pos = list(ann.position)
        view._drag_item_orig_positions = {id(item): item.pos() for item in items}
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path())
            for item in items
            if isinstance(item, QGraphicsPathItem)
        }
        view._drag_item_orig_text_states = {}
        view._drag_uid_orig_items = {"a1": list(items)}
        return view, ann, items[0]

    def _handle_positions(self, view, count=None):
        infos = view._handle_infos if count is None else view._handle_infos[:count]
        return [(info.item.pos().x(), info.item.pos().y()) for info in infos]

    def _dimension_label_center(self, label):
        # Production anchors the label box (font-metric height, not document
        # layout height) so the center is independent of installed fonts.
        metrics_height = QFontMetrics(label.font()).height()
        return label.mapToScene(
            QtCore.QPointF(label.textWidth() / 2.0, metrics_height / 2.0)
        )

    def _dimension_label_offset(self, label):
        metrics_height = QFontMetrics(label.font()).height()
        return max(6.0, min(18.0, metrics_height * 0.45))

    def _dimension_label(self, view):
        for item in view._uid_to_items["d1"]:
            if isinstance(item, QGraphicsTextItem):
                return item
        self.fail("Dimension label item was not found")

    def _dimension_path(self, view):
        item = view._uid_to_items["d1"][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        return item

    def test_area_pattern_preview_refreshes_during_resize_drag(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        new_pos = [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertIsNone(old_pattern.scene())
        self.assertEqual(len(view._uid_to_items["t1"]), 2)
        self.assertIs(view._uid_to_items["t1"][0], main_item)
        new_pattern = view._uid_to_items["t1"][1]
        self.assertIsNot(new_pattern, old_pattern)
        self.assertIs(new_pattern.scene(), view._scene)
        self.assertEqual(new_pattern.data(0), "t1")
        self.assertEqual(new_pattern.data(1), "c1")
        self.assertEqual(view._takeoff_items, [main_item, new_pattern])
        self.assertEqual(
            main_item.path().boundingRect(), QtCore.QRectF(0.0, 0.0, 20.0, 12.0)
        )
        self.assertEqual(new_pattern.path().boundingRect().right(), 20.0)
        self.assertEqual(main_item.pen().color().name(), "#123456")
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)
        self.assertEqual(
            self._handle_positions(view),
            [
                (0.0, 0.0),
                (20.0, 0.0),
                (20.0, 12.0),
                (0.0, 12.0),
                (10.0, 0.0),
                (20.0, 6.0),
                (10.0, 12.0),
                (0.0, 6.0),
            ],
        )

    def test_inactive_area_resize_preview_uses_configured_appearance(self):
        new_pos = [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0]
        for page_area, inactive_color, expected in (
            ("area-2", None, "#d0d0d0"),
            ("area-2", "#aa0000", "#aa0000"),
            ("area-1", "#aa0000", "#00aa00"),
        ):
            with self.subTest(page_area=page_area, inactive_color=inactive_color):
                view, main_item, _old_pattern = self._make_pattern_resize_view(
                    Condition.TYPE_AREA
                )
                view._current_color_map = {"c1": "#00aa00"}
                view._current_page_area_selections = {"page-1": page_area}
                if inactive_color is not None:
                    view._inactive_object_color = inactive_color
                view.update_drag_handle_positions(new_pos, "t1")
                self.assertEqual(main_item.pen().color().name(), expected)
                new_pattern = view._uid_to_items["t1"][1]
                self.assertEqual(new_pattern.pen().color().name(), expected)

    def test_hole_resize_preview_keeps_child_item_invisible(self):
        view, parent_item, hole_item, stale_hole_pattern = self._make_hole_resize_view()
        new_pos = [4.0, 4.0, 10.0, 4.0, 14.0, 14.0, 4.0, 10.0]
        hole_item.setPen(QPen(QColor("#ff00ff")))
        hole_item.setBrush(QBrush(QColor("#00ff00")))
        view.update_drag_handle_positions(new_pos, "hole")
        self.assertEqual(hole_item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(hole_item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertEqual(
            hole_item.path().boundingRect(), QtCore.QRectF(4.0, 4.0, 10.0, 10.0)
        )
        self.assertEqual(view._uid_to_items["hole"], [hole_item])
        self.assertIsNone(stale_hole_pattern.scene())
        self.assertNotIn(stale_hole_pattern, view._takeoff_items)
        self.assertFalse(parent_item.path().contains(QtCore.QPointF(8.0, 8.0)))
        self.assertTrue(parent_item.path().contains(QtCore.QPointF(2.0, 2.0)))
        self.assertEqual(len(view._scene_builder.pattern_angles), 1)
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)
        self.assertEqual(
            self._handle_positions(view, 4),
            [(4.0, 4.0), (10.0, 4.0), (14.0, 14.0), (4.0, 10.0)],
        )

    def test_hole_resize_outside_parent_keeps_previous_valid_geometry(self):
        view, parent_item, hole_item, stale_hole_pattern = self._make_hole_resize_view()
        del view._validate_hole_position
        del view._validate_parent_contains_holes
        original_valid = list(view._drag_last_valid_new_pos)
        original_hole_bounds = hole_item.path().boundingRect()
        original_handles = self._handle_positions(view)
        view.update_drag_handle_positions(
            [4.0, 4.0, 10.0, 4.0, 24.0, 24.0, 4.0, 10.0], "hole"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(hole_item.path().boundingRect(), original_hole_bounds)
        self.assertIs(stale_hole_pattern.scene(), view._scene)
        self.assertTrue(parent_item.path().contains(QtCore.QPointF(8.0, 8.0)))
        self.assertEqual(view._scene_builder.pattern_angles, [])
        self.assertEqual(self._handle_positions(view), original_handles)
        inside = [4.0, 4.0, 10.0, 4.0, 14.0, 14.0, 4.0, 10.0]
        view.update_drag_handle_positions(inside, "hole")
        self.assertEqual(view._drag_last_valid_new_pos, inside)
        self.assertNotEqual(hole_item.path().boundingRect(), original_hole_bounds)

    def test_area_resize_preview_recenters_condition_labels(self):
        view, main_item, _old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        dimension_label = QGraphicsTextItem("10 SF")
        dimension_label.setData(0, "t1")
        dimension_label.setData(2, "condition_label")
        dimension_label.setData(3, "display_dimension")
        dimension_label.setPos(200.0, 200.0)
        name_label = QGraphicsTextItem("Area")
        name_label.setData(0, "t1")
        name_label.setData(2, "condition_label")
        name_label.setData(3, "display_name")
        name_label.setPos(200.0, 240.0)
        view._scene.addItem(dimension_label)
        view._scene.addItem(name_label)
        view._uid_to_items["t1"].extend([dimension_label, name_label])
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        dimension_bounds = dimension_label.boundingRect()
        dimension_center = QtCore.QPointF(
            dimension_label.pos().x() + dimension_bounds.width() / 2.0,
            dimension_label.pos().y() + dimension_bounds.height() / 2.0,
        )
        name_bounds = name_label.boundingRect()
        name_center_x = name_label.pos().x() + name_bounds.width() / 2.0
        self.assertEqual(main_item.path().boundingRect().center(), dimension_center)
        self.assertAlmostEqual(name_center_x, dimension_center.x())
        self.assertEqual(
            name_label.pos().y(),
            dimension_label.pos().y() + dimension_bounds.height() + 4.0,
        )

    def test_linear_pattern_preview_refreshes_during_resize_drag(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_LINEAR
        )
        view.update_drag_handle_positions([0.0, 0.0, 20.0, 0.0], "t1")
        self.assertIsNone(old_pattern.scene())
        self.assertEqual(len(view._uid_to_items["t1"]), 2)
        self.assertIs(view._uid_to_items["t1"][0], main_item)
        new_pattern = view._uid_to_items["t1"][1]
        self.assertIsNot(new_pattern, old_pattern)
        self.assertIs(new_pattern.scene(), view._scene)
        self.assertEqual(new_pattern.data(0), "t1")
        self.assertEqual(view._takeoff_items, [main_item, new_pattern])
        self.assertEqual(
            main_item.path().boundingRect(), QtCore.QRectF(0.0, -1.0, 20.0, 2.0)
        )
        self.assertEqual(new_pattern.path().boundingRect().right(), 20.0)
        self.assertEqual(view._scene_builder.pattern_angles, [0.0])
        self.assertEqual(self._handle_positions(view, 2), [(0.0, 0.0), (20.0, 0.0)])

    def test_diagonal_linear_pattern_preview_uses_drag_direction(self):
        for end_x, end_y, expected in (
            (20.0, 20.0, math.pi / 4.0),
            (-20.0, 20.0, 3.0 * math.pi / 4.0),
            (-20.0, -20.0, -3.0 * math.pi / 4.0),
            (20.0, -20.0, -math.pi / 4.0),
        ):
            with self.subTest(end=(end_x, end_y)):
                view, _main_item, _old_pattern = self._make_pattern_resize_view(
                    Condition.TYPE_LINEAR
                )
                view.update_drag_handle_positions([0.0, 0.0, end_x, end_y], "t1")
                self.assertEqual(len(view._scene_builder.pattern_angles), 1)
                self.assertAlmostEqual(view._scene_builder.pattern_angles[-1], expected)

    def test_axis_aligned_linear_pattern_preview_uses_drag_direction(self):
        for end_x, end_y, expected in (
            (0.0, 20.0, math.pi / 2.0),
            (-20.0, 0.0, math.pi),
            (0.0, -20.0, -math.pi / 2.0),
        ):
            with self.subTest(end=(end_x, end_y)):
                view, main_item, _old_pattern = self._make_pattern_resize_view(
                    Condition.TYPE_LINEAR
                )
                view.update_drag_handle_positions([0.0, 0.0, end_x, end_y], "t1")
                self.assertAlmostEqual(view._scene_builder.pattern_angles[-1], expected)
                bounds = main_item.path().boundingRect()
                self.assertAlmostEqual(max(bounds.width(), bounds.height()), 20.0)
                self.assertAlmostEqual(min(bounds.width(), bounds.height()), 2.0)

    def test_zero_length_linear_resize_preview_keeps_previous_path_and_pattern(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_LINEAR
        )
        original_bounds = main_item.path().boundingRect()
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 0.0], "t1")
        self.assertEqual(main_item.path().boundingRect(), original_bounds)
        self.assertIs(old_pattern.scene(), view._scene)
        self.assertEqual(view._uid_to_items["t1"], [main_item, old_pattern])
        self.assertEqual(view._scene_builder.pattern_angles, [])

    def test_area_invalid_resize_keeps_previous_valid_geometry(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_bounds = main_item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        original_handles = self._handle_positions(view)
        invalid_pos = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view.update_drag_handle_positions(invalid_pos, "t1")
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(main_item.path().boundingRect(), original_bounds)
        self.assertEqual(self._handle_positions(view), original_handles)
        self.assertIs(old_pattern.scene(), view._scene)
        self.assertEqual(view._uid_to_items["t1"], [main_item, old_pattern])
        self.assertEqual(view._scene_builder.pattern_angles, [])

    def test_area_resize_that_reverses_winding_keeps_previous_valid_geometry(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_valid = list(view._drag_last_valid_new_pos)
        original_bounds = main_item.path().boundingRect()
        reversed_square = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 0.0]
        view.update_drag_handle_positions(reversed_square, "t1")
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(main_item.path().boundingRect(), original_bounds)
        self.assertIs(old_pattern.scene(), view._scene)
        self.assertEqual(view._scene_builder.pattern_angles, [])

    def test_horizontal_bid_dimension_resize_updates_label_live(self):
        view, _ann = self._make_dimension_resize_view()
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        label = self._dimension_label(view)
        center = self._dimension_label_center(label)
        self.assertEqual(label.toPlainText(), format_dimension_distance(255.0))
        self.assertAlmostEqual(center.x(), 127.5, delta=0.5)
        self.assertAlmostEqual(
            center.y(), -self._dimension_label_offset(label), delta=0.01
        )
        path = self._dimension_path(view).path()
        self.assertEqual(path.elementCount(), 6)
        self.assertEqual(path.boundingRect(), QtCore.QRectF(0.0, -5.0, 255.0, 10.0))
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0), (255.0, 0.0)])

    def test_vertical_bid_dimension_resize_updates_label_live(self):
        view, _ann = self._make_dimension_resize_view([0.0, 0.0, 0.0, 60.0])
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 120.0], "d1")
        label = self._dimension_label(view)
        center = self._dimension_label_center(label)
        self.assertEqual(label.toPlainText(), "10' - 0\"")
        self.assertAlmostEqual(abs(label.rotation()), 90.0, delta=0.01)
        self.assertAlmostEqual(
            center.x(), self._dimension_label_offset(label), delta=0.01
        )
        self.assertAlmostEqual(center.y(), 60.0, delta=0.01)
        path = self._dimension_path(view).path()
        tick_start = path.elementAt(2)
        tick_end = path.elementAt(3)
        self.assertAlmostEqual(tick_start.y, tick_end.y)
        self.assertNotAlmostEqual(tick_start.x, tick_end.x)
        self.assertEqual(path.boundingRect(), QtCore.QRectF(-5.0, 0.0, 10.0, 120.0))

    def test_angled_bid_dimension_resize_updates_label_rotation_live(self):
        view, _ann = self._make_dimension_resize_view([0.0, 0.0, 36.0, 0.0])
        view.update_drag_handle_positions([0.0, 0.0, 36.0, 48.0], "d1")
        label = self._dimension_label(view)
        center = self._dimension_label_center(label)
        path = self._dimension_path(view).path()
        label_offset = self._dimension_label_offset(label)
        self.assertEqual(label.toPlainText(), "5' - 0\"")
        self.assertAlmostEqual(label.rotation(), 53.130102, places=3)
        # Unit normal of the (36, 48) dimension is (-0.8, 0.6); the label sits
        # one offset against it from the midpoint.
        self.assertAlmostEqual(center.x(), 18.0 + 0.8 * label_offset, delta=0.01)
        self.assertAlmostEqual(center.y(), 24.0 - 0.6 * label_offset, delta=0.01)
        self.assertEqual(path.elementAt(1).x, 36.0)
        self.assertEqual(path.elementAt(1).y, 48.0)

    def test_bid_dimension_commit_text_matches_last_preview(self):
        view, ann = self._make_dimension_resize_view()
        new_pos = [0.0, 0.0, 255.0, 0.0]
        view.update_drag_handle_positions(new_pos, "d1")
        ann.position = new_pos
        view._clear_drag_tracking()
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")
        self.assertEqual(ann.position, new_pos)

    def test_cancel_bid_dimension_resize_restores_label_and_path(self):
        view, ann = self._make_dimension_resize_view()
        label = self._dimension_label(view)
        original_label = label.toPlainText()
        original_pos = label.pos()
        original_rotation = label.rotation()
        original_path_bounds = self._dimension_path(view).path().boundingRect()
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")
        view._clear_drag_tracking(restore_preview=True)
        self.assertIs(self._dimension_label(view), label)
        self.assertEqual(label.toPlainText(), original_label)
        self.assertEqual(label.pos(), original_pos)
        self.assertEqual(label.rotation(), original_rotation)
        self.assertEqual(
            self._dimension_path(view).path().boundingRect(), original_path_bounds
        )
        self.assertEqual(ann.position, [0.0, 0.0, 120.0, 0.0])

    def test_repeated_bid_dimension_resize_preview_reuses_label_item(self):
        view, _ann = self._make_dimension_resize_view()
        original_items = list(view._uid_to_items["d1"])
        view.update_drag_handle_positions([0.0, 0.0, 180.0, 0.0], "d1")
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "d1")
        self.assertEqual(view._uid_to_items["d1"], original_items)
        self.assertEqual(self._dimension_label(view).toPlainText(), "21' - 3\"")

    def test_collapsed_bid_dimension_preview_removes_and_recreates_label(self):
        view, _ann = self._make_dimension_resize_view()
        original_label = self._dimension_label(view)
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 0.0], "d1")
        self.assertTrue(self._dimension_path(view).path().isEmpty())
        self.assertIsNone(original_label.scene())
        self.assertNotIn(original_label, view._uid_to_items["d1"])
        self.assertNotIn(original_label, view._takeoff_items)
        view.update_drag_handle_positions([0.0, 0.0, 120.0, 0.0], "d1")
        replacement_label = self._dimension_label(view)
        self.assertIsNot(replacement_label, original_label)
        self.assertEqual(
            replacement_label.toPlainText(), format_dimension_distance(120.0)
        )
        self.assertIs(replacement_label.scene(), view._scene)
        self.assertIn(replacement_label, view._takeoff_items)
        self.assertEqual(replacement_label.data(0), "d1")
        self.assertEqual(replacement_label.data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertTrue(
            replacement_label.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )

    def test_cancel_after_collapsed_bid_dimension_preview_restores_original_label(
        self,
    ):
        view, _ann = self._make_dimension_resize_view()
        original_label = self._dimension_label(view)
        original_text = original_label.toPlainText()
        original_path_bounds = self._dimension_path(view).path().boundingRect()
        view.update_drag_handle_positions([0.0, 0.0, 0.0, 0.0], "d1")
        self.assertIsNone(original_label.scene())
        view._clear_drag_tracking(restore_preview=True)
        self.assertIs(self._dimension_label(view), original_label)
        self.assertIs(original_label.scene(), view._scene)
        self.assertIn(original_label, view._takeoff_items)
        self.assertEqual(original_label.toPlainText(), original_text)
        self.assertEqual(
            self._dimension_path(view).path().boundingRect(), original_path_bounds
        )

    def test_bid_aline_resize_preview_remains_path_only(self):
        view, _ann = self._make_dimension_resize_view()
        line = BidAnnotation(
            uid="l1",
            annotation_type="line",
            position=[0.0, 0.0, 120.0, 0.0],
            color="#ff0000",
        )
        line_path = QPainterPath()
        line_path.moveTo(0.0, 0.0)
        line_path.lineTo(120.0, 0.0)
        line_item = QGraphicsPathItem(line_path)
        line_item.setData(0, "l1")
        view._scene.addItem(line_item)
        view._current_annotations = {"l1": line}
        view._uid_to_items = {"l1": [line_item]}
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem()) for _ in range(2)
        ]
        view._drag_handle_index = 1
        view.update_drag_handle_positions([0.0, 0.0, 255.0, 0.0], "l1")
        self.assertEqual(view._uid_to_items["l1"], [line_item])
        self.assertEqual(len(view._scene.items()), len(view._takeoff_items) + 1)
        path = line_item.path()
        self.assertEqual(path.elementCount(), 2)
        self.assertEqual((path.elementAt(0).x, path.elementAt(0).y), (0.0, 0.0))
        self.assertEqual((path.elementAt(1).x, path.elementAt(1).y), (255.0, 0.0))
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0), (255.0, 0.0)])

    def test_cloud_resize_preview_from_corner_keeps_cloud_silhouette(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_position = list(ann.position)
        original_bounds = item.path().boundingRect()
        self.assertTrue(_interaction_support__path_has_curve(item.path()))
        view._drag_handle_index = 2
        new_pos = [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0]
        view.update_drag_handle_positions(new_pos, "a1")
        self.assertTrue(_interaction_support__path_has_curve(item.path()))
        bounds = item.path().boundingRect()
        self.assertGreater(bounds.width(), original_bounds.width())
        self.assertGreater(bounds.height(), original_bounds.height())
        self.assertGreater(bounds.right(), 80.0)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)
        self.assertEqual(
            self._handle_positions(view),
            [
                (0.0, 0.0),
                (80.0, 0.0),
                (80.0, 50.0),
                (0.0, 40.0),
                (40.0, 0.0),
                (80.0, 25.0),
                (40.0, 45.0),
                (0.0, 20.0),
            ],
        )

    def test_cloud_resize_preview_from_midpoint_keeps_cloud_silhouette(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_position = list(ann.position)
        original_bounds = item.path().boundingRect()
        self.assertTrue(_interaction_support__path_has_curve(item.path()))
        view._drag_handle_index = 5
        new_pos = [0.0, 0.0, 60.0, 0.0, 70.0, 50.0, -10.0, 50.0]
        view.update_drag_handle_positions(new_pos, "a1")
        self.assertTrue(_interaction_support__path_has_curve(item.path()))
        bounds = item.path().boundingRect()
        self.assertGreater(bounds.height(), original_bounds.height())
        self.assertLess(bounds.left(), -10.0)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)
        self.assertEqual(
            self._handle_positions(view),
            [
                (0.0, 0.0),
                (60.0, 0.0),
                (70.0, 50.0),
                (-10.0, 50.0),
                (30.0, 0.0),
                (65.0, 25.0),
                (30.0, 50.0),
                (-5.0, 25.0),
            ],
        )

    def test_polygon_point_edit_cannot_create_self_intersection(self):
        view, ann, item = self._make_area_annotation_resize_view("polygon")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        original_position = list(ann.position)
        original_handles = self._handle_positions(view)
        view._drag_handle_index = 1
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(self._handle_positions(view), original_handles)
        self.assertFalse(_interaction_support__path_has_curve(item.path()))

    def test_cloud_point_edit_cannot_create_self_intersection(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        original_position = list(ann.position)
        original_handles = self._handle_positions(view)
        view._drag_handle_index = 1
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(self._handle_positions(view), original_handles)
        self.assertTrue(_interaction_support__path_has_curve(item.path()))

    def test_polygon_corner_resize_cannot_create_invalid_geometry(self):
        view, ann, item = self._make_area_annotation_resize_view("polygon")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        original_position = list(ann.position)
        original_handles = self._handle_positions(view)
        view._drag_handle_index = 2
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(self._handle_positions(view), original_handles)
        self.assertFalse(_interaction_support__path_has_curve(item.path()))

    def test_cloud_midpoint_resize_cannot_create_invalid_geometry(self):
        view, ann, item = self._make_area_annotation_resize_view("cloud")
        original_bounds = item.path().boundingRect()
        original_valid = list(view._drag_last_valid_new_pos)
        original_position = list(ann.position)
        original_handles = self._handle_positions(view)
        view._drag_handle_index = 5
        view.update_drag_handle_positions(
            [0.0, 0.0, 60.0, 40.0, 60.0, 0.0, 0.0, 40.0], "a1"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original_valid)
        self.assertEqual(item.path().boundingRect(), original_bounds)
        self.assertEqual(ann.position, original_position)
        self.assertEqual(self._handle_positions(view), original_handles)
        self.assertTrue(_interaction_support__path_has_curve(item.path()))

    def test_valid_polygon_and_cloud_edits_update_last_valid_geometry(self):
        valid_pos = [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view, ann, item = self._make_area_annotation_resize_view(
                    annotation_type
                )
                original_bounds = item.path().boundingRect()
                original_position = list(ann.position)
                view._drag_handle_index = 2
                view.update_drag_handle_positions(valid_pos, "a1")
                self.assertEqual(view._drag_last_valid_new_pos, valid_pos)
                self.assertNotEqual(item.path().boundingRect(), original_bounds)
                self.assertEqual(ann.position, original_position)
                self.assertEqual(
                    self._handle_positions(view),
                    [
                        (0.0, 0.0),
                        (80.0, 0.0),
                        (80.0, 50.0),
                        (0.0, 40.0),
                        (40.0, 0.0),
                        (80.0, 25.0),
                        (40.0, 45.0),
                        (0.0, 20.0),
                    ],
                )

    def test_polygon_and_cloud_edits_that_reverse_winding_keep_previous_geometry(
        self,
    ):
        reversed_rectangle = [0.0, 0.0, 0.0, 40.0, 60.0, 40.0, 60.0, 0.0]
        for annotation_type in ("polygon", "cloud"):
            with self.subTest(annotation_type=annotation_type):
                view, _ann, item = self._make_area_annotation_resize_view(
                    annotation_type
                )
                original_bounds = item.path().boundingRect()
                original_valid = list(view._drag_last_valid_new_pos)
                view._drag_handle_index = 2
                view.update_drag_handle_positions(reversed_rectangle, "a1")
                self.assertEqual(view._drag_last_valid_new_pos, original_valid)
                self.assertEqual(item.path().boundingRect(), original_bounds)

    def test_polygon_resize_preview_stays_straight_polygon(self):
        view, ann, item = self._make_area_annotation_resize_view("polygon")
        original_position = list(ann.position)
        self.assertFalse(_interaction_support__path_has_curve(item.path()))
        view._drag_handle_index = 2
        new_pos = [0.0, 0.0, 80.0, 0.0, 80.0, 50.0, 0.0, 40.0]
        view.update_drag_handle_positions(new_pos, "a1")
        self.assertFalse(_interaction_support__path_has_curve(item.path()))
        self.assertEqual(
            item.path().boundingRect(), QtCore.QRectF(0.0, 0.0, 80.0, 50.0)
        )
        self.assertEqual(ann.position, original_position)
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)

    def test_cancel_resize_restores_original_pattern_items(self):
        view, main_item, old_pattern = self._make_pattern_resize_view(
            Condition.TYPE_AREA
        )
        original_bounds = main_item.path().boundingRect()
        original_pattern_bounds = old_pattern.path().boundingRect()
        view._drag_plan_item_uid = "t1"
        view._drag_item_orig_paths = {
            id(item): QPainterPath(item.path()) for item in view._uid_to_items["t1"]
        }
        view._drag_uid_orig_items = {"t1": list(view._uid_to_items["t1"])}
        view.update_drag_handle_positions(
            [0.0, 0.0, 20.0, 0.0, 20.0, 12.0, 0.0, 12.0], "t1"
        )
        new_pattern = view._uid_to_items["t1"][1]
        self.assertIsNot(new_pattern, old_pattern)
        self.assertIsNone(old_pattern.scene())
        view._clear_drag_tracking(restore_preview=True)
        self.assertIsNone(new_pattern.scene())
        self.assertIs(old_pattern.scene(), view._scene)
        self.assertEqual(view._uid_to_items["t1"], [main_item, old_pattern])
        self.assertEqual(view._takeoff_items, [main_item, old_pattern])
        self.assertEqual(main_item.path().boundingRect(), original_bounds)
        self.assertEqual(old_pattern.path().boundingRect(), original_pattern_bounds)


class AttachmentMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = fixtures._app()

    def make_view(self):
        view = fixtures.CtrlDragTests()._make_view({"attachment"})
        view._scene_builder = fixtures.FakeSceneBuilder()
        view._scene_builder.cs = fixtures.IdentityCoordinateSystem()
        view._linear_geom = fixtures.FakeLinearGeom()
        view._rotation_before_edit = {}
        view._dirty_rotations = {}
        view._current_conditions = {
            "area": Condition(uid="area", condition_type=Condition.TYPE_AREA),
            "attachment": Condition(
                uid="attachment", condition_type=Condition.TYPE_ATTACHMENT
            ),
        }
        view._current_takeoffs = {
            "parent": Takeoff(
                uid="parent",
                condition_uid="area",
                page_uid="page",
                position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
            ),
            "attachment": Takeoff(
                uid="attachment",
                condition_uid="attachment",
                page_uid="page",
                parent_uid="parent",
                position=[5.0, 5.0],
                area_uid="bid-area",
            ),
        }
        view._uid_to_items = {"attachment": [fixtures.FakeItem()]}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem(5.0, 5.0))]
        view._pt_to_scene = lambda x, y: QPointF(x, y)
        return view

    def add_backout(self, view, position):
        view._current_takeoffs["backout"] = Takeoff(
            uid="backout",
            condition_uid="area",
            page_uid="page",
            parent_uid="parent",
            position=list(position),
        )

    def test_nested_backout_vertex_edit_cannot_exclude_its_child(self):
        view = self.make_view()
        del view._current_takeoffs["attachment"]
        self.add_backout(view, [1, 1, 9, 1, 9, 9, 1, 9])
        view._current_takeoffs["nested"] = Takeoff(
            uid="nested",
            condition_uid="area",
            page_uid="page",
            parent_uid="backout",
            position=[7, 7, 8, 7, 8, 8, 7, 8],
        )
        original = list(view._current_takeoffs["backout"].position)
        view._drag_last_valid_new_pos = original
        view._drag_handle_index = 2
        view._uid_to_items = {}
        view._handle_infos = [SimpleNamespace(item=fixtures.FakeItem())]
        view.update_drag_handle_positions([1, 1, 9, 1, 5, 5, 1, 9], "backout")
        self.assertEqual(view._drag_last_valid_new_pos, original)
        self.assertEqual(view._handle_infos[0].item.pos(), QPointF(0.0, 0.0))
        still_containing = [1, 1, 9, 1, 8.5, 8.5, 1, 9]
        view.update_drag_handle_positions(still_containing, "backout")
        self.assertEqual(view._drag_last_valid_new_pos, still_containing)
        self.assertEqual(view._handle_infos[0].item.pos(), QPointF(1.0, 1.0))

    def test_mouse_preview_collides_at_every_edge(self):
        for position in ([-1.0, 5.0], [11.0, 5.0], [5.0, -1.0], [5.0, 11.0]):
            with self.subTest(position=position):
                view = self.make_view()
                view._drag_last_valid_new_pos = [5.0, 5.0]
                view.update_drag_handle_positions(position, "attachment")
                self.assertEqual(view._handle_infos[0].item.pos(), QPointF(5.0, 5.0))
                self.assertEqual(view._drag_last_valid_new_pos, [5.0, 5.0])
        view = self.make_view()
        view._drag_last_valid_new_pos = [5.0, 5.0]
        view.update_drag_handle_positions([6.0, 4.0], "attachment")
        self.assertEqual(view._drag_last_valid_new_pos, [6.0, 4.0])
        self.assertEqual(view._handle_infos[0].item.pos(), QPointF(6.0, 4.0))

    def test_parent_resize_cannot_exclude_attachment(self):
        view = self.make_view()
        self.assertFalse(
            view._validate_parent_contains_holes(
                "parent", [0.0, 0.0, 3.0, 0.0, 3.0, 3.0, 0.0, 3.0]
            )
        )
        self.assertTrue(
            view._validate_parent_contains_holes(
                "parent", [0.0, 0.0, 8.0, 0.0, 8.0, 8.0, 0.0, 8.0]
            )
        )
        original = list(view._current_takeoffs["parent"].position)
        view._uid_to_items = {}
        view._drag_handle_index = 2
        view._drag_handle_corner_count = 4
        view._drag_last_valid_new_pos = list(original)
        view.update_drag_handle_positions(
            [0.0, 0.0, 3.0, 0.0, 3.0, 3.0, 0.0, 3.0], "parent"
        )
        self.assertEqual(view._drag_last_valid_new_pos, original)
        self.assertEqual(view._handle_infos[0].item.pos(), QPointF(5.0, 5.0))
        enlarged = [0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0]
        view.update_drag_handle_positions(enlarged, "parent")
        self.assertEqual(view._drag_last_valid_new_pos, enlarged)


class PlanViewInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_text_annotation_resize_preview_updates_outline_and_handles(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = QGraphicsTextItem("Before")
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        view._drag_handle_index = 0
        cs = view._scene_builder.get_coordinate_system()
        view._update_ann_drag(annotation, [100.0, 100.0, 120.0, 60.0], "a1", cs, 0, 0)
        self.assertEqual(item.pos(), QtCore.QPointF(40.0, 70.0))
        self.assertEqual(item.textWidth(), 120.0)
        self.assertEqual(view._drag_last_valid_new_pos, [100.0, 100.0, 120.0, 60.0])
        outline = self._first_selection_outline(view)
        self.assertEqual(
            outline.polygon().boundingRect(),
            QtCore.QRectF(40.0, 70.0, 120.0, 60.0),
        )
        handle_positions = [info.item.pos() for info in view._handle_infos[:4]]
        self.assertEqual(
            handle_positions,
            [
                QtCore.QPointF(40.0, 70.0),
                QtCore.QPointF(160.0, 70.0),
                QtCore.QPointF(160.0, 130.0),
                QtCore.QPointF(40.0, 130.0),
            ],
        )
        view.cleanup()

    def test_text_annotation_resize_preview_updates_clip_rect(self):
        view = self._make_plan_view()
        annotation = BidAnnotation(
            uid="a1",
            annotation_type="text",
            position=[100.0, 100.0, 80.0, 40.0],
            properties={"Text": "Before", "FontColor": 0, "FontSize": 12},
        )
        item = ClippedTextGraphicsItem("Before", QtCore.QRectF(0.0, 0.0, 80.0, 40.0))
        item.setData(0, "a1")
        view._scene.addItem(item)
        view._uid_to_items = {"a1": [item]}
        view._current_annotations = {"a1": annotation}
        view._selected_uids = {"a1"}
        view.update_selection_visuals(emit=False)
        view._drag_handle_index = 0
        cs = view._scene_builder.get_coordinate_system()
        view._update_ann_drag(annotation, [100.0, 100.0, 120.0, 60.0], "a1", cs, 0, 0)
        self.assertEqual(item.pos(), QtCore.QPointF(40.0, 70.0))
        self.assertEqual(item.textWidth(), 120.0)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(0.0, 0.0, 120.0, 60.0))
        view.cleanup()

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
