import unittest
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.services.selection_clipboard_service import (
    SelectionClipboardService,
)


class SelectionClipboardFontSnapshotTests(unittest.TestCase):
    def test_takeoff_clipboard_snapshots_current_typed_font_state(self):
        source = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            name_font_name="Segoe UI",
            name_font_size=24,
            name_font_bold=True,
        )
        clipboard = SelectionClipboardService()
        clipboard.copy(
            [source],
            takeoff_extras={
                "takeoff-1": {
                    "NameFontName": "Arial",
                    "NameFontSize": 9,
                    "NameFontBold": False,
                }
            },
        )
        source.name_font_name = "Tahoma"
        source.name_font_size = 30
        source.name_font_bold = False
        copied = clipboard.items[0]
        self.assertEqual(copied.name_font_name, "Segoe UI")
        self.assertEqual(copied.name_font_size, 24)
        self.assertTrue(copied.name_font_bold)
        self.assertEqual(clipboard.get_extras("takeoff-1")["NameFontName"], "Segoe UI")
        self.assertEqual(clipboard.get_extras("takeoff-1")["NameFontSize"], 24)
        self.assertTrue(clipboard.get_extras("takeoff-1")["NameFontBold"])
