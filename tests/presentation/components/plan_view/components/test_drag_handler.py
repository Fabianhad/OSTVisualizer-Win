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


from ost_visualizer.presentation.components.plan_view.components import (
    drag_handler as drag_handler_module,
)


class _DragMath(DragHandlerMixin):
    """DragHandlerMixin with only the collaborators the pure maths touches."""

    def __init__(
        self, snap_increments=0.0, transform=None, scale_ratio=72.0, view_scale=1.0
    ):
        self._snap_increments = snap_increments
        self._transform = transform
        self._cs = SimpleNamespace(scale_ratio=scale_ratio, view_scale=view_scale)
        self._scene_builder = SimpleNamespace(get_coordinate_system=lambda: self._cs)
        self._drag_last_valid_new_pos = []
        self.snap_angle_calls = []
        self.snap_angle_result = lambda _ox, _oy, tx, ty: (tx, ty)

    def _current_page_transform(self):
        return self._transform

    def _snap_angle(self, origin_x, origin_y, target_x, target_y):
        self.snap_angle_calls.append((origin_x, origin_y, target_x, target_y))
        return self.snap_angle_result(origin_x, origin_y, target_x, target_y)


class LineLineIntersectTests(unittest.TestCase):
    def assertPoint(self, actual, expected):
        self.assertIsNotNone(actual)
        self.assertAlmostEqual(actual[0], expected[0], places=9)
        self.assertAlmostEqual(actual[1], expected[1], places=9)

    def test_axis_aligned_lines_meet_at_the_expected_point(self):
        point = drag_handler_module._line_line_intersect(
            0.0, 0.0, 1.0, 0.0, 5.0, -3.0, 0.0, 1.0
        )
        self.assertPoint(point, (5.0, 0.0))

    def test_oblique_lines_with_non_unit_directions_meet_on_both_lines(self):
        # (1,1)+t(2,1) meets (0,5)+s(1,-1) at t=1, s=3 -> (3,2).
        point = drag_handler_module._line_line_intersect(
            1.0, 1.0, 2.0, 1.0, 0.0, 5.0, 1.0, -1.0
        )
        self.assertPoint(point, (3.0, 2.0))
        # Swapping the lines gives the same point.
        swapped = drag_handler_module._line_line_intersect(
            0.0, 5.0, 1.0, -1.0, 1.0, 1.0, 2.0, 1.0
        )
        self.assertPoint(swapped, (3.0, 2.0))

    def test_intersection_is_found_outside_both_direction_segments(self):
        point = drag_handler_module._line_line_intersect(
            0.0, 0.0, 1.0, 1.0, 10.0, 0.0, 0.0, 1.0
        )
        self.assertPoint(point, (10.0, 10.0))
        behind = drag_handler_module._line_line_intersect(
            0.0, 0.0, 1.0, 0.0, -4.0, 7.0, 0.0, -1.0
        )
        self.assertPoint(behind, (-4.0, 0.0))

    def test_parallel_and_near_parallel_lines_have_no_intersection(self):
        self.assertIsNone(
            drag_handler_module._line_line_intersect(
                0.0, 0.0, 1.0, 0.0, 0.0, 5.0, 2.0, 0.0
            )
        )
        self.assertIsNone(
            drag_handler_module._line_line_intersect(
                0.0, 0.0, 1.0, 0.0, 0.0, 5.0, 1.0, 5e-13
            )
        )

    def test_determinant_threshold_is_exclusive_at_one_picounit(self):
        # det == 1e-12 exactly is still solvable; just below it is not.
        self.assertIsNotNone(
            drag_handler_module._line_line_intersect(
                0.0, 0.0, 1.0, 0.0, 0.0, 5.0, 1.0, 1e-12
            )
        )
        self.assertIsNotNone(
            drag_handler_module._line_line_intersect(
                0.0, 0.0, 1.0, 0.0, 0.0, 5.0, 1.0, 1.5e-12
            )
        )
        self.assertIsNone(
            drag_handler_module._line_line_intersect(
                0.0, 0.0, 1.0, 0.0, 0.0, 5.0, 1.0, 9e-13
            )
        )


class DragHandlerPathAndValidityTests(unittest.TestCase):
    @staticmethod
    def _elements(path):
        return [
            (path.elementAt(i).type, path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())
        ]

    def test_area_annotation_path_is_empty_without_points(self):
        self.assertTrue(
            _DragMath()
            ._build_area_annotation_path(ANNOTATION_TYPE_POLYGON, [])
            .isEmpty()
        )

    def test_polygon_path_is_a_closed_straight_outline_from_three_points(self):
        move, line = (
            QPainterPath.ElementType.MoveToElement,
            QPainterPath.ElementType.LineToElement,
        )
        path = _DragMath()._build_area_annotation_path(
            ANNOTATION_TYPE_POLYGON, [(1.0, 2.0), (11.0, 2.0), (11.0, 9.0)]
        )
        self.assertEqual(
            self._elements(path),
            [(move, 1.0, 2.0), (line, 11.0, 2.0), (line, 11.0, 9.0), (line, 1.0, 2.0)],
        )

    def test_two_point_path_is_an_open_line_for_polygons_and_clouds(self):
        move, line = (
            QPainterPath.ElementType.MoveToElement,
            QPainterPath.ElementType.LineToElement,
        )
        for annotation_type in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD):
            with self.subTest(annotation_type=annotation_type):
                path = _DragMath()._build_area_annotation_path(
                    annotation_type, [(1.0, 2.0), (11.0, 5.0)]
                )
                self.assertEqual(
                    self._elements(path), [(move, 1.0, 2.0), (line, 11.0, 5.0)]
                )

    def test_cloud_path_uses_one_subpath_of_curves_closed_back_to_the_start(self):
        points = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
        path = _DragMath()._build_area_annotation_path(ANNOTATION_TYPE_CLOUD, points)
        types = [element[0] for element in self._elements(path)]
        self.assertEqual(types.count(QPainterPath.ElementType.MoveToElement), 1)
        self.assertEqual(types[0], QPainterPath.ElementType.MoveToElement)
        self.assertGreaterEqual(types.count(QPainterPath.ElementType.CurveToElement), 4)
        first = path.elementAt(0)
        self.assertEqual((first.x, first.y), (0.0, 0.0))
        self.assertTrue(path.boundingRect().contains(QtCore.QPointF(20.0, 15.0)))

    def test_non_cloud_annotation_types_never_curve_even_with_many_points(self):
        points = [(0.0, 0.0), (40.0, 0.0), (40.0, 30.0), (0.0, 30.0)]
        path = _DragMath()._build_area_annotation_path(ANNOTATION_TYPE_POLYGON, points)
        self.assertFalse(_interaction_support__path_has_curve(path))
        self.assertEqual(path.boundingRect(), QtCore.QRectF(0.0, 0.0, 40.0, 30.0))

    def test_polygon_edit_requires_three_valid_points_and_stable_winding(self):
        handler = _DragMath()
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        reversed_square = [0.0, 10.0, 10.0, 10.0, 10.0, 0.0, 0.0, 0.0]
        bow_tie = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]

        def points(flat):
            return list(zip(flat[0::2], flat[1::2]))

        self.assertTrue(handler._polygon_edit_geometry_valid(square, points(square)))
        self.assertFalse(
            handler._polygon_edit_geometry_valid(square[:4], points(square[:4]))
        )
        self.assertFalse(handler._polygon_edit_geometry_valid(bow_tie, points(bow_tie)))
        handler._drag_last_valid_new_pos = list(square)
        self.assertTrue(handler._polygon_edit_geometry_valid(square, points(square)))
        self.assertFalse(
            handler._polygon_edit_geometry_valid(
                reversed_square, points(reversed_square)
            )
        )
        handler._drag_last_valid_new_pos = list(reversed_square)
        self.assertTrue(
            handler._polygon_edit_geometry_valid(
                reversed_square, points(reversed_square)
            )
        )
        self.assertFalse(handler._polygon_edit_geometry_valid(square, points(square)))

    def test_polygon_edit_ignores_winding_when_the_previous_area_is_zero(self):
        handler = _DragMath()
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        flat_previous = [0.0, 0.0, 5.0, 0.0, 10.0, 0.0]
        handler._drag_last_valid_new_pos = flat_previous
        self.assertTrue(
            handler._polygon_edit_geometry_valid(
                square, list(zip(square[0::2], square[1::2]))
            )
        )


class DragHandlerSnapAndDeltaTests(unittest.TestCase):
    def test_snap_ost_rounds_to_the_increment_and_ignores_non_positive_increments(self):
        for increment, value, expected in (
            (0.0, 12.4, 12.4),
            (-5.0, 12.4, 12.4),
            (5.0, 12.4, 10.0),
            (5.0, 12.6, 15.0),
            (5.0, -12.6, -15.0),
            (5.0, 0.0, 0.0),
            (0.25, 1.1, 1.0),
            (0.25, 1.2, 1.25),
        ):
            with self.subTest(increment=increment, value=value):
                self.assertAlmostEqual(
                    _DragMath(snap_increments=increment).snap_ost(value),
                    expected,
                    places=9,
                )

    def test_positions_meaningfully_different_uses_a_nano_unit_tolerance(self):
        different = DragHandlerMixin._positions_meaningfully_different
        self.assertFalse(different([], []))
        self.assertFalse(different([1.0, 2.0], [1.0, 2.0]))
        self.assertFalse(different([1.0, 2.0], [1.0 + 5e-10, 2.0 - 5e-10]))
        self.assertTrue(different([1.0, 2.0], [1.0, 2.0 + 1.5e-9]))
        self.assertTrue(different([1.0, 2.0], [1.0, 3.0]))
        self.assertTrue(different([1.0, 2.0], [0.0, 2.0]))
        self.assertTrue(different([1.0, 2.0], [1.0, 2.0, 3.0]))
        self.assertTrue(different([1.0, 2.0, 3.0], [1.0, 2.0]))
        # Tolerance is absolute, not relative: huge values do not widen it.
        self.assertTrue(different([1e9], [1e9 + 1e-3]))

    def test_scene_to_ost_delta_scales_by_the_pdf_ratio_without_a_page_transform(self):
        handler = _DragMath(scale_ratio=36.0, view_scale=1.0)
        self.assertEqual(handler.scene_to_ost_delta(6.0, 8.0), (3.0, 4.0))
        handler = _DragMath(scale_ratio=36.0, view_scale=2.0)
        self.assertEqual(handler.scene_to_ost_delta(6.0, 8.0), (1.5, 2.0))

    def test_ost_to_scene_delta_scales_by_the_pdf_ratio_without_a_page_transform(self):
        handler = _DragMath(scale_ratio=36.0, view_scale=1.0)
        self.assertEqual(handler.ost_to_scene_delta(3.0, 4.0), (6.0, 8.0))
        handler = _DragMath(scale_ratio=36.0, view_scale=2.0)
        self.assertEqual(handler.ost_to_scene_delta(3.0, 4.0), (12.0, 16.0))

    def test_page_transform_is_applied_linearly_ignoring_its_translation(self):
        transform = QTransform().translate(100.0, 50.0).scale(2.0, 4.0)
        handler = _DragMath(transform=transform)
        self.assertEqual(handler.ost_to_scene_delta(3.0, 5.0), (6.0, 20.0))
        self.assertEqual(handler.scene_to_ost_delta(6.0, 20.0), (3.0, 5.0))

    def test_page_rotation_mixes_the_axes_in_both_directions(self):
        transform = QTransform().translate(10.0, 20.0).rotate(90.0)
        handler = _DragMath(transform=transform)
        sdx, sdy = handler.ost_to_scene_delta(3.0, 5.0)
        self.assertAlmostEqual(sdx, -5.0, places=9)
        self.assertAlmostEqual(sdy, 3.0, places=9)
        dx, dy = handler.scene_to_ost_delta(-5.0, 3.0)
        self.assertAlmostEqual(dx, 3.0, places=9)
        self.assertAlmostEqual(dy, 5.0, places=9)

    def test_non_invertible_page_transform_leaves_scene_deltas_unmapped(self):
        handler = _DragMath(transform=QTransform().scale(0.0, 0.0), scale_ratio=36.0)
        self.assertEqual(handler.scene_to_ost_delta(6.0, 8.0), (3.0, 4.0))


class ComputeNewPositionTests(unittest.TestCase):
    def assertPos(self, actual, expected):
        self.assertEqual(len(actual), len(expected), msg=repr(actual))
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(
                a, e, places=6, msg="index %d: %r vs %r" % (index, actual, expected)
            )

    def test_body_drag_translates_every_point_and_keeps_trailing_values(self):
        handler = _DragMath()
        self.assertPos(
            handler.compute_new_position(
                [0.0, 0.0, 10.0, 0.0, 10.0, 10.0], 3.0, 4.0, -1, 0
            ),
            [3.0, 4.0, 13.0, 4.0, 13.0, 14.0],
        )
        self.assertPos(
            handler.compute_new_position(
                [0.0, 0.0, 10.0, 0.0, 5.0, 3.0, 0.5], 3.0, 4.0, -1, 0
            ),
            [3.0, 4.0, 13.0, 4.0, 8.0, 7.0, 0.5],
        )

    def test_body_drag_can_move_only_the_first_point_pair(self):
        handler = _DragMath()
        self.assertPos(
            handler.compute_new_position(
                [0.0, 0.0, 10.0, 0.0], 3.0, 4.0, -1, 0, move_only_first_pair=True
            ),
            [3.0, 4.0, 10.0, 0.0],
        )

    def test_body_drag_snaps_the_first_point_and_applies_the_same_delta_to_all(self):
        handler = _DragMath(snap_increments=5.0)
        self.assertPos(
            handler.compute_new_position([1.0, 2.0, 11.0, 2.0], 3.0, 4.0, -1, 0),
            [5.0, 5.0, 15.0, 5.0],
        )

    def test_body_drag_does_not_modify_its_input(self):
        original = [0.0, 0.0, 10.0, 0.0]
        _DragMath().compute_new_position(original, 3.0, 4.0, -1, 0)
        self.assertEqual(original, [0.0, 0.0, 10.0, 0.0])

    def test_free_edge_drag_moves_both_corners_by_the_angle_snapped_delta(self):
        handler = _DragMath()
        handler.snap_angle_result = lambda _ox, _oy, tx, ty: (tx + 1.0, ty + 2.0)
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(square, 3.0, 4.0, 7, 4, free_mode=True)
        self.assertPos(result, [4.0, 6.0, 10.0, 0.0, 10.0, 10.0, 4.0, 16.0])
        self.assertEqual(handler.snap_angle_calls, [(0.0, 0.0, 3.0, 4.0)])

    def test_edge_drag_of_a_two_corner_shape_is_always_free(self):
        handler = _DragMath(snap_increments=0.5)
        result = handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 1.2, 1.3, 2, 2)
        self.assertPos(result, [1.0, 1.5, 11.0, 1.5])
        self.assertEqual(handler.snap_angle_calls, [(0.0, 0.0, 1.2, 1.3)])

    def test_constrained_edge_resize_slides_the_edge_along_its_neighbours(self):
        handler = _DragMath()
        trapezoid = [0.0, 0.0, 10.0, 0.0, 8.0, 10.0, 2.0, 10.0]
        result = handler.compute_new_position(trapezoid, 5.0, 2.0, 4, 4)
        self.assertPos(result, [0.4, 2.0, 9.6, 2.0, 8.0, 10.0, 2.0, 10.0])
        self.assertEqual(handler.snap_angle_calls, [])
        # Edge 1 (right side) moved along its own normal: both ends stay on the
        # neighbouring edges y=0 and y=10, shifted 3.2 units to the right.
        result = handler.compute_new_position(trapezoid, 3.0, 1.0, 5, 4)
        self.assertPos(result, [0.0, 0.0, 13.2, 0.0, 11.2, 10.0, 2.0, 10.0])

    def test_constrained_edge_resize_snaps_the_new_corners(self):
        handler = _DragMath(snap_increments=0.5)
        trapezoid = [0.0, 0.0, 10.0, 0.0, 8.0, 10.0, 2.0, 10.0]
        result = handler.compute_new_position(trapezoid, 5.0, 2.0, 4, 4)
        self.assertPos(result, [0.5, 2.0, 9.5, 2.0, 8.0, 10.0, 2.0, 10.0])

    def test_constrained_edge_resize_keeps_the_start_corner_when_the_previous_edge_is_parallel(
        self,
    ):
        handler = _DragMath()
        pos = [0.0, 0.0, 5.0, 0.0, 10.0, 0.0, 10.0, 10.0]
        result = handler.compute_new_position(pos, 0.0, 2.0, 5, 4)
        self.assertPos(result, [0.0, 0.0, 5.0, 0.0, 10.0, 2.0, 10.0, 10.0])

    def test_constrained_edge_resize_keeps_the_end_corner_when_the_next_edge_is_parallel(
        self,
    ):
        handler = _DragMath()
        pos = [0.0, 10.0, 10.0, 10.0, 15.0, 10.0, 15.0, 0.0]
        # Edge 0 (0,10)-(10,10): the previous edge (15,0)->(0,10) is oblique, so its
        # corner slides to (3, 8); the next edge (10,10)->(15,10) is parallel.
        result = handler.compute_new_position(pos, 0.0, -2.0, 4, 4)
        self.assertPos(result, [3.0, 8.0, 10.0, 10.0, 15.0, 10.0, 15.0, 0.0])

    def test_constrained_edge_resize_ignores_a_zero_length_edge(self):
        handler = _DragMath()
        pos = [0.0, 0.0, 10.0, 0.0, 10.0, 0.0, 0.0, 10.0]
        result = handler.compute_new_position(pos, 3.0, 4.0, 5, 4)
        self.assertPos(result, pos)

    def test_curve_control_handle_moves_along_the_chord_normal(self):
        handler = _DragMath()
        result = handler.compute_new_position(
            [0.0, 0.0, 6.0, 8.0, 5.0, 3.0], 5.0, 10.0, 2, 0
        )
        # chord direction (0.6, 0.8), normal (-0.8, 0.6): projection = -4 + 6 = 2.
        self.assertPos(result, [0.0, 0.0, 6.0, 8.0, 3.4, 4.2])

    def test_curve_control_handle_with_a_bulge_value_updates_the_bulge(self):
        handler = _DragMath()
        result = handler.compute_new_position(
            [0.0, 0.0, 6.0, 8.0, 5.0, 3.0, 0.5], 5.0, 10.0, 2, 0
        )
        # bulge 0.5 - 2 = -1.5 puts the control point 1.5 along the normal from
        # the chord midpoint (3, 4).
        self.assertPos(result, [0.0, 0.0, 6.0, 8.0, 1.8, 4.9, -1.5])

    def test_curve_control_handle_on_a_degenerate_chord_does_nothing(self):
        handler = _DragMath()
        pos = [4.0, 4.0, 4.0, 4.0, 5.0, 3.0]
        self.assertPos(handler.compute_new_position(pos, 5.0, 10.0, 2, 0), pos)

    def test_handle_two_of_a_short_position_is_not_a_curve_control(self):
        handler = _DragMath()
        pos = [0.0, 0.0, 6.0, 8.0]
        self.assertPos(handler.compute_new_position(pos, 5.0, 10.0, 2, 0), pos)

    def test_polygon_corner_snaps_its_angle_from_the_previous_corner(self):
        handler = _DragMath()
        handler.snap_angle_result = lambda _ox, _oy, tx, ty: (tx - 1.0, ty - 1.0)
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(square, 1.0, 2.0, 2, 4)
        self.assertPos(result, [0.0, 0.0, 10.0, 0.0, 10.0, 11.0, 0.0, 10.0])
        result = handler.compute_new_position(square, 1.0, 2.0, 0, 4)
        self.assertPos(result, [0.0, 1.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0])
        self.assertEqual(
            handler.snap_angle_calls,
            [(10.0, 0.0, 11.0, 12.0), (0.0, 10.0, 1.0, 2.0)],
        )

    def test_polygon_corner_target_is_snapped_to_the_grid_before_the_angle(self):
        handler = _DragMath(snap_increments=5.0)
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        handler.compute_new_position(square, 1.0, 2.0, 2, 4)
        self.assertEqual(handler.snap_angle_calls, [(10.0, 0.0, 10.0, 10.0)])

    def test_line_end_point_snaps_its_angle_from_the_opposite_end(self):
        handler = _DragMath()
        result = handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 2.0, 3.0, 1, 0)
        self.assertPos(result, [0.0, 0.0, 12.0, 3.0])
        result = handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 2.0, 3.0, 0, 0)
        self.assertPos(result, [2.0, 3.0, 10.0, 0.0])
        self.assertEqual(
            handler.snap_angle_calls, [(0.0, 0.0, 12.0, 3.0), (10.0, 0.0, 2.0, 3.0)]
        )

    def test_line_end_point_is_grid_snapped(self):
        handler = _DragMath(snap_increments=5.0)
        result = handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 2.0, 3.0, 1, 0)
        self.assertPos(result, [0.0, 0.0, 10.0, 5.0])

    def test_curved_line_end_drag_keeps_the_control_point_at_the_same_chord_offset(
        self,
    ):
        handler = _DragMath()
        result = handler.compute_new_position(
            [0.0, 0.0, 10.0, 0.0, 5.0, 3.0], 0.0, 10.0, 1, 0
        )
        root = math.sqrt(2.0)
        self.assertPos(
            result,
            [0.0, 0.0, 10.0, 10.0, 5.0 - 3.0 / root, 5.0 + 3.0 / root],
        )
        result = handler.compute_new_position(
            [0.0, 0.0, 10.0, 0.0, 5.0, 3.0], 0.0, -4.0, 0, 0
        )
        # New chord (0,-4)->(10,0) has unit normal (-4, 10)/L; the control point keeps
        # its old 3-unit offset from the chord midpoint (5, -2).
        length = math.hypot(10.0, 4.0)
        self.assertPos(
            result,
            [0.0, -4.0, 10.0, 0.0, 5.0 - 12.0 / length, -2.0 + 30.0 / length],
        )

    def test_curved_line_end_drag_onto_the_other_end_collapses_the_control_to_the_midpoint(
        self,
    ):
        handler = _DragMath()
        result = handler.compute_new_position(
            [0.0, 0.0, 10.0, 0.0, 5.0, 3.0], -10.0, 0.0, 1, 0
        )
        self.assertPos(result, [0.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def test_curved_line_end_drag_from_a_degenerate_chord_has_no_offset(self):
        handler = _DragMath()
        result = handler.compute_new_position(
            [4.0, 4.0, 4.0, 4.0, 7.0, 9.0], 6.0, 0.0, 1, 0
        )
        self.assertPos(result, [4.0, 4.0, 10.0, 4.0, 7.0, 4.0])

    def test_five_value_position_moves_the_end_point_without_touching_a_control(self):
        handler = _DragMath()
        result = handler.compute_new_position(
            [0.0, 0.0, 10.0, 0.0, 7.0], 2.0, 3.0, 1, 0
        )
        self.assertPos(result, [0.0, 0.0, 12.0, 3.0, 7.0])

    def test_single_point_takeoff_moves_without_angle_snapping(self):
        handler = _DragMath(snap_increments=5.0)
        result = handler.compute_new_position([5.0, 5.0], 2.0, 3.0, 0, 0)
        self.assertPos(result, [5.0, 10.0])
        self.assertEqual(handler.snap_angle_calls, [])

    def test_later_points_of_a_multi_point_shape_move_without_angle_snapping(self):
        handler = _DragMath()
        pos = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(pos, 1.0, 2.0, 3, 0)
        self.assertPos(result, [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 1.0, 12.0])
        self.assertEqual(handler.snap_angle_calls, [])

    def test_out_of_range_handles_leave_the_position_unchanged(self):
        handler = _DragMath()
        pos = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0]
        for handle in (-2, 3, 4):
            with self.subTest(handle=handle):
                self.assertPos(
                    handler.compute_new_position(pos, 1.0, 2.0, handle, 0), pos
                )
        self.assertEqual(handler.snap_angle_calls, [])


from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    create_cloud_path_points,
)


