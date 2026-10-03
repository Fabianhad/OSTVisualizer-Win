import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
)
from ost_visualizer.application.services.project_write_service import (
    DeleteValidationResult,
    ProjectWriteService,
    WriteReloadResult,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.services.project_data_service import ProjectDataService
from ost_visualizer.presentation.handlers.project_write_handler import (
    ProjectWriteHandler,
)
from ost_visualizer.presentation.managers.ui_state_manager import UIStateManager
from PySide6 import QtCore, QtWidgets
from shiboken6 import delete
from tests.application.services import (
    test_sql_collaboration_coordinator as _coordinator_tests,
)
from tests.presentation.handlers.project_command_support import (
    _DeferredPersistenceRequiringBidCancel as _permissions__DeferredPersistenceRequiringBidCancel,
    _DeferredPersistenceRequiringSelectedPageFileCancel as _permissions__DeferredPersistenceRequiringSelectedPageFileCancel,
    _DeleteBidUiState as _permissions__DeleteBidUiState,
    _FakeDeferredPersistence as _permissions__FakeDeferredPersistence,
    _MoveToDeletedWriteService as _permissions__MoveToDeletedWriteService,
    _PartialPasteWriteService as _permissions__PartialPasteWriteService,
    _QueuedHierarchyDeleteWriteService as _permissions__QueuedHierarchyDeleteWriteService,
)
from tests.presentation.utils.dialog_lifecycle_support import (
    _app as _dialog_lifecycle_support__app,
)
from tests.presentation.managers.permission_support import (
    _FakeAction as _permissions__FakeAction,
)


class BidLockPermissionTests(unittest.TestCase):
    def test_project_delete_resolves_multi_selection_database_not_active_bid(self):
        ui_state = UIStateManager(
            SimpleNamespace(
                display_modes_synced=True,
                display_mode_3d="solid",
                display_mode_2d="solid",
                grayscale_enabled=False,
            )
        )
        ui_state.set_bid_selection(BidRef("C:/jobs/active.mdb", "7"))
        ui_state.set_bid_multi_selection([])
        ui_state.set_project_multi_selection(
            ["project-8", "project-9"], "C:/jobs/other.mdb"
        )
        calls = []
        handler = ProjectWriteHandler.__new__(ProjectWriteHandler)
        handler.ui_state_manager = ui_state
        handler._delete_projects = lambda project_uids, file_path: calls.append(
            (list(project_uids), file_path)
        )
        ProjectWriteHandler.delete_selected(handler)
        self.assertEqual(
            calls,
            [
                (
                    ["project-8", "project-9"],
                    "C:/jobs/other.mdb",
                )
            ],
        )

    def test_sql_bid_cut_completion_callback_runs_only_after_commit(self):
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        committed = []
        refreshes = []
        errors = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: refreshes.append(True),
                present_queued_mutation_error=lambda *args: errors.append(args),
            )
        )
        bid_ref = BidRef("database", "bid-1")
        self.assertTrue(
            handler.paste_bids(
                [bid_ref],
                "project-2",
                is_cut=True,
                on_cut_committed=lambda: committed.append(True),
            )
        )
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000301",
                outcome_status=MutationOutcomeStatus.REJECTED,
                commit_attempted=False,
            )
        )
        self.assertEqual(committed, [])
        self.assertEqual(refreshes, [True])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][:2], ("database", "Move Bids"))
        self.assertTrue(
            handler.paste_bids(
                [bid_ref],
                "project-2",
                is_cut=True,
                on_cut_committed=lambda: committed.append(True),
            )
        )
        write_service.callbacks[1](
            QueuedMutationResult(
                database_id="database",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000302",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(committed, [True])
        self.assertEqual(refreshes, [True])
        self.assertEqual(len(errors), 1)

    def test_bid_paste_handler_accepts_normalized_same_database_source_paths(self):
        write_service = _permissions__PartialPasteWriteService()
        write_service.duplicate_results = ["copy-1", "copy-2"]
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: "project-2"
            ),
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )

        def run_progress(_label, task_fn, action_text, reporter):
            del action_text, reporter
            return QtWidgets.QDialog.DialogCode.Accepted, task_fn(), None

        handler._run_progress_dialog = run_progress
        result = handler.paste_bids(
            [
                BidRef("C:/jobs/test.mdb", "bid-1"),
                BidRef("C:\\jobs\\test.mdb", "bid-2"),
            ],
            "project-2",
        )
        self.assertTrue(result)
        self.assertEqual(
            write_service.duplicate_calls,
            [
                ("C:/jobs/test.mdb", "bid-1", False),
                ("C:/jobs/test.mdb", "bid-2", False),
            ],
        )
        self.assertEqual(write_service.reloads, ["C:/jobs/test.mdb"])
        self.assertEqual(write_service.notifications, ["C:/jobs/test.mdb"])

    def test_multi_bid_paste_partial_success_warns_without_plain_failure(self):
        write_service = _permissions__PartialPasteWriteService()
        project_data = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "project-1",
            get_hierarchy=lambda: SimpleNamespace(find_bid_info=lambda _ref: None),
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )

        def run_progress(label, task_fn, action_text, reporter):
            return QtWidgets.QDialog.DialogCode.Accepted, task_fn(), None

        handler._run_progress_dialog = run_progress
        warnings = []
        criticals = []
        from ost_visualizer.presentation.handlers import project_write_handler

        old_warning = project_write_handler.show_warning
        old_critical = project_write_handler.show_critical
        old_logger_error = project_write_handler.logger.error
        project_write_handler.show_warning = lambda *args: warnings.append(args)
        project_write_handler.show_critical = lambda *args: criticals.append(args)
        project_write_handler.logger.error = lambda *args, **call_options: None
        try:
            result = handler.paste_bids(
                [
                    BidRef("db.mdb", "bid-1"),
                    BidRef("db.mdb", "bid-2"),
                ],
                "project-1",
            )
        finally:
            project_write_handler.show_warning = old_warning
            project_write_handler.show_critical = old_critical
            project_write_handler.logger.error = old_logger_error
        self.assertTrue(result)
        self.assertEqual(
            write_service.duplicate_calls,
            [
                ("db.mdb", "bid-1", False),
                ("db.mdb", "bid-2", False),
            ],
        )
        self.assertEqual(write_service.reloads, ["db.mdb"])
        self.assertEqual(write_service.notifications, ["db.mdb"])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0][1], "Paste Partially Completed")
        self.assertEqual(
            warnings[0][2],
            "Some bids were pasted, but the paste did not finish. "
            "Review the refreshed project tree before retrying.",
        )
        self.assertEqual(len(criticals), 0)

    def test_duplicate_stops_after_progress_dialog_destroys_main_window(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        bid_ref = BidRef("db.mdb", "bid-1")
        handler = ProjectWriteHandler(
            window=window,
            project_data_service=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda _ref: SimpleNamespace(name="Bid 1")
                )
            ),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _path: False
            ),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: bid_ref),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )

        def destroy_window(*_args, **_kwargs):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Rejected, None, None

        handler._run_progress_dialog = destroy_window
        criticals = []
        warnings = []
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ), patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_warning",
            side_effect=lambda *args: warnings.append(args),
        ):
            handler.duplicate_selected()
        self.assertEqual(len(criticals), 0)
        self.assertEqual(len(warnings), 0)
        self.assertFalse(handler._duplicate_in_progress)
        app.processEvents()

    def test_duplicate_worker_failure_is_reported_once_and_can_retry(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        bid_ref = BidRef("db.mdb", "bid-1")
        notifications = []
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _path: False,
            duplicate_bid_result=lambda _file_path, _bid_uid, reload=False: (
                WriteReloadResult("new-bid", True, True)
            ),
            reload_database=lambda _path: True,
            notify_database_refreshed=notifications.append,
        )
        ui_state = SimpleNamespace(get_selected_bid_ref=lambda: bid_ref)
        handler = ProjectWriteHandler(
            window=window,
            project_data_service=SimpleNamespace(
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda _ref: SimpleNamespace(name="Bid 1")
                )
            ),
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        attempts = []

        def run_progress(_label, task_fn, **_options):
            attempts.append(True)
            if len(attempts) == 1:
                return (
                    QtWidgets.QDialog.DialogCode.Rejected,
                    False,
                    RuntimeError("duplicate failed"),
                )
            return QtWidgets.QDialog.DialogCode.Accepted, task_fn(), None

        handler._run_progress_dialog = run_progress
        criticals = []
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ):
            handler.duplicate_selected()
            self.assertEqual(ui_state.get_selected_bid_ref(), bid_ref)
            self.assertFalse(handler._duplicate_in_progress)
            self.assertEqual(len(criticals), 1)
            self.assertEqual(notifications, [])
            handler.duplicate_selected()
        self.assertEqual(len(criticals), 1)
        self.assertEqual(criticals[0][1], "Duplicate Error")
        self.assertEqual(notifications, ["db.mdb"])
        self.assertEqual(len(attempts), 2)
        self.assertEqual(ui_state.get_selected_bid_ref(), bid_ref)
        window.deleteLater()
        app.processEvents()

    def test_paste_stops_after_progress_dialog_destroys_main_window(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = QtWidgets.QWidget()
        bid_ref = BidRef("db.mdb", "bid-1")
        handler = ProjectWriteHandler(
            window=window,
            project_data_service=SimpleNamespace(
                find_project_uid_for_bid=lambda _ref: "project-1",
                get_hierarchy=lambda: SimpleNamespace(
                    find_bid_info=lambda _ref: SimpleNamespace(name="Bid 1")
                ),
            ),
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _path: False
            ),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )

        def destroy_window(*_args, **_kwargs):
            delete(window)
            return QtWidgets.QDialog.DialogCode.Rejected, None, None

        handler._run_progress_dialog = destroy_window
        criticals = []
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ):
            result = handler.paste_bids([bid_ref], "project-2")
        self.assertIs(result, False)
        self.assertEqual(len(criticals), 0)
        app.processEvents()

    def test_sql_hierarchy_pending_keys_are_database_scoped_and_recovery_safe(self):
        callbacks = {}
        committed = []
        errors = []
        refreshes = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: refreshes.append(True),
                present_queued_mutation_error=lambda *args: errors.append(args),
            )
        )

        def submit(database_id):
            return handler._submit_sql_hierarchy_operation(
                database_id,
                ("move_bids", "7"),
                "Move Bids",
                lambda callback: callbacks.__setitem__(database_id, callback),
                lambda _result: committed.append(database_id),
            )

        self.assertTrue(submit("database-a"))
        self.assertTrue(submit("database-b"))
        key_a = ("database-a", "move_bids", "7")
        key_b = ("database-b", "move_bids", "7")
        self.assertIn(key_a, handler._pending_sql_operations)
        self.assertIn(key_b, handler._pending_sql_operations)
        # A still-pending operation for the same database and key is not
        # submitted twice.
        self.assertFalse(submit("database-a"))
        self.assertEqual(committed, [])
        for status in (
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        ):
            callbacks["database-a"](
                QueuedMutationResult(
                    database_id="database-a",
                    runtime_generation=1,
                    operation_id="00000000-0000-0000-0000-000000000001",
                    outcome_status=status,
                    commit_attempted=True,
                )
            )
            self.assertIn(key_a, handler._pending_sql_operations)
            self.assertEqual(errors, [])
            self.assertEqual(refreshes, [])
        callbacks["database-a"](
            QueuedMutationResult(
                database_id="database-a",
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000001",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertNotIn(key_a, handler._pending_sql_operations)
        self.assertIn(key_b, handler._pending_sql_operations)
        self.assertEqual(committed, ["database-a"])
        self.assertEqual(errors, [])
        self.assertEqual(refreshes, [])
        self.assertTrue(submit("database-a"))

    def _delete_project_data(
        self, selected_project_uid="project-2", remaining_uids=None
    ):
        remaining_uids = list(remaining_uids or [])
        projects = {
            selected_project_uid: HierarchyProjectInfo(
                name="Deleted Bids" if selected_project_uid == "1" else "Project",
                bids=[HierarchyBidInfo(uid=uid, name=uid) for uid in remaining_uids],
            )
        }
        if selected_project_uid != "1":
            projects["1"] = HierarchyProjectInfo(name="Deleted Bids")
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/jobs/test.mdb",
                    display_name="test.mdb",
                    bid_projects=projects,
                )
            ]
        )
        project_data = SimpleNamespace(
            clear_bid_calls=[],
            current_bid=object(),
            find_project_uid_for_bid=lambda _ref: selected_project_uid,
            get_hierarchy=lambda: hierarchy,
            get_current_file_path=lambda: "C:/jobs/test.mdb",
            project_exists=lambda project_uid, file_path: any(
                entry.file_path == file_path and project_uid in entry.bid_projects
                for entry in hierarchy.loaded_files
            ),
        )
        project_data.get_bid = lambda _ref: project_data.current_bid

        def clear_bid():
            project_data.clear_bid_calls.append(True)
            project_data.current_bid = None

        project_data.clear_bid = clear_bid
        return project_data

    def test_project_delete_identity_checks_are_scoped_to_database(self):
        project_uid = "shared-project"
        first_path = "C:/jobs/first.mdb"
        second_path = "C:/jobs/second.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=first_path,
                    bid_projects={
                        project_uid: HierarchyProjectInfo(
                            name="First",
                            bids=[HierarchyBidInfo(uid="bid-1")],
                        )
                    },
                ),
                HierarchyFileEntry(
                    file_path=second_path,
                    bid_projects={
                        project_uid: HierarchyProjectInfo(
                            name="Second",
                            bids=[],
                        )
                    },
                ),
            ]
        )
        project_data = ProjectDataService(
            SimpleNamespace(get_hierarchy_data=lambda: hierarchy)
        )
        delete_calls = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=SimpleNamespace(
                uses_sql_collaboration_mutations=lambda _database_id: False,
                delete_projects=lambda file_path, project_uids: delete_calls.append(
                    (file_path, list(project_uids))
                )
                or True,
            ),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        self.assertTrue(project_data.project_has_bids(project_uid, first_path))
        self.assertFalse(project_data.project_has_bids(project_uid, second_path))
        self.assertEqual(
            handler._valid_delete_selection_state(
                second_path,
                {
                    "kind": "project",
                    "file_path": second_path,
                    "project_uid": project_uid,
                },
            ),
            {
                "kind": "project",
                "file_path": second_path,
                "bid_uid": None,
                "project_uid": project_uid,
            },
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler._delete_projects([project_uid], second_path)
        self.assertEqual(delete_calls, [(second_path, [project_uid])])
        # The same project uid in the database that does hold bids stays blocked.
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ), patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_warning"
        ) as show_warning:
            handler._delete_projects([project_uid], first_path)
        self.assertEqual(delete_calls, [(second_path, [project_uid])])
        show_warning.assert_called_once()
        self.assertEqual(show_warning.call_args.args[1], "Cannot Delete Project")

    def test_moving_active_bid_to_deleted_clears_selection_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=[])
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        def confirm_yes(_window, _title, _message):
            return True

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = confirm_yes
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.move_calls,
            [
                (
                    "C:/jobs/test.mdb",
                    ["bid-1"],
                    "1",
                    "project-2",
                    False,
                )
            ],
        )
        self.assertEqual(project_data.clear_bid_calls, [True])
        self.assertEqual(write_service.selected_bid_during_reload, [None])
        self.assertEqual(write_service.reloads, ["C:/jobs/test.mdb"])
        self.assertEqual(write_service.selected_bid_during_notify, [None])
        self.assertIsNone(ui_state.get_selected_bid_ref())
        self.assertEqual(write_service.notifications, ["C:/jobs/test.mdb"])
        self.assertEqual(ui_state.selected_file_path, "C:/jobs/test.mdb")
        self.assertIsNone(ui_state.selected_project_uid)

    def test_empty_project_delete_discards_selected_page_writes_before_flush(self):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="C:/jobs/test.mdb",
                    display_name="test.mdb",
                    bid_projects={
                        "project-empty": HierarchyProjectInfo(
                            name="Empty Project",
                            bids=[],
                        )
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
        )
        ui_state = SimpleNamespace(
            selected_project_uids=["project-empty"],
            selected_file_path="C:/jobs/test.mdb",
            selected_project_file_path="C:/jobs/test.mdb",
            get_selected_bid_refs=lambda: [],
        )
        delete_calls = []
        write_service = SimpleNamespace(
            uses_sql_collaboration_mutations=lambda _database_id: False,
            delete_projects=lambda file_path, uids: delete_calls.append(
                (file_path, list(uids))
            )
            or True,
        )
        deferred = _permissions__DeferredPersistenceRequiringSelectedPageFileCancel(
            "C:/jobs/test.mdb"
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_page_files,
            ["C:/jobs/test.mdb"],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(delete_calls, [("C:/jobs/test.mdb", ["project-empty"])])

    def test_moving_active_bid_to_deleted_selects_replacement_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": "bid-2",
                    "project_uid": None,
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            ui_state.get_selected_bid_ref(), BidRef("C:/jobs/test.mdb", "bid-2")
        )
        self.assertEqual(
            write_service.move_calls,
            [("C:/jobs/test.mdb", ["bid-1"], "1", "project-2", False)],
        )
        self.assertEqual(project_data.clear_bid_calls, [True])
        self.assertEqual(write_service.selected_bid_during_reload, [None])
        self.assertEqual(
            write_service.selected_bid_during_notify,
            [BidRef("C:/jobs/test.mdb", "bid-2")],
        )

    def test_delete_selection_state_for_another_database_falls_back_to_deleted_one(
        self,
    ):
        first_path = "C:/jobs/first.mdb"
        second_path = "C:/jobs/second.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=path,
                    bid_projects={
                        "project-1": HierarchyProjectInfo(
                            name="Project",
                            bids=[HierarchyBidInfo(uid="bid-2", name="bid-2")],
                        )
                    },
                )
                for path in (first_path, second_path)
            ]
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=ProjectDataService(
                SimpleNamespace(get_hierarchy_data=lambda: hierarchy)
            ),
            project_write_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        database_state = {
            "kind": "database",
            "file_path": first_path,
            "bid_uid": None,
            "project_uid": None,
        }
        for requested in (
            {"kind": "bid", "file_path": second_path, "bid_uid": "bid-2"},
            {"kind": "project", "file_path": second_path, "project_uid": "project-1"},
            {"kind": "database", "file_path": second_path},
        ):
            self.assertEqual(
                handler._valid_delete_selection_state(first_path, requested),
                database_state,
                requested,
            )
        self.assertEqual(
            handler._valid_delete_selection_state(
                first_path,
                {"kind": "bid", "file_path": first_path, "bid_uid": "bid-2"},
            ),
            {
                "kind": "bid",
                "file_path": first_path,
                "bid_uid": "bid-2",
                "project_uid": None,
            },
        )

    def test_move_bid_to_deleted_discards_pending_selected_page_before_flush(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=[])
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        deferred = _permissions__DeferredPersistenceRequiringBidCancel(
            "C:/jobs/test.mdb", "bid-1"
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_pages,
            [("C:/jobs/test.mdb", ["bid-1"])],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(
            write_service.move_calls,
            [("C:/jobs/test.mdb", ["bid-1"], "1", "project-2", False)],
        )

    def test_sql_bid_delete_completion_does_not_replace_newer_bid_selection(self):
        original = BidRef("C:/jobs/test.mdb", "bid-1")
        replacement = BidRef("C:/jobs/test.mdb", "bid-2")
        newer = BidRef("C:/jobs/test.mdb", "bid-3")
        ui_state = _permissions__DeleteBidUiState(original)
        project_data = self._delete_project_data(remaining_uids=["bid-2", "bid-3"])
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": replacement.bid_uid,
                    "project_uid": None,
                }
            )
        self.assertEqual(len(write_service.callbacks), 1)
        ui_state.set_bid_selection(newer)
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000101",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), newer)
        self.assertEqual(project_data.clear_bid_calls, [])

    def test_sql_bid_delete_completion_rejects_same_uid_bid_replacement(self):
        original = BidRef("C:/jobs/test.mdb", "bid-1")
        replacement = BidRef("C:/jobs/test.mdb", "bid-2")
        ui_state = _permissions__DeleteBidUiState(original)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        original_bid = project_data.current_bid
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": replacement.bid_uid,
                    "project_uid": None,
                }
            )
        self.assertEqual(len(write_service.callbacks), 1)
        project_data.current_bid = object()
        self.assertIsNot(project_data.current_bid, original_bid)
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000107",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), original)
        self.assertEqual(project_data.clear_bid_calls, [])

    def test_sql_duplicate_completion_recomputes_current_toolbar_state(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=["bid-1"])
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        duplicate_action = _permissions__FakeAction()
        duplicate_action.setEnabled(True)
        refresh_calls = []

        def refresh_toolbar():
            refresh_calls.append(True)
            duplicate_action.setEnabled(False)

        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_duplicate_action(duplicate_action)
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
                refresh_toolbar=refresh_toolbar,
            )
        )
        handler.duplicate_selected()
        self.assertEqual(len(write_service.callbacks), 1)
        self.assertTrue(handler._duplicate_in_progress)
        self.assertFalse(duplicate_action.isEnabled())
        self.assertEqual(refresh_calls, [])
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=bid_ref.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000105",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(refresh_calls, [True])
        self.assertFalse(handler._duplicate_in_progress)
        self.assertFalse(duplicate_action.isEnabled())

    def test_sql_duplicate_failure_is_reported_once_and_can_retry(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "bid-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(remaining_uids=["bid-1"])
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        presented_errors = []
        refreshes = []
        toolbar_refreshes = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: refreshes.append(True),
                present_queued_mutation_error=lambda *args: presented_errors.append(
                    args
                ),
                refresh_toolbar=lambda: toolbar_refreshes.append(True),
            )
        )
        handler.duplicate_selected()
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=bid_ref.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000108",
                outcome_status=MutationOutcomeStatus.REJECTED,
                commit_attempted=False,
            )
        )
        self.assertEqual(len(presented_errors), 1)
        self.assertEqual(presented_errors[0][0], bid_ref.file_path)
        self.assertEqual(presented_errors[0][1], "Duplicate Bid")
        self.assertEqual(refreshes, [True])
        self.assertEqual(toolbar_refreshes, [True])
        self.assertFalse(handler._duplicate_in_progress)
        self.assertEqual(ui_state.get_selected_bid_ref(), bid_ref)
        handler.duplicate_selected()
        write_service.callbacks[1](
            QueuedMutationResult(
                database_id=bid_ref.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000109",
                outcome_status=MutationOutcomeStatus.COMMITTED,
                commit_attempted=True,
            )
        )
        self.assertEqual(len(write_service.callbacks), 2)
        self.assertEqual(len(presented_errors), 1)
        self.assertEqual(refreshes, [True])
        self.assertEqual(toolbar_refreshes, [True, True])
        self.assertEqual(ui_state.get_selected_bid_ref(), bid_ref)
        self.assertFalse(handler._duplicate_in_progress)

    def test_sql_bid_delete_completion_replaces_unchanged_deleted_selection(self):
        original = BidRef("C:/jobs/test.mdb", "bid-1")
        replacement = BidRef("C:/jobs/test.mdb", "bid-2")
        ui_state = _permissions__DeleteBidUiState(original)
        project_data = self._delete_project_data(remaining_uids=["bid-2"])
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": replacement.bid_uid,
                    "project_uid": None,
                }
            )
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000103",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), replacement)
        self.assertEqual(project_data.clear_bid_calls, [True])

    def test_sql_permanent_bid_delete_queues_delete_and_selects_replacement_on_commit(
        self,
    ):
        class _QueuedPermanentDeleteWriteService(
            _permissions__QueuedHierarchyDeleteWriteService
        ):
            def __init__(self):
                super().__init__()
                self.delete_requests = []

            def queue_bids_delete(self, file_path, uids, callback):
                self.delete_requests.append((file_path, list(uids)))
                self.callbacks.append(callback)

        original = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _permissions__DeleteBidUiState(original)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=["deleted-2"]
        )
        write_service = _QueuedPermanentDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": original.file_path,
                    "bid_uid": "deleted-2",
                    "project_uid": None,
                }
            )
        self.assertEqual(
            write_service.delete_requests, [(original.file_path, ["deleted-1"])]
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), original)
        self.assertEqual(project_data.clear_bid_calls, [])
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000110",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(
            ui_state.get_selected_bid_ref(), BidRef(original.file_path, "deleted-2")
        )
        self.assertEqual(project_data.clear_bid_calls, [True])

    def test_sql_project_delete_completion_does_not_replace_newer_project_selection(
        self,
    ):
        file_path = "C:/jobs/test.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    display_name="test.mdb",
                    bid_projects={
                        "project-delete": HierarchyProjectInfo(name="Delete", bids=[]),
                        "project-keep": HierarchyProjectInfo(name="Keep", bids=[]),
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
            project_exists=lambda project_uid, _file_path: project_uid
            in hierarchy.loaded_files[0].bid_projects,
        )
        ui_state = _permissions__DeleteBidUiState(BidRef(file_path, "unused"))
        ui_state.set_bid_selection(None)
        ui_state.set_file_path(file_path)
        ui_state.set_project_uid("project-delete")
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected()
        self.assertEqual(len(write_service.callbacks), 1)
        ui_state.set_project_uid("project-keep")
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000102",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.selected_file_path, file_path)
        self.assertEqual(ui_state.selected_project_uid, "project-keep")

    def test_sql_project_delete_completion_rejects_same_uid_project_replacement(self):
        file_path = "C:/jobs/test.mdb"
        original_project = HierarchyProjectInfo(name="Delete", bids=[])
        file_entry = HierarchyFileEntry(
            file_path=file_path,
            display_name="test.mdb",
            bid_projects={"project-delete": original_project},
        )
        hierarchy = HierarchyData(loaded_files=[file_entry])
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
            project_exists=lambda project_uid, _file_path: project_uid
            in file_entry.bid_projects,
        )
        ui_state = _permissions__DeleteBidUiState(BidRef(file_path, "unused"))
        ui_state.set_bid_selection(None)
        ui_state.set_file_path(file_path)
        ui_state.set_project_uid("project-delete")
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected()
        self.assertEqual(len(write_service.callbacks), 1)
        file_entry.bid_projects["project-delete"] = HierarchyProjectInfo(
            name="Replacement",
            bids=[],
        )
        self.assertIsNot(
            file_entry.bid_projects["project-delete"],
            original_project,
        )
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000108",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.selected_project_uid, "project-delete")

    def test_sql_project_delete_completion_clears_unchanged_deleted_selection(self):
        file_path = "C:/jobs/test.mdb"
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    display_name="test.mdb",
                    bid_projects={
                        "project-delete": HierarchyProjectInfo(name="Delete", bids=[])
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _project_uid, _file_path=None: False,
            project_exists=lambda project_uid, _file_path: project_uid
            in hierarchy.loaded_files[0].bid_projects,
        )
        ui_state = _permissions__DeleteBidUiState(BidRef(file_path, "unused"))
        ui_state.set_bid_selection(None)
        ui_state.set_file_path(file_path)
        ui_state.set_project_uid("project-delete")
        write_service = _permissions__QueuedHierarchyDeleteWriteService()
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
            )
        )
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.confirm",
            return_value=True,
        ):
            handler.delete_selected()
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000104",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.selected_file_path, file_path)
        self.assertIsNone(ui_state.selected_project_uid)

    def test_permanently_deleting_active_deleted_bid_selects_replacement_before_refresh(
        self,
    ):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=["deleted-2"]
        )
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "bid",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": "deleted-2",
                    "project_uid": None,
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )
        self.assertEqual(
            ui_state.get_selected_bid_ref(), BidRef("C:/jobs/test.mdb", "deleted-2")
        )
        self.assertEqual(project_data.clear_bid_calls, [True])
        self.assertEqual(write_service.selected_bid_during_reload, [None])
        self.assertEqual(
            write_service.selected_bid_during_notify,
            [BidRef("C:/jobs/test.mdb", "deleted-2")],
        )

    def test_permanent_bid_delete_discards_pending_selected_page_before_flush(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=[]
        )
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        deferred = _permissions__DeferredPersistenceRequiringBidCancel(
            "C:/jobs/test.mdb", "deleted-1"
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=deferred,
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected()
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            deferred.cancelled_bid_selected_pages,
            [("C:/jobs/test.mdb", ["deleted-1"])],
        )
        self.assertEqual(deferred.flushes, ["C:/jobs/test.mdb"])
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )

    def test_permanently_deleting_only_deleted_bid_falls_back_before_refresh(self):
        bid_ref = BidRef("C:/jobs/test.mdb", "deleted-1")
        ui_state = _permissions__DeleteBidUiState(bid_ref)
        project_data = self._delete_project_data(
            selected_project_uid="1", remaining_uids=[]
        )
        write_service = _permissions__MoveToDeletedWriteService(ui_state)
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=write_service,
            ui_state_manager=ui_state,
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        from ost_visualizer.presentation.handlers import project_write_handler

        old_confirm = project_write_handler.confirm
        project_write_handler.confirm = lambda _window, _title, _message: True
        try:
            handler.delete_selected(
                {
                    "kind": "project",
                    "file_path": "C:/jobs/test.mdb",
                    "bid_uid": None,
                    "project_uid": "1",
                }
            )
        finally:
            project_write_handler.confirm = old_confirm
        self.assertEqual(
            write_service.delete_calls,
            [("C:/jobs/test.mdb", ["deleted-1"], False)],
        )
        self.assertIsNone(ui_state.get_selected_bid_ref())
        self.assertEqual(ui_state.selected_project_uid, "1")
        self.assertEqual(ui_state.selected_file_path, "C:/jobs/test.mdb")
        self.assertEqual(write_service.selected_bid_during_notify, [None])


