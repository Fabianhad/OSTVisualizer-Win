import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
    HighlightGraphicsItem,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QStyle,
    QStyleOptionGraphicsItem,
)


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


class HighlightPlanPdfParityTests(unittest.TestCase):
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

    def test_plan_highlight_multiplies_with_backdrop_like_exported_multiply_blend(
        self,
    ):
        annotation = self._highlight()
        item = self._render_annotation(annotation)
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = _IdentityCoordinateSystem()
        exporter._color_service = _ColorService()
        exported = exporter._collect_highlights("", [annotation], object())[0]
        image = self._paint_item(item, QStyle.StateFlag.State_None)
        # Multiply of the #808080 backdrop with the exported yellow, per channel:
        # a Normal-mode fill would instead replace the backdrop with pure yellow.
        expected = [round(128 * channel / 255) for channel in exported.color]
        self.assertEqual(expected, [128, 128, 0])
        inside = image.pixelColor(60, 40)
        self.assertEqual([inside.red(), inside.green(), inside.blue()], expected)
        outside = image.pixelColor(5, 5)
        self.assertEqual([outside.red(), outside.green(), outside.blue()], [128] * 3)
