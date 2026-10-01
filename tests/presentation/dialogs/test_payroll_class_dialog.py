import unittest
from unittest.mock import Mock, patch
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.interfaces.i_window_icon_provider import (
    IWindowIconProvider,
)
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
            Mock(spec=IWindowIconProvider),
            make_workspace_state_model(),
            pay_classes=list(classes),
            selected_uid="1",
            event_bus=bus,
            database_id="db",
            reload_pay_classes_fn=reload_classes,
        )
        try:
            self.assertEqual(dialog.tree.currentItem().data(0, dialog._UID_ROLE), "1")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.get_result().selected_uid, "1")
            classes.pop(0)
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["pay_classes", "employees"],
            )
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.tree.topLevelItem(0).data(0, dialog._UID_ROLE), "2")
            self.assertIsNone(dialog.tree.currentItem())
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertFalse(dialog.get_result().selected_uid)
            self.assertEqual(
                [(pc.uid, pc.name) for pc in dialog.get_result().items],
                [("2", "Old")],
            )
            reload_classes.assert_called_once()
        finally:
            dialog.cleanup()
            delete(dialog)

    def test_standalone_pay_class_ignores_other_database_family_and_cleaned_up(self):
        bus = EventBus()
        classes = [PayClass("1", "Old"), PayClass("2", "Old")]
        reload_classes = Mock(side_effect=lambda: list(classes))
        dialog = PayrollClassListDialog(
            Mock(spec=IWindowIconProvider),
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
                database_id="other-db",
                families=["pay_classes"],
            )
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees"],
            )
            reload_classes.assert_not_called()
            self.assertEqual(dialog.tree.topLevelItemCount(), 2)
            self.assertEqual(dialog.get_result().selected_uid, "1")
            dialog.cleanup()
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["pay_classes"],
            )
            reload_classes.assert_not_called()
        finally:
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
            pay_classes=[PayClass("1", "Hourly")],
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

    def test_payroll_class_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._payroll_class_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
            self.assertEqual(
                self._button_column(dialog), ["Select", "Cancel", "New", "Delete"]
            )
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            self.assertTrue(dialog.btn_select.isEnabled())
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertEqual(dialog.get_result().selected_uid, "1")
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
            self.assertEqual(self._button_column(dialog), ["OK", "New", "Delete"])
            dialog.btn_select.click()
            self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertIsNone(dialog.get_result().selected_uid)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
