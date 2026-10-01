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
        self.assertGreater(overflowing_text_rect.height(), item.boundingRect().height())

    def test_clipped_text_item_clip_rect_is_copied_and_drives_bounding_rect(self):
        source_rect = QtCore.QRectF(0.0, 0.0, 140.0, 90.0)
        item = ClippedTextGraphicsItem("Short", source_rect)
        source_rect.setWidth(10.0)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        returned_rect = item.clip_rect()
        returned_rect.setHeight(1.0)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(0.0, 0.0, 140.0, 90.0))
        replacement_rect = QtCore.QRectF(5.0, 6.0, 30.0, 20.0)
        item.set_clip_rect(replacement_rect)
        replacement_rect.setWidth(99.0)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(5.0, 6.0, 30.0, 20.0))
        self.assertEqual(item.boundingRect(), QtCore.QRectF(5.0, 6.0, 30.0, 20.0))

    def test_clipped_text_annotation_paints_only_inside_textbox(self):
        item = ClippedTextGraphicsItem(
            "Line 1\nLine 2\nLine 3",
            QtCore.QRectF(0.0, 0.0, 60.0, 18.0),
        )
        item.setFont(QFont("Arial", 24))
        item.setDefaultTextColor(QColor("black"))
        item.setTextWidth(120.0)

        def painted_alpha_pixels(clip_rect):
            item.set_clip_rect(clip_rect)
            image = QImage(160, 100, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QPainter(image)
            try:
                item.paint(painter, QStyleOptionGraphicsItem(), None)
            finally:
                painter.end()
            return {
                (x, y)
                for y in range(image.height())
                for x in range(image.width())
                if QColor.fromRgba(image.pixel(x, y)).alpha() > 0
            }

        unclipped_pixels = painted_alpha_pixels(QtCore.QRectF(0.0, 0.0, 160.0, 100.0))
        self.assertTrue(
            any(y >= 24 for _x, y in unclipped_pixels),
            "control: unclipped text must extend below the 18px textbox",
        )
        self.assertTrue(
            any(x >= 60 for x, _y in unclipped_pixels),
            "control: unclipped text must extend right of the 60px textbox",
        )
        clipped_pixels = painted_alpha_pixels(QtCore.QRectF(0.0, 0.0, 60.0, 18.0))
        self.assertTrue(clipped_pixels)
        self.assertEqual(
            {(x, y) for x, y in clipped_pixels if y >= 18 or x >= 60}, set()
        )
        self.assertEqual(
            clipped_pixels,
            {(x, y) for x, y in unclipped_pixels if y < 18 and x < 60},
        )


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

    def test_tile_smoothing_follows_effective_device_scale_within_tolerance(self):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )

        def scale(x, y):
            return QtGui.QTransform().scale(x, y)

        cases = (
            ("within tolerance above", scale(1.009, 1.009), 1.0, False),
            ("within tolerance below", scale(0.991, 0.991), 1.0, False),
            ("beyond tolerance above", scale(1.02, 1.02), 1.0, True),
            ("beyond tolerance below", scale(0.98, 0.98), 1.0, True),
            ("downscaled", scale(0.5, 0.5), 1.0, True),
            ("only x crisp", scale(1.0, 2.0), 1.0, True),
            ("only y crisp", scale(2.0, 1.0), 1.0, True),
            ("hidpi compensated", scale(0.5, 0.5), 2.0, False),
            ("rotated one to one", QtGui.QTransform().rotate(30.0), 1.0, False),
        )
        for label, transform, device_pixel_ratio, expected in cases:
            with self.subTest(case=label):
                painter = _preferences_support__FakePainter(
                    transform=transform, device_pixel_ratio=device_pixel_ratio
                )
                self.assertIs(tile._should_smooth_transform(painter), expected)

    def test_tile_smoothing_accounts_for_scene_rect_versus_image_size(self):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        enlarged_tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 200.0, 200.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )
        self.assertTrue(
            enlarged_tile._should_smooth_transform(_preferences_support__FakePainter())
        )
        self.assertFalse(
            enlarged_tile._should_smooth_transform(
                _preferences_support__FakePainter(
                    transform=QtGui.QTransform().scale(0.5, 0.5)
                )
            )
        )

    def test_cleared_tile_image_is_never_smoothed_and_paint_leaves_hint_alone(self):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )
        tile.clear_image()
        self.assertFalse(
            tile._should_smooth_transform(
                _preferences_support__FakePainter(
                    transform=QtGui.QTransform().scale(2.0, 2.0)
                )
            )
        )
        target = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(target)
        try:
            painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
            tile.paint(painter, None)
            self.assertTrue(
                painter.testRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
            )
        finally:
            painter.end()

    def test_paint_sets_smooth_render_hint_from_the_smoothing_decision(self):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("red"))
        scene_rect = QtCore.QRectF(0.0, 0.0, 100.0, 100.0)
        background = ImageBackgroundItem(image, 100.0, 100.0)
        tile = TileGraphicsItem(image, scene_rect, scene_rect)
        for label, item, scale, expected_hint in (
            ("background at one to one", background, 1.0, True),
            ("tile at one to one", tile, 1.0, False),
            ("tile upscaled", tile, 2.0, True),
        ):
            with self.subTest(case=label):
                target = QtGui.QImage(200, 200, QtGui.QImage.Format.Format_ARGB32)
                painter = QtGui.QPainter(target)
                try:
                    painter.setRenderHint(
                        QtGui.QPainter.RenderHint.SmoothPixmapTransform,
                        not expected_hint,
                    )
                    painter.scale(scale, scale)
                    item.paint(painter, None)
                    self.assertIs(
                        painter.testRenderHint(
                            QtGui.QPainter.RenderHint.SmoothPixmapTransform
                        ),
                        expected_hint,
                    )
                finally:
                    painter.end()
