import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import make_workspace_state_model
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.dialogs.employees_dialog import (
    EmployeesDialog as MasterEmployeesDialog,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    MasterEmployeesDialog as _master_data_support_MasterEmployeesDialog,
    _app as _master_data_support__app,
)


class EmployeeCreatedProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_newly_persisted_employee_can_receive_authoritative_updates(self):
        from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord

        parent = EmployeesDialog(
            Mock(),
            make_workspace_state_model(),
            save_fn=lambda changes: {"new_1": "10"},
        )
        try:
            employee = EmployeeRecord("new_1", is_new=True, first_name="New")
            self.assertEqual(parent._save_new_employee([employee], "new_1"), "10")
            parent._employees = [employee]
            parent._populate(select_uid="10")
            parent.refresh_employees([Employee("10", first_name="Renamed")])
            self.assertEqual(parent.tree.currentItem().text(1), "Renamed")
        finally:
            parent.cleanup()
            delete(parent)


class EmployeesDialogEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _employee_dialog(self, *, menu_mode=False):
        return _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[
                Employee(
                    uid="emp-1",
                    employee_no="1",
                    first_name="Ava",
                    last_name="Lee",
                )
            ],
            menu_mode=menu_mode,
        )

    def _employee_dialog_with_save(self, save_fn):
        return _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[
                Employee(
                    uid="emp-1",
                    employee_no="1",
                    first_name="Ava",
                    last_name="Lee",
                )
            ],
            save_fn=save_fn,
            menu_mode=True,
        )

    def test_employees_picker_keeps_select_and_cancel_buttons(self):
        dialog = self._employee_dialog()
        try:
            self.assertEqual(dialog.btn_select.text(), "Select")
            self.assertIsNotNone(dialog.btn_cancel)
            self.assertEqual(dialog.btn_cancel.text(), "Cancel")
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_menu_mode_shows_ok_only_above_edit_buttons(self):
        dialog = self._employee_dialog(menu_mode=True)
        try:
            self.assertEqual(dialog.btn_select.text(), "OK")
            self.assertIsNone(dialog.btn_cancel)
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog.btn_new.text(), "New")
            self.assertEqual(dialog.btn_change.text(), "Change")
            self.assertEqual(dialog.btn_delete.text(), "Delete")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_dialog_does_not_accept_when_save_returns_false(self):
        dialog = self._employee_dialog_with_save(lambda _changes: False)
        try:
            dialog.accept()
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            self.assertFalse(dialog._save_done)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employees_dialog_stops_after_detail_dialog_destroys_parent(self):
        dialog = self._employee_dialog()

        class DestroyingDetailDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            def get_pay_classes(self):
                raise AssertionError("destroyed employee detail must not be read")

            def cleanup(self):
                pass

        with patch(
            "ost_visualizer.presentation.dialogs.employees_dialog."
            "EmployeeDetailDialog",
            DestroyingDetailDialog,
        ):
            dialog._open_detail_dialog(dialog._employees, 0)

    def test_employee_detail_new_employee_saves_immediately_and_selects_real_uid(self):
        save_calls = []

        def save_fn(changes):
            employee = changes["new"][0]
            save_calls.append(
                {
                    "new_uid": employee.uid,
                    "new_is_new": employee.is_new,
                    "updated": list(changes["updated"]),
                }
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(len(save_calls), 1)
            self.assertEqual(save_calls[0]["new_uid"], "new_0")
            self.assertTrue(save_calls[0]["new_is_new"])
            self.assertEqual(save_calls[0]["updated"], [])
            current_item = dialog.tree.currentItem()
            self.assertIsNotNone(current_item)
            self.assertEqual(current_item.data(0, dialog._UID_ROLE), "emp-2")
            self.assertTrue(dialog.btn_select.isEnabled())
            self.assertEqual(dialog._employees[-1].uid, "emp-2")
            self.assertFalse(dialog._employees[-1].is_new)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_new_employee_remains_after_reopen_from_saved_source(self):
        saved_employees = []

        def save_fn(changes):
            employee = changes["new"][0]
            saved_employees.append(
                Employee(
                    uid="emp-2",
                    employee_no=employee.employee_no,
                    first_name=employee.first_name,
                    last_name=employee.last_name,
                )
            )
            return {"new_0": "emp-2"}

        dialog = self._employee_dialog_with_save(save_fn)
        try:
            detail_dialog = self._employee_detail_dialog_stub()
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()
        reopened = _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=saved_employees,
            selected_uid="emp-2",
        )
        try:
            self.assertEqual(reopened.tree.topLevelItemCount(), 1)
            self.assertEqual(
                reopened.tree.topLevelItem(0).data(0, reopened._UID_ROLE), "emp-2"
            )
            self.assertEqual(reopened.tree.currentItem().text(1), "Mia Ray")
        finally:
            reopened.close()
            reopened.cleanup()
            reopened.deleteLater()

    def test_employee_detail_cancel_does_not_save_new_employee(self):
        save_calls = []
        dialog = self._employee_dialog_with_save(
            lambda changes: save_calls.append(changes) or {"new_0": "emp-2"}
        )
        try:
            detail_dialog = self._employee_detail_dialog_stub(
                QtWidgets.QDialog.DialogCode.Rejected
            )
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_new_with_first_name("Mia")
            self.assertEqual(save_calls, [])
            self.assertEqual(dialog.tree.topLevelItemCount(), 1)
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_cancel_does_not_modify_existing_employee(self):
        dialog = self._employee_dialog()
        try:
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            detail_dialog = self._employee_detail_dialog_stub(
                QtWidgets.QDialog.DialogCode.Rejected
            )
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                detail_dialog,
            ):
                dialog._on_change()
            self.assertEqual(dialog._employees[0].first_name, "Ava")
            self.assertEqual(dialog._employees[0].last_name, "Lee")
            self.assertEqual(dialog.tree.topLevelItem(0).text(1), "Ava Lee")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_async_create_requires_authoritative_uid_mapping(self):
        callbacks = []
        dialog = _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[],
            save_async_fn=lambda _changes, completed: (
                callbacks.append(completed) or True
            ),
            menu_mode=True,
        )
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog."
                "EmployeeDetailDialog",
                self._employee_detail_dialog_stub(),
            ):
                dialog._on_new_with_first_name("Mia")
            dialog.accept()
            self.assertTrue(dialog._operation_pending)
            with patch(
                "ost_visualizer.presentation.dialogs.employees_dialog.show_warning"
            ) as warning:
                callbacks[0](True, {})
            self.assertFalse(dialog._operation_pending)
            self.assertFalse(dialog._save_done)
            self.assertTrue(dialog._employees[0].is_new)
            self.assertEqual(dialog._employees[0].uid, "new_0")
            warning.assert_called_once_with(
                dialog, "Employees", "Failed to create employee."
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_async_failure_preserves_external_interactivity_block(self):
        callbacks = []
        dialog = _master_data_support_MasterEmployeesDialog(
            _master_data_support_FakeIconProvider(),
            employees=[Employee(uid="emp-1", first_name="Ava")],
            save_async_fn=lambda _changes, completed: (
                callbacks.append(completed) or True
            ),
            menu_mode=True,
        )
        try:
            dialog._employees[0].first_name = "Mia"
            dialog.accept()
            dialog.set_interactive(False)
            callbacks[0](False, None)
            self.assertFalse(dialog._interactive)
            self.assertFalse(dialog.btn_new.isEnabled())
            self.assertFalse(dialog.btn_select.isEnabled())
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    @staticmethod
    def _employee_detail_dialog_stub(
        result=QtWidgets.QDialog.DialogCode.Accepted,
    ):
        class DetailDialog:
            def __init__(
                self,
                _icon_provider,
                employees,
                current_index,
                parent=None,
                pay_classes=None,
                pay_classes_save_fn=None,
                pay_classes_save_async_fn=None,
                pay_class_usage_fn=None,
                employee_baselines=None,
                workspace_state_model=make_workspace_state_model(),
            ):
                self._employees = list(employees)
                self._current_index = current_index
                employee = self._employees[current_index]
                employee.employee_no = "2"
                employee.first_name = "Mia"
                employee.last_name = "Ray"

            def exec(self):
                return result

            def get_results(self):
                return self._employees

            def get_current_uid(self):
                return self._employees[self._current_index].uid

            def get_pay_classes(self):
                return []

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        return DetailDialog
