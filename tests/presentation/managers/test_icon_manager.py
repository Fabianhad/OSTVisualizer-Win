import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.managers.icon_manager import (
    ICON_SPECS,
    IconId,
    IconManager,
)
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)


class IconManagerPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_text_format_icons_are_registered(self):
        _preferences_support__app()
        expected_icons = {
            IconId.FORMAT_BOLD: (
                "format_bold_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ITALIC: (
                "format_italic_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_UNDERLINE: (
                "format_underlined_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_LEFT: (
                "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_CENTER: (
                "format_align_center_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FORMAT_ALIGN_RIGHT: (
                "format_align_right_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PROJECT_TREE_DATABASE: (
                "database_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.FOLDER: ("folder_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"),
            IconId.PROJECT_TREE_BID: (
                "request_page_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
            IconId.PAGE_TAKEOFF_INDICATOR: (
                "draft_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
            ),
        }
        for icon_id, svg_name in expected_icons.items():
            with self.subTest(icon_id=icon_id):
                self.assertEqual(ICON_SPECS[icon_id].svg_name, svg_name)
                self.assertFalse(IconManager.icon(icon_id).isNull())
