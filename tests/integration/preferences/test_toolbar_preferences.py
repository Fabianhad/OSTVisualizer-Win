import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import delete, isValid
import tests.presentation.components.test_toolbar_overflow as component_tests
from tests.presentation.components.toolbar_visibility_support import (
    register_test_fonts as _toolbar_visibility_support_register_test_fonts,
)


class TakeoffToolbarPreferencesTests(unittest.TestCase):
    _overflow_toolbar = component_tests.ToolbarOverflowTests._overflow_toolbar
    _use_extension_menu = component_tests.ToolbarOverflowTests._use_extension_menu

    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        _toolbar_visibility_support_register_test_fonts()

    def setUp(self):
        # Exceptions raised inside Qt slots are reported through sys.excepthook and
        # would otherwise be swallowed; fail the test if any occur.
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "config.json"
        self.repository = JsonConfigRepository(self.path)
        self.model = ConfigAggregate(self.repository)
        self.bus = EventBus()
        self.service = ConfigService(self.model, self.bus)

    def stored(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def reloaded(self):
        return ConfigAggregate(JsonConfigRepository(self.path)).snapshot()

    def dialog(self):
        dialog = OptionsDialog(
            self.model.snapshot(),
            apply_callback=self.service.update_app_options,
            reset_callback=lambda: (
                self.service.update_app_options(Config()),
                self.model.snapshot(),
            )[1],
        )
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        return dialog

    def test_normalization_missing_and_unknown_keys_round_trip(self):
        self.assertEqual(Config.from_dict({}).hidden_takeoff_toolbar_items, ())
        self.service.update_app_options(
            {
                "hidden_takeoff_toolbar_items": [
                    "future_tool",
                    "",
                    " line_annotation_tool ",
                    "future_tool",
                ]
            }
        )
        expected = ("future_tool", "line_annotation_tool")
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, expected)
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            expected,
        )
        self.assertEqual(
            json.loads(self.path.read_text())["hidden_takeoff_toolbar_items"],
            list(expected),
        )
        dialog = self.dialog()
        self.assertTrue(
            dialog._takeoff_toolbar_tab.checks["arrow_annotation_tool"].isChecked()
        )
        dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].setChecked(True)
        dialog.accept()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items, ("future_tool",)
        )

    def test_apply_ok_cancel_and_restore_defaults_use_one_config_write(self):
        changes = []
        self.bus.subscribe(
            AppEvents.APP_CONFIG_UPDATED, lambda **event: changes.append(event)
        )
        dialog = self.dialog()
        tab = dialog._takeoff_toolbar_tab
        tab.checks["line_annotation_tool"].setChecked(False)
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        dialog._apply_button.click()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        self.assertEqual(
            self.stored()["hidden_takeoff_toolbar_items"], ["line_annotation_tool"]
        )
        tab.checks["arrow_annotation_tool"].setChecked(False)
        dialog.reject()
        self.assertEqual(len(changes), 1)
        restored = self.dialog()
        self.assertFalse(
            restored._takeoff_toolbar_tab.checks["line_annotation_tool"].isChecked()
        )
        restored._takeoff_toolbar_tab.restore_button.click()
        self.assertEqual(
            self.model.snapshot().hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        restored.accept()
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        self.assertEqual(len(changes), 2)
        self.assertEqual(self.stored()["hidden_takeoff_toolbar_items"], [])
        self.assertEqual(self.reloaded().hidden_takeoff_toolbar_items, ())

    def test_scoped_restore_clears_unknown_entries_without_resetting_other_preferences(
        self,
    ):
        self.service.update_app_options(
            {
                "show_toolbar_text": False,
                "hidden_takeoff_toolbar_items": ["obsolete", "line_annotation_tool"],
            }
        )
        dialog = self.dialog()
        dialog._takeoff_toolbar_tab.restore_button.click()
        dialog.accept()
        self.assertFalse(self.model.snapshot().show_toolbar_text)
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        stored = self.stored()
        self.assertIs(stored["show_toolbar_text"], False)
        self.assertEqual(stored["hidden_takeoff_toolbar_items"], [])
        self.assertFalse(self.reloaded().show_toolbar_text)

    def test_reset_all_uses_existing_reset_lifecycle(self):
        self.service.update_app_options(
            {"hidden_takeoff_toolbar_items": ["line_annotation_tool"]}
        )
        dialog = self.dialog()
        checks = dialog._takeoff_toolbar_tab.checks
        self.assertIn("line_annotation_tool", checks)
        self.assertFalse(checks["line_annotation_tool"].isChecked())
        with patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            dialog._reset_all_button.click()
        self.assertEqual(self.model.snapshot().hidden_takeoff_toolbar_items, ())
        self.assertTrue(checks["line_annotation_tool"].isChecked())
        self.assertTrue(all(check.isChecked() for check in checks.values()))
        self.assertEqual(self.stored()["hidden_takeoff_toolbar_items"], [])

    def test_failed_apply_preserves_saved_state_and_retry_persists_and_publishes(self):
        original = self.model.snapshot()
        saved = self.path.read_bytes()
        events = []
        self.bus.subscribe(
            AppEvents.APP_CONFIG_UPDATED, lambda **event: events.append(event)
        )
        dialog = self.dialog()
        dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].setChecked(False)
        with patch.object(
            self.repository, "save", side_effect=OSError("disk unavailable")
        ), patch(
            "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
        ) as warning:
            dialog._apply_button.click()
        warning.assert_called_once()
        self.assertTrue(dialog._apply_button.isEnabled())
        self.assertEqual(events, [])
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(self.model.snapshot(), original)
        dialog._apply_button.click()
        self.assertFalse(dialog._apply_button.isEnabled())
        self.assertEqual(len(events), 1)
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            ("line_annotation_tool",),
        )
        dialog.accept()
        self.assertEqual(len(events), 1)

    def test_failed_reset_all_preserves_hidden_settings_until_retry(self):
        self.service.update_app_options(
            {"hidden_takeoff_toolbar_items": ["line_annotation_tool"]}
        )
        original = self.model.snapshot()
        saved = self.path.read_bytes()
        dialog = self.dialog()
        with patch(
            "ost_visualizer.presentation.dialogs.options.dialog.confirm",
            return_value=True,
        ):
            with patch.object(
                self.repository, "save", side_effect=OSError("disk unavailable")
            ), patch(
                "ost_visualizer.presentation.dialogs.options.dialog.show_warning"
            ) as warning:
                dialog._reset_all_button.click()
            warning.assert_called_once()
            self.assertEqual(self.model.snapshot(), original)
            self.assertEqual(self.path.read_bytes(), saved)
            self.assertFalse(
                dialog._takeoff_toolbar_tab.checks["line_annotation_tool"].isChecked()
            )
            dialog._reset_all_button.click()
        self.assertEqual(
            ConfigAggregate(JsonConfigRepository(self.path))
            .snapshot()
            .hidden_takeoff_toolbar_items,
            (),
        )