class ProjectWriteHandlerStaleTerminalDeliveryTests(unittest.TestCase):
    """A duplicate terminal result of operation A must not act on operation B."""

    def _handler(self):
        self.errors = []
        self.refreshes = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: self.refreshes.append(True),
                present_queued_mutation_error=lambda *args: self.errors.append(args),
            )
        )
        return handler

    @staticmethod
    def _result(status, operation_id):
        return QueuedMutationResult(
            database_id="database-a",
            runtime_generation=1,
            operation_id=operation_id,
            outcome_status=status,
            commit_attempted=status == MutationOutcomeStatus.COMMITTED,
        )

    def _submit(self, handler, callbacks, label):
        events = []
        submitted = handler._submit_sql_hierarchy_operation(
            "database-a",
            ("duplicate_bid", "7"),
            "Duplicate Bid",
            lambda callback: callbacks.append(callback),
            lambda _result: events.append((label, "committed")),
            lambda _result: events.append((label, "failed")),
        )
        self.assertTrue(submitted)
        return events

    def test_duplicate_failure_of_a_finished_operation_leaves_the_same_key_operation(
        self,
    ):
        handler = self._handler()
        callbacks_a, callbacks_b = [], []
        events_a = self._submit(handler, callbacks_a, "A")
        key = ("database-a", "duplicate_bid", "7")
        rejected_a = self._result(
            MutationOutcomeStatus.REJECTED, "00000000-0000-0000-0000-00000000000a"
        )
        callbacks_a[0](rejected_a)
        self.assertEqual(events_a, [("A", "failed")])
        self.assertNotIn(key, handler._pending_sql_operations)
        events_b = self._submit(handler, callbacks_b, "B")
        self.assertIn(key, handler._pending_sql_operations)
        # The terminal result of A is delivered a second time while B runs.
        callbacks_a[0](rejected_a)
        self.assertIn(key, handler._pending_sql_operations)
        self.assertEqual(events_a, [("A", "failed")])
        self.assertEqual(events_b, [])
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(len(self.refreshes), 1)
        # B is still protected against a third submission and ends normally.
        self.assertFalse(
            handler._submit_sql_hierarchy_operation(
                "database-a",
                ("duplicate_bid", "7"),
                "Duplicate Bid",
                lambda callback: self.fail("a pending operation must not resubmit"),
            )
        )
        callbacks_b[0](
            self._result(
                MutationOutcomeStatus.COMMITTED, "00000000-0000-0000-0000-00000000000b"
            )
        )
        self.assertEqual(events_b, [("B", "committed")])
        self.assertNotIn(key, handler._pending_sql_operations)

    def test_duplicate_commit_of_a_finished_operation_is_ignored(self):
        handler = self._handler()
        callbacks_a, callbacks_b = [], []
        events_a = self._submit(handler, callbacks_a, "A")
        committed_a = self._result(
            MutationOutcomeStatus.COMMITTED, "00000000-0000-0000-0000-00000000000a"
        )
        callbacks_a[0](committed_a)
        events_b = self._submit(handler, callbacks_b, "B")
        callbacks_a[0](committed_a)
        self.assertEqual(events_a, [("A", "committed")])
        self.assertEqual(events_b, [])
        self.assertIn(
            ("database-a", "duplicate_bid", "7"), handler._pending_sql_operations
        )


