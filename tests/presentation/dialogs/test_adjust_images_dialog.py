import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.adjust_images_dialog import (
    AdjustImagesDialog,
    ImageAdjustmentSettings,
)
from PySide6 import QtWidgets
from shiboken6 import delete


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class AdjustImagesDialogAsyncLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def test_adjust_images_waits_for_authoritative_async_save(self):
        callbacks = []
        saved_settings = []
        dialog = AdjustImagesDialog(
            None,
            None,
            0,
            False,
            False,
            False,
            False,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda settings, completed: saved_settings.append(settings)
            or callbacks.append(completed)
            or True,
        )
        try:
            dialog._flip_x_check.setChecked(True)
            dialog._on_ok()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertEqual(len(callbacks), 1)
            self.assertEqual(
                saved_settings,
                [ImageAdjustmentSettings(0, True, False, False, False, False)],
            )
            self.assertFalse(dialog._ok_btn.isEnabled())
            self.assertFalse(dialog._flip_x_check.isEnabled())
            dialog.reject()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            callbacks[0](True)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertTrue(dialog._flip_x_check.isEnabled())
            self.assertFalse(dialog._dirty)
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_adjust_images_failed_async_save_stays_open_and_restores_controls(self):
        callbacks = []
        dialog = AdjustImagesDialog(
            None,
            None,
            0,
            False,
            False,
            False,
            False,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        try:
            dialog._flip_x_check.setChecked(True)
            with mock.patch(
                "ost_visualizer.presentation.dialogs.adjust_images_dialog."
                "show_warning"
            ) as show_warning:
                dialog._on_ok()
                self.assertFalse(dialog._ok_btn.isEnabled())
                callbacks[0](False)
            show_warning.assert_called_once_with(
                dialog, "Save Failed", "Failed to save image adjustments."
            )
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertTrue(dialog._ok_btn.isEnabled())
            self.assertTrue(dialog._flip_x_check.isEnabled())
            self.assertTrue(dialog._dirty)
            self.assertFalse(dialog._accept_after_save)
            self.assertTrue(dialog._apply_btn.isEnabled())
        finally:
            dialog.close()
            dialog.deleteLater()

    def test_adjust_images_completion_is_dropped_after_dialog_destruction(self):
        callbacks = []
        dialog = AdjustImagesDialog(
            None,
            None,
            0,
            False,
            False,
            False,
            False,
            lambda _settings: self.fail("SQL must not use the synchronous save"),
            save_async_fn=lambda _settings, completed: callbacks.append(completed)
            or True,
        )
        dialog._flip_x_check.setChecked(True)
        dialog._on_apply()
        self.assertEqual(len(callbacks), 1)
        delete(dialog)
        with mock.patch(
            "ost_visualizer.presentation.dialogs.adjust_images_dialog.show_warning"
        ) as show_warning:
            callbacks[0](True)
            callbacks[0](False)
        show_warning.assert_not_called()
