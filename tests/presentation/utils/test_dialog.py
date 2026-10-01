import os
import unittest
from ost_visualizer.application.dtos.write_reload_result import WriteReloadResult
from ost_visualizer.domain.entities.employee import Employee, PayClass
from PySide6 import QtCore, QtWidgets
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterPayrollClassListDialog as _master_data_support_MasterPayrollClassListDialog,
    _app as _master_data_support__app,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.utils.dialog import BaseListDialog, exec_transient_menu


class BasePickerSaveRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _payroll_class_dialog_with_save(self, save_fn):
        return _master_data_support_MasterPayrollClassListDialog(
            _master_data_support_FakeIconProvider(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
            save_fn=save_fn,
            menu_mode=True,
        )

    def test_base_picker_does_not_accept_when_save_returns_false(self):
        calls = []

        def save(changes):
            calls.append(changes)
            return False

        dialog = self._payroll_class_dialog_with_save(save)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                [record["uid"] for record in calls[0]["updated"]], ["pay-1"]
            )
            self.assertEqual(calls[0]["new"], [])
            self.assertEqual(calls[0]["deleted_uids"], [])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_base_picker_does_not_accept_when_write_reload_result_failed(self):
        dialog = self._payroll_class_dialog_with_save(
            lambda _changes: WriteReloadResult(write_success=False)
        )
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_base_picker_accepts_and_saves_once_when_save_succeeds(self):
        calls = []
        dialog = self._payroll_class_dialog_with_save(
            lambda changes: calls.append(changes) or {}
        )
        try:
            dialog.accept()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertTrue(dialog._save_done)
            dialog.accept()
            self.assertEqual(len(calls), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_base_picker_accepts_without_saving_when_nothing_changed(self):
        calls = []
        dialog = self._payroll_class_dialog_with_save(
            lambda changes: calls.append(changes) or False
        )
        try:
            dialog._items = []
            dialog.accept()
            self.assertEqual(calls, [])
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertTrue(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


class BaseListDialogCleanupTests(unittest.TestCase):
    def test_base_list_dialog_cleanup_releases_save_callback(self):
        dialog = BaseListDialog.__new__(BaseListDialog)
        retained = object()
        cleanup_calls = []
        dialog.icon_provider = retained
        dialog._save_fn = lambda: retained
        dialog._save_async_fn = lambda: retained
        dialog._on_cleanup = lambda: cleanup_calls.append("cleanup")
        BaseListDialog.cleanup(dialog)
        self.assertIsNone(dialog.icon_provider)
        self.assertIsNone(dialog._save_fn)
        self.assertIsNone(dialog._save_async_fn)
        self.assertEqual(cleanup_calls, ["cleanup"])

    def test_base_picker_cleanup_releases_callbacks_and_clears_records(self):
        _master_data_support__app()
        dialog = _master_data_support_MasterPayrollClassListDialog(
            _master_data_support_FakeIconProvider(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
            save_fn=lambda _changes: True,
            used_uids_fn=lambda: set(),
            menu_mode=True,
        )
        try:
            self.assertEqual(len(dialog._items), 1)
            dialog.cleanup()
            self.assertIsNone(dialog.icon_provider)
            self.assertIsNone(dialog._save_fn)
            self.assertIsNone(dialog._used_uids_fn)
            self.assertEqual(dialog._items, [])
        finally:
            dialog.close()
            dialog.deleteLater()
