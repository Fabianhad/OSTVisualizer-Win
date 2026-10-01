import unittest
from ost_visualizer.presentation.components.splash_screen import SplashScreen
from ost_visualizer.presentation.utils.theme import (
    get_splash_message_font,
    get_splash_title_font,
)
from ost_visualizer.presentation.config import (
    SPLASH_MESSAGE_MARGIN,
    SPLASH_SCREEN_HEIGHT,
    SPLASH_SCREEN_WIDTH,
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

    def test_splash_screen_remains_top_level_with_owner(self):
        owner = QtWidgets.QWidget()
        splash = SplashScreen(owner)
        try:
            self.assertTrue(splash.isWindow())
            self.assertIsNone(splash.parentWidget())
        finally:
            splash.cleanup()
            owner.deleteLater()

    def test_splash_has_configured_size_and_cleanup_closes_and_clears_text(self):
        splash = SplashScreen()
        try:
            splash.show()
            self.app.processEvents()
            self.assertTrue(splash.isVisible())
            self.assertEqual(
                splash.pixmap().size(),
                QtCore.QSize(SPLASH_SCREEN_WIDTH, SPLASH_SCREEN_HEIGHT),
            )
            self.assertEqual(splash._title, "OST Visualizer")
            self.assertEqual(splash._message, "")
        finally:
            splash.cleanup()
        self.assertFalse(splash.isVisible())
        self.assertIsNone(splash._title)
        self.assertIsNone(splash._message)
        splash.cleanup()

    def test_splash_draws_title_and_optional_message(self):
        splash = SplashScreen()
        self.addCleanup(splash.cleanup)
        background = splash.pixmap().toImage()

        def render():
            image = QtGui.QImage(background.size(), QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtCore.Qt.GlobalColor.transparent)
            painter = QtGui.QPainter(image)
            splash.drawContents(painter)
            painter.end()
            return image

        def inked_rows(image):
            return {
                y
                for y in range(image.height())
                for x in range(image.width())
                if image.pixelColor(x, y).alpha() > 0
            }

        title_height = QtGui.QFontMetrics(get_splash_title_font()).height()
        message_height = QtGui.QFontMetrics(get_splash_message_font()).height()
        title_top = SPLASH_SCREEN_HEIGHT // 3
        title_only = inked_rows(render())
        self.assertTrue(title_only)
        self.assertTrue(
            all(title_top - 2 <= y <= title_top + title_height + 2 for y in title_only)
        )
        splash._message = "Loading"
        with_message = inked_rows(render())
        message_top = SPLASH_SCREEN_HEIGHT - message_height - SPLASH_MESSAGE_MARGIN
        added = with_message - title_only
        self.assertTrue(added)
        self.assertTrue(
            all(message_top - 2 <= y <= message_top + message_height + 2 for y in added)
        )
