import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.employee import PayClass
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from ost_visualizer.presentation.dtos.employee_edit_dtos import EmployeeRecord
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.helpers.workspace_state import make_workspace_state_model
import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.employee import Employee, PayClass
from PySide6.QtTest import QTest
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
    _app as _master_data_support__app,
)


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
                        _master_data_support_FakeIconProvider(),
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
                    executed = []

                    def exercise(child):
                        executed.append(child)
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
                            self.assertEqual(len(executed), 1)
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


class EmployeePayClassSaveWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _master_data_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_employee_pay_class_save_retry_refreshes_parent_once_by_uid(self):
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                submissions = []

                def save(changes):
                    submissions.append(changes)
                    return False if len(submissions) == 1 else {"new_0": "pay-b"}

                def queue(changes, completed):
                    result = save(changes)
                    completed(result is not False, result)
                    return True

                parent = EmployeeDetailDialog(
                    _master_data_support_FakeIconProvider(),
                    [
                        EmployeeRecord(
                            uid="emp-1",
                            employee_no="1",
                            first_name="Ava",
                            pay_class_uid="pay-a",
                        )
                    ],
                    0,
                    make_workspace_state_model(),
                    pay_classes=[
                        PayClass(uid="sibling", name="Regular"),
                        PayClass(uid="pay-a", name="Regular"),
                    ],
                    pay_classes_save_fn=save,
                    pay_classes_save_async_fn=queue if asynchronous else None,
                )
                errors = []

                def exercise_nested():
                    child = parent._active_payroll_dialog
                    try:
                        original = child.tree.currentItem()
                        self.assertEqual(original.data(0, child._UID_ROLE), "pay-a")
                        original.setText(0, "Renamed pay class")
                        child.btn_new.click()
                        editor = child.tree.viewport().focusWidget()
                        self.assertIsInstance(editor, QtWidgets.QLineEdit)
                        QTest.keyClicks(editor, "Created pay class")
                        QTest.keyClick(editor, QtCore.Qt.Key.Key_Return)
                        child.tree.setCurrentItem(original)
                        child.btn_select.click()
                        self.assertTrue(child.isVisible())
                        self.assertTrue(child.btn_select.isEnabled())
                        self.assertEqual(
                            parent.combo_pay_class.currentText(), "Regular"
                        )
                        child.btn_select.click()
                    except BaseException as exc:
                        errors.append(exc)
                    finally:
                        if child.isVisible():
                            child.reject()

                try:
                    parent.edit_first_name.setText("Unsaved employee")
                    with patch.object(
                        parent,
                        "_populate_pay_class_combo",
                        wraps=parent._populate_pay_class_combo,
                    ) as refresh:
                        QtCore.QTimer.singleShot(0, exercise_nested)
                        parent._btn_pay_class_picker.click()
                        self.assertEqual(refresh.call_count, 1)
                    if errors:
                        raise errors[0]
                    self.assertEqual(len(submissions), 2)
                    self.assertEqual(parent.combo_pay_class.currentData(), "pay-a")
                    self.assertEqual(
                        parent.combo_pay_class.currentText(), "Renamed pay class"
                    )
                    self.assertEqual(parent.edit_first_name.text(), "Unsaved employee")
                    self.assertEqual(parent.get_current_uid(), "emp-1")
                    self.assertEqual(
                        {
                            parent.combo_pay_class.itemData(i)
                            for i in range(parent.combo_pay_class.count())
                        },
                        {"pay-a", "pay-b", "sibling"},
                    )
                finally:
                    parent.close()
                    parent.cleanup()
                    parent.deleteLater()

    def test_employee_pay_class_cancel_projects_only_committed_deletions(self):
        for asynchronous in (False, True):
            for deletion_succeeds in (False, True):
                with self.subTest(
                    asynchronous=asynchronous, deletion_succeeds=deletion_succeeds
                ):
                    persisted = [
                        PayClass(uid="pay-0", name="Overtime"),
                        PayClass(uid="pay-a", name="Regular"),
                        PayClass(uid="pay-b", name="Regular"),
                    ]
                    writes = []

                    def save(changes):
                        writes.append(changes)
                        if not deletion_succeeds:
                            return False
                        persisted[:] = [
                            pc
                            for pc in persisted
                            if pc.uid not in changes["deleted_uids"]
                        ]
                        return {}

                    def queue(changes, completed):
                        result = save(changes)
                        completed(result is not False, result)
                        return True

                    employee = EmployeeRecord(
                        uid="emp-1",
                        employee_no="1",
                        first_name="Ava",
                        pay_class_uid="pay-a",
                    )
                    parent = EmployeeDetailDialog(
                        _master_data_support_FakeIconProvider(),
                        [employee],
                        0,
                        make_workspace_state_model(),
                        pay_classes=persisted,
                        pay_classes_save_fn=save,
                        pay_classes_save_async_fn=queue if asynchronous else None,
                    )
                    errors = []

                    def exercise_nested():
                        child = parent._active_payroll_dialog
                        try:
                            retained = next(
                                child.tree.topLevelItem(i)
                                for i in range(child.tree.topLevelItemCount())
                                if child.tree.topLevelItem(i).data(0, child._UID_ROLE)
                                == "pay-a"
                            )
                            removed = next(
                                child.tree.topLevelItem(i)
                                for i in range(child.tree.topLevelItemCount())
                                if child.tree.topLevelItem(i).data(0, child._UID_ROLE)
                                == "pay-b"
                            )
                            retained.setText(0, "Unsaved rename")
                            child.tree.setCurrentItem(removed)
                            with patch(
                                "ost_visualizer.presentation.utils.dialog.confirm_multi_delete",
                                return_value=[("Regular", "pay-b")],
                            ):
                                child.btn_delete.click()
                        except BaseException as exc:
                            errors.append(exc)
                        finally:
                            child.reject()

                    try:
                        parent.edit_first_name.setText("Unsaved employee")
                        with patch.object(
                            parent,
                            "_populate_pay_class_combo",
                            wraps=parent._populate_pay_class_combo,
                        ) as refresh:
                            QtCore.QTimer.singleShot(0, exercise_nested)
                            parent._btn_pay_class_picker.click()
                            self.assertEqual(refresh.call_count, int(deletion_succeeds))
                        if errors:
                            raise errors[0]
                        self.assertEqual(len(writes), 1)
                        self.assertEqual(writes[0]["deleted_uids"], ["pay-b"])
                        expected_rows = [
                            ("pay-0", "Overtime"),
                            ("pay-a", "Regular"),
                        ] + ([] if deletion_succeeds else [("pay-b", "Regular")])
                        self.assertEqual(
                            [
                                (
                                    parent.combo_pay_class.itemData(i),
                                    parent.combo_pay_class.itemText(i),
                                )
                                for i in range(parent.combo_pay_class.count())
                            ],
                            expected_rows,
                        )
                        self.assertEqual(
                            [(pc.uid, pc.name) for pc in persisted], expected_rows
                        )
                        self.assertEqual(parent.combo_pay_class.currentData(), "pay-a")
                        self.assertEqual(
                            parent.combo_pay_class.currentText(), "Regular"
                        )
                        self.assertEqual(
                            parent.edit_first_name.text(), "Unsaved employee"
                        )
                        self.assertEqual(parent.get_current_uid(), "emp-1")
                    finally:
                        parent.close()
                        parent.cleanup()
                        parent.deleteLater()
