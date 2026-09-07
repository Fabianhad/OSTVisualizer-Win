import unittest
from unittest.mock import Mock, patch
from PySide6 import QtWidgets
from shiboken6 import delete
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from tests.workspace_state_test_support import make_workspace_state_model


class CoverSheetMasterDataProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_remote_rename_delete_preserves_uid_and_parent_drafts(self):
        bus = EventBus()
        employees = [Employee("1", first_name="Old"), Employee("2", first_name="New")]
        statuses = [JobStatus("1", "Old"), JobStatus("2", "New")]
        pay_classes = [PayClass("1", "Old")]
        employee_reload = Mock(side_effect=lambda: (list(employees), list(pay_classes)))
        status_reload = Mock(side_effect=lambda: list(statuses))
        data = CoverSheetData(
            "bid",
            "1",
            "Job",
            "1",
            "",
            "",
            "1",
            "",
            employees=list(employees),
            job_statuses=list(statuses),
            pay_classes=list(pay_classes),
        )
        dialog = CoverSheetDialog(
            Mock(),
            None,
            data,
            make_workspace_state_model(),
            reload_employees_fn=employee_reload,
            reload_job_statuses_fn=status_reload,
            event_bus=bus,
            database_id="db",
        )
        try:
            dialog.edit_project_name.setText("Unsaved")
            employees[0] = Employee("1", first_name="New")
            statuses[0] = JobStatus("1", "New")
            with patch.object(dialog, "_populate") as rebuild:
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees", "pay_classes", "job_statuses"],
                )
                self.assertEqual(dialog.combo_estimator.currentText(), "New")
                self.assertEqual(dialog.combo_job_status.currentText(), "New")
                self.assertEqual(dialog.combo_estimator.currentData(), "1")
                self.assertEqual(dialog.combo_job_status.currentData(), "1")
                with patch.object(
                    dialog, "_replace_combo_items", wraps=dialog._replace_combo_items
                ) as replace_items:
                    bus.publish(
                        AppEvents.REMOTE_MASTER_DATA_CHANGED,
                        database_id="other",
                        families=["employees", "job_statuses"],
                    )
                    self.assertEqual(employee_reload.call_count, 1)
                    # Replayed notifications query current state; matching combos are untouched.
                    bus.publish(
                        AppEvents.REMOTE_MASTER_DATA_CHANGED,
                        database_id="db",
                        families=["employees", "pay_classes", "job_statuses"],
                    )
                    replace_items.assert_not_called()
                self.assertEqual(employee_reload.call_count, 2)
                self.assertEqual(status_reload.call_count, 2)
                dialog.combo_estimator.setEditText("Typed draft")
                employees[0] = Employee("1", first_name="Newest")
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["employees"],
                )
                self.assertEqual(dialog.combo_estimator.currentText(), "Typed draft")
                self.assertEqual(
                    dialog.combo_estimator.itemText(
                        dialog.combo_estimator.findData("1")
                    ),
                    "Newest",
                )
                statuses.pop(0)
                bus.publish(
                    AppEvents.REMOTE_MASTER_DATA_CHANGED,
                    database_id="db",
                    families=["job_statuses"],
                )
                self.assertEqual(dialog.combo_job_status.currentIndex(), -1)
                self.assertEqual(dialog.combo_job_status.currentText(), "")
                self.assertEqual(dialog.edit_project_name.text(), "Unsaved")
                rebuild.assert_not_called()
        finally:
            dialog.reject()
            employee_reload.reset_mock()
            bus.publish(
                AppEvents.REMOTE_MASTER_DATA_CHANGED,
                database_id="db",
                families=["employees"],
            )
            employee_reload.assert_not_called()
            delete(dialog)
