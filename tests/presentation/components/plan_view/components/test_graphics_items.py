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
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
    QTransform,
)
from PySide6 import QtCore, QtTest, QtWidgets
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    TileGraphicsItem,
)
import unittest
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    ImageBackgroundItem,
    TileGraphicsItem,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _FakePaintDevice as _preferences_support__FakePaintDevice,
    _FakePainter as _preferences_support__FakePainter,
    _app as _preferences_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ClippedTextGraphicsItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_clipped_text_item_inline_edit_bounds_use_textbox_not_text_height(self):
        item = ClippedTextGraphicsItem(
            "Short",
            QtCore.QRectF(0.0, 0.0, 140.0, 90.0),
        )
        item.setFont(QFont("Arial", 10))
        item.setTextWidth(140.0)
        natural_text_rect = item.text_bounding_rect()
        self.assertEqual(item.boundingRect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        self.assertLess(natural_text_rect.height(), item.boundingRect().height())
        item.setPlainText("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6")
        overflowing_text_rect = item.text_bounding_rect()
        self.assertEqual(item.boundingRect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        self.assertNotEqual(
            overflowing_text_rect.height(), item.boundingRect().height()
        )

    def test_clipped_text_annotation_paints_only_inside_textbox(self):
        item = ClippedTextGraphicsItem(
            "Line 1\nLine 2\nLine 3",
            QtCore.QRectF(0.0, 0.0, 120.0, 18.0),
        )
        item.setFont(QFont("Arial", 24))
        item.setDefaultTextColor(QColor("black"))
        item.setTextWidth(120.0)
        image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QPainter(image)
        item.paint(painter, QStyleOptionGraphicsItem(), None)
        painter.end()
        painted_inside_clip = False
        for y in range(0, 18):
            for x in range(image.width()):
                if QColor.fromRgba(image.pixel(x, y)).alpha() > 0:
                    painted_inside_clip = True
                    break
            if painted_inside_clip:
                break
        self.assertTrue(painted_inside_clip)
        for y in range(24, image.height()):
            for x in range(image.width()):
                self.assertEqual(QColor.fromRgba(image.pixel(x, y)).alpha(), 0)


class GraphicsItemsPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_background_images_smooth_but_high_resolution_tiles_stay_crisp_at_one_to_one(
        self,
    ):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        background = ImageBackgroundItem(image, 100.0, 100.0)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )
        self.assertTrue(
            background._should_smooth_transform(_preferences_support__FakePainter())
        )
        self.assertFalse(
            tile._should_smooth_transform(_preferences_support__FakePainter())
        )
        self.assertTrue(
            tile._should_smooth_transform(
                _preferences_support__FakePainter(
                    transform=QtGui.QTransform().scale(2.0, 2.0)
                )
            )
        )
        self.assertTrue(
            tile._should_smooth_transform(
                _preferences_support__FakePainter(device_pixel_ratio=2.0)
            )
        )
