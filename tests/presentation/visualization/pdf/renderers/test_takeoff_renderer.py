import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities import pattern as pattern_values
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.pdf.renderers.takeoff_renderer import (
    TakeoffRenderer,
)
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)

INACTIVE = Config.DEFAULT_INACTIVE_OBJECT_COLOR


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeCoordinateSystem:
    def __init__(self):
        self.page_info = {"view_scale": 1.0}

    def update_page_info(self, page_info):
        self.page_info.update(page_info)

    @staticmethod
    def parse_position(position):
        return list(position)

    def transform_vertices_to_2d(self, position):
        return list(position)

    def ost_to_pdf_points(self, value):
        return float(value)


class FakeColorService:
    def get_2d_color_for_takeoff(
        self,
        takeoff,
        _condition,
        color_map,
        _page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = inactive_object_color
        return color_map[takeoff.condition_uid]


class TakeoffRendererConditionBehaviorTests(unittest.TestCase):
    def _path_line_angle(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return math.atan2(second.y - first.y, second.x - first.x)

    def _line_path_items(self, items):
        return [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem) and item.path().elementCount() >= 2
        ]

    def _path_midpoint(self, item):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        return ((first.x + second.x) / 2.0, (first.y + second.y) / 2.0)

    def _line_spacing(self, first_item, second_item):
        line_angle = self._path_line_angle(first_item)
        normal_angle = line_angle + math.pi / 2.0
        first_projection = self._point_projection(
            self._path_midpoint(first_item), normal_angle
        )
        second_projection = self._point_projection(
            self._path_midpoint(second_item), normal_angle
        )
        return abs(second_projection - first_projection)

    def _point_projection(self, point, angle):
        return point[0] * math.cos(angle) + point[1] * math.sin(angle)

    def _assert_parallel_angle(self, actual, expected):
        diff = abs((actual - expected + math.pi / 2.0) % math.pi - math.pi / 2.0)
        self.assertLess(diff, 0.01)

    def _assert_line_avoids_rect(self, item, left, top, right, bottom):
        path = item.path()
        first = path.elementAt(0)
        second = path.elementAt(1)
        for step in range(1, 10):
            ratio = step / 10.0
            x = first.x + (second.x - first.x) * ratio
            y = first.y + (second.y - first.y) * ratio
            self.assertFalse(left < x < right and top < y < bottom)

    def _render_takeoff_items(self, condition, takeoff):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        rendered = renderer.create_all_path_items(
            [takeoff],
            {condition.uid: condition},
            {condition.uid: SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        return items if isinstance(items, list) else [items]

    def test_takeoff_renderer_creates_items_for_hidden_condition_layers(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Hidden Layer Condition",
            condition_type=Condition.TYPE_LINEAR,
            layer_visible=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 10.0, 0.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertEqual([uid for uid, _item in rendered], ["t1"])
        item = rendered[0][1]
        self.assertIsInstance(item, QGraphicsPathItem)
        self.assertFalse(item.path().isEmpty())
        self.assertEqual((item.data(0), item.data(1)), ("t1", "c1"))

    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        cls._quit_on_last_window_closed = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls._quit_on_last_window_closed)

    def tearDown(self):
        self.app.processEvents()

    def test_display_name_dimension_and_grid_render_as_scene_items(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            grid=True,
            grid_size1=3.0,
            grid_size2=3.0,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        text_items = [item for item in items if isinstance(item, QGraphicsTextItem)]
        grid_items = [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem)
            and item.data(2) != "condition_label"
            and not item.path().boundingRect().isNull()
        ]
        dimension_label = next(
            item for item in text_items if item.data(3) == "display_dimension"
        )
        name_label = next(item for item in text_items if item.data(3) == "display_name")
        self.assertIn("Area Label", name_label.toPlainText())
        self.assertIn("144.00 IN²", dimension_label.toPlainText())
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertAlmostEqual(dimension_center.x(), 6.0)
        self.assertAlmostEqual(dimension_center.y(), 6.0)
        self.assertAlmostEqual(name_center.x(), dimension_center.x())
        self.assertGreater(name_center.y(), dimension_center.y())
        self.assertNotEqual(name_center, dimension_center)
        self.assertGreater(len(grid_items), 1)

    def test_linear_horizontal_pattern_follows_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.HORIZONTAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), math.pi / 4.0)

    def test_linear_vertical_pattern_is_perpendicular_to_linear_direction(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.VERTICAL,
            spacing=2.0,
            thickness=8.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_item = items[1]
        self._assert_parallel_angle(self._path_line_angle(pattern_item), -math.pi / 4.0)

    def test_oriented_linear_diagonal_pattern_uses_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
            thickness=12.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_fixed_axis_area_diagonal_pattern_keeps_configured_spacing(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.BACKWARD_DIAG,
            spacing=2.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreaterEqual(len(pattern_items), 2)
        self.assertAlmostEqual(
            self._line_spacing(pattern_items[0], pattern_items[1]), 2.0, delta=0.01
        )

    def test_area_linear_patterns_exclude_backout_hole(self):
        line_patterns = [
            pattern_values.HORIZONTAL,
            pattern_values.VERTICAL,
            pattern_values.BACKWARD_DIAG,
            pattern_values.FORWARD_DIAG,
        ]
        for pattern in line_patterns:
            with self.subTest(pattern=pattern):
                condition = Condition(
                    uid="c1",
                    condition_type=Condition.TYPE_AREA,
                    color_fill=0,
                    pattern=pattern,
                    spacing=2.0,
                )
                parent = Takeoff(
                    uid="parent",
                    condition_uid="c1",
                    position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
                )
                backout = Takeoff(
                    uid="backout",
                    condition_uid="c1",
                    parent_uid="parent",
                    position=[8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0],
                )
                renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
                rendered = renderer.create_all_path_items(
                    [parent, backout],
                    {"c1": condition},
                    {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                )
                items = rendered[0][1]
                items = items if isinstance(items, list) else [items]
                pattern_items = self._line_path_items(items[1:])
                self.assertGreater(len(pattern_items), 0)
                for item in pattern_items:
                    self.assertEqual(item.pen().capStyle(), Qt.PenCapStyle.FlatCap)
                    self._assert_line_avoids_rect(item, 8.0, 8.0, 12.0, 12.0)

    def test_area_linear_pattern_without_backout_still_renders_lines(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.HORIZONTAL,
            spacing=2.0,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        items = self._render_takeoff_items(condition, takeoff)
        pattern_items = self._line_path_items(items[1:])
        self.assertGreater(len(pattern_items), 0)

    def test_area_solid_fill_excludes_backout_hole(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=pattern_values.SOLID,
        )
        parent = Takeoff(
            uid="parent",
            condition_uid="c1",
            position=[0.0, 0.0, 20.0, 0.0, 20.0, 20.0, 0.0, 20.0],
        )
        backout = Takeoff(
            uid="backout",
            condition_uid="c1",
            parent_uid="parent",
            position=[8.0, 8.0, 12.0, 8.0, 12.0, 12.0, 8.0, 12.0],
        )
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        rendered = renderer.create_all_path_items(
            [parent, backout],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertEqual([uid for uid, _item in rendered], ["parent", "backout"])
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        area_item = items[0]
        self.assertIsInstance(area_item, QGraphicsPathItem)
        self.assertFalse(area_item.path().contains(QtCore.QPointF(10.0, 10.0)))
        self.assertTrue(area_item.path().contains(QtCore.QPointF(4.0, 4.0)))
        self.assertTrue(area_item.path().contains(QtCore.QPointF(16.0, 16.0)))
        self.assertNotEqual(area_item.brush().style(), Qt.BrushStyle.NoBrush)
        # The backout itself stays addressable as an invisible hole carrier.
        hole_item = rendered[1][1]
        self.assertEqual(hole_item.data(0), "backout")
        self.assertEqual(hole_item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(hole_item.brush().style(), Qt.BrushStyle.NoBrush)
        self.assertTrue(hole_item.path().contains(QtCore.QPointF(10.0, 10.0)))

    def test_area_path_rejects_odd_coordinate_count(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        self.assertIsNone(
            renderer._create_area_path([0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0])
        )
        self.assertIsNone(renderer._create_area_path([0.0, 0.0, 10.0, 0.0]))
        triangle = renderer._create_area_path([0.0, 0.0, 10.0, 0.0, 10.0, 10.0])
        self.assertIsNotNone(triangle)
        self.assertEqual(triangle.boundingRect(), QtCore.QRectF(0.0, 0.0, 10.0, 10.0))

    def test_area_with_hole_uses_anchor_inside_visible_fill(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        outer = QPainterPath()
        outer.addRect(0.0, 0.0, 20.0, 20.0)
        hole = QPainterPath()
        hole.addRect(0.0, 0.0, 10.0, 10.0)
        visible_path = outer.subtracted(hole)
        anchor = renderer._path_centroid(visible_path)
        self.assertIsNotNone(anchor)
        self.assertTrue(visible_path.contains(QtCore.QPointF(*anchor)))

    def test_area_display_name_uses_centroid_when_dimension_is_not_present(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_name=True,
            display_dimension=False,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        name_center = name_label.mapToScene(name_label.boundingRect().center())
        self.assertAlmostEqual(name_center.x(), 6.0)
        self.assertAlmostEqual(name_center.y(), 6.0)

    def test_area_display_dimension_uses_negative_indicator_centroid_anchor(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            color_fill=0,
            pattern=0,
            spacing=0.0,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            is_negative=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        negative_box = next(
            item
            for item in items
            if isinstance(item, QGraphicsPathItem)
            and item.brush().color() == Qt.GlobalColor.red
        )
        dimension_center = dimension_label.mapToScene(
            dimension_label.boundingRect().center()
        )
        self.assertEqual(dimension_center, negative_box.pos())
        self.assertAlmostEqual(negative_box.pos().x(), 6.0)
        self.assertAlmostEqual(negative_box.pos().y(), 6.0)
        indicator_items = [
            item
            for item in items
            if isinstance(item, QGraphicsPathItem)
            and item.flags()
            & QGraphicsPathItem.GraphicsItemFlag.ItemIgnoresTransformations
        ]
        self.assertEqual(len(indicator_items), 2)
        positive = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        positive_rendered = positive.create_all_path_items(
            [
                Takeoff(
                    uid="t2",
                    condition_uid="c1",
                    position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
                )
            ],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        positive_items = positive_rendered[0][1]
        positive_items = (
            positive_items if isinstance(positive_items, list) else [positive_items]
        )
        self.assertFalse(
            [
                item
                for item in positive_items
                if isinstance(item, QGraphicsPathItem)
                and item.brush().color() == Qt.GlobalColor.red
            ]
        )

    def test_condition_label_style_fields_render_after_overlay_rebuild(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Area Label",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            dimension_font_name="Segoe UI",
            dimension_font_color=0x332211,
            dimension_font_size=24,
            dimension_font_bold=True,
            dimension_font_italic=True,
            dimension_font_underline=False,
            name_font_name="Calibri",
            name_font_color=0x665544,
            name_font_size=18,
            name_font_bold=False,
            name_font_italic=False,
            name_font_underline=True,
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        dimension_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem)
            and item.data(3) == "display_dimension"
        )
        name_label = next(
            item
            for item in items
            if isinstance(item, QGraphicsTextItem) and item.data(3) == "display_name"
        )
        self.assertEqual(dimension_label.defaultTextColor().name(), "#112233")
        self.assertEqual(dimension_label.font().family(), "Segoe UI")
        self.assertEqual(dimension_label.font().pointSize(), 24)
        self.assertTrue(dimension_label.font().bold())
        self.assertTrue(dimension_label.font().italic())
        self.assertFalse(dimension_label.font().underline())
        self.assertEqual(name_label.defaultTextColor().name(), "#445566")
        self.assertEqual(name_label.font().family(), "Calibri")
        self.assertEqual(name_label.font().pointSize(), 18)
        self.assertFalse(name_label.font().bold())
        self.assertFalse(name_label.font().italic())
        self.assertTrue(name_label.font().underline())

    def test_area_with_concave_outline_anchors_label_inside_visible_fill(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        # A "C" opening to the right: its vertex centroid (8.5, 10.0) lies in
        # the opening, outside the fill.
        outline = [
            (0.0, 0.0),
            (20.0, 0.0),
            (20.0, 5.0),
            (5.0, 5.0),
            (5.0, 15.0),
            (20.0, 15.0),
            (20.0, 20.0),
            (0.0, 20.0),
        ]
        path = QPainterPath()
        path.moveTo(*outline[0])
        for point in outline[1:]:
            path.lineTo(*point)
        path.closeSubpath()
        preferred = renderer._calculate_polygon_centroid(outline)
        self.assertEqual(preferred, (8.5, 10.0))
        self.assertFalse(path.contains(QtCore.QPointF(*preferred)))
        anchor = renderer._path_centroid(path)
        self.assertTrue(path.contains(QtCore.QPointF(*anchor)))
        # The fallback picks the interior point nearest the centroid: inside the
        # vertical bar (x < 5), vertically near the centroid.
        self.assertLess(anchor[0], 5.0)
        self.assertLess(math.hypot(anchor[0] - 8.5, anchor[1] - 10.0), 4.5)

    def test_path_centroid_rejects_paths_with_fewer_than_three_vertices(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        segment = QPainterPath()
        segment.moveTo(0.0, 0.0)
        segment.lineTo(10.0, 10.0)
        self.assertIsNone(renderer._path_centroid(segment))
        self.assertIsNone(renderer._create_negative_indicator(segment))

    def test_area_grid_lines_follow_grid_sizes_and_condition_gap(self):
        def grid_lines(**overrides):
            fields = dict(
                uid="c1",
                condition_type=Condition.TYPE_AREA,
                color_fill=0,
                pattern=0,
                spacing=0.0,
                grid=True,
                grid_size1=3.0,
                grid_size2=3.0,
            )
            fields.update(overrides)
            condition = Condition(**fields)
            takeoff = Takeoff(
                uid="t1",
                condition_uid="c1",
                position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
            )
            items = self._render_takeoff_items(condition, takeoff)
            horizontal, vertical = [], []
            for item in self._line_path_items(items[1:]):
                path = item.path()
                first, second = path.elementAt(0), path.elementAt(1)
                if abs(first.y - second.y) < 1e-9:
                    horizontal.append(
                        (first.y, min(first.x, second.x), max(first.x, second.x))
                    )
                else:
                    self.assertAlmostEqual(first.x, second.x)
                    vertical.append(
                        (first.x, min(first.y, second.y), max(first.y, second.y))
                    )
            return sorted(horizontal), sorted(vertical)

        horizontal, vertical = grid_lines()
        self.assertEqual(
            horizontal, [(3.0, 0.0, 12.0), (6.0, 0.0, 12.0), (9.0, 0.0, 12.0)]
        )
        self.assertEqual(
            vertical, [(3.0, 0.0, 12.0), (6.0, 0.0, 12.0), (9.0, 0.0, 12.0)]
        )
        # grid_size1 spaces the vertical lines, grid_size2 the horizontal ones.
        horizontal, vertical = grid_lines(grid_size1=4.0, grid_size2=6.0)
        self.assertEqual([line[0] for line in horizontal], [6.0])
        self.assertEqual([line[0] for line in vertical], [4.0, 8.0])
        # The condition gap widens both configured spacings.
        horizontal, vertical = grid_lines(gap=1.0)
        self.assertEqual([line[0] for line in horizontal], [4.0, 8.0])
        self.assertEqual([line[0] for line in vertical], [4.0, 8.0])

    def test_grid_spacing_falls_back_to_condition_spacing_without_gap_inflation(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        cases = (
            (dict(grid_size1=3.0, grid_size2=5.0, gap=0.0, spacing=9.0), (3.0, 5.0)),
            (dict(grid_size1=3.0, grid_size2=5.0, gap=1.0, spacing=9.0), (4.0, 6.0)),
            (dict(grid_size1=0.0, grid_size2=5.0, gap=1.0, spacing=9.0), (9.0, 6.0)),
            (dict(grid_size1=-2.0, grid_size2=0.0, gap=2.0, spacing=0.0), (4.0, 4.0)),
        )
        for fields, expected in cases:
            with self.subTest(**fields):
                self.assertEqual(
                    renderer._grid_spacing(SimpleNamespace(**fields)), expected
                )

    def test_linear_thickness_scales_with_view_scale_and_has_a_minimum(self):
        def bounds(thickness, view_scale):
            renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
            condition = Condition(
                uid="c1",
                condition_type=Condition.TYPE_LINEAR,
                color_fill=0,
                pattern=1,
                thickness=thickness,
            )
            takeoff = Takeoff(
                uid="t1", condition_uid="c1", position=[0.0, 0.0, 20.0, 0.0]
            )
            rendered = renderer.create_all_path_items(
                [takeoff],
                {"c1": condition},
                {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
                page_info={"view_scale": view_scale},
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
            item = rendered[0][1]
            return (item[0] if isinstance(item, list) else item).path().boundingRect()

        plain = bounds(8.0, 1.0)
        zoomed = bounds(8.0, 2.0)
        thin = bounds(0.5, 1.0)
        self.assertEqual((plain.width(), plain.height()), (20.0, 8.0))
        self.assertEqual((zoomed.width(), zoomed.height()), (20.0, 16.0))
        # Sub-pixel thickness is raised to the minimum rendered thickness.
        self.assertEqual((thin.width(), thin.height()), (20.0, 2.0))

    def test_count_takeoff_is_centered_and_has_a_minimum_rendered_size(self):
        def bounds(size):
            renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
            condition = Condition(
                uid="c1",
                condition_type=Condition.TYPE_COUNT,
                shape=shapes.SQUARE,
                width=size,
                depth=size,
                display_size=100.0,
            )
            takeoff = Takeoff(uid="t1", condition_uid="c1", position=[50.0, 60.0])
            rendered = renderer.create_all_path_items(
                [takeoff],
                {"c1": condition},
                {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
            item = rendered[0][1]
            return (item[0] if isinstance(item, list) else item).path().boundingRect()

        self.assertEqual(bounds(20.0), QtCore.QRectF(40.0, 50.0, 20.0, 20.0))
        self.assertEqual(bounds(2.0), QtCore.QRectF(46.0, 56.0, 8.0, 8.0))

    def test_linear_display_name_is_centered_below_the_rendered_path(self):
        condition = Condition(
            uid="c1",
            name="Linear Label",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=1,
            thickness=8.0,
            display_name=True,
        )
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=[0.0, 0.0, 20.0, 0.0])
        items = self._render_takeoff_items(condition, takeoff)
        self.assertEqual(len(items), 2)
        path_bounds = items[0].path().boundingRect()
        label = items[1]
        self.assertIsInstance(label, QGraphicsTextItem)
        self.assertEqual(label.data(3), "display_name")
        self.assertEqual(label.toPlainText(), "Linear Label")
        # Position derives from the label's own metrics, not a fixed font size.
        self.assertAlmostEqual(label.pos().y(), path_bounds.bottom() + 4.0)
        self.assertAlmostEqual(
            label.pos().x() + label.boundingRect().width() / 2.0,
            path_bounds.center().x(),
        )
        hidden_name = Condition(
            uid="c1",
            name="Linear Label",
            condition_type=Condition.TYPE_LINEAR,
            color_fill=0,
            pattern=1,
            thickness=8.0,
            display_name=False,
        )
        self.assertFalse(
            [
                item
                for item in self._render_takeoff_items(hidden_name, takeoff)
                if isinstance(item, QGraphicsTextItem)
            ]
        )

    def test_takeoffs_without_a_condition_or_color_entry_are_skipped(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1", condition_type=Condition.TYPE_LINEAR, color_fill=0, pattern=1
        )
        takeoffs = [
            Takeoff(uid="ok", condition_uid="c1", position=[0.0, 0.0, 10.0, 0.0]),
            Takeoff(
                uid="no-condition", condition_uid="gone", position=[0.0, 0.0, 10.0, 0.0]
            ),
            Takeoff(uid="short", condition_uid="c1", position=[0.0, 0.0]),
        ]
        rendered = renderer.create_all_path_items(
            takeoffs,
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertEqual([uid for uid, _item in rendered], ["ok"])
        no_color = renderer.create_all_path_items(
            takeoffs[:1],
            {"c1": condition},
            {},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertEqual(no_color, [])

    def test_label_style_defaults_to_condition_color_and_default_point_size(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        condition = Condition(
            uid="c1",
            name="Plain Label",
            condition_type=Condition.TYPE_AREA,
            display_name=True,
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0.0, 0.0, 12.0, 0.0, 12.0, 12.0, 0.0, 12.0],
        )
        rendered = renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            {"c1": SimpleNamespace(hex="#123456", opacity=1.0)},
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        label = next(item for item in items if isinstance(item, QGraphicsTextItem))
        self.assertEqual(label.defaultTextColor().name(), "#123456")
        self.assertEqual(label.font().pointSize(), 9)
        self.assertFalse(label.font().bold())
        self.assertFalse(label.font().italic())
        self.assertFalse(label.font().underline())
        self.assertTrue(
            label.flags() & QGraphicsTextItem.GraphicsItemFlag.ItemIsSelectable
        )

    def test_linear_patterns_follow_the_direction_of_a_non_diagonal_linear(self):
        for pattern, offset in (
            (pattern_values.HORIZONTAL, 0.0),
            (pattern_values.VERTICAL, math.pi / 2.0),
        ):
            with self.subTest(pattern=pattern):
                condition = Condition(
                    uid="c1",
                    condition_type=Condition.TYPE_LINEAR,
                    color_fill=0,
                    pattern=pattern,
                    spacing=2.0,
                    thickness=8.0,
                )
                takeoff = Takeoff(
                    uid="t1",
                    condition_uid="c1",
                    position=[0.0, 0.0, 30.0, 10.0],
                )
                items = self._render_takeoff_items(condition, takeoff)
                self._assert_parallel_angle(
                    self._path_line_angle(items[1]),
                    math.atan2(10.0, 30.0) + offset,
                )


class _CoordinateSystem:
    def __init__(self, scale=1.0, dx=0.0, dy=0.0, flip_y=False, page_info=None):
        self.scale = scale
        self.dx = dx
        self.dy = dy
        self.flip_y = flip_y
        self.page_info = {"view_scale": 1.0} if page_info is None else page_info

    def update_page_info(self, page_info):
        self.page_info.update(page_info)

    @staticmethod
    def parse_position(position):
        return list(position)

    def transform_vertices_to_2d(self, position):
        out = []
        for index in range(0, len(position) - 1, 2):
            x, y = position[index], position[index + 1]
            out.append(x * self.scale + self.dx)
            out.append((-y if self.flip_y else y) * self.scale + self.dy)
        return out

    def ost_to_pdf_points(self, value):
        return float(value)


class _ColorService:
    def get_2d_color_for_takeoff(
        self, takeoff, _condition, color_map, _selections=None, *, inactive_object_color
    ):
        return color_map[takeoff.condition_uid]


def _colors(condition_uid="c1", hex_color="#123456", opacity=1.0):
    return {condition_uid: SimpleNamespace(hex=hex_color, opacity=opacity)}


class _AppCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def renderer(self, **kwargs):
        return TakeoffRenderer(_CoordinateSystem(**kwargs), _ColorService())

    def render(self, takeoffs, conditions, cs=None, color_map=None, **kwargs):
        renderer = TakeoffRenderer(cs or _CoordinateSystem(), _ColorService())
        conditions = (
            conditions
            if isinstance(conditions, dict)
            else {c.uid: c for c in conditions}
        )
        return renderer.create_all_path_items(
            takeoffs,
            conditions,
            color_map or {uid: _colors(uid)[uid] for uid in conditions},
            inactive_object_color=INACTIVE,
            **kwargs,
        )

    def items(self, takeoff, condition, cs=None, **kwargs):
        rendered = self.render([takeoff], [condition], cs, **kwargs)
        self.assertEqual(len(rendered), 1)
        value = rendered[0][1]
        return value if isinstance(value, list) else [value]


def _elements(item):
    path = item.path()
    return [
        (round(path.elementAt(i).x, 6), round(path.elementAt(i).y, 6))
        for i in range(path.elementCount())
    ]


def _line_condition(**kwargs):
    fields = dict(
        uid="c1", condition_type=Condition.TYPE_LINEAR, color_fill=0, pattern=1
    )
    fields.update(kwargs)
    return Condition(**fields)


def _area_condition(**kwargs):
    fields = dict(uid="c1", condition_type=Condition.TYPE_AREA, color_fill=0, pattern=1)
    fields.update(kwargs)
    return Condition(**fields)


def _square(x, y, size):
    return [x, y, x + size, y, x + size, y + size, x, y + size]


class PrimaryItemTests(_AppCase):
    def test_the_main_item_is_a_cosmetic_outline_with_the_translucent_fill(self):
        condition = _area_condition()
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=_square(10, 20, 30))
        (item,) = self.items(
            takeoff,
            condition,
            color_map=_colors(hex_color="#336699", opacity=0.5),
        )
        self.assertEqual(item.pen().color(), QColor("#336699"))
        self.assertEqual(item.pen().widthF(), 2.0)
        self.assertTrue(item.pen().isCosmetic())
        self.assertEqual(item.brush().color().name(), "#336699")
        self.assertAlmostEqual(item.brush().color().alphaF(), 0.5, places=2)
        self.assertEqual((item.data(0), item.data(1)), ("t1", "c1"))

    def test_a_backed_out_area_keeps_the_same_outline_style(self):
        condition = _area_condition()
        parent = Takeoff(uid="p", condition_uid="c1", position=_square(0, 0, 40))
        hole = Takeoff(
            uid="h", condition_uid="c1", parent_uid="p", position=_square(10, 10, 10)
        )
        rendered = self.render([parent, hole], [condition])
        item = rendered[0][1]
        item = item[0] if isinstance(item, list) else item
        self.assertEqual(item.pen().widthF(), 2.0)
        self.assertTrue(item.pen().isCosmetic())
        self.assertEqual(item.pen().color(), QColor("#123456"))
        self.assertEqual((item.data(0), item.data(1)), ("p", "c1"))

    def test_a_condition_without_a_pattern_is_filled_solid(self):
        for pattern in (0, None):
            with self.subTest(pattern=pattern):
                condition = _area_condition(pattern=pattern)
                (item,) = self.items(
                    Takeoff(uid="t1", condition_uid="c1", position=_square(0, 0, 20)),
                    condition,
                )
                self.assertEqual(item.brush().style(), Qt.BrushStyle.SolidPattern)

    def test_the_coordinate_system_is_exposed(self):
        cs = _CoordinateSystem()
        self.assertIs(TakeoffRenderer(cs, _ColorService()).coordinate_system, cs)

    def test_page_info_reaches_the_coordinate_system_only_when_given(self):
        cs = _CoordinateSystem()
        renderer = TakeoffRenderer(cs, _ColorService())
        condition = _line_condition()
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=[0.0, 0.0, 10.0, 0.0])
        for page_info in (None, {}):
            renderer.create_all_path_items(
                [takeoff],
                {"c1": condition},
                _colors(),
                page_info=page_info,
                inactive_object_color=INACTIVE,
            )
        self.assertEqual(cs.page_info, {"view_scale": 1.0})
        renderer.create_all_path_items(
            [takeoff],
            {"c1": condition},
            _colors(),
            page_info={"view_scale": 3.0},
            inactive_object_color=INACTIVE,
        )
        self.assertEqual(cs.page_info["view_scale"], 3.0)

    def test_a_direct_build_without_options_has_no_negative_marker_or_labels(self):
        renderer = self.renderer()
        path = renderer._create_area_path(_square(0, 0, 20))
        item = renderer._build_item(
            path, _area_condition(), "#123456", 0.5, 2.0, "u", "c"
        )
        self.assertIsInstance(item, QGraphicsPathItem)
        self.assertEqual((item.data(0), item.data(1)), ("u", "c"))


class PatternOwnershipTests(_AppCase):
    def test_every_extra_item_is_tagged_with_its_takeoff_and_condition(self):
        condition = _area_condition(
            pattern=pattern_values.HORIZONTAL,
            spacing=4.0,
            name="Slab",
            display_name=True,
        )
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", position=_square(0, 0, 20), is_negative=True
        )
        items = self.items(takeoff, condition)
        self.assertGreater(len(items), 5)
        for item in items:
            self.assertEqual((item.data(0), item.data(1)), ("t1", "c1"))

    def test_grid_items_are_tagged_and_only_areas_get_a_grid(self):
        area = _area_condition(grid=True, grid_size1=5.0, grid_size2=5.0)
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=_square(0, 0, 20))
        items = self.items(takeoff, area)
        self.assertGreater(len(items), 3)
        for item in items:
            self.assertEqual((item.data(0), item.data(1)), ("t1", "c1"))
        linear = _line_condition(
            grid=True, grid_size1=5.0, grid_size2=5.0, thickness=8.0
        )
        line_items = self.items(
            Takeoff(uid="t2", condition_uid="c1", position=[0.0, 0.0, 40.0, 0.0]),
            linear,
        )
        self.assertEqual(len(line_items), 1)

    def test_an_area_pattern_stays_on_the_page_axes_even_if_the_outline_is_rotated(
        self,
    ):
        side = 40.0
        angle = math.radians(20.0)
        corners = []
        for u, v in ((0, 0), (side, 0), (side, side), (0, side)):
            corners.extend(
                [
                    50.0 + u * math.cos(angle) - v * math.sin(angle),
                    50.0 + u * math.sin(angle) + v * math.cos(angle),
                ]
            )
        condition = _area_condition(pattern=pattern_values.HORIZONTAL, spacing=4.0)
        items = self.items(
            Takeoff(uid="t1", condition_uid="c1", position=corners), condition
        )
        lines = [i for i in items[1:] if isinstance(i, QGraphicsPathItem)]
        self.assertGreater(len(lines), 3)
        for line in lines:
            first, second = _elements(line)[:2]
            self.assertAlmostEqual(first[1], second[1], places=6)

    def test_a_linear_pattern_follows_an_off_origin_direction(self):
        condition = _line_condition(
            pattern=pattern_values.HORIZONTAL, spacing=2.0, thickness=9.0
        )
        takeoff = Takeoff(
            uid="t1", condition_uid="c1", position=[10.0, 40.0, 50.0, 70.0]
        )
        items = self.items(takeoff, condition)
        lines = [i for i in items[1:] if isinstance(i, QGraphicsPathItem)]
        self.assertGreater(len(lines), 2)
        wanted = math.atan2(30.0, 40.0)
        for line in lines:
            (x1, y1), (x2, y2) = _elements(line)[:2]
            difference = abs(
                (math.atan2(y2 - y1, x2 - x1) - wanted + math.pi / 2) % math.pi
                - math.pi / 2
            )
            self.assertLess(difference, 0.01)


class LinearAngleTests(_AppCase):
    def test_the_angle_is_measured_between_the_transformed_end_points(self):
        renderer = self.renderer()
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[10.0, 40.0, 50.0, 70.0]
        )
        self.assertAlmostEqual(
            renderer._linear_pattern_angle(takeoff), math.atan2(30.0, 40.0)
        )
        flipped = self.renderer(flip_y=True)
        self.assertAlmostEqual(
            flipped._linear_pattern_angle(takeoff), -math.atan2(30.0, 40.0)
        )
        self.assertAlmostEqual(
            self.renderer(scale=3.0, dx=7.0, dy=-4.0)._linear_pattern_angle(takeoff),
            math.atan2(30.0, 40.0),
        )

    def test_a_short_or_degenerate_position_has_no_angle(self):
        renderer = self.renderer()
        for position in ([], [1.0, 2.0], [1.0, 2.0, 3.0], [5.0, 5.0, 5.0, 5.0]):
            with self.subTest(position=position):
                self.assertIsNone(
                    renderer._linear_pattern_angle(
                        Takeoff(uid="t", condition_uid="c1", position=position)
                    )
                )
        curved = Takeoff(
            uid="t", condition_uid="c1", position=[0.0, 0.0, 10.0, 0.0, 99.0, 99.0]
        )
        self.assertAlmostEqual(renderer._linear_pattern_angle(curved), 0.0)


class GridSpacingTests(_AppCase):
    def test_spacing_boundaries(self):
        renderer = self.renderer()
        cases = (
            (dict(grid_size1=1.0, grid_size2=0.5, gap=0.0, spacing=9.0), (1.0, 0.5)),
            (dict(grid_size1=1.0, grid_size2=0.5, gap=1.0, spacing=9.0), (2.0, 1.5)),
            (dict(grid_size1=0.0, grid_size2=0.0, gap=1.0, spacing=0.5), (0.5, 0.5)),
            (dict(grid_size1=0.0, grid_size2=0.0, gap=0.0, spacing=-1.0), (4.0, 4.0)),
            (dict(grid_size1=2.0, grid_size2=0.0, gap=0.0, spacing=0.0), (2.0, 4.0)),
        )
        for fields, expected in cases:
            with self.subTest(**fields):
                self.assertEqual(
                    renderer._grid_spacing(SimpleNamespace(**fields)), expected
                )


class LabelStyleTests(_AppCase):
    def _label(self, **style):
        takeoff = Takeoff(uid="t1", condition_uid="c1", position=[0, 0], **style)
        return self.renderer()._make_condition_text_item(
            "Label", QColor("#abcdef"), "t1", "c1", "display_name", takeoff
        )

    def test_nothing_set_uses_the_condition_colour_and_default_font(self):
        label = self._label()
        self.assertEqual(label.defaultTextColor(), QColor("#abcdef"))
        self.assertEqual(label.font().pointSize(), 9)
        self.assertEqual(label.font().family(), QtGuiFontFamily())
        self.assertFalse(
            label.font().bold() or label.font().italic() or label.font().underline()
        )

    def test_a_font_name_alone_does_not_change_the_colour(self):
        label = self._label(name_font_name="Calibri")
        self.assertEqual(label.defaultTextColor(), QColor("#abcdef"))
        self.assertEqual(label.font().family(), "Calibri")

    def test_a_colour_alone_is_used_even_without_size_or_flags(self):
        label = self._label(name_font_color=0x665544)
        self.assertEqual(label.defaultTextColor().name(), "#445566")
        self.assertEqual(label.font().pointSize(), 9)

    def test_a_colour_with_name_and_size_but_no_emphasis_is_still_used(self):
        label = self._label(
            name_font_color=0x665544,
            name_font_name="Calibri",
            name_font_size=18,
            name_font_bold=False,
            name_font_italic=False,
            name_font_underline=False,
        )
        self.assertEqual(label.defaultTextColor().name(), "#445566")
        self.assertEqual(label.font().pointSize(), 18)
        self.assertFalse(
            label.font().bold() or label.font().italic() or label.font().underline()
        )

    def test_each_emphasis_flag_acts_on_its_own(self):
        for flag in ("bold", "italic", "underline"):
            with self.subTest(flag=flag):
                font = self._label(**{f"name_font_{flag}": True}).font()
                self.assertEqual(
                    (font.bold(), font.italic(), font.underline()),
                    (flag == "bold", flag == "italic", flag == "underline"),
                )
                self.assertEqual(
                    self._label(**{f"name_font_{flag}": True}).defaultTextColor(),
                    QColor("#abcdef"),
                )

    def test_labels_are_selectable_and_tagged(self):
        label = self._label()
        self.assertEqual(
            (label.data(0), label.data(1), label.data(2), label.data(3)),
            ("t1", "c1", "condition_label", "display_name"),
        )
        self.assertTrue(label.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)

    def test_dimension_labels_read_the_dimension_fields_and_names_the_name_fields(self):
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            position=[0, 0],
            dimension_font_name="Segoe UI",
            dimension_font_size=20,
            name_font_name="Calibri",
            name_font_size=11,
        )
        renderer = self.renderer()
        dimension = renderer._make_condition_text_item(
            "x", QColor("#000000"), "t1", "c1", "display_dimension", takeoff
        )
        name = renderer._make_condition_text_item(
            "x", QColor("#000000"), "t1", "c1", "display_name", takeoff
        )
        self.assertEqual(
            (dimension.font().family(), dimension.font().pointSize()), ("Segoe UI", 20)
        )
        self.assertEqual(
            (name.font().family(), name.font().pointSize()), ("Calibri", 11)
        )
        self.assertEqual(dimension.data(3), "display_dimension")

    def test_without_a_takeoff_the_style_is_the_default_one(self):
        renderer = self.renderer()
        self.assertEqual(
            renderer._takeoff_label_style(None, "display_name"),
            (None, None, None, False, False, False),
        )
        self.assertEqual(
            renderer._takeoff_label_style(None, "display_dimension"),
            (None, None, None, False, False, False),
        )


def QtGuiFontFamily():
    from PySide6.QtGui import QFont

    return QFont().family()


class LabelTextAndPlacementTests(_AppCase):
    def test_the_dimension_text_lists_all_three_quantities(self):
        condition = _area_condition(display_dimension=True, calc_type1=11, uom1=4)
        takeoff = Takeoff(uid="t", condition_uid="c1", position=_square(0, 0, 12))
        self.assertEqual(
            self.renderer()._dimension_label_text(condition, takeoff, None),
            "144.00 IN²\n0.00 EA\n0.00 EA",
        )
        self.assertEqual(
            self.renderer()._dimension_label_text(condition, None, None), ""
        )

    def test_a_backed_out_area_shows_the_remaining_quantity(self):
        condition = _area_condition(
            display_dimension=True, calc_type1=11, uom1=4, name="Slab"
        )
        parent = Takeoff(uid="p", condition_uid="c1", position=_square(0, 0, 12))
        hole_a = Takeoff(
            uid="a", condition_uid="c1", parent_uid="p", position=_square(0, 0, 6)
        )
        hole_b = Takeoff(
            uid="b", condition_uid="c1", parent_uid="p", position=_square(6, 6, 3)
        )
        for holes, text in (([hole_a], "108.00"), ([hole_a, hole_b], "99.00")):
            with self.subTest(holes=len(holes)):
                rendered = self.render([parent, *holes], [condition])
                items = rendered[0][1]
                label = next(i for i in items if isinstance(i, QGraphicsTextItem))
                self.assertTrue(label.toPlainText().startswith(f"{text} IN²"))

    def test_labels_are_centred_on_the_centroid_of_an_off_origin_wide_area(self):
        condition = _area_condition(
            name="Wide",
            display_name=True,
            display_dimension=True,
            calc_type1=11,
            uom1=4,
        )
        takeoff = Takeoff(
            uid="t",
            condition_uid="c1",
            position=[100.0, 200.0, 140.0, 200.0, 140.0, 210.0, 100.0, 210.0],
        )
        items = self.items(takeoff, condition)
        texts = {i.data(3): i for i in items if isinstance(i, QGraphicsTextItem)}
        dimension = texts["display_dimension"]
        name = texts["display_name"]
        centre = dimension.mapToScene(dimension.boundingRect().center())
        self.assertAlmostEqual(centre.x(), 120.0, places=6)
        self.assertAlmostEqual(centre.y(), 205.0, places=6)
        self.assertAlmostEqual(
            name.pos().y(),
            dimension.pos().y() + dimension.boundingRect().height() + 4.0,
            places=6,
        )
        self.assertAlmostEqual(
            name.pos().x() + name.boundingRect().width() / 2.0, 120.0, places=6
        )

    def test_a_name_alone_is_centred_on_the_centroid(self):
        condition = _area_condition(name="Wide", display_name=True)
        takeoff = Takeoff(
            uid="t",
            condition_uid="c1",
            position=[100.0, 200.0, 140.0, 200.0, 140.0, 210.0, 100.0, 210.0],
        )
        (path_item, label) = self.items(takeoff, condition)
        centre = label.mapToScene(label.boundingRect().center())
        self.assertAlmostEqual(centre.x(), 120.0, places=6)
        self.assertAlmostEqual(centre.y(), 205.0, places=6)

    def test_a_path_without_an_area_centroid_centres_on_its_bounds(self):
        renderer = self.renderer()
        path = QPainterPath()
        path.moveTo(0.0, 0.0)
        path.lineTo(40.0, 10.0)
        label = renderer._create_centered_condition_text_item(
            path, "Edge", QColor("#000000"), "t", "c", "display_name", None
        )
        bounds = label.boundingRect()
        self.assertAlmostEqual(label.pos().x(), 20.0 - bounds.width() / 2.0)
        self.assertAlmostEqual(label.pos().y(), 5.0 - bounds.height() / 2.0)

    def test_a_linear_name_sits_four_below_the_path_and_is_centred_on_it(self):
        condition = _line_condition(name="Wall", display_name=True, thickness=8.0)
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[100.0, 200.0, 160.0, 200.0]
        )
        path_item, label = self.items(takeoff, condition)
        bounds = path_item.path().boundingRect()
        self.assertAlmostEqual(label.pos().y(), bounds.bottom() + 4.0, places=6)
        self.assertAlmostEqual(
            label.pos().x() + label.boundingRect().width() / 2.0, 130.0, places=6
        )


class CentroidTests(_AppCase):
    def _path(self, points, close=True):
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        if close:
            path.closeSubpath()
        return path

    def test_the_centroid_of_a_wide_off_origin_rectangle(self):
        renderer = self.renderer()
        centre = renderer._path_centroid(
            self._path([(100, 200), (140, 200), (140, 210), (100, 210)])
        )
        self.assertAlmostEqual(centre[0], 120.0)
        self.assertAlmostEqual(centre[1], 205.0)

    def test_an_open_triangle_still_has_a_centroid(self):
        renderer = self.renderer()
        triangle = self._path([(0, 0), (30, 0), (0, 60)], close=False)
        centre = renderer._path_centroid(triangle)
        self.assertAlmostEqual(centre[0], 10.0)
        self.assertAlmostEqual(centre[1], 20.0)

    def test_collinear_points_use_their_average(self):
        renderer = self.renderer()
        self.assertEqual(
            renderer._calculate_polygon_centroid(
                [(0.0, 0.0), (10.0, 4.0), (20.0, 8.0)]
            ),
            (10.0, 4.0),
        )
        self.assertEqual(
            renderer._calculate_polygon_centroid([(2.0, 3.0), (2.0, 3.0), (2.0, 3.0)]),
            (2.0, 3.0),
        )

    def test_the_centroid_of_a_triangle_is_the_mean_of_its_corners(self):
        renderer = self.renderer()
        centre = renderer._calculate_polygon_centroid(
            [(10.0, 0.0), (40.0, 0.0), (10.0, 90.0)]
        )
        self.assertAlmostEqual(centre[0], 20.0)
        self.assertAlmostEqual(centre[1], 30.0)

    def test_a_thin_l_falls_back_to_a_point_along_a_vertex_ray(self):
        # Arms of thickness 1 and 0.5: the centroid sits in the empty corner and no
        # cell centre of the 32 x 32 search grid falls inside an arm, so the
        # anchor is the vertex-ray point 5 % of the way from the origin corner.
        outline = [(0, 0), (100, 0), (100, 1), (0.5, 1), (0.5, 100), (0, 100)]
        path = self._path(outline)
        area = 100.0 + 49.5
        cx = (100.0 * 50.0 + 49.5 * 0.25) / area
        cy = (100.0 * 0.5 + 49.5 * 50.5) / area
        self.assertFalse(path.contains(QPointF(cx, cy)))
        anchor = self.renderer()._path_centroid(path)
        self.assertAlmostEqual(anchor[0], 0.05 * cx, places=9)
        self.assertAlmostEqual(anchor[1], 0.05 * cy, places=9)

    def test_a_thin_l_with_a_grid_cell_in_its_arm_anchors_on_that_cell_centre(self):
        # Horizontal arm 100 x 1, vertical arm 1 x 59: the 32 x 32 grid cell centre
        # (32.8125, 0.9375) lies in the arm and is nearest to the centroid.
        outline = [(0, 0), (100, 0), (100, 1), (1, 1), (1, 60), (0, 60)]
        path = self._path(outline)
        anchor = self.renderer()._path_centroid(path)
        self.assertAlmostEqual(anchor[0], 3.125 * 10.5, places=9)
        self.assertAlmostEqual(anchor[1], 1.875 * 0.5, places=9)

    def test_a_translated_thin_l_anchors_on_a_ray_from_its_own_corner(self):
        # Same L as above moved by (200, 300): the anchor is 5 % of the way from the
        # nearest corner vertex (200, 300) towards the centroid.
        dx, dy = 200.0, 300.0
        outline = [
            (dx + x, dy + y)
            for x, y in ((0, 0), (100, 0), (100, 1), (0.5, 1), (0.5, 100), (0, 100))
        ]
        area = 100.0 + 49.5
        cx = dx + (100.0 * 50.0 + 49.5 * 0.25) / area
        cy = dy + (100.0 * 0.5 + 49.5 * 50.5) / area
        anchor = self.renderer()._path_centroid(self._path(outline))
        self.assertAlmostEqual(anchor[0], dx + 0.05 * (cx - dx), places=9)
        self.assertAlmostEqual(anchor[1], dy + 0.05 * (cy - dy), places=9)

    def test_the_search_grid_reaches_its_last_row_and_column(self):
        # Bottom arm 100 x 2 and right arm 3 x 98: the centroid is (78.87, 69.24).
        # The grid cell centres 98.4375 (last row / column) are the only ones inside
        # an arm; the nearest of them is in the last column for this outline ...
        outline = [(0, 100), (100, 100), (100, 0), (97, 0), (97, 98), (0, 98)]
        anchor = self.renderer()._path_centroid(self._path(outline))
        self.assertAlmostEqual(anchor[0], 3.125 * 31.5, places=9)
        self.assertAlmostEqual(anchor[1], 3.125 * 22.5, places=9)
        # ... and in the last row for its mirror image across the diagonal.
        mirrored = [(y, x) for x, y in outline]
        anchor = self.renderer()._path_centroid(self._path(mirrored))
        self.assertAlmostEqual(anchor[0], 3.125 * 22.5, places=9)
        self.assertAlmostEqual(anchor[1], 3.125 * 31.5, places=9)

    def test_the_search_grid_works_at_a_tiny_scale(self):
        scale = 0.005
        outline = [
            (x * scale, y * scale)
            for x, y in ((0, 0), (100, 0), (100, 1), (1, 1), (1, 60), (0, 60))
        ]
        anchor = self.renderer()._path_centroid(self._path(outline))
        self.assertAlmostEqual(anchor[0], 3.125 * 10.5 * scale, places=9)
        self.assertAlmostEqual(anchor[1], 1.875 * 0.5 * scale, places=9)

    def test_with_no_interior_point_the_preferred_anchor_is_kept(self):
        line = QPainterPath()
        line.moveTo(0.0, 0.0)
        line.lineTo(10.0, 0.0)
        self.assertEqual(
            TakeoffRenderer._nearest_interior_anchor(
                line, (5.0, 5.0), [(0.0, 0.0), (10.0, 0.0)]
            ),
            (5.0, 5.0),
        )


class NegativeIndicatorTests(_AppCase):
    def test_the_marker_is_a_red_box_with_a_white_minus_at_the_centroid(self):
        path = QPainterPath()
        path.addRect(0.0, 0.0, 60.0, 30.0)
        box, minus = self.renderer()._create_negative_indicator(path)
        self.assertEqual(box.path().boundingRect(), QRectF(-6.0, -6.0, 12.0, 12.0))
        self.assertEqual(box.brush().color(), QColor(Qt.GlobalColor.red))
        self.assertEqual(box.pen().color(), QColor(Qt.GlobalColor.black))
        self.assertEqual(box.pen().widthF(), 1.0)
        self.assertEqual(minus.path().boundingRect(), QRectF(-3.0, -0.75, 6.0, 1.5))
        self.assertEqual(minus.brush().color(), QColor(Qt.GlobalColor.white))
        self.assertEqual(minus.pen().color(), QColor(Qt.GlobalColor.white))
        for item in (box, minus):
            self.assertEqual((item.pos().x(), item.pos().y()), (30.0, 15.0))
            self.assertTrue(
                item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
            )

    def test_the_marker_is_drawn_over_a_negative_takeoff(self):
        condition = _area_condition()
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=_square(10, 10, 60), is_negative=True
        )
        items = self.items(takeoff, condition, color_map=_colors(opacity=0.0))
        self.assertEqual(len(items), 3)
        scene = QGraphicsScene()
        scene.setSceneRect(QRectF(0, 0, 80, 80))
        for item in items:
            scene.addItem(item)
        image = QImage(80, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ffffff"))
        painter = QPainter(image)
        scene.render(painter, QRectF(0, 0, 80, 80), scene.sceneRect())
        painter.end()
        self.assertEqual(image.pixelColor(30, 30), QColor("#ffffff"))
        self.assertEqual(image.pixelColor(40, 40), QColor("#ffffff"))
        self.assertEqual(image.pixelColor(36, 40), QColor(255, 0, 0))
        self.assertEqual(image.pixelColor(44, 40), QColor(255, 0, 0))
        self.assertEqual(image.pixelColor(40, 36), QColor(255, 0, 0))
        self.assertEqual(image.pixelColor(40, 44), QColor(255, 0, 0))
        self.assertEqual(image.pixelColor(34, 40), QColor(0, 0, 0))
        for item in items:
            scene.removeItem(item)


class BuildPatternFillTests(_AppCase):
    def _path(self):
        path = QPainterPath()
        path.addRect(0.0, 0.0, 20.0, 20.0)
        return path

    def test_a_solid_pattern_is_only_a_translucent_brush(self):
        brush, items = self.renderer().build_pattern_fill(
            self._path(), pattern_values.SOLID, QColor("#336699"), 0.25, 2.0, 1.0
        )
        self.assertEqual(brush.color().name(), "#336699")
        self.assertAlmostEqual(brush.color().alphaF(), 0.25, places=2)
        self.assertEqual(items, [])

    def test_line_patterns_return_hatch_lines_and_no_brush(self):
        brush, items = self.renderer().build_pattern_fill(
            self._path(), pattern_values.HORIZONTAL, QColor("#336699"), 1.0, 5.0, 1.0
        )
        self.assertIsNone(brush)
        ys = sorted(round(_elements(item)[0][1], 6) for item in items)
        self.assertEqual(ys, [5.0, 10.0, 15.0])
        for item in items:
            self.assertEqual(item.pen().color(), QColor("#336699"))
            self.assertEqual(item.pen().widthF(), 1.0)

    def test_the_orientation_turns_the_hatch_lines(self):
        _brush, items = self.renderer().build_pattern_fill(
            self._path(),
            pattern_values.HORIZONTAL,
            QColor("#336699"),
            1.0,
            5.0,
            1.0,
            orientation_angle=math.pi / 2.0,
        )
        self.assertGreater(len(items), 2)
        for item in items:
            (x1, _y1), (x2, _y2) = _elements(item)[:2]
            self.assertAlmostEqual(x1, x2, places=6)

    def test_patterns_without_lines_return_no_items(self):
        for pattern in (pattern_values.NONE, pattern_values.TRANSPARENT):
            brush, items = self.renderer().build_pattern_fill(
                self._path(), pattern, QColor("#336699"), 0.5, 5.0, 1.0
            )
            self.assertEqual(items, [])
            self.assertEqual(brush is None, pattern == pattern_values.NONE)


class LinearPathGeometryTests(_AppCase):
    def test_a_straight_band_is_built_from_the_end_points_in_order(self):
        condition = _line_condition(thickness=6.0)
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[10.0, 40.0, 50.0, 70.0]
        )
        (item,) = self.items(takeoff, condition)
        self.assertEqual(
            _elements(item),
            [(8.2, 42.4), (11.8, 37.6), (51.8, 67.6), (48.2, 72.4), (8.2, 42.4)],
        )

    def test_the_band_is_placed_through_the_coordinate_system(self):
        condition = _line_condition(thickness=6.0)
        takeoff = Takeoff(uid="t", condition_uid="c1", position=[0.0, 0.0, 40.0, 0.0])
        (item,) = self.items(
            takeoff, condition, cs=_CoordinateSystem(scale=2.0, dx=10.0, dy=20.0)
        )
        self.assertEqual(
            _elements(item),
            [(10.0, 23.0), (10.0, 17.0), (90.0, 17.0), (90.0, 23.0), (10.0, 23.0)],
        )

    def test_a_missing_view_scale_means_no_scaling(self):
        condition = _line_condition(thickness=8.0)
        takeoff = Takeoff(uid="t", condition_uid="c1", position=[0.0, 0.0, 20.0, 0.0])
        cs = _CoordinateSystem(page_info={})
        (item,) = self.items(takeoff, condition, cs=cs)
        self.assertEqual(item.path().boundingRect(), QRectF(0.0, -4.0, 20.0, 8.0))

    def test_a_curved_linear_is_an_arc_band_through_the_control_point(self):
        condition = _line_condition(thickness=4.0)
        takeoff = Takeoff(
            uid="t",
            condition_uid="c1",
            position=[0.0, 0.0, 100.0, 0.0, 50.0, 30.0],
            curve=0,
        )
        cs = _CoordinateSystem(scale=2.0, dx=10.0, dy=20.0)
        (item,) = self.items(takeoff, condition, cs=cs)
        path = item.path()
        # end points (10, 20) and (210, 20), control point (110, 80)
        self.assertTrue(path.contains(QPointF(110.0, 80.0)))
        self.assertTrue(path.contains(QPointF(110.0, 81.5)))
        self.assertFalse(path.contains(QPointF(110.0, 83.0)))
        self.assertFalse(path.contains(QPointF(110.0, 77.0)))
        self.assertFalse(path.contains(QPointF(110.0, 30.0)))
        bounds = path.boundingRect()
        self.assertAlmostEqual(bounds.bottom(), 82.0, delta=0.3)
        self.assertGreater(bounds.left(), 8.0)
        self.assertLess(bounds.left(), 10.0)
        self.assertGreater(bounds.right(), 210.0)
        self.assertLess(bounds.right(), 212.0)
        self.assertGreater(bounds.top(), 17.5)
        self.assertLess(bounds.top(), 20.0)

    def test_a_seventh_value_is_the_sagitta_of_the_arc(self):
        condition = _line_condition(thickness=4.0)
        takeoff = Takeoff(
            uid="t",
            condition_uid="c1",
            position=[0.0, 0.0, 100.0, 0.0, 50.0, 30.0, 7.0],
            curve=0,
        )
        (item,) = self.items(takeoff, condition)
        path = item.path()
        # the stored control point is replaced by an apex 7 above the chord
        self.assertTrue(path.contains(QPointF(50.0, -7.0)))
        self.assertFalse(path.contains(QPointF(50.0, 30.0)))
        self.assertAlmostEqual(path.boundingRect().top(), -9.0, delta=0.3)

    def test_the_curve_flag_and_value_count_decide_between_arc_and_straight(self):
        condition = _line_condition(thickness=4.0)
        cases = (
            (0, [0.0, 0.0, 100.0, 0.0, 50.0, 30.0], True),
            (3, [0.0, 0.0, 100.0, 0.0, 50.0, 30.0], True),
            (-1, [0.0, 0.0, 100.0, 0.0, 50.0, 30.0], False),
            (0, [0.0, 0.0, 100.0, 0.0], False),
            (5, [0.0, 0.0, 100.0, 0.0], False),
        )
        for curve, position, curved in cases:
            with self.subTest(curve=curve, values=len(position)):
                takeoff = Takeoff(
                    uid="t", condition_uid="c1", position=position, curve=curve
                )
                (item,) = self.items(takeoff, condition)
                height = item.path().boundingRect().height()
                if curved:
                    self.assertGreater(height, 20.0)
                else:
                    self.assertAlmostEqual(height, 4.0)


class CountGeometryTests(_AppCase):
    def _bounds(self, condition, takeoff, cs=None):
        (item,) = self.items(takeoff, condition, cs=cs)
        return item.path().boundingRect()

    def test_the_size_scales_with_the_view_scale_for_width_and_depth_alike(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.RECTANGLE,
            width=30.0,
            depth=10.0,
            display_size=100.0,
        )
        takeoff = Takeoff(uid="t", condition_uid="c1", position=[100.0, 50.0])
        plain = self._bounds(condition, takeoff)
        zoomed = self._bounds(
            condition,
            takeoff,
            _CoordinateSystem(page_info={"view_scale": 2.0}),
        )
        unscaled = self._bounds(condition, takeoff, _CoordinateSystem(page_info={}))
        self.assertEqual(plain, QRectF(85.0, 45.0, 30.0, 10.0))
        self.assertEqual(zoomed, QRectF(70.0, 40.0, 60.0, 20.0))
        self.assertEqual(unscaled, plain)

    def test_the_marker_turns_about_its_position(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.SQUARE,
            width=20.0,
            depth=20.0,
            display_size=100.0,
        )
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[100.0, 50.0], rotation=math.pi / 4.0
        )
        bounds = self._bounds(condition, takeoff)
        half = 10.0 * math.sqrt(2.0)
        self.assertAlmostEqual(bounds.left(), 100.0 - half, places=6)
        self.assertAlmostEqual(bounds.right(), 100.0 + half, places=6)
        self.assertAlmostEqual(bounds.top(), 50.0 - half, places=6)
        self.assertAlmostEqual(bounds.bottom(), 50.0 + half, places=6)

    def test_a_count_position_goes_through_the_coordinate_system(self):
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.SQUARE,
            width=20.0,
            depth=20.0,
            display_size=100.0,
        )
        takeoff = Takeoff(uid="t", condition_uid="c1", position=[100.0, 50.0])
        bounds = self._bounds(
            condition, takeoff, _CoordinateSystem(scale=2.0, dx=5.0, dy=-5.0)
        )
        self.assertEqual(bounds, QRectF(195.0, 85.0, 20.0, 20.0))


class AreaPathGeometryTests(_AppCase):
    def test_an_area_outline_is_its_vertices_in_order_and_closed(self):
        condition = _area_condition()
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[0.0, 0.0, 10.0, 5.0, 0.0, 20.0]
        )
        (item,) = self.items(takeoff, condition)
        self.assertEqual(
            _elements(item), [(0.0, 0.0), (10.0, 5.0), (0.0, 20.0), (0.0, 0.0)]
        )

    def test_an_area_outline_is_placed_through_the_coordinate_system(self):
        condition = _area_condition()
        takeoff = Takeoff(
            uid="t", condition_uid="c1", position=[0.0, 0.0, 10.0, 5.0, 0.0, 20.0]
        )
        (item,) = self.items(
            takeoff, condition, cs=_CoordinateSystem(scale=2.0, dx=100.0, dy=-50.0)
        )
        self.assertEqual(
            _elements(item),
            [(100.0, -50.0), (120.0, -40.0), (100.0, -10.0), (100.0, -50.0)],
        )


class AreaAndHoleValidityTests(_AppCase):
    def test_a_triangle_is_a_valid_area_and_a_valid_hole(self):
        condition = _area_condition()
        triangle = Takeoff(
            uid="p", condition_uid="c1", position=[0.0, 0.0, 60.0, 0.0, 0.0, 60.0]
        )
        (plain,) = self.items(triangle, condition)
        self.assertEqual(plain.path().boundingRect(), QRectF(0.0, 0.0, 60.0, 60.0))
        hole = Takeoff(
            uid="h",
            condition_uid="c1",
            parent_uid="p",
            position=[5.0, 5.0, 25.0, 5.0, 5.0, 25.0],
        )
        rendered = self.render([triangle, hole], [condition])
        self.assertEqual([uid for uid, _ in rendered], ["p", "h"])
        parent_item = rendered[0][1]
        parent_item = parent_item[0] if isinstance(parent_item, list) else parent_item
        self.assertFalse(parent_item.path().contains(QPointF(10.0, 10.0)))
        self.assertTrue(parent_item.path().contains(QPointF(40.0, 10.0)))
        carrier = rendered[1][1]
        self.assertTrue(carrier.path().contains(QPointF(10.0, 10.0)))

    def test_areas_with_fewer_than_three_corners_or_odd_values_are_dropped(self):
        condition = _area_condition()
        for position in (
            [0.0, 0.0, 10.0, 0.0],
            [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0],
            [0.0, 0.0, 10.0],
        ):
            with self.subTest(position=position):
                self.assertEqual(
                    self.render(
                        [Takeoff(uid="t", condition_uid="c1", position=position)],
                        [condition],
                    ),
                    [],
                )

    def test_invalid_hole_positions_are_ignored_but_do_not_stop_the_parent(self):
        condition = _area_condition()
        parent = Takeoff(uid="p", condition_uid="c1", position=_square(0, 0, 40))
        for hole_position in (
            [1.0, 2.0, 3.0, 4.0],
            [1.0, 1.0, 5.0, 1.0, 5.0, 5.0, 3.0],
        ):
            with self.subTest(hole=hole_position):
                hole = Takeoff(
                    uid="h", condition_uid="c1", parent_uid="p", position=hole_position
                )
                rendered = self.render([parent, hole], [condition])
                self.assertEqual([uid for uid, _ in rendered], ["p"])
                item = rendered[0][1]
                item = item[0] if isinstance(item, list) else item
                self.assertTrue(item.path().contains(QPointF(2.0, 3.0)))


class HoleParentingTests(_AppCase):
    def test_only_real_area_parents_with_area_children_make_holes(self):
        area = _area_condition()
        linear = _line_condition(uid="c2", thickness=2.0)
        parent = Takeoff(uid="p", condition_uid="c1", position=_square(0, 0, 40))
        cases = {
            "linear child of an area": (
                Takeoff(
                    uid="k",
                    condition_uid="c2",
                    parent_uid="p",
                    position=[1.0, 1.0, 9.0, 1.0],
                ),
                [parent],
            ),
            "area child of a linear": (
                Takeoff(
                    uid="k",
                    condition_uid="c1",
                    parent_uid="q",
                    position=_square(5, 5, 5),
                ),
                [Takeoff(uid="q", condition_uid="c2", position=[0.0, 0.0, 40.0, 0.0])],
            ),
        }
        for label, (child, others) in cases.items():
            with self.subTest(label):
                rendered = self.render(
                    [*others, child],
                    {"c1": area, "c2": linear},
                    color_map={**_colors("c1"), **_colors("c2")},
                )
                self.assertEqual(
                    sorted(uid for uid, _ in rendered), sorted([others[0].uid, "k"])
                )

    def test_parent_ids_zero_and_none_mean_no_parent(self):
        area = _area_condition()
        first = Takeoff(uid="0", condition_uid="c1", position=_square(0, 0, 40))
        for parent_uid in ("0", 0, None, ""):
            with self.subTest(parent_uid=parent_uid):
                second = Takeoff(
                    uid="s",
                    condition_uid="c1",
                    parent_uid=parent_uid,
                    position=_square(5, 5, 5),
                )
                rendered = self.render([first, second], [area])
                self.assertEqual([uid for uid, _ in rendered], ["0", "s"])

    def test_numeric_parent_ids_other_than_zero_are_real_parents(self):
        area = _area_condition()
        parent = Takeoff(uid=1, condition_uid="c1", position=_square(0, 0, 40))
        hole = Takeoff(
            uid="h", condition_uid="c1", parent_uid=1, position=_square(5, 5, 5)
        )
        rendered = self.render([parent, hole], [area])
        self.assertEqual([uid for uid, _ in rendered], [1, "h"])
        item = rendered[0][1]
        item = item[0] if isinstance(item, list) else item
        self.assertFalse(item.path().contains(QPointF(7.0, 7.0)))
