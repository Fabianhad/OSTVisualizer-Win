import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.adjust_images_dialog import AdjustImagesDialog
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
            dialog._on_ok()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            self.assertFalse(dialog._ok_btn.isEnabled())
            dialog.reject()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)
            callbacks[0](True)
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
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
        delete(dialog)
        callbacks[0](True)
