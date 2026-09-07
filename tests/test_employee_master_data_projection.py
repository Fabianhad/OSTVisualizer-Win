import unittest
from unittest.mock import Mock, patch
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from tests.workspace_state_test_support import make_workspace_state_model


class EmployeeMasterDataProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_open_detail_updates_pay_class_label_without_losing_drafts(self):
        bus = EventBus()
        classes = [PayClass("1", "Old"), PayClass("2", "New")]
        reload_classes = Mock(side_effect=lambda: list(classes))
        parent = EmployeesDialog(
            Mock(),
            make_workspace_state_model(),
            employees=[Employee("employee", first_name="Name", pay_class_uid="1")],
            pay_classes=list(classes),
            event_bus=bus,
            database_id="db",
            reload_pay_classes_fn=reload_classes,
        )

        def exercise(detail):
            detail.edit_first_name.setText("Unsaved name")
            with patch.object(
                detail,
                "_populate_pay_class_combo",
                wraps=detail._populate_pay_class_combo,
            ) as rebuild:
                classes[0] = PayClass("1", "New")
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees", "pay_classes"],
                )
                self.assertEqual(detail.combo_pay_class.currentText(), "New")
                self.assertEqual(detail.combo_pay_class.currentData(), "1")
                self.assertEqual(rebuild.call_count, 1)
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["pay_classes"],
                )
                self.assertEqual(rebuild.call_count, 1)
                detail.combo_pay_class.setEditText("Draft")
                classes[0] = PayClass("1", "Newest")
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["pay_classes"],
                )
                self.assertEqual(detail.combo_pay_class.currentText(), "Draft")
                detail._select_pay_class_by_uid("1")
                classes.pop(0)
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["pay_classes"],
                )
                self.assertEqual(detail.combo_pay_class.currentIndex(), -1)
                self.assertEqual(detail.combo_pay_class.currentText(), "")
                self.assertEqual(detail.edit_first_name.text(), "Unsaved name")
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            parent.tree.setCurrentItem(parent.tree.topLevelItem(0))
            item = parent.tree.currentItem()
            with patch.object(EmployeeDetailDialog, "exec", exercise), patch.object(
                parent, "_populate"
            ) as rebuild:
                parent._on_change()
                rebuild.assert_not_called()
                self.assertIs(parent.tree.currentItem(), item)
        finally:
            parent.cleanup()
            delete(parent)

    def test_open_pay_class_editor_merges_remote_labels_without_overwriting_draft(self):
        parent = EmployeeDetailDialog(
            Mock(),
            [],
            0,
            make_workspace_state_model(),
            pay_classes=[PayClass("1", "Old"), PayClass("2", "Sibling")],
        )

        def exercise(child):
            rows = {
                str(
                    child.tree.topLevelItem(i).data(0, child._UID_ROLE)
                ): child.tree.topLevelItem(i)
                for i in range(2)
            }
            rows["2"].setText(0, "Unsaved")
            child.tree.setCurrentItem(rows["1"])
            parent.refresh_pay_classes(
                [PayClass("1", "New"), PayClass("2", "Remote sibling")]
            )
            self.assertEqual(rows["1"].text(0), "New")
            self.assertEqual(rows["2"].text(0), "Unsaved")
            self.assertIs(child.tree.currentItem(), rows["1"])
            parent.refresh_pay_classes([PayClass("2", "Remote sibling")])
            self.assertEqual(child.tree.topLevelItemCount(), 1)
            self.assertIsNone(child.tree.currentItem())
            child.reject()
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            with patch.object(PayrollClassListDialog, "exec", exercise):
                parent._open_payroll_class_dialog()
        finally:
            parent.cleanup()
            delete(parent)

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

    def test_remote_employee_fields_merge_with_open_draft_and_deletion_rejects(self):
        bus = EventBus()
        employees = [
            Employee(
                "1",
                employee_no="1",
                first_name="Old",
                last_name="Name",
                email="old@test",
                pay_class_uid="p1",
            ),
            Employee("2", employee_no="2", first_name="Same", last_name="Name"),
        ]
        classes = [PayClass("p1", "Same"), PayClass("p2", "Same")]
        reload_employees = Mock(side_effect=lambda: (list(employees), list(classes)))
        parent = EmployeesDialog(
            Mock(),
            make_workspace_state_model(),
            employees=list(employees),
            pay_classes=classes,
            event_bus=bus,
            database_id="db",
            reload_employees_fn=reload_employees,
        )

        def exercise(detail):
            detail.edit_first_name.setText("Draft")
            classes.pop(0)
            employees[0] = Employee(
                "1",
                employee_no="10",
                first_name="Same",
                last_name="Renamed",
                email="new@test",
                pay_class_uid="p2",
            )
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees", "pay_classes"],
            )
            self.assertEqual(detail.edit_employee_no.text(), "10")
            self.assertEqual(detail.edit_email.text(), "new@test")
            self.assertEqual(detail.edit_first_name.text(), "Draft")
            self.assertEqual(detail.edit_last_name.text(), "Renamed")
            self.assertEqual(detail.combo_pay_class.currentData(), "p2")
            self.assertEqual(detail.get_current_uid(), "1")
            self.assertEqual(reload_employees.call_count, 1)
            with patch.object(
                detail.edit_email, "setText", wraps=detail.edit_email.setText
            ) as write_email:
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees"],
                )
                write_email.assert_not_called()
            detail.edit_email.setText("draft@test")
            employees[0] = Employee(
                "1",
                employee_no="11",
                first_name="Same",
                last_name="Latest",
                email="latest@test",
                pay_class_uid="p2",
            )
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees"],
            )
            self.assertEqual(detail.edit_email.text(), "draft@test")
            self.assertEqual(detail.edit_last_name.text(), "Latest")
            detail._on_next()
            detail._on_previous()
            self.assertEqual(detail.edit_first_name.text(), "Draft")
            self.assertEqual(detail.edit_email.text(), "draft@test")
            rejected = Mock()
            detail.rejected.connect(rejected)
            employees.pop(0)
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees"],
            )
            rejected.assert_called_once()
            self.assertFalse(detail.btn_ok.isEnabled())
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            parent.tree.setCurrentItem(parent.tree.topLevelItem(0))
            with patch.object(EmployeeDetailDialog, "exec", exercise), patch.object(
                parent, "_populate"
            ) as rebuild:
                parent._on_change()
                rebuild.assert_not_called()
            self.assertEqual(parent.tree.topLevelItemCount(), 1)
            self.assertIsNone(parent.tree.currentItem())
        finally:
            parent.cleanup()
            delete(parent)

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