class ProjectWriteHandlerCommittedCallbackFailureTests(
    _coordinator_tests._SecondPassBase
):
    """Decision G4: an exception raised by on_committed is not swallowed by the handler
    and is not lost. The handler lets it propagate; the SQL coordinator (real object
    here, fake store/dispatcher) logs it with its traceback at ERROR and keeps the
    committed operation for recovery; the recovery re-delivery of COMMITTED reaches the
    handler's callback again but must not run on_committed a second time."""

    def _handler(self):
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        self.refreshes, self.errors = [], []
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: self.refreshes.append(True),
                present_queued_mutation_error=lambda *args: self.errors.append(args),
            )
        )
        return handler

    def _submit(self, handler, database_id, on_committed):
        callbacks = []
        self.assertTrue(
            handler._submit_sql_hierarchy_operation(
                database_id,
                ("move_bids", "7"),
                "Move Bids",
                callbacks.append,
                on_committed,
            )
        )
        return callbacks[0], ("database", "move_bids", "7")

    @staticmethod
    def _committed(operation_id="00000000-0000-0000-0000-0000000000c1"):
        return QueuedMutationResult(
            database_id="database",
            runtime_generation=1,
            operation_id=operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            commit_attempted=True,
        )

    def test_failing_on_committed_propagates_and_the_redelivery_does_not_rerun_it(
        self,
    ):
        handler = self._handler()
        calls = []

        def on_committed(result):
            calls.append(result.operation_id)
            raise RuntimeError("on_committed failed")

        complete, key = self._submit(handler, "database", on_committed)
        committed = self._committed()
        # Not swallowed by the handler: the caller (the coordinator) sees it.
        with self.assertRaisesRegex(RuntimeError, "on_committed failed"):
            complete(committed)
        self.assertEqual(calls, [committed.operation_id])
        # The pending marker was released before on_committed ran, so a retry is
        # possible, and no failure presentation was triggered for a committed write.
        self.assertNotIn(key, handler._pending_sql_operations)
        self.assertEqual((self.errors, self.refreshes), ([], []))
        # The coordinator's recovery re-delivers COMMITTED to the same callback.
        complete(committed)
        self.assertEqual(calls, [committed.operation_id])
        self.assertEqual((self.errors, self.refreshes), ([], []))

    def test_the_real_coordinator_logs_a_failing_on_committed_with_its_traceback(self):
        coordinator, runtime = self.ready_coordinator()
        request = _coordinator_tests._placement_request(
            runtime.database_id, "handler-on-committed"
        )
        coordinator._pending_mutations.begin(
            request, runtime_generation=runtime.generation
        )
        handler = self._handler()
        calls = []

        def on_committed(result):
            calls.append(result.operation_id)
            raise RuntimeError("on_committed failed")

        complete, _key = self._submit(handler, runtime.database_id, on_committed)
        committed = QueuedMutationResult(
            database_id=runtime.database_id,
            runtime_generation=runtime.generation,
            operation_id=request.operation_id,
            outcome_status=MutationOutcomeStatus.COMMITTED,
            commit_attempted=True,
        )
        with self.assertLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ) as logged:
            coordinator._complete_mutation_request((complete, committed))
        (record,) = logged.records
        self.assertEqual(
            record.getMessage(), "SQL queued-mutation completion callback failed"
        )
        self.assertEqual(record.levelname, "ERROR")
        self.assertIsInstance(record.exc_info[1], RuntimeError)
        self.assertEqual(str(record.exc_info[1]), "on_committed failed")
        self.assertEqual(calls, [request.operation_id])
        # The committed operation is kept for recovery and re-delivered to the same
        # callback, which the handler ignores.
        stored_request, stored_callback = coordinator._uncertain_callbacks[
            request.operation_id
        ]
        self.assertEqual(stored_request, request)
        with self.assertNoLogs(
            "ost_visualizer.application.services.sql_collaboration_coordinator",
            level="ERROR",
        ):
            coordinator._complete_mutation_request((stored_callback, committed))
        self.assertEqual(calls, [request.operation_id])


class ProjectWriteHandlerLockedActiveBidRefusalTests(unittest.TestCase):
    """Decision Q1: the SQL queue_* move/trash/restore/project-delete entry points raise
    ActiveBidLockedError for the status-locked active Bid. Every project-tree handler
    path (drag move, cut/paste-move, Restore, trash, project delete) treats it as a
    silent refusal: one warning log, no dialog, no failure presentation or refresh (the
    SQL tree is never changed optimistically, so there is nothing to roll back), and the
    pending key is freed so the same operation can be retried. Fake: write service that
    raises (the real gate is tested in ProjectTreeActiveBidMoveParityTests), recording
    coordinator, patched dialogs."""

    DATABASE = "C:/jobs/test.mdb"
    MODULE = "ost_visualizer.presentation.handlers.project_write_handler"

    class _RefusingWriteService:
        def __init__(self, error):
            self.error = error
            self.requests = []

        @staticmethod
        def uses_sql_collaboration_mutations(_database_id):
            return True

        def queue_bids_move(self, database, uids, target, callback, **options):
            self.requests.append(("queue_bids_move", list(uids), target, options))
            raise self.error

        def queue_projects_delete(self, database, uids, callback):
            self.requests.append(("queue_projects_delete", list(uids)))
            raise self.error

    def _handler(self, error):
        self.refreshes, self.errors = [], []
        self.service = self._RefusingWriteService(error)
        bid_ref = BidRef(self.DATABASE, "other-selected")
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=self.DATABASE,
                    display_name="test.mdb",
                    bid_projects={"3": HierarchyProjectInfo(name="Project 3")},
                )
            ]
        )
        project_data = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "3",
            get_bid=lambda _ref: None,
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _uid, _file_path: False,
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=self.service,
            ui_state_manager=_permissions__DeleteBidUiState(bid_ref),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: self.refreshes.append(True),
                present_queued_mutation_error=lambda *args: self.errors.append(args),
            )
        )
        return handler

    def _actions(self, handler):
        bid = BidRef(self.DATABASE, "7")
        return {
            "drag move": lambda: handler.move_bids([bid], "4"),
            "cut paste-move": lambda: handler.paste_bids([bid], "4", is_cut=True),
            "restore": lambda: handler.restore_bids([bid]),
            "trash": lambda: handler.delete_bids([bid]),
            "project delete": lambda: handler.delete_projects(self.DATABASE, ["3"]),
        }

    def _run(self, name, error):
        handler = self._handler(error)
        with patch(f"{self.MODULE}.confirm", return_value=True), patch(
            f"{self.MODULE}.show_warning"
        ) as warning, patch(f"{self.MODULE}.show_critical") as critical:
            if error is None:
                result = self._actions(handler)[name]()
            else:
                with self.assertLogs(self.MODULE, level="WARNING") as logged:
                    result = self._actions(handler)[name]()
                self.logged = logged
        return handler, result, warning, critical

    def test_locked_active_bid_refusal_is_silent_and_frees_the_pending_key(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )

        for name in (
            "drag move",
            "cut paste-move",
            "restore",
            "trash",
            "project delete",
        ):
            with self.subTest(action=name):
                handler, result, warning, critical = self._run(
                    name, ActiveBidLockedError()
                )
                self.assertEqual(len(self.service.requests), 1)
                warning.assert_not_called()
                critical.assert_not_called()
                self.assertEqual((self.errors, self.refreshes), ([], []))
                self.assertEqual(handler._pending_sql_operations, set())
                self.assertEqual(len(self.logged.records), 1)
                self.assertEqual(self.logged.records[0].levelname, "WARNING")
                self.assertIn("locked", self.logged.records[0].getMessage())
                if name in ("drag move", "cut paste-move"):
                    self.assertIs(result, False)

    def test_other_runtime_errors_still_warn_and_free_the_pending_key(self):
        # Positive control: only ActiveBidLockedError is silent. A different
        # RuntimeError of the same submission keeps the visible warning dialog.
        handler = self._handler(RuntimeError("queue unavailable"))
        with patch(f"{self.MODULE}.show_warning") as warning:
            self.assertIs(handler.move_bids([BidRef(self.DATABASE, "7")], "4"), False)
        warning.assert_called_once_with(None, "Move Bids", "queue unavailable")
        self.assertEqual(handler._pending_sql_operations, set())

    def test_refused_move_can_be_resubmitted_once_the_lock_is_gone(self):
        from ost_visualizer.application.dtos.active_bid_locked_error import (
            ActiveBidLockedError,
        )

        handler, _result, _warning, _critical = self._run(
            "drag move", ActiveBidLockedError()
        )
        self.service.error = None

        def accept(database, uids, target, callback, **options):
            self.service.requests.append(("queue_bids_move", list(uids), target))

        self.service.queue_bids_move = accept
        self.assertTrue(handler.move_bids([BidRef(self.DATABASE, "7")], "4"))
        self.assertEqual(len(self.service.requests), 2)
        self.assertEqual(
            handler._pending_sql_operations, {(self.DATABASE, "move_bids", "7")}
        )


class ProjectWriteHandlerBidLockedRejectionTests(unittest.TestCase):
    """Decision B4 at the project-tree handler: a queued SQL hierarchy write (bid move,
    project delete) that the SQL writer refused with REJECTED / bid_locked takes the
    handler's normal non-committed branch (projection refresh, failure callback, pending
    key released once) but opens no dialog because the real
    present_queued_mutation_error is silent for the reason; a rejection WITHOUT the
    reason keeps its warning dialog. Real handler and real coordinator method; the
    write service queues, the test delivers."""

    DATABASE = "C:/jobs/test.mdb"
    MODULE = "ost_visualizer.presentation.handlers.project_write_handler"
    COORDINATOR = "ost_visualizer.presentation.coordinators.ui_event_coordinator"

    def _handler(self):
        from ost_visualizer.presentation.coordinators.ui_event_coordinator import (
            UIEventCoordinator,
        )

        self.callbacks, self.refreshes, self.prepared = [], [], []

        class Service:
            @staticmethod
            def uses_sql_collaboration_mutations(_database_id):
                return True

            @staticmethod
            def queue_bids_move(database, uids, target, callback, **options):
                callbacks.append(callback)
                return 1

            @staticmethod
            def queue_projects_delete(database, uids, callback):
                callbacks.append(callback)
                return 1

        callbacks = self.callbacks
        presenter = UIEventCoordinator.__new__(UIEventCoordinator)
        presenter._is_cleaning_up = False
        presenter.main_window = "main-window"
        presenter._prepare_for_modal_mutation_error = self.prepared.append
        bid_ref = BidRef(self.DATABASE, "other-selected")
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=self.DATABASE,
                    display_name="test.mdb",
                    bid_projects={"3": HierarchyProjectInfo(name="Project 3")},
                )
            ]
        )
        project_data = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "3",
            get_bid=lambda _ref: None,
            get_hierarchy=lambda: hierarchy,
            project_has_bids=lambda _uid, _file_path: False,
        )
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=Service(),
            ui_state_manager=_permissions__DeleteBidUiState(bid_ref),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        coordinator = SimpleNamespace(
            refresh_hierarchy_projection=lambda: self.refreshes.append(True),
            present_queued_mutation_error=presenter.present_queued_mutation_error,
        )
        handler.set_ui_event_coordinator(coordinator)
        return handler

    @staticmethod
    def _rejection(bid_locked=True):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            MutationRejectionReason,
            QueuedMutationResult,
        )

        return QueuedMutationResult(
            database_id="C:/jobs/test.mdb",
            runtime_generation=2,
            operation_id="00000000-0000-4000-8000-0000000000dd",
            outcome_status=MutationOutcomeStatus.REJECTED,
            message="The active bid is locked" if bid_locked else "busy",
            rejection_reason=MutationRejectionReason.BID_LOCKED if bid_locked else None,
        )

    def _actions(self, handler):
        bid = BidRef(self.DATABASE, "7")
        return {
            "drag move": lambda: handler.move_bids([bid], "4"),
            "project delete": lambda: handler.delete_projects(self.DATABASE, ["3"]),
        }

    def test_a_rejected_hierarchy_write_refreshes_once_and_shows_no_dialog(self):
        for name in ("drag move", "project delete"):
            with self.subTest(action=name):
                handler = self._handler()
                with patch(f"{self.MODULE}.confirm", return_value=True):
                    self._actions(handler)[name]()
                self.assertEqual(len(self.callbacks), 1)
                self.assertEqual(len(handler._pending_sql_operations), 1)
                with patch(f"{self.COORDINATOR}.show_warning") as warning, patch(
                    f"{self.COORDINATOR}.show_critical"
                ) as critical, patch(
                    f"{self.MODULE}.show_warning"
                ) as handler_warning, patch(
                    f"{self.MODULE}.show_critical"
                ) as handler_critical:
                    self.callbacks[0](self._rejection())
                    self.callbacks[0](self._rejection())
                for dialog in (warning, critical, handler_warning, handler_critical):
                    dialog.assert_not_called()
                self.assertEqual(self.refreshes, [True])
                self.assertEqual(self.prepared, [])
                self.assertEqual(handler._pending_sql_operations, set())

    def test_a_rejection_without_the_reason_keeps_its_warning_dialog(self):
        handler = self._handler()
        with patch(f"{self.MODULE}.confirm", return_value=True):
            self._actions(handler)["drag move"]()
        with patch(f"{self.COORDINATOR}.show_warning") as warning:
            self.callbacks[0](self._rejection(bid_locked=False))
        warning.assert_called_once_with("main-window", "Move Bids", "busy")
        self.assertEqual(self.refreshes, [True])
        self.assertEqual(self.prepared, [self.DATABASE])
        self.assertEqual(handler._pending_sql_operations, set())


class ProjectWriteHandlerLockedBidDuplicateTests(unittest.TestCase):
    """Decision B6 (risk 2) at the project-tree handler: duplicating the ACTIVE,
    status-locked Bid works end to end on the SQL queue path. Real ProjectWriteHandler
    and the real ProjectWriteService with its client-side guard (harness executor and
    queue provider of the service tests): the duplicate is queued, not refused, no
    dialog opens, the busy flag and pending key are held while it runs and released
    when it commits."""

    MODULE = "ost_visualizer.presentation.handlers.project_write_handler"

    def test_a_locked_active_bid_can_be_duplicated(self):
        from tests.application.services.test_project_write_service import (
            _Harness,
            _Seq,
        )

        harness = _Harness({"duplicate_bid": _Seq("12")})
        harness.data.locked = True
        database = _Harness.DATABASE
        bid_ref = BidRef(database, "7")
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=database,
                    display_name="test.mdb",
                    bid_projects={
                        "4": HierarchyProjectInfo(
                            name="Project 4",
                            bids=[HierarchyBidInfo(uid="7", name="Locked source")],
                        )
                    },
                )
            ]
        )
        project_data = SimpleNamespace(
            find_project_uid_for_bid=lambda _ref: "4",
            get_hierarchy=lambda: hierarchy,
        )
        toolbar_refreshes = []
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=project_data,
            project_write_service=harness.service,
            ui_state_manager=_permissions__DeleteBidUiState(bid_ref),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_toolbar=lambda: toolbar_refreshes.append(True),
                refresh_hierarchy_projection=lambda: self.fail("no refresh expected"),
                present_queued_mutation_error=lambda *args: self.fail(
                    "no error expected"
                ),
            )
        )
        with patch(f"{self.MODULE}.show_warning") as warning, patch(
            f"{self.MODULE}.show_critical"
        ) as critical:
            handler.duplicate_bid(bid_ref)
            self.assertEqual(len(harness.provider.requests), 1)
            queued, execute, callback = harness.provider.requests[-1]
            self.assertEqual(
                {(r.resource_type, r.resource_id) for r in queued.resources},
                {("bid", "7")},
            )
            self.assertEqual(
                {(r.resource_type, r.resource_id) for r in queued.dependency_resources},
                {("project_bids", "4")},
            )
            self.assertIs(handler._duplicate_in_progress, True)
            self.assertEqual(
                handler._pending_sql_operations, {(database, "duplicate_bid", "7")}
            )
            execution = execute()
            self.assertEqual(execution.outcome_status, MutationOutcomeStatus.COMMITTED)
            callback(
                QueuedMutationResult(
                    database_id=database,
                    runtime_generation=1,
                    operation_id=queued.operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                    created_resource_ids=("12",),
                    commit_attempted=True,
                )
            )
        warning.assert_not_called()
        critical.assert_not_called()
        self.assertIs(handler._duplicate_in_progress, False)
        self.assertEqual(handler._pending_sql_operations, set())
        self.assertEqual(toolbar_refreshes, [True])


import contextlib
import gc
import weakref
from unittest import mock
from ost_visualizer.presentation.utils.messagebox import DB_LOCKED_HINT
from ost_visualizer.application.dtos.active_bid_locked_error import (
    ActiveBidLockedError as _SecondPassActiveBidLockedError,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult as _SecondPassAuthoritativeMutationResult,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo as _SecondPassHierarchyBidInfo,
)

_PWH_MODULE = "ost_visualizer.presentation.handlers.project_write_handler"


