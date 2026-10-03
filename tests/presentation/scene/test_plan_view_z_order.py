import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.scene.plan_view_z_order import (
    ANNOTATION_BODY_Z,
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    PDF_TEXT_SELECTION_Z,
    TAKEOFF_BODY_Z,
    TAKEOFF_DRAW_ORDER_STEP,
    TAKEOFF_LABEL_Z,
    TAKEOFF_PREVIEW_BODY_Z,
    TAKEOFF_PREVIEW_DRAW_INDEX,
    TAKEOFF_PREVIEW_INDICATOR_Z,
    TAKEOFF_PREVIEW_OUTLINE_Z,
    overlay_visual_z,
    takeoff_z_value,
)
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
    SHOW_BOTH,
)
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
)


class PlanViewZOrderCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_highlight_tints_paper_without_tinting_takeoff_body(self):
        scene = QGraphicsScene()
        paper = QGraphicsRectItem(QRectF(0.0, 0.0, 100.0, 100.0))
        paper.setBrush(QBrush(QColor("white")))
        paper.setPen(QPen(Qt.PenStyle.NoPen))
        paper.setZValue(PAGE_IMAGE_Z)
        scene.addItem(paper)
        frame = QGraphicsRectItem(QRectF(0.0, 0.0, 100.0, 100.0))
        frame.setBrush(QBrush(QColor("white")))
        frame.setPen(QPen(Qt.PenStyle.NoPen))
        frame.setZValue(PAGE_VISIBLE_FRAME_Z)
        scene.addItem(frame)
        highlight = QGraphicsRectItem(QRectF(10.0, 10.0, 80.0, 80.0))
        highlight_color = QColor("#ffff00")
        highlight_color.setAlphaF(0.3)
        highlight.setBrush(QBrush(highlight_color))
        highlight.setPen(QPen(Qt.PenStyle.NoPen))
        highlight.setZValue(PAPER_HIGHLIGHT_Z)
        scene.addItem(highlight)
        takeoff = QGraphicsRectItem(QRectF(20.0, 20.0, 60.0, 60.0))
        takeoff.setBrush(QBrush(QColor("#0080ff")))
        takeoff.setPen(QPen(Qt.PenStyle.NoPen))
        takeoff.setZValue(TAKEOFF_BODY_Z)
        scene.addItem(takeoff)
        image = QImage(100, 100, QImage.Format.Format_ARGB32)
        image.fill(QColor("transparent"))
        painter = QPainter(image)
        scene.render(painter, QRectF(0.0, 0.0, 100.0, 100.0), scene.sceneRect())
        painter.end()
        self.assertEqual(image.pixelColor(50, 50).getRgb()[:3], (0, 128, 255))
        self.assertEqual(image.pixelColor(15, 15).getRgb()[:3], (255, 255, 178))
        self.assertEqual(image.pixelColor(5, 5).getRgb()[:3], (255, 255, 255))
        self.assertEqual(image.pixelColor(85, 85).getRgb()[:3], (255, 255, 178))

    def test_documented_layer_stack_orders_paper_highlight_takeoff(self):
        self.assertLess(PAGE_IMAGE_Z, PAGE_VISIBLE_FRAME_Z)
        self.assertLess(PAGE_VISIBLE_FRAME_Z, PAPER_HIGHLIGHT_Z)
        self.assertLess(PAPER_HIGHLIGHT_Z, TAKEOFF_BODY_Z)

    def test_overlay_visual_z_uses_foreground_layer_only_when_showing_both(self):
        self.assertEqual(
            overlay_visual_z(
                SHOW_BOTH, primary_z=PAGE_IMAGE_Z, foreground_z=FOREGROUND_OVERLAY_Z
            ),
            FOREGROUND_OVERLAY_Z,
        )
        for mode in (SHOW_ORIGINAL, SHOW_OVERLAY):
            self.assertEqual(
                overlay_visual_z(
                    mode, primary_z=PAGE_IMAGE_Z, foreground_z=FOREGROUND_OVERLAY_Z
                ),
                PAGE_IMAGE_Z,
            )


class TakeoffPreviewZOrderTests(unittest.TestCase):
    def test_takeoff_z_value_adds_one_draw_step_per_slot(self):
        self.assertEqual(takeoff_z_value(TAKEOFF_BODY_Z, 0), TAKEOFF_BODY_Z)
        self.assertAlmostEqual(
            takeoff_z_value(TAKEOFF_BODY_Z, 7),
            TAKEOFF_BODY_Z + 7 * TAKEOFF_DRAW_ORDER_STEP,
            places=12,
        )
        self.assertLess(
            takeoff_z_value(TAKEOFF_LABEL_Z, 3), takeoff_z_value(TAKEOFF_LABEL_Z, 4)
        )

    def test_preview_body_is_derived_from_the_takeoff_body_band(self):
        self.assertEqual(
            TAKEOFF_PREVIEW_BODY_Z,
            takeoff_z_value(TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX),
        )
        self.assertEqual(
            TAKEOFF_PREVIEW_OUTLINE_Z,
            takeoff_z_value(TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX + 1),
        )
        self.assertEqual(
            TAKEOFF_PREVIEW_INDICATOR_Z,
            takeoff_z_value(TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX + 2),
        )

    def test_preview_stacks_above_every_placed_takeoff_body_and_below_annotations(
        self,
    ):
        last_placed_body = takeoff_z_value(
            TAKEOFF_BODY_Z, TAKEOFF_PREVIEW_DRAW_INDEX - 1
        )
        self.assertGreater(TAKEOFF_PREVIEW_BODY_Z, last_placed_body)
        self.assertLess(TAKEOFF_PREVIEW_BODY_Z, TAKEOFF_PREVIEW_OUTLINE_Z)
        self.assertLess(TAKEOFF_PREVIEW_OUTLINE_Z, TAKEOFF_PREVIEW_INDICATOR_Z)
        self.assertLess(TAKEOFF_PREVIEW_INDICATOR_Z, PDF_TEXT_SELECTION_Z)
        self.assertLess(TAKEOFF_PREVIEW_INDICATOR_Z, ANNOTATION_BODY_Z)
        self.assertLess(ANNOTATION_BODY_Z, TAKEOFF_LABEL_Z)
