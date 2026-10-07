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
