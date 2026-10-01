import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.cover_sheet import JobStatus
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from PySide6 import QtWidgets
from tests.helpers.workspace_state import with_workspace_state

JobStatusesDialog = with_workspace_state(JobStatusesDialog)


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

    def _button_column(self, dialog):
        content_row = dialog.layout().itemAt(1).layout()
        column = content_row.itemAt(1).layout()
        return [
            column.itemAt(index).widget().text()
            for index in range(column.count())
            if column.itemAt(index).widget() is not None
        ]

    def test_default_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._make_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertEqual(
                self._button_column(dialog),
                ["Select", "Cancel", "New", "Delete", "Move Up", "Move Down"],
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(1))
            self.assertTrue(dialog.btn_select.isEnabled())
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.get_result().selected_uid, "2")
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
            self.assertEqual(
                self._button_column(dialog),
                ["OK", "New", "Delete", "Move Up", "Move Down"],
            )
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
            self.assertEqual(dialog.btn_move_up.text(), "Move Up")
            self.assertEqual(dialog.btn_move_down.text(), "Move Down")
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIsNone(dialog.get_result().selected_uid)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
