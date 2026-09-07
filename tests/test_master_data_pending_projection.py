import unittest
from unittest.mock import Mock, patch
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from tests.workspace_state_test_support import make_workspace_state_model


class MasterDataPendingProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pending_success_does_not_accept_a_newer_conflicting_projection(self):
        for kind in ("employee", "pay_class"):
            for outcome in ("rename", "delete", "own_commit", "rejection", "reverted"):
                with self.subTest(kind=kind, outcome=outcome):
                    callbacks = []

                    def queue(changes, completed):
                        callbacks.append(completed)
                        return True

                    if kind == "employee":
                        dialog = EmployeesDialog(
                            Mock(),
                            make_workspace_state_model(),
                            employees=[Employee("1", first_name="Old")],
                            save_async_fn=queue,
                        )
                        dialog._employees[0].first_name = "Draft"
                    else:
                        dialog = PayrollClassListDialog(
                            Mock(),
                            make_workspace_state_model(),
                            pay_classes=[PayClass("1", "Old")],
                            save_async_fn=queue,
                        )
                        dialog.tree.topLevelItem(0).setText(0, "Draft")
                    dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
                    accepted = Mock()
                    dialog.accepted.connect(accepted)
                    try:
                        dialog.accept()
                        self.assertEqual(len(callbacks), 1)
                        self.assertTrue(dialog._operation_pending)
                        name = "Draft" if outcome == "own_commit" else "Remote"
                        with patch.object(dialog, "_populate") as rebuild:
                            if kind == "employee":
                                dialog.refresh_employees(
                                    []
                                    if outcome == "delete"
                                    else [Employee("1", first_name=name)]
                                )
                            else:
                                dialog.refresh_pay_classes(
                                    [] if outcome == "delete" else [PayClass("1", name)]
                                )
                            if outcome == "reverted":
                                if kind == "employee":
                                    dialog.refresh_employees(
                                        [Employee("1", first_name="Old")]
                                    )
                                else:
                                    dialog.refresh_pay_classes([PayClass("1", "Old")])
                            with patch.object(
                                QtWidgets.QMessageBox, "warning"
                            ) as warning:
                                callbacks[0](outcome != "rejection", {})
                                self.assertFalse(dialog._operation_pending)
                                if outcome == "own_commit":
                                    accepted.assert_called_once()
                                    warning.assert_not_called()
                                else:
                                    accepted.assert_not_called()
                                    self.assertFalse(dialog._save_done)
                                    self.assertEqual(
                                        warning.call_count,
                                        0 if outcome == "rejection" else 1,
                                    )
                            rebuild.assert_not_called()
                        if outcome == "delete":
                            self.assertEqual(dialog.tree.topLevelItemCount(), 0)
                        elif outcome != "own_commit":
                            # A valid remaining draft may be reviewed and retried.
                            dialog.accept()
                            self.assertEqual(len(callbacks), 2)
                            if kind == "employee":
                                dialog.refresh_employees(
                                    [Employee("1", first_name="Draft")]
                                )
                            else:
                                dialog.refresh_pay_classes([PayClass("1", "Draft")])
                            callbacks[1](True, {})
                            accepted.assert_called_once()
                    finally:
                        dialog.cleanup()
                        delete(dialog)

    def test_nested_pending_save_keeps_new_parent_label_and_draft(self):
        callbacks = []

        def queue(changes, completed):
            callbacks.append(completed)
            return True

        parent = EmployeeDetailDialog(
            Mock(),
            [EmployeeRecord("1", first_name="Old", pay_class_uid="p")],
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass("p", "Old")],
            pay_classes_save_async_fn=queue,
        )
        parent.edit_first_name.setText("Unsaved employee")

        def exercise(child):
            child.tree.setCurrentItem(child.tree.topLevelItem(0))
            child.tree.currentItem().setText(0, "Draft class")
            accepted = Mock()
            child.accepted.connect(accepted)
            child.accept()
            parent.refresh_pay_classes([PayClass("p", "Remote class")])
            with patch.object(QtWidgets.QMessageBox, "warning") as warning:
                callbacks[0](True, {})
                accepted.assert_not_called()
                warning.assert_called_once()
            child.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            with patch.object(PayrollClassListDialog, "exec", exercise):
                parent._open_payroll_class_dialog()
            self.assertEqual(parent.combo_pay_class.currentData(), "p")
            self.assertEqual(parent.combo_pay_class.currentText(), "Remote class")
            self.assertEqual(parent.edit_first_name.text(), "Unsaved employee")
        finally:
            parent.cleanup()
            delete(parent)

    def test_completion_after_editor_cleanup_is_inert(self):
        for kind in ("employee", "pay_class"):
            with self.subTest(kind=kind):
                callbacks = []

                def queue(changes, completed):
                    callbacks.append(completed)
                    return True

                if kind == "employee":
                    dialog = EmployeesDialog(
                        Mock(),
                        make_workspace_state_model(),
                        employees=[Employee("1")],
                        save_async_fn=queue,
                    )
                else:
                    dialog = PayrollClassListDialog(
                        Mock(),
                        make_workspace_state_model(),
                        pay_classes=[PayClass("1", "Old")],
                        save_async_fn=queue,
                    )
                accepted = Mock()
                dialog.accepted.connect(accepted)
                try:
                    dialog.accept()
                    dialog.cleanup()
                    with patch.object(QtWidgets.QMessageBox, "warning") as warning:
                        callbacks[0](True, {})
                        accepted.assert_not_called()
                        warning.assert_not_called()
                finally:
                    delete(dialog)
