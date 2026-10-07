from ost_visualizer.domain.entities.annotation_caption import (
    ANNOTATION_CAPTION_ORDER,
    DEFAULT_ANNOTATION_CAPTION_IDS,
)
import unittest
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition


class ConfigValidationTests(unittest.TestCase):
    def test_config_rejects_truthy_string_for_boolean_field(self):
        with self.assertRaisesRegex(TypeError, "show_toolbar_text"):
            Config.from_dict({"show_toolbar_text": "false"})


class ConfigPreferenceTests(unittest.TestCase):
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
        expected_ids = (
            "label",
            "length",
            "area",
            "volume",
            "depth",
            "wall_area",
            "width",
            "height",
            "slope",
        )
        self.assertEqual(
            tuple(item.value for item in ANNOTATION_CAPTION_ORDER), expected_ids
        )
        for caption_id in expected_ids:
            with self.subTest(caption_id=caption_id):
                expected = Config(
                    pdf_annotation_captions_enabled=True,
                    pdf_annotation_caption_ids=(caption_id,),
                )
                self.assertEqual(Config.from_dict(expected.to_dict()), expected)


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    def test_invalid_preference_uses_existing_config_validation_contract(self):
        for value in (None, "line_annotation_tool", [False]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                Config.from_dict({"hidden_takeoff_toolbar_items": value})


class ConditionElevationExportOptionTests(unittest.TestCase):
    FIELDS = (
        "ost_osp_export_drop_condition_elevation",
        "csv_export_drop_condition_elevation",
    )

    def test_both_options_default_off_and_legacy_payloads_keep_them_off(self):
        config = Config()
        legacy = Config.from_dict({"show_toolbar_text": False})
        for field in self.FIELDS:
            with self.subTest(field=field):
                self.assertIs(getattr(config, field), False)
                self.assertIs(getattr(legacy, field), False)
                self.assertIs(config.to_dict()[field], False)

    def test_each_option_round_trips_independently(self):
        for field in self.FIELDS:
            with self.subTest(field=field):
                changed = Config(**{field: True})
                payload = changed.to_dict()
                self.assertIs(payload[field], True)
                for other in self.FIELDS:
                    if other != field:
                        self.assertIs(payload[other], False)
                self.assertEqual(Config.from_dict(payload), changed)

    def test_non_boolean_values_are_rejected_with_the_key_name(self):
        for field in self.FIELDS:
            for value in ("true", 1, None):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(TypeError, field):
                        Config.from_dict({field: value})


class AiTakeoffOptionTests(unittest.TestCase):
    def test_ai_takeoff_defaults_off_and_legacy_payloads_keep_it_off(self):
        self.assertIs(Config().ai_takeoff_enabled, False)
        self.assertIs(
            Config.from_dict({"show_toolbar_text": False}).ai_takeoff_enabled, False
        )
        self.assertIs(Config().to_dict()["ai_takeoff_enabled"], False)

    def test_ai_takeoff_round_trips_and_rejects_non_boolean_values(self):
        enabled = Config(ai_takeoff_enabled=True)
        self.assertIs(enabled.to_dict()["ai_takeoff_enabled"], True)
        self.assertEqual(Config.from_dict(enabled.to_dict()), enabled)
        for value in ("true", 1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "ai_takeoff_enabled"):
                    Config.from_dict({"ai_takeoff_enabled": value})
