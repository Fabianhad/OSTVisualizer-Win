import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    _app as _master_data_support__app,
)


class EmployeeDetailValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_employee_detail_cannot_navigate_past_invalid_required_fields(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
            ),
            EmployeeRecord(
                uid="emp-2",
                employee_no="2",
                first_name="Mia",
                last_name="Ray",
            ),
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
        )
        try:
            dialog.edit_first_name.clear()
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                dialog._on_next()
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].first_name, "Ava")
            warning.assert_called_once_with(
                dialog, "Employee Detail", "First Name is required."
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_cannot_navigate_past_unknown_pay_class(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
                pay_class_uid="pay-1",
            ),
            EmployeeRecord(
                uid="emp-2",
                employee_no="2",
                first_name="Mia",
                last_name="Ray",
            ),
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
        )
        try:
            dialog.combo_pay_class.setEditText("Unknown")
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "confirm_not_found",
                return_value=False,
            ) as confirm:
                dialog._on_next()
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].pay_class_uid, "pay-1")
            confirm.assert_called_once_with(dialog, "Unknown")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_preserves_selected_duplicate_pay_class_uid(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
                pay_class_uid="pay-2",
            )
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
            pay_classes=[
                PayClass(uid="pay-1", name="Regular"),
                PayClass(uid="pay-2", name="Regular"),
            ],
        )
        try:
            self.assertEqual(dialog.combo_pay_class.currentData(), "pay-2")
            dialog._save_current()
            self.assertEqual(dialog.get_results()[0].pay_class_uid, "pay-2")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_rejects_case_colliding_employee_number(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="E100",
                first_name="Ava",
                last_name="Lee",
            ),
            EmployeeRecord(
                uid="emp-2",
                employee_no="e100",
                first_name="Mia",
                last_name="Ray",
            ),
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            1,
            make_workspace_state_model(),
        )
        try:
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                self.assertFalse(dialog._validate_current())
            warning.assert_called_once_with(
                dialog,
                "Employee Detail",
                "Employee Number is already in use by another employee.",
            )
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_rejects_typed_ambiguous_pay_class_name(self):
        employees = [
            EmployeeRecord(
                uid="emp-1",
                employee_no="1",
                first_name="Ava",
                last_name="Lee",
            )
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
            pay_classes=[
                PayClass(uid="pay-1", name="Regular"),
                PayClass(uid="pay-2", name="Regular"),
            ],
        )
        try:
            dialog.combo_pay_class.setCurrentIndex(-1)
            dialog.combo_pay_class.setEditText("Regular")
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                self.assertFalse(dialog._validate_current())
            warning.assert_called_once()
            self.assertIn("matches more than one item", warning.call_args.args[2])
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_stops_after_payroll_dialog_destroys_parent(self):
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            [EmployeeRecord(uid="emp-1", first_name="Ava")],
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass(uid="pay-1", name="Regular")],
        )

        class DestroyingPayrollDialog(QtWidgets.QDialog):
            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(self.parent())
                return QtWidgets.QDialog.DialogCode.Rejected

            @property
            def was_cancelled(self):
                raise AssertionError("destroyed payroll dialog must not be read")

            def cleanup(self):
                pass

        with patch(
            "ost_visualizer.presentation.dialogs.employee_detail_dialog."
            "PayrollClassListDialog",
            DestroyingPayrollDialog,
        ):
            dialog._open_payroll_class_dialog()
