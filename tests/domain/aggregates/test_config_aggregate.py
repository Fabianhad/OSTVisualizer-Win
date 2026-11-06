from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
import unittest
from dataclasses import replace
from pathlib import Path
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.font_definition import FontDefinition


class _ConfigRepository:
    config_path = Path("config.json")

    def __init__(self, config):
        self.config = config
        self.saved = []
        self.save_error = None

    def load(self):
        return Config.from_dict(self.config.to_dict())

    def save(self, config):
        if self.save_error is not None:
            raise self.save_error
        self.config = Config.from_dict(config.to_dict())
        self.saved.append(self.config)


class ConfigAggregateValidationTests(unittest.TestCase):
    def test_validation_constants_are_immutable_shared_state(self):
        self.assertIsInstance(ConfigAggregate.VALID_DISPLAY_MODES, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_HOTLINK_TARGETS, frozenset)
        self.assertIsInstance(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES, frozenset)
        self.assertEqual(
            ConfigAggregate.VALID_DISPLAY_MODES, {"Solid", "Original", "Transparent"}
        )
        self.assertEqual(
            ConfigAggregate.VALID_MOUSE_SNAP_ANGLES,
            {0, 1, 2, 3, 4, 5, 10, 15, 30, 45, 90},
        )
        for mode in ("Solid", "Original", "Transparent"):
            with self.subTest(mode=mode):
                repository = _ConfigRepository(
                    Config(display_mode_3d=mode, display_mode_2d=mode)
                )
                aggregate = ConfigAggregate(repository)
                self.assertEqual(aggregate.display_mode_3d, mode)
                self.assertEqual(aggregate.display_mode_2d, mode)
                self.assertEqual(repository.saved, [])


