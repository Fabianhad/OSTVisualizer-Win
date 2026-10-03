import os
import unittest
from pathlib import Path
from unittest.mock import patch
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
    qfont_from_resolved_definition,
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
        self.assertEqual(fallback.point_size, 72)
        self.assertIn(fallback.style_name, lossless_font_styles(fallback.family))

    def test_installed_families_are_case_insensitively_sorted(self):
        families = installed_font_families()
        self.assertTrue(families)
        self.assertEqual(families, tuple(sorted(families, key=str.casefold)))
        with patch.object(
            QtGui.QFontDatabase,
            "families",
            return_value=["banana", "Cherry", "apple", "Banana2", "Apple2"],
        ):
            self.assertEqual(
                installed_font_families(),
                ("apple", "Apple2", "banana", "Banana2", "Cherry"),
            )

    def test_exact_installed_style_is_kept_and_family_case_is_normalized(self):
        resolved = resolve_font_definition(
            FontDefinition("arial", "bold italic", 24, 700, True, True)
        )
        self.assertEqual(
            resolved, FontDefinition("Arial", "Bold Italic", 24, 700, True, True)
        )
        italic = FontDefinition("Arial", "Italic", 12, 400, True, False)
        self.assertEqual(resolve_font_definition(italic), italic)

    def test_unrepresentable_weight_has_no_lossless_style(self):
        definition = FontDefinition("Arial", "Regular", 12, 550, False, False)
        with self.assertRaises(ValueError):
            resolve_font_definition(definition)

    def test_resolution_requires_gui_application(self):
        definition = FontDefinition("Arial", "Regular", 12, 400, False, False)
        with patch.object(QtGui.QGuiApplication, "instance", return_value=None):
            with self.assertRaises(RuntimeError):
                resolve_font_definition(definition)

    def test_resolved_definition_round_trips_to_matching_qfont(self):
        resolved = resolve_font_definition(
            FontDefinition("Arial", "Bold Italic", 18, 700, True, True)
        )
        font = qfont_from_resolved_definition(resolved)
        self.assertEqual(font.family(), "Arial")
        self.assertEqual(font.styleName(), "Bold Italic")
        self.assertEqual(font.pointSize(), 18)
        self.assertTrue(font.bold())
        self.assertTrue(font.italic())
        self.assertTrue(font.underline())
