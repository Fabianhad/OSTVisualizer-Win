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
from PySide6 import QtWidgets
from shiboken6 import delete
from tests.presentation.handlers.project_command_support import (
    _DeferredPersistenceRequiringBidCancel as _permissions__DeferredPersistenceRequiringBidCancel,
    _DeferredPersistenceRequiringSelectedPageFileCancel as _permissions__DeferredPersistenceRequiringSelectedPageFileCancel,
    _DeleteBidUiState as _permissions__DeleteBidUiState,
    _FakeDeferredPersistence as _permissions__FakeDeferredPersistence,
    _MoveToDeletedWriteService as _permissions__MoveToDeletedWriteService,
    _PartialPasteWriteService as _permissions__PartialPasteWriteService,
    _QueuedHierarchyDeleteWriteService as _permissions__QueuedHierarchyDeleteWriteService,
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
        handler = ProjectWriteHandler(
            window=None,
            project_data_service=SimpleNamespace(),
            project_write_service=write_service,
            ui_state_manager=SimpleNamespace(),
            deferred_persistence_manager=_permissions__FakeDeferredPersistence(),
        )
        handler.set_ui_event_coordinator(
            SimpleNamespace(
                refresh_hierarchy_projection=lambda: None,
                present_queued_mutation_error=lambda *_args: None,
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
        self.assertIn("Some bids were pasted", warnings[0][2])
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
        with patch(
            "ost_visualizer.presentation.handlers.project_write_handler.show_critical",
            side_effect=lambda *args: criticals.append(args),
        ):
            handler.duplicate_selected()
        self.assertEqual(len(criticals), 0)
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
        self.assertFalse(result)
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
        replacement = ui_state.get_selected_bid_ref()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.bid_uid, "bid-2")
        self.assertEqual(
            [
                ref.bid_uid if ref else None
                for ref in write_service.selected_bid_during_notify
            ],
            ["bid-2"],
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
        self.assertEqual(len(write_service.callbacks), 1)
        ui_state.set_bid_selection(replacement)
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=original.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000101",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(ui_state.get_selected_bid_ref(), replacement)
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
        self.assertFalse(duplicate_action.isEnabled())
        write_service.callbacks[0](
            QueuedMutationResult(
                database_id=bid_ref.file_path,
                runtime_generation=1,
                operation_id="00000000-0000-0000-0000-000000000105",
                outcome_status=MutationOutcomeStatus.COMMITTED,
            )
        )
        self.assertEqual(refresh_calls, [True])
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
        self.assertEqual(len(presented_errors), 1)
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
        replacement = ui_state.get_selected_bid_ref()
        self.assertIsNotNone(replacement)
        self.assertEqual(replacement.bid_uid, "deleted-2")
        self.assertEqual(
            [
                ref.bid_uid if ref else None
                for ref in write_service.selected_bid_during_notify
            ],
            ["deleted-2"],
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
