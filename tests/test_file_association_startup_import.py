from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from PySide6 import QtWidgets
from ost_visualizer.application.dtos.file_import_args import (
    PROJECT_IMPORT_EXTENSION_OSP,
    PROJECT_IMPORT_EXTENSION_OST,
    parse_project_file_args,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    MutationOutcomeStatus,
    QueuedMutationResult,
)
from ost_visualizer.application.use_cases.project import (
    import_project_files_from_args_use_case as import_args_use_case,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.hierarchy_data import (
    HierarchyBidInfo,
    HierarchyData,
    HierarchyFileEntry,
    HierarchyProjectInfo,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.domain.entities.project_constants import (
    DELETED_BIDS_PROJECT_NAME,
    DELETED_BIDS_PROJECT_UID,
)
from ost_visualizer.domain.entities.workspace_state import (
    WORKSPACE_NODE_KIND_BID,
    WORKSPACE_NODE_KIND_PROJECT,
    ProjectTreeSelectionState,
    WorkspaceState,
)
from ost_visualizer.infrastructure.windows.file_associations import (
    ASSOCIATIONS,
    FileAssociationRegistrar,
    FileAssociationRegistryError,
    WinRegRegistry,
    build_open_command,
)
from ost_visualizer.main import (
    _install_single_instance_handler,
    _project_file_args_from_payload,
    _project_file_args_to_payload,
)
from ost_visualizer.presentation import main_window as main_window_module
from ost_visualizer.presentation.main_window import MainWindow

REPO_ROOT = Path(__file__).resolve().parents[1]
MSI_CREATOR_ROOT = REPO_ROOT.parent / "msicreator-master"
REPO_MSI_CONFIG = REPO_ROOT / "installer" / "ostvisualizer.json"
OST_PROG_ID = ASSOCIATIONS[PROJECT_IMPORT_EXTENSION_OST][0]
OSP_PROG_ID = ASSOCIATIONS[PROJECT_IMPORT_EXTENSION_OSP][0]


class FakeImportService:
    def __init__(self, project_data=None, new_project_uid=None, reload_result=True):
        self.calls = []
        self.reloads = []
        self.project_data = project_data
        self.new_project_uid = new_project_uid
        self.reload_result = reload_result
        self.sql_collaboration = False
        self.queued_imports = []

    def import_ost(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("ost", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def import_osp(self, source, target_db, project_uid, refresh=True):
        self.calls.append(("osp", source, target_db, project_uid, refresh))
        self._add_project(target_db)
        return True

    def reload_and_notify(self, target_db):
        self.reloads.append(target_db)
        return self.reload_result

    def uses_sql_collaboration_import(self, _target_db):
        return self.sql_collaboration

    def queue_project_import(
        self, source, source_kind, target_db, project_uid, callback
    ):
        self.queued_imports.append(
            (source, source_kind, target_db, project_uid, callback)
        )
        return len(self.queued_imports)

    def _add_project(self, target_db):
        if self.project_data is None or self.new_project_uid is None:
            return
        entry = self.project_data.hierarchy.loaded_files[0]
        entry.bid_projects[self.new_project_uid] = HierarchyProjectInfo(
            name="Imported Project"
        )


class FakeProjectData:
    def __init__(self, file_path):
        self.hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path=file_path,
                    bid_projects={
                        "stored-project": HierarchyProjectInfo(
                            name="Stored Project",
                            bids=[HierarchyBidInfo(uid="stored-bid")],
                        )
                    },
                )
            ]
        )

    def get_hierarchy(self):
        return self.hierarchy


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.deleted = []

    def set_value(self, key_path, name, value):
        self.values[(key_path, name)] = value

    def delete_tree(self, key_path):
        self.deleted.append(key_path)


class FakeProjectView:
    def __init__(self):
        self.bid_selections = []
        self.project_selections = []
        self.file_selections = []

    def restore_bid_selection(self, bid_ref):
        self.bid_selections.append(bid_ref)

    def restore_project_selection(self, project_uid, file_path=None):
        self.project_selections.append((project_uid, file_path))

    def restore_file_selection(self, file_path):
        self.file_selections.append(file_path)


class FakeTimerQueue:
    def __init__(self):
        self.callbacks = []

    def singleShot(self, _delay_ms, callback):
        self.callbacks.append(callback)


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self):
        for callback in list(self.callbacks):
            callback()


class FakeSocketBytes:
    def __init__(self, data):
        self._data = data

    def data(self):
        return self._data


class FragmentedLocalSocket:
    def __init__(self):
        self.readyRead = FakeSignal()
        self.disconnected = FakeSignal()
        self._buffer = bytearray()
        self._connected = True
        self.delete_later_calls = 0

    def push(self, data):
        self._buffer.extend(data)
        self.readyRead.emit()

    def bytesAvailable(self):
        return len(self._buffer)

    def readAll(self):
        data = bytes(self._buffer)
        self._buffer.clear()
        return FakeSocketBytes(data)

    def state(self):
        from PySide6.QtNetwork import QLocalSocket

        if self._connected:
            return QLocalSocket.LocalSocketState.ConnectedState
        return QLocalSocket.LocalSocketState.UnconnectedState

    def disconnect(self):
        self._connected = False
        self.disconnected.emit()

    def deleteLater(self):
        self.delete_later_calls += 1


class FakeLocalServer:
    def __init__(self, socket):
        self.newConnection = FakeSignal()
        self._pending = [socket]

    def hasPendingConnections(self):
        return bool(self._pending)

    def nextPendingConnection(self):
        return self._pending.pop(0)


