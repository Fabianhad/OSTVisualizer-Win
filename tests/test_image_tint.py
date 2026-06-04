import unittest
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.presentation.components.splash_screen import SplashScreen
from ost_visualizer.presentation.components.viewer_cursors import (
    _make_outlined_cursor,
    recolor_pixmap,
)
from ost_visualizer.presentation.visualization.utils import ost_image
from ost_visualizer.presentation.visualization.utils.image_effects import (
    bitonal_image,
    tint_image,
)


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _bgra_pixels(image):
    data = image.to_bytes()
    return [tuple(data[i : i + 4]) for i in range(0, len(data), 4)]


class ImageTintTests(unittest.TestCase):
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

    def test_recolor_pixmap_ignores_null_pixmap_without_qpainter_warning(self):
        messages = []

        def capture_qt_message(_mode, _context, message):
            messages.append(message)

        previous_handler = QtCore.qInstallMessageHandler(capture_qt_message)
        try:
            result = recolor_pixmap(QtGui.QPixmap(), QtGui.QColor(0, 0, 0))
        finally:
            QtCore.qInstallMessageHandler(previous_handler)
        self.assertTrue(result.isNull())
        self.assertEqual(
            [message for message in messages if message.startswith("QPainter::")],
            [],
        )

    def test_recolor_pixmap_ignores_empty_pixmap_without_qpainter_warning(self):
        messages = []

        def capture_qt_message(_mode, _context, message):
            messages.append(message)

        previous_handler = QtCore.qInstallMessageHandler(capture_qt_message)
        try:
            result = recolor_pixmap(QtGui.QPixmap(0, 10), QtGui.QColor(0, 0, 0))
        finally:
            QtCore.qInstallMessageHandler(previous_handler)
        self.assertTrue(result.isNull())
        self.assertEqual(
            [message for message in messages if message.startswith("QPainter::")],
            [],
        )

    def test_recolor_pixmap_recolors_valid_pixmap_and_preserves_alpha(self):
        image = QtGui.QImage(2, 1, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        image.setPixelColor(0, 0, QtGui.QColor(255, 0, 0, 255))
        src = QtGui.QPixmap.fromImage(image)
        result = recolor_pixmap(src, QtGui.QColor(0, 128, 0))
        pixels = result.toImage()
        self.assertEqual(pixels.pixelColor(0, 0), QtGui.QColor(0, 128, 0, 255))
        self.assertEqual(pixels.pixelColor(1, 0).alpha(), 0)
        self.assertEqual(src.toImage().pixelColor(0, 0), QtGui.QColor(255, 0, 0, 255))

    def test_cursor_fallback_for_missing_icon_avoids_qpainter_warning(self):
        messages = []

        def capture_qt_message(_mode, _context, message):
            messages.append(message)

        previous_handler = QtCore.qInstallMessageHandler(capture_qt_message)
        try:
            cursor = _make_outlined_cursor("missing_cursor_icon.svg")
        finally:
            QtCore.qInstallMessageHandler(previous_handler)
        self.assertEqual(cursor.shape(), QtCore.Qt.CursorShape.ArrowCursor)
        self.assertEqual(
            [message for message in messages if message.startswith("QPainter::")],
            [],
        )

    def test_splash_screen_remains_top_level_with_owner(self):
        owner = QtWidgets.QWidget()
        splash = SplashScreen(owner)
        try:
            self.assertTrue(splash.isWindow())
            self.assertIsNone(splash.parentWidget())
        finally:
            splash.cleanup()
            owner.deleteLater()

    def test_tint_grayscale_preserves_antialias_alpha(self):
        tinted = ost_image.tint_grayscale(
            bytes([0, 128, 234, 235, 255]),
            5,
            1,
            255,
            80,
            40,
            235,
        )
        black, gray, near_paper, paper, white = _bgra_pixels(tinted)
        self.assertEqual(black, (40, 80, 255, 255))
        self.assertEqual(gray[:3], (40, 80, 255))
        self.assertEqual(near_paper[:3], (40, 80, 255))
        self.assertEqual(paper, (0, 0, 0, 0))
        self.assertEqual(white, (0, 0, 0, 0))
        self.assertGreater(black[3], gray[3])
        self.assertGreater(gray[3], near_paper[3])
        self.assertGreater(near_paper[3], paper[3])

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

    def test_tint_red_and_blue_keep_alpha_coverage_behavior(self):
        red = _bgra_pixels(ost_image.tint_red(bytes([0, 128, 235]), 3, 1))
        blue = _bgra_pixels(ost_image.tint_blue(bytes([0, 128, 235]), 3, 1))
        self.assertEqual(red[0], (80, 80, 255, 255))
        self.assertEqual(blue[0], (255, 80, 80, 255))
        self.assertEqual(red[1][:3], red[0][:3])
        self.assertEqual(blue[1][:3], blue[0][:3])
        self.assertTrue(0 < red[1][3] < red[0][3])
        self.assertTrue(0 < blue[1][3] < blue[0][3])
        self.assertEqual(red[2], (0, 0, 0, 0))
        self.assertEqual(blue[2], (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
