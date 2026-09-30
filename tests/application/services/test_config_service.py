import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.snap_preferences_dto import SnapPreferencesDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    FakeConfigRepository as _preferences_support_FakeConfigRepository,
    FakeEventBus as _preferences_support_FakeEventBus,
    SNAP_PREF_CHANGED_KEYS as _preferences_support_SNAP_PREF_CHANGED_KEYS,
    SNAP_PREF_UPDATE as _preferences_support_SNAP_PREF_UPDATE,
    _app as _preferences_support__app,
    _app_config_event as _preferences_support__app_config_event,
    _assert_snap_pref_update_applied as _preferences_support__assert_snap_pref_update_applied,
)


class ConfigServicePreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_update_app_options_updates_split_display_modes_and_publishes_changed_payload(
        self,
    ):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
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
        self.assertEqual(repo.saved[-1]["display_mode_3d"], Config.DISPLAY_MODE_SOLID)
        self.assertEqual(
            repo.saved[-1]["display_mode_2d"], Config.DISPLAY_MODE_TRANSPARENT
        )
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    {
                        "display_modes_synced": False,
                        "display_mode_3d": Config.DISPLAY_MODE_SOLID,
                        "display_mode_2d": Config.DISPLAY_MODE_TRANSPARENT,
                    }
                )
            ],
        )

    def test_update_app_options_updates_grayscale_and_publishes_changed_payload(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": True})
        self.assertEqual(changed, ["grayscale_enabled"])
        self.assertTrue(aggregate.grayscale_enabled)
        self.assertTrue(repo.saved[-1]["grayscale_enabled"])
        self.assertEqual(
            event_bus.events,
            [_preferences_support__app_config_event({"grayscale_enabled": True})],
        )

    def test_update_app_options_updates_snap_preferences_and_publishes_payload(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(_preferences_support_SNAP_PREF_UPDATE)
        self.assertEqual(changed, _preferences_support_SNAP_PREF_CHANGED_KEYS)
        _preferences_support__assert_snap_pref_update_applied(self, aggregate)
        self.assertEqual(
            event_bus.events,
            [
                _preferences_support__app_config_event(
                    _preferences_support_SNAP_PREF_UPDATE
                )
            ],
        )

    def test_grayscale_noop_does_not_publish(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"grayscale_enabled": False})
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_update_app_options_accepts_main_hotlink_target(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options({"hotlink_target": "main"})
        self.assertEqual(changed, ["hotlink_target"])
        self.assertEqual(aggregate.hotlink_target, "main")
        self.assertEqual(
            event_bus.events,
            [_preferences_support__app_config_event({"hotlink_target": "main"})],
        )

    def test_update_app_options_does_not_publish_when_nothing_changed(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        changed = service.update_app_options(
            {"display_mode_3d": aggregate.display_mode_3d}
        )
        self.assertEqual(changed, [])
        self.assertEqual(event_bus.events, [])

    def test_invalid_display_mode_uses_config_aggregate_validation_policy(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
        service = ConfigService(aggregate, event_bus)
        with self.assertLogs(
            "ost_visualizer.domain.aggregates.config_aggregate",
            level="WARNING",
        ):
            changed = service.update_app_options({"display_mode_3d": "BadMode"})
        self.assertEqual(changed, [])
        self.assertEqual(aggregate.display_mode_3d, Config.DEFAULT_DISPLAY_MODE)
        self.assertEqual(event_bus.events, [])

    def test_corrected_option_update_is_persisted_once(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
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

    def test_invalid_snap_threshold_uses_config_aggregate_validation_policy(self):
        repo = _preferences_support_FakeConfigRepository()
        aggregate = ConfigAggregate(repo)
        event_bus = _preferences_support_FakeEventBus()
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
