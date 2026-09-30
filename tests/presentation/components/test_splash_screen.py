import unittest
from ost_visualizer.presentation.components.splash_screen import SplashScreen
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
