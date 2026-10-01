import unittest
from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config


class _Repository:
    config_path = "memory"

    def __init__(self, config=None):
        self.persisted = (config or Config()).to_dict()
        self.saved = []
        self.fail = False

    def load(self):
        return Config.from_dict(deepcopy(self.persisted))

    def save(self, config):
        if self.fail:
            raise OSError("configuration storage unavailable")
        self.persisted = deepcopy(config.to_dict())
        self.saved.append(deepcopy(self.persisted))


class _Events:
    def __init__(self):
        self.events = []

    def publish(self, event_type, **payload):
        self.events.append(event_type(**payload))


def _event(value):
    return AppEvents.APP_CONFIG_UPDATED(setting="options", value=value)


SNAP_PREF_UPDATE = {
    "snap_to_grid_enabled": False,
    "snap_to_grid_threshold_px": 0,
    "snap_to_pdf_lines_enabled": False,
    "snap_to_pdf_lines_threshold_px": 12,
    "snap_to_takeoffs_enabled": False,
    "snap_to_takeoffs_threshold_px": 16,
    "snap_to_right_angle_enabled": False,
    "snap_to_right_angle_threshold_px": 20,
}


class ConfigServicePreferenceTests(unittest.TestCase):
    def test_update_app_options_updates_split_display_modes_and_publishes_changed_payload(
        self,
    ):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(
            {
                "display_modes_synced": False,
                "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
            }
        )
        self.assertEqual(
            changed,
            ["display_modes_synced", "display_mode_3d", "display_mode_2d"],
        )
        self.assertFalse(aggregate.display_modes_synced)
        self.assertEqual(aggregate.display_mode_3d, Config.DISPLAY_MODE_SOLID)
        self.assertEqual(aggregate.display_mode_2d, Config.DISPLAY_MODE_TRANSPARENT)
        self.assertEqual(repo.saved, [aggregate.snapshot().to_dict()])
        self.assertEqual(repo.saved[-1]["display_mode_3d"], Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            repo.saved[-1]["display_mode_2d"], Config.DISPLAY_MODE_TRANSPARENT
        )
        self.assertEqual(
            event_bus.events,
            [
                _event(
                    {
                        "display_modes_synced": False,
                        "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                    }
                )
            ],
        )

    def test_update_app_options_updates_grayscale_and_publishes_changed_payload(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": True})
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertEqual(repo.saved, [aggregate.snapshot().to_dict()])
        self.assertTrue(repo.saved[-1]["grayscale_enabled"])
        self.assertEqual(
            event_bus.events,
            [_event({"grayscale_enabled": True})],
        )

    def test_update_app_options_updates_snap_preferences_and_publishes_payload(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(SNAP_PREF_UPDATE)
        self.assertEqual(changed, list(SNAP_PREF_UPDATE))
        self.assertEqual(repo.saved, [aggregate.snapshot().to_dict()])
        self.assertEqual(
            {key: aggregate.snapshot().to_dict()[key] for key in SNAP_PREF_UPDATE},
            SNAP_PREF_UPDATE,
        )
        self.assertEqual(
            event_bus.events,
            [_event(SNAP_PREF_UPDATE)],
        )

    def test_grayscale_noop_does_not_publish(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": False})
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])
        self.assertEqual(repo.saved, [])

    def test_update_app_options_accepts_main_hotlink_target(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"hotlink_target": "main"})
        self.assertEqual(changed, ["hotlink_target"])
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(repo.saved, [aggregate.snapshot().to_dict()])
        self.assertEqual(
            event_bus.events,
            [_event({"hotlink_target": "main"})],
        )

    def test_update_app_options_does_not_publish_when_nothing_changed(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(
            {"display_mode_3d": aggregate.display_mode_3d}
        )
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])
        self.assertEqual(repo.saved, [])

    def test_invalid_display_mode_uses_config_aggregate_validation_policy(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"display_mode_3d": "BadMode"})
        self.assertEqual(changed, [])
        self.assertEqual(aggregate.display_mode_3d, Config.DEFAULT_DISPLAY_MODE)
        self.assertEqual(event_bus.events, [])
        self.assertEqual(repo.saved, [])

    def test_corrected_option_update_is_persisted_once(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options(
                {
                    "display_mode_3d": "BadMode",
                    "grayscale_enabled": True,
                }
            )
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertEqual(len(repo.saved), 1)
        self.assertTrue(repo.saved[0]["grayscale_enabled"])
        self.assertEqual(event_bus.events, [_event({"grayscale_enabled": True})])

    def test_invalid_snap_threshold_uses_config_aggregate_validation_policy(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        event_bus = _Events()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"snap_to_grid_threshold_px": 101})
        self.assertEqual(changed, [])
        self.assertEqual(
            aggregate.snap_to_grid_threshold_px, Config.DEFAULT_SNAP_THRESHOLD_PX
        )
        self.assertEqual(event_bus.events, [])
        self.assertEqual(repo.saved, [])

    def test_mapping_update_preserves_unmentioned_settings_and_caller_data(self):
        initial = Config(hotlink_target="main", default_auto_zoom_level=75)
        repo = _Repository(initial)
        aggregate = ConfigAggregate(repo)
        events = _Events()
        service = ConfigService(aggregate, events)
        source = {"grayscale_enabled": True}
        self.assertEqual(
            service.update_app_options(MappingProxyType(source)), ["grayscale_enabled"]
        )
        expected = replace(initial, grayscale_enabled=True)
        self.assertEqual(service.get_config_snapshot(), expected)
        self.assertEqual(repo.saved, [expected.to_dict()])
        self.assertEqual(events.events, [_event(source)])
        source["grayscale_enabled"] = False
        self.assertEqual(service.get_config_snapshot(), expected)
        self.assertEqual(events.events, [_event({"grayscale_enabled": True})])

    def test_config_input_and_snapshots_do_not_alias_authoritative_state(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        events = _Events()
        service = ConfigService(aggregate, events)
        original = service.get_config_snapshot()
        draft = replace(original, grayscale_enabled=True)
        self.assertEqual(service.update_app_options(draft), ["grayscale_enabled"])
        snapshot = service.get_config_snapshot()
        draft.grayscale_enabled = False
        snapshot.grayscale_enabled = False
        self.assertEqual(
            service.get_config_snapshot(), replace(original, grayscale_enabled=True)
        )
        self.assertEqual(
            repo.saved, [replace(original, grayscale_enabled=True).to_dict()]
        )
        self.assertEqual(events.events, [_event({"grayscale_enabled": True})])

    def test_invalid_update_type_has_no_model_persistence_or_event_effect(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        events = _Events()
        service = ConfigService(aggregate, events)
        initial = service.get_config_snapshot()
        for invalid in (None, [], "grayscale_enabled", 1):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                TypeError, "Config or mapping"
            ):
                service.update_app_options(invalid)
        self.assertEqual(service.get_config_snapshot(), initial)
        self.assertEqual(repo.saved, [])
        self.assertEqual(events.events, [])

    def test_failed_save_rolls_back_without_event_and_retry_persists_once(self):
        repo = _Repository()
        aggregate = ConfigAggregate(repo)
        events = _Events()
        service = ConfigService(aggregate, events)
        initial = service.get_config_snapshot()
        repo.fail = True
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate", level="ERROR"
        ), self.assertRaisesRegex(OSError, "storage unavailable"):
            service.update_app_options({"grayscale_enabled": True})
        self.assertEqual(service.get_config_snapshot(), initial)
        self.assertEqual(repo.load(), initial)
        self.assertEqual(repo.saved, [])
        self.assertEqual(events.events, [])
        repo.fail = False
        self.assertEqual(
            service.update_app_options({"grayscale_enabled": True}),
            ["grayscale_enabled"],
        )
        expected = replace(initial, grayscale_enabled=True)
        self.assertEqual(repo.load(), expected)
        self.assertEqual(service.get_config_snapshot(), expected)
        self.assertEqual(repo.saved, [expected.to_dict()])
        self.assertEqual(events.events, [_event({"grayscale_enabled": True})])

    def test_event_contains_validated_values_not_raw_update(self):
        repo = _Repository()
        events = _Events()
        service = ConfigService(ConfigAggregate(repo), events)
        self.assertEqual(
            service.update_app_options({"crosshair_color": "  #ABCDEF  "}),
            ["crosshair_color"],
        )
        self.assertEqual(service.get_config_snapshot().crosshair_color, "#abcdef")
        self.assertEqual(events.events, [_event({"crosshair_color": "#abcdef"})])
        self.assertEqual(len(repo.saved), 1)
        self.assertEqual(repo.load().crosshair_color, "#abcdef")
