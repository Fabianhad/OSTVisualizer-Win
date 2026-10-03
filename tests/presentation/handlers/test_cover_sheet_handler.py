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
                    self.assertIs(handler.add_blank_page_from_takeoff_tab(), False)
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
            self.assertIs(handler.add_blank_page_from_takeoff_tab(), False)
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


class CoverSheetBidAreasLockedBidTests(unittest.TestCase):
    """Decisions H2 and H3: the Cover Sheet's Bid Areas save (the shared BidAreasDialog)
    treats the SQL write service's locked-active-Bid refusal as 'not started': it only
    logs (no dialog, no queued-mutation error) and returns False, so the dialog keeps its
    draft and the lease session gets its handle back. Any other queue rejection still
    opens the critical dialog."""

    MODULE = "ost_visualizer.presentation.handlers.cover_sheet_handler"

    def _handler(self, error):
        saves = []

        def queue(*args, **kwargs):
            saves.append((args[:-1], sorted(kwargs)))
            raise error

        errors = []
        handler = CoverSheetHandler(
            window="window",
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=object(),
            project_write_service=SimpleNamespace(queue_bid_areas_save=queue),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        handler._present_mutation_error = lambda *args: errors.append(args)
        return handler, saves, errors

    def test_locked_bid_refusal_is_not_started_and_silent(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )

        bid_ref = BidRef("sql-database", "7")
        for options in ({}, {"edit_lease_handle": object()}):
            with self.subTest(lease=bool(options)):
                handler, saves, errors = self._handler(ActiveBidLockedError())
                completed = []
                with (
                    patch(f"{self.MODULE}.show_critical") as critical,
                    patch(f"{self.MODULE}.logger.warning") as log,
                ):
                    started = handler._save_bid_areas_async(
                        bid_ref,
                        object(),
                        lambda *args: completed.append(args),
                        **options,
                    )
                self.assertIs(started, False)
                self.assertEqual(len(saves), 1)
                self.assertEqual(completed, [])
                self.assertEqual(errors, [])
                critical.assert_not_called()
                self.assertEqual(log.call_count, 1)

    def test_other_queue_rejections_still_open_the_critical_dialog(self):
        handler, saves, errors = self._handler(RuntimeError("The queue is full."))
        with patch(f"{self.MODULE}.show_critical") as critical:
            started = handler._save_bid_areas_async(
                BidRef("sql-database", "7"), object(), lambda *_args: None
            )
        self.assertIs(started, False)
        critical.assert_called_once_with("window", "Bid Areas", "The queue is full.")
        self.assertEqual(errors, [])


class CoverSheetSaveLockedBidTests(unittest.TestCase):
    """Decision Q2: the Cover Sheet save (the whole payload: Bid settings, pages, page
    folders, Apply to all and the deleted page uids are ONE queue_cover_sheet_save)
    treats the SQL write service's locked-active-Bid refusal as 'not started' like the
    Bid Areas save: one warning, no dialog, no queued-mutation error, False, so the
    dialog keeps its draft and the lease session gets its handle back. Any other queue
    rejection still opens the critical dialog."""

    MODULE = "ost_visualizer.presentation.handlers.cover_sheet_handler"
    BID_REF = BidRef("sql-database", "7")

    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def _handler(self, error):
        saves = []

        def queue(*args, **kwargs):
            saves.append((args[:-1], sorted(kwargs)))
            raise error

        errors = []
        handler = CoverSheetHandler(
            window="window",
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=object(),
            project_write_service=SimpleNamespace(queue_cover_sheet_save=queue),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        handler._present_mutation_error = lambda *args: errors.append(args)
        return handler, saves, errors

    def test_locked_bid_refusal_is_not_started_and_silent(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )

        updates = {"job_name": "N", "deleted_page_uids": ["20"], "pages": []}
        for options in ({}, {"edit_lease_handle": object()}):
            with self.subTest(lease=bool(options)):
                handler, saves, errors = self._handler(ActiveBidLockedError())
                completed = []
                with (
                    patch(f"{self.MODULE}.show_critical") as critical,
                    self.assertLogs(self.MODULE, "WARNING") as logs,
                ):
                    started = handler._save_cover_sheet_async(
                        self.BID_REF,
                        updates,
                        lambda *args: completed.append(args),
                        **options,
                    )
                self.assertIs(started, False)
                self.assertEqual(
                    saves, [((("sql-database", "7", updates)), sorted(options))]
                )
                self.assertEqual(completed, [])
                self.assertEqual(errors, [])
                critical.assert_not_called()
                self.assertEqual(
                    logs.output,
                    [
                        f"WARNING:{self.MODULE}:Cover Sheet blocked: the active bid is locked"
                    ],
                )

    def test_other_queue_rejections_still_open_the_critical_dialog(self):
        handler, saves, errors = self._handler(RuntimeError("The queue is full."))
        with patch(f"{self.MODULE}.show_critical") as critical:
            started = handler._save_cover_sheet_async(
                self.BID_REF, {}, lambda *_args: None
            )
        self.assertIs(started, False)
        critical.assert_called_once_with("window", "Cover Sheet", "The queue is full.")
        self.assertEqual(errors, [])

    def test_add_blank_page_refused_by_the_lock_is_silent(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )

        data = _path_support__cover_sheet_data()
        queued = []

        def queue(database_id, bid_uid, updates, callback):
            queued.append((database_id, bid_uid, updates))
            raise ActiveBidLockedError()

        handler = CoverSheetHandler(
            window="window",
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=SimpleNamespace(
                is_current_bid_locked=lambda: False,
                get_cover_sheet_snapshot=lambda _database_id, _bid_uid: data,
            ),
            project_read_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: True,
                queue_cover_sheet_save=queue,
            ),
            infrastructure_provider=SimpleNamespace(),
            event_bus=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: self.BID_REF),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=SimpleNamespace(),
            workspace_state_model=make_workspace_state_model(),
        )
        with (
            patch(f"{self.MODULE}.confirm", return_value=True),
            patch(f"{self.MODULE}.show_critical") as critical,
            self.assertLogs(self.MODULE, "WARNING") as logs,
        ):
            self.assertIs(handler.add_blank_page_from_takeoff_tab(), False)
        self.assertEqual(len(queued), 1)
        critical.assert_not_called()
        self.assertEqual(len(logs.output), 1)

    def test_the_real_dialog_keeps_its_draft_and_lease_after_a_locked_refusal(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.presentation.services.modal_edit_lease_session import (
            ModalEditLeaseSession,
        )
        from tests.presentation.dialogs.cover_sheet.path_support import (
            CoverSheetDialog as RealCoverSheetDialog,
        )

        handle = EditLeaseHandle(
            database_id="sql-database",
            draft_id="draft",
            runtime_generation=1,
            operation_id="CoverSheetDialog",
            owning_surface="main-window-dialog",
            resources=(ResourceRef("cover_sheet", "7", 7),),
        )
        ended = []
        requested = []

        class Owner:
            @staticmethod
            def request_collaboration_edit(_db, _resources, callback, **_options):
                requested.append(callback)
                callback(EditLeaseResult(True, handle=handle))

            @staticmethod
            def end_collaboration_edit(ended_handle):
                ended.append(ended_handle)

        queued = []

        def queue(database_id, bid_uid, updates, callback, *, edit_lease_handle):
            queued.append((database_id, bid_uid, updates, edit_lease_handle))
            raise ActiveBidLockedError()

        handler = CoverSheetHandler(
            window="window",
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=object(),
            project_write_service=SimpleNamespace(queue_cover_sheet_save=queue),
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        errors = []
        handler._present_mutation_error = lambda *args: errors.append(args)
        session = ModalEditLeaseSession(
            Owner(),
            "sql-database",
            (ResourceRef("cover_sheet", "7", 7),),
            "CoverSheetDialog",
            event_bus=EventBus(),
        )
        session.request_initial(lambda _result: None)
        dialog = RealCoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            save_cover_sheet_async_fn=lambda updates, completed: (
                session.submit_mutation(
                    lambda lease, done: handler._save_cover_sheet_async(
                        self.BID_REF,
                        updates,
                        lambda success: done(success, None),
                        edit_lease_handle=lease,
                    ),
                    lambda success, _value: completed(success),
                )
            ),
        )
        session.bind_dialog(dialog)
        try:
            dialog.edit_notes.setPlainText("Draft notes")
            with (
                patch(f"{self.MODULE}.show_critical") as critical,
                patch(f"{self.MODULE}.logger.warning") as log,
            ):
                dialog.accept()
            critical.assert_not_called()
            self.assertEqual(log.call_count, 1)
            self.assertEqual(errors, [])
            self.assertEqual(len(queued), 1)
            self.assertIs(queued[0][3], handle)
            self.assertEqual(queued[0][2]["notes"], "Draft notes")
            # The dialog is interactive again, still open, and keeps its draft.
            self.assertFalse(dialog._operation_pending)
            self.assertFalse(dialog._save_done)
            self.assertFalse(dialog._closed)
            self.assertTrue(dialog.ok_button.isEnabled())
            self.assertEqual(dialog.edit_notes.toPlainText(), "Draft notes")
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            # The lease handle was handed back to the session, not ended.
            self.assertIs(session._handle, handle)
            self.assertEqual(ended, [])
        finally:
            session.close()
            dialog.reject()
            dialog.deleteLater()
        self.assertEqual(ended, [handle])


class CoverSheetBidLockedRejectionTests(unittest.TestCase):
    """Decision B4 at the Cover Sheet handler: a queued Cover Sheet write (or Bid Areas
    save) that the SQL writer refused with REJECTED / bid_locked is handled like the
    queue-time refusal: no dialog (the coordinator's present_queued_mutation_error is
    silent for the reason, and so is the handler's own fallback without a coordinator),
    the save completes False, and the real dialog keeps its draft, stays open and
    interactive and the lease session holds a freshly acquired lease again. A rejection
    WITHOUT the reason keeps its critical dialog. Real handler, real
    CoverSheetDialog/BidAreasDialog, real ModalEditLeaseSession and the real
    present_queued_mutation_error; the write service and the lease owner are fakes."""

    MODULE = "ost_visualizer.presentation.handlers.cover_sheet_handler"
    COORDINATOR = "ost_visualizer.presentation.coordinators.ui_event_coordinator"
    BID_REF = BidRef("sql-database", "7")

    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    @staticmethod
    def _result(bid_locked=True):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            MutationRejectionReason,
        )

        return QueuedMutationResult(
            database_id="sql-database",
            runtime_generation=2,
            operation_id="00000000-0000-4000-8000-0000000000cc",
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="The active bid is locked" if bid_locked else "busy",
            rejection_reason=MutationRejectionReason.BID_LOCKED if bid_locked else None,
        )

    def _handler(self, write_service, *, with_coordinator=True):
        from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
            UIEventCoordinator,
        )

        handler = CoverSheetHandler(
            window="window",
            icon_provider=object(),
            project_data_service=object(),
            project_read_service=object(),
            project_write_service=write_service,
            infrastructure_provider=object(),
            event_bus=object(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            deferred_persistence_manager=object(),
            workspace_state_model=object(),
        )
        prepared = []
        if with_coordinator:
            presenter = UIEventCoordinator.__new__(UIEventCoordinator)
            presenter._is_cleaning_up = False
            presenter.main_window = "main-window"
            presenter._prepare_for_modal_mutation_error = prepared.append
            handler.set_ui_event_coordinator(presenter)
        return handler, prepared

    def test_the_fallback_without_a_coordinator_is_silent_only_for_the_reason(self):
        handler, _prepared = self._handler(object(), with_coordinator=False)
        with patch(f"{self.MODULE}.show_critical") as critical:
            handler._present_mutation_error(
                "sql-database", "Cover Sheet", self._result()
            )
        critical.assert_not_called()
        with patch(f"{self.MODULE}.show_critical") as critical:
            handler._present_mutation_error(
                "sql-database", "Cover Sheet", self._result(bid_locked=False)
            )
        critical.assert_called_once_with("window", "Cover Sheet", "busy")

    def test_every_cover_sheet_save_completes_false_silently_and_once(self):
        saves = {}

        def queued(name):
            def queue(*args, **kwargs):
                saves[name] = args[-1]
                return 1

            return queue

        service = SimpleNamespace(
            queue_cover_sheet_save=queued("cover"),
            queue_bid_areas_save=queued("areas"),
            queue_bid_job_status_update=queued("status"),
            queue_bid_create=queued("create"),
        )
        handler, prepared = self._handler(service)
        completed = []
        handler._save_cover_sheet_async(
            self.BID_REF, {}, lambda *args: completed.append(("cover", args))
        )
        handler._save_bid_areas_async(
            self.BID_REF, [], lambda *args: completed.append(("areas", args))
        )
        handler._save_locked_bid_status_async(
            self.BID_REF,
            "1",
            {"job_status_uid": "2"},
            lambda *args: completed.append(("status", args)),
        )
        handler.create_bid_async(
            "sql-database", "5", {}, lambda *args: completed.append(("create", args))
        )
        self.assertEqual(sorted(saves), ["areas", "cover", "create", "status"])
        with (
            patch(f"{self.MODULE}.show_critical") as critical,
            patch(f"{self.COORDINATOR}.show_critical") as coordinator_critical,
            patch(f"{self.COORDINATOR}.show_warning") as coordinator_warning,
        ):
            for callback in saves.values():
                callback(self._result())
        critical.assert_not_called()
        coordinator_critical.assert_not_called()
        coordinator_warning.assert_not_called()
        self.assertEqual(prepared, [])
        self.assertEqual(
            sorted(completed),
            sorted(
                [
                    ("cover", (False,)),
                    ("areas", (False, None)),
                    ("status", (False,)),
                    ("create", (False,)),
                ]
            ),
        )

    def test_a_cover_sheet_rejected_for_another_reason_keeps_its_critical_dialog(self):
        saves = []
        service = SimpleNamespace(
            queue_cover_sheet_save=lambda *args, **kwargs: saves.append(args[-1]) or 1
        )
        handler, prepared = self._handler(service)
        completed = []
        handler._save_cover_sheet_async(self.BID_REF, {}, completed.append)
        with (
            patch(f"{self.COORDINATOR}.show_warning") as warning,
            patch(f"{self.COORDINATOR}.show_critical") as critical,
        ):
            saves[0](self._result(bid_locked=False))
        warning.assert_called_once_with("main-window", "Cover Sheet", "busy")
        critical.assert_not_called()
        self.assertEqual(prepared, ["sql-database"])
        self.assertEqual(completed, [False])

    def test_the_real_dialog_keeps_its_draft_and_gets_a_lease_after_a_rejection(self):
        from ost_visualizer.infrastructure.events.event_bus import EventBus
        from ost_visualizer.presentation.services.modal_edit_lease_session import (
            ModalEditLeaseSession,
        )
        from tests.presentation.dialogs.cover_sheet.path_support import (
            CoverSheetDialog as RealCoverSheetDialog,
        )

        def lease(name):
            return EditLeaseHandle(
                database_id="sql-database",
                draft_id=name,
                runtime_generation=1,
                operation_id="CoverSheetDialog",
                owning_surface="main-window-dialog",
                resources=(ResourceRef("cover_sheet", "7", 7),),
            )

        first, second = lease("draft-1"), lease("draft-2")
        granted = [first, second]
        ended = []

        class Owner:
            @staticmethod
            def request_collaboration_edit(_db, _resources, callback, **_options):
                callback(EditLeaseResult(True, handle=granted.pop(0)))

            @staticmethod
            def end_collaboration_edit(ended_handle):
                ended.append(ended_handle)

        queued = []
        service = SimpleNamespace(
            queue_cover_sheet_save=lambda database_id, bid_uid, updates, callback, **kw: (
                queued.append((updates, callback, kw)) or 1
            )
        )
        handler, prepared = self._handler(service)
        session = ModalEditLeaseSession(
            Owner(),
            "sql-database",
            (ResourceRef("cover_sheet", "7", 7),),
            "CoverSheetDialog",
            event_bus=EventBus(),
        )
        session.request_initial(lambda _result: None)
        dialog = RealCoverSheetDialog(
            _path_support__FakeIconProvider(),
            None,
            _path_support__cover_sheet_data(),
            save_cover_sheet_async_fn=lambda updates, completed: (
                session.submit_mutation(
                    lambda lease_handle, done: handler._save_cover_sheet_async(
                        self.BID_REF,
                        updates,
                        lambda success: done(success, None),
                        edit_lease_handle=lease_handle,
                    ),
                    lambda success, _value: completed(success),
                )
            ),
        )
        session.bind_dialog(dialog)
        try:
            dialog.edit_notes.setPlainText("Draft notes")
            dialog.accept()
            self.assertEqual(len(queued), 1)
            self.assertIs(queued[0][2]["edit_lease_handle"], first)
            with (
                patch(f"{self.MODULE}.show_critical") as critical,
                patch(f"{self.COORDINATOR}.show_critical") as coordinator_critical,
                patch(f"{self.COORDINATOR}.show_warning") as coordinator_warning,
            ):
                queued[0][1](self._result())
                queued[0][1](self._result())
            critical.assert_not_called()
            coordinator_critical.assert_not_called()
            coordinator_warning.assert_not_called()
            self.assertEqual(prepared, [])
            # still open, interactive and holding its draft
            self.assertFalse(dialog._operation_pending)
            self.assertFalse(dialog._save_done)
            self.assertFalse(dialog._closed)
            self.assertTrue(dialog.ok_button.isEnabled())
            self.assertEqual(dialog.edit_notes.toPlainText(), "Draft notes")
            self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
            # the consumed lease is not ended again; a fresh one is held for the retry
            self.assertEqual(ended, [])
            self.assertIs(session._handle, second)
        finally:
            session.close()
            dialog.reject()
            dialog.deleteLater()
        self.assertEqual(ended, [second])


from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError as _SecondPassActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    EditLeaseLoss,
    MutationRejectionReason,
)
from ost_visualizer.application.events.app_events import AppEvents


