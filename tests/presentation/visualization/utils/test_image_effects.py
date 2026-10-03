import unittest
from ost_visualizer.presentation.visualization.utils.image_effects import (
    apply_page_image_effects,
    bitonal_image,
    invert_image,
    page_effect_paper_color,
    tint_image,
)
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _gray_image(*grays):
    image = QtGui.QImage(len(grays), 1, QtGui.QImage.Format.Format_ARGB32)
    for x, gray in enumerate(grays):
        image.setPixelColor(x, 0, QtGui.QColor(gray, gray, gray))
    return image


def _gray_values(image):
    return [image.pixelColor(x, 0).red() for x in range(image.width())]


class TintImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_tint_image_ignores_grayscale_scanline_padding(self):
        image = QtGui.QImage(5, 2, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(255, 255, 255))
        image.setPixelColor(2, 0, QtGui.QColor(0, 0, 0))
        image.setPixelColor(2, 1, QtGui.QColor(0, 0, 0))
        tinted = tint_image(image, 80, 80, 255)
        for y in range(2):
            for x in range(5):
                pixel = tinted.pixelColor(x, y)
                if x == 2:
                    self.assertEqual(pixel, QtGui.QColor(80, 80, 255, 255))
                else:
                    self.assertEqual(pixel.alpha(), 0)

    def test_tint_image_alpha_scales_with_darkness_below_white_threshold(self):
        # Native ost_image.tint_grayscale is real. Opaque tint at black fading
        # linearly to transparent at gray 235 (255 * (1 - gray / 235)); a width
        # of 4 has no scanline padding, covering the unpadded copy path.
        image = QtGui.QImage(4, 2, QtGui.QImage.Format.Format_ARGB32)
        grays = [(0, 128, 200, 255), (255, 200, 128, 0)]
        for y, row in enumerate(grays):
            for x, gray in enumerate(row):
                image.setPixelColor(x, y, QtGui.QColor(gray, gray, gray))
        tinted = tint_image(image, 10, 20, 30)
        expected_alpha = [(255, 116, 38, 0), (0, 38, 116, 255)]
        self.assertEqual((tinted.width(), tinted.height()), (4, 2))
        for y in range(2):
            for x in range(4):
                with self.subTest(x=x, y=y):
                    pixel = tinted.pixelColor(x, y)
                    self.assertEqual(pixel.alpha(), expected_alpha[y][x])
                    if expected_alpha[y][x]:
                        self.assertEqual(pixel.getRgb()[:3], (10, 20, 30))


class BitonalImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_bitonal_image_ignores_null_image_without_qpainter_warning(self):
        messages = []

        def capture_qt_message(_mode, _context, message):
            messages.append(message)

        previous_handler = QtCore.qInstallMessageHandler(capture_qt_message)
        try:
            result = bitonal_image(QtGui.QImage())
        finally:
            QtCore.qInstallMessageHandler(previous_handler)
        self.assertTrue(result.isNull())
        self.assertEqual(
            [message for message in messages if message.startswith("QPainter::")],
            [],
        )

    def test_bitonal_image_clamps_paper_to_220_and_keeps_darker_pixels(self):
        source = _gray_image(255, 220, 200, 0)
        result = bitonal_image(source)
        self.assertEqual(
            [result.pixelColor(x, 0).getRgb() for x in range(4)],
            [
                (220, 220, 220, 255),
                (220, 220, 220, 255),
                (200, 200, 200, 255),
                (0, 0, 0, 255),
            ],
        )
        self.assertEqual(_gray_values(source), [255, 220, 200, 0])


class InvertImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_invert_image_inverts_rgb_keeps_alpha_and_leaves_source_unchanged(self):
        source = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_ARGB32)
        source.setPixelColor(0, 0, QtGui.QColor(10, 20, 30, 128))
        source.setPixelColor(1, 0, QtGui.QColor(255, 255, 255, 255))
        result = invert_image(source)
        self.assertEqual(result.pixelColor(0, 0).getRgb(), (245, 235, 225, 128))
        self.assertEqual(result.pixelColor(1, 0).getRgb(), (0, 0, 0, 255))
        self.assertEqual(source.pixelColor(0, 0).getRgb(), (10, 20, 30, 128))


class PageImageEffectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_paper_color_follows_bitonal_then_invert(self):
        self.assertEqual(page_effect_paper_color().getRgb(), (255, 255, 255, 255))
        self.assertEqual(
            page_effect_paper_color(bitonal=True).getRgb(), (220, 220, 220, 255)
        )
        self.assertEqual(page_effect_paper_color(invert=True).getRgb(), (0, 0, 0, 255))
        self.assertEqual(
            page_effect_paper_color(invert=True, bitonal=True).getRgb(),
            (35, 35, 35, 255),
        )

    def test_no_effects_returns_the_same_image_object(self):
        source = _gray_image(255, 0)
        self.assertIs(apply_page_image_effects(source), source)

    def test_effects_render_paper_exactly_as_the_paper_color_predicts(self):
        paper = _gray_image(255, 255)
        for invert in (False, True):
            for bitonal in (False, True):
                if not (invert or bitonal):
                    continue
                with self.subTest(invert=invert, bitonal=bitonal):
                    result = apply_page_image_effects(
                        paper, invert=invert, bitonal=bitonal
                    )
                    expected = page_effect_paper_color(invert=invert, bitonal=bitonal)
                    self.assertEqual(
                        result.pixelColor(0, 0).getRgb()[:3], expected.getRgb()[:3]
                    )
        # Bitonal runs before invert: ink 0 stays 0 then inverts to 255, while
        # invert-first would darken the inverted ink back down to 220.
        ink = _gray_image(0)
        inked = apply_page_image_effects(ink, invert=True, bitonal=True)
        self.assertEqual(inked.pixelColor(0, 0).getRgb()[:3], (255, 255, 255))
        self.assertEqual(_gray_values(paper), [255, 255])
