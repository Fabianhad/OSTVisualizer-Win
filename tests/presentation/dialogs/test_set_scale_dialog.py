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
        dialog = SetScaleDialog(
            None,
            None,
            1.0,
            48.0,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        try:
            dialog._custom_radio.setChecked(True)
            dialog._custom_factor2_edit.setText("96")
            dialog._on_apply()
            self.assertFalse(dialog._ok_btn.isEnabled())
            with patch(
                "ost_visualizer.presentation.dialogs.set_scale_dialog.show_warning"
            ):
                callbacks[0](False)
            self.assertTrue(dialog._ok_btn.isEnabled())
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
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
        delete(dialog)
        callbacks[0](True)