class ConfigAggregateFontColorTests(unittest.TestCase):
    def test_invalid_new_fields_are_corrected_independently(self):
        config = Config(
            default_text_font=FontDefinition("", "Bold", 12, 700, False, False),
            default_area_label_color="blue",
            default_hotlink_color="#ABCDEF",
            show_toolbar_text=False,
        )
        repository = _ConfigRepository(config)
        aggregate = ConfigAggregate(repository)
        snapshot = aggregate.snapshot()
        self.assertEqual(snapshot.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(
            snapshot.default_area_label_color, Config.DEFAULT_AREA_LABEL_COLOR
        )
        self.assertEqual(snapshot.default_hotlink_color, "#abcdef")
        self.assertFalse(snapshot.show_toolbar_text)
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(repository.saved[0], snapshot)
        self.assertEqual(config.default_area_label_color, "blue")
        self.assertEqual(config.default_hotlink_color, "#ABCDEF")


class ConfigAggregateUpdateTests(unittest.TestCase):
    def test_no_change_does_not_save_and_returned_snapshot_is_detached(self):
        repository = _ConfigRepository(Config())
        aggregate = ConfigAggregate(repository)
        draft = aggregate.snapshot()
        self.assertEqual(aggregate.update_options(draft), [])
        draft.show_toolbar_text = not draft.show_toolbar_text
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(repository.saved, [])

    def test_success_saves_exact_changes_and_failure_preserves_previous_config(self):
        repository = _ConfigRepository(Config())
        aggregate = ConfigAggregate(repository)
        expected = replace(aggregate.snapshot(), default_hotlink_color="#123456")
        self.assertEqual(aggregate.update_options(expected), ["default_hotlink_color"])
        self.assertEqual(repository.saved, [expected])
        self.assertEqual(aggregate.snapshot(), expected)
        repository.save_error = OSError("disk unavailable")
        with self.assertRaisesRegex(OSError, "disk unavailable"):
            aggregate.update_options(replace(expected, default_hotlink_color="#654321"))
        self.assertEqual(repository.saved, [expected])
        self.assertEqual(aggregate.snapshot(), expected)


class ConditionElevationExportOptionAggregateTests(unittest.TestCase):
    def test_both_options_survive_validation_and_report_their_own_changes(self):
        for field in (
            "ost_osp_export_drop_condition_elevation",
            "csv_export_drop_condition_elevation",
        ):
            with self.subTest(field=field):
                repository = _ConfigRepository(Config())
                aggregate = ConfigAggregate(repository)
                draft = replace(aggregate.snapshot(), **{field: True})
                self.assertEqual(aggregate.update_options(draft), [field])
                self.assertIs(getattr(aggregate.snapshot(), field), True)
                self.assertIs(getattr(repository.saved[-1], field), True)
                reloaded = ConfigAggregate(repository)
                self.assertIs(getattr(reloaded.snapshot(), field), True)

    def test_saved_options_are_not_reset_by_loading_other_fields(self):
        repository = _ConfigRepository(
            Config(
                ost_osp_export_drop_condition_elevation=True,
                csv_export_drop_condition_elevation=True,
                show_toolbar_text=False,
            )
        )
        snapshot = ConfigAggregate(repository).snapshot()
        self.assertTrue(snapshot.ost_osp_export_drop_condition_elevation)
        self.assertTrue(snapshot.csv_export_drop_condition_elevation)
        self.assertFalse(snapshot.show_toolbar_text)


class AiTakeoffOptionAggregateTests(unittest.TestCase):
    def test_ai_takeoff_option_survives_validation_and_reload(self):
        repository = _ConfigRepository(Config())
        aggregate = ConfigAggregate(repository)
        self.assertFalse(aggregate.snapshot().ai_takeoff_enabled)
        draft = replace(aggregate.snapshot(), ai_takeoff_enabled=True)
        self.assertEqual(aggregate.update_options(draft), ["ai_takeoff_enabled"])
        self.assertIs(aggregate.snapshot().ai_takeoff_enabled, True)
        self.assertIs(repository.saved[-1].ai_takeoff_enabled, True)
        self.assertIs(ConfigAggregate(repository).snapshot().ai_takeoff_enabled, True)


from tests.domain.entities.test_config import custom_config


class _RecordingLogger:
    def __init__(self):
        self.records = []

    def _record(self, level, message, args):
        self.records.append((level, message % args if args else message))

    def error(self, message, *args, **kwargs):
        self._record("error", message, args)

    def warning(self, message, *args, **kwargs):
        self.warning_kwargs = kwargs
        self._record("warning", message, args)

    def exception(self, message, *args, **kwargs):
        self._record("exception", message, args)

    def levels(self):
        return [level for level, _ in self.records]

    def messages(self):
        return [message for _, message in self.records]


class _ScriptedConfigRepository:
    config_path = Path("scripted-config.json")

    def __init__(self, outcome, save_error=None):
        self.outcome = outcome
        self.save_error = save_error
        self.saved = []

    def load(self):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome

    def save(self, config):
        if self.save_error is not None:
            raise self.save_error
        self.saved.append(config)


def _loaded(config, logger=None, **kwargs):
    repository = _ScriptedConfigRepository(config, **kwargs)
    aggregate = ConfigAggregate(repository, logger) if logger else ConfigAggregate(repository)
    return aggregate, repository


class ConfigAggregatePropertyTests(unittest.TestCase):
    PROPERTIES = (
        "display_modes_synced",
        "display_mode_3d",
        "display_mode_2d",
        "grayscale_enabled",
        "roping_selection_method",
        "display_page_index_with_sheet_name",
        "display_sheet_number_with_sheet_name",
        "hotlink_target",
        "show_toolbar_text",
        "disable_high_resolution_images",
        "enable_intelligent_paste",
        "enable_advanced_mouse_controls",
        "default_auto_zoom_level",
        "use_full_window_crosshairs",
        "crosshair_color",
        "crosshair_line_thickness",
        "allow_add_page_from_takeoff_tab",
        "mouse_unpressed_snap_angle",
        "mouse_pressed_snap_angle",
        "snap_to_grid_enabled",
        "snap_to_grid_threshold_px",
        "snap_to_pdf_lines_enabled",
        "snap_to_pdf_lines_threshold_px",
        "snap_to_takeoffs_enabled",
        "snap_to_takeoffs_threshold_px",
        "snap_to_right_angle_enabled",
        "snap_to_right_angle_threshold_px",
        "default_text_font",
        "default_area_label_font",
        "default_dimension_annotation_font",
        "default_style_label_font",
        "default_text_color",
        "default_area_label_color",
        "default_dimension_annotation_color",
        "default_style_label_color",
        "default_highlight_color",
        "default_hotlink_color",
        "inactive_object_color",
    )

    def test_every_property_reports_the_loaded_value_and_a_valid_config_is_not_re_saved(self):
        # display modes cannot differ while synced, so load the unsynced variant.
        custom = custom_config()
        aggregate, repository = _loaded(custom)
        for name in self.PROPERTIES:
            with self.subTest(property=name):
                self.assertEqual(getattr(aggregate, name), getattr(custom, name))
        self.assertEqual(repository.saved, [])
        self.assertEqual(aggregate.snapshot(), custom)

    def test_properties_follow_a_later_update_not_a_stale_copy(self):
        aggregate, _ = _loaded(Config())
        updated = custom_config()
        aggregate.update_options(updated)
        for name in self.PROPERTIES:
            with self.subTest(property=name):
                self.assertEqual(getattr(aggregate, name), getattr(updated, name))

    def test_snapshot_is_a_detached_copy(self):
        aggregate, _ = _loaded(Config())
        first = aggregate.snapshot()
        first.show_toolbar_text = False
        self.assertIsNot(first, aggregate.snapshot())
        self.assertTrue(aggregate.snapshot().show_toolbar_text)


class ConfigAggregateBoundsTests(unittest.TestCase):
    def check(self, field, cases, getter=None):
        for given, expected, changed in cases:
            with self.subTest(field=field, given=given):
                aggregate, repository = _loaded(replace(Config(), **{field: given}))
                self.assertEqual(getattr(aggregate.snapshot(), field), expected)
                self.assertEqual(len(repository.saved), 1 if changed else 0)

    def test_auto_zoom_is_clamped_to_zero_through_1600(self):
        self.assertEqual((ConfigAggregate.MIN_AUTO_ZOOM_LEVEL, ConfigAggregate.MAX_AUTO_ZOOM_LEVEL), (0, 1600))
        self.check(
            "default_auto_zoom_level",
            ((-1, 0, True), (0, 0, False), (1, 1, False), (1599, 1599, False), (1600, 1600, False), (1601, 1600, True), (-500, 0, True), (99999, 1600, True)),
        )

    def test_crosshair_thickness_is_clamped_to_one_through_ten(self):
        self.assertEqual(
            (ConfigAggregate.MIN_CROSSHAIR_LINE_THICKNESS, ConfigAggregate.MAX_CROSSHAIR_LINE_THICKNESS), (1, 10)
        )
        self.check(
            "crosshair_line_thickness",
            ((0, 1, True), (1, 1, False), (2, 2, False), (9, 9, False), (10, 10, False), (11, 10, True), (-3, 1, True), (400, 10, True)),
        )

    def test_each_snap_threshold_accepts_zero_through_100_and_falls_back_to_the_default(self):
        self.assertEqual((ConfigAggregate.MIN_SNAP_THRESHOLD_PX, ConfigAggregate.MAX_SNAP_THRESHOLD_PX), (0, 100))
        for field in (
            "snap_to_grid_threshold_px",
            "snap_to_pdf_lines_threshold_px",
            "snap_to_takeoffs_threshold_px",
            "snap_to_right_angle_threshold_px",
        ):
            self.check(
                field,
                ((-1, 8, True), (0, 0, False), (1, 1, False), (99, 99, False), (100, 100, False), (101, 8, True), (5000, 8, True)),
            )

    def test_snap_thresholds_are_validated_independently_of_each_other(self):
        config = replace(
            Config(),
            snap_to_grid_threshold_px=500,
            snap_to_pdf_lines_threshold_px=12,
            snap_to_takeoffs_threshold_px=-4,
            snap_to_right_angle_threshold_px=100,
        )
        aggregate, repository = _loaded(config)
        snapshot = aggregate.snapshot()
        self.assertEqual(
            (
                snapshot.snap_to_grid_threshold_px,
                snapshot.snap_to_pdf_lines_threshold_px,
                snapshot.snap_to_takeoffs_threshold_px,
                snapshot.snap_to_right_angle_threshold_px,
            ),
            (8, 12, 8, 100),
        )
        self.assertEqual(len(repository.saved), 1)

    def test_snap_angles_must_be_one_of_the_supported_values_otherwise_each_uses_its_own_default(self):
        for angle in sorted(ConfigAggregate.VALID_MOUSE_SNAP_ANGLES):
            with self.subTest(angle=angle):
                aggregate, repository = _loaded(
                    replace(Config(), mouse_unpressed_snap_angle=angle, mouse_pressed_snap_angle=angle)
                )
                self.assertEqual(
                    (aggregate.mouse_unpressed_snap_angle, aggregate.mouse_pressed_snap_angle), (angle, angle)
                )
                self.assertEqual(repository.saved, [])
        for angle in (-1, 6, 7, 20, 44, 91, 180):
            with self.subTest(invalid=angle):
                aggregate, repository = _loaded(
                    replace(Config(), mouse_unpressed_snap_angle=angle, mouse_pressed_snap_angle=angle)
                )
                self.assertEqual(
                    (aggregate.mouse_unpressed_snap_angle, aggregate.mouse_pressed_snap_angle),
                    (Config.DEFAULT_MOUSE_UNPRESSED_SNAP_ANGLE, Config.DEFAULT_MOUSE_PRESSED_SNAP_ANGLE),
                )
                self.assertEqual(len(repository.saved), 1)
        aggregate, repository = _loaded(replace(Config(), mouse_unpressed_snap_angle=44, mouse_pressed_snap_angle=45))
        self.assertEqual((aggregate.mouse_unpressed_snap_angle, aggregate.mouse_pressed_snap_angle), (15, 45))
        logger = _RecordingLogger()
        _loaded(replace(Config(), mouse_unpressed_snap_angle=44, snap_to_takeoffs_threshold_px=700), logger)
        self.assertEqual(
            logger.messages(),
            [
                "Invalid mouse snap angle '44' in config; using default '15'",
                "Invalid snap_to_takeoffs_threshold_px '700' in config; using default '8'",
            ],
        )


class ConfigAggregateChoiceTests(unittest.TestCase):
    def test_display_modes_default_when_invalid_and_each_mode_is_corrected_on_its_own(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(
            replace(Config(), display_modes_synced=False, display_mode_3d="Bogus", display_mode_2d="Solid"), logger
        )
        self.assertEqual((aggregate.display_mode_3d, aggregate.display_mode_2d), ("Original", "Solid"))
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(
            logger.messages(), ["Invalid display_mode_3d 'Bogus' in config; using default 'Original'"]
        )
        logger = _RecordingLogger()
        aggregate, repository = _loaded(
            replace(Config(), display_modes_synced=False, display_mode_3d="Transparent", display_mode_2d=""), logger
        )
        self.assertEqual((aggregate.display_mode_3d, aggregate.display_mode_2d), ("Transparent", "Original"))
        self.assertEqual(logger.messages(), ["Invalid display_mode_2d '' in config; using default 'Original'"])
        self.assertEqual(len(repository.saved), 1)

    def test_synced_modes_follow_the_3d_mode_and_unsynced_modes_stay_independent(self):
        aggregate, repository = _loaded(
            replace(Config(), display_modes_synced=True, display_mode_3d="Solid", display_mode_2d="Transparent")
        )
        self.assertEqual((aggregate.display_mode_3d, aggregate.display_mode_2d), ("Solid", "Solid"))
        self.assertEqual(len(repository.saved), 1)
        aggregate, repository = _loaded(
            replace(Config(), display_modes_synced=False, display_mode_3d="Solid", display_mode_2d="Transparent")
        )
        self.assertEqual((aggregate.display_mode_3d, aggregate.display_mode_2d), ("Solid", "Transparent"))
        self.assertEqual(repository.saved, [])
        aggregate, repository = _loaded(replace(Config(), display_modes_synced=True, display_mode_3d="Solid", display_mode_2d="Solid"))
        self.assertEqual(repository.saved, [])

    def test_the_synced_flag_is_coerced_to_a_boolean(self):
        aggregate, _ = _loaded(replace(Config(), display_modes_synced=1))
        self.assertIs(aggregate.display_modes_synced, True)
        aggregate, _ = _loaded(replace(Config(), display_modes_synced=0, display_mode_3d="Solid", display_mode_2d="Original"))
        self.assertIs(aggregate.display_modes_synced, False)

    def test_roping_and_hotlink_choices_fall_back_to_their_defaults_with_a_warning(self):
        for value in sorted(ConfigAggregate.VALID_ROPING_SELECTION_METHODS):
            aggregate, repository = _loaded(replace(Config(), roping_selection_method=value))
            self.assertEqual(aggregate.roping_selection_method, value)
            self.assertEqual(repository.saved, [])
        for value in sorted(ConfigAggregate.VALID_HOTLINK_TARGETS):
            aggregate, repository = _loaded(replace(Config(), hotlink_target=value))
            self.assertEqual(aggregate.hotlink_target, value)
            self.assertEqual(repository.saved, [])
        logger = _RecordingLogger()
        aggregate, repository = _loaded(replace(Config(), roping_selection_method="Touching", hotlink_target="elsewhere"), logger)
        self.assertEqual((aggregate.roping_selection_method, aggregate.hotlink_target), ("touching", "annotation"))
        self.assertEqual(
            logger.messages(),
            [
                "Invalid roping_selection_method 'Touching' in config; using default 'touching'",
                "Invalid hotlink_target 'elsewhere' in config; using default 'annotation'",
            ],
        )
        self.assertEqual(len(repository.saved), 1)

    def test_valid_choice_sets_are_exactly_the_documented_vocabulary(self):
        self.assertEqual(ConfigAggregate.VALID_ROPING_SELECTION_METHODS, {"touching", "inclusive"})
        self.assertEqual(ConfigAggregate.VALID_HOTLINK_TARGETS, {"annotation", "view", "main"})

    def test_boolean_fields_are_coerced_to_real_booleans(self):
        aggregate, _ = _loaded(
            replace(
                Config(),
                grayscale_enabled=1,
                show_toolbar_text=0,
                snap_to_grid_enabled="",
                ai_takeoff_enabled="yes",
                csv_export_drop_condition_elevation=1,
                pdf_annotation_captions_enabled=1,
            )
        )
        snapshot = aggregate.snapshot()
        self.assertIs(snapshot.grayscale_enabled, True)
        self.assertIs(snapshot.show_toolbar_text, False)
        self.assertIs(snapshot.snap_to_grid_enabled, False)
        self.assertIs(snapshot.ai_takeoff_enabled, True)
        self.assertIs(snapshot.csv_export_drop_condition_elevation, True)
        self.assertIs(snapshot.pdf_annotation_captions_enabled, True)

    def test_caption_ids_keep_only_supported_ones_deduplicated_in_canonical_order(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(
            replace(Config(), pdf_annotation_caption_ids=("slope", "bogus", "area", "area", "label")), logger
        )
        self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ("label", "area", "slope"))
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(
            logger.messages(),
            [
                "Invalid or duplicate PDF annotation caption identifiers in config; "
                "using the supported identifiers in canonical order"
            ],
        )
        aggregate, repository = _loaded(replace(Config(), pdf_annotation_caption_ids=("label", "area")))
        self.assertEqual(repository.saved, [])
        aggregate, _ = _loaded(replace(Config(), pdf_annotation_caption_ids=()))
        self.assertEqual(aggregate.snapshot().pdf_annotation_caption_ids, ())

    def test_hidden_toolbar_items_are_normalized_on_load(self):
        aggregate, _ = _loaded(replace(Config(), hidden_takeoff_toolbar_items=("b", "a")))
        self.assertEqual(aggregate.snapshot().hidden_takeoff_toolbar_items, ("a", "b"))
        logger = _RecordingLogger()
        aggregate, repository = _loaded(
            replace(Config(), show_toolbar_text=False, hidden_takeoff_toolbar_items="text"), logger
        )
        # An unusable value is a load failure: everything resets to defaults and is saved.
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(
            logger.messages(),
            ["hidden_takeoff_toolbar_items must be a list of strings; resetting to defaults"],
        )
        self.assertEqual(repository.saved, [Config()])


class ConfigAggregateCorrectionSaveTests(unittest.TestCase):
    GOOD_FONT = FontDefinition("Arial", "Bold", 12, 700, False, False)

    def test_every_single_correction_is_saved_by_itself_and_leaves_other_fields_alone(self):
        corrections = (
            ("display_mode_3d", "Bogus", "Original"),
            ("display_mode_2d", "Bogus", "Original"),
            ("roping_selection_method", "x", "touching"),
            ("hotlink_target", "x", "annotation"),
            ("default_auto_zoom_level", -5, 0),
            ("default_auto_zoom_level", 5000, 1600),
            ("crosshair_line_thickness", 0, 1),
            ("crosshair_line_thickness", 99, 10),
            ("mouse_unpressed_snap_angle", 7, 15),
            ("mouse_pressed_snap_angle", 7, 0),
            ("snap_to_grid_threshold_px", -1, 8),
            ("pdf_annotation_caption_ids", ("bogus",), ()),
            ("crosshair_color", "red", "#00ff00"),
            ("html_elevation_callout_color", "red", "#ff0000"),
            ("pdf_elevation_callout_color", "red", "#ff0000"),
            ("default_text_color", "red", "#ff0000"),
            ("default_area_label_color", "red", "#0000ff"),
            ("default_dimension_annotation_color", "red", "#000080"),
            ("default_style_label_color", "red", "#000080"),
            ("default_highlight_color", "red", "#ffff00"),
            ("default_hotlink_color", "red", "#ff0000"),
            ("inactive_object_color", "red", "#d0d0d0"),
            ("default_text_font", FontDefinition("", "Bold", 12, 700, False, False), Config.DEFAULT_TEXT_FONT),
            ("default_area_label_font", FontDefinition("", "Bold", 12, 700, False, False), Config.DEFAULT_AREA_LABEL_FONT),
            ("default_dimension_annotation_font", None, Config.DEFAULT_DIMENSION_ANNOTATION_FONT),
            ("default_style_label_font", "Arial", Config.DEFAULT_STYLE_LABEL_FONT),
            ("crosshair_color", "#ABCDEF", "#abcdef"),
            ("default_text_color", "  #abcdef ", "#abcdef"),
            (
                "default_text_font",
                FontDefinition("  Arial ", " Bold ", 12, 700, False, False),
                Config.DEFAULT_TEXT_FONT,
            ),
        )
        for field, bad, expected in corrections:
            with self.subTest(field=field, bad=bad):
                aggregate, repository = _loaded(replace(Config(), **{field: bad}))
                snapshot = aggregate.snapshot()
                self.assertEqual(getattr(snapshot, field), expected)
                self.assertEqual(repository.saved, [snapshot])
                self.assertEqual(
                    replace(snapshot, **{field: getattr(Config(), field)}), Config()
                )

    def test_a_clean_configuration_is_never_rewritten(self):
        for config in (Config(), custom_config()):
            aggregate, repository = _loaded(config)
            self.assertEqual(repository.saved, [])
            self.assertEqual(aggregate.snapshot(), config)

    def test_a_failed_correction_save_is_logged_but_keeps_the_corrected_config(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(
            replace(Config(), default_auto_zoom_level=5000),
            logger,
            save_error=OSError("read-only"),
        )
        self.assertEqual(aggregate.default_auto_zoom_level, 1600)
        self.assertEqual(
            logger.records,
            [
                ("error", "Error saving configuration: read-only"),
                ("warning", "Failed to save corrected config"),
            ],
        )
        self.assertIs(logger.warning_kwargs["exc_info"], True)


class ConfigAggregateColorTests(unittest.TestCase):
    def color(self, value):
        aggregate, repository = _loaded(replace(Config(), default_hotlink_color=value))
        return aggregate.default_hotlink_color, len(repository.saved)

    def test_valid_seven_character_hex_colors_are_kept_lowercased_and_trimmed(self):
        self.assertEqual(self.color("#abcdef"), ("#abcdef", 0))
        self.assertEqual(self.color("#ABCDEF"), ("#abcdef", 1))
        self.assertEqual(self.color("#012345"), ("#012345", 0))
        self.assertEqual(self.color("#6789aB"), ("#6789ab", 1))
        self.assertEqual(self.color("  #123456\t"), ("#123456", 1))

    def test_everything_else_falls_back_to_the_default_and_logs_the_field_and_value(self):
        for value in ("#abcde", "#abcdef0", "abcdef0", "#ggg000", "#12345G", "#XXXXXX", "#g12345", "#1g2345", "#12 456", "", "   ", None, 5, 1.5, ("#123456",)):
            with self.subTest(value=value):
                logger = _RecordingLogger()
                aggregate, repository = _loaded(replace(Config(), default_hotlink_color=value), logger)
                self.assertEqual(aggregate.default_hotlink_color, Config.DEFAULT_HOTLINK_COLOR)
                self.assertEqual(len(repository.saved), 1)
                self.assertEqual(
                    logger.messages(),
                    [f"Invalid default_hotlink_color '{value}' in config; using default '#ff0000'"],
                )

    def test_colors_are_validated_independently(self):
        config = replace(Config(), default_text_color="red", default_area_label_color="#ABCDEF", inactive_object_color="#111111")
        aggregate, _ = _loaded(config)
        self.assertEqual(
            (aggregate.default_text_color, aggregate.default_area_label_color, aggregate.inactive_object_color),
            ("#ff0000", "#abcdef", "#111111"),
        )


class ConfigAggregateFontTests(unittest.TestCase):
    def font(self, **changes):
        values = dict(family="Arial", style_name="Bold", point_size=12, weight=700, italic=False, underline=False)
        values.update(changes)
        return FontDefinition(**values)

    def loaded_font(self, font, logger=None):
        aggregate, repository = _loaded(replace(Config(), default_text_font=font), logger)
        return aggregate.default_text_font, len(repository.saved)

    def test_sizes_weights_and_flags_are_validated_at_their_boundaries(self):
        accepted = (
            self.font(point_size=1),
            self.font(point_size=2),
            self.font(point_size=143),
            self.font(point_size=144),
            self.font(weight=400),
            self.font(weight=700),
            self.font(italic=True, underline=True),
            self.font(family="A", style_name="B"),
        )
        for font in accepted:
            with self.subTest(font=font):
                self.assertEqual(self.loaded_font(font), (font, 0))
        rejected = (
            self.font(point_size=0),
            self.font(point_size=145),
            self.font(point_size=-5),
            self.font(point_size=12.0),
            self.font(point_size=True),
            self.font(point_size="12"),
            self.font(point_size=None),
            self.font(weight=500),
            self.font(weight=401),
            self.font(weight=True),
            self.font(weight=700.0),
            self.font(italic=1),
            self.font(italic=None),
            self.font(underline=1),
            self.font(underline="no"),
            self.font(family=""),
            self.font(family="   "),
            self.font(family=None),
            self.font(family=5),
            self.font(style_name=""),
            self.font(style_name=" "),
            self.font(style_name=None),
            self.font(style_name=5),
            None,
            {"family": "Arial"},
            "Arial",
        )
        for font in rejected:
            with self.subTest(font=font):
                self.assertEqual(self.loaded_font(font), (Config.DEFAULT_TEXT_FONT, 1))

    def test_valid_fonts_have_their_family_and_style_trimmed_and_that_counts_as_a_correction(self):
        font, saved = self.loaded_font(self.font(family="  Segoe UI ", style_name=" Bold Italic\t", italic=True))
        self.assertEqual((font.family, font.style_name, font.italic), ("Segoe UI", "Bold Italic", True))
        self.assertEqual(saved, 1)

    def test_invalid_fonts_are_logged_with_field_name_and_value(self):
        logger = _RecordingLogger()
        aggregate, _ = _loaded(
            replace(Config(), default_style_label_font=self.font(weight=500)), logger
        )
        self.assertEqual(
            logger.messages(),
            [
                "Invalid default_style_label_font 'FontDefinition(family='Arial', "
                "style_name='Bold', point_size=12, weight=500, italic=False, "
                "underline=False)' in config; using canonical default"
            ],
        )
        self.assertEqual(aggregate.default_style_label_font, Config.DEFAULT_STYLE_LABEL_FONT)

    def test_each_font_field_is_validated_separately_and_corrections_accumulate(self):
        config = replace(
            Config(),
            default_text_font=self.font(family=""),
            default_area_label_font=self.font(family="Verdana", point_size=9),
            default_dimension_annotation_font=self.font(point_size=999),
            default_style_label_font=self.font(family=" Mono ", style_name="Regular", weight=400),
        )
        aggregate, repository = _loaded(config)
        self.assertEqual(aggregate.default_text_font, Config.DEFAULT_TEXT_FONT)
        self.assertEqual(aggregate.default_area_label_font, self.font(family="Verdana", point_size=9))
        self.assertEqual(aggregate.default_dimension_annotation_font, Config.DEFAULT_DIMENSION_ANNOTATION_FONT)
        self.assertEqual(
            aggregate.default_style_label_font, self.font(family="Mono", style_name="Regular", weight=400)
        )
        self.assertEqual(len(repository.saved), 1)
        # A later-listed font that is already valid must not hide an earlier correction.
        only_first = replace(Config(), default_text_font=self.font(family=""))
        _, repository = _loaded(only_first)
        self.assertEqual(len(repository.saved), 1)
        only_last = replace(Config(), default_style_label_font=self.font(family=""))
        _, repository = _loaded(only_last)
        self.assertEqual(len(repository.saved), 1)


class ConfigAggregateLoadFailureTests(unittest.TestCase):
    def test_a_missing_file_starts_from_defaults_and_writes_them_without_an_error(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(FileNotFoundError("none"), logger)
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(repository.saved, [Config()])
        self.assertEqual(logger.records, [])

    def test_invalid_stored_data_is_logged_and_replaced_by_saved_defaults(self):
        for error in (ValueError("bad value"), TypeError("bad type")):
            with self.subTest(error=type(error).__name__):
                logger = _RecordingLogger()
                aggregate, repository = _loaded(error, logger)
                self.assertEqual(aggregate.snapshot(), Config())
                self.assertEqual(repository.saved, [Config()])
                self.assertEqual(logger.records, [("error", f"{error}; resetting to defaults")])

    def test_an_unreadable_file_is_logged_and_defaults_are_used_without_overwriting_it(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(OSError("locked"), logger)
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(repository.saved, [])
        self.assertEqual(logger.records, [("error", "Error reading configuration: locked")])

    def test_failing_to_write_the_defaults_is_logged_with_the_path_and_does_not_raise(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(FileNotFoundError("none"), logger, save_error=OSError("read-only"))
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(
            logger.records,
            [("exception", "Failed to save default configuration to scripted-config.json: read-only")],
        )

    def test_without_an_injected_logger_the_module_logger_is_used(self):
        with self.assertLogs("ost_visualizer.domain.aggregates.config_aggregate", level="ERROR") as captured:
            ConfigAggregate(_ScriptedConfigRepository(OSError("locked")))
        self.assertEqual(
            [record.getMessage() for record in captured.records], ["Error reading configuration: locked"]
        )


class ConfigAggregateUpdateDetailTests(unittest.TestCase):
    def test_updates_are_validated_but_corrections_are_reported_as_changes_and_saved_once(self):
        aggregate, repository = _loaded(Config())
        draft = replace(aggregate.snapshot(), default_auto_zoom_level=5000, crosshair_color="#ABCDEF")
        changed = aggregate.update_options(draft)
        self.assertEqual(changed, ["default_auto_zoom_level", "crosshair_color"])
        self.assertEqual(aggregate.default_auto_zoom_level, 1600)
        self.assertEqual(aggregate.crosshair_color, "#abcdef")
        self.assertEqual(len(repository.saved), 1)
        self.assertEqual(repository.saved[0], aggregate.snapshot())

    def test_a_draft_that_validates_to_the_current_config_changes_and_saves_nothing(self):
        aggregate, repository = _loaded(Config())
        draft = replace(aggregate.snapshot(), default_auto_zoom_level=-3)
        self.assertEqual(aggregate.update_options(draft), [])
        self.assertEqual(repository.saved, [])
        self.assertEqual(aggregate.snapshot(), Config())

    def test_changed_keys_are_reported_in_payload_order(self):
        aggregate, _ = _loaded(Config())
        changed = aggregate.update_options(custom_config())
        self.assertEqual(changed, list(custom_config().to_dict()))

    def test_a_failed_save_logs_reraises_and_restores_the_previous_configuration(self):
        logger = _RecordingLogger()
        aggregate, repository = _loaded(Config(), logger)
        repository.save_error = OSError("disk full")
        with self.assertRaises(OSError):
            aggregate.update_options(replace(aggregate.snapshot(), show_toolbar_text=False))
        self.assertEqual(aggregate.snapshot(), Config())
        self.assertEqual(logger.records, [("error", "Error saving configuration: disk full")])
        self.assertEqual(repository.saved, [])

    def test_an_update_is_not_saved_while_an_invalid_value_is_only_corrected_in_memory_first(self):
        aggregate, repository = _loaded(Config())
        aggregate.update_options(replace(aggregate.snapshot(), hotlink_target="elsewhere", show_toolbar_text=False))
        self.assertEqual(aggregate.hotlink_target, "annotation")
        self.assertFalse(aggregate.show_toolbar_text)
        self.assertEqual(len(repository.saved), 1)
