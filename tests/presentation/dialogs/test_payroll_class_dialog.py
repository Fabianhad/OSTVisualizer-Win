import unittest
from unittest.mock import Mock, patch
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import make_workspace_state_model
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog as MasterPayrollClassListDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterPayrollClassListDialog as _master_data_support_MasterPayrollClassListDialog,
    _app as _master_data_support__app,
)


class PayrollClassProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_standalone_pay_class_remote_deletion_clears_selected_result(self):
        bus = EventBus()
        classes = [PayClass("1", "Old"), PayClass("2", "Old")]
        reload_classes = Mock(side_effect=lambda: list(classes))
        dialog = PayrollClassListDialog(
            Mock(),
            make_workspace_state_model(),
            pay_classes=list(classes),
            selected_uid="1",
            event_bus=bus,
            database_id="db",
            reload_pay_classes_fn=reload_classes,
        )
        try:
            classes.pop(0)
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["pay_classes", "employees"],
            )
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertIsNone(dialog.tree.currentItem())
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.get_result().selected_uid)
            reload_classes.assert_called_once()
        finally:
            dialog.cleanup()
            delete(dialog)


class PayrollPickerButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _payroll_class_dialog(self, *, menu_mode=False):
        return _master_data_support_MasterPayrollClassListDialog(
            _master_data_support_FakeIconProvider(),
            pay_classes=[],
            menu_mode=menu_mode,
        )

    def test_payroll_class_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._payroll_class_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_payroll_class_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._payroll_class_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
