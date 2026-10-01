import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.color_swatch import rounded_color_swatch
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


class ColorSwatchPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_color_preview_swatch_has_rounded_transparent_corners(self):
        pixmap = rounded_color_swatch(QtGui.QColor("#123456"), 24)
        image = pixmap.toImage()
        self.assertEqual(image.pixelColor(12, 12).name(), "#123456")
        self.assertEqual(image.pixelColor(12, 12).alpha(), 255)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertLess(image.pixelColor(1, 1).alpha(), 64)
        self.assertEqual(image.pixelColor(12, 1).alpha(), 255)
        self.assertEqual(image.pixelColor(1, 12).alpha(), 255)

    def test_zero_radius_swatch_keeps_square_inset_corner(self):
        image = rounded_color_swatch(QtGui.QColor("#123456"), 24, radius=0).toImage()
        self.assertEqual(image.pixelColor(1, 1).name(), "#123456")
        self.assertEqual(image.pixelColor(1, 1).alpha(), 255)
        self.assertEqual(image.pixelColor(22, 22).alpha(), 255)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)

    def test_swatch_pixmap_has_requested_square_size(self):
        pixmap = rounded_color_swatch(QtGui.QColor("#123456"), 18)
        self.assertEqual((pixmap.width(), pixmap.height()), (18, 18))