class _SecondPassRecordingCoverSheetDialog:
    """Records every constructor argument of the dialog the handler builds."""

    instance = None
    updates = {}

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.deleted = False
        self.rejected = 0
        type(self).instance = self

    def get_updates(self):
        return dict(type(self).updates)

    def reject(self):
        self.rejected += 1

    def deleteLater(self):
        self.deleted = True


class _SecondPassCoverSheetHarness:
    """A real CoverSheetHandler over strict recording fakes. Every read records its
    arguments and returns a value no other call returns, so a swapped argument, a
    wrong backend or a dropped assignment is visible. Fakes (no live SQL Server,
    no real queue): project data, read service, write service, lease owner."""

    def __init__(self, test, *, sql, locked=False):
        self.test = test
        self.sql = sql
        self.locked = locked
        self.file_path = "sql-database" if sql else "bid.mdb"
        self.window = object()
        self.calls = []
        self.queued = []
        self.requested = []
        self.ended = []
        self.presented = []
        self.critical = []
        self.event_bus = EventBus()
        self.data = _path_support__cover_sheet_data()
        self.data.job_status_uid = "status-1"
        self.snapshot_statuses = [SimpleNamespace(uid="s1")]
        self.snapshot_employees = [SimpleNamespace(uid="e1")]
        self.snapshot_pay_classes = [SimpleNamespace(uid="pc1")]
        self.used_statuses = {"s1"}
        self.areas = [SimpleNamespace(uid="a1")]
        self.pages = [
            SimpleNamespace(uid="p1"),
            SimpleNamespace(uid="p2"),
            SimpleNamespace(uid="p3"),
        ]
        self.takeoffs = {"p1": [object()]}
        self.annotations = {"p2": [object()]}
        self.delete_content = {"p3"}
        self.exec_result = QtWidgets.QDialog.DialogCode.Rejected
        self.on_exec = lambda dialog: None
        harness = self

        class ProjectData:
            def get_cover_sheet_snapshot(self, file_path, bid_uid):
                harness.calls.append(("snapshot", (file_path, bid_uid)))
                return harness.data

            def get_job_status_snapshot(self, file_path):
                harness.calls.append(("job_statuses", (file_path,)))
                return harness.snapshot_statuses

            def get_employee_snapshot(self, file_path):
                harness.calls.append(("employees", (file_path,)))
                return harness.snapshot_employees

            def get_pay_class_snapshot(self, file_path):
                harness.calls.append(("pay_classes", (file_path,)))
                return harness.snapshot_pay_classes

            def get_used_job_status_uids(self, file_path):
                harness.calls.append(("used_statuses", (file_path,)))
                return harness.used_statuses

            def get_bid_area_snapshot(self):
                return harness.areas

            def get_all_pages(self):
                return harness.pages

            def get_page_takeoffs(self, page_uid):
                return harness.takeoffs.get(page_uid, [])

            def get_page_annotations(self, page_uid):
                return harness.annotations.get(page_uid, [])

            def get_page_delete_content_snapshot(self, file_path, bid_uid):
                harness.calls.append(("delete_content", (file_path, bid_uid)))
                return set(harness.delete_content)

            def is_current_bid_locked(self):
                return harness.locked

            def get_assigned_area_uids_with_stored_takeoff(self):
                return set()

            def get_master_data_uids_in_use(self, file_path, kind):
                harness.calls.append(("project_data_in_use", (file_path, kind)))
                return {"project-data-" + kind}

        class ReadService:
            def get_cover_sheet_data(self, file_path, bid_uid):
                harness.calls.append(("read_cover_sheet", (file_path, bid_uid)))
                return harness.data

            def get_pages_with_takeoffs(self, file_path, bid_uid):
                harness.calls.append(("read_takeoffs", (file_path, bid_uid)))
                return {"read-takeoff-page"}

            def get_pages_with_delete_content(self, file_path, bid_uid):
                harness.calls.append(("read_delete_content", (file_path, bid_uid)))
                return {"read-delete-page"}

            def get_master_data_uids_in_use(self, file_path, kind):
                harness.calls.append(("read_in_use", (file_path, kind)))
                return {"read-" + kind}

        class WriteService:
            def uses_sql_collaboration_mutations(self, _file_path):
                return harness.sql

            def _queue(self, name, args, callback, kwargs):
                harness.queued.append((name, args, callback, kwargs))
                return len(harness.queued)

            def queue_job_statuses_save(self, file_path, changes, callback, **kw):
                return self._queue("job_statuses", (file_path, changes), callback, kw)

            def queue_employees_save(self, file_path, changes, callback, **kw):
                return self._queue("employees", (file_path, changes), callback, kw)

            def queue_pay_classes_save(self, file_path, changes, callback, **kw):
                return self._queue("pay_classes", (file_path, changes), callback, kw)

            def queue_bid_areas_save(self, file_path, bid_uid, changes, callback, **kw):
                return self._queue(
                    "bid_areas", (file_path, bid_uid, changes), callback, kw
                )

            def queue_cover_sheet_save(
                self, file_path, bid_uid, updates, callback, **kw
            ):
                return self._queue(
                    "cover_sheet", (file_path, bid_uid, updates), callback, kw
                )

            def queue_bid_job_status_update(
                self, file_path, bid_uid, status_uid, callback, **kw
            ):
                return self._queue(
                    "job_status", (file_path, bid_uid, status_uid), callback, kw
                )

            def queue_bid_create(self, file_path, project_uid, updates, callback, **kw):
                return self._queue(
                    "bid_create", (file_path, project_uid, updates), callback, kw
                )

            def save_cover_sheet(self, file_path, bid_uid, updates):
                harness.calls.append(("sync_save", (file_path, bid_uid, updates)))
                return True

            def update_bid_job_status(self, file_path, bid_uid, status_uid):
                harness.calls.append(("sync_status", (file_path, bid_uid, status_uid)))
                return True

        class Coordinator:
            def request_collaboration_edit(
                self,
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
                    draft_id=f"draft-{len(harness.requested) + 1}",
                    runtime_generation=1,
                    operation_id=operation_id,
                    owning_surface=owning_surface,
                    resources=tuple(resources),
                    dependency_resources=tuple(dependency_resources),
                )
                harness.requested.append(handle)
                callback(EditLeaseResult(True, handle=handle))

            def end_collaboration_edit(self, handle):
                harness.ended.append(handle)

            def present_queued_mutation_error(self, file_path, title, result):
                harness.presented.append((file_path, title, result))

        self.coordinator = Coordinator()
        self.read = ReadService()
        self.project_data = ProjectData()
        self.write = WriteService()
        self.handler = CoverSheetHandler(
            window=self.window,
            icon_provider=_path_support__FakeIconProvider(),
            project_data_service=self.project_data,
            project_read_service=self.read,
            project_write_service=self.write,
            infrastructure_provider=SimpleNamespace(
                get_pdf_page_sizes=lambda _path: []
            ),
            event_bus=self.event_bus,
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: BidRef(self.file_path, "7")
            ),
            ui_access_manager=SimpleNamespace(
                is_allowed=lambda _feature: True, has_license=lambda: True
            ),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _database_id: True
            ),
            workspace_state_model=make_workspace_state_model(),
        )
        if sql:
            self.handler.set_ui_event_coordinator(self.coordinator)

    def open(self):
        module = mock.patch.multiple(
            "ost_visualizer.presentation.handlers.cover_sheet_handler",
            CoverSheetDialog=_SecondPassRecordingCoverSheetDialog,
            exec_with_ost_blocking=self._exec,
            show_critical=lambda *args: self.critical.append(args),
        )
        with module:
            self.handler.open_cover_sheet()
        return _SecondPassRecordingCoverSheetDialog.instance

    def _exec(self, dialog, _event_bus):
        self.dialog = dialog
        self.on_exec(dialog)
        return self.exec_result

    def calls_named(self, *names):
        return [call for call in self.calls if call[0] in names]

    def callback(self, status=MutationOutcomeStatus.COMMITTED, **fields):
        return QueuedMutationResult(
            database_id=self.file_path,
            runtime_generation=1,
            operation_id="00000000-0000-4000-8000-00000000009a",
            outcome_status=status,
            **fields,
        )


