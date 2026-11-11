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
        self.assertFalse(config.show_edges)
        self.assertTrue(config.show_tower_crane)
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


def custom_config():
    """A Config with every persisted field set to a distinct non-default value."""
    return Config(
        display_modes_synced=False,
        display_mode_3d="Solid",
        display_mode_2d="Transparent",
        grayscale_enabled=True,
        show_edges=True,
        show_tower_crane=False,
        roping_selection_method="inclusive",
        display_page_index_with_sheet_name=True,
        display_sheet_number_with_sheet_name=True,
        hotlink_target="main",
        show_toolbar_text=False,
        hidden_takeoff_toolbar_items=("a_tool", "b_tool"),
        disable_high_resolution_images=True,
        enable_intelligent_paste=False,
        enable_advanced_mouse_controls=False,
        default_auto_zoom_level=250,
        use_full_window_crosshairs=True,
        crosshair_color="#112233",
        crosshair_line_thickness=4,
        allow_add_page_from_takeoff_tab=True,
        mouse_unpressed_snap_angle=45,
        mouse_pressed_snap_angle=10,
        snap_to_grid_enabled=False,
        snap_to_grid_threshold_px=11,
        snap_to_pdf_lines_enabled=False,
        snap_to_pdf_lines_threshold_px=12,
        snap_to_takeoffs_enabled=False,
        snap_to_takeoffs_threshold_px=13,
        snap_to_right_angle_enabled=False,
        snap_to_right_angle_threshold_px=14,
        pdf_annotation_captions_enabled=True,
        pdf_annotation_caption_ids=("area", "slope"),
        html_elevation_callouts_enabled=False,
        pdf_elevation_callouts_enabled=True,
        elevation_callout_include_condition=False,
        elevation_callout_include_top=False,
        elevation_callout_include_bottom=False,
        elevation_callout_include_cubic_yards=False,
        html_elevation_callout_color="#010203",
        pdf_elevation_callout_color="#040506",
        ost_osp_export_drop_condition_elevation=True,
        csv_export_drop_condition_elevation=True,
        ai_takeoff_enabled=True,
        default_text_font=FontDefinition("Calibri", "Italic", 14, 400, True, False),
        default_area_label_font=FontDefinition("Verdana", "Bold", 9, 700, False, True),
        default_dimension_annotation_font=FontDefinition(
            "Tahoma", "Regular", 20, 400, False, False
        ),
        default_style_label_font=FontDefinition(
            "Consolas", "Bold Italic", 8, 700, True, True
        ),
        default_text_color="#0a0b0c",
        default_area_label_color="#0d0e0f",
        default_dimension_annotation_color="#101112",
        default_style_label_color="#131415",
        default_highlight_color="#161718",
        default_hotlink_color="#191a1b",
        inactive_object_color="#1c1d1e",
    )


class ConfigConstantTests(unittest.TestCase):
    def test_class_constants_are_the_persisted_vocabulary_and_defaults(self):
        self.assertEqual(
            (
                Config.DISPLAY_MODE_SOLID,
                Config.DISPLAY_MODE_ORIGINAL,
                Config.DISPLAY_MODE_TRANSPARENT,
            ),
            ("Solid", "Original", "Transparent"),
        )
        self.assertEqual(
            (Config.ROPING_SELECTION_TOUCHING, Config.ROPING_SELECTION_INCLUSIVE),
            ("touching", "inclusive"),
        )
        self.assertEqual(
            (
                Config.HOTLINK_TARGET_ANNOTATION,
                Config.HOTLINK_TARGET_VIEW,
                Config.HOTLINK_TARGET_MAIN,
            ),
            ("annotation", "view", "main"),
        )
        self.assertEqual(Config.DEFAULT_DISPLAY_MODE, "Original")
        self.assertEqual(Config.DEFAULT_ROPING_SELECTION_METHOD, "touching")
        self.assertEqual(Config.DEFAULT_HOTLINK_TARGET, "annotation")
        self.assertEqual(Config.DEFAULT_AUTO_ZOOM_LEVEL, 0)
        self.assertEqual(Config.DEFAULT_CROSSHAIR_COLOR, "#00ff00")
        self.assertEqual(Config.DEFAULT_CROSSHAIR_LINE_THICKNESS, 1)
        self.assertEqual(Config.DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE, 15)
        self.assertEqual(Config.DEFAULT_MOUSE_PRESSED_SNAP_ANGLE, 0)
        self.assertEqual(Config.DEFAULT_SNAP_THRESHOLD_PX, 8)
        self.assertEqual(Config.DEFAULT_ELEVATION_CALLOUT_COLOR, "#ff0000")

    def test_font_defaults_match_the_original_ost_labels(self):
        self.assertEqual(
            Config.DEFAULT_TEXT_FONT,
            FontDefinition("Arial", "Bold", 12, 700, False, False),
        )
        self.assertEqual(
            Config.DEFAULT_AREA_LABEL_FONT,
            FontDefinition("Arial", "Bold", 10, 700, False, False),
        )
        self.assertEqual(
            Config.DEFAULT_DIMENSION_ANNOTATION_FONT,
            FontDefinition("Arial", "Bold", 12, 700, False, False),
        )
        self.assertEqual(
            Config.DEFAULT_STYLE_LABEL_FONT,
            FontDefinition("Arial", "Bold", 12, 700, False, False),
        )

    def test_defaults_that_are_not_pinned_elsewhere(self):
        config = Config()
        self.assertEqual(config.hidden_takeoff_toolbar_items, ())
        self.assertIs(config.display_page_index_with_sheet_name, False)
        self.assertIs(config.display_sheet_number_with_sheet_name, False)
        self.assertEqual(config.roping_selection_method, "touching")
        self.assertEqual(config.hotlink_target, "annotation")
        self.assertIs(config.ost_osp_export_drop_condition_elevation, False)
        self.assertIs(config.csv_export_drop_condition_elevation, False)
        self.assertIs(config.ai_takeoff_enabled, False)


