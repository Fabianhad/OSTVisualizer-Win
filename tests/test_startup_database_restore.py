import logging
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtWidgets
from ost_visualizer.application.app_controller import AppController
from ost_visualizer.application.use_cases.project.load_file_use_case import (
    LoadFileUseCase,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.domain.entities.file_results import FileLoadResult
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.domain.aggregates.file_state_aggregate import FileStateAggregate
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from ost_visualizer.presentation.dialogs.open_files_dialog import OpenFilesDialog


class StartupDatabaseRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_failed_database_load_preserves_existing_access_projection(self):
        class _DataService:
            reset_count = 0

            def reset(self):
                self.reset_count += 1

        data_service = _DataService()
        model = SimpleNamespace(projects=["access-project"])
        file_manager = SimpleNamespace(
            load_file=lambda _locator: FileLoadResult(
                success=False, error_message="server unavailable"
            )
        )
        use_case = LoadFileUseCase(
            model,
            data_service,
            file_manager,
            logging.getLogger("test.startup.load"),
        )
        self.assertFalse(use_case.execute("sql-database-id"))
        self.assertEqual(data_service.reset_count, 0)
        self.assertEqual(model.projects, ["access-project"])

    def test_failed_file_state_save_preserves_authoritative_in_memory_entries(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)

        class _FailingRepository:
            def load(self):
                return FileState(file_entries=[original])

            def save(self, _state):
                raise OSError("disk unavailable")

        aggregate = FileStateAggregate(_FailingRepository())
        with self.assertRaises(OSError):
            aggregate.update_entries([original.with_checked(False)])
        self.assertEqual(aggregate.file_entries, [original])

    def test_file_state_entries_are_defensive_copies(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)
        repository = SimpleNamespace(
            load=lambda: FileState(file_entries=[original]),
            save=lambda _state: None,
        )
        aggregate = FileStateAggregate(repository)
        returned_entry = aggregate.file_entries[0]
        returned_entry.is_checked = False
        self.assertTrue(aggregate.file_entries[0].is_checked)

    def test_file_state_update_does_not_retain_caller_owned_entries(self):
        repository = SimpleNamespace(
            load=lambda: FileState(),
            save=lambda _state: None,
        )
        aggregate = FileStateAggregate(repository)
        caller_entry = FileEntry("C:/projects/active.mdb", is_checked=True)
        aggregate.update_entries([caller_entry])
        caller_entry.is_checked = False
        self.assertTrue(aggregate.file_entries[0].is_checked)

    def test_file_state_reload_failure_preserves_last_known_entries(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)

        class _Repository:
            load_count = 0

            def load(self):
                self.load_count += 1
                if self.load_count == 1:
                    return FileState(file_entries=[original])
                raise OSError("temporary read failure")

            def save(self, _state):
                pass

        aggregate = FileStateAggregate(_Repository())
        aggregate.reload()
        self.assertEqual(aggregate.file_entries, [original])

    def test_startup_loads_access_synchronously_and_starts_sql_asynchronously(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            access_path = Path(temp_dir) / "available.mdb"
            access_path.touch()
            access_entry = FileEntry(str(access_path), is_checked=True)
            sql_descriptor = DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="localhost", database="UNAVAILABLE_SQL"
                ),
                schema_version=SQL_SCHEMA_V1.version,
            )
            sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
            execute_calls = []
            starts = []
            connected = []

            class _LoadConfigured:
                def execute(self, backends):
                    execute_calls.append((set(backends), threading.get_ident()))
                    return [access_entry.runtime_locator]

            controller = AppController.__new__(AppController)
            controller.logger = logging.getLogger("test.startup.controller")
            controller._auto_discover_databases = lambda: None
            controller._database_descriptor_registry = SimpleNamespace(
                register_all=lambda _descriptors: None
            )
            controller._file_state_model = SimpleNamespace(
                file_entries=[access_entry, sql_entry]
            )
            controller._load_files_from_config_use_case = _LoadConfigured()
            services = {
                "database_capability_service": SimpleNamespace(
                    mark_connected=connected.append
                ),
                "sql_collaboration_coordinator": SimpleNamespace(
                    start_database=lambda database_id, **kwargs: starts.append(
                        (database_id, kwargs, threading.get_ident())
                    )
                ),
            }
            controller.container = SimpleNamespace(get=services.__getitem__)
            main_thread = threading.get_ident()
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])
        self.assertEqual(execute_calls, [({DatabaseBackend.ACCESS}, main_thread)])
        self.assertEqual(connected, [access_entry.database_id])
        self.assertEqual(
            starts,
            [
                (
                    sql_descriptor.database_id,
                    {"retry_initial_failure": False},
                    main_thread,
                )
            ],
        )

    def test_sql_only_startup_starts_in_background_and_reports_no_loaded_file(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        starts = []

        class _LoadConfigured:
            def execute(self, backends):
                self.assertEqual(backends, {DatabaseBackend.ACCESS})
                return []

        load_configured = _LoadConfigured()
        load_configured.assertEqual = self.assertEqual
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.sql_only")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = SimpleNamespace(
            register_all=lambda _descriptors: None
        )
        controller._file_state_model = SimpleNamespace(file_entries=[entry])
        controller._load_files_from_config_use_case = load_configured
        controller.container = SimpleNamespace(
            get=lambda _name: SimpleNamespace(
                start_database=lambda database_id, **kwargs: starts.append(
                    (database_id, kwargs)
                )
            )
        )
        self.assertEqual(AppController.load_files_from_config(controller), [])
        self.assertEqual(
            starts,
            [(descriptor.database_id, {"retry_initial_failure": False})],
        )
        self.assertTrue(AppController.has_any_databases(controller))

    def test_sql_start_scheduling_failure_still_returns_loaded_access(self):
        access_entry = FileEntry("C:/projects/active.mdb", is_checked=True)
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        sql_entry = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.schedule_failure")
        controller._auto_discover_databases = lambda: None
        controller._database_descriptor_registry = SimpleNamespace(
            register_all=lambda _descriptors: None
        )
        controller._file_state_model = SimpleNamespace(
            file_entries=[access_entry, sql_entry]
        )
        controller._load_files_from_config_use_case = SimpleNamespace(
            execute=lambda _backends: [access_entry.runtime_locator]
        )

        def fail_start(_database_id, **_kwargs):
            raise RuntimeError("worker could not be scheduled")

        services = {
            "database_capability_service": SimpleNamespace(
                mark_connected=lambda _database_id: None,
                mark_disconnected=lambda _database_id: None,
            ),
            "sql_collaboration_coordinator": SimpleNamespace(start_database=fail_start),
        }
        controller.container = SimpleNamespace(get=services.__getitem__)
        with self.assertLogs(controller.logger, level="ERROR"):
            loaded = AppController.load_files_from_config(controller)
        self.assertEqual(loaded, [access_entry.runtime_locator])

    def test_unloading_inactive_database_preserves_active_visualization(self):
        closed_visualizations = []
        published = []
        active_access = "C:/projects/active.mdb"
        inactive_sql = "sql-database-id"
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.inactive_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda file_path: SimpleNamespace(
                success=file_path == inactive_sql,
                error_message="",
            )
        )
        controller.orchestrators = SimpleNamespace(
            visualization=SimpleNamespace(
                close_realtime_visualization=lambda: closed_visualizations.append(True)
            )
        )
        controller.event_bus = SimpleNamespace(
            publish=lambda event, **payload: published.append((event, payload))
        )
        self.assertTrue(AppController.unload_file(controller, inactive_sql))
        self.assertEqual(closed_visualizations, [])
        self.assertEqual(len(published), 1)
        self.assertFalse(published[0][1]["active_context_removed"])

    def test_failed_active_database_unload_preserves_active_visualization(self):
        closed_visualizations = []
        active_access = "C:/projects/active.mdb"
        controller = AppController.__new__(AppController)
        controller.logger = logging.getLogger("test.startup.failed_active_unload")
        controller._project_data_service = SimpleNamespace(
            get_current_file_path=lambda: active_access,
            get_current_bid_file_path=lambda: active_access,
        )
        controller._file_loading_service = SimpleNamespace(
            unload_file=lambda _file_path: SimpleNamespace(
                success=False,
                error_message="database is busy",
            )
        )
        controller.orchestrators = SimpleNamespace(
            visualization=SimpleNamespace(
                close_realtime_visualization=lambda: closed_visualizations.append(True)
            )
        )
        controller.event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        with self.assertLogs(controller.logger, level="ERROR"):
            self.assertFalse(AppController.unload_file(controller, active_access))
        self.assertEqual(closed_visualizations, [])

    def test_unchecking_unavailable_sql_does_not_require_repository_unload(self):
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
        unchecked = original.with_checked(False)
        stopped = []
        cancelled = []

        class _State:
            file_entries = [original]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda _locator: self.fail(
                "An unavailable SQL database must not be unloaded from the repository"
            ),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: self.fail(
                    "Offline SQL uncheck must abandon deferred writes without flushing"
                ),
                cancel_for_file=cancelled.append,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda database_id, reason="closed", callback=None: stopped.append(
                    (database_id, reason)
                )
            ),
            database_capability_service=SimpleNamespace(
                mark_disconnected=lambda _database_id: None
            ),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertEqual(state.file_entries, [unchecked])
        self.assertEqual(stopped, [(sql_descriptor.database_id, "unchecked")])
        self.assertEqual(cancelled, [sql_descriptor.database_id])

    def test_open_files_uncheck_of_loaded_sql_waits_for_critical_drain(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="LOADED_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)
        unchecked = original.with_checked(False)
        flushed = []
        cancelled = []
        unloads = []
        drain_callbacks = []

        class _State:
            file_entries = [original]

            def reload(self):
                return None

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(
                is_loaded=lambda locator: locator == descriptor.database_id
            ),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloads.append(locator) or True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda locator: flushed.append(locator) or True,
                cancel_for_file=cancelled.append,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda database_id, callback: (
                    drain_callbacks.append((database_id, callback))
                )
            ),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertEqual(flushed, [descriptor.database_id])
        self.assertEqual(unloads, [])
        self.assertEqual(len(drain_callbacks), 1)
        drain_callbacks[0][1](True, "")
        self.assertEqual(unloads, [descriptor.database_id])
        self.assertEqual(cancelled, [descriptor.database_id])

    def test_explicit_unload_of_offline_sql_detaches_local_state(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OFFLINE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)

        class _State:
            file_entries = [original]

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()
        cancelled = []
        stopped = []
        disconnected = []
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda _locator: self.fail(
                "Offline SQL detach must not call repository unload"
            ),
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: self.fail(
                    "Offline SQL detach must not flush deferred writes"
                ),
                cancel_for_file=cancelled.append,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda database_id, reason: stopped.append(
                    (database_id, reason)
                )
            ),
            ui_state_manager=SimpleNamespace(selected_file_path=descriptor.database_id),
            database_capability_service=SimpleNamespace(
                mark_disconnected=disconnected.append
            ),
        )
        handler.unload_file()
        self.assertEqual(state.file_entries, [original.with_checked(False)])
        self.assertEqual(cancelled, [descriptor.database_id])
        self.assertEqual(stopped, [(descriptor.database_id, "unchecked")])
        self.assertEqual(disconnected, [descriptor.database_id])

    def test_sql_unload_state_save_failure_preserves_writes_and_runtime(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="SQL_STATE_FAIL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)
        cancelled = []
        stopped = []
        unloaded = []
        flushed = []
        drains = []

        class _State:
            file_entries = [original]

            def update_entries(self, _entries):
                raise OSError("disk unavailable")

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: True),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloaded.append(locator) or True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda locator: flushed.append(locator) or True,
                cancel_for_file=cancelled.append,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda database_id, callback: (
                    drains.append(database_id),
                    callback(True, ""),
                ),
                stop_database_async=lambda database_id, reason: stopped.append(
                    (database_id, reason)
                ),
            ),
            ui_state_manager=SimpleNamespace(selected_file_path=descriptor.database_id),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
        self.assertEqual(cancelled, [])
        self.assertEqual(stopped, [])
        self.assertEqual(unloaded, [])
        self.assertEqual(flushed, [descriptor.database_id])
        self.assertEqual(drains, [descriptor.database_id])
        self.assertTrue(_State.file_entries[0].is_checked)
        warning.assert_called_once()

    def test_loaded_sql_unload_failure_preserves_deferred_writes(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="SQL_LOCAL_FAIL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)
        cancelled = []

        class _State:
            file_entries = [original]

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()
        flushed = []
        drains = []
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: True),
            working_directory_service=None,
            unload_file_fn=lambda _locator: False,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda locator: flushed.append(locator) or True,
                cancel_for_file=cancelled.append,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda database_id, callback: (
                    drains.append(database_id),
                    callback(True, ""),
                )
            ),
            ui_state_manager=SimpleNamespace(selected_file_path=descriptor.database_id),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ):
            handler.unload_file()
        self.assertEqual(state.file_entries, [original])
        self.assertEqual(cancelled, [])
        self.assertEqual(flushed, [descriptor.database_id])
        self.assertEqual(drains, [descriptor.database_id])

    def test_open_files_save_failure_does_not_unload_the_active_database(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)
        unchecked = original.with_checked(False)
        unloads = []
        credential_commits = []

        class _State:
            file_entries = [original]

            def reload(self):
                pass

            def update_entries(self, _entries):
                raise OSError("disk unavailable")

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                credential_commits.append(True)
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloads.append(locator) or True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
                _Dialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            handler.open_files()
        self.assertEqual(unloads, [])
        self.assertEqual(credential_commits, [])
        self.assertEqual(handler._file_state_model.file_entries, [original])
        warning.assert_called_once()
        self.assertIn("could not be saved", warning.call_args.args[2])

    def test_open_files_credential_commit_failure_restores_saved_selection(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)
        unchecked = original.with_checked(False)
        unloads = []

        class _State:
            file_entries = [original]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                raise OSError("credential store unavailable")

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloads.append(locator) or True,
            deferred_persistence_manager=SimpleNamespace(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
                _Dialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            handler.open_files()
        self.assertEqual(state.file_entries, [original])
        self.assertEqual(unloads, [])
        warning.assert_called_once()
        self.assertIn("credentials", warning.call_args.args[2])

    def test_failed_load_checkbox_rollback_save_failure_is_contained(self):
        checked = FileEntry("C:/projects/unavailable.mdb", is_checked=True)

        class _State:
            file_entries = []

            def __init__(self):
                self.update_count = 0

            def reload(self):
                pass

            def update_entries(self, entries):
                self.update_count += 1
                if self.update_count == 2:
                    raise OSError("disk unavailable")
                self.file_entries = list(entries)

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [checked]

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(
                load_file=lambda _locator: SimpleNamespace(
                    success=False,
                    error_message="unavailable",
                )
            ),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler."
                "OpenFilesDialog",
                _Dialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler."
                "show_warning"
            ) as warning,
        ):
            handler.open_files()
        self.assertEqual(state.file_entries, [checked])
        self.assertEqual(warning.call_count, 2)
        self.assertIn("checked state could not be cleared", warning.call_args.args[2])

    def test_saved_sql_checkbox_remains_enabled_and_interactive(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        dialog = OpenFilesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            None,
            [FileEntry.for_descriptor(descriptor, is_checked=True)],
            None,
        )
        try:
            checkbox = dialog._checkboxes[0]
            self.assertTrue(checkbox.isEnabled())
            checkbox.click()
            self.assertFalse(dialog.get_file_entries()[0].is_checked)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_sql_retry_uses_coordinator_without_loading_on_qt_thread(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        restarts = []
        active_access = ["C:/projects/active.mdb"]

        def stop_database(database_id, reason, callback):
            restarts.append(("stop", database_id, reason, threading.get_ident()))
            callback(True, "")

        handler = FileOperationHandler.__new__(FileOperationHandler)
        handler.window = None
        handler._file_state_model = SimpleNamespace(file_entries=[entry])
        handler.event_bus = SimpleNamespace(publish=lambda *_args, **_kwargs: None)
        handler._file_loading_service = SimpleNamespace(
            is_loaded=lambda _locator: False,
            load_file=lambda _locator: self.fail(
                "SQL retry must not use the synchronous UI-thread loader"
            ),
        )
        handler._database_capability_service = SimpleNamespace(
            mark_disconnected=lambda _database_id: None
        )
        handler._sql_collaboration = SimpleNamespace(
            stop_database_async=stop_database,
            start_database=lambda database_id: restarts.append(
                ("start", database_id, threading.get_ident())
            ),
        )
        loaded = handler._load_specific_entries([entry])
        self.assertEqual(loaded, {descriptor.database_id})
        self.assertEqual(active_access, ["C:/projects/active.mdb"])
        self.assertEqual(
            [call[:2] for call in restarts],
            [
                ("stop", descriptor.database_id),
                ("start", descriptor.database_id),
            ],
        )

    def test_rechecking_sql_persists_checked_state_before_immediate_restart(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        unchecked = FileEntry.for_descriptor(descriptor, is_checked=False)
        checked = unchecked.with_checked(True)
        starts = []

        class _State:
            file_entries = [unchecked]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            def __init__(self, *_args, **_kwargs):
                pass

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [checked]

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda _database_id, _reason, callback: callback(
                    True, ""
                ),
                start_database=starts.append,
            ),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertEqual(state.file_entries, [checked])
        self.assertEqual(starts, [descriptor.database_id])

    def test_stale_sql_restart_callback_does_not_revive_removed_database(self):
        starts = []
        handler = FileOperationHandler.__new__(FileOperationHandler)
        handler._file_state_model = SimpleNamespace(file_entries=[])
        handler._sql_collaboration = SimpleNamespace(start_database=starts.append)
        handler._complete_sql_connection_restart(
            "removed-sql-database",
            True,
            "",
        )
        self.assertEqual(starts, [])

    def test_stale_sql_restart_failure_does_not_warn_after_removal(self):
        handler = FileOperationHandler.__new__(FileOperationHandler)
        handler.window = None
        handler._file_state_model = SimpleNamespace(file_entries=[])
        handler._sql_collaboration = SimpleNamespace(
            start_database=lambda _database_id: None
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler._complete_sql_connection_restart(
                "removed-sql-database",
                False,
                "old drain failed",
            )
        warning.assert_not_called()

    def test_completed_removal_drain_does_not_start_readded_unchecked_sql(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        starts = []
        handler = FileOperationHandler.__new__(FileOperationHandler)
        handler._file_state_model = SimpleNamespace(
            file_entries=[entry.with_checked(False)]
        )
        handler._sql_collaboration = SimpleNamespace(start_database=starts.append)
        handler._database_descriptor_registry = None
        handler._credential_store = None
        handler._database_capability_service = None
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(starts, [])


if __name__ == "__main__":
    unittest.main()