class FakeStartupProgressDialog:
    result_code = QtWidgets.QDialog.DialogCode.Accepted
    instances = []

    def __init__(
        self, filename, task_fn, parent=None, reporter=None, action_text="Processing"
    ):
        self.filename = filename
        self.parent = parent
        self.action_text = action_text
        self.reporter = reporter
        self.result = task_fn()
        self.error = None
        self.cleanup_calls = 0
        self.delete_later_calls = 0
        self.window_modality = None
        self.instances.append(self)

    def setWindowModality(self, modality):
        self.window_modality = modality

    def exec(self):
        return self.result_code

    def cleanup(self):
        self.cleanup_calls += 1

    def deleteLater(self):
        self.delete_later_calls += 1


def _project_file_args(*paths):
    return parse_project_file_args([str(path) for path in paths])


def _startup_import_window():
    window = MainWindow.__new__(MainWindow)
    window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
    window._pending_project_file_args = []
    window._startup_load_complete = False
    window._main_window_ready = False
    window._project_file_import_scheduled = False
    window._project_file_import_running = False
    window._collaboration_shutdown_pending = False
    window._collaboration_shutdown_complete = False
    window._application_shutdown_finalized = False
    window._shutdown_deferred_callbacks = {}
    window._deferred_persistence_manager = SimpleNamespace(abort_shutdown=lambda: None)
    return window


