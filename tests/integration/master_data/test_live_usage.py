import sqlite3
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
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
from ost_visualizer.infrastructure.events.event_bus import EventBus
from tests.helpers.mdb.import_export_support import (
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteSchema as _import_export_support__SqliteSchema,
)
from tests.helpers.workspace_state import make_workspace_state_model
from tests.presentation.dialogs.master_data_support import (
    FakeIconProvider as _master_data_support_FakeIconProvider,
)


class _CountingMasterDataReader:
    """Explicit reader fake: usage is read through the data service, counted."""

    def __init__(self, data, employees, pay_classes, statuses):
        self.usage_calls = 0
        self._data = data
        self._employees = employees
        self._pay_classes = pay_classes
        self._statuses = statuses

    def get_master_data_uids_in_use(self, file_path, kind):
        self.usage_calls += 1
        return self._data.get_master_data_uids_in_use(file_path, kind)

    def get_employees_and_pay_classes(self, _file_path):
        return self._employees, self._pay_classes

    def get_job_statuses(self, _file_path):
        return self._statuses


class _SqliteSettingsReader(SettingsReaderMixin):
    """SettingsReaderMixin over an sqlite connection (Access stand-in)."""

    def __init__(self, connection):
        self._connection_ref = connection
        self.failure = None

    @contextmanager
    def _connection(self, _file_path):
        if self.failure is not None:
            raise self.failure
        with _import_export_support__SqliteConnection(
            self._connection_ref
        ) as connection:
            yield connection

    def _schema(self, _connection):
        return _import_export_support__SqliteSchema(self._connection_ref)


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
                    _master_data_support_FakeIconProvider(),
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
                    data = ProjectDataService(None)
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
                    reader = _CountingMasterDataReader(
                        data, employees, pay_classes, statuses
                    )
                    coordinator = UIEventCoordinator.__new__(UIEventCoordinator)
                    coordinator._editable_master_data_file_path = lambda: "db"
                    coordinator._project_write_service = SimpleNamespace(
                        uses_sql_collaboration_mutations=lambda _file_path, sql=sql: sql
                    )
                    coordinator._project_read_service = ProjectReadService(reader)
                    coordinator.project_data = data
                    coordinator.ui_state_manager = SimpleNamespace(
                        get_selected_bid_ref=lambda: None
                    )
                    coordinator._icon_provider = _master_data_support_FakeIconProvider()
                    coordinator._workspace_state_model = make_workspace_state_model()
                    coordinator.main_window = None
                    coordinator.event_bus = EventBus()
                    interacted = []

                    def interact(dialog, *_args, **_kwargs):
                        interacted.append(dialog)
                        try:
                            self.assertEqual(reader.usage_calls, 0)
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
                            self.assertEqual(reader.usage_calls, 0 if sql else 2)
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
                    self.assertEqual(len(interacted), 1)

    def test_strict_mdb_usage_reuses_role_parsers_and_propagates_failure(self):
        # Real SettingsReaderMixin queries run against an in-memory sqlite
        # stand-in for the Access database (the driver itself is not used).
        database = sqlite3.connect(":memory:")
        database.execute(
            "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER, JobStatusUID INTEGER)"
        )
        database.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?, ?, ?)",
            [
                (1, 11, None, 14, 12),
                (2, 11, 15, None, None),
                (3, None, None, None, 12),
            ],
        )
        database.execute("CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)")
        database.executemany(
            "INSERT INTO Employees VALUES (?, ?)", [(1, 13), (2, 13), (3, None)]
        )
        reader = _SqliteSettingsReader(database)
        service = ProjectReadService(reader)
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "employees"),
            {"11", "14", "15"},
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "job_statuses"), {"12"}
        )
        self.assertEqual(
            service.get_master_data_uids_in_use("db", "pay_classes"), {"13"}
        )
        with self.assertRaisesRegex(ValueError, "Unsupported master-data usage kind"):
            service.get_master_data_uids_in_use("db", "layers")
        # Older databases without the referencing columns report no usage.
        legacy = sqlite3.connect(":memory:")
        legacy.execute("CREATE TABLE Bids (UID INTEGER)")
        legacy.execute("CREATE TABLE Employees (UID INTEGER)")
        legacy_service = ProjectReadService(_SqliteSettingsReader(legacy))
        for kind in ("employees", "job_statuses", "pay_classes"):
            self.assertEqual(
                legacy_service.get_master_data_uids_in_use("db", kind), set()
            )
        # A read failure is propagated, never reported as "not in use".
        reader.failure = RuntimeError("read failed")
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
                    _master_data_support_FakeIconProvider(),
                    make_workspace_state_model(),
                    used_uids_fn=usage,
                    **kwargs
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
            _master_data_support_FakeIconProvider(),
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
            # Each nested editor ran its own checks (two usage queries each).
            self.assertEqual(employee_usage.call_count, 2)
            self.assertEqual(pay_usage.call_count, 2)
            self.assertEqual(status_usage.call_count, 2)
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
                    _master_data_support_FakeIconProvider(),
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
