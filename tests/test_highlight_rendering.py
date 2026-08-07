import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QGraphicsScene, QStyle
from PySide6.QtWidgets import QStyleOptionGraphicsItem
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    HighlightGraphicsItem,
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter


class _IdentityCoordinateSystem:
    @staticmethod
    def transform_vertices_to_2d(values):
        return list(values)

    @staticmethod
    def ost_to_pdf_coordinates(values, _page_info):
        return [
            (values[index], values[index + 1]) for index in range(0, len(values) - 1, 2)
        ]


class _ColorService:
    @staticmethod
    def hex_to_rgb_int(value):
        color = QColor(value)
        return [color.red(), color.green(), color.blue()]


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

    def test_plan_and_pdf_export_share_highlight_color_and_full_opacity(self):
        annotation = self._highlight()
        item = self._render_annotation(annotation)
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = _IdentityCoordinateSystem()
        exporter._color_service = _ColorService()
        exported = exporter._collect_highlights("", [annotation], object())
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0].color, [255, 255, 0])
        self.assertEqual(exported[0].opacity, 1.0)
        self.assertEqual(item.brush().color(), QColor("#ffff00"))
        self.assertEqual(item.brush().color().alphaF(), exported[0].opacity)

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


if __name__ == "__main__":
    unittest.main()
