import unittest
from ost_visualizer.presentation.visualization.utils.image_effects import (
    bitonal_image,
    tint_image,
)
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


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
