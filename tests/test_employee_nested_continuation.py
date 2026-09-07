import unittest
from unittest.mock import Mock, patch
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from ost_visualizer.domain.entities.employee import PayClass
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from tests.workspace_state_test_support import make_workspace_state_model


class EmployeeNestedContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_pay_class_return_requires_current_employee_parent(self):
        for transition in ("current", "close", "navigate", "access", "cleanup"):
            for success in (False, True):
                with self.subTest(transition=transition, success=success):
                    callbacks = []

                    def queue(changes, completed):
                        callbacks.append(completed)
                        return True

                    parent = EmployeeDetailDialog(
                        Mock(),
                        [
                            EmployeeRecord(
                                "1",
                                first_name="First",
                                last_name="One",
                                employee_no="1",
                                pay_class_uid="p",
                            ),
                            EmployeeRecord(
                                "2",
                                first_name="Second",
                                last_name="Two",
                                employee_no="2",
                                pay_class_uid="q",
                            ),
                        ],
                        0,
                        make_workspace_state_model(),
                        pay_classes=[PayClass("p", "Old"), PayClass("q", "Other")],
                        pay_classes_save_async_fn=queue,
                    )

                    def exercise(child):
                        child.tree.setCurrentItem(child.tree.topLevelItem(0))
                        child.tree.currentItem().setText(0, "Saved")
                        child.accept()
                        self.assertEqual(len(callbacks), 1)
                        if transition == "close":
                            parent.reject()
                        elif transition == "navigate":
                            parent._on_next()
                        elif transition == "access":
                            parent.set_interactive(False)
                        elif transition == "cleanup":
                            parent.cleanup()
                        parent.edit_first_name.setText("New draft")
                        parent.combo_pay_class.setCurrentIndex(
                            parent.combo_pay_class.findData("q")
                        )
                        rebuild.reset_mock()
                        callbacks[0](success, {})
                        if not success:
                            child.reject()
                        return child.result()

                    try:
                        with patch.object(
                            parent,
                            "_populate_pay_class_combo",
                            wraps=parent._populate_pay_class_combo,
                        ) as rebuild:
                            with patch.object(PayrollClassListDialog, "exec", exercise):
                                parent._open_payroll_class_dialog()
                            self.assertEqual(
                                parent.combo_pay_class.currentData(),
                                "p" if transition == "current" and success else "q",
                            )
                            self.assertEqual(
                                rebuild.call_count,
                                1 if transition == "current" and success else 0,
                            )
                            self.assertEqual(parent.edit_first_name.text(), "New draft")
                    finally:
                        parent.cleanup()
                        delete(parent)
                        QtCore.QCoreApplication.sendPostedEvents(
                            None, QtCore.QEvent.Type.DeferredDelete
                        )