class ConfigFullRoundTripTests(unittest.TestCase):
    def test_every_persisted_field_round_trips_individually_from_a_non_default_value(
        self,
    ):
        custom = custom_config()
        defaults = Config()
        from dataclasses import fields as dataclass_fields

        for field in dataclass_fields(Config):
            self.assertNotEqual(
                getattr(custom, field.name), getattr(defaults, field.name), field.name
            )
        payload = custom.to_dict()
        self.assertEqual(
            {field.name for field in dataclass_fields(Config)}, set(payload)
        )
        self.assertEqual(Config.from_dict(payload), custom)
        for field in dataclass_fields(Config):
            with self.subTest(field=field.name):
                partial = Config.from_dict({field.name: payload[field.name]})
                self.assertEqual(
                    getattr(partial, field.name), getattr(custom, field.name)
                )
                for other in dataclass_fields(Config):
                    if other.name != field.name:
                        self.assertEqual(
                            getattr(partial, other.name),
                            getattr(defaults, other.name),
                            other.name,
                        )

    def test_payload_uses_plain_json_types(self):
        import json

        payload = custom_config().to_dict()
        self.assertEqual(json.loads(json.dumps(payload)), payload)
        self.assertEqual(payload["hidden_takeoff_toolbar_items"], ["a_tool", "b_tool"])
        self.assertEqual(payload["pdf_annotation_caption_ids"], ["area", "slope"])
        self.assertEqual(
            payload["default_text_font"],
            {
                "family": "Calibri",
                "style_name": "Italic",
                "point_size": 14,
                "weight": 400,
                "italic": True,
                "underline": False,
            },
        )

    def test_empty_or_missing_payload_gives_defaults_without_sharing_state(self):
        for data in (None, {}, []):
            self.assertEqual(Config.from_dict(data), Config())
        first = Config.from_dict({})
        second = Config.from_dict({})
        self.assertIsNot(first, second)

    def test_every_boolean_field_rejects_non_boolean_values_naming_the_key(self):
        from dataclasses import fields as dataclass_fields

        bool_fields = [
            f.name
            for f in dataclass_fields(Config)
            if isinstance(getattr(Config(), f.name), bool)
        ]
        self.assertEqual(len(bool_fields), 26)
        for name in bool_fields:
            for value in ("true", 1, 0, None, "false"):
                with self.subTest(field=name, value=value):
                    with self.assertRaises(TypeError) as raised:
                        Config.from_dict({name: value})
                    self.assertEqual(str(raised.exception), f"{name} must be a boolean")

    def test_text_and_number_fields_are_coerced_to_their_declared_types(self):
        config = Config.from_dict(
            {
                "display_mode_3d": 5,
                "display_mode_2d": None,
                "roping_selection_method": 7,
                "hotlink_target": 8,
                "crosshair_color": 9,
                "html_elevation_callout_color": 10,
                "pdf_elevation_callout_color": 11,
                "default_auto_zoom_level": "250",
                "crosshair_line_thickness": 3.9,
                "mouse_unpressed_snap_angle": "45",
                "mouse_pressed_snap_angle": 10.2,
                "snap_to_grid_threshold_px": "9",
                "snap_to_pdf_lines_threshold_px": 9.7,
                "snap_to_takeoffs_threshold_px": "10",
                "snap_to_right_angle_threshold_px": 11.1,
            }
        )
        self.assertEqual(
            (
                config.display_mode_3d,
                config.display_mode_2d,
                config.roping_selection_method,
                config.hotlink_target,
            ),
            ("5", "None", "7", "8"),
        )
        self.assertEqual(
            (
                config.crosshair_color,
                config.html_elevation_callout_color,
                config.pdf_elevation_callout_color,
            ),
            ("9", "10", "11"),
        )
        self.assertEqual(
            (
                config.default_auto_zoom_level,
                config.crosshair_line_thickness,
                config.mouse_unpressed_snap_angle,
                config.mouse_pressed_snap_angle,
                config.snap_to_grid_threshold_px,
                config.snap_to_pdf_lines_threshold_px,
                config.snap_to_takeoffs_threshold_px,
                config.snap_to_right_angle_threshold_px,
            ),
            (250, 3, 45, 10, 9, 9, 10, 11),
        )
        for value in ("x", None, [1]):
            with self.assertRaises((TypeError, ValueError)):
                Config.from_dict({"default_auto_zoom_level": value})

    def test_default_color_fields_are_stored_without_coercion_for_the_aggregate_to_validate(
        self,
    ):
        config = Config.from_dict(
            {
                "default_text_color": "blue",
                "default_area_label_color": 3,
                "default_dimension_annotation_color": None,
                "default_style_label_color": " #ABC ",
                "default_highlight_color": "#FFFF00",
                "default_hotlink_color": "x",
                "inactive_object_color": "",
            }
        )
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
            ("blue", 3, None, " #ABC ", "#FFFF00", "x", ""),
        )

    def test_hidden_toolbar_items_are_trimmed_deduplicated_sorted_and_blank_free(self):
        self.assertEqual(
            Config.normalize_hidden_toolbar_items([" b ", "a", "b", "", "  ", "a "]),
            ("a", "b"),
        )
        self.assertEqual(Config.normalize_hidden_toolbar_items(("z", "y")), ("y", "z"))
        self.assertEqual(Config.normalize_hidden_toolbar_items([]), ())
        for bad in (None, "text", {"a"}, [1], ["a", None], 5):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError) as raised:
                    Config.normalize_hidden_toolbar_items(bad)
                self.assertEqual(
                    str(raised.exception),
                    "hidden_takeoff_toolbar_items must be a list of strings",
                )
        loaded = Config.from_dict({"hidden_takeoff_toolbar_items": [" b", "a", "b"]})
        self.assertEqual(loaded.hidden_takeoff_toolbar_items, ("a", "b"))

    def test_caption_ids_must_be_a_list_and_are_kept_as_text_in_order(self):
        loaded = Config.from_dict(
            {"pdf_annotation_caption_ids": ["slope", 3, "area", "area"]}
        )
        self.assertEqual(
            loaded.pdf_annotation_caption_ids, ("slope", "3", "area", "area")
        )
        self.assertEqual(
            Config.from_dict(
                {"pdf_annotation_caption_ids": ("area",)}
            ).pdf_annotation_caption_ids,
            ("area",),
        )
        for bad in ("area", None, 5, {"area"}):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError) as raised:
                    Config.from_dict({"pdf_annotation_caption_ids": bad})
                self.assertEqual(
                    str(raised.exception), "pdf_annotation_caption_ids must be a list"
                )

    def test_font_payloads_that_are_not_objects_become_the_invalid_empty_font(self):
        config = Config.from_dict(
            {"default_text_font": None, "default_style_label_font": "Arial"}
        )
        empty = FontDefinition("", "", 0, 0, False, False)
        self.assertEqual(config.default_text_font, empty)
        self.assertEqual(config.default_style_label_font, empty)
        self.assertEqual(config.default_area_label_font, Config.DEFAULT_AREA_LABEL_FONT)

    def test_font_definition_round_trips_and_keeps_wrong_typed_members_for_validation(
        self,
    ):
        font = FontDefinition("Calibri", "Italic", 14, 400, True, False)
        self.assertEqual(FontDefinition.from_dict(font.to_dict()), font)
        loose = FontDefinition.from_dict({"family": 5, "point_size": "x"})
        self.assertEqual(
            (loose.family, loose.style_name, loose.point_size), (5, None, "x")
        )

    def test_elevation_callout_settings_view_follows_the_include_flags(self):
        settings = custom_config().elevation_callout_settings()
        self.assertEqual(
            (
                settings.include_condition,
                settings.include_top,
                settings.include_bottom,
                settings.include_cubic_yards,
            ),
            (False, False, False, False),
        )
        self.assertFalse(settings.has_content)
        for flag in (
            "elevation_callout_include_condition",
            "elevation_callout_include_top",
            "elevation_callout_include_bottom",
            "elevation_callout_include_cubic_yards",
        ):
            only = Config(
                **{
                    "elevation_callout_include_condition": False,
                    "elevation_callout_include_top": False,
                    "elevation_callout_include_bottom": False,
                    "elevation_callout_include_cubic_yards": False,
                    flag: True,
                }
            ).elevation_callout_settings()
            with self.subTest(flag=flag):
                self.assertTrue(only.has_content)
                self.assertEqual(
                    sum(
                        [
                            only.include_condition,
                            only.include_top,
                            only.include_bottom,
                            only.include_cubic_yards,
                        ]
                    ),
                    1,
                )
