import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog


def _app():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class FakeIconProvider:
    def set_window_icon(self, _window):
        pass


class JobStatusesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def tearDown(self):
        self.app.processEvents()

    def _make_dialog(self, *, menu_mode=False):
        return JobStatusesDialog(
            FakeIconProvider(),
            job_statuses=[
                JobStatus(uid="1", name="Open", locked=False, sequence=1),
                JobStatus(uid="2", name="Locked", locked=True, sequence=2),
            ],
            menu_mode=menu_mode,
        )

    def test_default_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._make_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._make_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
            self.assertEqual(dialog.btn_move_up.text(), "Move Up")
            self.assertEqual(dialog.btn_move_down.text(), "Move Down")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
