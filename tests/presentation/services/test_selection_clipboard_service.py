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

    def test_every_dimension_and_name_font_field_is_snapshotted_into_takeoff_and_extras(
        self,
    ):
        source = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            dimension_font_name="Calibri",
            dimension_font_color=255,
            dimension_font_size=11,
            dimension_font_bold=True,
            dimension_font_italic=True,
            dimension_font_underline=True,
            name_font_name="Segoe UI",
            name_font_color=65280,
            name_font_size=24,
            name_font_bold=True,
            name_font_italic=True,
            name_font_underline=True,
        )
        caller_extras = {"takeoff-1": {"Custom": "kept", "FontName": "Stale"}}
        clipboard = SelectionClipboardService()
        clipboard.copy([source], takeoff_extras=caller_extras)
        copied = clipboard.items[0]
        for field_name in (
            "dimension_font_name",
            "dimension_font_color",
            "dimension_font_size",
            "dimension_font_bold",
            "dimension_font_italic",
            "dimension_font_underline",
            "name_font_name",
            "name_font_color",
            "name_font_size",
            "name_font_bold",
            "name_font_italic",
            "name_font_underline",
        ):
            with self.subTest(field=field_name):
                self.assertEqual(
                    getattr(copied, field_name), getattr(source, field_name)
                )
        self.assertEqual(
            clipboard.get_extras("takeoff-1"),
            {
                "Custom": "kept",
                "FontName": "Calibri",
                "FontColor": 255,
                "FontSize": 11,
                "FontBold": True,
                "FontItalic": True,
                "FontUnderline": True,
                "NameFontName": "Segoe UI",
                "NameFontColor": 65280,
                "NameFontSize": 24,
                "NameFontBold": True,
                "NameFontItalic": True,
                "NameFontUnderline": True,
            },
        )
        self.assertEqual(caller_extras["takeoff-1"]["FontName"], "Stale")

    def test_copied_takeoff_does_not_alias_source_position_and_recopy_replaces_content(
        self,
    ):
        source = Takeoff(
            uid="takeoff-1",
            condition_uid="condition-1",
            page_uid="page-1",
            position=[1.0, 2.0],
        )
        clipboard = SelectionClipboardService()
        clipboard.copy([source], source_bid_uid="bid-1", source_file_path="C:/a.mdb")
        source.position.append(3.0)
        self.assertEqual(clipboard.items[0].position, [1.0, 2.0])
        self.assertTrue(clipboard.source_matches_database("C:\\a.mdb"))
        self.assertFalse(clipboard.source_matches_database("C:/b.mdb"))
        self.assertFalse(clipboard.source_matches_database(None))
        clipboard.copy([])
        self.assertFalse(clipboard.has_content())
        self.assertEqual(clipboard.get_extras("takeoff-1"), {})
        self.assertFalse(clipboard.source_matches_database("C:/a.mdb"))
