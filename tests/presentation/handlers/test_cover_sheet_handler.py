from ost_visualizer.presentation.handlers.cover_sheet_handler import CoverSheetHandler
from ost_visualizer.domain.entities.identity_refs import BidRef
from unittest.mock import Mock, patch
from types import SimpleNamespace
import unittest
import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    DatabaseMutationResult,
    EditLeaseHandle,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.domain.entities.cover_sheet import (
    CoverSheetData,
    CoverSheetFolder,
    CoverSheetPage,
    JobStatus,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from PySide6 import QtCore, QtGui, QtWidgets
from tests.helpers.workspace_state import (
    make_workspace_state_model,
    with_workspace_state,
)
from tests.presentation.dialogs.cover_sheet.path_support import (
    _FakeCoverSheetDialog as _path_support__FakeCoverSheetDialog,
    _FakeIconProvider as _path_support__FakeIconProvider,
    _app as _path_support__app,
    _cover_sheet_data as _path_support__cover_sheet_data,
)


class CoverSheetContentReadFailureTests(unittest.TestCase):
    def test_cover_sheet_stops_when_content_verification_is_unavailable(self):
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda _file_path, _bid_uid: object(),
            get_employee_uids_in_use=lambda _file_path: set(),
            get_pages_with_takeoffs=lambda _file_path, _bid_uid: set(),
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None,
        )
        handler = CoverSheetHandler(
            window=object(),
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=read_service,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: False
            ),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("project.mdb", "bid-1")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical, patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.CoverSheetDialog",
            side_effect=AssertionError("dialog must not open"),
        ):
            handler.open_cover_sheet()
        critical.assert_called_once()


class CoverSheetHandlerCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_cover_sheet_async_save_waits_for_recovered_terminal_result(self):
        queued = {}
        completions = []
        errors = []

        class WriteService:
            @staticmethod
            def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                queued.update(
                    database_id=database_id,
                    bid_uid=bid_uid,
                    updates=updates,
                    callback=callback,
                )
                return 1

        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = None
        handler._write_service = WriteService()
        handler._ui_event_coordinator = SimpleNamespace(
            present_queued_mutation_error=lambda database_id, title, result: (
                errors.append((database_id, title, result))
            )
        )
        self.assertTrue(
            handler._save_cover_sheet_async(
                BidRef("database", "7"),
                {"notes": "updated"},
                completions.append,
            )
        )
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            queued["callback"](
                QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=status,
                    commit_attempted=True,
                )
            )
        self.assertEqual(completions, [])
        self.assertEqual(errors, [])
        queued["callback"](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(completions, [True])
        self.assertEqual(errors, [])

    def test_sql_add_blank_page_uses_hydrated_cover_sheet_without_qt_thread_read(self):
        queued = []
        data = _path_support__cover_sheet_data()

        class ProjectData:
            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_cover_sheet_snapshot(database_id, bid_uid):
                self.assertEqual((database_id, bid_uid), ("sql-database", "7"))
                return data

        class ReadService:
            @staticmethod
            def get_cover_sheet_data(*_args):
                raise AssertionError("SQL cover-sheet reads must use hydrated state")

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                queued.append((database_id, bid_uid, updates, callback))
                return 1

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(),
            event_bus=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("sql-database", "7")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(module, "confirm", return_value=True):
            self.assertTrue(handler.add_blank_page_from_takeoff_tab())
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0][:2], ("sql-database", "7"))
        self.assertEqual(len(queued[0][2]["pages"]), 1)

    def test_mdb_add_blank_page_uses_cover_sheet_save_workflow(self):
        saved = []
        data = _path_support__cover_sheet_data()
        data.job_status_uid = ""
        data.estimator_uid = ""
        data.bid_date = ""
        data.bid_no = ""

        class ProjectData:
            @staticmethod
            def is_current_bid_locked():
                return False

        class ReadService:
            @staticmethod
            def get_cover_sheet_data(database_id, bid_uid):
                self.assertEqual((database_id, bid_uid), ("bid.mdb", "7"))
                return data

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def save_cover_sheet(database_id, bid_uid, updates):
                saved.append((database_id, bid_uid, updates))
                return True

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=ReadService(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(),
            event_bus=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _database_id: True
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with mock.patch.object(module, "confirm", return_value=True):
            self.assertTrue(handler.add_blank_page_from_takeoff_tab())
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0][:2], ("bid.mdb", "7"))
        self.assertEqual(saved[0][2]["job_status_uid"], "")
        self.assertEqual(len(saved[0][2]["pages"]), 1)

    def test_unlocked_sql_cover_sheet_invokes_async_save_instead_of_returning_it(self):
        queued = []
        callback_results = []
        nested_results = []
        requested_leases = []
        released_leases = []
        data = _path_support__cover_sheet_data()

        class ProjectData:
            @staticmethod
            def get_cover_sheet_snapshot(_database_id, _bid_uid):
                return data

            @staticmethod
            def get_job_status_snapshot(_database_id):
                return data.job_statuses

            @staticmethod
            def get_employee_snapshot(_database_id):
                return data.employees

            @staticmethod
            def get_pay_class_snapshot(_database_id):
                return data.pay_classes

            @staticmethod
            def get_used_job_status_uids(_database_id):
                return set()

            @staticmethod
            def get_used_employee_uids(_database_id):
                return set()

            @staticmethod
            def get_bid_area_snapshot():
                return []

            @staticmethod
            def get_all_pages():
                return []

            @staticmethod
            def get_page_delete_content_snapshot(_database_id, _bid_uid):
                return set()

            @staticmethod
            def is_current_bid_locked():
                return False

            @staticmethod
            def get_assigned_area_uids_with_stored_takeoff():
                return set()

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_cover_sheet_save(
                database_id,
                bid_uid,
                updates,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append(
                    (database_id, bid_uid, updates, callback, edit_lease_handle)
                )
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="49350e91-a3b8-42fa-b6f4-9a30dd997516",
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        authoritative_result=AuthoritativeMutationResult(),
                    )
                )
                return 1

            @staticmethod
            def queue_job_statuses_save(
                database_id,
                changes,
                callback,
                *,
                edit_lease_handle,
            ):
                queued.append((database_id, None, changes, callback, edit_lease_handle))
                callback(
                    QueuedMutationResult(
                        database_id=database_id,
                        runtime_generation=1,
                        operation_id="28ff5cd9-3cdb-4af0-9d6a-6ea5097ea887",
                        outcome_status=MutationOutcomeStatus.COMMITTED,
                        authoritative_result=AuthoritativeMutationResult(
                            affected_families=("job_statuses",)
                        ),
                    )
                )
                return 1

        class FakeDialog(_path_support__FakeCoverSheetDialog):
            pass

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=SimpleNamespace(),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(
                get_pdf_page_sizes=lambda _path: []
            ),
            event_bus=EventBus(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("sql-database", "7")
            ),
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True,
                has_license=lambda: True,
            ),
            deferred_persistence_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )

        class LeaseCoordinator:
            @staticmethod
            def request_collaboration_edit(
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id=f"draft-{len(requested_leases) + 1}",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=resources,
                    dependency_resources=dependency_resources,
                )
                requested_leases.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(handle):
                released_leases.append(handle)

        handler.set_ui_event_coordinator(LeaseCoordinator())
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        def execute_dialog(dialog, _event_bus):
            nested_save = dialog.async_save_functions["save_job_statuses_async_fn"]
            callback_results.append(
                nested_save(
                    {
                        "new": [],
                        "updated": [],
                        "deleted_uids": ["status-1"],
                    },
                    lambda success, mapping: nested_results.append((success, mapping)),
                )
            )
            callback_results.append(
                dialog.save_async({"notes": "Updated"}, lambda _success: None)
            )
            return QtWidgets.QDialog.DialogCode.Rejected

        with (
            mock.patch.object(module, "CoverSheetDialog", FakeDialog),
            mock.patch.object(
                module, "exec_with_ost_blocking", side_effect=execute_dialog
            ),
        ):
            handler.open_cover_sheet()
        self.assertEqual(callback_results, [True, True])
        self.assertEqual(nested_results, [(True, {})])
        self.assertEqual(len(queued), 2)
        self.assertEqual(queued[1][:3], ("sql-database", "7", {"notes": "Updated"}))
        self.assertEqual(len(requested_leases), 3)
        self.assertIs(queued[0][4], requested_leases[0])
        self.assertIs(queued[1][4], requested_leases[1])
        self.assertEqual(released_leases, [requested_leases[2]])
        self.assertIn(
            "cover_sheet",
            {resource.resource_type for resource in requested_leases[0].resources},
        )

    def test_new_project_cover_sheet_lease_owns_target_and_nested_master_data(self):
        requested = []
        released = []

        class LeaseCoordinator:
            @staticmethod
            def request_collaboration_edit(
                database_id,
                resources,
                callback,
                *,
                dependency_resources=(),
                operation_id="",
                owning_surface="desktop",
            ):
                handle = EditLeaseHandle(
                    database_id=database_id,
                    draft_id="new-project-dialog",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=resources,
                    dependency_resources=dependency_resources,
                )
                requested.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(handle):
                released.append(handle)

        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler._ui_event_coordinator = LeaseCoordinator()
        handler._event_bus = EventBus()
        data = _path_support__cover_sheet_data()
        data.job_statuses = [SimpleNamespace(uid="status-1")]
        data.employees = [SimpleNamespace(uid="employee-1")]
        data.pay_classes = [SimpleNamespace(uid="pay-class-1")]
        session = handler.create_new_bid_lease_session(
            "sql-database", "project-1", data
        )
        session.request_initial(lambda result: self.assertTrue(result.granted))
        session.close()
        self.assertEqual(len(requested), 1)
        resource_keys = {
            (resource.resource_type, resource.resource_id)
            for resource in requested[0].resources
        }
        self.assertTrue(
            {
                ("project_bids", "project-1"),
                ("job_statuses_collection", "database"),
                ("employees_collection", "database"),
                ("pay_classes_collection", "database"),
                ("job_status", "status-1"),
                ("employee", "employee-1"),
                ("pay_class", "pay-class-1"),
            }.issubset(resource_keys)
        )
        self.assertEqual(
            set(requested[0].dependency_resources),
            {
                ResourceRef("default_layers_collection", "database"),
                ResourceRef("project", "project-1"),
            },
        )
        self.assertEqual(released, requested)
