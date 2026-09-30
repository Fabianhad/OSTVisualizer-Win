from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QStyle,
    QStyleOptionGraphicsItem,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtCore import QRectF, Qt
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
    HighlightGraphicsItem,
)
import os
import unittest
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.scene.plan_view_z_order import (
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
import math
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from tests.presentation.visualization.exporters.oval_support import (
    _page_info as _oval_support__page_info,
    _rotated_oval_position as _oval_support__rotated_oval_position,
)
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _page_info as _dimension_support__page_info,
)
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import tests.presentation.components.plan_view.test_view as view_fixtures

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _IdentityCoordinateSystem:
    @staticmethod
    def transform_vertices_to_2d(values):
        return list(values)

    @staticmethod
    def ost_to_pdf_coordinates(values, _page_info):
        return [
            (values[index], values[index + 1]) for index in range(0, len(values) - 1, 2)
        ]


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


class AnnotationRendererZOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_highlight_annotation_renders_in_paper_highlight_band(self):
        renderer = AnnotationItemRenderer(FakeCoordinateSystem())
        highlight = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 90.0],
            color="#ffff00",
        )
        rect = BidAnnotation(
            uid="r1",
            annotation_type="rect",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 90.0],
            color="#ff0000",
            width=1.0,
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("h1", highlight), ("r1", rect)], {}, "p1"
        )
        by_uid = {item.data(0): item for item, _hotlink in results}
        self.assertEqual(by_uid["h1"].zValue(), PAPER_HIGHLIGHT_Z)
        self.assertGreater(by_uid["h1"].zValue(), PAGE_VISIBLE_FRAME_Z)
        self.assertGreater(by_uid["h1"].zValue(), FOREGROUND_OVERLAY_Z)
        self.assertLess(by_uid["h1"].zValue(), TAKEOFF_BODY_Z)
        self.assertLess(by_uid["h1"].zValue(), by_uid["r1"].zValue())

    def test_rotated_highlight_annotation_uses_paper_highlight_band(self):
        renderer = AnnotationItemRenderer(FakeCoordinateSystem())
        highlight = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 10.0, 90.0, 10.0, 90.0, 90.0, 10.0, 90.0],
            color="#ffff00",
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("h1", highlight)], {}, "p1"
        )
        self.assertEqual(results[0][0].zValue(), PAPER_HIGHLIGHT_Z)


class HighlightRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _render_annotation(self, annotation):
        renderer = AnnotationItemRenderer(_IdentityCoordinateSystem())
        results, uid_to_items = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)]
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(uid_to_items[annotation.uid], [results[0][0]])
        return results[0][0]

    @staticmethod
    def _highlight():
        return BidAnnotation(
            uid="highlight-1",
            annotation_type="highlight",
            position=[20.0, 20.0, 100.0, 20.0, 100.0, 60.0, 20.0, 60.0],
            color="#ffff00",
            width=0.0,
        )

    @staticmethod
    def _paint_item(item, state):
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#808080"))
        painter = QPainter(image)
        option = QStyleOptionGraphicsItem()
        option.state = state
        item.paint(painter, option)
        painter.end()
        return image

    def test_highlight_uses_full_rgb_multiply_and_preserves_black_content(self):
        item = self._render_annotation(self._highlight())
        self.assertIsInstance(item, HighlightGraphicsItem)
        scene = QGraphicsScene()
        scene.setSceneRect(QRectF(0.0, 0.0, 120.0, 80.0))
        page = scene.addRect(
            scene.sceneRect(), QPen(Qt.PenStyle.NoPen), QColor("#ffffff")
        )
        page.setZValue(-1.0)
        text = scene.addRect(
            QRectF(55.0, 25.0, 10.0, 30.0),
            QPen(Qt.PenStyle.NoPen),
            QColor("#000000"),
        )
        text.setZValue(0.0)
        scene.addItem(item)
        image = QImage(120, 80, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        scene.render(painter, QRectF(0.0, 0.0, 120.0, 80.0), scene.sceneRect())
        painter.end()
        self.assertEqual(image.pixelColor(40, 40), QColor("#ffff00"))
        self.assertEqual(image.pixelColor(60, 40), QColor("#000000"))

    def test_plan_highlight_is_fill_only_with_square_ends(self):
        item = self._render_annotation(self._highlight())
        path = item.path()
        self.assertEqual(item.pen().style(), Qt.PenStyle.NoPen)
        self.assertEqual(item.brush().color(), QColor("#ffff00"))
        self.assertEqual(item.brush().color().alpha(), 255)
        self.assertFalse(
            any(
                path.elementAt(index).type == QPainterPath.ElementType.CurveToElement
                for index in range(path.elementCount())
            )
        )
        self.assertEqual(path.boundingRect(), QRectF(20.0, 20.0, 80.0, 40.0))

    def test_rotated_highlight_preserves_quad_geometry_instead_of_axis_bounds(self):
        corners = [(30.0, 20.0), (100.0, 40.0), (90.0, 70.0), (20.0, 50.0)]
        annotation = self._highlight()
        annotation.position = [coordinate for point in corners for coordinate in point]
        item = self._render_annotation(annotation)
        path = item.path()
        path_points = {
            (round(path.elementAt(index).x, 6), round(path.elementAt(index).y, 6))
            for index in range(path.elementCount())
        }
        self.assertEqual(path_points, set(corners))

    def test_multiple_highlight_quads_render_as_separate_filled_subpaths(self):
        annotation = self._highlight()
        annotation.position = [
            10.0,
            10.0,
            50.0,
            10.0,
            50.0,
            30.0,
            10.0,
            30.0,
            60.0,
            40.0,
            110.0,
            40.0,
            110.0,
            60.0,
            60.0,
            60.0,
        ]
        path = self._render_annotation(annotation).path()
        move_count = sum(
            path.elementAt(index).type == QPainterPath.ElementType.MoveToElement
            for index in range(path.elementCount())
        )
        self.assertEqual(move_count, 2)

    def test_selection_and_hover_state_do_not_change_base_highlight_pixels(self):
        item = self._render_annotation(self._highlight())
        normal = self._paint_item(item, QStyle.StateFlag.State_None)
        selected_hovered = self._paint_item(
            item,
            QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver,
        )
        self.assertEqual(bytes(normal.constBits()), bytes(selected_hovered.constBits()))

    def test_regular_rectangle_keeps_existing_outline_renderer(self):
        rectangle = BidAnnotation(
            uid="rect-1",
            annotation_type="rect",
            position=[20.0, 20.0, 100.0, 60.0],
            color="#ff0000",
            width=3.0,
        )
        item = self._render_annotation(rectangle)
        self.assertIsInstance(item, QGraphicsPathItem)
        self.assertNotIsInstance(item, HighlightGraphicsItem)
        self.assertEqual(item.pen().style(), Qt.PenStyle.SolidLine)
        self.assertEqual(item.pen().color(), QColor("#ff0000"))
        self.assertEqual(item.brush().color().alpha(), 0)


class PlanOvalRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rotated_plan_view_oval_uses_canonical_width_height_and_rotation(self):
        annotation = BidAnnotation(
            uid="oval",
            annotation_type="oval",
            page_uid="page",
            position=_oval_support__rotated_oval_position(
                200.0, 150.0, 120.0, 40.0, 30.0
            ),
            width=2.0,
        )
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        results, _items_by_uid = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)],
            _oval_support__page_info(),
            annotation.page_uid,
        )
        self.assertEqual(len(results), 1)
        item = results[0][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        bounds = item.path().boundingRect()
        self.assertAlmostEqual(bounds.center().x(), 200.0)
        self.assertAlmostEqual(bounds.center().y(), 150.0)
        self.assertAlmostEqual(bounds.width(), 120.0)
        self.assertAlmostEqual(bounds.height(), 40.0)
        self.assertAlmostEqual(item.rotation(), 30.0)


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_horizontal_dimension_renders_line_ticks_and_centered_text(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("d1", annotation)], _dimension_support__page_info(), "p1"
        )
        items = [item for item, _link in results]
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], QGraphicsPathItem)
        self.assertIsInstance(items[1], QGraphicsTextItem)
        self.assertEqual(items[1].toPlainText(), "21' - 3\"")
        self.assertEqual(items[1].data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertEqual(items[0].path().elementCount(), 6)
        self.assertEqual(items[0].pen().widthF(), 1.0)
        self.assertEqual([item.data(0) for item in uid_to_items["d1"]], ["d1", "d1"])

    def test_vertical_dimension_renders_perpendicular_ticks(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d2",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 0.0, 120.0],
            color="#00aa00",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d2", annotation)], _dimension_support__page_info(), "p1"
        )
        path = results[0][0].path()
        tick_start = path.elementAt(2)
        tick_end = path.elementAt(3)
        self.assertAlmostEqual(tick_start.y, tick_end.y)
        self.assertNotAlmostEqual(tick_start.x, tick_end.x)
        self.assertEqual(results[1][0].toPlainText(), "10' - 0\"")

    def test_angled_dimension_renders_without_crashing(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d3",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 36.0, 48.0],
            color="#0000ff",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d3", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "5' - 0\"")

    def test_missing_scale_data_is_graceful(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d4",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 12.0, 0.0],
            color="#000000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d4", annotation)],
            {"scale_factor1": 0.0, "scale_factor2": 0.0, "view_scale": 0.0},
            "p1",
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "1' - 0\"")

    def test_bid_aline_rendering_remains_a_single_line_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="l1",
            annotation_type="line",
            page_uid="p1",
            position=[0.0, 0.0, 24.0, 0.0],
            color="#ff0000",
            width=2.0,
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("l1", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsPathItem)
        self.assertEqual(results[0][0].path().elementCount(), 2)

    def test_dimension_text_and_ticks_are_selectable_scene_items(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d5",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d5", annotation)], _dimension_support__page_info(), "p1"
        )
        scene = QGraphicsScene()
        for item, _link in results:
            scene.addItem(item)
        text_item = results[1][0]
        hit_items = scene.items(text_item.mapToScene(text_item.boundingRect().center()))
        self.assertIn("d5", [item.data(0) for item in hit_items])

    def test_empty_text_annotation_renders_editable_text_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="text-1",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#336699",
            properties={"Text": "", "FontName": "Arial", "FontSize": 12},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("text-1", annotation)], _dimension_support__page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsTextItem)
        self.assertEqual(results[0][0].toPlainText(), "")
        self.assertEqual(uid_to_items["text-1"], [results[0][0]])


class TextAnnotationNativeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.errors = []
        hook = patch(
            "sys.excepthook", side_effect=lambda *args: self.errors.append(args)
        )
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(self.errors, []))
        fixture = view_fixtures.TakeoffPlanViewOverlayRefreshTests()
        self.addCleanup(fixture.doCleanups)
        self.view = fixture._make_plan_view()
        self.annotation, self.item = fixture._add_text_annotation(
            self.view, text="Before", page_uid="p1"
        )
        self.changes = []
        self.view.annotation_text_properties_flushed.connect(self.changes.extend)

    def test_reconstructed_text_keeps_long_words_and_newlines_for_qt_wrapping(self):
        content = "a" * 150 + "\nsecond\nline"
        renderer = AnnotationItemRenderer(
            self.view._scene_builder.get_coordinate_system()
        )
        items = renderer._render_text(
            {
                "content": content,
                "center_x": 10,
                "center_y": 10,
                "box_width": 40,
                "box_height": 100,
                "font_size": 12,
                "font_name": "Arial",
            },
            "#000000",
        )
        self.assertEqual(items[0][0].toPlainText(), content)