class DragHandlerPathGapTests(unittest.TestCase):
    @staticmethod
    def _elements(path):
        return [
            (path.elementAt(i).type, path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())
        ]

    def test_cloud_path_is_the_cloud_segments_from_the_first_point_and_closed(self):
        move = QPainterPath.ElementType.MoveToElement
        curve = QPainterPath.ElementType.CurveToElement
        curve_data = QPainterPath.ElementType.CurveToDataElement
        points = [(5.0, 7.0), (45.0, 9.0), (44.0, 37.0), (4.0, 35.0)]
        path = _DragMath()._build_area_annotation_path(ANNOTATION_TYPE_CLOUD, points)
        expected = [(move, 5.0, 7.0)]
        for _start, cp1, cp2, end in create_cloud_path_points(points):
            expected.append((curve, cp1[0], cp1[1]))
            expected.append((curve_data, cp2[0], cp2[1]))
            expected.append((curve_data, end[0], end[1]))
        elements = self._elements(path)
        self.assertEqual(len(elements), len(expected))
        self.assertEqual(elements[:-1], expected[:-1])
        # The last cloud arc ends a rounding error short of the start; closing the
        # subpath snaps that end point exactly onto (5, 7).
        self.assertNotEqual(expected[-1][1:], (5.0, 7.0))
        self.assertEqual(elements[-1], (curve_data, 5.0, 7.0))

    def test_three_point_cloud_is_drawn_as_curves(self):
        path = _DragMath()._build_area_annotation_path(
            ANNOTATION_TYPE_CLOUD, [(5.0, 7.0), (45.0, 7.0), (45.0, 37.0)]
        )
        self.assertTrue(_interaction_support__path_has_curve(path))

    def test_polygon_edit_accepts_a_valid_triangle_and_reports_plain_booleans(self):
        handler = _DragMath()
        triangle = [0.0, 0.0, 10.0, 0.0, 5.0, 8.0]
        points = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
        self.assertIs(handler._polygon_edit_geometry_valid(triangle, points), True)
        self.assertIs(
            handler._polygon_edit_geometry_valid(triangle[:4], points[:2]), False
        )
        bow_tie = [(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)]
        self.assertIs(handler._polygon_edit_geometry_valid(triangle, bow_tie), False)
        handler._drag_last_valid_new_pos = [0.0, 0.0, 5.0, 8.0, 10.0, 0.0]
        self.assertIs(handler._polygon_edit_geometry_valid(triangle, points), False)

    def test_polygon_edit_winding_check_uses_the_sign_of_each_area_not_a_threshold(
        self,
    ):
        handler = _DragMath()
        tiny_ccw = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0]
        tiny_cw = [0.0, 0.0, 0.0, 1.0, 1.0, 0.0]
        big_cw = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0, 10.0, 0.0]
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        triangle = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        handler._drag_last_valid_new_pos = list(tiny_ccw)
        self.assertIs(handler._polygon_edit_geometry_valid(tiny_cw, triangle), False)
        self.assertIs(handler._polygon_edit_geometry_valid(tiny_ccw, triangle), True)
        handler._drag_last_valid_new_pos = list(big_cw)
        self.assertIs(handler._polygon_edit_geometry_valid(tiny_ccw, square), False)

    def test_polygon_edit_skips_the_winding_check_for_a_zero_area_candidate(self):
        handler = _DragMath()
        handler._drag_last_valid_new_pos = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        collinear = [0.0, 0.0, 5.0, 0.0, 10.0, 0.0]
        square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
        self.assertIs(handler._polygon_edit_geometry_valid(collinear, square), True)