class _SecondPassHierarchy:
    """A real ProjectWriteHandler over strict recording fakes (no live SQL Server, no
    real queue, no Qt progress dialog): every write-service call is recorded with its
    exact positional and keyword arguments, queued callbacks are kept for delivery,
    Access results are scripted per method, and selection changes are recorded."""

    DB = "C:/jobs/a.mdb"

    def __init__(self, *, sql, flush_ok=True, window="window"):
        self.sql = sql
        self.calls = []
        self.callbacks = []
        self.script = {}
        self.errors = []
        self.refreshes = []
        self.toolbar = []
        self.selection = []
        self.flushes = []
        self.cancelled = []
        self.cancelled_files = []
        self.cleared = []
        self.reports = []
        self.flush_ok = flush_ok
        self.selected_bid = None
        self.selected_bids = []
        self.selected_projects = []
        self.selected_project_file = None
        self.project_of = {}
        self.bid_info = {}
        self.owner = {}
        self.deleted_project_ids = set()
        self.projects_with_bids = set()
        self.loaded = {self.DB: {"project-1": object(), "project-2": object()}}
        self.progress = []
        self.busy_during = []
        self.progress_rc = QtWidgets.QDialog.DialogCode.Accepted
        harness = self

        class Write:
            def uses_sql_collaboration_mutations(self, _file_path):
                return harness.sql

            def _record(self, name, args, kwargs):
                harness.calls.append((name, args, kwargs))

            def _queue(self, name, args, kwargs):
                self._record(name, args[:-1], kwargs)
                harness.callbacks.append(args[-1])
                if name in harness.script and isinstance(
                    harness.script[name], BaseException
                ):
                    raise harness.script[name]
                return len(harness.callbacks)

            def queue_project_rename(self, *args, **kw):
                return self._queue("queue_project_rename", args, kw)

            def queue_project_create(self, *args, **kw):
                return self._queue("queue_project_create", args, kw)

            def queue_bid_job_status_update(self, *args, **kw):
                return self._queue("queue_bid_job_status_update", args, kw)

            def queue_bids_move(self, *args, **kw):
                return self._queue("queue_bids_move", args, kw)

            def queue_bids_duplicate(self, *args, **kw):
                return self._queue("queue_bids_duplicate", args, kw)

            def queue_bids_delete(self, *args, **kw):
                return self._queue("queue_bids_delete", args, kw)

            def queue_projects_delete(self, *args, **kw):
                return self._queue("queue_projects_delete", args, kw)

            def _scripted(self, name, args, kwargs, default=True):
                self._record(name, args, kwargs)
                outcomes = harness.script.get(name, default)
                if isinstance(outcomes, list):
                    return outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
                return outcomes

            def rename_project(self, *args, **kw):
                return self._scripted("rename_project", args, kw)

            def update_bid_job_status(self, *args, **kw):
                return self._scripted("update_bid_job_status", args, kw)

            def move_bids(self, *args, **kw):
                return self._scripted("move_bids", args, kw)

            def delete_bids(self, *args, **kw):
                return self._scripted("delete_bids", args, kw)

            def delete_projects(self, *args, **kw):
                return self._scripted("delete_projects", args, kw)

            def duplicate_bid(self, *args, **kw):
                return self._scripted("duplicate_bid", args, kw, default="copy")

            def duplicate_bid_result(self, *args, **kw):
                return self._scripted(
                    "duplicate_bid_result",
                    args,
                    kw,
                    default=WriteReloadResult("copy", True, True),
                )

            def reload_database(self, *args, **kw):
                return self._scripted("reload_database", args, kw)

            def notify_database_refreshed(self, *args, **kw):
                self._record("notify_database_refreshed", args, kw)

        class Data:
            def find_project_uid_for_bid(self, ref):
                return harness.project_of.get(ref.bid_uid, "project-1")

            def get_hierarchy(self):
                return SimpleNamespace(
                    find_bid_info=lambda ref: harness.bid_info.get(ref.bid_uid),
                    loaded_files=[
                        SimpleNamespace(file_path=path, bid_projects=projects)
                        for path, projects in harness.loaded.items()
                    ],
                )

            def get_current_file_path(self):
                return harness.DB

            def get_bid(self, ref):
                return harness.owner.get(ref.bid_uid)

            def clear_bid(self):
                harness.cleared.append(True)

            def project_exists(self, project_uid, file_path):
                return project_uid in harness.loaded.get(file_path, {})

            def project_has_bids(self, project_uid, file_path):
                return project_uid in harness.projects_with_bids

        class Ui:
            @property
            def selected_project_uids(self):
                return harness.selected_projects

            @property
            def selected_project_file_path(self):
                return harness.selected_project_file

            def get_selected_bid_ref(self):
                return harness.selected_bid

            def get_selected_bid_refs(self):
                return harness.selected_bids

            def set_bid_selection(self, ref):
                harness.selection.append(("bid", ref))
                harness.selected_bid = ref

            def set_file_path(self, path):
                harness.selection.append(("file", path))

            def set_project_uid(self, uid):
                harness.selection.append(("project", uid))

            def set_database_selected(self, flag, path):
                harness.selection.append(("database", flag, path))

        class Deferred:
            def flush_for_file(self, file_path):
                harness.flushes.append(file_path)
                return harness.flush_ok

            def cancel_bid_selected_pages(self, file_path, uids):
                harness.cancelled.append((file_path, list(uids)))

            def cancel_bid_selected_pages_for_file(self, file_path):
                harness.cancelled_files.append(file_path)

        class Coordinator:
            def refresh_hierarchy_projection(self):
                harness.refreshes.append(True)

            def present_queued_mutation_error(self, database_id, title, result):
                harness.errors.append((database_id, title, result))

            def refresh_toolbar(self):
                harness.toolbar.append(True)

        self.write = Write()
        self.data = Data()
        self.ui = Ui()
        self.handler = ProjectWriteHandler(
            window=window,
            project_data_service=self.data,
            project_write_service=self.write,
            ui_state_manager=self.ui,
            deferred_persistence_manager=Deferred(),
        )
        self.handler.set_ui_event_coordinator(Coordinator())

        def run_progress(label, task_fn, action_text, reporter):
            harness.progress.append((label, action_text))
            harness.busy_during.append(harness.handler._duplicate_in_progress)
            reporter.progress.connect(harness.reports.append)
            worker_error = harness.script.get("worker_error")
            result = None if worker_error else task_fn()
            return harness.progress_rc, result, worker_error

        self.handler._run_progress_dialog = run_progress

    def names(self):
        return [name for name, _args, _kwargs in self.calls]

    def call(self, name):
        return [(args, kwargs) for n, args, kwargs in self.calls if n == name]

    @staticmethod
    def result(status=MutationOutcomeStatus.COMMITTED, **fields):
        return QueuedMutationResult(
            database_id=_SecondPassHierarchy.DB,
            runtime_generation=1,
            operation_id="00000000-0000-4000-8000-0000000000e1",
            outcome_status=status,
            **fields,
        )

    def patched(self):
        stack = contextlib.ExitStack()
        self.confirm = stack.enter_context(
            patch(f"{_PWH_MODULE}.confirm", return_value=True)
        )
        self.warning = stack.enter_context(patch(f"{_PWH_MODULE}.show_warning"))
        self.critical = stack.enter_context(patch(f"{_PWH_MODULE}.show_critical"))
        return stack


