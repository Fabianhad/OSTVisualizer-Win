import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.set_scale_dialog import (
    ScaleSettings,
    SetScaleDialog,
)
from PySide6 import QtWidgets
from shiboken6 import delete


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class SetScaleDialogAsyncLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_set_scale_failure_restores_interactive_retry(self):
        callbacks = []
        saved_settings = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda settings, completed: saved_settings.append(settings)
            or callbacks.append(completed)
            or True,
        )
        try:
            dialog._custom_radio.setChecked(True)
            dialog._custom_factor2_edit.setText("96")
            dialog._on_apply()
            self.assertFalse(dialog._ok_btn.isEnabled())
            self.assertFalse(dialog._custom_factor2_edit.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
            ) as show_warning:
                callbacks[0](False)
            show_warning.assert_called_once_with(
                dialog, "Save Failed", "Failed to save page scale."
            )
            self.assertTrue(dialog._ok_btn.isEnabled())
            self.assertTrue(dialog._custom_factor2_edit.isEnabled())
            self.assertTrue(dialog._apply_btn.isEnabled())
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            dialog._on_ok()
            self.assertEqual(len(callbacks), 2)
            self.assertEqual(saved_settings[0], saved_settings[1])
            self.assertEqual(saved_settings[1], ScaleSettings(1.0, 96.0, False))
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            callbacks[1](True)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_set_scale_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        dialog._custom_radio.setChecked(True)
        dialog._custom_factor2_edit.setText("96")
        dialog._on_apply()
        self.assertEqual(len(callbacks), 1)
        delete(dialog)
        with patch(
            "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
        ) as show_warning:
            callbacks[0](True)
            callbacks[0](False)
        show_warning.assert_not_called()