class CoverSheetHandlerSecondPassTests(unittest.TestCase):
    """Second-pass coverage of CoverSheetHandler: the SQL and Access open paths side by
    side (which service answers which read, with which arguments), the nested master
    data and Bid Areas saves through the dialog's lease session, the Cover Sheet save
    on a Bid that was locked when the dialog opened (job status only), and the
    queue-result handlers. Fakes are strict recording classes; the lease owner is a
    fake that always grants, so no SQL Server semantics are claimed."""

    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_sql_open_reads_the_hydrated_state_of_the_selected_bid_only(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        dialog = harness.open()
        self.assertEqual(
            harness.calls_named(
                "snapshot",
                "job_statuses",
                "employees",
                "pay_classes",
                "used_statuses",
                "delete_content",
            ),
            [
                ("snapshot", ("sql-database", "7")),
                ("job_statuses", ("sql-database",)),
                ("employees", ("sql-database",)),
                ("pay_classes", ("sql-database",)),
                ("used_statuses", ("sql-database",)),
                ("delete_content", ("sql-database", "7")),
            ],
        )
        self.assertEqual(
            harness.calls_named(
                "read_cover_sheet", "read_takeoffs", "read_delete_content"
            ),
            [],
        )
        data = dialog.args[2]
        self.assertIs(data, harness.data)
        self.assertIs(data.job_statuses, harness.snapshot_statuses)
        self.assertIs(data.employees, harness.snapshot_employees)
        self.assertIs(data.pay_classes, harness.snapshot_pay_classes)
        self.assertIs(data.used_job_status_uids, harness.used_statuses)
        self.assertIs(dialog.args[1], harness.window)
        self.assertEqual(dialog.kwargs["database_id"], "sql-database")
        self.assertEqual(dialog.kwargs["pages_with_takeoffs"], {"p1"})
        self.assertEqual(
            dialog.kwargs["pages_requiring_delete_confirmation"], {"p1", "p2", "p3"}
        )
        self.assertTrue(dialog.kwargs["has_license"])
        self.assertIs(dialog.kwargs["event_bus"], harness.event_bus)

    def test_access_open_reads_through_the_read_service_without_sql_wiring(self):
        harness = _SecondPassCoverSheetHarness(self, sql=False)
        dialog = harness.open()
        self.assertEqual(
            harness.calls,
            [
                ("read_cover_sheet", ("bid.mdb", "7")),
                ("read_takeoffs", ("bid.mdb", "7")),
                ("read_delete_content", ("bid.mdb", "7")),
            ],
        )
        self.assertEqual(dialog.kwargs["pages_with_takeoffs"], {"read-takeoff-page"})
        self.assertEqual(
            dialog.kwargs["pages_requiring_delete_confirmation"], {"read-delete-page"}
        )
        self.assertEqual(dialog.kwargs["database_id"], "bid.mdb")
        for name in (
            "save_job_statuses_async_fn",
            "reload_job_statuses_fn",
            "save_employees_async_fn",
            "save_pay_classes_async_fn",
            "reload_employees_fn",
            "save_bid_areas_async_fn",
            "reload_bid_areas_fn",
            "save_cover_sheet_async_fn",
        ):
            self.assertIsNone(dialog.kwargs[name], name)
        self.assertEqual(harness.requested, [])
        self.assertTrue(dialog.deleted)
        harness.calls.clear()
        self.assertEqual(dialog.kwargs["employee_usage_fn"](), {"read-employees"})
        self.assertEqual(dialog.kwargs["pay_class_usage_fn"](), {"read-pay_classes"})
        self.assertEqual(dialog.kwargs["job_status_usage_fn"](), {"read-job_statuses"})
        self.assertEqual(
            harness.calls,
            [
                ("read_in_use", ("bid.mdb", "employees")),
                ("read_in_use", ("bid.mdb", "pay_classes")),
                ("read_in_use", ("bid.mdb", "job_statuses")),
            ],
        )

    def test_sql_dialog_usage_and_reload_callbacks_answer_from_hydrated_state(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        dialog = harness.open()
        harness.calls.clear()
        self.assertEqual(
            dialog.kwargs["employee_usage_fn"](), {"project-data-employees"}
        )
        self.assertEqual(
            dialog.kwargs["pay_class_usage_fn"](), {"project-data-pay_classes"}
        )
        self.assertEqual(
            dialog.kwargs["job_status_usage_fn"](), {"project-data-job_statuses"}
        )
        self.assertEqual(
            harness.calls,
            [
                ("project_data_in_use", ("sql-database", "employees")),
                ("project_data_in_use", ("sql-database", "pay_classes")),
                ("project_data_in_use", ("sql-database", "job_statuses")),
            ],
        )
        harness.calls.clear()
        self.assertIs(
            dialog.kwargs["reload_job_statuses_fn"](), harness.snapshot_statuses
        )
        employees, pay_classes = dialog.kwargs["reload_employees_fn"]()
        self.assertIs(employees, harness.snapshot_employees)
        self.assertIs(pay_classes, harness.snapshot_pay_classes)
        self.assertIs(dialog.kwargs["reload_bid_areas_fn"](), harness.areas)
        self.assertEqual(
            harness.calls,
            [
                ("job_statuses", ("sql-database",)),
                ("employees", ("sql-database",)),
                ("pay_classes", ("sql-database",)),
            ],
        )

    def test_sql_open_leases_the_cover_sheet_master_data_and_every_bid_area(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        harness.open()
        self.assertEqual(len(harness.requested), 1)
        lease = harness.requested[0]
        self.assertEqual(lease.operation_id, "CoverSheetDialog")
        self.assertEqual(
            {
                (ref.resource_type, ref.resource_id, ref.bid_uid)
                for ref in lease.resources
            },
            {
                ("cover_sheet", "7", 7),
                ("bid", "7", 7),
                ("job_statuses_collection", "database", None),
                ("employees_collection", "database", None),
                ("pay_classes_collection", "database", None),
                ("areas_collection", "7", 7),
                ("area", "a1", 7),
                ("job_status", "s1", None),
                ("employee", "e1", None),
                ("pay_class", "pc1", None),
            },
        )
        self.assertEqual(harness.ended, [lease])

    def test_sql_accepted_dialog_saves_nothing_synchronously(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                harness = _SecondPassCoverSheetHarness(self, sql=True, locked=locked)
                harness.exec_result = QtWidgets.QDialog.DialogCode.Accepted
                _SecondPassRecordingCoverSheetDialog.updates = {
                    "job_status_uid": "status-2",
                    "notes": "Updated",
                }
                dialog = harness.open()
                self.assertEqual(harness.calls_named("sync_save", "sync_status"), [])
                self.assertEqual(harness.queued, [])
                self.assertEqual(harness.critical, [])
                self.assertTrue(dialog.deleted)

    def test_a_lost_lease_rejects_the_open_dialog_and_the_session_still_closes(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)

        def lose(dialog):
            lease = harness.requested[0]
            harness.event_bus.publish(
                AppEvents.EDIT_LEASE_LOST,
                loss=EditLeaseLoss(
                    database_id=lease.database_id,
                    draft_id=lease.draft_id,
                    runtime_generation=lease.runtime_generation,
                    operation_id=lease.operation_id,
                    owning_surface=lease.owning_surface,
                    resources=lease.resources,
                    reason="expired",
                ),
            )

        harness.on_exec = lose
        dialog = harness.open()
        self.assertEqual(dialog.rejected, 1)
        self.assertEqual(harness.ended, [])
        self.assertTrue(dialog.deleted)

    def test_sql_nested_master_data_saves_use_their_queue_title_family_and_lease(self):
        cases = (
            ("save_job_statuses_async_fn", "job_statuses", "Job Statuses"),
            ("save_employees_async_fn", "employees", "Employees"),
            ("save_pay_classes_async_fn", "pay_classes", "Payroll Classes"),
        )
        for key, family, title in cases:
            with self.subTest(family=family):
                harness = _SecondPassCoverSheetHarness(self, sql=True)
                harness.on_exec = lambda dialog, key=key, family=family, title=title, harness=harness: (
                    self._drive_master_save(harness, dialog, key, family, title)
                )
                harness.open()
                self.assertEqual(len(harness.requested), 3)
                self.assertEqual(len(harness.ended), 1)

    def _drive_master_save(self, harness, dialog, key, family, title):
        save = dialog.kwargs[key]
        results = []
        changes = {"new": [], "updated": [], "deleted_uids": ["x"]}
        initial = harness.requested[0]
        self.assertTrue(save(changes, lambda *args: results.append(args)))
        (name, args, callback, kwargs) = harness.queued[-1]
        self.assertEqual((name, args), (family, ("sql-database", changes)))
        self.assertIs(kwargs["edit_lease_handle"], initial)
        self.assertEqual(results, [])
        callback(harness.callback(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        callback(harness.callback(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(results, [])
        callback(
            harness.callback(
                authoritative_result=AuthoritativeMutationResult(
                    created_uid_maps=(
                        (family, (("new-1", "7"),)),
                        ("other_family", (("x", "y"),)),
                    )
                )
            )
        )
        self.assertEqual(results, [(True, {"new-1": "7"})])
        self.assertEqual(harness.presented, [])
        self.assertEqual(len(harness.requested), 2)
        self.assertEqual(harness.ended, [])
        # A rejected save reports through the coordinator with this save's title.
        results.clear()
        self.assertTrue(save(changes, lambda *args: results.append(args)))
        rejected = harness.callback(MutationOutcomeStatus.REJECTED, message="refused")
        harness.queued[-1][2](rejected)
        self.assertEqual(harness.presented, [("sql-database", title, rejected)])
        self.assertEqual(results, [(False, None)])

    def test_committed_master_data_save_without_authoritative_result_maps_nothing(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        results = []
        queue = harness.write.queue_employees_save
        self.assertTrue(
            harness.handler.save_master_data_async(
                "sql-database",
                "Employees",
                queue,
                {"new": []},
                lambda *args: results.append(args),
                "employees",
            )
        )
        name, args, callback, kwargs = harness.queued[-1]
        self.assertEqual(
            (name, args, kwargs), ("employees", ("sql-database", {"new": []}), {})
        )
        callback(harness.callback())
        self.assertEqual(results, [(True, {})])

    def test_master_data_queue_refusals_open_one_critical_dialog_and_return_false(self):
        for error in (RuntimeError("queue is closed"), ValueError("bad payload")):
            with self.subTest(error=type(error).__name__):
                harness = _SecondPassCoverSheetHarness(self, sql=True)
                results = []

                def refuse(*_args, **_kwargs):
                    raise error

                with mock.patch(
                    "ost_visualizer.presentation.handlers.cover_sheet_handler"
                    ".show_critical"
                ) as critical:
                    started = harness.handler._save_master_data_async(
                        "sql-database",
                        "Employees",
                        refuse,
                        {},
                        lambda *args: results.append(args),
                        "employees",
                        edit_lease_handle=object(),
                    )
                self.assertIs(started, False)
                self.assertEqual(results, [])
                critical.assert_called_once_with(
                    harness.window, "Employees", str(error)
                )

    def test_create_bid_async_queues_with_the_lease_and_reports_each_outcome(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        results = []
        lease = object()
        started = harness.handler.create_bid_async(
            "sql-database",
            "project-1",
            {"job_name": "N"},
            lambda *args: results.append(args),
            edit_lease_handle=lease,
        )
        self.assertIs(started, True)
        name, args, callback, kwargs = harness.queued[-1]
        self.assertEqual(
            (name, args),
            ("bid_create", ("sql-database", "project-1", {"job_name": "N"})),
        )
        self.assertIs(kwargs["edit_lease_handle"], lease)
        callback(harness.callback(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        callback(harness.callback(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual((results, harness.presented), ([], []))
        callback(harness.callback())
        self.assertEqual(results, [(True,)])
        rejected = harness.callback(MutationOutcomeStatus.REJECTED, message="no")
        results.clear()
        harness.handler.create_bid_async(
            "sql-database", None, {}, lambda *args: results.append(args)
        )
        self.assertIsNone(harness.queued[-1][3]["edit_lease_handle"])
        harness.queued[-1][2](rejected)
        self.assertEqual(results, [(False,)])
        self.assertEqual(harness.presented, [("sql-database", "New Project", rejected)])

    def test_create_bid_async_queue_refusal_opens_the_new_project_dialog_once(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        harness.write.queue_bid_create = lambda *_a, **_k: (_ for _ in ()).throw(
            ValueError("project is gone")
        )
        results = []
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical:
            started = harness.handler.create_bid_async(
                "sql-database", "p", {}, lambda *args: results.append(args)
            )
        self.assertIs(started, False)
        self.assertEqual(results, [])
        critical.assert_called_once_with(
            harness.window, "New Project", "project is gone"
        )

    def test_bid_areas_save_maps_created_areas_and_titles_its_failures(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        bid_ref = BidRef("sql-database", "7")
        results = []
        self.assertTrue(
            harness.handler._save_bid_areas_async(
                bid_ref, ["change"], lambda *args: results.append(args)
            )
        )
        name, args, callback, kwargs = harness.queued[-1]
        self.assertEqual(
            (name, args, kwargs), ("bid_areas", ("sql-database", "7", ["change"]), {})
        )
        callback(harness.callback(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        callback(harness.callback(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED))
        self.assertEqual(results, [])
        callback(
            harness.callback(
                authoritative_result=AuthoritativeMutationResult(
                    created_uid_maps=(("areas", (("new", "9"),)), ("x", (("y", "z"),)))
                )
            )
        )
        self.assertEqual(results, [(True, {"new": "9"})])
        results.clear()
        self.assertTrue(
            harness.handler._save_bid_areas_async(
                bid_ref, [], lambda *args: results.append(args), edit_lease_handle=None
            )
        )
        harness.queued[-1][2](harness.callback())
        self.assertEqual(results, [(True, {})])
        rejected = harness.callback(MutationOutcomeStatus.CONFLICT, message="stale")
        results.clear()
        harness.handler._save_bid_areas_async(
            bid_ref, [], lambda *args: results.append(args)
        )
        harness.queued[-1][2](rejected)
        self.assertEqual(results, [(False, None)])
        self.assertEqual(harness.presented, [("sql-database", "Bid Areas", rejected)])

    def test_bid_areas_queue_refusal_with_a_lease_opens_the_critical_dialog(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        lease = object()
        harness.write.queue_bid_areas_save = lambda *_a, **kw: (_ for _ in ()).throw(
            ValueError("area " + str(kw["edit_lease_handle"] is lease))
        )
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical:
            started = harness.handler._save_bid_areas_async(
                BidRef("sql-database", "7"),
                [],
                lambda *_a: None,
                edit_lease_handle=lease,
            )
        self.assertIs(started, False)
        critical.assert_called_once_with(harness.window, "Bid Areas", "area True")

    def test_cover_sheet_failure_without_a_coordinator_shows_the_message_or_a_default(
        self,
    ):
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = "window"
        handler._ui_event_coordinator = None
        cases = (
            ("stale data", MutationOutcomeStatus.CONFLICT, "stale data"),
            ("", MutationOutcomeStatus.CONFLICT, "The update failed."),
        )
        for message, status, shown in cases:
            with self.subTest(message=message):
                result = QueuedMutationResult(
                    database_id="database",
                    runtime_generation=1,
                    operation_id="00000000-0000-4000-8000-00000000009b",
                    outcome_status=status,
                    message=message,
                )
                with mock.patch(
                    "ost_visualizer.presentation.handlers.cover_sheet_handler"
                    ".show_critical"
                ) as critical:
                    handler._present_mutation_error("database", "Cover Sheet", result)
                critical.assert_called_once_with("window", "Cover Sheet", shown)

    def test_locked_bid_job_status_save_queues_only_a_changed_status(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        bid_ref = BidRef("sql-database", "7")
        results = []

        def save(current, updates, **options):
            return harness.handler._save_locked_bid_status_async(
                bid_ref, current, updates, lambda *args: results.append(args), **options
            )

        for current, updates in (
            ("status-1", {"job_status_uid": "status-1", "notes": "n"}),
            (None, {"job_status_uid": None}),
            ("", {}),
            (None, {"job_status_uid": ""}),
        ):
            with self.subTest(current=current, updates=updates):
                results.clear()
                self.assertIs(save(current, updates), True)
                self.assertEqual(results, [(True,)])
                self.assertEqual(harness.queued, [])
        results.clear()
        self.assertIs(save("status-1", {"job_status_uid": "status-2"}), True)
        self.assertIs(save(None, {"job_status_uid": 5}, edit_lease_handle=None), True)
        lease = object()
        self.assertIs(
            save("status-1", {"job_status_uid": ""}, edit_lease_handle=lease), True
        )
        self.assertEqual(
            [(name, args) for name, args, _cb, _kw in harness.queued],
            [
                ("job_status", ("sql-database", "7", "status-2")),
                ("job_status", ("sql-database", "7", "5")),
                ("job_status", ("sql-database", "7", "")),
            ],
        )
        self.assertEqual(
            [kw for *_rest, kw in harness.queued],
            [{}, {}, {"edit_lease_handle": lease}],
        )
        self.assertEqual(results, [])
        callbacks = [item[2] for item in harness.queued]
        callbacks[0](harness.callback(MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN))
        callbacks[0](
            harness.callback(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED)
        )
        self.assertEqual((results, harness.presented), ([], []))
        callbacks[0](harness.callback())
        self.assertEqual(results, [(True,)])
        rejected = harness.callback(MutationOutcomeStatus.REJECTED, message="no")
        callbacks[1](rejected)
        self.assertEqual(results, [(True,), (False,)])
        self.assertEqual(harness.presented, [("sql-database", "Cover Sheet", rejected)])

    def test_locked_bid_job_status_queue_refusal_opens_the_critical_dialog(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        harness.write.queue_bid_job_status_update = lambda *_a, **_k: (
            _ for _ in ()
        ).throw(RuntimeError("queue closed"))
        results = []
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical:
            started = harness.handler._save_locked_bid_status_async(
                BidRef("sql-database", "7"),
                "a",
                {"job_status_uid": "b"},
                lambda *args: results.append(args),
            )
        self.assertIs(started, False)
        self.assertEqual(results, [])
        critical.assert_called_once_with(harness.window, "Cover Sheet", "queue closed")

    def test_sql_cover_sheet_dialog_save_follows_the_lock_state_at_open(self):
        for locked in (False, True):
            with self.subTest(locked=locked):
                harness = _SecondPassCoverSheetHarness(self, sql=True, locked=locked)
                outcomes = []
                dialog_updates = {"job_status_uid": "status-2", "notes": "Updated"}

                def drive(dialog):
                    save = dialog.kwargs["save_cover_sheet_async_fn"]
                    outcomes.append(
                        save(dialog_updates, lambda success: outcomes.append(success))
                    )
                    name, args, callback, kwargs = harness.queued[-1]
                    outcomes.append((name, args))
                    self.assertIs(kwargs["edit_lease_handle"], harness.requested[0])
                    callback(harness.callback())
                    outcomes.append(len(harness.requested))
                    outcomes.append(len(harness.ended))

                harness.on_exec = drive
                harness.open()
                expected = (
                    ("job_status", ("sql-database", "7", "status-2"))
                    if locked
                    else ("cover_sheet", ("sql-database", "7", dialog_updates))
                )
                self.assertEqual(outcomes, [True, expected, True, 2, 0])
                self.assertEqual(len(harness.queued), 1)

    def test_locked_bid_dialog_without_a_status_change_completes_without_queueing(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True, locked=True)
        outcomes = []

        def drive(dialog):
            save = dialog.kwargs["save_cover_sheet_async_fn"]
            outcomes.append(
                save(
                    {"job_status_uid": "status-1", "notes": "edited"},
                    lambda success: outcomes.append(success),
                )
            )

        harness.on_exec = drive
        harness.open()
        self.assertEqual(outcomes, [True, True])
        self.assertEqual(harness.queued, [])
        self.assertEqual(len(harness.requested), 2)
        self.assertEqual(harness.presented, [])

    def test_nested_bid_areas_save_goes_through_the_lease_session(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        results = []

        def drive(dialog):
            save = dialog.kwargs["save_bid_areas_async_fn"]
            self.assertTrue(save(["area-change"], lambda *args: results.append(args)))
            name, args, callback, kwargs = harness.queued[-1]
            self.assertEqual(
                (name, args), ("bid_areas", ("sql-database", "7", ["area-change"]))
            )
            self.assertIs(kwargs["edit_lease_handle"], harness.requested[0])
            callback(
                harness.callback(
                    authoritative_result=AuthoritativeMutationResult(
                        created_uid_maps=(("areas", (("tmp", "11"),)),)
                    )
                )
            )

        harness.on_exec = drive
        harness.open()
        self.assertEqual(results, [(True, {"tmp": "11"})])
        self.assertEqual(len(harness.requested), 2)

    def test_access_locked_cover_sheet_saves_only_a_changed_job_status(self):
        for status, expect_update, expect_critical in (
            ("status-1", [], 0),
            ("status-2", [("bid.mdb", "7", "status-2")], 0),
        ):
            with self.subTest(status=status):
                harness = _SecondPassCoverSheetHarness(self, sql=False, locked=True)
                harness.exec_result = QtWidgets.QDialog.DialogCode.Accepted
                _SecondPassRecordingCoverSheetDialog.updates = {
                    "job_status_uid": status,
                    "notes": "Updated",
                }
                harness.open()
                self.assertEqual(
                    [args for _n, args in harness.calls_named("sync_status")],
                    expect_update,
                )
                self.assertEqual(harness.calls_named("sync_save"), [])
                self.assertEqual(len(harness.critical), expect_critical)

    def test_locked_status_change_reports_failure_and_treats_none_like_empty(self):
        handler = CoverSheetHandler.__new__(CoverSheetHandler)
        handler.window = "window"
        updated = []

        class Context:
            result = True

            def update_bid_job_status(self, status_uid):
                updated.append(status_uid)
                return self.result

        context = Context()
        for current, new in (("", None), (None, ""), ("s", "s")):
            with self.subTest(current=current, new=new):
                updated.clear()
                with mock.patch(
                    "ost_visualizer.presentation.handlers.cover_sheet_handler"
                    ".show_critical"
                ) as critical:
                    self.assertIs(
                        handler._save_locked_bid_status_change(
                            context, current, {"job_status_uid": new}
                        ),
                        False,
                    )
                self.assertEqual((updated, critical.call_count), ([], 0))
        self.assertIs(
            handler._save_locked_bid_status_change(
                context, None, {"job_status_uid": "t"}
            ),
            True,
        )
        self.assertEqual(updated, ["t"])
        context.result = False
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.show_critical"
        ) as critical:
            self.assertIs(
                handler._save_locked_bid_status_change(
                    context, "a", {"job_status_uid": "b"}
                ),
                False,
            )
        critical.assert_called_once_with(
            "window", "Cover Sheet", f"Failed to save job status. {DB_LOCKED_HINT}"
        )

    def test_add_blank_page_reads_the_selected_bid_and_reports_missing_data(self):
        for sql in (True, False):
            with self.subTest(sql=sql):
                harness = _SecondPassCoverSheetHarness(self, sql=sql)
                harness.data = None
                with (
                    mock.patch(
                        "ost_visualizer.presentation.handlers.cover_sheet_handler.confirm",
                        return_value=True,
                    ) as confirm,
                    mock.patch(
                        "ost_visualizer.presentation.handlers.cover_sheet_handler"
                        ".show_critical"
                    ) as critical,
                ):
                    self.assertIs(
                        harness.handler.add_blank_page_from_takeoff_tab(), False
                    )
                confirm.assert_called_once_with(
                    harness.window, "Add Page", "Do you want to add a new page?"
                )
                critical.assert_called_once_with(
                    harness.window,
                    "Add Page",
                    f"Failed to load cover sheet data. {DB_LOCKED_HINT}",
                )
                self.assertEqual(
                    harness.calls,
                    (
                        [("snapshot", ("sql-database", "7"))]
                        if sql
                        else [("read_cover_sheet", ("bid.mdb", "7"))]
                    ),
                )
                self.assertEqual(harness.queued, [])

    def test_add_blank_page_ignores_pages_without_a_sheet_number(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        template = harness.data.pages_without_folder[0]
        template.sheet_no = None
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.confirm",
            return_value=True,
        ):
            self.assertIs(harness.handler.add_blank_page_from_takeoff_tab(), True)
        updates = harness.queued[-1][1][2]
        self.assertEqual(updates["pages"][0]["sheet_no"], "00001")
        self.assertEqual(updates["pages"][0]["sequence"], 2)

    def test_add_blank_page_returns_false_without_a_selected_bid(self):
        harness = _SecondPassCoverSheetHarness(self, sql=True)
        harness.handler.ui_state_manager = SimpleNamespace(
            get_selected_bid_ref=lambda: None
        )
        with mock.patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler.confirm"
        ) as confirm:
            self.assertIs(harness.handler.add_blank_page_from_takeoff_tab(), False)
        confirm.assert_not_called()


def _second_pass_unexpected_modal(name):
    def refuse(*_args, **_kwargs):
        raise AssertionError(
            f"unexpected modal call {name}: patch it in the test that expects it"
        )

    return refuse


_second_pass_modal_guards = []


def setUpModule():
    """A regression that reaches a real modal dialog fails fast instead of hanging the
    whole run (a stuck QMessageBox freezes the test process); tests that expect a
    dialog patch it themselves, which takes precedence over this module default."""
    for name in (
        "show_critical",
        "confirm",
        "exec_with_ost_blocking",
        "CoverSheetDialog",
    ):
        guard = patch(
            "ost_visualizer.presentation.handlers.cover_sheet_handler." + name,
            side_effect=_second_pass_unexpected_modal(name),
        )
        guard.start()
        _second_pass_modal_guards.append(guard)


def tearDownModule():
    while _second_pass_modal_guards:
        _second_pass_modal_guards.pop().stop()
