import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui
from ost_visualizer.application.services.config_service import ConfigService
from ost_visualizer.domain.aggregates.config_aggregate import ConfigAggregate
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.infrastructure.persistence.repositories.json_config_repository import (
    JsonConfigRepository,
)
from ost_visualizer.presentation.dialogs.options.dialog import OptionsDialog
from shiboken6 import delete, isValid
from tests.presentation.dialogs.options.preference_support import (
    FakeConfigRepository,
    FakeEventBus,
    _app,
    _app_config_event,
    _apply_button,
)

OST_KEY = "ost_osp_export_drop_condition_elevation"
CSV_KEY = "csv_export_drop_condition_elevation"
CONFIRM = "ost_visualizer.presentation.dialogs.options.dialog.confirm"


class ConditionElevationExportOptionPersistenceTests(unittest.TestCase):
    def test_both_options_persist_through_the_json_repository_independently(self):
        mirrored = (
            Config(**{OST_KEY: True, CSV_KEY: False}),
            Config(**{OST_KEY: False, CSV_KEY: True}),
            Config(**{OST_KEY: True, CSV_KEY: True}),
            Config(),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            repository = JsonConfigRepository(config_path=path)
            for index, expected in enumerate(mirrored):
                with self.subTest(index=index):
                    repository.save(expected)
                    on_disk = json.loads(path.read_text(encoding="utf-8"))
                    self.assertIs(on_disk[OST_KEY], getattr(expected, OST_KEY))
                    self.assertIs(on_disk[CSV_KEY], getattr(expected, CSV_KEY))
                    reloaded = JsonConfigRepository(config_path=path).load()
                    self.assertEqual(reloaded, expected)
                    aggregate = ConfigAggregate(JsonConfigRepository(config_path=path))
                    self.assertEqual(aggregate.snapshot(), expected)

    def test_a_config_file_from_before_the_options_loads_with_both_off(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"show_toolbar_text": False}), encoding="utf-8")
            snapshot = ConfigAggregate(
                JsonConfigRepository(config_path=path)
            ).snapshot()
        self.assertIs(getattr(snapshot, OST_KEY), False)
        self.assertIs(getattr(snapshot, CSV_KEY), False)
        self.assertFalse(snapshot.show_toolbar_text)

    def test_a_non_boolean_value_resets_the_file_to_defaults_with_both_off(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({OST_KEY: "yes"}), encoding="utf-8")
            snapshot = ConfigAggregate(
                JsonConfigRepository(config_path=path)
            ).snapshot()
        self.assertEqual(snapshot, Config())


class ConditionElevationExportOptionDialogWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def setUp(self):
        errors = []
        hook = patch("sys.excepthook", side_effect=lambda *error: errors.append(error))
        hook.start()
        self.addCleanup(hook.stop)
        self.addCleanup(lambda: self.assertEqual(errors, []))
        self.repository = FakeConfigRepository()
        self.aggregate = ConfigAggregate(self.repository)
        self.event_bus = FakeEventBus()
        self.service = ConfigService(self.aggregate, self.event_bus)

    def tearDown(self):
        self.app.processEvents()

    def open_dialog(self):
        dialog = OptionsDialog(
            self.service.get_config_snapshot(),
            apply_callback=self.service.update_app_options,
        )
        self.addCleanup(lambda: delete(dialog) if isValid(dialog) else None)
        self.addCleanup(dialog.close)
        return dialog

    def test_apply_after_a_confirmed_warning_saves_publishes_and_survives_reopen(self):
        dialog = self.open_dialog()
        with patch(CONFIRM, return_value=True):
            dialog._ost_osp_drop_elevation_check.click()
        _apply_button(dialog).click()
        self.assertEqual(len(self.repository.saved), 1)
        self.assertIs(self.repository.saved[0][OST_KEY], True)
        self.assertIs(self.repository.saved[0][CSV_KEY], False)
        self.assertEqual(self.event_bus.events, [_app_config_event({OST_KEY: True})])
        with patch(CONFIRM) as confirm:
            reopened = self.open_dialog()
        confirm.assert_not_called()
        self.assertTrue(reopened._ost_osp_drop_elevation_check.isChecked())
        self.assertFalse(reopened._csv_drop_elevation_check.isChecked())

    def test_a_cancelled_warning_saves_nothing_and_publishes_nothing(self):
        dialog = self.open_dialog()
        with patch(CONFIRM, return_value=False):
            dialog._csv_drop_elevation_check.click()
        dialog.accept()
        self.assertEqual(self.repository.saved, [])
        self.assertEqual(self.event_bus.events, [])
        self.assertIs(getattr(self.aggregate.snapshot(), CSV_KEY), False)

    def test_turning_an_option_back_off_persists_without_a_warning(self):
        self.service.update_app_options(Config(**{CSV_KEY: True}))
        self.repository.saved.clear()
        self.event_bus.events.clear()
        dialog = self.open_dialog()
        with patch(CONFIRM) as confirm:
            dialog._csv_drop_elevation_check.click()
        confirm.assert_not_called()
        _apply_button(dialog).click()
        self.assertIs(self.repository.saved[0][CSV_KEY], False)
        self.assertEqual(self.event_bus.events, [_app_config_event({CSV_KEY: False})])


if __name__ == "__main__":
    unittest.main()
