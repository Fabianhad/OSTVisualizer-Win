import os
import unittest
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
from ost_visualizer.presentation.utils.font_catalog import (
    installed_font_families,
    lossless_font_styles,
    resolve_font_definition,
)
from PySide6 import QtCore, QtGui, QtWidgets


class FontCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_lossless_style_filter_and_missing_font_fallback(self):
        families = installed_font_families()
        self.assertTrue(any(family.casefold() == "arial" for family in families))
        styles = lossless_font_styles("Arial")
        self.assertIn("Regular", styles)
        self.assertIn("Bold", styles)
        self.assertNotIn("Narrow", styles)
        self.assertNotIn("Black", styles)
        mismatched_style = resolve_font_definition(
            FontDefinition("Arial", "Bold", 12, 400, False, False)
        )
        self.assertEqual(mismatched_style.style_name, "Regular")
        fallback = resolve_font_definition(
            FontDefinition(
                "Definitely Missing Family",
                "Definitely Missing Style",
                72,
                700,
                True,
                True,
            )
        )
        self.assertEqual(fallback.family.casefold(), "arial")
        self.assertEqual((fallback.weight, fallback.italic), (700, True))
        self.assertTrue(fallback.underline)