class FileAssociationStartupImportTests(unittest.TestCase):
    def test_sql_multi_file_import_uses_independent_ordered_durable_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.ost"
            second = Path(tmp) / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            service = FakeImportService()
            service.sql_collaboration = True
            target = import_args_use_case.ProjectImportTarget("sql-database")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(
                _project_file_args(first, second), target, completed.append
            )
            self.assertEqual(len(service.queued_imports), 2)
            self.assertEqual(
                [call[1] for call in service.queued_imports], ["ost", "osp"]
            )
            service.queued_imports[0][4](
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(completed, [])
            service.queued_imports[1][4](
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=str(uuid.uuid4()),
                    outcome_status=MutationOutcomeStatus.CONFLICT,
                    message="conflicting import",
                )
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].succeeded, 1)
            self.assertEqual(completed[0].failed, 1)
            self.assertEqual(
                [result.outcome_status for result in completed[0].results],
                [MutationOutcomeStatus.COMMITTED, MutationOutcomeStatus.CONFLICT],
            )

    def test_sql_startup_import_waits_for_uncertain_commit_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            service = FakeImportService()
            service.sql_collaboration = True
            target = import_args_use_case.ProjectImportTarget("sql-database")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                service,
                FakeProjectData("sql-database"),
                SimpleNamespace(file_entries=[]),
                SimpleNamespace(),
            )
            completed = []
            use_case.queue_imports(_project_file_args(source), target, completed.append)
            queued_callback = service.queued_imports[0][4]
            operation_id = str(uuid.uuid4())
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                )
            )
            self.assertEqual(completed, [])
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=(MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED),
                )
            )
            self.assertEqual(completed, [])
            queued_callback(
                QueuedMutationResult(
                    database_id="sql-database",
                    runtime_generation=1,
                    operation_id=operation_id,
                    outcome_status=MutationOutcomeStatus.COMMITTED,
                )
            )
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0].succeeded, 1)
            self.assertEqual(
                completed[0].results[0].outcome_status,
                MutationOutcomeStatus.COMMITTED,
            )

    def test_current_project_import_target_uses_selected_database_for_duplicate_uid(
        self,
    ):
        hierarchy = HierarchyData(
            loaded_files=[
                HierarchyFileEntry(
                    file_path="first.mdb",
                    bid_projects={"1": HierarchyProjectInfo(name="First")},
                ),
                HierarchyFileEntry(
                    file_path="second.mdb",
                    bid_projects={"1": HierarchyProjectInfo(name="Second")},
                ),
            ]
        )
        window = SimpleNamespace(
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: None,
                selected_project_uid="1",
                selected_file_path="second.mdb",
            ),
            _project_data_service=SimpleNamespace(
                get_hierarchy=lambda: hierarchy,
                get_current_file_path=lambda: "first.mdb",
            ),
        )
        target = MainWindow._current_project_import_target(window)
        self.assertEqual(target.file_path, "second.mdb")
        self.assertEqual(target.project_uid, "1")

    def test_parse_project_file_args_with_no_files_keeps_startup_path_empty(self):
        result = parse_project_file_args([])
        self.assertFalse(result.has_file_args)

    def test_parse_project_file_args_accepts_ost_osp_and_preserves_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ost = root / "project with spaces.ost"
            osp = root / "package.osp"
            ost.write_text("ost")
            osp.write_text("osp")
            result = parse_project_file_args([str(ost), str(osp)])
            self.assertEqual(
                [item.extension for item in result.files],
                [PROJECT_IMPORT_EXTENSION_OST, PROJECT_IMPORT_EXTENSION_OSP],
            )
            self.assertEqual([item.path for item in result.files], [str(ost), str(osp)])
            self.assertEqual(result.rejected, [])

    def test_parse_project_file_args_rejects_unsupported_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsupported = root / "notes.txt"
            missing = root / "missing.ost"
            unsupported.write_text("x")
            result = parse_project_file_args([str(unsupported), str(missing)])
            self.assertEqual(result.files, [])
            self.assertEqual(len(result.rejected), 2)
            self.assertIn("Unsupported file type", result.rejected[0].reason)
            self.assertEqual(result.rejected[1].reason, "File does not exist.")

    def test_startup_import_waits_for_config_load_and_main_window_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import_window()
            window._pending_project_file_args.append(_project_file_args(source))
            timer = FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(timer.callbacks, [])
                window._startup_load_complete = True
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(timer.callbacks, [])
                MainWindow._mark_main_window_ready(window)
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertTrue(window._main_window_ready)
            self.assertEqual(
                timer.callbacks, [window._run_pending_project_file_imports]
            )
            self.assertTrue(window._project_file_import_scheduled)

    def test_startup_load_does_not_schedule_import_before_main_window_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import_window()
            window._pending_project_file_args.append(_project_file_args(source))
            window.app_controller = SimpleNamespace(
                load_files_from_config=lambda: ["target.mdb"],
                has_any_databases=lambda: True,
            )
            window.handlers = SimpleNamespace(
                ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
            )
            window._workspace_state_coordinator = SimpleNamespace(
                restore_deferred_state=lambda: None
            )
            timer = FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._load_files_from_config(window)
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertTrue(window._startup_load_complete)
            self.assertEqual(
                timer.callbacks,
                [window._restore_deferred_workspace_state],
            )
            self.assertFalse(window._project_file_import_scheduled)

    def test_ready_startup_import_batches_pending_args_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.ost"
            second = root / "second.osp"
            first.write_text("ost")
            second.write_text("osp")
            window = _startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            execute_calls = []
            refresh_calls = []
            flush_calls = []
            selections = []
            summaries = []
            target = import_args_use_case.ProjectImportTarget("target.mdb")
            window._import_project_files_from_args = SimpleNamespace(
                resolve_target=lambda _current_target: target,
                uses_async_import=lambda _target: False,
                execute_imports=lambda args, target, refresh_after_import=True: (
                    execute_calls.append((args, target, refresh_after_import))
                    or import_args_use_case.ProjectFileImportBatchResult(
                        results=[
                            import_args_use_case.ProjectFileImportResult(
                                source_path=args.files[0].path,
                                success=True,
                                message="Imported successfully.",
                            )
                        ],
                        target_db_path=target.file_path,
                        refresh_pending=True,
                    )
                ),
                refresh_import_result=lambda result: refresh_calls.append(result)
                or import_args_use_case.ProjectFileImportBatchResult(
                    target_db_path=result.target_db_path
                ),
            )
            window._current_project_import_target = lambda: None
            window._deferred_persistence_manager = SimpleNamespace(
                flush_for_file=lambda path: flush_calls.append(path) or True
            )
            window._select_project_file_import_result = selections.append
            window._show_project_file_import_result = summaries.append
            timer = FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            original_progress_dialog = main_window_module.ProgressDialog
            try:
                FakeStartupProgressDialog.instances = []
                main_window_module.ProgressDialog = FakeStartupProgressDialog
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow.enqueue_project_file_args(window, _project_file_args(first))
                MainWindow.enqueue_project_file_args(window, _project_file_args(second))
                self.assertEqual(
                    timer.callbacks, [window._run_pending_project_file_imports]
                )
                timer.callbacks.pop(0)()
            finally:
                main_window_module.ProgressDialog = original_progress_dialog
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertEqual(len(execute_calls), 1)
            self.assertIs(execute_calls[0][1], target)
            self.assertFalse(execute_calls[0][2])
            self.assertEqual(
                [item.path for item in execute_calls[0][0].files],
                [str(first), str(second)],
            )
            self.assertEqual(flush_calls, ["target.mdb"])
            self.assertEqual(len(refresh_calls), 1)
            self.assertEqual(len(selections), 1)
            self.assertEqual(len(summaries), 1)
            self.assertEqual(len(FakeStartupProgressDialog.instances), 1)
            self.assertIs(FakeStartupProgressDialog.instances[0].parent, window)
            self.assertEqual(
                FakeStartupProgressDialog.instances[0].action_text, "Importing"
            )
            self.assertFalse(window._pending_project_file_args)
            self.assertFalse(window._project_file_import_scheduled)
            self.assertFalse(window._project_file_import_running)

    def test_queued_startup_load_is_ignored_after_shutdown_starts(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: self.fail(
                "Startup database loading must not begin during shutdown"
            )
        )
        MainWindow._load_files_from_config(window)
        self.assertFalse(window._startup_load_complete)

    def test_queued_startup_load_replays_when_shutdown_is_aborted(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        loads = []
        shown = []
        restores = []
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: loads.append(True) or ["target.mdb"],
            has_any_databases=lambda: True,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            restore_deferred_state=lambda: restores.append(True)
        )
        window.show = lambda: shown.append(True)
        timer = FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        original_show_critical = main_window_module.show_critical
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            main_window_module.show_critical = lambda *_args: None
            MainWindow._load_files_from_config(window)
            self.assertEqual(loads, [])
            MainWindow._on_shutdown_mutation_drain_complete(
                window, False, "shutdown aborted"
            )
            while timer.callbacks:
                timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
            main_window_module.show_critical = original_show_critical
        self.assertEqual(shown, [True])
        self.assertEqual(loads, [True])
        self.assertEqual(restores, [True])
        self.assertTrue(window._startup_load_complete)

    def test_aborted_shutdown_replays_startup_load_before_main_window_show(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        calls = []
        window._needs_create_database_prompt = False
        window._update_service = None
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: calls.append("load") or [],
            has_any_databases=lambda: False,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: calls.append("show"),
            restore_deferred_state=lambda: calls.append("restore"),
        )
        window.raise_ = lambda: None
        window.activateWindow = lambda: None
        window._prompt_create_database = lambda: calls.append("prompt")
        timer = FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._show_main_window(window)
            MainWindow._load_files_from_config(window)
            window._collaboration_shutdown_pending = False
            MainWindow._resume_shutdown_deferred_callbacks(window)
            while timer.callbacks:
                timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(calls[:2], ["load", "show"])
        self.assertEqual(calls.count("prompt"), 1)

    def test_deferred_workspace_restore_waits_for_tentative_shutdown(self):
        window = _startup_import_window()
        restores = []
        window.app_controller = SimpleNamespace(
            load_files_from_config=lambda: ["target.mdb"],
            has_any_databases=lambda: True,
        )
        window.handlers = SimpleNamespace(
            ui_event=SimpleNamespace(sync_after_startup_load=lambda: None)
        )
        window._workspace_state_coordinator = SimpleNamespace(
            restore_deferred_state=lambda: restores.append(True)
        )
        timer = FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._load_files_from_config(window)
            window._collaboration_shutdown_pending = True
            timer.callbacks.pop(0)()
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(restores, [])
        self.assertTrue(window._shutdown_deferred_callbacks)

    def test_queued_main_window_show_is_ignored_after_shutdown_starts(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: self.fail(
                "A queued startup callback must not reshow the closing window"
            )
        )
        MainWindow._show_main_window(window)

    def test_normal_main_window_show_schedules_update_and_database_prompt(self):
        window = _startup_import_window()
        calls = []
        window._workspace_state_coordinator = SimpleNamespace(
            show_main_window=lambda: calls.append("show")
        )
        window.raise_ = lambda: calls.append("raise")
        window.activateWindow = lambda: calls.append("activate")
        window._update_service = object()
        window._needs_create_database_prompt = True
        timer = FakeTimerQueue()
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._show_main_window(window)
        finally:
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertEqual(calls, ["show", "raise", "activate"])
        self.assertEqual(
            timer.callbacks,
            [window._check_for_updates, window._prompt_create_database],
        )
        self.assertFalse(window._needs_create_database_prompt)

    def test_queued_create_database_prompt_is_ignored_after_shutdown_starts(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        window.ui_access_manager = SimpleNamespace(
            is_allowed=lambda _feature: self.fail(
                "A queued database prompt must not inspect access during shutdown"
            )
        )
        MainWindow._prompt_create_database(window)

    def test_create_database_prompt_does_not_continue_when_shutdown_starts_in_dialog(
        self,
    ):
        window = _startup_import_window()
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window.icon_provider = object()
        window._create_database_with_progress = lambda: self.fail(
            "Database creation must not begin after shutdown starts"
        )

        class ShutdownDialog:
            deleted = False

            def __init__(self, _icon_provider, _parent):
                pass

            def exec(self):
                window._collaboration_shutdown_pending = True
                return main_window_module.QtWidgets.QDialog.DialogCode.Accepted

            def deleteLater(self):
                type(self).deleted = True

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = ShutdownDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog
        self.assertTrue(ShutdownDialog.deleted)

    def test_create_database_prompt_completes_normally_before_shutdown(self):
        window = _startup_import_window()
        window.icon_provider = object()
        window._create_database_with_progress = lambda: "new.mdb"
        window._file_loading_service = SimpleNamespace(
            load_file=lambda path: SimpleNamespace(success=True, file_path=path)
        )
        published = []
        window.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )

        class AcceptedDialog:
            deleted = False

            def __init__(self, _icon_provider, _parent):
                pass

            def exec(self):
                return main_window_module.QtWidgets.QDialog.DialogCode.Accepted

            def deleteLater(self):
                type(self).deleted = True

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = AcceptedDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog
        self.assertTrue(AcceptedDialog.deleted)
        self.assertEqual(
            published,
            [(main_window_module.AppEvents.FILE_OPENED, {"file_path": "new.mdb"})],
        )

    def test_deferred_database_creation_revalidates_a_second_shutdown(self):
        window = _startup_import_window()
        window._collaboration_shutdown_pending = True
        window._create_database_with_progress = lambda: self.fail(
            "Deferred database creation must revalidate shutdown ownership"
        )
        MainWindow._complete_create_database_prompt(window)
        self.assertIn(
            "create_database_after_prompt", window._shutdown_deferred_callbacks
        )

    def test_database_creation_does_not_load_when_shutdown_starts_in_progress(self):
        window = _startup_import_window()
        loads = []

        def create_database():
            window._collaboration_shutdown_pending = True
            return "new.mdb"

        window._create_database_with_progress = create_database
        window._file_loading_service = SimpleNamespace(load_file=loads.append)
        MainWindow._complete_create_database_prompt(window)
        self.assertEqual(loads, [])
        self.assertTrue(window._shutdown_deferred_callbacks)

    def test_database_creation_failure_notice_waits_when_shutdown_starts_in_progress(
        self,
    ):
        window = _startup_import_window()
        warnings = []

        def create_database():
            window._collaboration_shutdown_pending = True
            return None

        window._create_database_with_progress = create_database
        original_show_warning = main_window_module.show_warning
        try:
            main_window_module.show_warning = lambda *_args: warnings.append(True)
            MainWindow._complete_create_database_prompt(window)
        finally:
            main_window_module.show_warning = original_show_warning
        self.assertEqual(warnings, [])
        self.assertTrue(window._shutdown_deferred_callbacks)

    def test_database_prompt_tolerates_parent_destroying_dialog(self):
        from shiboken6 import delete

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        window = _startup_import_window()
        window.icon_provider = object()
        window.ui_access_manager = SimpleNamespace(is_allowed=lambda _feature: True)
        window._complete_create_database_prompt = lambda: self.fail(
            "A rejected prompt must not create a database"
        )

        class DestroyedCreateDatabaseDialog(QtWidgets.QDialog):
            def __init__(self, *_args):
                super().__init__()

            def exec(self):
                delete(self)
                return QtWidgets.QDialog.DialogCode.Rejected

        original_dialog = main_window_module.CreateDatabaseDialog
        try:
            main_window_module.CreateDatabaseDialog = DestroyedCreateDatabaseDialog
            MainWindow._prompt_create_database(window)
        finally:
            main_window_module.CreateDatabaseDialog = original_dialog

    def test_queued_startup_import_does_not_begin_after_shutdown_starts(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(_project_file_args(source))
            window._import_project_files_with_progress = lambda _args: self.fail(
                "A queued startup import must not begin during shutdown"
            )
            timer = FakeTimerQueue()
            original_single_shot = main_window_module.QtCore.QTimer.singleShot
            try:
                main_window_module.QtCore.QTimer.singleShot = timer.singleShot
                MainWindow._schedule_pending_project_file_imports(window)
                self.assertEqual(
                    timer.callbacks, [window._run_pending_project_file_imports]
                )
                window._collaboration_shutdown_pending = True
                timer.callbacks.pop()()
            finally:
                main_window_module.QtCore.QTimer.singleShot = original_single_shot
            self.assertFalse(window._project_file_import_scheduled)
            self.assertFalse(window._project_file_import_running)
            self.assertEqual(len(window._pending_project_file_args), 1)

    def test_async_startup_import_completion_does_not_project_during_shutdown(self):
        window = _startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        window._select_project_file_import_result = lambda _result: self.fail(
            "A shutdown completion must not change project selection"
        )
        window._show_project_file_import_result = lambda _result: self.fail(
            "A shutdown completion must not open a result dialog"
        )
        window._schedule_pending_project_file_imports = lambda: self.fail(
            "Shutdown must not schedule another startup import"
        )
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        original_is_valid = main_window_module.isValid
        try:
            main_window_module.isValid = lambda _window: True
            MainWindow._complete_async_project_file_imports(window, result)
        finally:
            main_window_module.isValid = original_is_valid
        self.assertFalse(window._project_file_import_running)
        self.assertIn(
            "complete_project_file_imports", window._shutdown_deferred_callbacks
        )

    def test_sync_startup_import_completion_waits_when_shutdown_starts_in_progress(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(_project_file_args(source))
            selections = []
            summaries = []
            result = import_args_use_case.ProjectFileImportBatchResult(
                target_db_path="target.mdb"
            )

            def import_with_progress(_args):
                window._collaboration_shutdown_pending = True
                return result

            window._import_project_files_with_progress = import_with_progress
            window._select_project_file_import_result = selections.append
            window._show_project_file_import_result = summaries.append
            MainWindow._run_pending_project_file_imports(window)
            self.assertEqual(selections, [])
            self.assertEqual(summaries, [])
            self.assertIn(
                "complete_project_file_imports",
                window._shutdown_deferred_callbacks,
            )

    def test_sync_startup_import_does_not_refresh_after_terminal_modal_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            window = _startup_import_window()
            window._startup_load_complete = True
            window._main_window_ready = True
            window._pending_project_file_args.append(_project_file_args(source))
            target = import_args_use_case.ProjectImportTarget("target.mdb")
            raw_result = import_args_use_case.ProjectFileImportBatchResult(
                results=[
                    import_args_use_case.ProjectFileImportResult(
                        source_path=str(source),
                        success=True,
                        message="Imported successfully.",
                    )
                ],
                target_db_path=target.file_path,
                refresh_pending=True,
            )
            refreshes = []
            window._current_project_import_target = lambda: None
            window._deferred_persistence_manager = SimpleNamespace(
                flush_for_file=lambda _path: True
            )
            window._import_project_files_from_args = SimpleNamespace(
                resolve_target=lambda _current: target,
                uses_async_import=lambda _target: False,
                execute_imports=lambda *_args, **_kwargs: raw_result,
                refresh_import_result=lambda result: refreshes.append(result) or result,
            )
            window._select_project_file_import_result = lambda _result: self.fail(
                "Terminal shutdown must not project the imported project"
            )
            window._show_project_file_import_result = lambda _result: self.fail(
                "Terminal shutdown must not show an import result"
            )

            class ClosingProgressDialog(FakeStartupProgressDialog):
                def exec(self):
                    window._collaboration_shutdown_complete = True
                    return self.result_code

            original_progress_dialog = main_window_module.ProgressDialog
            try:
                main_window_module.ProgressDialog = ClosingProgressDialog
                MainWindow._run_pending_project_file_imports(window)
            finally:
                main_window_module.ProgressDialog = original_progress_dialog
            self.assertEqual(refreshes, [])
            self.assertFalse(window._project_file_import_running)

    def test_terminal_shutdown_discards_deferred_startup_import_completion(self):
        window = _startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        window._select_project_file_import_result = lambda _result: self.fail(
            "Terminal shutdown must not project a deferred import"
        )
        window._show_project_file_import_result = lambda _result: self.fail(
            "Terminal shutdown must not show a deferred import result"
        )
        window._schedule_pending_project_file_imports = lambda: self.fail(
            "Terminal shutdown must not schedule another import"
        )
        window.close = lambda: None
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        timer = FakeTimerQueue()
        original_is_valid = main_window_module.isValid
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        try:
            main_window_module.isValid = lambda _window: True
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            MainWindow._complete_async_project_file_imports(window, result)
            MainWindow._on_collaboration_shutdown_complete(window, True, "")
        finally:
            main_window_module.isValid = original_is_valid
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
        self.assertTrue(window._collaboration_shutdown_complete)
        self.assertEqual(window._shutdown_deferred_callbacks, {})

    def test_async_startup_import_completion_replays_when_shutdown_is_aborted(self):
        window = _startup_import_window()
        window._project_file_import_running = True
        window._collaboration_shutdown_pending = True
        selections = []
        summaries = []
        scheduled_imports = []
        shown = []
        window._select_project_file_import_result = selections.append
        window._show_project_file_import_result = summaries.append
        window._schedule_pending_project_file_imports = (
            lambda: scheduled_imports.append(True)
        )
        window.show = lambda: shown.append(True)
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="sql-database"
        )
        timer = FakeTimerQueue()
        original_is_valid = main_window_module.isValid
        original_single_shot = main_window_module.QtCore.QTimer.singleShot
        original_show_critical = main_window_module.show_critical
        try:
            main_window_module.isValid = lambda _window: True
            main_window_module.QtCore.QTimer.singleShot = timer.singleShot
            main_window_module.show_critical = lambda *_args: None
            MainWindow._complete_async_project_file_imports(window, result)
            self.assertEqual(selections, [])
            self.assertFalse(window._project_file_import_running)
            MainWindow._on_shutdown_mutation_drain_complete(
                window, False, "shutdown aborted"
            )
            for callback in list(timer.callbacks):
                callback()
        finally:
            main_window_module.isValid = original_is_valid
            main_window_module.QtCore.QTimer.singleShot = original_single_shot
            main_window_module.show_critical = original_show_critical
        self.assertEqual(shown, [True])
        self.assertEqual(selections, [result])
        self.assertEqual(summaries, [result])
        self.assertEqual(scheduled_imports, [True])
        self.assertFalse(window._project_file_import_running)

    def test_startup_import_summary_uses_main_window_parent(self):
        window = _startup_import_window()
        calls = []
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path="source.ost",
                    success=True,
                    message="Imported successfully.",
                    project_name="Imported Project",
                )
            ],
            target_db_path="target.mdb",
            selected_project_uid="project-1",
        )
        original_show_info = main_window_module.show_info
        try:
            main_window_module.show_info = lambda parent, title, details: calls.append(
                (parent, title, details)
            )
            MainWindow._show_project_file_import_result(window, result)
        finally:
            main_window_module.show_info = original_show_info
        self.assertEqual(calls[0][0], window)
        self.assertEqual(calls[0][1], "Import Complete")

    def test_startup_import_success_message_uses_source_path(self):
        source = "C:/Users/fabia/Downloads/Woodside Village.osp"
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path=source,
                    success=True,
                    message="Imported successfully.",
                    project_name=DELETED_BIDS_PROJECT_NAME,
                )
            ],
            target_db_path="target.mdb",
            selected_project_uid=DELETED_BIDS_PROJECT_UID,
        )
        details = MainWindow._format_project_file_import_details(
            _startup_import_window(), result
        )
        self.assertEqual(
            details,
            f"Successfully imported '{source}' into the database.",
        )

    def test_startup_import_orphan_message_explains_deleted_bids_fallback(self):
        source = "C:/Users/fabia/Downloads/Woodside Village.osp"
        result = import_args_use_case.ProjectFileImportBatchResult(
            results=[
                import_args_use_case.ProjectFileImportResult(
                    source_path=source,
                    success=True,
                    message="Imported successfully.",
                )
            ],
            target_db_path="target.mdb",
            import_as_orphaned_due_to_deleted_target=True,
        )
        details = MainWindow._format_project_file_import_details(
            _startup_import_window(), result
        )
        self.assertEqual(
            details,
            f"Successfully imported '{source}' as orphaned because "
            f"{DELETED_BIDS_PROJECT_NAME} cannot be used as an import target.",
        )

    def test_import_use_case_uses_stored_project_before_first_checked_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_PROJECT,
                file_path=str(target_db),
                project_uid="stored-project",
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertEqual(import_service.calls[0][0], "ost")
            self.assertEqual(import_service.calls[0][2], str(target_db))
            self.assertEqual(import_service.calls[0][3], "stored-project")
            self.assertIs(import_service.calls[0][4], False)
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_import_use_case_resolves_stored_bid_to_project_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="stored-bid",
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            use_case.execute(parse_project_file_args([str(source)]), lambda _path: True)
            self.assertEqual(import_service.calls[0][3], "stored-project")

    def test_import_use_case_imports_deleted_bids_project_target_as_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_PROJECT,
                file_path=str(target_db),
                project_uid=DELETED_BIDS_PROJECT_UID,
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)
            self.assertIsNone(result.selected_project_uid)

    def test_import_use_case_imports_deleted_bids_bid_target_as_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            workspace = WorkspaceState()
            workspace.project_workspace.selected_node = ProjectTreeSelectionState(
                kind=WORKSPACE_NODE_KIND_BID,
                file_path=str(target_db),
                bid_uid="deleted-bid",
            )
            project_data = FakeProjectData(str(target_db))
            project_data.hierarchy.loaded_files[0].bid_projects[
                DELETED_BIDS_PROJECT_UID
            ] = HierarchyProjectInfo(
                name=DELETED_BIDS_PROJECT_NAME,
                bids=[HierarchyBidInfo(uid="deleted-bid")],
            )
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=workspace),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 1)
            self.assertIsNone(import_service.calls[0][3])
            self.assertTrue(result.import_as_orphaned_due_to_deleted_target)

    def test_import_use_case_imports_multiple_files_sequentially(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            ost = root / "source.ost"
            osp = root / "source.osp"
            target_db.write_text("db")
            ost.write_text("ost")
            osp.write_text("osp")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(ost), str(osp)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 2)
            self.assertEqual([call[0] for call in import_service.calls], ["ost", "osp"])
            self.assertEqual(import_service.reloads, [str(target_db)])

    def test_main_window_selects_batch_project_or_database_once(self):
        window = SimpleNamespace(
            project_view=FakeProjectView(),
            ui_state_manager=SimpleNamespace(get_selected_bid_ref=lambda: None),
            _project_data_service=SimpleNamespace(get_bid=lambda _bid_ref: None),
        )
        project_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
            selected_project_uid="project-1",
        )
        database_result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
        )
        MainWindow._select_project_file_import_result(window, project_result)
        MainWindow._select_project_file_import_result(window, database_result)
        self.assertEqual(
            window.project_view.project_selections, [("project-1", "target.mdb")]
        )
        self.assertEqual(window.project_view.file_selections, ["target.mdb"])

    def test_main_window_preserves_active_bid_after_import_into_project(self):
        selected_bid_ref = BidRef("target.mdb", "38")
        window = SimpleNamespace(
            project_view=FakeProjectView(),
            ui_state_manager=SimpleNamespace(
                get_selected_bid_ref=lambda: selected_bid_ref
            ),
            _project_data_service=SimpleNamespace(
                get_bid=lambda bid_ref: (
                    object() if bid_ref == selected_bid_ref else None
                )
            ),
        )
        result = import_args_use_case.ProjectFileImportBatchResult(
            target_db_path="target.mdb",
            selected_project_uid="comparison",
        )
        MainWindow._select_project_file_import_result(window, result)
        self.assertEqual(window.project_view.bid_selections, [selected_bid_ref])
        self.assertEqual(window.project_view.project_selections, [])
        self.assertEqual(window.project_view.file_selections, [])

    def test_import_use_case_reports_missing_enabled_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.osp"
            source.write_text("osp")
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=FakeImportService(),
                project_data_service=FakeProjectData(str(Path(tmp) / "missing.mdb")),
                file_state_model=SimpleNamespace(file_entries=[]),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.succeeded, 0)
            self.assertEqual(result.failed, 1)
            self.assertIn("Enable or store a database", result.results[0].message)

    def test_import_use_case_flush_failure_prevents_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: False,
            )
            self.assertEqual(result.failed, 1)
            self.assertEqual(import_service.calls, [])
            self.assertIn("Pending database changes", result.results[0].message)

    def test_import_use_case_reports_refresh_failure_after_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            import_service = FakeImportService(reload_result=False)
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(target_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.failed, 1)
            self.assertIn("could not be refreshed", result.results[0].message)

    def test_import_use_case_prefers_current_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_db = root / "first.mdb"
            current_db = root / "current.mdb"
            source = root / "source.osp"
            first_db.write_text("db")
            current_db.write_text("db")
            source.write_text("osp")
            import_service = FakeImportService()
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=import_service,
                project_data_service=FakeProjectData(str(current_db)),
                file_state_model=SimpleNamespace(
                    file_entries=[
                        FileEntry(str(first_db), is_checked=True),
                        FileEntry(str(current_db), is_checked=True),
                    ]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            use_case.execute(
                parse_project_file_args([str(source)]),
                lambda _path: True,
                current_target=import_args_use_case.ProjectImportCurrentTarget(
                    file_path=str(current_db), project_uid="current-project"
                ),
            )
            self.assertEqual(import_service.calls[0][2], str(current_db))
            self.assertEqual(import_service.calls[0][3], "current-project")

    def test_import_use_case_accepts_checked_sql_database_as_current_target(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST",
                database_guid="00000000-0000-0000-0000-000000000111",
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
        use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
            import_service=FakeImportService(),
            project_data_service=FakeProjectData(descriptor.database_id),
            file_state_model=SimpleNamespace(
                file_entries=[FileEntry.for_descriptor(descriptor)]
            ),
            workspace_state_model=SimpleNamespace(state=WorkspaceState()),
        )
        target = use_case.resolve_target(
            import_args_use_case.ProjectImportCurrentTarget(
                file_path=descriptor.database_id,
                project_uid="sql-project",
            )
        )
        self.assertEqual(
            target,
            import_args_use_case.ProjectImportTarget(
                file_path=descriptor.database_id,
                project_uid="sql-project",
            ),
        )

    def test_import_use_case_detects_single_new_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_db = root / "target.mdb"
            source = root / "source.ost"
            target_db.write_text("db")
            source.write_text("ost")
            project_data = FakeProjectData(str(target_db))
            use_case = import_args_use_case.ImportProjectFilesFromArgsUseCase(
                import_service=FakeImportService(project_data, "new-project"),
                project_data_service=project_data,
                file_state_model=SimpleNamespace(
                    file_entries=[FileEntry(str(target_db), is_checked=True)]
                ),
                workspace_state_model=SimpleNamespace(state=WorkspaceState()),
            )
            result = use_case.execute(
                parse_project_file_args([str(source)]), lambda _path: True
            )
            self.assertEqual(result.selected_project_uid, "new-project")
            self.assertEqual(result.results[0].project_name, "Imported Project")

    def test_socket_payload_round_trip_preserves_file_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            args = parse_project_file_args([str(source), str(Path(tmp) / "bad.txt")])
            restored = _project_file_args_from_payload(
                _project_file_args_to_payload(args)
            )
            self.assertEqual(restored.files, args.files)
            self.assertEqual(restored.rejected, args.rejected)

    def test_single_instance_handler_buffers_fragmented_socket_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.ost"
            source.write_text("ost")
            args = parse_project_file_args([str(source)])
            payload = _project_file_args_to_payload(args)
            socket = FragmentedLocalSocket()
            server = FakeLocalServer(socket)
            queued = []
            window = SimpleNamespace(enqueue_project_file_args=queued.append)
            logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)
            _install_single_instance_handler(server, window, logger)
            midpoint = len(payload) // 2
            socket.push(payload[:midpoint])
            socket.push(payload[midpoint:])
            self.assertEqual(queued, [])
            socket.disconnect()
            self.assertEqual(queued, [args])
            self.assertEqual(socket.delete_later_calls, 1)

    def test_registry_register_and_unregister_keys(self):
        registry = FakeRegistry()
        exe = Path("C:/Program Files/OST Visualizer/Visualizer.exe")
        registrar = FileAssociationRegistrar(executable_path=exe, registry=registry)
        registrar.register()
        registrar.unregister()
        command = build_open_command(exe)
        self.assertEqual(
            command, '"C:\\Program Files\\OST Visualizer\\Visualizer.exe" "%1"'
        )
        for extension, (prog_id, description) in ASSOCIATIONS.items():
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{extension}", "")],
                prog_id,
            )
            self.assertEqual(
                registry.values[(f"Software\\Classes\\{prog_id}", "")],
                description,
            )
            self.assertEqual(
                registry.values[
                    (f"Software\\Classes\\{prog_id}\\shell\\open\\command", "")
                ],
                command,
            )
            self.assertIn(f"Software\\Classes\\{extension}", registry.deleted)
            self.assertIn(f"Software\\Classes\\{prog_id}", registry.deleted)

    def test_registry_command_can_include_development_script(self):
        command = build_open_command(
            Path("C:/Python311/python.exe"),
            Path("C:/Projects/OST Visualizer/Visualizer.py"),
        )
        self.assertEqual(
            command,
            '"C:\\Python311\\python.exe" '
            '"C:\\Projects\\OST Visualizer\\Visualizer.py" "%1"',
        )

    def test_winreg_registry_reports_non_windows_import_failure(self):
        def missing_winreg(_name):
            raise ImportError("no winreg")

        with self.assertRaisesRegex(FileAssociationRegistryError, "only be registered"):
            WinRegRegistry(import_module=missing_winreg)

    def test_msi_config_contains_installed_file_associations(self):
        config = json.loads(REPO_MSI_CONFIG.read_text(encoding="utf-8"))
        entries = {
            (entry["root"], entry["key"], entry.get("name")): entry
            for entry in config["registry_entries"]
        }
        self.assertEqual(
            entries[
                ("HKLM", f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OST}", None)
            ]["value"],
            OST_PROG_ID,
        )
        self.assertEqual(
            entries[
                ("HKLM", f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OSP}", None)
            ]["value"],
            OSP_PROG_ID,
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    f"Software\\Classes\\{OST_PROG_ID}\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )
        self.assertEqual(
            entries[
                (
                    "HKLM",
                    f"Software\\Classes\\{OSP_PROG_ID}\\shell\\open\\command",
                    None,
                )
            ]["value"],
            '"[INSTALLDIR]Visualizer.exe" "%1"',
        )

    def test_external_msi_config_matches_checked_in_source_when_available(self):
        external_config = MSI_CREATOR_ROOT / "ostvisualizer.json"
        if not external_config.exists():
            self.skipTest("msicreator-master checkout is not available")
        repo_config = json.loads(REPO_MSI_CONFIG.read_text(encoding="utf-8"))
        builder_config = json.loads(external_config.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            builder_config["registry_entries"], repo_config["registry_entries"]
        )

    def test_msi_creator_omits_name_for_default_registry_value(self):
        module_path = MSI_CREATOR_ROOT / "createmsi.py"
        if not module_path.exists():
            self.skipTest("msicreator-master checkout is not available")
        spec = importlib.util.spec_from_file_location("createmsi_external", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        component = ET.Element("Component")
        module.PackageGenerator.create_registry_entries(
            None,
            component,
            {
                "root": "HKLM",
                "key": f"Software\\Classes\\{PROJECT_IMPORT_EXTENSION_OST}",
                "name": None,
                "type": "string",
                "value": OST_PROG_ID,
                "key_path": "yes",
            },
        )
        value = component.find("RegistryKey/RegistryValue")
        self.assertIsNotNone(value)
        self.assertNotIn("Name", value.attrib)
        self.assertEqual(value.attrib["Value"], OST_PROG_ID)


if __name__ == "__main__":
    unittest.main()
