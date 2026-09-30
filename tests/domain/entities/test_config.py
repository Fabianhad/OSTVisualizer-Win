from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from PySide6 import QtCore, QtGui, QtWidgets
from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
    AnnotationCaptionId,
)
from pathlib import Path
import os
import unittest
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition
from ost_visualizer.presentation.utils.annotation_defaults import (
    apply_config_owned_annotation_defaults,
    build_placed_annotation_spec,
    set_annotation_styles_by_tool,
)
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import tests.presentation.components.test_toolbar_overflow as component_tests
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ConfigValidationTests(unittest.TestCase):
    def test_config_rejects_truthy_string_for_boolean_field(self):
        with self.assertRaisesRegex(TypeError, "show_toolbar_text"):
            Config.from_dict({"show_toolbar_text": "false"})


class ConfigPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_config_defaults_preserve_existing_enabled_behaviors(self):
        config = Config()
        self.assertFalse(config.pdf_annotation_captions_enabled)
        self.assertEqual(
            config.pdf_annotation_caption_ids,
            DEFAULT_ANNOTATION_CAPTION_IDS,
        )
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)
        self.assertTrue(config.elevation_callout_include_condition)
        self.assertTrue(config.elevation_callout_include_top)
        self.assertTrue(config.elevation_callout_include_bottom)
        self.assertTrue(config.elevation_callout_include_cubic_yards)
        self.assertEqual(config.html_elevation_callout_color, "#ff0000")
        self.assertEqual(config.pdf_elevation_callout_color, "#ff0000")
        self.assertTrue(config.show_toolbar_text)
        self.assertTrue(config.display_modes_synced)
        self.assertEqual(config.display_mode_3d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertEqual(config.display_mode_2d, Config.DISPLAY_MODE_ORIGINAL)
        self.assertFalse(config.grayscale_enabled)
        self.assertFalse(config.disable_high_resolution_images)
        self.assertTrue(config.enable_intelligent_paste)
        self.assertTrue(config.enable_advanced_mouse_controls)
        self.assertFalse(config.use_full_window_crosshairs)
        self.assertEqual(config.crosshair_color, "#00ff00")
        self.assertEqual(config.crosshair_line_thickness, 1)
        self.assertFalse(config.allow_add_page_from_takeoff_tab)
        self.assertEqual(config.mouse_unpressed_snap_angle, 15)
        self.assertEqual(config.mouse_pressed_snap_angle, 0)
        self.assertTrue(config.snap_to_grid_enabled)
        self.assertEqual(
            config.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_pdf_lines_enabled)
        self.assertEqual(
            config.snap_to_pdf_lines_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_takeoffs_enabled)
        self.assertEqual(
            config.snap_to_takeoffs_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertTrue(config.snap_to_right_angle_enabled)
        self.assertEqual(
            config.snap_to_right_angle_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(config.default_auto_zoom_level, 0)


class ConfigFontColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        set_annotation_styles_by_tool({}, Config())
        self.app.processEvents()

    def test_canonical_defaults_match_original_ost_contract(self):
        config = Config()
        self.assertEqual(
            config.default_text_font,
            FontDefinition("Arial", "Bold", 12, 700, False, False),
        )
        self.assertEqual(config.default_area_label_font.point_size, 10)
        self.assertEqual(config.default_dimension_annotation_font.weight, 700)
        self.assertEqual(config.default_style_label_font.style_name, "Bold")
        self.assertEqual(
            (
                config.default_text_color,
                config.default_area_label_color,
                config.default_dimension_annotation_color,
                config.default_style_label_color,
                config.default_highlight_color,
                config.default_hotlink_color,
                config.inactive_object_color,
            ),
            (
                "#ff0000",
                "#0000ff",
                "#000080",
                "#000080",
                "#ffff00",
                "#ff0000",
                "#d0d0d0",
            ),
        )

    def test_config_round_trip_and_missing_key_schema_evolution(self):
        changed = Config(
            default_text_font=FontDefinition(
                "Arial", "Bold Italic", 48, 700, True, True
            ),
            inactive_object_color="#123456",
        )
        self.assertEqual(Config.from_dict(changed.to_dict()), changed)
        old = Config.from_dict({"show_toolbar_text": False})
        self.assertFalse(old.show_toolbar_text)
        self.assertEqual(old.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(
            old.inactive_object_color, Config.DEFAULT_INACTIVE_OBJECT_COLOR
        )


class ElevationCalloutConfigTests(unittest.TestCase):
    def test_defaults_preserve_html_behavior_and_leave_pdf_unchanged(self):
        config = Config()
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)
        self.assertTrue(config.elevation_callout_include_condition)
        self.assertTrue(config.elevation_callout_include_top)
        self.assertTrue(config.elevation_callout_include_bottom)
        self.assertTrue(config.elevation_callout_include_cubic_yards)
        self.assertEqual(config.html_elevation_callout_color, "#ff0000")
        self.assertEqual(config.pdf_elevation_callout_color, "#ff0000")

    def test_legacy_config_uses_canonical_callout_defaults(self):
        config = Config.from_dict({"show_toolbar_text": False})
        self.assertTrue(config.html_elevation_callouts_enabled)
        self.assertFalse(config.pdf_elevation_callouts_enabled)
        self.assertTrue(config.elevation_callout_settings().has_content)

    def test_independent_callout_settings_round_trip_in_existing_config_payload(self):
        expected = Config(
            html_elevation_callouts_enabled=False,
            pdf_elevation_callouts_enabled=True,
            elevation_callout_include_condition=False,
            elevation_callout_include_top=True,
            elevation_callout_include_bottom=False,
            elevation_callout_include_cubic_yards=True,
            html_elevation_callout_color="#123456",
            pdf_elevation_callout_color="#abcdef",
        )
        loaded = Config.from_dict(expected.to_dict())
        self.assertEqual(loaded, expected)


class PdfAnnotationCaptionSettingsTests(unittest.TestCase):
    def test_missing_caption_configuration_uses_disabled_empty_defaults(self):
        config = Config.from_dict({"show_toolbar_text": False})
        self.assertFalse(config.pdf_annotation_captions_enabled)
        self.assertEqual(
            config.pdf_annotation_caption_ids,
            DEFAULT_ANNOTATION_CAPTION_IDS,
        )

    def test_each_caption_identifier_loads_and_saves_independently(self):
        for caption_id in ANNOTATION_CAPTION_ORDER:
            with self.subTest(caption_id=caption_id.value):
                expected = Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=(caption_id.value,),
                )
                self.assertEqual(Config.from_dict(expected.to_dict()), expected)


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    _overflow_toolbar = component_tests.ToolbarOverflowTests._overflow_toolbar
    _use_extension_menu = component_tests.ToolbarOverflowTests._use_extension_menu

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.json"
        self.repository = JsonConfigRepository(self.path)
        self.model = ConfigAggregate(self.repository)
        self.bus = EventBus()
        self.service = ConfigService(self.model, self.bus)

    def test_invalid_preference_uses_existing_config_validation_contract(self):
        for value in (None, "line_annotation_tool", [False]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                Config.from_dict({"hidden_takeoff_toolbar_items": value})
