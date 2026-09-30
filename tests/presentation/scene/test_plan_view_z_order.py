import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.scene.plan_view_z_order import (
    FOREGROUND_OVERLAY_Z,
    PAGE_IMAGE_Z,
    PAGE_VISIBLE_FRAME_Z,
    PAPER_HIGHLIGHT_Z,
    TAKEOFF_BODY_Z,
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