class ProjectWriteHandlerSecondPassSubmitTests(unittest.TestCase):
    """_submit_sql_hierarchy_operation: the pending key is freed on every terminal path
    and the failure presentation order is refresh, present, callback."""

    def test_the_handler_needs_its_coordinator_before_it_queues_anything(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.handler._ui_event_coordinator = None
        with self.assertRaisesRegex(RuntimeError, "not fully initialized"):
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("x",), "Title", lambda callback: self.fail("queued")
            )
        self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_a_pending_operation_is_not_submitted_twice_and_the_key_is_stringified(
        self,
    ):
        harness = _SecondPassHierarchy(sql=True)
        submitted = []
        self.assertTrue(
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op", 7), "Title", submitted.append
            )
        )
        self.assertEqual(
            harness.handler._pending_sql_operations, {(harness.DB, "op", "7")}
        )
        self.assertIs(
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op", "7"), "Title", self.fail
            ),
            False,
        )
        self.assertEqual(len(submitted), 1)

    def test_a_failed_terminal_refreshes_then_presents_then_runs_the_callback(self):
        harness = _SecondPassHierarchy(sql=True)
        order = []
        harness.handler._ui_event_coordinator = SimpleNamespace(
            refresh_hierarchy_projection=lambda: order.append("refresh"),
            present_queued_mutation_error=lambda *args: order.append(("present", args)),
        )
        callbacks = []
        self.assertTrue(
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB,
                ("op",),
                "Title",
                callbacks.append,
                lambda _result: order.append("committed"),
                lambda result: order.append(("failed", result)),
            )
        )
        rejected = harness.result(MutationOutcomeStatus.CONFLICT)
        callbacks[0](rejected)
        self.assertEqual(
            order,
            [
                "refresh",
                ("present", (harness.DB, "Title", rejected)),
                ("failed", rejected),
            ],
        )

    def test_a_collected_handler_ignores_a_late_terminal_result(self):
        callbacks, committed = [], []

        def build():
            harness = _SecondPassHierarchy(sql=True)
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op",), "Title", callbacks.append, committed.append
            )
            return weakref.ref(harness.handler)

        handler_ref = build()
        gc.collect()
        self.assertIsNone(handler_ref())
        callbacks[0](_SecondPassHierarchy.result())
        self.assertEqual(committed, [])

    def test_a_locked_submission_is_silent_and_runs_the_failure_callback_with_none(
        self,
    ):
        harness = _SecondPassHierarchy(sql=True)
        failed, committed = [], []

        def refuse(_callback):
            raise _SecondPassActiveBidLockedError()

        with harness.patched(), self.assertLogs(_PWH_MODULE, "WARNING") as logged:
            started = harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op",), "Title", refuse, committed.append, failed.append
            )
        self.assertIs(started, False)
        self.assertEqual((failed, committed), ([None], []))
        self.assertEqual(harness.handler._pending_sql_operations, set())
        harness.warning.assert_not_called()
        self.assertEqual(
            logged.output,
            [f"WARNING:{_PWH_MODULE}:Title blocked: the active bid is locked"],
        )

    def test_other_refused_submissions_warn_once_and_run_the_failure_callback(self):
        for error in (RuntimeError("queue closed"), ValueError("bad value")):
            with self.subTest(error=type(error).__name__):
                harness = _SecondPassHierarchy(sql=True)
                failed, committed = [], []

                def refuse(_callback, error=error):
                    raise error

                with harness.patched(), patch(f"{_PWH_MODULE}.logger") as logger:
                    started = harness.handler._submit_sql_hierarchy_operation(
                        harness.DB,
                        ("op",),
                        "Title",
                        refuse,
                        committed.append,
                        failed.append,
                    )
                self.assertIs(started, False)
                self.assertEqual((failed, committed), ([None], []))
                self.assertEqual(harness.handler._pending_sql_operations, set())
                harness.warning.assert_called_once_with("window", "Title", str(error))
                logger.warning.assert_not_called()

    def test_an_unexpected_submit_failure_frees_the_key_and_propagates(self):
        harness = _SecondPassHierarchy(sql=True)

        def broken(_callback):
            raise LookupError("unexpected queue failure")

        with self.assertRaises(LookupError):
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op",), "Title", broken
            )
        self.assertEqual(harness.handler._pending_sql_operations, set())
        self.assertTrue(
            harness.handler._submit_sql_hierarchy_operation(
                harness.DB, ("op",), "Title", lambda _callback: None
            )
        )

    def test_a_failing_sql_duplicate_submission_does_not_leave_the_busy_flag_set(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.selected_bid = BidRef(harness.DB, "7")
        harness.script["queue_bids_duplicate"] = LookupError("unexpected")
        with self.assertRaises(LookupError):
            harness.handler.duplicate_selected()
        self.assertIs(harness.handler._duplicate_in_progress, False)
        self.assertEqual(harness.handler._pending_sql_operations, set())


class ProjectWriteHandlerSecondPassCommandTests(unittest.TestCase):
    """The simple project-tree commands on both backends, side by side: the exact write
    call, the pending key and title, and what the user sees when the write fails."""

    def test_rename_project_normalizes_the_name_and_picks_the_database(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                with harness.patched():
                    self.assertIs(
                        harness.handler.rename_project("p9", "  New name \n", None),
                        True,
                    )
                self.assertEqual(harness.flushes, [harness.DB])
                if sql:
                    self.assertEqual(
                        harness.call("queue_project_rename"),
                        [((harness.DB, "p9", "New name"), {})],
                    )
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {(harness.DB, "rename_project", "p9")},
                    )
                else:
                    self.assertEqual(
                        harness.call("rename_project"),
                        [((harness.DB, "p9", "New name"), {})],
                    )
                harness.critical.assert_not_called()

    def test_rename_project_prefers_the_given_database_path(self):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            self.assertIs(
                harness.handler.rename_project("p9", "N", "C:/jobs/other.mdb"), True
            )
        self.assertEqual(harness.flushes, ["C:/jobs/other.mdb"])
        self.assertEqual(
            harness.call("rename_project"), [(("C:/jobs/other.mdb", "p9", "N"), {})]
        )

    def test_rename_project_refuses_blank_names_and_unsaved_pending_changes(self):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            for name in ("", "   \t"):
                self.assertIs(harness.handler.rename_project("p9", name, None), False)
            self.assertEqual((harness.flushes, harness.calls), ([], []))
            harness.flush_ok = False
            self.assertIs(harness.handler.rename_project("p9", "N", None), False)
        self.assertEqual(harness.flushes, [harness.DB])
        self.assertEqual(harness.calls, [])
        harness.critical.assert_not_called()

    def test_rename_project_without_any_database_path_does_nothing(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.data.get_current_file_path = lambda: ""
        with harness.patched():
            self.assertIs(harness.handler.rename_project("p9", "N", ""), False)
        self.assertEqual((harness.flushes, harness.calls), ([], []))

    def test_access_rename_failure_opens_one_critical_dialog(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["rename_project"] = False
        with harness.patched():
            self.assertIs(harness.handler.rename_project("p9", "N", None), False)
        harness.critical.assert_called_once_with(
            "window", "Rename Error", f"Failed to rename project. {DB_LOCKED_HINT}"
        )

    def test_sql_rename_refused_while_the_same_rename_is_pending(self):
        harness = _SecondPassHierarchy(sql=True)
        with harness.patched():
            self.assertIs(harness.handler.rename_project("p9", "A", None), True)
            self.assertIs(harness.handler.rename_project("p9", "B", None), False)
            self.assertIs(harness.handler.rename_project("p8", "B", None), True)
        self.assertEqual(len(harness.call("queue_project_rename")), 2)

    def test_create_project_is_sql_only(self):
        harness = _SecondPassHierarchy(sql=False)
        with self.assertRaisesRegex(ValueError, "only available for SQL"):
            harness.handler.create_project(harness.DB, "Name", lambda uid: None)
        self.assertEqual(harness.calls, [])

    def test_create_project_reports_only_exactly_one_created_id(self):
        harness = _SecondPassHierarchy(sql=True)
        created = []
        self.assertIs(
            harness.handler.create_project(harness.DB, "Name", created.append), True
        )
        self.assertEqual(
            harness.call("queue_project_create"), [((harness.DB, "Name"), {})]
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {(harness.DB, "create_project", "Name")},
        )
        self.assertIs(
            harness.handler.create_project(harness.DB, "Name", created.append), False
        )
        for authoritative in (
            None,
            _SecondPassAuthoritativeMutationResult(),
            _SecondPassAuthoritativeMutationResult(created_resource_ids=("1", "2")),
        ):
            harness.callbacks.clear()
            harness.handler._pending_sql_operations.clear()
            harness.handler.create_project(harness.DB, "Name", created.append)
            harness.callbacks[0](harness.result(authoritative_result=authoritative))
        self.assertEqual(created, [])
        harness.callbacks.clear()
        harness.handler._pending_sql_operations.clear()
        harness.handler.create_project(harness.DB, "Name", created.append)
        harness.callbacks[0](
            harness.result(
                authoritative_result=_SecondPassAuthoritativeMutationResult(
                    created_resource_ids=("42",)
                )
            )
        )
        self.assertEqual(created, ["42"])

    def test_update_bid_job_status_ignores_incomplete_references_and_failed_flush(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            for ref in (None, BidRef("", "7"), BidRef(harness.DB, "")):
                harness.handler.update_bid_job_status(ref, "status")
            self.assertEqual((harness.flushes, harness.calls), ([], []))
            harness.flush_ok = False
            harness.handler.update_bid_job_status(BidRef(harness.DB, "7"), "status")
        self.assertEqual(harness.flushes, [harness.DB])
        self.assertEqual(harness.calls, [])
        harness.critical.assert_not_called()

    def test_update_bid_job_status_writes_through_the_backend_queue(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                with harness.patched():
                    harness.handler.update_bid_job_status(
                        BidRef(harness.DB, "7"), "status-3"
                    )
                    harness.critical.assert_not_called()
                    if sql:
                        self.assertEqual(
                            harness.call("queue_bid_job_status_update"),
                            [((harness.DB, "7", "status-3"), {})],
                        )
                        self.assertEqual(
                            harness.handler._pending_sql_operations,
                            {(harness.DB, "bid_job_status", "7")},
                        )
                        harness.handler.update_bid_job_status(
                            BidRef(harness.DB, "7"), "status-4"
                        )
                        self.assertEqual(
                            len(harness.call("queue_bid_job_status_update")), 1
                        )
                    else:
                        self.assertEqual(
                            harness.call("update_bid_job_status"),
                            [((harness.DB, "7", "status-3"), {})],
                        )

    def test_access_job_status_failure_opens_one_critical_dialog(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["update_bid_job_status"] = False
        with harness.patched():
            harness.handler.update_bid_job_status(BidRef(harness.DB, "7"), "s")
        harness.critical.assert_called_once_with(
            "window", "Job Status", f"Failed to change job status. {DB_LOCKED_HINT}"
        )

    def test_move_bids_groups_by_database_in_argument_order(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                other = "C:/jobs/b.mdb"
                refs = [
                    BidRef(harness.DB, "1"),
                    BidRef(other, "2"),
                    BidRef(harness.DB.upper(), "3"),
                ]
                with harness.patched():
                    self.assertIs(harness.handler.move_bids([], "p"), True)
                    self.assertEqual(harness.calls, [])
                    self.assertIs(harness.handler.move_bids(refs, "project-9"), True)
                name = "queue_bids_move" if sql else "move_bids"
                self.assertEqual(
                    harness.call(name),
                    [
                        ((harness.DB, ["1", "3"], "project-9"), {}),
                        ((other, ["2"], "project-9"), {}),
                    ],
                )
                self.assertEqual(harness.flushes, [harness.DB, other])
                harness.critical.assert_not_called()

    def test_move_bids_flush_failure_and_write_failure_stop_the_remaining_databases(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        refs = [BidRef(harness.DB, "1"), BidRef("C:/jobs/b.mdb", "2")]
        with harness.patched():
            harness.flush_ok = False
            self.assertIs(harness.handler.move_bids(refs, "p"), False)
            self.assertEqual((harness.flushes, harness.calls), ([harness.DB], []))
            harness.flush_ok = True
            harness.script["move_bids"] = False
            self.assertIs(harness.handler.move_bids(refs, "p"), False)
        self.assertEqual(len(harness.call("move_bids")), 1)
        harness.critical.assert_called_once_with(
            "window", "Move Error", f"Failed to move bids. {DB_LOCKED_HINT}"
        )

    def test_sql_move_bids_stops_when_a_submission_is_refused(self):
        harness = _SecondPassHierarchy(sql=True)
        refs = [BidRef(harness.DB, "1"), BidRef("C:/jobs/b.mdb", "2")]
        harness.script["queue_bids_move"] = RuntimeError("queue closed")
        with harness.patched():
            self.assertIs(harness.handler.move_bids(refs, "p"), False)
        self.assertEqual(len(harness.call("queue_bids_move")), 1)
        harness.warning.assert_called_once_with("window", "Move Bids", "queue closed")

    def test_paste_bids_sql_queues_a_move_for_cut_and_a_duplicate_for_copy(self):
        refs = [BidRef("C:/jobs/a.mdb", "1"), BidRef("c:\\jobs\\a.mdb", "2")]
        harness = _SecondPassHierarchy(sql=True)
        cut_done = []
        with harness.patched():
            self.assertIs(harness.handler.paste_bids([], "p"), True)
            self.assertIs(
                harness.handler.paste_bids(refs + [BidRef("C:/jobs/b.mdb", "3")], "p"),
                False,
            )
            self.assertEqual(harness.calls, [])
            self.assertIs(harness.handler.paste_bids(refs, "project-9"), True)
            self.assertIs(
                harness.handler.paste_bids(
                    refs,
                    "project-9",
                    is_cut=True,
                    on_cut_committed=lambda: cut_done.append(True),
                ),
                True,
            )
        self.assertEqual(
            harness.call("queue_bids_duplicate"),
            [(("C:/jobs/a.mdb", ["1", "2"], "project-9"), {})],
        )
        self.assertEqual(
            harness.call("queue_bids_move"),
            [(("C:/jobs/a.mdb", ["1", "2"], "project-9"), {})],
        )
        self.assertEqual(
            harness.handler._pending_sql_operations,
            {
                ("C:/jobs/a.mdb", "paste_duplicate_bids", "1", "2"),
                ("C:/jobs/a.mdb", "paste_move_bids", "1", "2"),
            },
        )
        harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
        harness.callbacks[1](harness.result())
        self.assertEqual(cut_done, [True])
        self.assertEqual(
            [(database, title) for database, title, _result in harness.errors],
            [("C:/jobs/a.mdb", "Paste Bids")],
        )

    def test_paste_bids_cut_without_a_completion_callback_still_commits(self):
        harness = _SecondPassHierarchy(sql=True)
        with harness.patched():
            self.assertIs(
                harness.handler.paste_bids([BidRef(harness.DB, "1")], "p", is_cut=True),
                True,
            )
        harness.callbacks[0](harness.result())
        self.assertEqual(harness.handler._pending_sql_operations, set())
        self.assertEqual(harness.errors, [])

    def test_paste_bids_flush_failure_queues_nothing(self):
        for sql in (True, False):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql, flush_ok=False)
                with harness.patched():
                    self.assertIs(
                        harness.handler.paste_bids([BidRef(harness.DB, "1")], "p"),
                        False,
                    )
                self.assertEqual(harness.calls, [])
                self.assertEqual(harness.progress, [])
                self.assertEqual(harness.flushes, [harness.DB])

    def test_restore_bids_groups_by_original_project_and_uses_the_trash_marker(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                harness.bid_info = {
                    "1": SimpleNamespace(orig_bid_project_uid="project-2"),
                    "2": SimpleNamespace(orig_bid_project_uid="project-3"),
                    "3": SimpleNamespace(orig_bid_project_uid="project-2"),
                }
                refs = [BidRef(harness.DB, uid) for uid in ("1", "2", "3", "4")]
                with harness.patched():
                    harness.handler.restore_bids(refs)
                if sql:
                    marker = {"original_project_uid": "1"}
                    self.assertEqual(
                        harness.call("queue_bids_move"),
                        [
                            ((harness.DB, ["1", "3"], "project-2"), marker),
                            ((harness.DB, ["2"], "project-3"), marker),
                            ((harness.DB, ["4"], None), marker),
                        ],
                    )
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {
                            (harness.DB, "restore_bids", "1", "3"),
                            (harness.DB, "restore_bids", "2"),
                            (harness.DB, "restore_bids", "4"),
                        },
                    )
                else:
                    self.assertEqual(
                        harness.call("move_bids"),
                        [
                            ((harness.DB, ["1", "3"], "project-2"), {}),
                            ((harness.DB, ["2"], "project-3"), {}),
                            ((harness.DB, ["4"], None), {}),
                        ],
                    )

    def test_restore_bids_stops_on_a_flush_or_write_failure(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.bid_info = {
            "1": SimpleNamespace(orig_bid_project_uid="project-2"),
            "2": SimpleNamespace(orig_bid_project_uid="project-3"),
        }
        refs = [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")]
        with harness.patched():
            harness.flush_ok = False
            harness.handler.restore_bids(refs)
            self.assertEqual(harness.calls, [])
            harness.flush_ok = True
            harness.script["move_bids"] = False
            harness.handler.restore_bids(refs)
        self.assertEqual(len(harness.call("move_bids")), 1)
        harness.critical.assert_called_once_with(
            "window", "Restore Error", f"Failed to restore bids. {DB_LOCKED_HINT}"
        )

    def test_delete_selected_routes_bids_before_projects_and_ignores_empty_selection(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        routed = []
        harness.handler._delete_bids = lambda refs, selection: routed.append(
            ("bids", list(refs), selection)
        )
        harness.handler._delete_projects = lambda uids, path: routed.append(
            ("projects", list(uids), path)
        )
        harness.handler.delete_selected({"kind": "database"})
        self.assertEqual(routed, [])
        harness.selected_projects = ["p1"]
        harness.selected_project_file = harness.DB
        harness.handler.delete_selected()
        harness.selected_bids = [BidRef(harness.DB, "1")]
        harness.handler.delete_selected({"kind": "database"})
        self.assertEqual(
            routed,
            [
                ("projects", ["p1"], harness.DB),
                ("bids", [BidRef(harness.DB, "1")], {"kind": "database"}),
            ],
        )
        routed.clear()
        harness.handler.delete_bids([BidRef(harness.DB, "2")], None)
        harness.handler.delete_projects(harness.DB, ["p9"])
        self.assertEqual(
            routed,
            [
                ("bids", [BidRef(harness.DB, "2")], None),
                ("projects", ["p9"], harness.DB),
            ],
        )

    def test_delete_projects_skips_the_trash_and_projects_with_bids(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                harness.projects_with_bids = {"busy"}
                with harness.patched():
                    harness.handler._delete_projects(["1", "busy", "empty"], None)
                    self.assertEqual(harness.calls, [])
                    harness.handler._delete_projects(["1", "busy", "empty"], harness.DB)
                harness.warning.assert_called_once_with(
                    "window",
                    "Cannot Delete Project",
                    "Some selected projects still have bids inside.\n"
                    "Only empty projects can be deleted.",
                )
                harness.confirm.assert_called_once_with(
                    "window",
                    "Delete Projects",
                    "Permanently delete this empty project?\nThis cannot be undone.",
                )
                self.assertEqual(harness.cancelled_files, [harness.DB])
                self.assertEqual(harness.flushes, [harness.DB])
                name = "queue_projects_delete" if sql else "delete_projects"
                self.assertEqual(harness.call(name), [((harness.DB, ["empty"]), {})])

    def test_delete_projects_confirmation_text_counts_several_projects(self):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            harness.handler._delete_projects(["1", "e1", "e2"], harness.DB)
        harness.warning.assert_not_called()
        harness.confirm.assert_called_once_with(
            "window",
            "Delete Projects",
            "Permanently delete 2 empty projects?\nThis cannot be undone.",
        )

    def test_delete_projects_stops_on_cancel_flush_failure_and_write_failure(self):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            harness.handler._delete_projects(["1"], harness.DB)
            self.assertEqual(harness.calls, [])
            self.assertEqual(harness.confirm.call_count, 0)
            harness.confirm.return_value = False
            harness.handler._delete_projects(["e1"], harness.DB)
            self.assertEqual((harness.cancelled_files, harness.calls), ([], []))
            harness.confirm.return_value = True
            harness.flush_ok = False
            harness.handler._delete_projects(["e1"], harness.DB)
            self.assertEqual(harness.calls, [])
            harness.flush_ok = True
            harness.script["delete_projects"] = False
            harness.handler._delete_projects(["e1"], harness.DB)
        harness.critical.assert_called_once_with(
            "window", "Delete Error", f"Failed to delete projects. {DB_LOCKED_HINT}"
        )

    def test_sql_project_delete_commit_applies_the_selection_fallback(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.selected_projects = ["e1"]
        harness.selected_project_file = harness.DB
        harness.loaded = {harness.DB: {"e1": object()}}
        with harness.patched():
            harness.handler._delete_projects(["e1"], harness.DB)
        harness.callbacks[0](harness.result())
        self.assertEqual(
            harness.selection,
            [("bid", None), ("project", None), ("database", True, harness.DB)],
        )


class ProjectWriteHandlerSecondPassDuplicateAndPasteTests(unittest.TestCase):
    """Access duplicate and paste through the progress dialog (the dialog itself is a
    fake that runs the task and returns the scripted result code), SQL duplicate, and the
    busy flag of the duplicate action."""

    def test_duplicate_is_ignored_while_one_is_running_or_nothing_is_selected(self):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            harness.handler.duplicate_selected()
            self.assertEqual((harness.calls, harness.progress), ([], []))
            harness.selected_bid = BidRef(harness.DB, "7")
            harness.handler._duplicate_in_progress = True
            harness.handler.duplicate_selected()
        self.assertEqual(
            (harness.calls, harness.progress, harness.flushes), ([], [], [])
        )

    def test_duplicate_does_not_start_when_pending_changes_cannot_be_saved(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql, flush_ok=False)
                with harness.patched():
                    harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
                self.assertEqual((harness.calls, harness.progress), ([], []))
                self.assertIs(harness.handler._duplicate_in_progress, False)

    def test_access_duplicate_reports_progress_and_publishes_the_refresh_once(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.bid_info = {"7": SimpleNamespace(name="North Wing")}
        harness.ui.get_selected_bid_ref = lambda: BidRef(harness.DB, "7")
        with harness.patched():
            harness.handler.duplicate_selected()
        self.assertEqual(harness.progress, [("North Wing", "Duplicating")])
        self.assertEqual(harness.reports, ["bid data", "project data"])
        self.assertEqual(
            harness.names(),
            ["duplicate_bid_result", "reload_database", "notify_database_refreshed"],
        )
        self.assertEqual(
            harness.call("duplicate_bid_result"),
            [((harness.DB, "7"), {"reload": False})],
        )
        self.assertEqual(harness.call("reload_database"), [((harness.DB,), {})])
        self.assertEqual(
            harness.call("notify_database_refreshed"), [((harness.DB,), {})]
        )
        harness.warning.assert_not_called()
        harness.critical.assert_not_called()
        self.assertIs(harness.handler._duplicate_in_progress, False)

    def test_access_duplicate_names_an_unnamed_bid_generically(self):
        for info in (None, SimpleNamespace(name=""), SimpleNamespace(name=None)):
            with self.subTest(info=info):
                harness = _SecondPassHierarchy(sql=False)
                harness.bid_info = {"7": info} if info else {}
                with harness.patched():
                    harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
                self.assertEqual(harness.progress, [("selected bid", "Duplicating")])

    def test_access_duplicate_warns_when_only_the_refresh_failed(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["reload_database"] = False
        with harness.patched(), patch(f"{_PWH_MODULE}.logger") as logger:
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
        self.assertEqual(harness.call("notify_database_refreshed"), [])
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The bid was duplicated, but the project tree could not be refreshed. "
            "Reopen the database to see the duplicated bid.",
        )
        harness.critical.assert_not_called()
        logger.error.assert_called_once()

    def test_access_duplicate_failures_open_one_critical_dialog(self):
        failed = (
            ("write failed", WriteReloadResult(None, False, False)),
            ("empty value", WriteReloadResult("", True, True)),
            ("no value", WriteReloadResult(None, True, True)),
        )
        for label, result in failed:
            with self.subTest(label):
                harness = _SecondPassHierarchy(sql=False)
                harness.script["duplicate_bid_result"] = result
                with harness.patched():
                    harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
                self.assertEqual(harness.names(), ["duplicate_bid_result"])
                self.assertEqual(harness.reports, ["bid data"])
                harness.critical.assert_called_once_with(
                    "window",
                    "Duplicate Error",
                    f"Failed to duplicate bid. {DB_LOCKED_HINT}",
                )
                harness.warning.assert_not_called()
                self.assertIs(harness.handler._duplicate_in_progress, False)

    def test_access_duplicate_worker_error_is_logged_and_reported(self):
        harness = _SecondPassHierarchy(sql=False)
        error = RuntimeError("worker died")
        harness.script["worker_error"] = error
        harness.progress_rc = QtWidgets.QDialog.DialogCode.Rejected
        with harness.patched(), patch(f"{_PWH_MODULE}.logger") as logger:
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
        logger.error.assert_called_once()
        self.assertIs(logger.error.call_args.kwargs["exc_info"][1], error)
        harness.critical.assert_called_once_with(
            "window", "Duplicate Error", f"Failed to duplicate bid. {DB_LOCKED_HINT}"
        )

    def test_the_busy_flag_disables_the_action_and_the_toolbar_refresh_ends_it(self):
        harness = _SecondPassHierarchy(sql=False)
        enabled = []
        harness.handler.set_duplicate_action(SimpleNamespace(setEnabled=enabled.append))
        harness.handler._set_duplicate_busy(True)
        self.assertEqual((enabled, harness.toolbar), ([False], []))
        self.assertIs(harness.handler._duplicate_in_progress, True)
        harness.handler._set_duplicate_busy(False)
        self.assertEqual((enabled, harness.toolbar), ([False], [True]))
        self.assertIs(harness.handler._duplicate_in_progress, False)
        bare = _SecondPassHierarchy(sql=False)
        bare.handler._ui_event_coordinator = None
        bare.handler._set_duplicate_busy(True)
        bare.handler._set_duplicate_busy(False)
        self.assertIs(bare.handler._duplicate_in_progress, False)

    def test_sql_duplicate_holds_the_busy_flag_until_the_terminal_result(self):
        for status, expects_error in (
            (MutationOutcomeStatus.COMMITTED, False),
            (MutationOutcomeStatus.REJECTED, True),
        ):
            with self.subTest(status=status):
                harness = _SecondPassHierarchy(sql=True)
                harness.project_of = {"7": "project-4"}
                with harness.patched():
                    harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
                self.assertEqual(
                    harness.call("queue_bids_duplicate"),
                    [((harness.DB, ["7"], "project-4"), {})],
                )
                self.assertIs(harness.handler._duplicate_in_progress, True)
                harness.callbacks[0](harness.result(status))
                self.assertIs(harness.handler._duplicate_in_progress, False)
                self.assertEqual(harness.toolbar, [True])
                self.assertEqual(len(harness.errors), int(expects_error))
                self.assertEqual(harness.refreshes, [True] if expects_error else [])

    def test_sql_duplicate_refused_twice_ends_the_busy_flag_each_time(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.script["queue_bids_duplicate"] = RuntimeError("queue closed")
        with harness.patched():
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
        self.assertEqual(len(harness.call("queue_bids_duplicate")), 2)
        self.assertEqual(harness.toolbar, [True] * 4)
        self.assertIs(harness.handler._duplicate_in_progress, False)

    def test_sql_duplicate_of_a_pending_bid_clears_the_busy_flag(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.handler._pending_sql_operations.add((harness.DB, "duplicate_bid", "7"))
        with harness.patched():
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
        self.assertEqual(harness.calls, [])
        self.assertIs(harness.handler._duplicate_in_progress, False)
        self.assertEqual(harness.toolbar, [True])

    def _paste(self, harness, refs, target="project-9", **options):
        with harness.patched():
            return harness.handler.paste_bids(refs, target, **options)

    def test_access_cut_paste_moves_without_publishing_and_commits_once(self):
        harness = _SecondPassHierarchy(sql=False)
        cut_done = []
        refs = [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")]
        self.assertIs(
            self._paste(
                harness, refs, is_cut=True, on_cut_committed=lambda: cut_done.append(1)
            ),
            True,
        )
        self.assertEqual(
            harness.call("move_bids"),
            [
                (
                    (harness.DB, ["1", "2"], "project-9"),
                    {"publish_database_refreshed_after_write": False},
                )
            ],
        )
        self.assertEqual(harness.progress, [("2 bids", "Pasting")])
        self.assertEqual(harness.reports, ["bid data", "project data"])
        self.assertEqual(harness.call("reload_database"), [((harness.DB,), {})])
        self.assertEqual(
            harness.call("notify_database_refreshed"), [((harness.DB,), {})]
        )
        self.assertEqual(cut_done, [1])
        harness.warning.assert_not_called()
        harness.critical.assert_not_called()

    def test_access_paste_names_a_single_bid_in_the_progress_label(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.bid_info = {"1": SimpleNamespace(name="North Wing")}
        self._paste(harness, [BidRef(harness.DB, "1")], is_cut=True)
        self.assertEqual(harness.progress, [("North Wing", "Pasting")])

    def test_access_cut_paste_refresh_failure_warns_but_the_cut_still_completes(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["reload_database"] = False
        cut_done = []
        with patch(f"{_PWH_MODULE}.logger") as logger:
            self.assertIs(
                self._paste(
                    harness,
                    [BidRef(harness.DB, "1")],
                    is_cut=True,
                    on_cut_committed=lambda: cut_done.append(1),
                ),
                True,
            )
        self.assertEqual(cut_done, [1])
        self.assertEqual(harness.call("notify_database_refreshed"), [])
        harness.warning.assert_called_once_with(
            "window",
            "Refresh Error",
            "The bid was pasted, but the project tree could not be refreshed. "
            "Reopen the database to see the pasted bid.",
        )
        logger.error.assert_called_once()
        harness.critical.assert_not_called()

    def test_access_paste_without_a_cut_callback_or_for_a_copy_does_not_commit_a_cut(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        self.assertIs(
            self._paste(harness, [BidRef(harness.DB, "1")], is_cut=True), True
        )
        copy = _SecondPassHierarchy(sql=False)
        cut_done = []
        self.assertIs(
            self._paste(
                copy,
                [BidRef(copy.DB, "1")],
                on_cut_committed=lambda: cut_done.append(1),
            ),
            True,
        )
        self.assertEqual(cut_done, [])

    def test_access_cut_paste_failure_opens_one_critical_dialog_and_reloads_nothing(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["move_bids"] = False
        cut_done = []
        self.assertIs(
            self._paste(
                harness,
                [BidRef(harness.DB, "1")],
                is_cut=True,
                on_cut_committed=lambda: cut_done.append(1),
            ),
            False,
        )
        self.assertEqual(harness.call("reload_database"), [])
        self.assertEqual(harness.call("notify_database_refreshed"), [])
        self.assertEqual(cut_done, [])
        harness.critical.assert_called_once_with(
            "window", "Paste Error", f"Failed to paste bid. {DB_LOCKED_HINT}"
        )

    def test_access_copy_paste_duplicates_each_bid_and_moves_only_other_project_copies(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "project-9", "2": "project-2", "3": "project-3"}
        harness.script["duplicate_bid"] = ["copy-1", "copy-2", "copy-3"]
        refs = [BidRef(harness.DB, uid) for uid in ("1", "2", "3")]
        self.assertIs(self._paste(harness, refs), True)
        self.assertEqual(
            harness.call("duplicate_bid"),
            [
                ((harness.DB, "1"), {"reload": False}),
                ((harness.DB, "2"), {"reload": False}),
                ((harness.DB, "3"), {"reload": False}),
            ],
        )
        self.assertEqual(
            harness.call("move_bids"),
            [
                (
                    (harness.DB, ["copy-2", "copy-3"], "project-9"),
                    {"publish_database_refreshed_after_write": False},
                )
            ],
        )
        self.assertEqual(
            harness.reports,
            [
                "bid 1 of 3",
                "bid 2 of 3",
                "bid 3 of 3",
                "project assignment",
                "project data",
            ],
        )
        self.assertEqual(
            harness.call("notify_database_refreshed"), [((harness.DB,), {})]
        )

    def test_access_copy_paste_into_the_same_project_needs_no_move(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "project-9"}
        self.assertIs(self._paste(harness, [BidRef(harness.DB, "1")]), True)
        self.assertEqual(harness.call("move_bids"), [])
        self.assertEqual(harness.reports, ["bid 1 of 1", "project data"])

    def test_access_copy_paste_failure_before_anything_changed_reloads_nothing(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["duplicate_bid"] = ""
        self.assertIs(self._paste(harness, [BidRef(harness.DB, "1")]), False)
        self.assertEqual(harness.call("reload_database"), [])
        self.assertEqual(harness.call("notify_database_refreshed"), [])
        self.assertEqual(harness.reports, ["bid 1 of 1"])
        harness.critical.assert_called_once_with(
            "window", "Paste Error", f"Failed to paste bid. {DB_LOCKED_HINT}"
        )
        harness.warning.assert_not_called()

    def test_access_copy_paste_partial_failure_reloads_and_warns_once(self):
        for reload_ok, text in (
            (
                True,
                "Some bids were pasted, but the paste did not finish. "
                "Review the refreshed project tree before retrying.",
            ),
            (
                False,
                "Some bids were pasted, but the paste did not finish and the "
                "project tree could not be refreshed. Reopen the database before "
                "retrying.",
            ),
        ):
            with self.subTest(reload_ok=reload_ok):
                harness = _SecondPassHierarchy(sql=False)
                harness.script["duplicate_bid"] = ["copy-1", ""]
                harness.script["reload_database"] = reload_ok
                refs = [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")]
                with patch(f"{_PWH_MODULE}.logger") as logger:
                    self.assertIs(self._paste(harness, refs), True)
                harness.warning.assert_called_once_with(
                    "window", "Paste Partially Completed", text
                )
                harness.critical.assert_not_called()
                logger.error.assert_called_once()
                self.assertEqual(len(harness.call("reload_database")), 1)
                self.assertEqual(
                    len(harness.call("notify_database_refreshed")), int(reload_ok)
                )

    def test_access_copy_paste_failed_assignment_after_duplicates_is_partial(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "project-2"}
        harness.script["duplicate_bid"] = ["copy-1"]
        harness.script["move_bids"] = False
        self.assertIs(self._paste(harness, [BidRef(harness.DB, "1")]), True)
        self.assertEqual(
            harness.reports, ["bid 1 of 1", "project assignment", "project data"]
        )
        harness.warning.assert_called_once()
        self.assertEqual(harness.warning.call_args.args[1], "Paste Partially Completed")

    def test_access_paste_worker_error_is_logged_and_reported_as_failure(self):
        harness = _SecondPassHierarchy(sql=False)
        error = RuntimeError("worker died")
        harness.script["worker_error"] = error
        harness.progress_rc = QtWidgets.QDialog.DialogCode.Rejected
        with patch(f"{_PWH_MODULE}.logger") as logger:
            self.assertIs(self._paste(harness, [BidRef(harness.DB, "1")]), False)
        self.assertIs(logger.error.call_args.kwargs["exc_info"][1], error)
        harness.critical.assert_called_once_with(
            "window", "Paste Error", f"Failed to paste bid. {DB_LOCKED_HINT}"
        )


class ProjectWriteHandlerSecondPassDeleteBidsTests(unittest.TestCase):
    """Delete and trash of Bids on both backends: confirmation texts, grouping, the
    active-Bid selection rules, and the selection fallback helpers."""

    TRASH = "1"

    def _delete(self, harness, refs, selection=None):
        with harness.patched():
            harness.handler.delete_bids(refs, selection)

    def test_trashing_one_bid_confirms_and_moves_it_with_its_original_project(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                harness.project_of = {"1": "project-3"}
                self._delete(harness, [BidRef(harness.DB, "1")])
                harness.confirm.assert_called_once_with(
                    "window",
                    "Move to Deleted Bids",
                    "Move this bid to 'Deleted Bids'?\n"
                    "You can permanently delete it from there.",
                )
                self.assertEqual(harness.cancelled, [(harness.DB, ["1"])])
                self.assertEqual(harness.flushes, [harness.DB])
                if sql:
                    self.assertEqual(
                        harness.call("queue_bids_move"),
                        [
                            (
                                (harness.DB, ["1"], "1"),
                                {"original_project_uid": "project-3"},
                            )
                        ],
                    )
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {(harness.DB, "trash_bids", "1")},
                    )
                else:
                    self.assertEqual(
                        harness.call("move_bids"),
                        [
                            (
                                (harness.DB, ["1"], "1", "project-3"),
                                {"publish_database_refreshed_after_write": False},
                            )
                        ],
                    )
                    self.assertEqual(
                        harness.call("reload_database"), [((harness.DB,), {})]
                    )
                    self.assertEqual(
                        harness.call("notify_database_refreshed"), [((harness.DB,), {})]
                    )

    def test_trashing_several_bids_groups_them_by_original_project(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                harness.project_of = {
                    "1": "project-3",
                    "2": "project-4",
                    "3": "project-3",
                }
                harness.project_of["4"] = None
                refs = [BidRef(harness.DB, uid) for uid in ("1", "2", "3", "4")]
                self._delete(harness, refs)
                harness.confirm.assert_called_once_with(
                    "window",
                    "Move to Deleted Bids",
                    "Move 4 bids to 'Deleted Bids'?\n"
                    "You can permanently delete them from there.",
                )
                name = "queue_bids_move" if sql else "move_bids"
                calls = harness.call(name)
                if sql:
                    self.assertEqual(
                        calls,
                        [
                            (
                                (harness.DB, ["1", "3"], "1"),
                                {"original_project_uid": "project-3"},
                            ),
                            (
                                (harness.DB, ["2"], "1"),
                                {"original_project_uid": "project-4"},
                            ),
                            ((harness.DB, ["4"], "1"), {"original_project_uid": None}),
                        ],
                    )
                else:
                    options = {"publish_database_refreshed_after_write": False}
                    self.assertEqual(
                        calls,
                        [
                            ((harness.DB, ["1", "3"], "1", "project-3"), options),
                            ((harness.DB, ["2"], "1", "project-4"), options),
                            ((harness.DB, ["4"], "1", None), options),
                        ],
                    )

    def test_permanent_delete_confirms_with_the_bid_count_and_writes_per_database(self):
        for sql in (False, True):
            with self.subTest(sql=sql):
                harness = _SecondPassHierarchy(sql=sql)
                other = "C:/jobs/b.mdb"
                harness.project_of = {"1": "1", "2": "1", "3": "1"}
                refs = [
                    BidRef(harness.DB, "1"),
                    BidRef(other, "2"),
                    BidRef(harness.DB, "3"),
                ]
                harness.loaded[other] = {}
                self._delete(harness, refs)
                harness.confirm.assert_called_once_with(
                    "window",
                    "Delete Bids",
                    "Permanently delete 3 bids and all their data?\n"
                    "This cannot be undone.",
                )
                name = "queue_bids_delete" if sql else "delete_bids"
                options = (
                    {} if sql else {"publish_database_refreshed_after_write": False}
                )
                self.assertEqual(
                    harness.call(name),
                    [
                        ((harness.DB, ["1", "3"]), options),
                        ((other, ["2"]), options),
                    ],
                )
                self.assertEqual(
                    harness.cancelled, [(harness.DB, ["1", "3"]), (other, ["2"])]
                )
                if sql:
                    self.assertEqual(
                        harness.handler._pending_sql_operations,
                        {
                            (harness.DB, "delete_bids", "1", "3"),
                            (other, "delete_bids", "2"),
                        },
                    )

    def test_permanent_delete_of_one_bid_uses_the_singular_text(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "1"}
        self._delete(harness, [BidRef(harness.DB, "1")])
        harness.confirm.assert_called_once_with(
            "window",
            "Delete Bids",
            "Permanently delete this bid and all its data?\nThis cannot be undone.",
        )

    def test_cancelling_the_permanent_confirmation_skips_the_trash_part_too(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "1", "2": "project-3"}
        with harness.patched():
            harness.confirm.side_effect = [False]
            harness.handler.delete_bids(
                [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")], None
            )
        self.assertEqual(harness.confirm.call_count, 1)
        self.assertEqual(
            (harness.calls, harness.flushes, harness.cancelled), ([], [], [])
        )

    def test_cancelling_the_trash_confirmation_writes_nothing(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"2": "project-3"}
        with harness.patched():
            harness.confirm.return_value = False
            harness.handler.delete_bids([BidRef(harness.DB, "2")], None)
        self.assertEqual(
            (harness.calls, harness.flushes, harness.cancelled), ([], [], [])
        )

    def test_mixed_selection_deletes_permanently_first_and_then_trashes(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "1", "2": "project-3"}
        self._delete(harness, [BidRef(harness.DB, "2"), BidRef(harness.DB, "1")])
        self.assertEqual(
            [call.args[1] for call in harness.confirm.call_args_list],
            ["Delete Bids", "Move to Deleted Bids"],
        )
        self.assertEqual(harness.names()[0], "delete_bids")
        self.assertIn("move_bids", harness.names())

    def test_a_failed_flush_stops_before_any_write(self):
        harness = _SecondPassHierarchy(sql=False, flush_ok=False)
        harness.project_of = {"1": "1", "2": "project-3"}
        self._delete(harness, [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")])
        self.assertEqual(harness.calls, [])
        self.assertEqual(harness.confirm.call_count, 1)
        harness = _SecondPassHierarchy(sql=False, flush_ok=False)
        harness.project_of = {"2": "project-3"}
        self._delete(harness, [BidRef(harness.DB, "2")])
        self.assertEqual(harness.calls, [])

    def test_an_access_write_failure_opens_one_critical_dialog_and_stops(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "1", "2": "1"}
        harness.script["delete_bids"] = False
        refs = [BidRef(harness.DB, "1"), BidRef("C:/jobs/b.mdb", "2")]
        self._delete(harness, refs)
        self.assertEqual(len(harness.call("delete_bids")), 1)
        self.assertEqual(harness.call("reload_database"), [])
        harness.critical.assert_called_once_with(
            "window", "Delete Error", f"Failed to delete bids. {DB_LOCKED_HINT}"
        )
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": "project-3"}
        harness.script["move_bids"] = False
        self._delete(harness, [BidRef(harness.DB, "1")])
        self.assertEqual(harness.call("reload_database"), [])
        harness.critical.assert_called_once_with(
            "window",
            "Move Error",
            f"Failed to move bids to Deleted Bids. {DB_LOCKED_HINT}",
        )

    def test_an_access_refresh_failure_warns_and_stops_before_the_selection_update(
        self,
    ):
        for trash, text in (
            (
                False,
                "The bid was deleted, but the project tree could not be "
                "refreshed. Reopen the database to see the change.",
            ),
            (
                True,
                "The bid was moved to Deleted Bids, but the project tree "
                "could not be refreshed. Reopen the database to see the change.",
            ),
        ):
            with self.subTest(trash=trash):
                harness = _SecondPassHierarchy(sql=False)
                harness.project_of = {"1": "project-3" if trash else "1"}
                harness.selected_bid = BidRef(harness.DB, "1")
                harness.owner = {"1": object()}
                harness.script["reload_database"] = False
                self._delete(harness, [BidRef(harness.DB, "1")], {"kind": "database"})
                harness.warning.assert_called_once_with("window", "Refresh Error", text)
                self.assertEqual(harness.call("notify_database_refreshed"), [])
                self.assertEqual(harness.selection, [("bid", None)])
                self.assertEqual(harness.cleared, [True])

    def test_only_the_active_bid_of_the_same_database_clears_the_selection(self):
        for trash in (False, True):
            for label, selected, expect_clear in (
                ("same bid", BidRef("C:/jobs/a.mdb", "1"), True),
                ("other database", BidRef("C:/jobs/b.mdb", "1"), False),
                ("other bid", BidRef("C:/jobs/a.mdb", "9"), False),
                ("no selection", None, False),
            ):
                with self.subTest(trash=trash, label=label):
                    harness = _SecondPassHierarchy(sql=False)
                    harness.project_of = {"1": "project-3" if trash else "1"}
                    harness.selected_bid = selected
                    harness.owner = {"1": object(), "9": object()}
                    harness.loaded["C:/jobs/b.mdb"] = {}
                    self._delete(harness, [BidRef(harness.DB, "1")])
                    self.assertEqual(harness.cleared, [True] if expect_clear else [])
                    cleared_selection = [
                        item for item in harness.selection if item[0] == "bid"
                    ]
                    self.assertEqual(
                        cleared_selection, [("bid", None)] * 2 if expect_clear else []
                    )
                    self.assertEqual(len(harness.call("notify_database_refreshed")), 1)

    def test_a_selection_state_without_an_active_bid_still_updates_the_selection(self):
        for trash in (False, True):
            with self.subTest(trash=trash):
                harness = _SecondPassHierarchy(sql=False)
                harness.project_of = {"1": "project-3" if trash else "1"}
                harness.selected_bid = BidRef(harness.DB, "9")
                state = {
                    "kind": "project",
                    "file_path": harness.DB,
                    "project_uid": "project-1",
                }
                self._delete(harness, [BidRef(harness.DB, "1")], state)
                self.assertEqual(
                    harness.selection,
                    [("bid", None), ("file", harness.DB), ("project", "project-1")],
                )
                self.assertEqual(harness.cleared, [])

    def test_a_delete_without_selection_state_or_active_bid_leaves_the_selection(self):
        for trash in (False, True):
            with self.subTest(trash=trash):
                harness = _SecondPassHierarchy(sql=False)
                harness.project_of = {"1": "project-3" if trash else "1"}
                self._delete(harness, [BidRef(harness.DB, "1")], None)
                self.assertEqual(harness.selection, [])

    def test_sql_removal_commit_clears_the_active_bid_before_selecting_the_fallback(
        self,
    ):
        harness = _SecondPassHierarchy(sql=True)
        harness.project_of = {"1": "project-3"}
        original = BidRef(harness.DB, "1")
        harness.selected_bid = original
        owner = object()
        harness.owner = {"1": owner, "2": object()}
        harness.loaded[harness.DB] = {"project-3": object()}
        harness.bid_info = {"2": object()}
        state = {"kind": "bid", "file_path": harness.DB, "bid_uid": "2"}
        self._delete(harness, [original], state)
        self.assertEqual(
            harness.call("queue_bids_move"),
            [((harness.DB, ["1"], "1"), {"original_project_uid": "project-3"})],
        )
        harness.callbacks[0](harness.result())
        self.assertEqual(
            harness.selection, [("bid", None), ("bid", BidRef(harness.DB, "2"))]
        )
        self.assertEqual(harness.cleared, [True])

    def test_sql_removal_commit_leaves_a_selection_the_user_moved_away_from(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.project_of = {"1": "project-3"}
        original = BidRef(harness.DB, "1")
        harness.selected_bid = original
        harness.owner = {"1": object()}
        self._delete(harness, [original], None)
        harness.selected_bid = BidRef(harness.DB, "2")
        harness.callbacks[0](harness.result())
        self.assertEqual((harness.selection, harness.cleared), ([], []))

    def test_sql_removal_commit_for_a_bid_that_was_not_selected_changes_nothing(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.project_of = {"1": "project-3"}
        harness.selected_bid = BidRef(harness.DB, "9")
        self._delete(harness, [BidRef(harness.DB, "1")], {"kind": "database"})
        harness.callbacks[0](harness.result())
        self.assertEqual((harness.selection, harness.cleared), ([], []))

    def test_sql_removal_clears_the_current_bid_only_for_the_same_database(self):
        for current_path, expected in ((None, [True]), ("C:/jobs/other.mdb", [])):
            with self.subTest(current=current_path):
                harness = _SecondPassHierarchy(sql=True)
                harness.project_of = {"1": "project-3"}
                original = BidRef(harness.DB, "1")
                harness.selected_bid = original
                harness.owner = {"1": object()}
                harness.data.get_current_file_path = lambda path=current_path: (
                    path or harness.DB
                )
                self._delete(harness, [original], None)
                harness.callbacks[0](harness.result())
                self.assertEqual(harness.cleared, expected)
                self.assertEqual(harness.selection[0], ("bid", None))

    def test_sql_project_removal_ignores_a_changed_selection_or_replaced_project(self):
        harness = _SecondPassHierarchy(sql=True)
        owner = object()
        harness.loaded = {harness.DB: {"e1": owner}}
        harness.selected_projects = ["e1"]
        harness.selected_project_file = harness.DB
        finish = harness.handler._finish_sql_project_removal
        args = (harness.DB, ("e1",), (("e1", owner),))
        harness.selected_bid = BidRef(harness.DB, "5")
        finish(*args)
        harness.selected_bid = None
        harness.selected_project_file = "C:/jobs/other.mdb"
        finish(*args)
        harness.selected_project_file = harness.DB
        harness.selected_projects = ["e1", "e2"]
        finish(*args)
        harness.selected_projects = ["e1"]
        harness.loaded = {harness.DB: {"e1": object()}}
        finish(*args)
        self.assertEqual(harness.selection, [])
        harness.loaded = {harness.DB: {"e1": owner}}
        finish(*args)
        self.assertEqual(
            harness.selection,
            [("bid", None), ("project", None), ("database", True, harness.DB)],
        )
        harness.selection.clear()
        harness.loaded = {harness.DB: {}}
        finish(*args)
        self.assertEqual(
            harness.selection,
            [("bid", None), ("project", None), ("database", True, harness.DB)],
        )

    def test_the_selection_fallback_covers_every_state_kind(self):
        db = _SecondPassHierarchy.DB
        other = "C:/jobs/b.mdb"
        cases = {
            "none": (None, [("bid", None), ("project", None), ("database", True, db)]),
            "not a dict": (
                "x",
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "valid bid": (
                {"kind": "bid", "file_path": db, "bid_uid": "2"},
                [("bid", BidRef(db, "2"))],
            ),
            "unknown bid": (
                {"kind": "bid", "file_path": db, "bid_uid": "99"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "empty bid": (
                {"kind": "bid", "file_path": db, "bid_uid": ""},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "valid project": (
                {"kind": "project", "file_path": db, "project_uid": "project-1"},
                [("bid", None), ("file", db), ("project", "project-1")],
            ),
            "unknown project": (
                {"kind": "project", "file_path": db, "project_uid": "nope"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "empty project": (
                {"kind": "project", "file_path": db, "project_uid": ""},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "database": (
                {"kind": "database", "file_path": db.upper()},
                [("bid", None), ("project", None), ("database", True, db.upper())],
            ),
            "missing database": (
                {"kind": "database", "file_path": "C:/jobs/gone.mdb"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "no kind": (
                {"file_path": db, "bid_uid": "2"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "other database": (
                {"kind": "bid", "file_path": other, "bid_uid": "2"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
            "no file": (
                {"kind": "bid", "bid_uid": "2"},
                [("bid", None), ("project", None), ("database", True, db)],
            ),
        }
        for label, (state, expected) in cases.items():
            with self.subTest(label):
                harness = _SecondPassHierarchy(sql=False)
                harness.bid_info = {"2": object()}
                harness.loaded[other] = {}
                harness.handler._apply_delete_selection_state(db, state)
                self.assertEqual(harness.selection, expected)

    def test_the_selection_fallback_for_an_unloaded_database_still_selects_it(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.loaded = {}
        harness.handler._apply_delete_selection_state(harness.DB, None)
        self.assertEqual(
            harness.selection,
            [("bid", None), ("project", None), ("database", True, harness.DB)],
        )
        self.assertIsNone(harness.handler._database_selection_state(harness.DB))
        self.assertIs(harness.handler._same_file("", "x"), False)
        self.assertIs(harness.handler._same_file("x", ""), False)
        self.assertIs(harness.handler._same_file("C:/A.mdb", "c:\\a.mdb"), True)


from ost_visualizer.presentation.handlers.project_write_handler import (
    _PasteBidsResult,
)


class ProjectWriteHandlerSecondPassRemainingTests(unittest.TestCase):
    """Second-pass mutation survivors of the project-tree handler: titles of the failure
    presentation of every SQL command, the real progress-dialog wrapper, the paste task
    results, the group key of unassigned Bids and the selection-state validation."""

    def test_every_rejected_sql_command_is_presented_under_its_own_title(self):
        db = _SecondPassHierarchy.DB
        ref = BidRef(db, "7")
        trash_ref = BidRef(db, "8")
        commands = (
            (
                "rename",
                "Rename Project",
                lambda h: h.handler.rename_project("p9", "N", None),
            ),
            (
                "create",
                "New Project",
                lambda h: h.handler.create_project(db, "N", lambda uid: None),
            ),
            (
                "status",
                "Job Status",
                lambda h: h.handler.update_bid_job_status(ref, "s"),
            ),
            ("move", "Move Bids", lambda h: h.handler.move_bids([ref], "p")),
            ("paste copy", "Paste Bids", lambda h: h.handler.paste_bids([ref], "p")),
            (
                "paste cut",
                "Move Bids",
                lambda h: h.handler.paste_bids([ref], "p", is_cut=True),
            ),
            ("restore", "Restore Bids", lambda h: h.handler.restore_bids([ref])),
            ("trash", "Move Bids", lambda h: h.handler.delete_bids([ref])),
            ("delete", "Delete Bids", lambda h: h.handler.delete_bids([trash_ref])),
            (
                "projects",
                "Delete Projects",
                lambda h: h.handler.delete_projects(db, ["empty"]),
            ),
            ("duplicate", "Duplicate Bid", lambda h: h.handler.duplicate_bid(ref)),
        )
        for label, title, run in commands:
            with self.subTest(label):
                harness = _SecondPassHierarchy(sql=True)
                harness.project_of = {"7": "project-3", "8": "1"}
                with harness.patched():
                    run(harness)
                self.assertEqual(len(harness.callbacks), 1, label)
                harness.callbacks[0](harness.result(MutationOutcomeStatus.REJECTED))
                self.assertEqual(
                    [(database, shown) for database, shown, _result in harness.errors],
                    [(db, title)],
                )
                self.assertEqual(harness.refreshes, [True])
                self.assertEqual(harness.handler._pending_sql_operations, set())

    def test_the_pending_keys_of_the_sql_commands(self):
        db = _SecondPassHierarchy.DB
        ref = BidRef(db, "7")
        expected = {
            "projects": (
                lambda h: h.handler.delete_projects(db, ["e1", "e2"]),
                (db, "delete_projects", "e1", "e2"),
            ),
            "delete": (
                lambda h: h.handler.delete_bids([BidRef(db, "8"), BidRef(db, "9")]),
                (db, "delete_bids", "8", "9"),
            ),
            "trash": (lambda h: h.handler.delete_bids([ref]), (db, "trash_bids", "7")),
            "move": (lambda h: h.handler.move_bids([ref], "p"), (db, "move_bids", "7")),
        }
        for label, (run, key) in expected.items():
            with self.subTest(label):
                harness = _SecondPassHierarchy(sql=True)
                harness.project_of = {"7": "project-3", "8": "1", "9": "1"}
                with harness.patched():
                    run(harness)
                self.assertEqual(harness.handler._pending_sql_operations, {key})

    def test_flushing_without_a_database_path_is_a_success_without_a_flush(self):
        harness = _SecondPassHierarchy(sql=False, flush_ok=False)
        for path in (None, ""):
            self.assertIs(harness.handler._flush_deferred_for_file(path), True)
        self.assertEqual(harness.flushes, [])
        self.assertIs(harness.handler._flush_deferred_for_file("C:/jobs/a.mdb"), False)
        self.assertEqual(harness.flushes, ["C:/jobs/a.mdb"])

    def test_the_sql_job_status_command_does_not_also_run_the_access_write(self):
        harness = _SecondPassHierarchy(sql=True)
        with harness.patched():
            harness.handler.update_bid_job_status(BidRef(harness.DB, "7"), "s")
        self.assertEqual(harness.names(), ["queue_bid_job_status_update"])

    def test_the_access_duplicate_holds_the_busy_flag_while_the_progress_dialog_runs(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        with harness.patched():
            harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
        self.assertEqual(harness.busy_during, [True])
        self.assertIs(harness.handler._duplicate_in_progress, False)

    def test_an_access_duplicate_without_a_result_object_opens_one_critical_dialog(
        self,
    ):
        for outcome in (
            None,
            WriteReloadResult("copy", False, True),
            WriteReloadResult("copy", False, False),
        ):
            with self.subTest(outcome=outcome):
                harness = _SecondPassHierarchy(sql=False)
                harness.script["duplicate_bid_result"] = outcome
                if outcome is None:
                    harness.script["worker_error"] = None
                    harness.handler._run_progress_dialog = lambda *a, **k: (
                        QtWidgets.QDialog.DialogCode.Rejected,
                        None,
                        None,
                    )
                with harness.patched():
                    harness.handler.duplicate_bid(BidRef(harness.DB, "7"))
                harness.critical.assert_called_once_with(
                    "window",
                    "Duplicate Error",
                    f"Failed to duplicate bid. {DB_LOCKED_HINT}",
                )
                harness.warning.assert_not_called()
                if outcome is not None:
                    self.assertEqual(harness.call("reload_database"), [])

    def test_the_duplicate_task_returns_a_failed_write_result_unchanged(self):
        harness = _SecondPassHierarchy(sql=False)
        reports = []

        class Reporter:
            def report(self, description):
                reports.append(description)

        for failed in (
            WriteReloadResult(None, False, False),
            WriteReloadResult("copy", False, True),
            WriteReloadResult("", True, True),
        ):
            with self.subTest(failed=failed):
                harness.script["duplicate_bid_result"] = failed
                reports.clear()
                self.assertIs(
                    harness.handler._duplicate_bid_with_reload(
                        BidRef(harness.DB, "7"), Reporter()
                    ),
                    failed,
                )
                self.assertEqual(reports, ["bid data"])
        harness.script["duplicate_bid_result"] = WriteReloadResult(12, True, True)
        harness.script["reload_database"] = False
        reports.clear()
        self.assertEqual(
            harness.handler._duplicate_bid_with_reload(
                BidRef(harness.DB, "7"), Reporter()
            ),
            WriteReloadResult("12", True, False),
        )
        self.assertEqual(reports, ["bid data", "project data"])

    def test_the_paste_task_returns_exact_results_for_every_failure_shape(self):
        db = _SecondPassHierarchy.DB
        refs = [BidRef(db, "1"), BidRef(db, "2")]

        class Reporter:
            def report(self, _description):
                pass

        def run(script, *, is_cut=False, sources=None):
            harness = _SecondPassHierarchy(sql=False)
            harness.script.update(script)
            result = harness.handler._paste_bids_with_reload(
                refs, "target", is_cut, sources or {}, Reporter()
            )
            return result, harness

        result, harness = run({"move_bids": False}, is_cut=True)
        self.assertEqual(result, _PasteBidsResult(False, False))
        self.assertEqual(harness.call("reload_database"), [])
        result, harness = run({"duplicate_bid": ""})
        self.assertEqual(result, _PasteBidsResult(False, False))
        self.assertEqual(harness.call("reload_database"), [])
        result, harness = run(
            {"duplicate_bid": ["copy-1", ""], "reload_database": True}
        )
        self.assertEqual(result, _PasteBidsResult(False, True, partial_success=True))
        self.assertEqual(len(harness.call("reload_database")), 1)
        result, harness = run(
            {"duplicate_bid": ["copy-1", ""], "reload_database": False}
        )
        self.assertEqual(result, _PasteBidsResult(False, False, partial_success=True))
        result, harness = run(
            {"duplicate_bid": ["copy-1", "copy-2"], "move_bids": False},
            sources={"1": "other", "2": "target"},
        )
        self.assertEqual(result, _PasteBidsResult(False, True, partial_success=True))
        self.assertEqual(harness.call("move_bids")[0][0][1], ["copy-1"])
        result, harness = run({"move_bids": True}, is_cut=True)
        self.assertEqual(result, _PasteBidsResult(True, True))
        result, harness = run({"duplicate_bid": ["c1", "c2"], "reload_database": False})
        self.assertEqual(result, _PasteBidsResult(True, False))

    def test_a_paste_failure_before_any_change_does_not_reload(self):
        harness = _SecondPassHierarchy(sql=False)
        reporter = SimpleNamespace(report=lambda _text: None)
        self.assertEqual(
            harness.handler._paste_failure(False, harness.DB, reporter),
            _PasteBidsResult(False, False),
        )
        self.assertEqual(harness.calls, [])
        self.assertEqual(
            harness.handler._paste_failure(True, harness.DB, reporter),
            _PasteBidsResult(False, True, partial_success=True),
        )
        self.assertEqual(harness.names(), ["reload_database"])

    def test_a_worker_error_with_no_result_is_a_plain_paste_failure(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.script["worker_error"] = RuntimeError("worker died")
        with harness.patched(), patch(f"{_PWH_MODULE}.logger"):
            self.assertIs(
                harness.handler.paste_bids([BidRef(harness.DB, "1")], "p"), False
            )
        self.assertEqual(harness.names(), [])
        harness.critical.assert_called_once()
        harness.warning.assert_not_called()

    def test_the_progress_dialog_wrapper_runs_the_task_and_always_cleans_up(self):
        events = []
        created = []

        class FakeDialog:
            def __init__(self, label, task_fn, *, parent, reporter, action_text):
                created.append((label, parent, reporter, action_text))
                self.result = "task-result"
                self.error = RuntimeError("worker error")
                self.raise_in_exec = False

            def exec(self):
                events.append("exec")
                if self.raise_in_exec:
                    raise RuntimeError("exec failed")
                return QtWidgets.QDialog.DialogCode.Accepted

            def cleanup(self):
                events.append("cleanup")

        harness = _SecondPassHierarchy(sql=False)
        handler = ProjectWriteHandler(
            window="window",
            project_data_service=harness.data,
            project_write_service=harness.write,
            ui_state_manager=harness.ui,
            deferred_persistence_manager=SimpleNamespace(),
        )
        reporter = object()
        with patch(f"{_PWH_MODULE}.ProgressDialog", FakeDialog), patch(
            f"{_PWH_MODULE}.delete_later_if_valid",
            side_effect=lambda dialog: events.append("delete_later"),
        ):
            outcome = handler._run_progress_dialog(
                "label", lambda: None, "Doing", reporter
            )
        self.assertEqual(
            outcome[:2], (QtWidgets.QDialog.DialogCode.Accepted, "task-result")
        )
        self.assertIsInstance(outcome[2], RuntimeError)
        self.assertEqual(created, [("label", "window", reporter, "Doing")])
        self.assertEqual(events, ["exec", "cleanup", "delete_later"])
        events.clear()
        with patch(f"{_PWH_MODULE}.ProgressDialog", FakeDialog), patch(
            f"{_PWH_MODULE}.delete_later_if_valid",
            side_effect=lambda dialog: events.append("delete_later"),
        ), patch(f"{_PWH_MODULE}.isValid", return_value=False):
            outcome = handler._run_progress_dialog(
                "label", lambda: None, "Doing", reporter
            )
        self.assertEqual(outcome, (QtWidgets.QDialog.DialogCode.Accepted, None, None))
        self.assertEqual(events, ["exec", "cleanup", "delete_later"])

    def test_a_failing_progress_dialog_still_cleans_up_and_propagates(self):
        events = []

        class FakeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                raise RuntimeError("exec failed")

            def cleanup(self):
                events.append("cleanup")
                raise ValueError("cleanup failed too")

        harness = _SecondPassHierarchy(sql=False)
        with patch(f"{_PWH_MODULE}.ProgressDialog", FakeDialog), patch(
            f"{_PWH_MODULE}.delete_later_if_valid",
            side_effect=lambda dialog: events.append("delete_later"),
        ), self.assertRaises(ValueError):
            ProjectWriteHandler._run_progress_dialog(
                harness.handler, "label", lambda: None, "Doing", object()
            )
        self.assertEqual(events, ["cleanup", "delete_later"])

    def test_unassigned_bids_share_one_trash_group_whatever_their_missing_project_is(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        harness.project_of = {"1": None, "2": "", "3": "project-3"}
        refs = [BidRef(harness.DB, uid) for uid in ("1", "2", "3")]
        with harness.patched():
            harness.handler.delete_bids(refs)
        self.assertEqual(
            [args for args, _kwargs in harness.call("move_bids")],
            [
                (harness.DB, ["1", "2"], "1", None),
                (harness.DB, ["3"], "1", "project-3"),
            ],
        )

    def test_a_sql_removal_commit_with_no_selection_at_either_time_changes_nothing(
        self,
    ):
        harness = _SecondPassHierarchy(sql=True)
        harness.project_of = {"1": "project-3"}
        harness.selected_bid = None
        with harness.patched():
            harness.handler.delete_bids([BidRef(harness.DB, "1")], {"kind": "database"})
        harness.callbacks[0](harness.result())
        self.assertEqual((harness.selection, harness.cleared), ([], []))

    def test_a_sql_removal_commit_proceeds_when_the_bid_is_already_gone_from_memory(
        self,
    ):
        harness = _SecondPassHierarchy(sql=True)
        harness.project_of = {"1": "project-3"}
        original = BidRef(harness.DB, "1")
        harness.selected_bid = original
        harness.owner = {"1": object()}
        with harness.patched():
            harness.handler.delete_bids([original], None)
        harness.owner = {}
        harness.callbacks[0](harness.result())
        self.assertEqual(harness.cleared, [True])
        self.assertEqual(harness.selection[0], ("bid", None))

    def test_the_project_removal_selection_check_is_symmetric_in_the_file_names(self):
        harness = _SecondPassHierarchy(sql=True)
        harness.selected_projects = ["e1"]
        harness.selected_project_file = harness.DB.upper()
        harness.loaded = {harness.DB: {"e1": object()}}
        owner = harness.loaded[harness.DB]["e1"]
        harness.handler._finish_sql_project_removal(
            harness.DB, ("e1",), (("e1", owner),)
        )
        self.assertEqual(len(harness.selection), 3)

    def test_the_delete_selection_state_is_validated_field_by_field(self):
        db = _SecondPassHierarchy.DB
        database = {
            "kind": "database",
            "file_path": db,
            "bid_uid": None,
            "project_uid": None,
        }
        harness = _SecondPassHierarchy(sql=False)
        harness.bid_info = {"2": object(), "": object(), "None": object()}
        harness.loaded[db] = {"project-1": object(), "": object(), "None": object()}
        valid = harness.handler._valid_delete_selection_state
        self.assertEqual(valid(db, None), database)
        self.assertEqual(valid(db, "not a dict"), database)
        self.assertEqual(valid(db, {}), database)
        self.assertEqual(
            valid(db, {"kind": "bid", "file_path": db, "bid_uid": "2"}),
            {"kind": "bid", "file_path": db, "bid_uid": "2", "project_uid": None},
        )
        self.assertEqual(
            valid(db, {"kind": "project", "file_path": db, "project_uid": "project-1"}),
            {
                "kind": "project",
                "file_path": db,
                "bid_uid": None,
                "project_uid": "project-1",
            },
        )
        self.assertEqual(
            valid(db, {"kind": "database", "file_path": db.upper()}),
            {**database, "file_path": db.upper()},
        )
        for label, state in (
            ("no bid uid", {"kind": "bid", "file_path": db}),
            ("empty bid uid", {"kind": "bid", "file_path": db, "bid_uid": ""}),
            ("no project uid", {"kind": "project", "file_path": db}),
            (
                "empty project uid",
                {"kind": "project", "file_path": db, "project_uid": ""},
            ),
            ("unknown kind", {"kind": "weird", "file_path": db.upper()}),
            ("no kind", {"file_path": db.upper()}),
            ("no file", {"kind": "database"}),
            ("other file", {"kind": "database", "file_path": "C:/jobs/other.mdb"}),
        ):
            with self.subTest(label):
                self.assertEqual(valid(db, state), database)
        harness.loaded = {}
        self.assertIsNone(valid(db, {"kind": "database", "file_path": db}))
        self.assertIsNone(valid(db, None))
        self.assertIsNone(valid(db, {"kind": "weird", "file_path": db}))

    def test_a_database_counts_as_loaded_only_when_its_path_matches_a_loaded_file(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.loaded = {"C:/jobs/a.mdb": {}, "C:/jobs/b.mdb": {}}
        exists = harness.handler._database_file_exists
        self.assertIs(exists("c:\\JOBS\\A.mdb"), True)
        self.assertIs(exists("C:/jobs/b.mdb"), True)
        self.assertIs(exists("C:/jobs/c.mdb"), False)
        harness.loaded = {}
        self.assertIs(exists("C:/jobs/a.mdb"), False)

    def test_same_file_needs_both_names_and_compares_them_normalized(self):
        same = ProjectWriteHandler._same_file
        self.assertIs(same("C:/A.mdb", "c:\\a.mdb"), True)
        self.assertIs(same("C:/A.mdb", "C:/B.mdb"), False)
        for left, right in (("", "."), (".", ""), ("", ""), (None, "x"), ("x", None)):
            with self.subTest(left=left, right=right):
                self.assertIs(same(left, right), False)

    def test_a_selection_state_without_a_file_never_matches_a_database_named_none(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.loaded = {"None": {"project-1": object()}}
        harness.bid_info = {"2": object()}
        database = {
            "kind": "database",
            "file_path": "None",
            "bid_uid": None,
            "project_uid": None,
        }
        for state in (
            {"kind": "bid", "bid_uid": "2"},
            {"kind": "project", "project_uid": "project-1"},
            {"kind": "database"},
        ):
            with self.subTest(state=state):
                self.assertEqual(
                    harness.handler._valid_delete_selection_state("None", state),
                    database,
                )


class ProjectWriteHandlerPasteOutcomeFromResultTests(unittest.TestCase):
    """Decision R2: an Access paste is a success or a failure by the worker result only.
    ProgressDialog.reject() is allowed once the result has arrived and its thread has
    stopped, so Esc in the window before the queued QThread.finished slot runs ends
    exec() with Rejected AFTER the paste committed; the dialog code must not turn that
    committed paste into 'Failed to paste bid' or skip on_cut_committed."""

    ACCEPTED = QtWidgets.QDialog.DialogCode.Accepted
    REJECTED = QtWidgets.QDialog.DialogCode.Rejected

    def _paste(self, harness, refs, **options):
        with harness.patched():
            return harness.handler.paste_bids(refs, "project-9", **options)

    def test_a_committed_cut_paste_survives_a_dialog_rejected_after_the_result(self):
        for code in (self.ACCEPTED, self.REJECTED):
            with self.subTest(code=code):
                harness = _SecondPassHierarchy(sql=False)
                harness.progress_rc = code
                cut_done = []
                self.assertIs(
                    self._paste(
                        harness,
                        [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")],
                        is_cut=True,
                        on_cut_committed=lambda: cut_done.append(1),
                    ),
                    True,
                )
                self.assertEqual(cut_done, [1])
                self.assertEqual(
                    harness.call("notify_database_refreshed"), [((harness.DB,), {})]
                )
                harness.critical.assert_not_called()
                harness.warning.assert_not_called()

    def test_a_committed_copy_paste_survives_a_dialog_rejected_after_the_result(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.progress_rc = self.REJECTED
        harness.script["duplicate_bid"] = ["copy-1", "copy-2"]
        harness.project_of = {"1": "project-9", "2": "project-2"}
        self.assertIs(
            self._paste(harness, [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")]),
            True,
        )
        self.assertEqual(len(harness.call("duplicate_bid")), 2)
        self.assertEqual(
            harness.call("notify_database_refreshed"), [((harness.DB,), {})]
        )
        harness.critical.assert_not_called()
        harness.warning.assert_not_called()

    def test_a_rejected_dialog_after_a_committed_cut_still_reports_a_failed_refresh(
        self,
    ):
        harness = _SecondPassHierarchy(sql=False)
        harness.progress_rc = self.REJECTED
        harness.script["reload_database"] = False
        cut_done = []
        with patch(f"{_PWH_MODULE}.logger"):
            self.assertIs(
                self._paste(
                    harness,
                    [BidRef(harness.DB, "1")],
                    is_cut=True,
                    on_cut_committed=lambda: cut_done.append(1),
                ),
                True,
            )
        self.assertEqual(cut_done, [1])
        self.assertEqual(harness.call("notify_database_refreshed"), [])
        harness.warning.assert_called_once()
        self.assertEqual(harness.warning.call_args.args[1], "Refresh Error")
        harness.critical.assert_not_called()

    def test_a_rejected_dialog_after_a_partial_paste_still_warns_and_succeeds(self):
        harness = _SecondPassHierarchy(sql=False)
        harness.progress_rc = self.REJECTED
        harness.script["duplicate_bid"] = ["copy-1", ""]
        with patch(f"{_PWH_MODULE}.logger"):
            self.assertIs(
                self._paste(
                    harness,
                    [BidRef(harness.DB, "1"), BidRef(harness.DB, "2")],
                ),
                True,
            )
        harness.warning.assert_called_once()
        self.assertEqual(harness.warning.call_args.args[1], "Paste Partially Completed")
        harness.critical.assert_not_called()

    def test_a_paste_that_did_not_commit_fails_for_every_dialog_code(self):
        for code in (self.ACCEPTED, self.REJECTED):
            for label, is_cut, script in (
                ("cut move refused", True, {"move_bids": False}),
                ("copy duplicate refused", False, {"duplicate_bid": ""}),
            ):
                with self.subTest(code=code, label=label):
                    harness = _SecondPassHierarchy(sql=False)
                    harness.progress_rc = code
                    harness.script.update(script)
                    cut_done = []
                    self.assertIs(
                        self._paste(
                            harness,
                            [BidRef(harness.DB, "1")],
                            is_cut=is_cut,
                            on_cut_committed=lambda: cut_done.append(1),
                        ),
                        False,
                    )
                    self.assertEqual(cut_done, [])
                    self.assertEqual(harness.call("notify_database_refreshed"), [])
                    harness.critical.assert_called_once_with(
                        "window",
                        "Paste Error",
                        f"Failed to paste bid. {DB_LOCKED_HINT}",
                    )
                    harness.warning.assert_not_called()

    def test_a_cancelled_or_crashed_worker_without_a_result_fails_for_every_code(self):
        for code in (self.ACCEPTED, self.REJECTED):
            for error in (None, RuntimeError("worker died")):
                with self.subTest(code=code, error=error):
                    harness = _SecondPassHierarchy(sql=False)
                    harness.handler._run_progress_dialog = (
                        lambda *a, code=code, error=error, **k: (code, None, error)
                    )
                    cut_done = []
                    with patch(f"{_PWH_MODULE}.logger") as logger:
                        self.assertIs(
                            self._paste(
                                harness,
                                [BidRef(harness.DB, "1")],
                                is_cut=True,
                                on_cut_committed=lambda: cut_done.append(1),
                            ),
                            False,
                        )
                    self.assertEqual(logger.error.call_count, int(error is not None))
                    self.assertEqual(cut_done, [])
                    self.assertEqual(harness.names(), [])
                    harness.critical.assert_called_once()
                    harness.warning.assert_not_called()

    def _escaping_dialog_class(self, escape_after_result, late_slot_runs):
        from ost_visualizer.presentation.components.progress_dialog import (
            ProgressDialog as RealProgressDialog,
        )

        class EscapeBetweenResultAndFinishedSlot(RealProgressDialog):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.escaped = False
                guard = QtCore.QTimer(self)
                guard.setSingleShot(True)
                guard.timeout.connect(lambda: QtWidgets.QDialog.reject(self))
                guard.start(8000)

            def _finish_if_ready(self):
                if escape_after_result and self._worker_finished:
                    if not self.escaped:
                        self.escaped = True
                        self._thread.wait(5000)
                        self.reject()
                    if not late_slot_runs:
                        return
                super()._finish_if_ready()

        return EscapeBetweenResultAndFinishedSlot

    def _paste_through_a_real_dialog(
        self, *, escape_after_result, late_slot_runs=False
    ):
        _dialog_lifecycle_support__app()
        window = QtWidgets.QWidget()
        harness = _SecondPassHierarchy(sql=False, window=window)
        del harness.handler._run_progress_dialog
        dialog_class = self._escaping_dialog_class(escape_after_result, late_slot_runs)
        cut_done = []
        try:
            with patch(f"{_PWH_MODULE}.ProgressDialog", dialog_class):
                outcome = self._paste(
                    harness,
                    [BidRef(harness.DB, "1")],
                    is_cut=True,
                    on_cut_committed=lambda: cut_done.append(1),
                )
        finally:
            window.deleteLater()
        return outcome, cut_done, harness

    def test_esc_between_the_worker_result_and_the_finished_slot_keeps_a_committed_cut(
        self,
    ):
        outcome, cut_done, harness = self._paste_through_a_real_dialog(
            escape_after_result=True
        )
        self.assertIs(outcome, True)
        self.assertEqual(cut_done, [1])
        self.assertEqual(
            harness.call("notify_database_refreshed"), [((harness.DB,), {})]
        )
        harness.critical.assert_not_called()
        harness.warning.assert_not_called()

    def test_a_real_dialog_without_an_escape_reports_the_same_committed_cut(self):
        outcome, cut_done, harness = self._paste_through_a_real_dialog(
            escape_after_result=False
        )
        self.assertIs(outcome, True)
        self.assertEqual(cut_done, [1])
        harness.critical.assert_not_called()


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
    for name in ("show_critical", "show_warning", "confirm", "ProgressDialog"):
        guard = patch(
            "ost_visualizer.presentation.handlers.project_write_handler." + name,
            side_effect=_second_pass_unexpected_modal(name),
        )
        guard.start()
        _second_pass_modal_guards.append(guard)


def tearDownModule():
    while _second_pass_modal_guards:
        _second_pass_modal_guards.pop().stop()
