import math
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities import pattern as pattern_values
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
    page_info = {"view_scale": 1.0}

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
        items = rendered[0][1]
        items = items if isinstance(items, list) else [items]
        area_item = items[0]
        self.assertIsInstance(area_item, QGraphicsPathItem)
        self.assertFalse(area_item.path().contains(QtCore.QPointF(10.0, 10.0)))
        self.assertNotEqual(area_item.brush().style(), Qt.BrushStyle.NoBrush)

    def test_area_path_rejects_odd_coordinate_count(self):
        renderer = TakeoffRenderer(FakeCoordinateSystem(), FakeColorService())
        self.assertIsNone(
            renderer._create_area_path([0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 5.0])
        )

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
            dimension_font_underline=True,
            name_font_name="Calibri",
            name_font_color=0x665544,
            name_font_size=18,
            name_font_bold=True,
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
        self.assertTrue(dimension_label.font().underline())
        self.assertEqual(name_label.defaultTextColor().name(), "#445566")
        self.assertEqual(name_label.font().family(), "Calibri")
        self.assertEqual(name_label.font().pointSize(), 18)
        self.assertTrue(name_label.font().bold())
        self.assertFalse(name_label.font().italic())
        self.assertTrue(name_label.font().underline())
