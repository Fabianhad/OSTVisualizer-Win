import unittest
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.employee import Employee
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.workspace_state_test_support import make_workspace_state_model


class NestedParentCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_nested_terminal_result_does_not_project_into_closed_cover_sheet(self):
        for kind in ("employee", "status"):
            for closed in (False, True):
                for success in (False, True):
                    with self.subTest(kind=kind, closed=closed, success=success):
                        callbacks = []

                        def queue(changes, completed):
                            callbacks.append(completed)
                            return True

                        employees = [Employee("1", first_name="Old")]
                        statuses = [JobStatus("1", "Old")]
                        reload_employees = Mock(return_value=(employees, []))
                        reload_statuses = Mock(return_value=statuses)
                        parent = CoverSheetDialog(
                            Mock(),
                            None,
                            CoverSheetData(
                                "bid",
                                "1",
                                "Job",
                                "1",
                                "",
                                "",
                                "1",
                                "",
                                employees=employees,
                                job_statuses=statuses,
                            ),
                            make_workspace_state_model(),
                            save_employees_async_fn=queue,
                            save_job_statuses_async_fn=queue,
                            reload_employees_fn=reload_employees,
                            reload_job_statuses_fn=reload_statuses,
                        )
                        parent.edit_project_name.setText("Parent draft")
                        child_type = (
                            EmployeesDialog if kind == "employee" else JobStatusesDialog
                        )

                        def exercise(child):
                            child.tree.setCurrentItem(child.tree.topLevelItem(0))
                            if kind == "employee":
                                child._employees[0].first_name = "Edited"
                            else:
                                child.tree.currentItem().setText(0, "Edited")
                            child.accept()
                            self.assertEqual(len(callbacks), 1)
                            if closed:
                                parent.reject()
                                combo = (
                                    parent.combo_estimator
                                    if kind == "employee"
                                    else parent.combo_job_status
                                )
                                combo.setEditText("Retired parent draft")
                            callbacks[0](success, {})
                            if not success:
                                child.reject()
                            return child.result()

                        try:
                            with patch.object(
                                parent,
                                "_replace_combo_items",
                                wraps=parent._replace_combo_items,
                            ) as rebuild:
                                with patch.object(child_type, "exec", exercise):
                                    if kind == "employee":
                                        parent._open_employees_dialog()
                                    else:
                                        parent._open_job_statuses_dialog()
                                reload_fn = (
                                    reload_employees
                                    if kind == "employee"
                                    else reload_statuses
                                )
                                if closed:
                                    combo = (
                                        parent.combo_estimator
                                        if kind == "employee"
                                        else parent.combo_job_status
                                    )
                                    self.assertEqual(
                                        combo.currentText(), "Retired parent draft"
                                    )
                                self.assertEqual(
                                    reload_fn.call_count, 0 if closed else 1
                                )
                                self.assertEqual(rebuild.call_count, 0 if closed else 1)
                                self.assertEqual(
                                    parent.edit_project_name.text(), "Parent draft"
                                )
                        finally:
                            parent.reject()
                            delete(parent)

    def test_bid_areas_return_does_not_refresh_closed_cover_sheet(self):
        from ost_visualizer.domain.entities.area import BidArea
        from ost_visualizer.presentation.dialogs.areas_dialog import BidAreasDialog

        for closed in (False, True):
            for accepted in (False, True):
                with self.subTest(closed=closed, accepted=accepted):
                    parent = CoverSheetDialog(
                        Mock(),
                        None,
                        CoverSheetData("bid", "1", "Job", "", "", "", "", ""),
                        make_workspace_state_model(),
                        reload_bid_areas_fn=lambda: [
                            BidArea(
                                uid="area",
                                bid_uid="bid",
                                name="Old",
                                parent_uid="",
                                sequence=0,
                            )
                        ],
                        save_bid_areas_fn=lambda changes: {},
                    )

                    def refresh():
                        parent.edit_project_name.setText("Reloaded")
                        return True

                    refresh_spy = Mock(side_effect=refresh)
                    parent._refresh_fn = refresh_spy

                    def exercise(child):
                        child.tree.topLevelItem(0).setText(0, "Saved Area")
                        self.assertTrue(child.flush_pending_save())
                        self.assertTrue(child.has_saved_changes())
                        if closed:
                            parent.reject()
                        parent.edit_project_name.setText("Newer draft")
                        if accepted:
                            child.accept()
                        else:
                            child.reject()
                        return child.result()

                    try:
                        with patch.object(BidAreasDialog, "exec", exercise):
                            parent._open_bid_areas_dialog()
                        self.assertEqual(
                            parent.edit_project_name.text(),
                            "Newer draft" if closed else "Reloaded",
                        )
                        self.assertEqual(refresh_spy.call_count, 0 if closed else 1)
                    finally:
                        parent.reject()
                        delete(parent)
