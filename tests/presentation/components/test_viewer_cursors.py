import unittest
from ost_visualizer.presentation.components.viewer_cursors import (
    _make_outlined_cursor,
    make_move_overlay_cursor,
    make_rotate_cursor,
    make_zoom_cursor,
    recolor_pixmap,
)
from PySide6 import QtCore, QtGui, QtWidgets


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class ImageTintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

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
        image = QtGui.QImage(3, 1, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtCore.Qt.GlobalColor.transparent)
        image.setPixelColor(0, 0, QtGui.QColor(255, 0, 0, 255))
        image.setPixelColor(2, 0, QtGui.QColor(255, 0, 0, 128))
        src = QtGui.QPixmap.fromImage(image)
        result = recolor_pixmap(src, QtGui.QColor(0, 128, 0))
        pixels = result.toImage()
        self.assertEqual(result.size(), src.size())
        self.assertEqual(pixels.pixelColor(0, 0), QtGui.QColor(0, 128, 0, 255))
        self.assertEqual(pixels.pixelColor(1, 0).alpha(), 0)
        partial = pixels.pixelColor(2, 0)
        self.assertEqual(partial.alpha(), 128)
        self.assertEqual((partial.red(), partial.green()), (0, 128))
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

    def test_outlined_cursors_are_bitmap_cursors_with_white_glyph_and_black_outline(
        self,
    ):
        for name, factory in (
            ("zoom", make_zoom_cursor),
            ("rotate", make_rotate_cursor),
            ("move", make_move_overlay_cursor),
        ):
            with self.subTest(cursor=name):
                cursor = factory()
                self.assertEqual(cursor.shape(), QtCore.Qt.CursorShape.BitmapCursor)
                self.assertEqual(cursor.hotSpot(), QtCore.QPoint(11, 11))
                pixmap = cursor.pixmap()
                self.assertEqual(pixmap.size(), QtCore.QSize(26, 26))
                image = pixmap.toImage()
                colors = {
                    (c.red(), c.green(), c.blue())
                    for c in (
                        image.pixelColor(x, y)
                        for x in range(image.width())
                        for y in range(image.height())
                    )
                    if c.alpha() == 255
                }
                self.assertIn((255, 255, 255), colors)
                self.assertIn((0, 0, 0), colors)
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
