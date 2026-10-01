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
from ost_visualizer.presentation.utils.messagebox import DB_LOCKED_HINT
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
    @staticmethod
    def _handler(window, read_service, selected_bid_ref, *, allowed=True):
        return CoverSheetHandler(
            window=window,
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=read_service,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _file_path: False
            ),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: selected_bid_ref
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: allowed),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )

    def test_cover_sheet_stops_when_content_verification_is_unavailable(self):
        window = object()
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda _file_path, _bid_uid: object(),
            get_employee_uids_in_use=lambda _file_path: set(),
            get_pages_with_takeoffs=lambda _file_path, _bid_uid: set(),
            get_pages_with_delete_content=lambda _file_path, _bid_uid: None,
        )
        handler = self._handler(window, read_service, BidRef("project.mdb", "bid-1"))
        with (
            patch(
                "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
            ) as critical,
            patch(
                "ost_visualizer.presentation.handlers.cover_sheet_handler.CoverSheetDialog",
                side_effect=AssertionError("dialog must not open"),
            ) as dialog_class,
        ):
            handler.open_cover_sheet()
        critical.assert_called_once_with(
            window,
            "Cover Sheet",
            f"Failed to verify page contents. {DB_LOCKED_HINT}",
        )
        dialog_class.assert_not_called()

    def test_cover_sheet_stops_when_cover_sheet_data_is_unavailable(self):
        window = object()
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda _file_path, _bid_uid: None,
            get_pages_with_takeoffs=lambda *_args: self.fail(
                "page contents must not be read without cover sheet data"
            ),
            get_pages_with_delete_content=lambda *_args: self.fail(
                "page contents must not be read without cover sheet data"
            ),
        )
        handler = self._handler(window, read_service, BidRef("project.mdb", "bid-1"))
        with (
            patch(
                "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
            ) as critical,
            patch(
                "ost_visualizer.presentation.handlers.cover_sheet_handler.CoverSheetDialog",
                side_effect=AssertionError("dialog must not open"),
            ) as dialog_class,
        ):
            handler.open_cover_sheet()
        critical.assert_called_once_with(
            window,
            "Cover Sheet",
            f"Failed to load cover sheet data. {DB_LOCKED_HINT}",
        )
        dialog_class.assert_not_called()

    def test_cover_sheet_does_nothing_when_denied_or_without_selected_bid(self):
        read_service = SimpleNamespace(
            get_cover_sheet_data=lambda *_args: self.fail("must not read data")
        )
        cases = (
            ("denied", BidRef("project.mdb", "bid-1"), False),
            ("no selected bid", None, True),
        )
        for label, selected_bid_ref, allowed in cases:
            with self.subTest(label):
                handler = self._handler(
                    object(), read_service, selected_bid_ref, allowed=allowed
                )
                with (
                    patch(
                        "ost_visualizer.presentation.handlers.cover_sheet_handler"
                        ".show_critical"
                    ) as critical,
                    patch(
                        "ost_visualizer.presentation.handlers.cover_sheet_handler"
                        ".CoverSheetDialog",
                        side_effect=AssertionError("dialog must not open"),
                    ),
                ):
                    handler.open_cover_sheet()
                critical.assert_not_called()


class CoverSheetHandlerCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    @staticmethod
    def _expected_blank_page_updates(data, *, sequence, sheet_no):
        return {
            "job_status_uid": data.job_status_uid,
            "job_name": data.job_name,
            "estimator_uid": data.estimator_uid,
            "notes": data.notes,
            "bid_date": data.bid_date,
            "bid_no": data.bid_no,
            "job_id": data.job_id,
            "measure_base": data.measure_base,
            "takeoff_increments": data.takeoff_increments,
            "scale_style": data.scale_style,
            "scale_factor1": data.scale_factor1,
            "scale_factor2": data.scale_factor2,
            "page_width": data.page_width,
            "page_height": data.page_height,
            "pages": [
                {
                    "uid": None,
                    "folder_uid": None,
                    "sequence": sequence,
                    "sheet_no": sheet_no,
                    "name": "",
                    "width": data.page_width,
                    "height": data.page_height,
                    "scale_factor1": data.scale_factor1,
                    "scale_factor2": data.scale_factor2,
                    "show_mode": 0,
                    "index": 1,
                    "multi_page_count": 0,
                    "image_path": "",
                    "overlay_path": "",
                }
            ],
        }

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
        self.assertEqual(
            (queued["database_id"], queued["bid_uid"], queued["updates"]),
            ("database", "7", {"notes": "updated"}),
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

    def test_cover_sheet_async_save_reports_each_terminal_failure_once(self):
        for status in (
            MutationOutcomeStatus.REJECTED,
            MutationOutcomeStatus.CONFLICT,
            MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
            MutationOutcomeStatus.CANCELLED_BEFORE_START,
        ):
            with self.subTest(status=status):
                queued = {}
                completions = []
                errors = []

                class WriteService:
                    @staticmethod
                    def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                        queued["callback"] = callback
                        return 1

                handler = CoverSheetHandler.__new__(CoverSheetHandler)
                handler.window = None
                handler._write_service = WriteService()
                handler._ui_event_coordinator = SimpleNamespace(
                    present_queued_mutation_error=lambda database_id, title, result: (
                        errors.append((database_id, title, result.outcome_status))
                    )
                )
                self.assertTrue(
                    handler._save_cover_sheet_async(
                        BidRef("database", "7"), {}, completions.append
                    )
                )
                queued["callback"](
                    QueuedMutationResult(
                        database_id="database",
                        runtime_generation=1,
                        operation_id="00000000-0000-0000-0000-000000000001",
                        outcome_status=status,
                    )
                )
                self.assertEqual(completions, [False])
                self.assertEqual(errors, [("database", "Cover Sheet", status)])

    def test_cover_sheet_async_save_reports_queue_rejection_without_completion(self):
        completions = []

        class WriteService:
            @staticmethod
            def queue_cover_sheet_save(database_id, bid_uid, updates, callback):
                raise RuntimeError("queue is closed")

        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = object()
        handler._write_service = WriteService()
        with patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical:
            started = handler._save_cover_sheet_async(
                BidRef("database", "7"), {}, completions.append
            )
        self.assertFalse(started)
        self.assertEqual(completions, [])
        critical.assert_called_once_with(
            handler.window, "Cover Sheet", "queue is closed"
        )

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
        self.assertEqual(
            queued[0][2],
            self._expected_blank_page_updates(data, sequence=2, sheet_no="00001"),
        )

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
        self.assertEqual(
            saved[0][2],
            self._expected_blank_page_updates(data, sequence=2, sheet_no="00001"),
        )

    def test_add_blank_page_numbers_after_highest_numeric_sheet_in_nested_folders(
        self,
    ):
        saved = []
        data = _path_support__cover_sheet_data()
        template = data.pages_without_folder[0]

        def page(uid, sheet_no):
            return CoverSheetPage(
                uid=uid,
                sheet_no=sheet_no,
                name=uid,
                width=template.width,
                height=template.height,
                scale_factor1=template.scale_factor1,
                scale_factor2=template.scale_factor2,
                image_path="",
                overlay_image_path="",
                index=1,
                show_mode=0,
            )

        data.pages_without_folder = [page("root", "00003"), page("note", "A-101")]
        data.folders = {
            "f1": CoverSheetFolder(
                uid="f1",
                name="Folder",
                pages=[page("in-folder", " 00011 ")],
                subfolders={
                    "f2": CoverSheetFolder(
                        uid="f2", name="Nested", pages=[page("nested", "00007")]
                    )
                },
            )
        }

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def save_cover_sheet(database_id, bid_uid, updates):
                saved.append(updates)
                return True

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=SimpleNamespace(is_current_bid_locked=lambda: False),
            project_read_service=SimpleNamespace(
                get_cover_sheet_data=lambda _database_id, _bid_uid: data
            ),
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
        self.assertEqual(saved[0]["pages"][0]["sequence"], 5)
        self.assertEqual(saved[0]["pages"][0]["sheet_no"], "00012")

    def test_add_blank_page_declines_without_saving_for_locked_bid_or_unconfirmed(
        self,
    ):
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        for label, locked, confirmed, allowed in (
            ("locked bid", True, True, True),
            ("not confirmed", False, False, True),
            ("denied", False, True, False),
        ):
            with self.subTest(label):
                handler = CoverSheetHandler(
                    window=object(),
                    icon_provider=_path_support__FakeIconProvider(),
                    project_data_service=SimpleNamespace(
                        is_current_bid_locked=lambda locked=locked: locked
                    ),
                    project_read_service=SimpleNamespace(
                        get_cover_sheet_data=lambda *_args: self.fail("no read")
                    ),
                    project_write_service=SimpleNamespace(
                        uses_sql_collaboration_mutations=lambda _id: self.fail(
                            "no save"
                        )
                    ),
                    infrastructure_provider=SimpleNamespace(),
                    event_bus=SimpleNamespace(),
                    ui_state_manager=SimpleNamespace(
                        get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
                    ),
                    ui_access_manager=SimpleNamespace(
                        is_allowed=lambda _feature, allowed=allowed: allowed
                    ),
                    deferred_persistence_manager=SimpleNamespace(),
                    workspace_state_model=make_workspace_state_model(),
                )
                with (
                    mock.patch.object(module, "confirm", return_value=confirmed),
                    mock.patch.object(module, "show_critical") as critical,
                ):
                    self.assertFalse(handler.add_blank_page_from_takeoff_tab())
                critical.assert_not_called()

    def test_mdb_add_blank_page_reports_save_failure(self):
        data = _path_support__cover_sheet_data()
        window = object()

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def save_cover_sheet(database_id, bid_uid, updates):
                return False

        handler = CoverSheetHandler(
            window=window,
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=SimpleNamespace(is_current_bid_locked=lambda: False),
            project_read_service=SimpleNamespace(
                get_cover_sheet_data=lambda _database_id, _bid_uid: data
            ),
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

        with (
            mock.patch.object(module, "confirm", return_value=True),
            mock.patch.object(module, "show_critical") as critical,
        ):
            self.assertFalse(handler.add_blank_page_from_takeoff_tab())
        critical.assert_called_once_with(
            window, "Add Page", f"Failed to add page. {DB_LOCKED_HINT}"
        )

    def test_unlocked_sql_cover_sheet_invokes_async_save_instead_of_returning_it(self):
        queued = []
        callback_results = []
        nested_results = []
        requested_leases = []
        released_leases = []
        data = _path_support__cover_sheet_data()
        data.job_statuses = [SimpleNamespace(uid="status-1")]
        data.employees = [SimpleNamespace(uid="employee-1")]
        data.pay_classes = [SimpleNamespace(uid="pay-class-1")]

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
        self.assertEqual(
            queued[0][:3],
            (
                "sql-database",
                None,
                {"new": [], "updated": [], "deleted_uids": ["status-1"]},
            ),
        )
        initial_lease = requested_leases[0]
        self.assertEqual(initial_lease.database_id, "sql-database")
        self.assertEqual(initial_lease.operation_id, "CoverSheetDialog")
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in initial_lease.resources
            },
            {
                ("cover_sheet", "7"),
                ("bid", "7"),
                ("job_statuses_collection", "database"),
                ("employees_collection", "database"),
                ("pay_classes_collection", "database"),
                ("areas_collection", "7"),
                *(("job_status", str(item.uid)) for item in data.job_statuses),
                *(("employee", str(item.uid)) for item in data.employees),
                *(("pay_class", str(item.uid)) for item in data.pay_classes),
            },
        )
        self.assertEqual(
            {
                (resource.resource_type, resource.resource_id)
                for resource in initial_lease.dependency_resources
            },
            {
                ("pages_collection", "7"),
                ("conditions_collection", "7"),
                ("takeoffs_collection", "7"),
                ("annotations_collection", "7"),
            },
        )
        self.assertTrue(FakeDialog.instance.deleted)

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
        self.assertEqual(requested[0].database_id, "sql-database")
        self.assertEqual(requested[0].operation_id, "NewProjectCoverSheetDialog")
        self.assertEqual(
            resource_keys,
            {
                ("project_bids", "project-1"),
                ("job_statuses_collection", "database"),
                ("employees_collection", "database"),
                ("pay_classes_collection", "database"),
                ("job_status", "status-1"),
                ("employee", "employee-1"),
                ("pay_class", "pay-class-1"),
            },
        )
        self.assertEqual(
            set(requested[0].dependency_resources),
            {
                ResourceRef("default_layers_collection", "database"),
                ResourceRef("project", "project-1"),
            },
        )
        self.assertEqual(released, requested)

    def test_new_project_without_known_project_leases_orphan_bids_and_no_project_dependency(
        self,
    ):
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler._ui_event_coordinator = SimpleNamespace()
        handler._event_bus = EventBus()
        data = _path_support__cover_sheet_data()
        requested = []
        handler._ui_event_coordinator.request_collaboration_edit = (
            lambda database_id, resources, callback, **kwargs: requested.append(
                (resources, kwargs["dependency_resources"])
            )
        )
        session = handler.create_new_bid_lease_session("sql-database", None, data)
        session.request_initial(lambda _result: None)
        session.close()
        resources, dependencies = requested[0]
        self.assertIn(ResourceRef("project_bids", "orphan"), resources)
        self.assertEqual(
            set(dependencies), {ResourceRef("default_layers_collection", "database")}
        )

    def test_new_project_lease_requires_collaboration_coordinator(self):
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler._ui_event_coordinator = None
        handler._event_bus = EventBus()
        with self.assertRaises(RuntimeError):
            handler.create_new_bid_lease_session(
                "sql-database", "project-1", _path_support__cover_sheet_data()
            )

    def _open_mdb_cover_sheet(self, *, save_result, locked, dialog_result):
        saved = []
        status_updates = []
        window = object()
        data = _path_support__cover_sheet_data()
        data.job_status_uid = "status-1"

        class WriteService:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return False

            @staticmethod
            def save_cover_sheet(database_id, bid_uid, updates):
                saved.append((database_id, bid_uid, updates))
                return save_result

            @staticmethod
            def update_bid_job_status(database_id, bid_uid, job_status_uid):
                status_updates.append((database_id, bid_uid, job_status_uid))
                return save_result

        class FakeDialog(_path_support__FakeCoverSheetDialog):
            @staticmethod
            def get_updates():
                return {"job_status_uid": "status-2", "notes": "Updated"}

        handler = CoverSheetHandler(
            window=window,
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=SimpleNamespace(
                is_current_bid_locked=lambda: locked,
                get_assigned_area_uids_with_stored_takeoff=lambda: set(),
                get_master_data_uids_in_use=lambda _id, _kind: set(),
            ),
            project_read_service=SimpleNamespace(
                get_cover_sheet_data=lambda _database_id, _bid_uid: data,
                get_pages_with_takeoffs=lambda _database_id, _bid_uid: set(),
                get_pages_with_delete_content=lambda _database_id, _bid_uid: set(),
            ),
            project_write_service=WriteService(),
            infrastructure_provider=SimpleNamespace(
                get_pdf_page_sizes=lambda _path: []
            ),
            event_bus=EventBus(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef("bid.mdb", "7")
            ),
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True, has_license=lambda: True
            ),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _database_id: True
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with (
            mock.patch.object(module, "CoverSheetDialog", FakeDialog),
            mock.patch.object(
                module, "exec_with_ost_blocking", return_value=dialog_result
            ),
            mock.patch.object(module, "show_critical") as critical,
        ):
            handler.open_cover_sheet()
        return saved, status_updates, critical, window, FakeDialog.instance

    def test_mdb_cover_sheet_accepted_saves_dialog_updates_synchronously(self):
        saved, status_updates, critical, _window, dialog = self._open_mdb_cover_sheet(
            save_result=True,
            locked=False,
            dialog_result=QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(
            saved,
            [
                (
                    "bid.mdb",
                    "7",
                    {"job_status_uid": "status-2", "notes": "Updated"},
                )
            ],
        )
        self.assertEqual(status_updates, [])
        critical.assert_not_called()
        self.assertTrue(dialog.deleted)

    def test_mdb_cover_sheet_rejected_saves_nothing(self):
        saved, status_updates, critical, _window, dialog = self._open_mdb_cover_sheet(
            save_result=True,
            locked=False,
            dialog_result=QtWidgets.QDialog.DialogCode.Rejected,
        )
        self.assertEqual((saved, status_updates), ([], []))
        critical.assert_not_called()
        self.assertTrue(dialog.deleted)

    def test_mdb_cover_sheet_save_failure_is_reported(self):
        saved, _status_updates, critical, window, dialog = self._open_mdb_cover_sheet(
            save_result=False,
            locked=False,
            dialog_result=QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(len(saved), 1)
        critical.assert_called_once_with(
            window,
            "Cover Sheet",
            f"Failed to save cover sheet data. {DB_LOCKED_HINT}",
        )
        self.assertTrue(dialog.deleted)

    def test_mdb_locked_cover_sheet_saves_only_the_job_status(self):
        saved, status_updates, critical, _window, _dialog = self._open_mdb_cover_sheet(
            save_result=True,
            locked=True,
            dialog_result=QtWidgets.QDialog.DialogCode.Accepted,
        )
        self.assertEqual(saved, [])
        self.assertEqual(status_updates, [("bid.mdb", "7", "status-2")])
        critical.assert_not_called()

    def test_denied_initial_sql_lease_closes_session_and_never_opens_dialog(self):
        data = _path_support__cover_sheet_data()
        requested = []

        class TrackingEventBus(EventBus):
            def __init__(self):
                super().__init__()
                self.live_subscriptions = []

            def subscribe(self, event_type, callback):
                super().subscribe(event_type, callback)
                self.live_subscriptions.append((event_type, callback))

            def unsubscribe(self, event_type, callback):
                super().unsubscribe(event_type, callback)
                self.live_subscriptions.remove((event_type, callback))

        event_bus = TrackingEventBus()

        class ProjectData:
            @staticmethod
            def get_cover_sheet_snapshot(_database_id, _bid_uid):
                return data

            @staticmethod
            def get_job_status_snapshot(_database_id):
                return []

            @staticmethod
            def get_employee_snapshot(_database_id):
                return []

            @staticmethod
            def get_pay_class_snapshot(_database_id):
                return []

            @staticmethod
            def get_used_job_status_uids(_database_id):
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

        class FakeDialog(_path_support__FakeCoverSheetDialog):
            pass

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
                requested.append(database_id)
                callback(EditLeaseResult(False, "Another user is editing."))

            @staticmethod
            def end_collaboration_edit(handle):
                raise AssertionError("a denied lease has no handle to release")

        handler = CoverSheetHandler(
            window=object(),
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=ProjectData(),
            project_read_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: True
            ),
            infrastructure_provider=SimpleNamespace(
                get_pdf_page_sizes=lambda _path: []
            ),
            event_bus=event_bus,
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
        handler.set_ui_event_coordinator(LeaseCoordinator())
        from ost_visualizer.presentation.handlers import cover_sheet_handler as module

        with (
            mock.patch.object(module, "CoverSheetDialog", FakeDialog),
            mock.patch.object(
                module,
                "exec_with_ost_blocking",
                side_effect=AssertionError("denied lease must not open the dialog"),
            ),
        ):
            handler.open_cover_sheet()
        self.assertEqual(requested, ["sql-database"])
        self.assertTrue(FakeDialog.instance.deleted)
        self.assertEqual(event_bus.live_subscriptions, [])