class ComputeNewPositionGapTests(unittest.TestCase):
    def assertPos(self, actual, expected, places=6):
        self.assertEqual(len(actual), len(expected), msg=repr(actual))
        for index, (a, e) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(
                a,
                e,
                places=places,
                msg="index %d: %r vs %r" % (index, actual, expected),
            )

    def test_body_drag_snaps_with_each_axis_of_the_first_point(self):
        handler = _DragMath(snap_increments=5.0)
        # dx = snap(1+3) - 1 = 4 and dy = snap(8+4) - 8 = 2.
        self.assertPos(
            handler.compute_new_position([1.0, 8.0, 11.0, 8.0], 3.0, 4.0, -1, 0),
            [5.0, 10.0, 15.0, 10.0],
        )

    def test_free_edge_drag_moves_interior_edges_by_corner_index(self):
        handler = _DragMath()
        square = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(square, 3.0, 4.0, 5, 4, free_mode=True)
        self.assertPos(result, [0.0, 0.0, 13.0, 4.0, 13.0, 14.0, 0.0, 10.0])
        result = handler.compute_new_position(square, 3.0, 4.0, 6, 4, free_mode=True)
        self.assertPos(result, [0.0, 0.0, 10.0, 0.0, 13.0, 14.0, 3.0, 14.0])

    def test_triangles_use_constrained_edge_resize_unless_free(self):
        handler = _DragMath()
        triangle = [0.0, 0.0, 10.0, 0.0, 5.0, 10.0]
        result = handler.compute_new_position(triangle, 0.0, 2.0, 3, 3)
        self.assertPos(result, [1.0, 2.0, 9.0, 2.0, 5.0, 10.0])
        result = handler.compute_new_position(triangle, 0.0, 2.0, 3, 3, free_mode=True)
        self.assertPos(result, [0.0, 2.0, 10.0, 2.0, 5.0, 10.0])

    def test_constrained_resize_updates_both_axes_of_a_skewed_edge(self):
        handler = _DragMath()
        skewed = [0.0, 0.0, 10.0, 1.0, 9.0, 10.0, 1.0, 9.0]
        result = handler.compute_new_position(skewed, 2.0, 0.0, 5, 4)
        self.assertPos(
            result,
            [0.0, 0.0, 11.978021978, 1.197802198, 10.972602740, 10.246575342, 1.0, 9.0],
        )

    def test_constrained_resize_edge_length_threshold_is_one_nanounit(self):
        handler = _DragMath()
        at_threshold = [0.0, 0.0, 1e-9, 0.0, 1e-9, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(at_threshold, 0.0, 2.0, 4, 4)
        self.assertPos(result, [0.0, 2.0, 1e-9, 2.0, 1e-9, 10.0, 0.0, 10.0], places=12)
        below = [0.0, 0.0, 1e-10, 0.0, 1e-10, 10.0, 0.0, 10.0]
        self.assertEqual(handler.compute_new_position(below, 0.0, 2.0, 4, 4), below)
        above = [0.0, 0.0, 1.5e-9, 0.0, 1.5e-9, 10.0, 0.0, 10.0]
        result = handler.compute_new_position(above, 0.0, 2.0, 4, 4)
        self.assertPos(
            result, [0.0, 2.0, 1.5e-9, 2.0, 1.5e-9, 10.0, 0.0, 10.0], places=12
        )

    def test_curve_control_handle_on_a_chord_away_from_the_origin(self):
        handler = _DragMath()
        result = handler.compute_new_position(
            [1.0, 2.0, 7.0, 10.0, 5.0, 3.0], 5.0, 10.0, 2, 0
        )
        self.assertPos(result, [1.0, 2.0, 7.0, 10.0, 3.4, 4.2])
        result = handler.compute_new_position(
            [1.0, 2.0, 7.0, 10.0, 5.0, 3.0, 0.5], 5.0, 10.0, 2, 0
        )
        self.assertPos(result, [1.0, 2.0, 7.0, 10.0, 2.8, 6.9, -1.5])

    def test_curve_control_handle_needs_six_values_and_a_chord_longer_than_a_nanounit(
        self,
    ):
        handler = _DragMath()
        five = [1.0, 2.0, 7.0, 10.0, 5.0]
        self.assertPos(handler.compute_new_position(five, 5.0, 10.0, 2, 0), five)
        at_threshold = [0.0, 0.0, 1e-9, 0.0, 5.0, 3.0]
        self.assertPos(
            handler.compute_new_position(at_threshold, 0.0, 2.0, 2, 0), at_threshold
        )
        above = [0.0, 0.0, 1.5e-9, 0.0, 5.0, 3.0]
        self.assertPos(
            handler.compute_new_position(above, 0.0, 2.0, 2, 0),
            [0.0, 0.0, 1.5e-9, 0.0, 5.0, 5.0],
            places=9,
        )

    def test_polygon_corner_angle_origin_uses_both_coordinates_of_the_previous_corner(
        self,
    ):
        handler = _DragMath()
        pentagon_ish = [1.0, 2.0, 11.0, 3.0, 12.0, 13.0, 2.0, 14.0]
        handler.compute_new_position(pentagon_ish, 1.0, 1.0, 2, 4)
        handler.compute_new_position(pentagon_ish, 1.0, 1.0, 0, 4)
        self.assertEqual(
            handler.snap_angle_calls,
            [(11.0, 3.0, 13.0, 14.0), (2.0, 14.0, 2.0, 3.0)],
        )

    def test_line_end_angle_origin_is_the_other_end_of_a_slanted_line(self):
        handler = _DragMath()
        handler.compute_new_position([0.0, 2.0, 10.0, 5.0], 1.0, 1.0, 0, 0)
        handler.compute_new_position([0.0, 2.0, 10.0, 5.0], 1.0, 1.0, 1, 0)
        self.assertEqual(
            handler.snap_angle_calls, [(10.0, 5.0, 1.0, 3.0), (0.0, 2.0, 11.0, 6.0)]
        )

    def test_curved_line_end_angle_origin_is_the_other_end_not_the_control_point(self):
        handler = _DragMath()
        handler.compute_new_position([0.0, 2.0, 10.0, 5.0, 4.0, 9.0], 1.0, 1.0, 0, 0)
        self.assertEqual(handler.snap_angle_calls, [(10.0, 5.0, 1.0, 3.0)])

    def test_curved_line_end_drag_on_a_slanted_chord_keeps_the_signed_control_offset(
        self,
    ):
        handler = _DragMath()
        pos = [1.0, 2.0, 7.0, 10.0, 5.0, 3.0]
        result = handler.compute_new_position(pos, -3.0, 4.0, 1, 0)
        self.assertPos(result, [1.0, 2.0, 4.0, 14.0, 5.022370500, 7.369407375])
        result = handler.compute_new_position(pos, -3.0, 4.0, 0, 0)
        self.assertPos(result, [-2.0, 6.0, 7.0, 10.0, 3.555960012, 5.624089974])

    def test_curved_line_end_drag_keeps_no_offset_when_either_chord_is_at_the_threshold(
        self,
    ):
        handler = _DragMath()
        # Old chord exactly 1e-9 long, new chord long: the old offset is ignored.
        result = handler.compute_new_position(
            [0.0, 0.0, 1e-9, 0.0, 5.0, 3.0], 5.0, 0.0, 1, 0
        )
        self.assertPos(
            result, [0.0, 0.0, 5.000000001, 0.0, 2.5000000005, 0.0], places=9
        )
        # Old chord long, new chord exactly 1e-9 long: the control sits on the midpoint.
        result = handler.compute_new_position(
            [-5.0, 0.0, 1e-9, 0.0, 5.0, 3.0], 5.0, 0.0, 0, 0
        )
        self.assertPos(result, [0.0, 0.0, 1e-9, 0.0, 5e-10, 0.0], places=12)

    def test_curved_line_end_drag_chord_threshold_is_one_nanounit(self):
        handler = _DragMath()
        at_threshold = [0.0, 0.0, 1e-9, 0.0, 5.0, 3.0]
        result = handler.compute_new_position(at_threshold, 0.0, 0.0, 0, 0)
        self.assertPos(result, [0.0, 0.0, 1e-9, 0.0, 5e-10, 0.0], places=12)
        above = [0.0, 0.0, 1.5e-9, 0.0, 5.0, 3.0]
        result = handler.compute_new_position(above, 0.0, 0.0, 0, 0)
        self.assertPos(result, [0.0, 0.0, 1.5e-9, 0.0, 7.5e-10, 3.0], places=12)


from unittest.mock import patch


class _RecordingColorService:
    def __init__(self):
        self.calls = []

    def get_2d_color_for_takeoff(
        self,
        takeoff,
        condition,
        color_map,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        self.calls.append(
            (takeoff, condition, color_map, page_area_selections, inactive_object_color)
        )
        return "#336699", 0.4


class _RecordingPatternBuilder:
    def __init__(self, brush=None, items=()):
        self.brush = brush
        self.items = list(items)
        self.calls = []

    def build_pattern_fill(
        self, path, pattern_type, color, opacity, spacing, line_width, angle=None
    ):
        self.calls.append(
            (path, pattern_type, color, opacity, spacing, line_width, angle)
        )
        return self.brush, list(self.items)


class DragPreviewHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _helpers(self):
        return CtrlDragTests("test_area_pattern_preview_refreshes_during_resize_drag")

    def _pattern_view(self, builder, transform=None):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = builder
        view._color_service = _RecordingColorService()
        view._current_takeoffs = {"t1": SimpleNamespace(uid="t1", condition_uid="c1")}
        view._current_color_map = {"c1": "#abcdef"}
        view._current_page_area_selections = {"page": "area"}
        view._uid_to_items = {}
        view._takeoff_items = []
        view._current_page_transform = lambda: transform
        return view

    @staticmethod
    def _rect_path(width=10.0, height=6.0):
        path = QPainterPath()
        path.addRect(0.0, 0.0, width, height)
        return path

    def test_pattern_preview_requests_the_condition_pattern_with_its_colour(self):
        builder = _RecordingPatternBuilder()
        view = self._pattern_view(builder)
        condition = Condition(uid="c1", pattern=7, spacing=6.5)
        path_item = QGraphicsPathItem()
        path = self._rect_path()
        view._uid_to_items["t1"] = [path_item]
        view._refresh_takeoff_pattern_preview("t1", path_item, path, condition, 45.0)
        takeoff = view._current_takeoffs["t1"]
        self.assertEqual(
            view._color_service.calls,
            [
                (
                    takeoff,
                    condition,
                    view._current_color_map,
                    view._current_page_area_selections,
                    view._inactive_object_color,
                )
            ],
        )
        self.assertEqual(len(builder.calls), 1)
        got_path, pattern_type, color, opacity, spacing, line_width, angle = (
            builder.calls[0]
        )
        self.assertEqual(got_path, path)
        self.assertEqual(
            (pattern_type, color, opacity, spacing, line_width, angle),
            (7, QColor("#336699"), 0.4, 6.5, 2.0, 45.0),
        )

    def test_pattern_preview_defaults_missing_pattern_and_spacing(self):
        builder = _RecordingPatternBuilder()
        view = self._pattern_view(builder)
        condition = Condition(uid="c1", pattern=0, spacing=0.0)
        path_item = QGraphicsPathItem()
        view._uid_to_items["t1"] = [path_item]
        view._refresh_takeoff_pattern_preview(
            "t1", path_item, self._rect_path(), condition
        )
        _path, pattern_type, _color, _opacity, spacing, line_width, angle = (
            builder.calls[0]
        )
        self.assertEqual(
            (pattern_type, spacing, line_width, angle), (1, 4.0, 2.0, None)
        )

    def test_pattern_preview_styles_the_outline_and_fill_of_the_main_item(self):
        view = self._pattern_view(
            _RecordingPatternBuilder(brush=QBrush(QColor("#112233")))
        )
        condition = Condition(uid="c1", pattern=3, spacing=2.0)
        path_item = QGraphicsPathItem()
        view._uid_to_items["t1"] = [path_item]
        view._refresh_takeoff_pattern_preview(
            "t1", path_item, self._rect_path(), condition
        )
        self.assertEqual(path_item.pen().color(), QColor("#336699"))
        self.assertEqual(path_item.pen().widthF(), 2.0)
        self.assertTrue(path_item.pen().isCosmetic())
        self.assertEqual(path_item.brush().color(), QColor("#112233"))
        self.assertEqual(path_item.brush().style(), Qt.BrushStyle.SolidPattern)

    def test_pattern_preview_uses_an_empty_brush_when_the_builder_gives_no_fill(self):
        view = self._pattern_view(_RecordingPatternBuilder(brush=None))
        path_item = QGraphicsPathItem()
        path_item.setBrush(QBrush(QColor("red")))
        view._uid_to_items["t1"] = [path_item]
        view._refresh_takeoff_pattern_preview(
            "t1", path_item, self._rect_path(), Condition(uid="c1", pattern=3)
        )
        self.assertEqual(path_item.brush().style(), Qt.BrushStyle.NoBrush)

    def test_pattern_preview_replaces_old_pattern_lines_and_keeps_other_items(self):
        new_line = QGraphicsPathItem(self._rect_path())
        builder = _RecordingPatternBuilder(items=[new_line])
        view = self._pattern_view(builder, transform=QTransform().translate(5.0, 6.0))
        path_item = QGraphicsPathItem()
        path_item.setZValue(7.0)
        old_line = QGraphicsPathItem(self._rect_path())
        filled = QGraphicsPathItem(self._rect_path())
        filled.setBrush(QBrush(QColor("blue")))
        label = QGraphicsTextItem("label")
        for item in (path_item, old_line, filled, label):
            view._scene.addItem(item)
        view._uid_to_items["t1"] = [path_item, old_line, filled, label]
        view._takeoff_items = [path_item, old_line, filled, label]
        view._refresh_takeoff_pattern_preview(
            "t1", path_item, self._rect_path(), Condition(uid="c1", pattern=3)
        )
        self.assertIsNone(old_line.scene())
        self.assertNotIn(old_line, view._takeoff_items)
        self.assertIs(path_item.scene(), view._scene)
        self.assertIs(filled.scene(), view._scene)
        self.assertIs(label.scene(), view._scene)
        self.assertEqual(view._uid_to_items["t1"], [path_item, new_line, filled, label])
        self.assertEqual(view._takeoff_items, [path_item, filled, label, new_line])
        self.assertIs(new_line.scene(), view._scene)
        self.assertEqual(new_line.data(0), "t1")
        self.assertEqual(new_line.data(1), "c1")
        self.assertEqual(new_line.zValue(), 7.0)
        self.assertEqual(new_line.transform(), QTransform().translate(5.0, 6.0))

    def test_pattern_preview_items_inherit_visibility_and_the_item_transform_fallback(
        self,
    ):
        new_line = QGraphicsPathItem(self._rect_path())
        builder = _RecordingPatternBuilder(items=[new_line])
        view = self._pattern_view(builder, transform=None)
        path_item = QGraphicsPathItem()
        path_item.setTransform(QTransform().scale(2.0, 3.0))
        path_item.setVisible(False)
        view._uid_to_items["t1"] = [path_item]
        view._takeoff_items = [new_line]
        view._refresh_takeoff_pattern_preview(
            "t1", path_item, self._rect_path(), Condition(uid="c1", pattern=3)
        )
        self.assertFalse(new_line.isVisible())
        self.assertEqual(new_line.transform(), QTransform().scale(2.0, 3.0))
        # An item already tracked is not tracked twice.
        self.assertEqual(view._takeoff_items, [new_line])

    def test_hole_cutout_preview_hides_the_hole_and_drops_other_path_items(self):
        view = self._pattern_view(_RecordingPatternBuilder())
        path_item = QGraphicsPathItem()
        path_item.setPos(5.0, 5.0)
        path_item.setPen(QPen(QColor("red")))
        path_item.setBrush(QBrush(QColor("red")))
        stale = QGraphicsPathItem(self._rect_path())
        never_added = QGraphicsPathItem(self._rect_path())
        label = QGraphicsTextItem("label")
        for item in (path_item, stale, label):
            view._scene.addItem(item)
        view._uid_to_items["h"] = [path_item, stale, never_added, label]
        view._takeoff_items = [path_item, stale, never_added, label]
        path = self._rect_path(8.0, 4.0)
        view._apply_hole_cutout_preview_style("h", path_item, path)
        self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(path_item.path(), path)
        self.assertEqual(path_item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(path_item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertIs(path_item.scene(), view._scene)
        self.assertIsNone(stale.scene())
        self.assertIs(label.scene(), view._scene)
        self.assertEqual(view._takeoff_items, [path_item, label])
        self.assertEqual(view._uid_to_items["h"], [path_item, label])

    def test_dimension_preview_ignores_a_position_without_two_points(self):
        view, ann = self._helpers()._make_dimension_resize_view()
        path_item = view._uid_to_items["d1"][0]
        before = QPainterPath(path_item.path())
        path_item.setPos(7.0, 9.0)
        view._update_dimension_preview_items(
            ann, "d1", [5.0, 5.0], view._scene_builder.get_coordinate_system()
        )
        self.assertEqual(path_item.path(), before)
        self.assertEqual(path_item.pos(), QtCore.QPointF(7.0, 9.0))

    def test_dimension_preview_ignores_unknown_uids_and_non_path_first_items(self):
        view, ann = self._helpers()._make_dimension_resize_view()
        cs = view._scene_builder.get_coordinate_system()
        view._update_dimension_preview_items(ann, "missing", [0.0, 0.0, 60.0, 0.0], cs)
        self.assertNotIn("missing", view._uid_to_items)
        label = QGraphicsTextItem("keep")
        view._uid_to_items["odd"] = [label]
        view._update_dimension_preview_items(ann, "odd", [0.0, 0.0, 60.0, 0.0], cs)
        self.assertEqual(view._uid_to_items["odd"], [label])
        self.assertEqual(label.toPlainText(), "keep")

    def test_dimension_preview_resets_the_path_item_origin_before_setting_the_path(
        self,
    ):
        view, ann = self._helpers()._make_dimension_resize_view()
        path_item = view._uid_to_items["d1"][0]
        path_item.setPos(7.0, 9.0)
        view._update_dimension_preview_items(
            ann,
            "d1",
            [0.0, 0.0, 255.0, 0.0],
            view._scene_builder.get_coordinate_system(),
        )
        self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -5.0, 255.0, 10.0)
        )

    def test_dimension_preview_creates_a_tracked_selectable_label_when_missing(self):
        view, ann = self._helpers()._make_dimension_resize_view()
        view._current_page_transform = lambda: QTransform().translate(5.0, 6.0)
        path_item = view._uid_to_items["d1"][0]
        original_label = view._uid_to_items["d1"][1]
        view._scene.removeItem(original_label)
        view._takeoff_items.remove(original_label)
        view._uid_to_items["d1"] = [path_item]
        view._update_dimension_preview_items(
            ann,
            "d1",
            [0.0, 0.0, 255.0, 0.0],
            view._scene_builder.get_coordinate_system(),
        )
        self.assertEqual(len(view._uid_to_items["d1"]), 2)
        label = view._uid_to_items["d1"][1]
        self.assertIs(label.scene(), view._scene)
        self.assertEqual(label.toPlainText(), format_dimension_distance(255.0))
        self.assertEqual(label.data(0), "d1")
        self.assertEqual(label.data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertTrue(label.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.assertEqual(label.transform(), QTransform().translate(5.0, 6.0))
        self.assertEqual(view._takeoff_items.count(label), 1)

    def test_dimension_preview_without_a_page_transform_leaves_a_new_label_untransformed(
        self,
    ):
        view, ann = self._helpers()._make_dimension_resize_view()
        path_item = view._uid_to_items["d1"][0]
        view._uid_to_items["d1"] = [path_item]
        view._update_dimension_preview_items(
            ann,
            "d1",
            [0.0, 0.0, 255.0, 0.0],
            view._scene_builder.get_coordinate_system(),
        )
        self.assertTrue(view._uid_to_items["d1"][1].transform().isIdentity())

    def test_dimension_preview_adds_nothing_when_no_label_can_be_created(self):
        view, ann = self._helpers()._make_dimension_resize_view()
        path_item = view._uid_to_items["d1"][0]
        view._uid_to_items["d1"] = [path_item]
        scene_count = len(view._scene.items())
        tracked = list(view._takeoff_items)
        with patch.object(
            drag_handler_module, "create_dimension_text_item", return_value=None
        ):
            view._update_dimension_preview_items(
                ann,
                "d1",
                [0.0, 0.0, 255.0, 0.0],
                view._scene_builder.get_coordinate_system(),
            )
        self.assertEqual(view._uid_to_items["d1"], [path_item])
        self.assertEqual(len(view._scene.items()), scene_count)
        self.assertEqual(view._takeoff_items, tracked)

    def test_dimension_preview_updates_only_the_first_label(self):
        view, ann = self._helpers()._make_dimension_resize_view()
        first = view._uid_to_items["d1"][1]
        second = QGraphicsTextItem("stale second label")
        view._scene.addItem(second)
        view._uid_to_items["d1"].append(second)
        view._update_dimension_preview_items(
            ann,
            "d1",
            [0.0, 0.0, 255.0, 0.0],
            view._scene_builder.get_coordinate_system(),
        )
        self.assertEqual(first.toPlainText(), format_dimension_distance(255.0))
        self.assertEqual(second.toPlainText(), "stale second label")


from ost_visualizer.presentation.visualization.core.geometry.takeoff_geometry import (
    MINIMUM_RENDERED_LINEAR_THICKNESS,
    compute_line_angle,
)


class _ScriptedLinearGeometry:
    """Linear geometry double that returns scripted curve data and records calls."""

    def __init__(self, processed, curve_points, offsets):
        self.processed = processed
        self.curve_points = curve_points
        self.offsets = offsets
        self.proc_calls = []
        self.curve_calls = []
        self.offset_calls = []

    def calc_chord_length(self, x1, y1, x2, y2):
        return math.hypot(x2 - x1, y2 - y1)

    def proc_curved_pos(self, *args):
        self.proc_calls.append(args)
        return self.processed

    def gen_curve_pts(self, *args):
        self.curve_calls.append(args)
        return self.curve_points

    def gen_thick_curve_offsets(self, *args):
        self.offset_calls.append(args)
        return self.offsets


class _HandleCs(_interaction_support_FakeCoordinateSystem):
    """Identity coordinate system whose transform can be scripted per call."""

    def __init__(self):
        self.truncate_to = None
        self.px_scale = 1.0
        self.transform_calls = None

    def transform_vertices_to_2d(self, pos):
        result = list(pos)
        if self.transform_calls is not None:
            self.transform_calls.append(list(pos))
        if self.truncate_to is not None:
            return result[: self.truncate_to]
        return result

    def ost_to_screen_pixels(self, value):
        return float(value) * self.px_scale


class UpdateDragHandlePositionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(
        self,
        *,
        takeoff=None,
        condition=None,
        annotation=None,
        n_handles=8,
        handle_index=0,
        items=None,
        linear_geom=None,
    ):
        view = _interaction_support_InputHandlerHarness()
        view._scene = QGraphicsScene()
        view._scene_builder = _interaction_support_FakeSceneBuilder()
        view._scene_builder.cs = _HandleCs()
        view._color_service = _interaction_support_FakeColorService()
        view._linear_geom = linear_geom or _interaction_support_FakeLinearGeom()
        view._current_takeoffs = {"t1": takeoff} if takeoff is not None else {}
        view._current_annotations = {"t1": annotation} if annotation is not None else {}
        view._current_conditions = (
            {condition.uid: condition} if condition is not None else {}
        )
        view._current_color_map = {}
        view._current_page_area_selections = {}
        view._uid_to_items = {"t1": list(items or [])}
        view._takeoff_items = list(items or [])
        for item in items or []:
            view._scene.addItem(item)
        view._handle_infos = [
            SimpleNamespace(item=_interaction_support_FakeItem())
            for _ in range(n_handles)
        ]
        view._drag_handle_index = handle_index
        view._drag_handle_corner_count = 4
        view._drag_last_valid_new_pos = []
        view._drag_item_orig_positions = {}
        view._drag_orig_position = []
        view._selection_items = []
        view._pt_to_scene = lambda x, y: QtCore.QPointF(x, y)
        view._current_page_transform = lambda: None
        view.calls = []
        view.hole_valid = True
        view.parent_valid = True
        view.child_holes = False
        view._validate_hole_position = lambda *args: (
            view.calls.append(("validate_hole", args)) or view.hole_valid
        )
        view._validate_parent_contains_holes = lambda *args: (
            view.calls.append(("validate_parent", args)) or view.parent_valid
        )
        view._has_child_holes = lambda uid: view.child_holes
        view._refresh_condition_text_labels_for_takeoff = lambda uid: view.calls.append(
            ("labels", uid)
        )
        view._rebuild_parent_with_holes = lambda *args: view.calls.append(
            ("rebuild_parent", args)
        )
        view._update_parent_hole_path = lambda *args: view.calls.append(
            ("hole_path", args)
        )
        view._refresh_takeoff_pattern_preview = lambda *args: view.calls.append(
            ("pattern", args)
        )
        view._update_dimension_preview_items = lambda *args: view.calls.append(
            ("dimension", args)
        )
        view._update_ann_drag = lambda *args: view.calls.append(("ann_drag", args))
        return view

    @staticmethod
    def _takeoff(position, *, is_hole=False, parent_uid="0", condition_uid="c1"):
        return Takeoff(
            uid="t1",
            condition_uid=condition_uid,
            page_uid="page-1",
            area_uid="area-1",
            position=list(position),
            parent_uid="p1" if is_hole else parent_uid,
        )

    @staticmethod
    def _handle_positions(view):
        return [(h.item.pos().x(), h.item.pos().y()) for h in view._handle_infos]

    @staticmethod
    def _elements(path):
        return [
            (path.elementAt(i).type, path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())
        ]

    # ---- early exits
    def test_unknown_takeoffs_and_conditions_change_nothing(self):
        for takeoff, condition in (
            (None, None),
            (self._takeoff([0.0, 0.0, 6.0, 8.0]), None),
        ):
            with self.subTest(has_takeoff=takeoff is not None):
                view = self._view(takeoff=takeoff, condition=condition)
                view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
                self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)
                self.assertEqual(view._drag_last_valid_new_pos, [])
                self.assertEqual(view.calls, [])

    def test_degenerate_transforms_or_missing_handles_change_nothing(self):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=4.0
        )
        takeoff = self._takeoff([0.0, 0.0, 6.0, 8.0])
        path_item = QGraphicsPathItem()
        view = self._view(takeoff=takeoff, condition=condition, items=[path_item])
        view._scene_builder.cs.truncate_to = 0
        view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
        view._scene_builder.cs.truncate_to = 1
        view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)
        self.assertTrue(path_item.path().isEmpty())
        view = self._view(
            takeoff=takeoff, condition=condition, n_handles=0, items=[path_item]
        )
        view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(view.calls, [])

    def test_two_value_position_is_enough_to_place_a_point_handle(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        view = self._view(takeoff=self._takeoff([5.0, 6.0]), condition=condition)
        view.update_drag_handle_positions([5.0, 6.0], "t1")
        self.assertEqual(self._handle_positions(view)[0], (5.0, 6.0))
        self.assertEqual(self._handle_positions(view)[1:], [(0.0, 0.0)] * 7)

    # ---- linear takeoffs
    def test_linear_takeoff_drag_moves_both_end_handles_and_rebuilds_the_thick_segment(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        path_item = QGraphicsPathItem()
        path_item.setPos(3.0, 3.0)
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 6.0, 8.0]),
            condition=condition,
            n_handles=3,
            handle_index=1,
            items=[path_item],
        )
        view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
        self.assertEqual(
            self._handle_positions(view), [(1.0, 2.0), (7.0, 10.0), (0.0, 0.0)]
        )
        self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        # Chord (6, 8): unit (0.6, 0.8); half thickness 4 along the normal (-0.8, 0.6).
        expected = [
            (move, -2.2, 4.4),
            (line, 4.2, -0.4),
            (line, 10.2, 7.6),
            (line, 3.8, 12.4),
            (line, -2.2, 4.4),
        ]
        elements = self._elements(path_item.path())
        self.assertEqual(len(elements), len(expected))
        for (kind, x, y), (e_kind, e_x, e_y) in zip(elements, expected):
            self.assertEqual(kind, e_kind)
            self.assertAlmostEqual(x, e_x, places=6)
            self.assertAlmostEqual(y, e_y, places=6)
        self.assertEqual(len(view.calls), 1)
        name, args = view.calls[0]
        self.assertEqual(name, "pattern")
        self.assertEqual(args[:4], ("t1", path_item, path_item.path(), condition))
        self.assertEqual(args[4], compute_line_angle(1.0, 2.0, 7.0, 10.0))

    def test_linear_takeoff_without_a_thickness_uses_one_unit_but_never_below_the_minimum(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=0.0
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0]),
            condition=condition,
            n_handles=2,
            handle_index=1,
            items=[path_item],
        )
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0], "t1")
        half = MINIMUM_RENDERED_LINEAR_THICKNESS / 2.0
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -half, 10.0, 2 * half)
        )
        # A thickness above the minimum is used as is (identity pixel scale).
        condition.thickness = 6.0
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0], "t1")
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -3.0, 10.0, 6.0)
        )

    def test_linear_takeoff_segment_shorter_than_a_milli_unit_keeps_the_previous_path(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=6.0
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0]),
            condition=condition,
            n_handles=2,
            handle_index=1,
            items=[path_item],
        )
        view.update_drag_handle_positions([0.0, 0.0, 0.0005, 0.0], "t1")
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(view.calls, [])
        view.update_drag_handle_positions([0.0, 0.0, 0.002, 0.0], "t1")
        self.assertFalse(path_item.path().isEmpty())
        self.assertEqual(len(view.calls), 1)

    def test_curved_linear_takeoff_drags_the_control_handle_and_builds_a_thick_curve(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        geometry = _ScriptedLinearGeometry(
            processed=(1.0, 2.0, 3.0, 4.0, 5.5, 6.5),
            curve_points=[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)],
            offsets=(
                [(0.0, 1.0), (1.0, 2.0), (2.0, 1.0)],
                [(0.0, -1.0), (1.0, 0.0), (2.0, -1.0)],
            ),
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0]),
            condition=condition,
            n_handles=3,
            handle_index=2,
            items=[path_item],
            linear_geom=geometry,
        )
        new_pos = [0.0, 1.0, 10.0, 2.0, 5.0, 3.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(
            geometry.proc_calls, [(new_pos, 0.0, 1.0, 10.0, 2.0, 5.0, 3.0)] * 2
        )
        self.assertEqual(
            self._handle_positions(view), [(0.0, 1.0), (10.0, 2.0), (5.5, 6.5)]
        )
        self.assertEqual(geometry.curve_calls, [(1.0, 2.0, 3.0, 4.0, 5.5, 6.5, 24)])
        self.assertEqual(geometry.offset_calls, [(geometry.curve_points, 8.0)])
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(path_item.path()),
            [
                (move, 0.0, 1.0),
                (line, 1.0, 2.0),
                (line, 2.0, 1.0),
                (line, 2.0, -1.0),
                (line, 1.0, 0.0),
                (line, 0.0, -1.0),
                (line, 0.0, 1.0),
            ],
        )
        self.assertEqual(len(view.calls), 1)

    def test_curved_linear_takeoff_needs_a_control_handle_and_six_values(self):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        for label, n_handles, new_pos in (
            ("no control handle", 2, [0.0, 1.0, 10.0, 2.0, 5.0, 3.0]),
            ("no control value", 3, [0.0, 1.0, 10.0, 2.0, 5.0]),
        ):
            with self.subTest(label):
                geometry = _ScriptedLinearGeometry(
                    (1.0, 2.0, 3.0, 4.0, 5.5, 6.5), [(0.0, 0.0), (1.0, 1.0)], ([], [])
                )
                path_item = QGraphicsPathItem()
                view = self._view(
                    takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0]),
                    condition=condition,
                    n_handles=n_handles,
                    handle_index=1,
                    items=[path_item],
                    linear_geom=geometry,
                )
                view.update_drag_handle_positions(new_pos, "t1")
                self.assertEqual(geometry.proc_calls, [])
                self.assertEqual(geometry.curve_calls, [])
                self.assertFalse(path_item.path().isEmpty())
                if n_handles == 3:
                    self.assertEqual(self._handle_positions(view)[2], (0.0, 0.0))

    def test_curved_linear_takeoff_with_too_few_curve_points_falls_back_to_a_straight_segment(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        geometry = _ScriptedLinearGeometry(
            (1.0, 2.0, 3.0, 4.0, 5.5, 6.5), [(0.0, 0.0)], ([], [])
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0]),
            condition=condition,
            n_handles=3,
            handle_index=1,
            items=[path_item],
            linear_geom=geometry,
        )
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0, 5.0, 3.0], "t1")
        self.assertEqual(geometry.offset_calls, [])
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -4.0, 10.0, 8.0)
        )

    def test_curved_linear_takeoff_ignores_a_short_control_transform(self):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        geometry = _ScriptedLinearGeometry(
            (1.0, 2.0, 3.0, 4.0, 5.5, 6.5), [(0.0, 0.0), (1.0, 1.0)], ([], [])
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0]),
            condition=condition,
            n_handles=3,
            handle_index=1,
            items=[path_item],
            linear_geom=geometry,
        )
        original_transform = view._scene_builder.cs.transform_vertices_to_2d

        def short_for_control(pos):
            result = original_transform(pos)
            return result[:5] if tuple(pos) == geometry.processed else result

        view._scene_builder.cs.transform_vertices_to_2d = short_for_control
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0, 5.0, 3.0], "t1")
        self.assertEqual(self._handle_positions(view)[2], (0.0, 0.0))
        self.assertEqual(geometry.curve_calls, [])
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -4.0, 10.0, 8.0)
        )

    # ---- annotations
    def test_arrow_annotation_drag_redraws_the_shaft_and_a_thirty_degree_head(self):
        for width, size in ((2.0, 40.0), (0.5, 24.0)):
            with self.subTest(width=width):
                annotation = BidAnnotation(
                    uid="t1",
                    annotation_type="arrow",
                    position=[10.0, 20.0, 110.0, 120.0],
                    width=width,
                )
                path_item = QGraphicsPathItem()
                path_item.setPos(4.0, 4.0)
                view = self._view(
                    annotation=annotation,
                    n_handles=2,
                    handle_index=1,
                    items=[path_item],
                )
                view.update_drag_handle_positions([10.0, 20.0, 110.0, 120.0], "t1")
                self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
                self.assertEqual(
                    self._handle_positions(view), [(10.0, 20.0), (110.0, 120.0)]
                )
                cos15 = 0.9659258262890683
                sin15 = 0.25881904510252074
                move = QPainterPath.ElementType.MoveToElement
                line = QPainterPath.ElementType.LineToElement
                expected = [
                    (move, 10.0, 20.0),
                    (line, 110.0, 120.0),
                    (move, 110.0 - size * cos15, 120.0 - size * sin15),
                    (line, 110.0, 120.0),
                    (line, 110.0 - size * sin15, 120.0 - size * cos15),
                ]
                elements = self._elements(path_item.path())
                self.assertEqual(len(elements), len(expected))
                for (kind, x, y), (e_kind, e_x, e_y) in zip(elements, expected):
                    self.assertEqual(kind, e_kind)
                    self.assertAlmostEqual(x, e_x, places=6)
                    self.assertAlmostEqual(y, e_y, places=6)

    def test_line_annotation_drag_redraws_a_plain_segment(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="line", position=[10.0, 20.0, 110.0, 120.0]
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            annotation=annotation, n_handles=2, handle_index=0, items=[path_item]
        )
        view.update_drag_handle_positions([5.0, 6.0, 110.0, 120.0], "t1")
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(path_item.path()), [(move, 5.0, 6.0), (line, 110.0, 120.0)]
        )
        self.assertEqual(self._handle_positions(view), [(5.0, 6.0), (110.0, 120.0)])
        self.assertEqual(view.calls, [])

    def test_dimension_annotation_drag_delegates_to_the_dimension_preview(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="dimension", position=[0.0, 0.0, 60.0, 0.0]
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            annotation=annotation, n_handles=2, handle_index=1, items=[path_item]
        )
        view.update_drag_handle_positions([0.0, 0.0, 90.0, 0.0], "t1")
        self.assertEqual(len(view.calls), 1)
        name, args = view.calls[0]
        self.assertEqual(name, "dimension")
        self.assertEqual(args[:3], (annotation, "t1", [0.0, 0.0, 90.0, 0.0]))
        self.assertIs(args[3], view._scene_builder.cs)
        self.assertTrue(path_item.path().isEmpty())

    def test_linear_annotation_body_drag_does_not_rebuild_the_segment(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="line", position=[10.0, 20.0, 110.0, 120.0]
        )
        path_item = QGraphicsPathItem()
        view = self._view(
            annotation=annotation, n_handles=2, handle_index=-1, items=[path_item]
        )
        view.update_drag_handle_positions([20.0, 30.0, 120.0, 130.0], "t1")
        self.assertEqual(self._handle_positions(view), [(20.0, 30.0), (120.0, 130.0)])
        self.assertTrue(path_item.path().isEmpty())

    def test_area_and_text_annotations_are_handled_by_the_annotation_drag(self):
        for annotation_type in ("rect", "polygon", "text"):
            with self.subTest(annotation_type=annotation_type):
                annotation = BidAnnotation(
                    uid="t1",
                    annotation_type=annotation_type,
                    position=[0.0, 0.0, 6.0, 8.0],
                )
                view = self._view(annotation=annotation, handle_index=2)
                view.update_drag_handle_positions([1.0, 1.0, 6.0, 8.0], "t1", 3.0, 4.0)
                self.assertEqual(len(view.calls), 1)
                name, args = view.calls[0]
                self.assertEqual(name, "ann_drag")
                self.assertEqual(args[:3], (annotation, [1.0, 1.0, 6.0, 8.0], "t1"))
                self.assertIs(args[3], view._scene_builder.cs)
                self.assertEqual(args[4:], (3.0, 4.0))
                self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)

    def test_non_interactive_annotation_ids_fall_back_to_takeoff_lookup(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="unknown", position=[0.0, 0.0]
        )
        view = self._view(annotation=annotation)
        view.update_drag_handle_positions([1.0, 1.0, 6.0, 8.0], "t1")
        self.assertEqual(view.calls, [])
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)

    # ---- area takeoffs
    def _area_view(self, *, is_hole=False, handle_index=2, n_handles=8, items=None):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        path_item = QGraphicsPathItem()
        view = self._view(
            takeoff=self._takeoff(
                [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0], is_hole=is_hole
            ),
            condition=condition,
            n_handles=n_handles,
            handle_index=handle_index,
            items=items if items is not None else [path_item],
        )
        return view, condition

    def test_area_vertex_drag_places_corner_and_midpoint_handles(self):
        view, _condition = self._area_view()
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(
            self._handle_positions(view),
            [
                (0.0, 0.0),
                (10.0, 0.0),
                (14.0, 12.0),
                (0.0, 10.0),
                (5.0, 0.0),
                (12.0, 6.0),
                (7.0, 11.0),
                (0.0, 5.0),
            ],
        )
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)

    def test_area_vertex_drag_with_fewer_handles_places_only_the_available_ones(self):
        view, _condition = self._area_view(n_handles=6)
        view.update_drag_handle_positions(
            [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(
            self._handle_positions(view),
            [
                (0.0, 0.0),
                (10.0, 0.0),
                (14.0, 12.0),
                (0.0, 10.0),
                (5.0, 0.0),
                (12.0, 6.0),
            ],
        )

    def test_area_vertex_drag_rebuilds_the_outline_and_refreshes_labels(self):
        view, condition = self._area_view()
        path_item = view._uid_to_items["t1"][0]
        path_item.setPos(4.0, 4.0)
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view.update_drag_handle_positions(new_pos, "t1")
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(path_item.path()),
            [
                (move, 0.0, 0.0),
                (line, 10.0, 0.0),
                (line, 14.0, 12.0),
                (line, 0.0, 10.0),
                (line, 0.0, 0.0),
            ],
        )
        self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(
            view.calls,
            [
                ("validate_parent", ("t1", new_pos)),
                ("pattern", ("t1", path_item, path_item.path(), condition)),
                ("labels", "t1"),
            ],
        )

    def test_area_vertex_drag_rebuilds_the_parent_when_it_owns_holes(self):
        view, _condition = self._area_view()
        view.child_holes = True
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view.update_drag_handle_positions(new_pos, "t1")
        names = [name for name, _args in view.calls]
        self.assertEqual(names, ["validate_parent", "pattern", "rebuild_parent"])
        _name, args = view.calls[-1]
        self.assertEqual(args[0], "t1")
        self.assertEqual(args[1], view._uid_to_items["t1"][0].path())

    def test_hole_vertex_drag_hides_the_hole_and_cuts_it_from_the_parent(self):
        view, _condition = self._area_view(is_hole=True)
        path_item = view._uid_to_items["t1"][0]
        path_item.setBrush(QBrush(QColor("red")))
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(path_item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertEqual(path_item.pen().style(), Qt.PenStyle.NoPen)
        names = [name for name, _args in view.calls]
        self.assertEqual(names, ["validate_hole", "validate_parent", "hole_path"])
        self.assertEqual(view.calls[0][1], (view._current_takeoffs["t1"], new_pos))
        self.assertEqual(view.calls[2][1], ("p1", "t1", path_item.path()))

    def test_invalid_hole_position_keeps_handles_and_last_valid_geometry(self):
        view, _condition = self._area_view(is_hole=True)
        view.hole_valid = False
        view._drag_last_valid_new_pos = [9.0] * 8
        view.update_drag_handle_positions(
            [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)
        self.assertEqual(view._drag_last_valid_new_pos, [9.0] * 8)
        self.assertEqual([name for name, _ in view.calls], ["validate_hole"])

    def test_parent_that_no_longer_contains_its_holes_keeps_the_previous_geometry(self):
        view, _condition = self._area_view()
        view.parent_valid = False
        view._drag_last_valid_new_pos = [9.0] * 8
        view.update_drag_handle_positions(
            [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(self._handle_positions(view), [(0.0, 0.0)] * 8)
        self.assertEqual(view._drag_last_valid_new_pos, [9.0] * 8)
        self.assertTrue(view._uid_to_items["t1"][0].path().isEmpty())

    def test_area_body_drag_skips_the_parent_validation_and_outline_rebuild(self):
        view, _condition = self._area_view(handle_index=-1)
        path_item = view._uid_to_items["t1"][0]
        new_pos = [1.0, 1.0, 11.0, 1.0, 11.0, 11.0, 1.0, 11.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(view.calls, [])
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)
        self.assertEqual(self._handle_positions(view)[0], (1.0, 1.0))

    def test_area_body_drag_of_a_hole_still_validates_its_position_only(self):
        view, _condition = self._area_view(is_hole=True, handle_index=-1)
        new_pos = [1.0, 1.0, 11.0, 1.0, 11.0, 11.0, 1.0, 11.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual([name for name, _ in view.calls[:1]], ["validate_hole"])
        self.assertNotIn("validate_parent", [name for name, _ in view.calls])
        self.assertNotIn("hole_path", [name for name, _ in view.calls])

    def test_area_drag_with_a_short_transform_is_not_treated_as_a_vertex_drag(self):
        view, _condition = self._area_view()
        view._scene_builder.cs.truncate_to = 4
        view.update_drag_handle_positions(
            [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(
            self._handle_positions(view)[:3], [(0.0, 0.0), (10.0, 0.0), (5.0, 0.0)]
        )
        self.assertEqual(view.calls, [])
        self.assertTrue(view._uid_to_items["t1"][0].path().isEmpty())

    # ---- body moves of the preview items
    def _body_move_view(self, condition_type, *, handle_index=-1, is_hole=False):
        condition = Condition(uid="c1", condition_type=condition_type)
        a = QGraphicsPathItem()
        b = QGraphicsPathItem()
        a.setPos(10.0, 20.0)
        b.setPos(30.0, 40.0)
        position = (
            [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
            if condition_type == Condition.TYPE_AREA
            else [0.0, 0.0]
        )
        view = self._view(
            takeoff=self._takeoff(position, is_hole=is_hole),
            condition=condition,
            handle_index=handle_index,
            items=[a, b],
        )
        view._drag_item_orig_positions = {id(a): a.pos(), id(b): b.pos()}
        view._drag_orig_position = list(position)
        return view, a, b

    def test_body_drag_moves_preview_items_by_the_ost_delta_in_scene_units(self):
        view, a, b = self._body_move_view(Condition.TYPE_COUNT)
        view.update_drag_handle_positions([36.0, 72.0], "t1", 500.0, 500.0)
        # 72 / (scale_ratio 1 * view_scale 1) -> scene factor 72.
        self.assertEqual(
            a.pos(), QtCore.QPointF(10.0 + 36.0 * 72.0, 20.0 + 72.0 * 72.0)
        )
        self.assertEqual(
            b.pos(), QtCore.QPointF(30.0 + 36.0 * 72.0, 40.0 + 72.0 * 72.0)
        )

    def test_body_drag_prefers_the_last_valid_position_over_the_candidate(self):
        view, a, _b = self._body_move_view(Condition.TYPE_COUNT)
        view._drag_last_valid_new_pos = [1.0, 2.0]
        view.update_drag_handle_positions([36.0, 72.0], "t1")
        self.assertEqual(a.pos(), QtCore.QPointF(10.0 + 1.0 * 72.0, 20.0 + 2.0 * 72.0))

    def test_body_drag_uses_scene_deltas_without_an_original_position(self):
        view, a, b = self._body_move_view(Condition.TYPE_COUNT)
        view._drag_orig_position = []
        view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
        self.assertEqual(a.pos(), QtCore.QPointF(15.0, 27.0))
        self.assertEqual(b.pos(), QtCore.QPointF(35.0, 47.0))
        view.update_drag_handle_positions([36.0, 72.0], "t1")
        self.assertEqual(a.pos(), QtCore.QPointF(10.0, 20.0))

    def test_body_drag_requires_two_values_in_the_candidate_and_original_positions(
        self,
    ):
        view, a, _b = self._body_move_view(Condition.TYPE_COUNT)
        view._drag_orig_position = [0.0]
        view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
        self.assertEqual(a.pos(), QtCore.QPointF(15.0, 27.0))
        view._drag_orig_position = [0.0, 0.0]
        view._drag_last_valid_new_pos = [3.0]
        view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
        self.assertEqual(a.pos(), QtCore.QPointF(15.0, 27.0))

    def test_body_drag_leaves_untracked_items_alone(self):
        view, a, b = self._body_move_view(Condition.TYPE_COUNT)
        del view._drag_item_orig_positions[id(b)]
        view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
        self.assertEqual(b.pos(), QtCore.QPointF(30.0, 40.0))

    def test_body_drag_does_nothing_without_recorded_original_item_positions(self):
        view, a, _b = self._body_move_view(Condition.TYPE_COUNT)
        view._drag_item_orig_positions = {}
        view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
        self.assertEqual(a.pos(), QtCore.QPointF(10.0, 20.0))

    def test_point_takeoff_handle_drag_also_moves_the_body_items(self):
        view, a, _b = self._body_move_view(Condition.TYPE_COUNT, handle_index=0)
        view.update_drag_handle_positions([1.0, 1.0], "t1", 5.0, 7.0)
        self.assertEqual(a.pos(), QtCore.QPointF(10.0 + 72.0, 20.0 + 72.0))

    def test_linear_and_area_handle_drags_do_not_move_the_body_items(self):
        for condition_type in (Condition.TYPE_LINEAR, Condition.TYPE_AREA):
            with self.subTest(condition_type=condition_type):
                view, _a, b = self._body_move_view(condition_type, handle_index=1)
                new_pos = (
                    [1.0, 1.0, 10.0, 0.0]
                    if condition_type == Condition.TYPE_LINEAR
                    else [1.0, 1.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
                )
                view.update_drag_handle_positions(new_pos, "t1", 5.0, 7.0)
                # The outline item is rebuilt in place; the other preview items stay.
                self.assertEqual(b.pos(), QtCore.QPointF(30.0, 40.0))

    def _hole_cut_path(self, view):
        hole_calls = [args for name, args in view.calls if name == "hole_path"]
        self.assertEqual(len(hole_calls), 1)
        parent_uid, uid, path = hole_calls[0]
        self.assertEqual((parent_uid, uid), ("p1", "t1"))
        return path

    def test_hole_body_drag_cuts_the_moved_hole_out_of_its_parent(self):
        view, _a, _b = self._body_move_view(Condition.TYPE_AREA, is_hole=True)
        view.update_drag_handle_positions(
            [2.0, 5.0, 12.0, 5.0, 12.0, 15.0, 2.0, 15.0], "t1", 5.0, 7.0
        )
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(self._hole_cut_path(view)),
            [
                (move, 2.0, 5.0),
                (line, 12.0, 5.0),
                (line, 12.0, 15.0),
                (line, 2.0, 15.0),
                (line, 2.0, 5.0),
            ],
        )

    def test_hole_body_drag_with_an_invalid_candidate_uses_the_last_valid_geometry(
        self,
    ):
        view, _a, _b = self._body_move_view(Condition.TYPE_AREA, is_hole=True)
        view.hole_valid = False
        view._drag_last_valid_new_pos = [1.0, 3.0, 11.0, 3.0, 11.0, 13.0, 1.0, 13.0]
        view.update_drag_handle_positions(
            [2.0, 5.0, 12.0, 5.0, 12.0, 15.0, 2.0, 15.0], "t1", 5.0, 7.0
        )
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(self._hole_cut_path(view)),
            [
                (move, 1.0, 3.0),
                (line, 11.0, 3.0),
                (line, 11.0, 13.0),
                (line, 1.0, 13.0),
                (line, 1.0, 3.0),
            ],
        )

    def test_hole_body_drag_without_any_valid_geometry_does_not_touch_the_parent(self):
        view, _a, _b = self._body_move_view(Condition.TYPE_AREA, is_hole=True)
        view.hole_valid = False
        view.update_drag_handle_positions(
            [2.0, 2.0, 12.0, 2.0, 12.0, 12.0, 2.0, 12.0], "t1", 5.0, 7.0
        )
        self.assertNotIn("hole_path", [name for name, _ in view.calls])

    def test_non_hole_area_body_drag_never_updates_a_parent_cutout(self):
        view, _a, _b = self._body_move_view(Condition.TYPE_AREA)
        view.update_drag_handle_positions(
            [2.0, 2.0, 12.0, 2.0, 12.0, 12.0, 2.0, 12.0], "t1", 5.0, 7.0
        )
        self.assertNotIn("hole_path", [name for name, _ in view.calls])


from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ClippedTextGraphicsItem,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    build_highlight_path,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    highlight_position_coordinates,
)
from PySide6.QtWidgets import QGraphicsPolygonItem


class AnnotationDragTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(
        self, annotation, *, n_handles=8, handle_index=0, items=None, selection=None
    ):
        base = UpdateDragHandlePositionsTests(
            "test_unknown_takeoffs_and_conditions_change_nothing"
        )
        view = base._view(
            annotation=annotation,
            n_handles=n_handles,
            handle_index=handle_index,
            items=items,
        )
        del view._update_ann_drag
        view._selection_items = list(selection or [])
        view.bbox_calls = []
        view.outline_calls = []
        view.rebuild_calls = []
        view._update_bbox_handles = lambda *args: view.bbox_calls.append(args)
        view._update_annotation_selection_outline_from_box = lambda *args: (
            view.outline_calls.append(args)
        )
        view._rebuild_ann_shape_path = lambda *args: view.rebuild_calls.append(args)
        return view

    @staticmethod
    def _annotation(annotation_type, position):
        return BidAnnotation(
            uid="t1", annotation_type=annotation_type, position=list(position)
        )

    @staticmethod
    def _handles(view):
        return [(h.item.pos().x(), h.item.pos().y()) for h in view._handle_infos]

    def test_text_drag_derives_the_box_from_centre_and_size(self):
        annotation = self._annotation("text", [50.0, 40.0, 20.0, 10.0])
        view = self._view(annotation, handle_index=2)
        view.update_drag_handle_positions([50.0, 40.0, 20.0, 10.0], "t1")
        cs = view._scene_builder.cs
        self.assertEqual(view.bbox_calls, [(cs, 40.0, 35.0, 60.0, 45.0, 8)])
        self.assertEqual(view.outline_calls, [("t1", cs, 40.0, 35.0, 60.0, 45.0)])
        self.assertEqual(
            view.rebuild_calls, [("text", "t1", 40.0, 35.0, 60.0, 45.0, None)]
        )
        self.assertEqual(view._drag_last_valid_new_pos, [50.0, 40.0, 20.0, 10.0])

    def test_text_drag_with_a_short_position_uses_a_zero_box(self):
        annotation = self._annotation("text", [50.0, 40.0])
        view = self._view(annotation, handle_index=2)
        view.update_drag_handle_positions([50.0, 40.0], "t1")
        self.assertEqual(view.rebuild_calls, [("text", "t1", 0.0, 0.0, 0.0, 0.0, None)])

    def test_point_based_annotation_drag_uses_the_extents_of_all_points(self):
        for annotation_type in ("rect", "oval", "namedview"):
            with self.subTest(annotation_type=annotation_type):
                annotation = self._annotation(annotation_type, [0.0, 0.0, 10.0, 5.0])
                view = self._view(annotation, handle_index=1)
                new_pos = [14.0, 12.0, 30.0, 5.0, 20.0, 40.0]
                view.update_drag_handle_positions(new_pos, "t1")
                cs = view._scene_builder.cs
                self.assertEqual(view.bbox_calls, [(cs, 14.0, 5.0, 30.0, 40.0, 8)])
                self.assertEqual(
                    view.rebuild_calls,
                    [(annotation_type, "t1", 14.0, 5.0, 30.0, 40.0, None)],
                )

    def test_annotation_with_less_than_two_points_uses_a_zero_box(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        view = self._view(annotation, handle_index=1)
        view.update_drag_handle_positions([7.0, 8.0], "t1")
        self.assertEqual(view.rebuild_calls, [("rect", "t1", 0.0, 0.0, 0.0, 0.0, None)])

    def test_bbox_handles_are_updated_only_for_four_or_more_handles(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        for n_handles, expected_calls in ((3, 0), (4, 1), (8, 1)):
            with self.subTest(n_handles=n_handles):
                view = self._view(annotation, n_handles=n_handles, handle_index=1)
                view.update_drag_handle_positions([0.0, 0.0, 10.0, 5.0], "t1")
                self.assertEqual(len(view.bbox_calls), expected_calls)
                self.assertEqual(len(view.outline_calls), expected_calls)
                self.assertEqual(len(view.rebuild_calls), 1)

    def test_highlight_drag_rebuilds_from_the_transformed_highlight_points(self):
        annotation = self._annotation("highlight", [0.0, 0.0, 10.0, 5.0])
        view = self._view(annotation, handle_index=1)
        new_pos = [2.0, 3.0, 12.0, 3.0, 12.0, 9.0, 2.0, 9.0, 99.0]
        view.update_drag_handle_positions(new_pos, "t1")
        coordinates = highlight_position_coordinates(new_pos)
        points = [
            (coordinates[i], coordinates[i + 1])
            for i in range(0, len(coordinates) - 1, 2)
        ]
        self.assertEqual(len(points), 4)
        self.assertEqual(
            view.rebuild_calls, [("highlight", "t1", 2.0, 3.0, 12.0, 9.0, points)]
        )

    def test_body_drag_leaves_the_shape_and_handles_to_the_item_move(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        view = self._view(annotation, handle_index=-1)
        view.update_drag_handle_positions([1.0, 1.0, 11.0, 6.0], "t1")
        self.assertEqual(view.bbox_calls, [])
        self.assertEqual(view.outline_calls, [])
        self.assertEqual(view.rebuild_calls, [])
        self.assertEqual(view._drag_last_valid_new_pos, [1.0, 1.0, 11.0, 6.0])

    def _square_pos(self):
        return [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]

    def test_polygon_vertex_drag_places_handles_and_rebuilds_the_outline(self):
        annotation = self._annotation("polygon", self._square_pos())
        path_item = QGraphicsPathItem()
        path_item.setPos(3.0, 3.0)
        view = self._view(annotation, handle_index=2, items=[path_item])
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(
            self._handles(view),
            [
                (0.0, 0.0),
                (10.0, 0.0),
                (14.0, 12.0),
                (0.0, 10.0),
                (5.0, 0.0),
                (12.0, 6.0),
                (7.0, 11.0),
                (0.0, 5.0),
            ],
        )
        expected = view._build_area_annotation_path(
            ANNOTATION_TYPE_POLYGON,
            [(0.0, 0.0), (10.0, 0.0), (14.0, 12.0), (0.0, 10.0)],
        )
        self.assertEqual(path_item.path(), expected)
        self.assertEqual(path_item.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(view._drag_last_valid_new_pos, new_pos)

    def test_polygon_vertex_drag_that_breaks_validity_returns_before_any_update(self):
        annotation = self._annotation("polygon", self._square_pos())
        path_item = QGraphicsPathItem()
        view = self._view(annotation, handle_index=2, items=[path_item])
        view._drag_last_valid_new_pos = list(self._square_pos())
        bow_tie = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view.update_drag_handle_positions(bow_tie, "t1")
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(view._drag_last_valid_new_pos, self._square_pos())

    def test_polygon_vertex_drag_that_reverses_winding_is_rejected(self):
        annotation = self._annotation("cloud", self._square_pos())
        view = self._view(annotation, handle_index=1)
        view._drag_last_valid_new_pos = list(self._square_pos())
        reversed_square = [0.0, 10.0, 10.0, 10.0, 10.0, 0.0, 0.0, 0.0]
        view.update_drag_handle_positions(reversed_square, "t1")
        self.assertEqual(view._drag_last_valid_new_pos, self._square_pos())
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)

    def test_polygon_body_drag_skips_validity_and_the_outline_rebuild(self):
        annotation = self._annotation("polygon", self._square_pos())
        path_item = QGraphicsPathItem()
        view = self._view(annotation, handle_index=-1, items=[path_item])
        view._drag_last_valid_new_pos = list(self._square_pos())
        # A bow-tie would be invalid for a vertex drag but a body drag never edits shape.
        bow_tie = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view.update_drag_handle_positions(bow_tie, "t1")
        self.assertEqual(
            self._handles(view)[:4],
            [(0.0, 0.0), (10.0, 10.0), (10.0, 0.0), (0.0, 10.0)],
        )
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(view._drag_last_valid_new_pos, bow_tie)

    def test_two_point_polygon_drag_is_not_a_vertex_drag_and_skips_validation(self):
        annotation = self._annotation("polygon", [0.0, 0.0, 10.0, 0.0])
        view = self._view(annotation, n_handles=4, handle_index=1)
        view._drag_last_valid_new_pos = [9.0, 9.0, 9.0, 9.0]
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0], "t1")
        self.assertEqual(view._drag_last_valid_new_pos, [0.0, 0.0, 10.0, 0.0])
        self.assertEqual(self._handles(view)[:3], [(0.0, 0.0), (10.0, 0.0), (5.0, 0.0)])

    def test_polygon_handles_need_at_least_one_handle_per_point(self):
        annotation = self._annotation("polygon", self._square_pos())
        new_pos = [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]
        view = self._view(annotation, n_handles=3, handle_index=2)
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 3)
        view = self._view(annotation, n_handles=4, handle_index=2)
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(
            self._handles(view), [(0.0, 0.0), (10.0, 0.0), (14.0, 12.0), (0.0, 10.0)]
        )
        view = self._view(annotation, n_handles=6, handle_index=2)
        view.update_drag_handle_positions(new_pos, "t1")
        self.assertEqual(self._handles(view)[4:], [(5.0, 0.0), (12.0, 6.0)])

    def test_polygon_with_fewer_than_four_values_is_ignored_by_the_shape_update(self):
        annotation = self._annotation("polygon", self._square_pos())
        path_item = QGraphicsPathItem()
        view = self._view(annotation, handle_index=2, items=[path_item])
        view.update_drag_handle_positions([1.0, 1.0], "t1")
        self.assertTrue(path_item.path().isEmpty())
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)
        self.assertEqual(view._drag_last_valid_new_pos, [1.0, 1.0])

    def _body_items(self, annotation, orig_position):
        item = QGraphicsPathItem()
        other = QGraphicsPathItem()
        outline = QGraphicsPolygonItem()
        item.setPos(10.0, 20.0)
        other.setPos(30.0, 40.0)
        outline.setPos(50.0, 60.0)
        stray = QGraphicsPathItem()
        stray.setPos(70.0, 80.0)
        view = self._view(
            annotation, handle_index=-1, items=[item, other], selection=[outline, stray]
        )
        view._drag_item_orig_positions = {
            id(item): item.pos(),
            id(other): other.pos(),
            id(outline): outline.pos(),
        }
        view._drag_orig_position = list(orig_position)
        return view, item, other, outline, stray

    def test_body_drag_moves_items_and_selection_outlines_by_the_ost_delta(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        view, item, other, outline, stray = self._body_items(
            annotation, [0.0, 0.0, 10.0, 5.0]
        )
        view.update_drag_handle_positions([2.0, 3.0, 12.0, 8.0], "t1", 500.0, 500.0)
        self.assertEqual(item.pos(), QtCore.QPointF(10.0 + 144.0, 20.0 + 216.0))
        self.assertEqual(other.pos(), QtCore.QPointF(30.0 + 144.0, 40.0 + 216.0))
        self.assertEqual(outline.pos(), QtCore.QPointF(50.0 + 144.0, 60.0 + 216.0))
        self.assertEqual(stray.pos(), QtCore.QPointF(70.0, 80.0))

    def test_ink_body_drag_skips_the_leading_style_value(self):
        annotation = self._annotation("ink", [9.0, 0.0, 0.0, 10.0, 5.0])
        view, item, _other, _outline, _stray = self._body_items(
            annotation, [9.0, 0.0, 0.0, 10.0, 5.0]
        )
        view.update_drag_handle_positions(
            [9.0, 2.0, 3.0, 12.0, 8.0], "t1", 500.0, 500.0
        )
        self.assertEqual(item.pos(), QtCore.QPointF(10.0 + 144.0, 20.0 + 216.0))

    def test_non_ink_odd_length_body_drag_does_not_skip_a_value(self):
        annotation = self._annotation("polygon", [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0])
        view, item, _other, _outline, _stray = self._body_items(
            annotation, [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0]
        )
        view.update_drag_handle_positions(
            [2.0, 3.0, 12.0, 3.0, 12.0, 13.0, 5.0], "t1", 500.0, 500.0
        )
        self.assertEqual(item.pos(), QtCore.QPointF(10.0 + 144.0, 20.0 + 216.0))

    def test_body_drag_falls_back_to_scene_deltas_when_positions_are_too_short(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        for orig, new_pos in (
            ([], [2.0, 3.0, 12.0, 8.0]),
            ([0.0], [2.0, 3.0, 12.0, 8.0]),
            ([0.0, 0.0, 10.0, 5.0], [2.0]),
            ([0.0, 0.0, 10.0, 5.0], [2.0, 3.0]),
            ([0.0, 0.0], [2.0, 3.0]),
        ):
            with self.subTest(orig=orig, new=new_pos):
                view, item, _other, _outline, _stray = self._body_items(
                    annotation, orig
                )
                if len(new_pos) == 2:
                    # Two values are enough for a rectangle delta: it is not a fallback.
                    view.update_drag_handle_positions(new_pos, "t1", 5.0, 7.0)
                    self.assertEqual(
                        item.pos(), QtCore.QPointF(10.0 + 144.0, 20.0 + 216.0)
                    )
                else:
                    view.update_drag_handle_positions(new_pos, "t1", 5.0, 7.0)
                    self.assertEqual(item.pos(), QtCore.QPointF(15.0, 27.0))

    def test_ink_body_drag_requires_start_plus_two_values(self):
        annotation = self._annotation("ink", [9.0, 0.0, 0.0])
        view, item, _other, _outline, _stray = self._body_items(annotation, [9.0, 0.0])
        view.update_drag_handle_positions([9.0, 2.0, 3.0], "t1", 5.0, 7.0)
        self.assertEqual(item.pos(), QtCore.QPointF(15.0, 27.0))
        view, item, _other, _outline, _stray = self._body_items(
            annotation, [9.0, 0.0, 0.0]
        )
        view.update_drag_handle_positions([9.0], "t1", 5.0, 7.0)
        self.assertEqual(item.pos(), QtCore.QPointF(15.0, 27.0))

    def test_body_drag_without_recorded_item_positions_moves_nothing(self):
        annotation = self._annotation("rect", [0.0, 0.0, 10.0, 5.0])
        view, item, _other, _outline, _stray = self._body_items(
            annotation, [0.0, 0.0, 10.0, 5.0]
        )
        view._drag_item_orig_positions = {}
        view.update_drag_handle_positions([2.0, 3.0, 12.0, 8.0], "t1", 5.0, 7.0)
        self.assertEqual(item.pos(), QtCore.QPointF(10.0, 20.0))


class AnnotationShapeHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(self, items=None, selection=None, n_handles=8):
        base = UpdateDragHandlePositionsTests(
            "test_unknown_takeoffs_and_conditions_change_nothing"
        )
        view = base._view(items=items, n_handles=n_handles)
        view._selection_items = list(selection or [])
        return view

    @staticmethod
    def _handles(view):
        return [(h.item.pos().x(), h.item.pos().y()) for h in view._handle_infos]

    def test_bbox_handles_follow_the_corners_and_edge_midpoints(self):
        view = self._view()
        view._update_bbox_handles(view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0, 8)
        self.assertEqual(
            self._handles(view),
            [
                (10.0, 20.0),
                (50.0, 20.0),
                (50.0, 80.0),
                (10.0, 80.0),
                (30.0, 20.0),
                (50.0, 50.0),
                (30.0, 80.0),
                (10.0, 50.0),
            ],
        )

    def test_bbox_handles_beyond_the_available_count_are_skipped(self):
        view = self._view(n_handles=6)
        view._update_bbox_handles(view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0, 6)
        self.assertEqual(
            self._handles(view)[3:], [(10.0, 80.0), (30.0, 20.0), (50.0, 50.0)]
        )
        view = self._view(n_handles=3)
        view._update_bbox_handles(view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0, 3)
        self.assertEqual(
            self._handles(view), [(10.0, 20.0), (50.0, 20.0), (50.0, 80.0)]
        )

    def test_selection_outline_follows_the_first_polygon_item_of_the_annotation(self):
        first = QGraphicsPolygonItem()
        second = QGraphicsPolygonItem()
        other = QGraphicsPolygonItem()
        for item, uid in ((first, "t1"), (second, "t1"), (other, "other")):
            item.setData(0, uid)
        rect_item = QGraphicsRectItem()
        rect_item.setData(0, "t1")
        view = self._view(selection=[rect_item, other, first, second])
        view._update_annotation_selection_outline_from_box(
            "t1", view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0
        )
        self.assertEqual(
            first.polygon().boundingRect(), QtCore.QRectF(10.0, 20.0, 40.0, 60.0)
        )
        self.assertEqual(first.polygon().count(), 4)
        self.assertTrue(second.polygon().isEmpty())
        self.assertTrue(other.polygon().isEmpty())

    def test_selection_outline_needs_a_complete_box_transform(self):
        outline = QGraphicsPolygonItem()
        outline.setData(0, "t1")
        view = self._view(selection=[outline])
        view._scene_builder.cs.truncate_to = 6
        view._update_annotation_selection_outline_from_box(
            "t1", view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0
        )
        self.assertTrue(outline.polygon().isEmpty())

    def test_rebuild_ignores_an_annotation_without_preview_items(self):
        view = self._view()
        view._uid_to_items = {}
        self.assertIsNone(
            view._rebuild_ann_shape_path("rect", "t1", 0.0, 0.0, 10.0, 10.0)
        )
        self.assertEqual(view._uid_to_items, {})
        view._uid_to_items = {"t1": []}
        self.assertIsNone(
            view._rebuild_ann_shape_path("rect", "t1", 0.0, 0.0, 10.0, 10.0)
        )
        self.assertEqual(view._uid_to_items, {"t1": []})
        self.assertEqual(view._scene.items(), [])

    def test_rect_annotation_path_is_a_normalised_rectangle(self):
        main = QGraphicsPathItem()
        main.setPos(4.0, 4.0)
        view = self._view(items=[main])
        view._rebuild_ann_shape_path("rect", "t1", 30.0, 50.0, 10.0, 20.0)
        self.assertEqual(
            main.path().boundingRect(), QtCore.QRectF(10.0, 20.0, 20.0, 30.0)
        )
        self.assertEqual(main.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(main.path().elementCount(), 5)

    def test_oval_annotation_path_is_an_ellipse_and_clears_rotation(self):
        main = QGraphicsPathItem()
        main.setRotation(30.0)
        main.setPos(4.0, 4.0)
        view = self._view(items=[main])
        view._rebuild_ann_shape_path("oval", "t1", 30.0, 50.0, 10.0, 20.0)
        expected = QPainterPath()
        expected.addEllipse(QtCore.QRectF(10.0, 20.0, 20.0, 30.0))
        self.assertEqual(main.path(), expected)
        self.assertEqual(main.rotation(), 0.0)
        self.assertEqual(main.pos(), QtCore.QPointF(0.0, 0.0))

    def test_rect_annotation_does_not_reset_rotation(self):
        main = QGraphicsPathItem()
        main.setRotation(30.0)
        view = self._view(items=[main])
        view._rebuild_ann_shape_path("rect", "t1", 30.0, 50.0, 10.0, 20.0)
        self.assertEqual(main.rotation(), 30.0)

    def test_highlight_annotation_path_is_built_from_the_highlight_points(self):
        main = QGraphicsPathItem()
        main.setPos(4.0, 4.0)
        view = self._view(items=[main])
        points = [(0.0, 0.0), (20.0, 0.0), (20.0, 5.0), (0.0, 5.0)]
        view._rebuild_ann_shape_path("highlight", "t1", 0.0, 0.0, 20.0, 5.0, points)
        self.assertEqual(main.path(), build_highlight_path(points))
        self.assertEqual(main.pos(), QtCore.QPointF(0.0, 0.0))
        main2 = QGraphicsPathItem()
        view = self._view(items=[main2])
        view._rebuild_ann_shape_path("highlight", "t1", 0.0, 0.0, 20.0, 5.0)
        self.assertEqual(main2.path(), build_highlight_path([(0.0, 0.0), (20.0, 5.0)]))

    def test_rect_item_annotation_moves_followers_by_the_rect_displacement(self):
        main = QGraphicsRectItem(QtCore.QRectF(5.0, 6.0, 10.0, 10.0))
        main.setPos(2.0, 3.0)
        follower = QGraphicsPathItem()
        follower.setPos(100.0, 200.0)
        view = self._view(items=[main, follower])
        view._rebuild_ann_shape_path("rect", "t1", 40.0, 70.0, 20.0, 30.0)
        # The old top-left was (7, 9) in the scene; the new rect starts at (20, 30).
        self.assertEqual(main.rect(), QtCore.QRectF(20.0, 30.0, 20.0, 40.0))
        self.assertEqual(main.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertEqual(follower.pos(), QtCore.QPointF(113.0, 221.0))

    def test_text_annotation_item_is_repositioned_resized_and_unrotated(self):
        main = QGraphicsTextItem("text")
        main.setRotation(25.0)
        view = self._view(items=[main])
        view._rebuild_ann_shape_path("text", "t1", 40.0, 70.0, 20.0, 30.0)
        self.assertEqual(main.pos(), QtCore.QPointF(20.0, 30.0))
        self.assertEqual(main.rotation(), 0.0)
        self.assertEqual(main.transformOriginPoint(), QtCore.QPointF(10.0, 20.0))
        self.assertEqual(main.textWidth(), 20.0)

    def test_clipped_text_annotation_item_gets_a_zero_origin_clip_rect(self):
        main = ClippedTextGraphicsItem("text", QtCore.QRectF(0.0, 0.0, 5.0, 5.0))
        view = self._view(items=[main])
        view._rebuild_ann_shape_path("text", "t1", 40.0, 70.0, 20.0, 30.0)
        self.assertEqual(main.clip_rect(), QtCore.QRectF(0.0, 0.0, 20.0, 40.0))
        self.assertEqual(main.textWidth(), 20.0)


class HierarchyDragTests(unittest.TestCase):
    SQUARE_100 = [0.0, 0.0, 100.0, 0.0, 100.0, 100.0, 0.0, 100.0]

    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    @staticmethod
    def _square(left, top, right, bottom):
        return [left, top, right, top, right, bottom, left, bottom]

    @staticmethod
    def _takeoff(uid, condition_uid, position, parent="0", page="pg1", rotation=0.0):
        return Takeoff(
            uid=uid,
            condition_uid=condition_uid,
            page_uid=page,
            area_uid="area-1",
            position=list(position),
            parent_uid=parent,
            rotation=rotation,
        )

    @staticmethod
    def _conditions():
        return [
            Condition(
                uid="ca", condition_type=Condition.TYPE_AREA, pattern=3, spacing=2.0
            ),
            Condition(
                uid="cat",
                condition_type=Condition.TYPE_ATTACHMENT,
                shape=3,
                width=10.0,
                depth=4.0,
            ),
            Condition(uid="cl", condition_type=Condition.TYPE_LINEAR),
        ]

    def _view(self, takeoffs, conditions=None, items=None):
        base = UpdateDragHandlePositionsTests(
            "test_unknown_takeoffs_and_conditions_change_nothing"
        )
        view = base._view(items=items)
        for name in (
            "_validate_hole_position",
            "_validate_parent_contains_holes",
            "_has_child_holes",
            "_rebuild_parent_with_holes",
            "_update_parent_hole_path",
        ):
            delattr(view, name)
        view._current_takeoffs = {t.uid: t for t in takeoffs}
        view._current_conditions = {
            c.uid: c
            for c in (conditions if conditions is not None else self._conditions())
        }
        return view

    @staticmethod
    def _rect_path(left, top, right, bottom):
        path = QPainterPath()
        path.addRect(left, top, right - left, bottom - top)
        return path

    # ---- _has_child_holes
    def test_has_child_holes_reports_only_children_of_that_parent(self):
        view = self._view(
            [
                self._takeoff("p", "ca", self.SQUARE_100),
                self._takeoff("h", "ca", self._square(1, 1, 2, 2), parent="p"),
                self._takeoff("lonely", "ca", self.SQUARE_100),
            ]
        )
        self.assertIs(view._has_child_holes("p"), True)
        self.assertIs(view._has_child_holes("lonely"), False)
        self.assertIs(view._has_child_holes("missing"), False)

    # ---- _attachment_position_valid
    def _attachment_view(self, **overrides):
        parent = overrides.get("parent") or self._takeoff("p", "ca", self.SQUARE_100)
        attachment = overrides.get("attachment") or self._takeoff(
            "a", "cat", [20.0, 20.0], parent="p"
        )
        extra = overrides.get("extra", [])
        conditions = overrides.get("conditions")
        view = self._view([parent, attachment, *extra], conditions)
        return view, attachment

    def test_attachment_inside_its_area_is_valid(self):
        view, attachment = self._attachment_view()
        self.assertIs(view._attachment_position_valid(attachment, [20.0, 20.0]), True)
        self.assertIs(
            view._attachment_position_valid(attachment, [150.0, 150.0]), False
        )
        self.assertIs(view._attachment_position_valid(attachment, [99.0, 50.0]), False)

    def test_attachment_needs_a_parent_on_the_same_page(self):
        view, attachment = self._attachment_view()
        orphan = self._takeoff("orphan", "cat", [20.0, 20.0], parent="ghost")
        view._current_takeoffs["orphan"] = orphan
        self.assertIs(view._attachment_position_valid(orphan, [20.0, 20.0]), False)
        other_page = self._takeoff("moved", "cat", [20.0, 20.0], parent="p", page="pg2")
        view._current_takeoffs["moved"] = other_page
        self.assertIs(view._attachment_position_valid(other_page, [20.0, 20.0]), False)

    def test_attachment_parent_must_be_a_top_level_area_with_a_known_condition(self):
        cases = {
            "unknown parent condition": self._takeoff("p", "ghost", self.SQUARE_100),
            "non-area parent": self._takeoff("p", "cl", self.SQUARE_100),
            "hole parent": self._takeoff("p", "ca", self.SQUARE_100, parent="grand"),
        }
        for label, parent in cases.items():
            with self.subTest(label):
                view, attachment = self._attachment_view(parent=parent)
                self.assertIs(
                    view._attachment_position_valid(attachment, [20.0, 20.0]), False
                )

    def test_attachment_condition_must_exist_and_be_an_attachment(self):
        for condition_uid in ("ghost", "ca", "cl"):
            with self.subTest(condition_uid=condition_uid):
                attachment = self._takeoff("a", condition_uid, [20.0, 20.0], parent="p")
                view, attachment = self._attachment_view(attachment=attachment)
                self.assertIs(
                    view._attachment_position_valid(attachment, [20.0, 20.0]), False
                )

    def test_attachment_uses_an_overriding_parent_position(self):
        view, attachment = self._attachment_view()
        small = self._square(0, 0, 10, 10)
        self.assertIs(
            view._attachment_position_valid(attachment, [20.0, 20.0], small), False
        )
        large = self._square(0, 0, 500, 500)
        self.assertIs(
            view._attachment_position_valid(attachment, [300.0, 300.0], large), True
        )

    def test_attachment_avoids_area_backouts_but_not_other_children(self):
        hole = self._takeoff("h", "ca", self._square(40, 40, 60, 60), parent="p")
        sibling_attachment = self._takeoff("b", "cat", [50.0, 50.0], parent="p")
        foreign_hole = self._takeoff(
            "fh", "ca", self._square(40, 40, 60, 60), parent="q"
        )
        view, attachment = self._attachment_view(
            extra=[sibling_attachment, foreign_hole]
        )
        self.assertIs(view._attachment_position_valid(attachment, [50.0, 50.0]), True)
        view._current_takeoffs["h"] = hole
        self.assertIs(view._attachment_position_valid(attachment, [50.0, 50.0]), False)
        self.assertIs(view._attachment_position_valid(attachment, [20.0, 20.0]), True)

    def test_attachment_backout_positions_can_be_overridden_per_takeoff(self):
        hole = self._takeoff("h", "ca", self._square(40, 40, 60, 60), parent="p")
        view, attachment = self._attachment_view(extra=[hole])
        self.assertIs(
            view._attachment_position_valid(
                attachment,
                [50.0, 50.0],
                takeoff_positions={"h": self._square(80, 80, 90, 90)},
            ),
            True,
        )
        self.assertIs(
            view._attachment_position_valid(
                attachment,
                [50.0, 50.0],
                takeoff_positions={"other": self._square(0, 0, 1, 1)},
            ),
            False,
        )
        self.assertIs(
            view._attachment_position_valid(
                attachment, [50.0, 50.0], takeoff_positions={}
            ),
            False,
        )

    def test_attachment_rotation_defaults_to_the_takeoff_rotation_unless_overridden(
        self,
    ):
        quarter_turn = math.pi / 2
        upright = self._takeoff("a", "cat", [50.0, 3.0], parent="p", rotation=0.0)
        turned = self._takeoff(
            "a", "cat", [50.0, 3.0], parent="p", rotation=quarter_turn
        )
        view, upright = self._attachment_view(attachment=upright)
        view._current_takeoffs["a"] = upright
        self.assertIs(view._attachment_position_valid(upright, [50.0, 3.0]), True)
        self.assertIs(
            view._attachment_position_valid(
                upright, [50.0, 3.0], rotation=quarter_turn
            ),
            False,
        )
        view._current_takeoffs["a"] = turned
        self.assertIs(view._attachment_position_valid(turned, [50.0, 3.0]), False)
        self.assertIs(
            view._attachment_position_valid(turned, [50.0, 3.0], rotation=0.0), True
        )

    # ---- _takeoff_children_valid_for_geometry_changes
    def _family(self):
        return self._view(
            [
                self._takeoff("p", "ca", self.SQUARE_100),
                self._takeoff("h1", "ca", self._square(10, 10, 30, 30), parent="p"),
                self._takeoff("h2", "ca", self._square(50, 50, 70, 70), parent="p"),
                self._takeoff("a", "cat", [90.0, 90.0], parent="p"),
                self._takeoff("free", "cl", [1.0, 1.0, 2.0, 2.0]),
            ]
        )

    def test_overrides_that_touch_no_hierarchy_are_always_valid(self):
        view = self._family()
        self.assertIs(view._takeoff_children_valid_for_geometry_changes({}), True)
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes({"unknown": [0.0, 0.0]}),
            True,
        )
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"free": [5.0, 5.0, 6.0, 6.0]}
            ),
            True,
        )
        view._current_takeoffs["nocond"] = self._takeoff("nocond", "ghost", [1.0, 1.0])
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes({"nocond": [5.0, 5.0]}),
            True,
        )

    def test_moving_a_hole_keeps_it_inside_the_parent_and_off_its_siblings(self):
        view = self._family()
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"h1": self._square(10, 10, 25, 25)}), True)
        self.assertIs(check({"h1": self._square(45, 45, 65, 65)}), False)
        self.assertIs(check({"h1": self._square(150, 150, 170, 170)}), False)
        self.assertIs(
            check(
                {"h1": self._square(10, 10, 25, 25), "h2": self._square(20, 20, 40, 40)}
            ),
            False,
        )

    def test_resizing_the_parent_checks_holes_and_attachments(self):
        view = self._family()
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"p": list(self.SQUARE_100)}), True)
        self.assertIs(check({"p": self._square(0, 0, 60, 60)}), False)
        # Holes fit in an 80x80 parent but the attachment at (90, 90) does not.
        self.assertIs(check({"p": self._square(0, 0, 80, 80)}), False)
        self.assertIs(check({"p": self._square(0, 0, 80, 80), "a": [60.0, 20.0]}), True)

    def test_moving_an_attachment_must_keep_it_in_the_area_and_out_of_the_holes(self):
        view = self._family()
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"a": [90.0, 20.0]}), True)
        self.assertIs(check({"a": [150.0, 20.0]}), False)
        self.assertIs(check({"a": [60.0, 60.0]}), False)

    def test_attachment_rotation_overrides_are_validated(self):
        view = self._view(
            [
                self._takeoff("p", "ca", self.SQUARE_100),
                self._takeoff("a", "cat", [50.0, 3.0], parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({}, {"a": 0.0}), True)
        self.assertIs(check({}, {"a": math.pi / 2}), False)
        self.assertIs(check({"a": [50.0, 3.0]}, None), True)
        view._current_takeoffs["a"].rotation = math.pi / 2
        self.assertIs(check({"a": [50.0, 3.0]}, {}), False)
        self.assertIs(check({"a": [50.0, 3.0]}, {"a": 0.0}), True)

    def test_children_with_unknown_conditions_or_inconsistent_parents_are_invalid(self):
        view = self._family()
        view._current_takeoffs["mystery"] = self._takeoff(
            "mystery", "ghost", [1.0, 1.0], parent="p"
        )
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"p": list(self.SQUARE_100)}
            ),
            False,
        )
        view = self._family()
        view._current_takeoffs["h2"].page_uid = "pg2"
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"p": list(self.SQUARE_100)}
            ),
            False,
        )

    def test_holes_of_a_missing_or_non_area_parent_are_invalid(self):
        view = self._view(
            [self._takeoff("h", "ca", self._square(1, 1, 2, 2), parent="ghost")]
        )
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"h": self._square(1, 1, 3, 3)}
            ),
            False,
        )
        view = self._view(
            [
                self._takeoff("p", "cl", [0.0, 0.0, 9.0, 9.0]),
                self._takeoff("h", "ca", self._square(1, 1, 2, 2), parent="p"),
            ]
        )
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"h": self._square(1, 1, 3, 3)}
            ),
            False,
        )

    def test_children_that_are_neither_areas_nor_attachments_are_not_checked(self):
        view = self._family()
        view._current_takeoffs["line"] = self._takeoff(
            "line", "cl", [500.0, 500.0, 600.0, 600.0], parent="p"
        )
        self.assertIs(
            view._takeoff_children_valid_for_geometry_changes(
                {"p": list(self.SQUARE_100)}
            ),
            True,
        )

    # ---- _validate_parent_contains_holes
    def test_parent_must_contain_every_hole_and_attachment(self):
        view = self._family()
        validate = view._validate_parent_contains_holes
        self.assertIs(validate("p", list(self.SQUARE_100)), True)
        self.assertIs(validate("p", self._square(0, 0, 60, 60)), False)
        self.assertIs(validate("p", self._square(0, 0, 80, 80)), False)
        self.assertIs(validate("p", self._square(0, 0, 500, 500)), True)

    def test_parent_validation_ignores_unrelated_unknown_and_short_children(self):
        view = self._family()
        view._current_takeoffs["unknown"] = self._takeoff(
            "unknown", "ghost", self._square(500, 500, 600, 600), parent="p"
        )
        view._current_takeoffs["short"] = self._takeoff(
            "short", "ca", [500.0, 500.0, 1.0, 1.0], parent="p"
        )
        view._current_takeoffs["line"] = self._takeoff(
            "line", "cl", [500.0, 500.0, 600.0, 600.0], parent="p"
        )
        view._current_takeoffs["foreign"] = self._takeoff(
            "foreign", "ca", self._square(500, 500, 600, 600), parent="q"
        )
        self.assertIs(
            view._validate_parent_contains_holes("p", list(self.SQUARE_100)), True
        )

    def test_parent_validation_attachment_check_uses_the_new_parent_shape(self):
        view = self._view(
            [
                self._takeoff("p", "ca", self.SQUARE_100),
                self._takeoff("a", "cat", [90.0, 90.0], parent="p"),
            ]
        )
        self.assertIs(
            view._validate_parent_contains_holes("p", self._square(0, 0, 96, 96)), True
        )
        self.assertIs(
            view._validate_parent_contains_holes("p", self._square(0, 0, 80, 80)), False
        )

    # ---- _validate_hole_position
    def _hole_view(self):
        hole = self._takeoff("h", "ca", self._square(10, 10, 20, 20), parent="p")
        return (
            self._view(
                [
                    self._takeoff("p", "ca", self.SQUARE_100),
                    hole,
                    self._takeoff(
                        "sib", "ca", self._square(50, 50, 70, 70), parent="p"
                    ),
                    self._takeoff("a", "cat", [90.0, 90.0], parent="p"),
                ]
            ),
            hole,
        )

    def test_hole_position_must_be_inside_the_parent(self):
        view, hole = self._hole_view()
        self.assertIs(
            view._validate_hole_position(hole, self._square(10, 10, 30, 30)), True
        )
        self.assertIs(
            view._validate_hole_position(hole, self._square(90, 90, 120, 120)), False
        )

    def test_hole_without_a_usable_parent_is_invalid(self):
        view, hole = self._hole_view()
        orphan = self._takeoff("o", "ca", self._square(1, 1, 2, 2), parent="ghost")
        self.assertIs(
            view._validate_hole_position(orphan, self._square(1, 1, 2, 2)), False
        )
        view._current_takeoffs["p"].position = [0.0, 0.0, 10.0, 10.0]
        self.assertIs(
            view._validate_hole_position(hole, self._square(1, 1, 2, 2)), False
        )
        view._current_takeoffs["p"].position = []
        self.assertIs(
            view._validate_hole_position(hole, self._square(1, 1, 2, 2)), False
        )

    def test_hole_position_must_not_overlap_sibling_holes_or_attachments(self):
        view, hole = self._hole_view()
        self.assertIs(
            view._validate_hole_position(hole, self._square(40, 40, 60, 60)), False
        )
        self.assertIs(
            view._validate_hole_position(hole, self._square(80, 80, 98, 98)), False
        )
        self.assertIs(
            view._validate_hole_position(hole, self._square(10, 10, 20, 20)), True
        )

    def test_hole_validation_ignores_unrelated_children(self):
        view, hole = self._hole_view()
        view._current_takeoffs["foreign"] = self._takeoff(
            "foreign", "ca", self._square(30, 30, 40, 40), parent="q"
        )
        view._current_takeoffs["ghost"] = self._takeoff(
            "ghost", "nope", self._square(30, 30, 40, 40), parent="p"
        )
        view._current_takeoffs["line"] = self._takeoff(
            "line", "cl", [30.0, 30.0, 40.0, 40.0], parent="p"
        )
        view._current_takeoffs["short"] = self._takeoff(
            "short", "ca", [30.0, 30.0], parent="p"
        )
        view._current_takeoffs["foreign_attachment"] = self._takeoff(
            "foreign_attachment", "cat", [35.0, 35.0], parent="q"
        )
        self.assertIs(
            view._validate_hole_position(hole, self._square(25, 25, 45, 45)), True
        )

    def test_hole_validation_moves_its_own_old_position_out_of_the_way(self):
        view, hole = self._hole_view()
        self.assertIs(
            view._validate_hole_position(hole, self._square(12, 12, 22, 22)), True
        )

    # ---- parent outline rebuilding
    def _outline_view(self, with_parent_condition=True):
        text = QGraphicsTextItem("label")
        first = QGraphicsPathItem()
        first.setPos(7.0, 7.0)
        second = QGraphicsPathItem()
        view = self._view(
            [
                self._takeoff(
                    "p",
                    "ca" if with_parent_condition else "ghost",
                    self._square(0, 0, 20, 20),
                ),
                self._takeoff("h1", "ca", self._square(2, 2, 6, 6), parent="p"),
                self._takeoff("h2", "ca", self._square(10, 10, 14, 14), parent="p"),
                self._takeoff("short", "ca", [15.0, 15.0], parent="p"),
                self._takeoff("foreign", "ca", self._square(16, 2, 19, 5), parent="q"),
            ],
            items=[text, first, second],
        )
        view._uid_to_items = {"p": [text, first, second]}
        return view, first, second

    def test_dragged_hole_replaces_its_stored_shape_in_the_parent_outline(self):
        view, first, second = self._outline_view()
        view._update_parent_hole_path("p", "h1", self._rect_path(3, 3, 8, 8))
        path = first.path()
        self.assertEqual(path.boundingRect(), QtCore.QRectF(0.0, 0.0, 20.0, 20.0))
        for point, expected in (
            ((5.0, 5.0), False),
            ((12.0, 12.0), False),
            ((2.5, 2.5), True),
            ((17.0, 3.0), True),
            ((18.0, 18.0), True),
            ((15.0, 15.0), True),
        ):
            with self.subTest(point=point):
                self.assertIs(path.contains(QtCore.QPointF(*point)), expected)
        self.assertEqual(first.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertTrue(second.path().isEmpty())
        self.assertEqual(
            view.calls,
            [
                ("pattern", ("p", first, path, view._current_conditions["ca"])),
                ("labels", "p"),
            ],
        )

    def test_parent_outline_update_without_a_parent_condition_still_refreshes_labels(
        self,
    ):
        view, first, _second = self._outline_view(with_parent_condition=False)
        view._update_parent_hole_path("p", "h1", self._rect_path(3, 3, 8, 8))
        self.assertFalse(first.path().isEmpty())
        self.assertEqual(view.calls, [("labels", "p")])

    def test_parent_outline_update_is_skipped_for_missing_or_degenerate_parents(self):
        view, first, _second = self._outline_view()
        view._update_parent_hole_path("ghost", "h1", self._rect_path(3, 3, 8, 8))
        view._current_takeoffs["p"].position = [0.0, 0.0, 20.0, 20.0]
        view._update_parent_hole_path("p", "h1", self._rect_path(3, 3, 8, 8))
        view._current_takeoffs["p"].position = []
        view._update_parent_hole_path("p", "h1", self._rect_path(3, 3, 8, 8))
        self.assertTrue(first.path().isEmpty())
        self.assertEqual(view.calls, [])

    def test_parent_outline_update_needs_a_path_item_to_refresh_labels(self):
        view, _first, _second = self._outline_view()
        view._uid_to_items = {"p": [QGraphicsTextItem("only text")]}
        view._update_parent_hole_path("p", "h1", self._rect_path(3, 3, 8, 8))
        self.assertEqual(view.calls, [])

    def test_rebuilt_parent_outline_cuts_every_child_hole_out_of_the_given_path(self):
        view, first, second = self._outline_view()
        view._rebuild_parent_with_holes("p", self._rect_path(0, 0, 20, 20))
        path = first.path()
        for point, expected in (
            ((4.0, 4.0), False),
            ((12.0, 12.0), False),
            ((8.0, 8.0), True),
            ((17.0, 3.0), True),
            ((15.0, 15.0), True),
        ):
            with self.subTest(point=point):
                self.assertIs(path.contains(QtCore.QPointF(*point)), expected)
        self.assertEqual(first.pos(), QtCore.QPointF(0.0, 0.0))
        self.assertTrue(second.path().isEmpty())
        self.assertEqual(
            view.calls,
            [
                ("pattern", ("p", first, path, view._current_conditions["ca"])),
                ("labels", "p"),
            ],
        )

    def test_rebuilt_parent_outline_without_the_parent_takeoff_only_refreshes_labels(
        self,
    ):
        view, first, _second = self._outline_view()
        del view._current_takeoffs["p"]
        view._rebuild_parent_with_holes("p", self._rect_path(0, 0, 20, 20))
        self.assertFalse(first.path().isEmpty())
        self.assertEqual(view.calls, [("labels", "p")])

    def test_rebuilt_parent_outline_without_a_parent_condition_only_refreshes_labels(
        self,
    ):
        view, first, _second = self._outline_view(with_parent_condition=False)
        view._rebuild_parent_with_holes("p", self._rect_path(0, 0, 20, 20))
        self.assertEqual(view.calls, [("labels", "p")])

    def test_rebuilt_parent_outline_leaves_the_given_path_unchanged(self):
        view, _first, _second = self._outline_view()
        parent_path = self._rect_path(0, 0, 20, 20)
        view._rebuild_parent_with_holes("p", parent_path)
        self.assertEqual(parent_path, self._rect_path(0, 0, 20, 20))


class UpdateDragGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(self, **kwargs):
        base = UpdateDragHandlePositionsTests(
            "test_unknown_takeoffs_and_conditions_change_nothing"
        )
        return base._view(**kwargs), base

    @staticmethod
    def _handles(view):
        return [(h.item.pos().x(), h.item.pos().y()) for h in view._handle_infos]

    @staticmethod
    def _elements(path):
        return [
            (path.elementAt(i).type, path.elementAt(i).x, path.elementAt(i).y)
            for i in range(path.elementCount())
        ]

    def _takeoff(self, position, **kwargs):
        return UpdateDragHandlePositionsTests._takeoff(position, **kwargs)

    def test_truncated_transforms_do_not_move_the_preview_items(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        for truncate_to in (0, 1):
            with self.subTest(truncate_to=truncate_to):
                item = QGraphicsPathItem()
                item.setPos(10.0, 20.0)
                view, _base = self._view(
                    takeoff=self._takeoff([5.0, 6.0]),
                    condition=condition,
                    handle_index=-1,
                    items=[item],
                )
                view._drag_item_orig_positions = {id(item): item.pos()}
                view._drag_orig_position = [5.0, 6.0]
                view._scene_builder.cs.truncate_to = truncate_to
                view.update_drag_handle_positions([36.0, 72.0], "t1", 5.0, 7.0)
                self.assertEqual(item.pos(), QtCore.QPointF(10.0, 20.0))
                self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)

    def test_linear_drag_with_too_few_transformed_values_or_handles_places_nothing(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=6.0
        )
        for truncate_to, n_handles in ((2, 8), (3, 8), (4, 1), (4, 0)):
            with self.subTest(truncate_to=truncate_to, n_handles=n_handles):
                path_item = QGraphicsPathItem()
                view, _base = self._view(
                    takeoff=self._takeoff([0.0, 0.0, 6.0, 8.0]),
                    condition=condition,
                    n_handles=n_handles,
                    handle_index=1,
                    items=[path_item],
                )
                view._scene_builder.cs.truncate_to = truncate_to
                view.update_drag_handle_positions([1.0, 2.0, 7.0, 10.0], "t1")
                self.assertEqual(self._handles(view), [(0.0, 0.0)] * n_handles)
                if truncate_to < 4:
                    self.assertTrue(path_item.path().isEmpty())

    def test_curved_linear_drag_transforms_only_six_values_of_the_control_geometry(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        geometry = _ScriptedLinearGeometry(
            (1.0, 2.0, 3.0, 4.0, 5.5, 6.5),
            [(0.0, 0.0), (1.0, 1.0)],
            ([(0.0, 1.0), (1.0, 2.0)], [(0.0, -1.0), (1.0, 0.0)]),
        )
        path_item = QGraphicsPathItem()
        view, _base = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0, 0.5]),
            condition=condition,
            n_handles=3,
            handle_index=2,
            items=[path_item],
            linear_geom=geometry,
        )
        view._scene_builder.cs.transform_calls = []
        view.update_drag_handle_positions([0.0, 1.0, 10.0, 2.0, 5.0, 3.0, 0.5], "t1")
        self.assertEqual(
            [len(call) for call in view._scene_builder.cs.transform_calls], [7, 6, 6]
        )
        self.assertEqual(len(geometry.proc_calls[0]), 7)

    def test_curved_linear_drag_with_exactly_two_curve_points_still_builds_the_curve(
        self,
    ):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=8.0
        )
        geometry = _ScriptedLinearGeometry(
            (1.0, 2.0, 3.0, 4.0, 5.5, 6.5),
            [(0.0, 0.0), (1.0, 1.0)],
            ([(0.0, 1.0), (1.0, 2.0)], [(0.0, -1.0), (1.0, 0.0)]),
        )
        path_item = QGraphicsPathItem()
        view, _base = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 3.0]),
            condition=condition,
            n_handles=3,
            handle_index=1,
            items=[path_item],
            linear_geom=geometry,
        )
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0, 5.0, 3.0], "t1")
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(path_item.path()),
            [
                (move, 0.0, 1.0),
                (line, 1.0, 2.0),
                (line, 1.0, 0.0),
                (line, 0.0, -1.0),
                (line, 0.0, 1.0),
            ],
        )

    def test_straight_segment_threshold_is_one_milli_unit(self):
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=6.0
        )
        geometry = _ScriptedLinearGeometry((0.0,) * 6, [], ([], []))
        for end_x, expect_path in ((0.0009, False), (0.001, True), (0.0015, True)):
            with self.subTest(end_x=end_x):
                path_item = QGraphicsPathItem()
                view, _base = self._view(
                    takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0]),
                    condition=condition,
                    n_handles=2,
                    handle_index=1,
                    items=[path_item],
                    linear_geom=geometry,
                )
                view.update_drag_handle_positions([0.0, 0.0, end_x, 0.0], "t1")
                self.assertEqual(not path_item.path().isEmpty(), expect_path)

    def test_linear_thickness_is_converted_to_pixels_and_defaults_to_one_unit(self):
        path_item = QGraphicsPathItem()
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, thickness=3.0
        )
        view, _base = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0]),
            condition=condition,
            n_handles=2,
            handle_index=1,
            items=[path_item],
        )
        view._scene_builder.cs.px_scale = 5.0
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0], "t1")
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -7.5, 10.0, 15.0)
        )
        condition.thickness = 0.0
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0], "t1")
        self.assertEqual(
            path_item.path().boundingRect(), QtCore.QRectF(0.0, -2.5, 10.0, 5.0)
        )

    def test_arrow_head_follows_the_segment_direction_for_an_oblique_arrow(self):
        annotation = BidAnnotation(
            uid="t1",
            annotation_type="arrow",
            position=[10.0, 20.0, 110.0, 70.0],
            width=2.0,
        )
        path_item = QGraphicsPathItem()
        view, _base = self._view(
            annotation=annotation, n_handles=2, handle_index=1, items=[path_item]
        )
        view.update_drag_handle_positions([10.0, 20.0, 110.0, 70.0], "t1")
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        expected = [
            (move, 10.0, 20.0),
            (line, 110.0, 70.0),
            (move, 70.07186132, 72.39661044),
            (line, 110.0, 70.0),
            (line, 87.96040514, 36.61952280),
        ]
        elements = self._elements(path_item.path())
        self.assertEqual(len(elements), len(expected))
        for (kind, x, y), (e_kind, e_x, e_y) in zip(elements, expected):
            self.assertEqual(kind, e_kind)
            self.assertAlmostEqual(x, e_x, places=6)
            self.assertAlmostEqual(y, e_y, places=6)

    def test_triangle_area_vertex_drag_is_a_full_vertex_drag(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        path_item = QGraphicsPathItem()
        view, _base = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 5.0, 8.0]),
            condition=condition,
            handle_index=1,
            items=[path_item],
        )
        view.update_drag_handle_positions([0.0, 0.0, 10.0, 0.0, 5.0, 9.0], "t1")
        self.assertEqual(
            [name for name, _args in view.calls],
            ["validate_parent", "pattern", "labels"],
        )
        self.assertFalse(path_item.path().isEmpty())

    def test_area_drag_with_five_transformed_values_is_not_a_vertex_drag(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        view, _base = self._view(
            takeoff=self._takeoff([0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0]),
            condition=condition,
            handle_index=1,
            items=[QGraphicsPathItem()],
        )
        view._scene_builder.cs.truncate_to = 5
        view.update_drag_handle_positions(
            [1.0, 2.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(self._handles(view)[:2], [(1.0, 2.0), (10.0, 0.0)])
        self.assertEqual(view.calls, [])

    def test_invalid_hole_geometry_is_rejected_before_the_hole_position_check(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        view, _base = self._view(
            takeoff=self._takeoff(
                [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0], is_hole=True
            ),
            condition=condition,
            handle_index=2,
            items=[QGraphicsPathItem()],
        )
        bow_tie = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view.update_drag_handle_positions(bow_tie, "t1")
        self.assertEqual(view.calls, [])
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)

    def test_area_vertex_outline_follows_every_vertex_of_an_irregular_polygon(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_AREA)
        path_item = QGraphicsPathItem()
        view, _base = self._view(
            takeoff=self._takeoff([3.0, 7.0, 10.0, 1.0, 14.0, 12.0, 1.0, 10.0]),
            condition=condition,
            handle_index=1,
            items=[path_item],
        )
        view.update_drag_handle_positions(
            [3.0, 7.0, 10.0, 1.0, 14.0, 12.0, 1.0, 10.0], "t1"
        )
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            self._elements(path_item.path()),
            [
                (move, 3.0, 7.0),
                (line, 10.0, 1.0),
                (line, 14.0, 12.0),
                (line, 1.0, 10.0),
                (line, 3.0, 7.0),
            ],
        )

    def test_vertex_drags_leave_a_non_path_first_item_alone(self):
        for condition_type, position, new_pos in (
            (
                Condition.TYPE_AREA,
                [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0],
                [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0],
            ),
            (Condition.TYPE_LINEAR, [0.0, 0.0, 6.0, 8.0], [1.0, 2.0, 7.0, 10.0]),
        ):
            with self.subTest(condition_type=condition_type):
                condition = Condition(
                    uid="c1", condition_type=condition_type, thickness=4.0
                )
                first = QGraphicsRectItem(QtCore.QRectF(0.0, 0.0, 5.0, 5.0))
                view, _base = self._view(
                    takeoff=self._takeoff(position),
                    condition=condition,
                    n_handles=3,
                    handle_index=1,
                    items=[first],
                )
                view.update_drag_handle_positions(new_pos, "t1")
                self.assertEqual(first.rect(), QtCore.QRectF(0.0, 0.0, 5.0, 5.0))
                self.assertNotIn("pattern", [name for name, _args in view.calls])

    def test_point_takeoff_marked_as_a_hole_never_cuts_a_parent_outline(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        item = QGraphicsPathItem()
        view, _base = self._view(
            takeoff=self._takeoff([5.0, 6.0], is_hole=True),
            condition=condition,
            handle_index=-1,
            items=[item],
        )
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [5.0, 6.0]
        view._drag_last_valid_new_pos = [7.0, 8.0]
        view.update_drag_handle_positions([9.0, 10.0], "t1")
        self.assertNotIn("hole_path", [name for name, _args in view.calls])

    def test_body_drag_delta_is_measured_from_the_original_position(self):
        condition = Condition(uid="c1", condition_type=Condition.TYPE_COUNT)
        item = QGraphicsPathItem()
        item.setPos(10.0, 20.0)
        view, _base = self._view(
            takeoff=self._takeoff([1.0, 2.0]),
            condition=condition,
            handle_index=-1,
            items=[item],
        )
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [1.0, 2.0]
        view.update_drag_handle_positions([3.0, 5.0], "t1", 500.0, 500.0)
        self.assertEqual(
            item.pos(), QtCore.QPointF(10.0 + 2.0 * 72.0, 20.0 + 3.0 * 72.0)
        )

    def test_linear_annotation_body_drag_moves_the_recorded_preview_items(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="line", position=[10.0, 20.0, 110.0, 120.0]
        )
        item = QGraphicsPathItem()
        item.setPos(10.0, 20.0)
        view, _base = self._view(
            annotation=annotation, n_handles=2, handle_index=-1, items=[item]
        )
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [10.0, 20.0, 110.0, 120.0]
        view.update_drag_handle_positions(
            [11.0, 22.0, 111.0, 122.0], "t1", 500.0, 500.0
        )
        self.assertEqual(item.pos(), QtCore.QPointF(10.0 + 72.0, 20.0 + 144.0))


class AnnotationDragGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(self, annotation, **kwargs):
        helper = AnnotationDragTests(
            "test_text_drag_derives_the_box_from_centre_and_size"
        )
        return helper._view(annotation, **kwargs), helper

    @staticmethod
    def _handles(view):
        return [(h.item.pos().x(), h.item.pos().y()) for h in view._handle_infos]

    def test_text_drag_with_three_values_uses_a_zero_box(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="text", position=[1.0, 2.0, 3.0, 4.0]
        )
        view, _helper = self._view(annotation, handle_index=2)
        view.update_drag_handle_positions([50.0, 40.0, 20.0], "t1")
        self.assertEqual(view.rebuild_calls, [("text", "t1", 0.0, 0.0, 0.0, 0.0, None)])

    def test_box_annotation_drag_needs_four_values_and_uses_the_extremes_of_each_axis(
        self,
    ):
        annotation = BidAnnotation(
            uid="t1", annotation_type="rect", position=[0.0, 0.0, 1.0, 1.0]
        )
        cases = (
            ([14.0, 12.0, 30.0, 5.0], (14.0, 5.0, 30.0, 12.0)),
            ([14.0, 12.0, 30.0, 5.0, 20.0, 40.0], (14.0, 5.0, 30.0, 40.0)),
            ([14.0, 12.0, 30.0], (0.0, 0.0, 0.0, 0.0)),
        )
        for new_pos, box in cases:
            with self.subTest(new_pos=new_pos):
                view, _helper = self._view(annotation, handle_index=1)
                view.update_drag_handle_positions(new_pos, "t1")
                self.assertEqual(view.rebuild_calls, [("rect", "t1", *box, None)])

    def test_ink_annotation_body_drag_does_not_edit_handles(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="ink", position=[9.0, 0.0, 0.0, 10.0, 5.0]
        )
        view, _helper = self._view(annotation, handle_index=-1)
        view.update_drag_handle_positions([9.0, 2.0, 3.0, 12.0, 8.0], "t1")
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)

    def test_ink_annotation_with_an_even_number_of_values_has_no_style_prefix(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="ink", position=[0.0, 0.0, 10.0, 5.0]
        )
        item = QGraphicsPathItem()
        item.setPos(10.0, 20.0)
        view, _helper = self._view(annotation, handle_index=-1, items=[item])
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [1.0, 2.0, 10.0, 5.0]
        view.update_drag_handle_positions([3.0, 5.0, 12.0, 8.0], "t1", 500.0, 500.0)
        self.assertEqual(
            item.pos(), QtCore.QPointF(10.0 + 2.0 * 72.0, 20.0 + 3.0 * 72.0)
        )

    def test_ink_annotation_with_an_odd_number_of_values_skips_the_style_prefix(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="ink", position=[9.0, 0.0, 0.0]
        )
        item = QGraphicsPathItem()
        item.setPos(10.0, 20.0)
        view, _helper = self._view(annotation, handle_index=-1, items=[item])
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [9.0, 1.0, 2.0, 10.0, 5.0]
        view.update_drag_handle_positions(
            [9.0, 3.0, 5.0, 12.0, 8.0], "t1", 500.0, 500.0
        )
        self.assertEqual(
            item.pos(), QtCore.QPointF(10.0 + 2.0 * 72.0, 20.0 + 3.0 * 72.0)
        )

    def test_body_drag_with_a_minimal_original_position_still_uses_the_delta(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="rect", position=[0.0, 0.0, 10.0, 5.0]
        )
        item = QGraphicsPathItem()
        item.setPos(10.0, 20.0)
        view, _helper = self._view(annotation, handle_index=-1, items=[item])
        view._drag_item_orig_positions = {id(item): item.pos()}
        view._drag_orig_position = [1.0, 2.0]
        view.update_drag_handle_positions([3.0, 5.0], "t1", 500.0, 500.0)
        self.assertEqual(
            item.pos(), QtCore.QPointF(10.0 + 2.0 * 72.0, 20.0 + 3.0 * 72.0)
        )

    def test_polygon_drag_with_three_values_is_not_a_polygon_edit(self):
        annotation = BidAnnotation(
            uid="t1", annotation_type="polygon", position=[0.0, 0.0, 10.0, 0.0]
        )
        view, _helper = self._view(annotation, handle_index=1)
        view.update_drag_handle_positions([1.0, 1.0, 5.0], "t1")
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)

    def test_first_handle_polygon_drag_is_validated_like_any_vertex_drag(self):
        annotation = BidAnnotation(
            uid="t1",
            annotation_type="polygon",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        )
        view, _helper = self._view(annotation, handle_index=0)
        bow_tie = [0.0, 0.0, 10.0, 10.0, 10.0, 0.0, 0.0, 10.0]
        view._drag_last_valid_new_pos = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        view.update_drag_handle_positions(bow_tie, "t1")
        self.assertEqual(self._handles(view), [(0.0, 0.0)] * 8)
        self.assertEqual(
            view._drag_last_valid_new_pos, [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        )

    def test_triangle_polygon_drag_that_reverses_winding_is_rejected(self):
        annotation = BidAnnotation(
            uid="t1",
            annotation_type="polygon",
            position=[0.0, 0.0, 10.0, 0.0, 5.0, 8.0],
        )
        view, _helper = self._view(annotation, handle_index=1)
        view._drag_last_valid_new_pos = [0.0, 0.0, 10.0, 0.0, 5.0, 8.0]
        view.update_drag_handle_positions([0.0, 0.0, 5.0, 8.0, 10.0, 0.0], "t1")
        self.assertEqual(view._drag_last_valid_new_pos, [0.0, 0.0, 10.0, 0.0, 5.0, 8.0])

    def test_polygon_vertex_drag_leaves_a_non_path_first_item_alone(self):
        annotation = BidAnnotation(
            uid="t1",
            annotation_type="polygon",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        )
        first = QGraphicsRectItem(QtCore.QRectF(0.0, 0.0, 5.0, 5.0))
        view, _helper = self._view(annotation, handle_index=1, items=[first])
        view.update_drag_handle_positions(
            [0.0, 0.0, 10.0, 0.0, 14.0, 12.0, 0.0, 10.0], "t1"
        )
        self.assertEqual(first.rect(), QtCore.QRectF(0.0, 0.0, 5.0, 5.0))

    def test_vertex_drag_never_moves_the_recorded_body_items(self):
        annotation = BidAnnotation(
            uid="t1",
            annotation_type="polygon",
            position=[0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        )
        path_item = QGraphicsPathItem()
        other = QGraphicsPathItem()
        other.setPos(30.0, 40.0)
        view, _helper = self._view(annotation, handle_index=1, items=[path_item, other])
        view._drag_item_orig_positions = {id(other): other.pos()}
        view._drag_orig_position = [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0]
        view.update_drag_handle_positions(
            [0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0], "t1", 500.0, 500.0
        )
        self.assertEqual(other.pos(), QtCore.QPointF(30.0, 40.0))
        view = self._view(
            BidAnnotation(
                uid="t1",
                annotation_type="rect",
                position=[0.0, 0.0, 10.0, 5.0],
            ),
            handle_index=1,
            items=[other],
        )[0]
        view._drag_item_orig_positions = {id(other): other.pos()}
        view._drag_orig_position = [0.0, 0.0, 10.0, 5.0]
        view.update_drag_handle_positions([2.0, 3.0, 12.0, 8.0], "t1", 500.0, 500.0)
        self.assertEqual(other.pos(), QtCore.QPointF(30.0, 40.0))


class AnnotationShapeHelperGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def _view(self, items=None, selection=None):
        helper = AnnotationShapeHelperTests(
            "test_rebuild_ignores_an_annotation_without_preview_items"
        )
        return helper._view(items=items, selection=selection)

    def test_selection_outline_corners_follow_the_box_in_order(self):
        outline = QGraphicsPolygonItem()
        outline.setData(0, "t1")
        view = self._view(selection=[outline])
        view._update_annotation_selection_outline_from_box(
            "t1", view._scene_builder.cs, 10.0, 20.0, 50.0, 80.0
        )
        polygon = outline.polygon()
        self.assertEqual(
            [(polygon.at(i).x(), polygon.at(i).y()) for i in range(polygon.count())],
            [(10.0, 20.0), (50.0, 20.0), (50.0, 80.0), (10.0, 80.0)],
        )

    def test_highlight_rebuild_prefers_explicit_points_over_the_corner_pair(self):
        main = QGraphicsPathItem()
        view = self._view(items=[main])
        points = [
            (0.0, 0.0),
            (30.0, 0.0),
            (30.0, 5.0),
            (0.0, 5.0),
            (0.0, 20.0),
            (30.0, 20.0),
            (30.0, 25.0),
            (0.0, 25.0),
        ]
        view._rebuild_ann_shape_path("highlight", "t1", 0.0, 0.0, 30.0, 25.0, points)
        self.assertEqual(main.path(), build_highlight_path(points))
        self.assertNotEqual(
            main.path(), build_highlight_path([(0.0, 0.0), (30.0, 25.0)])
        )


class HierarchyDragGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def setUp(self):
        self.h = HierarchyDragTests(
            "test_has_child_holes_reports_only_children_of_that_parent"
        )

    def _view(self, takeoffs, **kwargs):
        return self.h._view(takeoffs, **kwargs)

    def _takeoff(self, *args, **kwargs):
        return self.h._takeoff(*args, **kwargs)

    def _outline_view(self, parent_position, children):
        first = QGraphicsPathItem()
        first.setPos(7.0, 7.0)
        view = self._view(
            [self._takeoff("p", "ca", parent_position), *children], items=[first]
        )
        view._uid_to_items = {"p": [first]}
        return view, first

    def test_parent_outline_follows_every_vertex_of_an_irregular_parent(self):
        parent = [5.0, 8.0, 25.0, 6.0, 27.0, 28.0, 3.0, 24.0]
        view, first = self._outline_view(parent, [])
        view._update_parent_hole_path("p", "none", self.h._rect_path(0, 0, 1, 1))
        move = QPainterPath.ElementType.MoveToElement
        line = QPainterPath.ElementType.LineToElement
        self.assertEqual(
            [
                (
                    first.path().elementAt(i).type,
                    first.path().elementAt(i).x,
                    first.path().elementAt(i).y,
                )
                for i in range(first.path().elementCount())
            ],
            [
                (move, 5.0, 8.0),
                (line, 25.0, 6.0),
                (line, 27.0, 28.0),
                (line, 3.0, 24.0),
                (line, 5.0, 8.0),
            ],
        )

    def test_triangular_parent_and_triangular_hole_are_handled(self):
        parent = [0.0, 0.0, 30.0, 0.0, 0.0, 30.0]
        hole = self._takeoff("h", "ca", [2.0, 2.0, 12.0, 2.0, 2.0, 12.0], parent="p")
        view, first = self._outline_view(parent, [hole])
        view._update_parent_hole_path("p", "other", self.h._rect_path(0, 0, 1, 1))
        self.assertTrue(first.path().contains(QtCore.QPointF(20.0, 5.0)))
        self.assertFalse(first.path().contains(QtCore.QPointF(4.0, 4.0)))
        view, first = self._outline_view(parent, [hole])
        view._rebuild_parent_with_holes("p", self.h._rect_path(0, 0, 30, 30))
        self.assertTrue(first.path().contains(QtCore.QPointF(20.0, 5.0)))
        self.assertFalse(first.path().contains(QtCore.QPointF(4.0, 4.0)))

    def test_a_five_value_parent_position_is_not_a_polygon(self):
        view, first = self._outline_view([0.0, 0.0, 30.0, 0.0, 15.0], [])
        view._update_parent_hole_path("p", "h", self.h._rect_path(0, 0, 1, 1))
        self.assertTrue(first.path().isEmpty())
        self.assertEqual(view.calls, [])

    def test_five_value_children_do_not_cut_the_parent_outline(self):
        child = self._takeoff("bad", "ca", [2.0, 2.0, 12.0, 2.0, 7.0], parent="p")
        view, first = self._outline_view(self.h.SQUARE_100, [child])
        view._update_parent_hole_path(
            "p", "other", self.h._rect_path(200, 200, 201, 201)
        )
        self.assertTrue(first.path().contains(QtCore.QPointF(5.0, 1.0)))
        view, first = self._outline_view(self.h.SQUARE_100, [child])
        view._rebuild_parent_with_holes("p", self.h._rect_path(0, 0, 100, 100))
        self.assertTrue(first.path().contains(QtCore.QPointF(5.0, 1.0)))

    def test_linear_siblings_are_not_attachment_backouts(self):
        parent = self._takeoff("p", "ca", self.h.SQUARE_100)
        attachment = self._takeoff("a", "cat", [20.0, 20.0], parent="p")
        line = self._takeoff(
            "line", "cl", [10.0, 10.0, 30.0, 10.0, 30.0, 30.0, 10.0, 30.0], parent="p"
        )
        view = self._view([parent, attachment, line])
        self.assertIs(view._attachment_position_valid(attachment, [20.0, 20.0]), True)

    def test_parent_validation_checks_triangular_holes_and_ignores_other_shapes(self):
        triangle = self._takeoff(
            "tri", "ca", [200.0, 200.0, 210.0, 200.0, 200.0, 210.0], parent="p"
        )
        view = self._view([self._takeoff("p", "ca", self.h.SQUARE_100), triangle])
        self.assertIs(
            view._validate_parent_contains_holes("p", list(self.h.SQUARE_100)), False
        )
        view = self._view(
            [
                self._takeoff("p", "ca", self.h.SQUARE_100),
                self._takeoff(
                    "line",
                    "cl",
                    [200.0, 200.0, 210.0, 200.0, 200.0, 210.0],
                    parent="p",
                ),
                self._takeoff(
                    "bad", "ca", [200.0, 200.0, 210.0, 200.0, 205.0], parent="p"
                ),
            ]
        )
        self.assertIs(
            view._validate_parent_contains_holes("p", list(self.h.SQUARE_100)), True
        )

    def test_hole_validation_accepts_a_triangular_parent_and_checks_triangular_siblings(
        self,
    ):
        hole = self._takeoff("h", "ca", [2.0, 2.0, 6.0, 2.0, 2.0, 6.0], parent="p")
        sibling = self._takeoff(
            "s", "ca", [10.0, 10.0, 20.0, 10.0, 10.0, 20.0], parent="p"
        )
        line = self._takeoff("l", "cl", [4.0, 4.0, 9.0, 4.0, 4.0, 9.0], parent="p")
        view = self._view(
            [
                self._takeoff("p", "ca", [0.0, 0.0, 50.0, 0.0, 0.0, 50.0]),
                hole,
                sibling,
                line,
            ]
        )
        self.assertIs(
            view._validate_hole_position(hole, [2.0, 2.0, 8.0, 2.0, 2.0, 8.0]), True
        )
        self.assertIs(
            view._validate_hole_position(hole, [12.0, 12.0, 16.0, 12.0, 12.0, 16.0]),
            False,
        )

    def test_hole_validation_rejects_a_five_value_parent(self):
        hole = self._takeoff("h", "ca", [2.0, 2.0, 6.0, 2.0, 2.0, 6.0], parent="p")
        view = self._view(
            [
                self._takeoff(
                    "p",
                    "ca",
                    [0.0, 0.0, 50.0, 0.0, 0.0],
                ),
                hole,
            ]
        )
        self.assertIs(
            view._validate_hole_position(hole, [2.0, 2.0, 6.0, 2.0, 2.0, 6.0]), False
        )

    def test_children_of_a_non_area_parent_are_invalid_even_when_geometrically_inside(
        self,
    ):
        view = self._view(
            [
                self._takeoff("p", "cl", self.h.SQUARE_100),
                self._takeoff("h", "ca", self.h._square(10, 10, 20, 20), parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"h": self.h._square(10, 10, 25, 25)}), False)

    def test_children_of_a_parent_without_a_known_condition_are_invalid(self):
        view = self._view(
            [
                self._takeoff("p", "ghost", self.h.SQUARE_100),
                self._takeoff("h", "ca", self.h._square(10, 10, 20, 20), parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"h": self.h._square(10, 10, 25, 25)}), False)

    def test_a_child_whose_parent_is_on_another_page_is_invalid(self):
        view = self._view(
            [
                self._takeoff("p", "ca", self.h.SQUARE_100, page="pg2"),
                self._takeoff("h", "ca", self.h._square(10, 10, 20, 20), parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"h": self.h._square(10, 10, 25, 25)}), False)

    def test_parent_and_page_checks_are_independent_of_the_override_order(self):
        view = self._view(
            [
                self._takeoff("p", "ca", self.h.SQUARE_100),
                self._takeoff("h", "ca", self.h._square(10, 10, 20, 20), parent="p"),
                self._takeoff("h2", "ca", self.h._square(30, 30, 40, 40), parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(
            check(
                {
                    "h": self.h._square(10, 10, 25, 25),
                    "h2": self.h._square(30, 30, 45, 45),
                }
            ),
            True,
        )
        self.assertIs(
            check(
                {
                    "h2": self.h._square(30, 30, 45, 45),
                    "h": self.h._square(10, 10, 25, 25),
                }
            ),
            True,
        )

    def test_rebuilt_parent_outline_keeps_the_axes_of_off_diagonal_holes(self):
        child = self._takeoff("off", "ca", self.h._square(4, 10, 8, 14), parent="p")
        view, first = self._outline_view(self.h.SQUARE_100, [child])
        view._rebuild_parent_with_holes("p", self.h._rect_path(0, 0, 100, 100))
        self.assertFalse(first.path().contains(QtCore.QPointF(6.0, 12.0)))
        self.assertTrue(first.path().contains(QtCore.QPointF(12.0, 6.0)))
        self.assertTrue(first.path().contains(QtCore.QPointF(6.0, 6.0)))
        self.assertTrue(first.path().contains(QtCore.QPointF(12.0, 12.0)))
        expected = self.h._rect_path(0, 0, 100, 100).subtracted(
            self.h._rect_path(4, 10, 8, 14)
        )
        self.assertEqual(first.path(), expected)


class HoleOutlineAndFamilySweepTests(unittest.TestCase):
    """Pins drag_handler hole-outline geometry and hierarchy checks that the
    path-membership assertions above could not distinguish."""

    @classmethod
    def setUpClass(cls):
        cls.app = _interaction_support__app()

    def setUp(self):
        self.h = HierarchyDragTests(
            "test_has_child_holes_reports_only_children_of_that_parent"
        )

    @staticmethod
    def _closed_polygon(position):
        path = QPainterPath()
        path.moveTo(position[0], position[1])
        for index in range(2, len(position) - 1, 2):
            path.lineTo(position[index], position[index + 1])
        path.closeSubpath()
        return path

    def _outline_view(self, children):
        first = QGraphicsPathItem()
        view = self.h._view(
            [self.h._takeoff("p", "ca", self.h.SQUARE_100), *children], items=[first]
        )
        view._uid_to_items = {"p": [first]}
        return view, first

    def test_rebuilt_parent_outline_is_the_parent_minus_each_closed_child_polygon(self):
        hole_a = self.h._takeoff("a", "ca", self.h._square(10, 10, 30, 30), parent="p")
        hole_b = self.h._takeoff("b", "ca", self.h._square(50, 20, 70, 60), parent="p")
        view, first = self._outline_view([hole_a, hole_b])
        parent_path = self._closed_polygon(self.h.SQUARE_100)
        view._rebuild_parent_with_holes("p", parent_path)
        expected = parent_path.subtracted(
            self._closed_polygon(hole_a.position)
        ).subtracted(self._closed_polygon(hole_b.position))
        self.assertEqual(first.path(), expected)
        self.assertEqual(first.path().elementCount(), expected.elementCount())

    def test_dragged_hole_outline_is_the_closed_parent_minus_every_closed_hole(self):
        dragged = self.h._takeoff("a", "ca", self.h._square(10, 10, 30, 30), parent="p")
        other = self.h._takeoff("b", "ca", self.h._square(50, 20, 70, 60), parent="p")
        view, first = self._outline_view([dragged, other])
        moved = self._closed_polygon(self.h._square(15, 15, 35, 35))
        view._update_parent_hole_path("p", "a", moved)
        expected = (
            self._closed_polygon(self.h.SQUARE_100)
            .subtracted(moved)
            .subtracted(self._closed_polygon(other.position))
        )
        self.assertEqual(first.path(), expected)
        self.assertEqual(first.path().elementCount(), expected.elementCount())

    def test_overriding_a_plain_child_does_not_validate_its_parents_other_children(
        self,
    ):
        # Only attachments and area holes participate in the hierarchy check; a
        # linear takeoff that merely carries a parent uid must not make the
        # (already inconsistent) stored hole of that parent veto the move.
        view = self.h._view(
            [
                self.h._takeoff("p", "ca", self.h.SQUARE_100),
                self.h._takeoff(
                    "bad", "ca", self.h._square(200, 200, 210, 210), parent="p"
                ),
                self.h._takeoff("line", "cl", [1.0, 1.0, 5.0, 5.0], parent="p"),
            ]
        )
        check = view._takeoff_children_valid_for_geometry_changes
        self.assertIs(check({"line": [2.0, 2.0, 6.0, 6.0]}), True)
        # Control: the same stored hole does veto an override of a sibling hole.
        view._current_takeoffs["good"] = self.h._takeoff(
            "good", "ca", self.h._square(10, 10, 20, 20), parent="p"
        )
        self.assertIs(check({"good": self.h._square(10, 10, 25, 25)}), False)


class SingleCornerHandleSweepTests(unittest.TestCase):
    """Pins compute_new_position's corner_count > 0 boundary (one corner is already
    'a polygon-style handle set'), which the multi-corner tests never reach."""

    def test_edge_handle_of_a_single_corner_shape_takes_the_free_edge_branch(self):
        handler = _DragMath()
        handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 3.0, 0.0, 1, 1)
        # The free edge branch snaps the raw delta around the origin; the vertex
        # branch would instead snap the moved point against its previous corner.
        self.assertEqual(handler.snap_angle_calls, [(0.0, 0.0, 3.0, 0.0)])

    def test_vertex_handle_of_a_single_corner_shape_snaps_against_itself(self):
        handler = _DragMath()
        self.assertEqual(
            handler.compute_new_position([0.0, 0.0, 10.0, 0.0], 3.0, 0.0, 0, 1),
            [3.0, 0.0, 10.0, 0.0],
        )
        # The previous corner of the only corner is that corner's original position.
        self.assertEqual(handler.snap_angle_calls, [(0.0, 0.0, 3.0, 0.0)])
