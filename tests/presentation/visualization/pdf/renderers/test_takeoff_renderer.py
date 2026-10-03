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
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem


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
