import os
import unittest
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
        dialog = self._payroll_class_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()


class BaseListDialogCleanupTests(unittest.TestCase):
    def test_base_list_dialog_cleanup_releases_save_callback(self):
        dialog = BaseListDialog.__new__(BaseListDialog)
        retained = object()
        dialog.icon_provider = retained
        dialog._save_fn = lambda: retained
        dialog._on_cleanup = lambda: None
        BaseListDialog.cleanup(dialog)
        self.assertIsNone(dialog.icon_provider)
        self.assertIsNone(dialog._save_fn)
