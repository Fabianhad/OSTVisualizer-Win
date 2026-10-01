import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from ost_visualizer.presentation.dtos.picker_dialog_result_dto import (
    PickerDialogResult,
)
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
            self.assertEqual(dialog.edit_last_name.text(), "Lee")
            dialog.edit_last_name.clear()
            dialog.edit_employee_no.clear()
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                dialog._on_next()
            warning.assert_called_once_with(
                dialog,
                "Employee Detail",
                "First Name is required.\nLast Name is required.\n"
                "Employee Number is required.",
            )
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].employee_no, "1")
        finally:
            dialog.close()
            dialog.cleanup()
            dialog.deleteLater()

    def test_employee_detail_navigation_saves_valid_edits_before_moving(self):
        employees = [
            EmployeeRecord(
                uid="emp-1", employee_no="1", first_name="Ava", last_name="Lee"
            ),
            EmployeeRecord(
                uid="emp-2", employee_no="2", first_name="Mia", last_name="Ray"
            ),
        ]
        dialog = EmployeeDetailDialog(
            _master_data_support_FakeIconProvider(),
            employees,
            0,
            make_workspace_state_model(),
        )
        try:
            self.assertFalse(dialog.btn_previous.isEnabled())
            self.assertTrue(dialog.btn_next.isEnabled())
            dialog.edit_first_name.setText("  Zed ")
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                dialog._on_next()
            warning.assert_not_called()
            self.assertEqual(dialog._current_index, 1)
            self.assertEqual(dialog.get_results()[0].first_name, "Zed")
            self.assertEqual(dialog.edit_first_name.text(), "Mia")
            self.assertTrue(dialog.btn_previous.isEnabled())
            self.assertFalse(dialog.btn_next.isEnabled())
            dialog._on_previous()
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.edit_first_name.text(), "Zed")
            self.assertEqual(dialog.get_current_uid(), "emp-1")
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
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "confirm_not_found",
                return_value=True,
            ), patch.object(dialog, "_open_payroll_class_dialog") as open_picker:
                dialog._on_next()
            open_picker.assert_called_once_with(initial_name="Unknown")
            self.assertEqual(dialog._current_index, 0)
            self.assertEqual(dialog.get_results()[0].pay_class_uid, "pay-1")
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
            dialog.edit_employee_no.setText("E101")
            with patch(
                "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                "show_warning"
            ) as warning:
                self.assertTrue(dialog._validate_current())
            warning.assert_not_called()
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
            warning.assert_called_once_with(
                dialog,
                "Employee Detail",
                '"Regular" matches more than one item. Select the intended item '
                "from the list.",
            )
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
        self.assertIsNone(dialog._active_payroll_dialog)
        self.assertEqual(
            [(pc.uid, pc.name) for pc in dialog._pay_classes],
            [("pay-1", "Regular")],
        )

    def test_employee_detail_payroll_dialog_result_updates_pay_class_combo(self):
        class ResultPayrollDialog(QtWidgets.QDialog):
            accepted_result = True
            deleted_uids = frozenset()

            def __init__(self, *_args, parent=None, **_kwargs):
                super().__init__(parent)

            def exec(self):
                if self.accepted_result:
                    return QtWidgets.QDialog.DialogCode.Accepted
                return QtWidgets.QDialog.DialogCode.Rejected

            @property
            def was_cancelled(self):
                return not self.accepted_result

            @property
            def persisted_deleted_uids(self):
                return self.deleted_uids

            def get_result(self):
                return PickerDialogResult(
                    selected_uid="pay-2",
                    items=[
                        PayClass(uid="pay-1", name="Regular"),
                        PayClass(uid="pay-2", name="Night"),
                    ],
                )

            def cleanup(self):
                pass

        for accepted in (True, False):
            with self.subTest(accepted=accepted):
                dialog = EmployeeDetailDialog(
                    _master_data_support_FakeIconProvider(),
                    [
                        EmployeeRecord(
                            uid="emp-1", first_name="Ava", pay_class_uid="pay-1"
                        )
                    ],
                    0,
                    make_workspace_state_model(),
                    pay_classes=[PayClass(uid="pay-1", name="Regular")],
                )
                self.addCleanup(delete, dialog)

                class Variant(ResultPayrollDialog):
                    accepted_result = accepted
                    deleted_uids = frozenset({"pay-1"})

                with patch(
                    "ost_visualizer.presentation.dialogs.employee_detail_dialog."
                    "PayrollClassListDialog",
                    Variant,
                ):
                    dialog._open_payroll_class_dialog()
                if accepted:
                    self.assertEqual(dialog.combo_pay_class.currentData(), "pay-2")
                    self.assertEqual(dialog.combo_pay_class.currentText(), "Night")
                    self.assertEqual(
                        [pc.uid for pc in dialog.get_pay_classes()],
                        ["pay-1", "pay-2"],
                    )
                else:
                    self.assertEqual(dialog.get_pay_classes(), [])
                    self.assertEqual(dialog.combo_pay_class.count(), 0)
                    self.assertEqual(dialog.combo_pay_class.currentText(), "")
