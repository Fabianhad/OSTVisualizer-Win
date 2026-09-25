import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from ost_visualizer.application.services.project_read_service import ProjectReadService
from ost_visualizer.domain.entities.cover_sheet import CoverSheetData, JobStatus
from ost_visualizer.domain.entities.employee import Employee, PayClass
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.infrastructure.mdb.components.settings_reader import (
    SettingsReaderMixin,
)
from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
    UIEventCoordinator,
)
from ost_visualizer.presentation.dialogs.cover_sheet.dialog import CoverSheetDialog
from ost_visualizer.presentation.dialogs.employee_detail_dialog import (
    EmployeeDetailDialog,
)
from ost_visualizer.presentation.dialogs.employees_dialog import EmployeesDialog
from ost_visualizer.presentation.dialogs.job_statuses_dialog import JobStatusesDialog
from ost_visualizer.presentation.dialogs.payroll_class_dialog import (
    PayrollClassListDialog,
)
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.workspace_state_test_support import make_workspace_state_model


class MasterDataActionUsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_delete_uses_current_usage_without_rebuilding(self):
        cases = (
            (
                EmployeesDialog,
                {
                    "employees": [
                        Employee("1", first_name="Same"),
                        Employee("2", first_name="Same"),
                    ],
                    "used_uids": {"1"},
                },
            ),
            (
                PayrollClassListDialog,
                {
                    "pay_classes": [PayClass("1", "Same"), PayClass("2", "Same")],
                    "used_pay_class_uids": {"1"},
                },
            ),
            (
                JobStatusesDialog,
                {
                    "job_statuses": [JobStatus("1", "Same"), JobStatus("2", "Same")],
                    "used_job_status_uids": {"1"},
                },
            ),
        )
        for cls, kwargs in cases:
            with self.subTest(dialog=cls.__name__):
                save = Mock(return_value=True)
                usage = Mock(return_value={"2"})
                dialog = cls(
                    Mock(),
                    make_workspace_state_model(),
                    save_fn=save,
                    used_uids_fn=usage,
                    **kwargs
                )
                usage.assert_not_called()
                try:
                    col = 0 if cls is EmployeesDialog else dialog._uid_col
                    item = next(
                        dialog.tree.topLevelItem(i)
                        for i in range(2)
                        if str(dialog.tree.topLevelItem(i).data(col, dialog._UID_ROLE))
                        == "1"
                    )
                    dialog.tree.setCurrentItem(item)
                    scroll = dialog.tree.verticalScrollBar().value()
                    with patch.object(
                        QtWidgets.QMessageBox,
                        "question",
                        return_value=QtWidgets.QMessageBox.StandardButton.No,
                    ) as question, patch.object(
                        QtWidgets.QMessageBox, "warning"
                    ) as warning, patch.object(
                        dialog, "_populate"
                    ) as rebuild:
                        dialog._on_delete()
                        self.assertEqual(
                            question.call_count,
                            1,
                            "removed usage must no longer block the selected UID",
                        )
                        warning.assert_not_called()
                        usage.return_value = {"1"}
                        dialog._on_delete()
                        self.assertEqual(warning.call_count, 1)
                        self.assertEqual(question.call_count, 1)
                        usage.side_effect = RuntimeError("unavailable")
                        dialog._on_delete()
                        self.assertEqual(warning.call_count, 2)
                        self.assertEqual(question.call_count, 1)
                        self.assertEqual(usage.call_count, 3)
                        save.assert_not_called()
                        rebuild.assert_not_called()
                        self.assertIs(dialog.tree.currentItem(), item)
                        self.assertEqual(dialog.tree.selectedItems(), [item])
                        self.assertEqual(
                            dialog.tree.verticalScrollBar().value(), scroll
                        )
                finally:
                    dialog.cleanup()
                    delete(dialog)

    def test_main_dialogs_read_local_and_remote_usage_at_action_time(self):
        for sql in (False, True):
            for kind, method in (
                ("employees", "open_employees_dialog"),
                ("pay_classes", "open_payroll_classes_dialog"),
                ("job_statuses", "open_job_statuses_dialog"),
            ):
                with self.subTest(sql=sql, kind=kind):
                    data = ProjectDataService(Mock())
                    employees = [Employee("1", first_name="Same", pay_class_uid="1")]
                    pay_classes = [PayClass("1", "Same")]
                    statuses = [JobStatus("1", "Same")]
                    data.replace_database_settings(
                        "db",
                        employees=employees,
                        pay_classes=pay_classes,
                        job_statuses=statuses,
                        used_employee_uids={"1"},
                        used_job_status_uids={"1"},
                    )
                    reader = Mock()
                    reader.get_master_data_uids_in_use.side_effect = (
                        data.get_master_data_uids_in_use
                    )
                    reader.get_employees_and_pay_classes.return_value = (
                        employees,
                        pay_classes,
                    )
                    reader.get_job_statuses.return_value = statuses
                    coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
                    coordinator._editable_master_data_file_path = lambda: "db"
                    coordinator._project_write_service = Mock()
                    coordinator._project_write_service.uses_sql_collaboration_mutations.return_value = (
                        sql
                    )
                    coordinator._project_read_service = ProjectReadService(reader)
                    coordinator.project_data = data
                    coordinator.ui_state_manager = SimpleNamespace(
                        get_selected_bid_ref=lambda: None
                    )
                    coordinator._icon_provider = Mock()
                    coordinator._workspace_state_model = make_workspace_state_model()
                    coordinator.main_window = None
                    coordinator.event_bus = Mock()

                    def interact(dialog, *_args, **_kwargs):
                        try:
                            reader.get_master_data_uids_in_use.assert_not_called()
                            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
                            item = dialog.tree.currentItem()
                            # Same authoritative replacement used by SQL reconciliation;
                            # local read queries observe the corresponding current rows.
                            data.replace_database_settings(
                                "db",
                                employees=[Employee("1", first_name="Same")],
                                used_employee_uids=set(),
                                used_job_status_uids=set(),
                            )
                            with patch.object(
                                QtWidgets.QMessageBox,
                                "question",
                                return_value=QtWidgets.QMessageBox.StandardButton.No,
                            ) as question, patch.object(
                                QtWidgets.QMessageBox, "warning"
                            ) as warning:
                                dialog._on_delete()
                                question.assert_called_once()
                                warning.assert_not_called()
                                data.replace_database_settings(
                                    "db",
                                    employees=employees,
                                    used_employee_uids={"1"},
                                    used_job_status_uids={"1"},
                                )
                                dialog._on_delete()
                                warning.assert_called_once()
                                self.assertIs(dialog.tree.currentItem(), item)
                            self.assertEqual(
                                reader.get_master_data_uids_in_use.call_count,
                                0 if sql else 2,
                            )
                        finally:
                            dialog.cleanup()
                            delete(dialog)

                    coordinator._exec_with_collaboration_lease = interact
                    with patch(
                        "ost_visualizer.presentation.coordinators.ui_event_coordinator.ModalEditLeaseSession"
                    ):
                        if method == "open_employees_dialog":
                            coordinator.open_employees_dialog()
                        elif method == "open_payroll_classes_dialog":
                            coordinator.open_payroll_classes_dialog()
                        else:
                            coordinator.open_job_statuses_dialog()

    def test_strict_mdb_usage_reuses_role_parsers_and_propagates_failure(self):
        reader = SettingsReaderMixin()
        connection = MagicMock()
        reader._connection = Mock(return_value=nullcontext(connection))
        reader._parse_used_employee_uids = Mock(return_value={"11"})
        reader._parse_used_job_status_uids = Mock(return_value={"12"})
        schema = Mock()
        schema.optional_table_missing.return_value = False
        schema.column_exists.return_value = True
        reader._schema = Mock(return_value=schema)
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(13,), (None,)]
        service = ProjectReadService(reader)
        self.assertEqual(service.get_master_data_uids_in_use("db", "employees"), {"11"})
        reader._parse_used_employee_uids.assert_called_once_with(connection)
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "job_statuses"), {"12"}
        )
        reader._parse_used_job_status_uids.assert_called_once_with(connection)
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "pay_classes"), {"13"}
        )
        self.assertIn(
            "[PayClassUID] FROM [Employees]", cursor.execute.call_args.args[0]
        )
        schema.column_exists.return_value = False
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "pay_classes"), set()
        )
        reader._connection.side_effect = RuntimeError("read failed")
        for kind in ("employees", "job_statuses", "pay_classes"):
            with self.assertRaisesRegex(RuntimeError, "read failed"):
                service.get_master_data_uids_in_use("db", kind)

    def test_delete_other_selected_row_preserves_current_uid(self):
        for cls, kwargs in (
            (EmployeesDialog, {"employees": [Employee("1"), Employee("2")]}),
            (
                PayrollClassListDialog,
                {"pay_classes": [PayClass("1", "Same"), PayClass("2", "Same")]},
            ),
            (
                JobStatusesDialog,
                {"job_statuses": [JobStatus("1", "Same"), JobStatus("2", "Same")]},
            ),
        ):
            with self.subTest(dialog=cls.__name__):
                usage = Mock(return_value=set())
                dialog = cls(
                    Mock(), make_workspace_state_model(), used_uids_fn=usage, **kwargs
                )
                try:
                    first, current = dialog.tree.topLevelItem(
                        0
                    ), dialog.tree.topLevelItem(1)
                    first.setSelected(True)
                    dialog.tree.setCurrentItem(
                        current, 0, QtCore.QItemSelectionModel.SelectionFlag.NoUpdate
                    )
                    with patch.object(
                        QtWidgets.QMessageBox,
                        "question",
                        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
                    ):
                        dialog._on_delete()
                    self.assertIs(dialog.tree.currentItem(), current)
                    self.assertEqual(dialog.tree.topLevelItemCount(), 1)
                    usage.assert_called_once()
                finally:
                    dialog.cleanup()
                    delete(dialog)

    def test_cover_sheet_nested_editors_keep_live_usage_queries(self):
        employee_usage, pay_usage, status_usage = (
            Mock(return_value={"1"}) for _ in range(3)
        )
        data = CoverSheetData(
            "bid",
            "1",
            "Job",
            "1",
            "",
            "",
            "1",
            "",
            employees=[Employee("1", first_name="Same", pay_class_uid="1")],
            pay_classes=[PayClass("1", "Same")],
            job_statuses=[JobStatus("1", "Same")],
        )
        parent = CoverSheetDialog(
            Mock(),
            None,
            data,
            make_workspace_state_model(),
            employee_usage_fn=employee_usage,
            pay_class_usage_fn=pay_usage,
            job_status_usage_fn=status_usage,
        )
        parent.edit_project_name.setText("Unsaved job")

        def check(dialog, usage):
            usage.assert_not_called()
            dialog.tree.setCurrentItem(dialog.tree.topLevelItem(0))
            item = dialog.tree.currentItem()
            with patch.object(
                QtWidgets.QMessageBox, "warning"
            ) as warning, patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.No,
            ) as question:
                dialog._on_delete()
                warning.assert_called_once()
                usage.return_value = set()
                dialog._on_delete()
                question.assert_called_once()
                self.assertIs(dialog.tree.currentItem(), item)
            self.assertEqual(usage.call_count, 2)
            return QtWidgets.QDialog.DialogCode.Rejected

        def payroll_exec(dialog):
            return check(dialog, pay_usage)

        def detail_exec(dialog):
            with patch.object(PayrollClassListDialog, "exec", payroll_exec):
                dialog._open_payroll_class_dialog()
            return QtWidgets.QDialog.DialogCode.Rejected

        def employee_exec(dialog):
            check(dialog, employee_usage)
            with patch.object(EmployeeDetailDialog, "exec", detail_exec):
                dialog._on_change()
            return QtWidgets.QDialog.DialogCode.Rejected

        try:
            with patch.object(EmployeesDialog, "exec", employee_exec):
                parent._open_employees_dialog()
            with patch.object(
                JobStatusesDialog, "exec", lambda dialog: check(dialog, status_usage)
            ):
                parent._open_job_statuses_dialog()
            self.assertEqual(parent.edit_project_name.text(), "Unsaved job")
            self.assertEqual(str(parent.combo_estimator.currentData()), "1")
            self.assertEqual(str(parent.combo_job_status.currentData()), "1")
        finally:
            parent.close()
            delete(parent)
            QtCore.QCoreApplication.sendPostedEvents(
                None, QtCore.QEvent.Type.DeferredDelete
            )

    def test_reference_added_after_open_blocks_delete(self):
        for cls, kwargs in (
            (EmployeesDialog, {"employees": [Employee("1")]}),
            (PayrollClassListDialog, {"pay_classes": [PayClass("1", "Same")]}),
            (JobStatusesDialog, {"job_statuses": [JobStatus("1", "Same")]}),
        ):
            with self.subTest(dialog=cls.__name__):
                usage = Mock(return_value=set())
                save = Mock(return_value=True)
                dialog = cls(
                    Mock(),
                    make_workspace_state_model(),
                    used_uids_fn=usage,
                    save_fn=save,
                    **kwargs
                )
                try:
                    usage.assert_not_called()
                    item = dialog.tree.topLevelItem(0)
                    dialog.tree.setCurrentItem(item)
                    usage.return_value = {"1"}
                    with patch.object(
                        QtWidgets.QMessageBox,
                        "question",
                        return_value=QtWidgets.QMessageBox.StandardButton.Yes,
                    ) as question, patch.object(
                        QtWidgets.QMessageBox, "warning"
                    ) as warning:
                        dialog._on_delete()
                        warning.assert_called_once()
                        question.assert_not_called()
                    save.assert_not_called()
                    usage.assert_called_once()
                    self.assertIs(dialog.tree.currentItem(), item)
                    self.assertEqual(dialog.tree.topLevelItemCount(), 1)
                finally:
                    dialog.cleanup()
                    delete(dialog)
