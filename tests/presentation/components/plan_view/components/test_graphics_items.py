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


def _quadrant_image():
    """4x2 image: red/blue on the top row, green/yellow on the bottom row."""
    image = QtGui.QImage(4, 2, QtGui.QImage.Format.Format_ARGB32)
    image.setPixelColor(0, 0, QtGui.QColor(255, 0, 0))
    image.setPixelColor(1, 0, QtGui.QColor(255, 0, 0))
    image.setPixelColor(2, 0, QtGui.QColor(0, 0, 255))
    image.setPixelColor(3, 0, QtGui.QColor(0, 0, 255))
    image.setPixelColor(0, 1, QtGui.QColor(0, 255, 0))
    image.setPixelColor(1, 1, QtGui.QColor(0, 255, 0))
    image.setPixelColor(2, 1, QtGui.QColor(255, 255, 0))
    image.setPixelColor(3, 1, QtGui.QColor(255, 255, 0))
    return image


class GraphicsItemsGeometryAndPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def tearDown(self):
        self.app.processEvents()

    def assertColourNear(self, actual, expected, tolerance=24):
        # Smoothed scaling blends neighbouring blocks slightly; the four test colours
        # are far apart, so a small per-channel tolerance still identifies the block.
        for channel in ("red", "green", "blue", "alpha"):
            self.assertLessEqual(
                abs(getattr(actual, channel)() - getattr(expected, channel)()),
                tolerance,
                msg="%s: %s vs %s" % (channel, actual.getRgb(), expected.getRgb()),
            )

    @staticmethod
    def _paint(item, size, transform=None):
        target = QtGui.QImage(size[0], size[1], QtGui.QImage.Format.Format_ARGB32)
        target.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(target)
        try:
            if transform is not None:
                painter.setTransform(transform)
            item.paint(painter, None)
        finally:
            painter.end()
        return target

    def test_bounding_rects_are_the_scene_rects_given_at_construction(self):
        image = _quadrant_image()
        background = ImageBackgroundItem(image, 120.0, 80.0)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(10.0, 20.0, 30.0, 40.0),
            QtCore.QRectF(2.0, 0.0, 2.0, 2.0),
        )
        self.assertEqual(
            background.boundingRect(), QtCore.QRectF(0.0, 0.0, 120.0, 80.0)
        )
        self.assertEqual(tile.boundingRect(), QtCore.QRectF(10.0, 20.0, 30.0, 40.0))

    def test_background_item_paints_the_whole_image_scaled_into_the_scene_rect(self):
        item = ImageBackgroundItem(_quadrant_image(), 32.0, 16.0)
        target = self._paint(item, (32, 16))
        # Block centres only: the item smooths, so block edges are interpolated.
        expected = {
            (8, 4): QtGui.QColor(255, 0, 0),
            (24, 4): QtGui.QColor(0, 0, 255),
            (8, 12): QtGui.QColor(0, 255, 0),
            (24, 12): QtGui.QColor(255, 255, 0),
        }
        for (x, y), colour in expected.items():
            with self.subTest(pixel=(x, y)):
                self.assertColourNear(target.pixelColor(x, y), colour)

    def test_tile_paints_only_its_source_rect_into_its_scene_rect(self):
        tile = TileGraphicsItem(
            _quadrant_image(),
            QtCore.QRectF(10.0, 10.0, 20.0, 10.0),
            QtCore.QRectF(2.0, 0.0, 2.0, 2.0),
        )
        target = self._paint(tile, (40, 30))
        # The right half of the image (blue over yellow) fills the 20x10 scene rect.
        self.assertColourNear(target.pixelColor(20, 12), QtGui.QColor(0, 0, 255))
        self.assertColourNear(target.pixelColor(20, 18), QtGui.QColor(255, 255, 0))
        for x, y in ((5, 15), (35, 15), (20, 5), (20, 25)):
            with self.subTest(outside=(x, y)):
                self.assertEqual(target.pixelColor(x, y).alpha(), 0)

    def test_smoothing_ratio_pairs_each_axis_with_its_own_dimensions(self):
        image = QtGui.QImage(80, 40, QtGui.QImage.Format.Format_ARGB32)

        def tile(width, height):
            return TileGraphicsItem(
                image,
                QtCore.QRectF(0.0, 0.0, width, height),
                QtCore.QRectF(0.0, 0.0, 80.0, 40.0),
            )

        def smooth(item, transform=None):
            return item._should_smooth_transform(
                _preferences_support__FakePainter(transform=transform)
            )

        self.assertIs(smooth(tile(80.0, 40.0)), False)
        self.assertIs(smooth(tile(160.0, 40.0)), True)
        self.assertIs(smooth(tile(80.0, 80.0)), True)
        self.assertIs(smooth(tile(40.0, 40.0)), True)
        self.assertIs(smooth(tile(80.0, 20.0)), True)
        # Anisotropic transforms are matched axis by axis with the item geometry.
        self.assertIs(
            smooth(tile(160.0, 20.0), QtGui.QTransform().scale(0.5, 2.0)), False
        )
        self.assertIs(
            smooth(tile(80.0, 40.0), QtGui.QTransform().scale(2.0, 0.5)), True
        )

    def test_smoothing_ignores_translation_and_keeps_inclusive_tolerance_edges(self):
        image = QtGui.QImage(100, 100, QtGui.QImage.Format.Format_ARGB32)
        tile = TileGraphicsItem(
            image,
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
            QtCore.QRectF(0.0, 0.0, 100.0, 100.0),
        )

        def smooth(transform):
            return tile._should_smooth_transform(
                _preferences_support__FakePainter(transform=transform)
            )

        moved = QtGui.QTransform().translate(30.0, 50.0)
        self.assertIs(smooth(moved), False)
        self.assertIs(smooth(moved.rotate(30.0)), False)
        self.assertIs(
            smooth(QtGui.QTransform().translate(7.0, 3.0).scale(2.0, 2.0)), True
        )
        # Both edges of the 1% band are still crisp; just beyond them is smoothed.
        self.assertIs(smooth(QtGui.QTransform().scale(0.99, 0.99)), False)
        self.assertIs(smooth(QtGui.QTransform().scale(1.01, 1.01)), False)
        # 0.99005 is inside the band, while its reciprocal (1.01005) would not be.
        self.assertIs(smooth(QtGui.QTransform().scale(0.99005, 0.99005)), False)
        self.assertIs(smooth(QtGui.QTransform().scale(1.0101, 1.0101)), True)
        self.assertIs(smooth(QtGui.QTransform().scale(0.9899, 0.9899)), True)
        # Each axis must be crisp on its own.
        self.assertIs(smooth(QtGui.QTransform().scale(1.0, 1.0101)), True)
        self.assertIs(smooth(QtGui.QTransform().scale(1.0101, 1.0)), True)

    def test_images_one_pixel_wide_or_tall_are_still_measured(self):
        for width, height in ((1, 1), (1, 5), (5, 1)):
            with self.subTest(size=(width, height)):
                image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_ARGB32)
                tile = TileGraphicsItem(
                    image,
                    QtCore.QRectF(0.0, 0.0, float(width), float(height)),
                    QtCore.QRectF(0.0, 0.0, float(width), float(height)),
                )
                self.assertIs(
                    tile._should_smooth_transform(_preferences_support__FakePainter()),
                    False,
                )
                self.assertIs(
                    tile._should_smooth_transform(
                        _preferences_support__FakePainter(
                            transform=QtGui.QTransform().scale(2.0, 2.0)
                        )
                    ),
                    True,
                )

    def test_cleared_image_reports_a_plain_false_and_stops_painting(self):
        tile = TileGraphicsItem(
            _quadrant_image(),
            QtCore.QRectF(0.0, 0.0, 8.0, 4.0),
            QtCore.QRectF(0.0, 0.0, 4.0, 2.0),
        )
        tile.clear_image()
        self.assertIs(
            tile._should_smooth_transform(_preferences_support__FakePainter()), False
        )
        target = self._paint(tile, (8, 4))
        self.assertEqual(target.pixelColor(2, 2).alpha(), 0)

    def test_clipped_text_set_clip_rect_notifies_the_scene_of_old_and_new_bounds(self):
        scene = QtWidgets.QGraphicsScene(QtCore.QRectF(0.0, 0.0, 400.0, 400.0))
        item = ClippedTextGraphicsItem("Text", QtCore.QRectF(0.0, 0.0, 20.0, 20.0))
        scene.addItem(item)
        QtTest.QTest.qWait(30)
        changed = []
        scene.changed.connect(lambda rects: changed.extend(rects))
        item.set_clip_rect(QtCore.QRectF(200.0, 200.0, 20.0, 20.0))
        QtTest.QTest.qWait(30)
        union = QtCore.QRectF()
        for rect in changed:
            union = union.united(rect)
        self.assertTrue(union.contains(QtCore.QRectF(0.0, 0.0, 20.0, 20.0)))
        self.assertTrue(union.contains(QtCore.QRectF(200.0, 200.0, 20.0, 20.0)))

    def test_clipped_text_paint_restores_the_painter_state(self):
        item = ClippedTextGraphicsItem("Text", QtCore.QRectF(0.0, 0.0, 30.0, 20.0))
        target = QtGui.QImage(60, 40, QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(target)
        try:
            painter.setPen(QtGui.QColor("red"))
            painter.setTransform(QtGui.QTransform().translate(3.0, 4.0))
            self.assertFalse(painter.hasClipping())
            item.paint(painter, QStyleOptionGraphicsItem(), None)
            self.assertFalse(painter.hasClipping())
            self.assertEqual(painter.pen().color(), QtGui.QColor("red"))
            self.assertEqual(
                painter.worldTransform(), QtGui.QTransform().translate(3.0, 4.0)
            )
        finally:
            painter.end()


class _UpdateRecordingTextItem(ClippedTextGraphicsItem):
    def __init__(self, text, clip_rect):
        super().__init__(text, clip_rect)
        self.update_calls = 0

    def update(self, *args):
        self.update_calls += 1
        super().update(*args)


class ClippedTextRepaintRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def test_set_clip_rect_requests_a_repaint_and_stores_a_copy(self):
        item = _UpdateRecordingTextItem("Text", QtCore.QRectF(0.0, 0.0, 20.0, 20.0))
        new_rect = QtCore.QRectF(5.0, 6.0, 30.0, 40.0)
        item.set_clip_rect(new_rect)
        self.assertEqual(item.update_calls, 1)
        self.assertEqual(item.clip_rect(), QtCore.QRectF(5.0, 6.0, 30.0, 40.0))
        self.assertEqual(item.boundingRect(), QtCore.QRectF(5.0, 6.0, 30.0, 40.0))
        new_rect.setWidth(99.0)
        self.assertEqual(item.clip_rect().width(), 30.0)
