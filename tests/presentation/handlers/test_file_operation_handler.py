from tests.presentation.managers.deferred_persistence_support import (
    RecordingDeferredPersistence,
    WorkspaceFileOperationHandler,
)
from ost_visualizer.presentation.main_window import MainWindow
from ost_visualizer.domain.entities.file_state import FileEntry
from unittest.mock import patch
from types import SimpleNamespace
import unittest
import os
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtWidgets
from tests.helpers.sql.cleanup_support import (
    FileOperationHandler as _cleanup_support_FileOperationHandler,
    _CredentialStore as _cleanup_support__CredentialStore,
)
import secrets
from ost_visualizer.application.interfaces.i_database_catalog import (
    DatabaseCatalogError,
    SqlDatabaseCatalogEntry,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.schema_definition import (
    SQL_SCHEMA_V1,
    schema_record_is_canonical,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import with_workspace_state
from tests.helpers.sql.database_foundation_support import (
    FileOperationHandler as _database_foundation_support_FileOperationHandler,
    _Catalog as _database_foundation_support__Catalog,
    _CredentialStore as _database_foundation_support__CredentialStore,
    _IconProvider as _database_foundation_support__IconProvider,
    _SqlDatabaseCreator as _database_foundation_support__SqlDatabaseCreator,
    _app as _database_foundation_support__app,
)
from dataclasses import replace
from unittest.mock import Mock, patch
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
)
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _GUID as _creation_handoff_support__GUID,
)
from ost_visualizer.domain.aggregates.file_state_aggregate import FileStateAggregate
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    validate_sql_database_creation_name,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT,
    _CREATOR,
    _GUID,
    _RUNTIME,
    _Connections,
    _error,
    _snapshot,
)
from tests.helpers.sql.creation_release_readiness_support import (
    _ImmediateProgress as _creation_release_readiness_support__ImmediateProgress,
)
import json
import tempfile
from pathlib import Path
from ost_visualizer.infrastructure.persistence.repositories.json_file_state_repository import (
    JsonFileStateRepository,
)
from unittest import mock
from ost_visualizer.domain.aggregates.workspace_state_aggregate import (
    WorkspaceStateAggregate,
)
from ost_visualizer.infrastructure.persistence.repositories.json_workspace_state_repository import (
    JsonWorkspaceStateRepository,
)
from tests.presentation.utils.header_support import (
    _IconProvider as _header_support__IconProvider,
    _app as _header_support__app,
)
import threading
from unittest.mock import create_autospec
from ost_visualizer.application.interfaces.i_credential_store import ICredentialStore
from ost_visualizer.application.interfaces.i_database_catalog import IDatabaseCatalog
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    ISqlDatabaseCreator,
)
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler as StartupFileOperationHandler,
)
from shiboken6 import delete, isValid
from tests.helpers.startup_database import (
    StartupFileOperationHandler as _startup_database_StartupFileOperationHandler,
    _OpenFilesDialogStub as _startup_database__OpenFilesDialogStub,
)
import inspect
from ost_visualizer.application.dtos.file_dto import FileLoadResultDto
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.application.services.file_loading_service import FileLoadingService
from ost_visualizer.presentation.managers.ui_access_manager import Feature
from ost_visualizer.application.interfaces.i_database_maintenance import (
    DatabaseMaintenanceResult,
)
from ost_visualizer.application.interfaces.i_window_icon_provider import (
    IWindowIconProvider,
)
from ost_visualizer.application.services.database_maintenance_service import (
    DatabaseMaintenanceService,
)
from ost_visualizer.infrastructure.events.event_bus import EventBus
from ost_visualizer.presentation.managers.deferred_persistence_manager import (
    DeferredPersistenceManager,
)
from ost_visualizer.presentation.managers.ui_access_manager import UIAccessManager
from tests.helpers.workspace_state import make_workspace_state_model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FileOperationDeferredUnloadTests(unittest.TestCase):
    def setUp(self):
        # These partial MainWindow fixtures do not construct detached managers.
        for name, result in (("_detached_plan_windows", ()), ("get_mesh_window", None)):
            patcher = patch.object(MainWindow, name, return_value=result)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_project_unload_flushes_pending_writes_before_unload(self):
        deferred = RecordingDeferredPersistence()
        events = []
        unload_calls = []
        updates = []
        entries = [FileEntry("a.mdb", is_checked=True)]
        original_flush = deferred.flush_for_file
        original_cancel = deferred.cancel_for_file

        def flush_for_file(path):
            events.append("flush")
            return original_flush(path)

        def cancel_for_file(path):
            events.append("cancel")
            original_cancel(path)

        def update_entries(next_entries):
            events.append("save")
            updates.append(next_entries)

        def unload_file(file_path):
            events.append("unload")
            unload_calls.append(file_path)
            return True

        deferred.flush_for_file = flush_for_file
        deferred.cancel_for_file = cancel_for_file
        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=entries,
                update_entries=update_entries,
            ),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=unload_file,
            deferred_persistence_manager=deferred,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, ["a.mdb"])
        self.assertEqual(deferred.cancel_calls, ["a.mdb"])
        self.assertEqual(events, ["flush", "save", "unload", "cancel"])
        self.assertEqual(len(updates), 1)
        self.assertEqual(
            [(entry.database_id, entry.is_checked) for entry in updates[0]],
            [(entries[0].database_id, False)],
        )

    def test_project_unload_stops_when_deferred_flush_fails(self):
        deferred = RecordingDeferredPersistence()
        deferred.flush_result = False
        unload_calls = []
        updates = []
        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=[FileEntry("a.mdb", is_checked=True)],
                update_entries=updates.append,
            ),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda file_path: unload_calls.append(file_path) or True,
            deferred_persistence_manager=deferred,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, [])
        self.assertEqual(updates, [])
        self.assertEqual(deferred.cancel_calls, [])
        warning.assert_not_called()

    def test_project_unload_stops_when_open_files_state_cannot_be_saved(self):
        deferred = RecordingDeferredPersistence()
        unload_calls = []

        class _FailingState:
            file_entries = [FileEntry("a.mdb", is_checked=True)]

            def update_entries(self, _entries):
                raise OSError("disk unavailable")

        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=_FailingState(),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda file_path: unload_calls.append(file_path) or True,
            deferred_persistence_manager=deferred,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(deferred.cancel_calls, [])
        self.assertEqual(unload_calls, [])
        self.assertTrue(_FailingState.file_entries[0].is_checked)
        warning.assert_called_once_with(
            None,
            "Unload File",
            "The Open Files state could not be saved, so the database was not "
            "unloaded.",
        )

    def test_failed_project_unload_restores_saved_open_files_state(self):
        deferred = RecordingDeferredPersistence()
        state = SimpleNamespace(file_entries=[FileEntry("a.mdb", is_checked=True)])
        updates = []

        def update_entries(entries):
            state.file_entries = list(entries)
            updates.append(list(entries))

        state.update_entries = update_entries
        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda _file_path: False,
            deferred_persistence_manager=deferred,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
        self.assertEqual(len(updates), 2)
        self.assertFalse(updates[0][0].is_checked)
        self.assertTrue(updates[1][0].is_checked)
        self.assertTrue(state.file_entries[0].is_checked)
        self.assertEqual(deferred.cancel_calls, [])
        warning.assert_called_once_with(
            None, "No File Loaded", "There is no file currently loaded."
        )

    def test_failed_project_unload_reports_when_saved_state_cannot_be_restored(self):
        deferred = RecordingDeferredPersistence()
        saves = []

        class _State:
            file_entries = [FileEntry("a.mdb", is_checked=True)]

            def update_entries(self, entries):
                saves.append([entry.is_checked for entry in entries])
                if len(saves) == 2:
                    raise OSError("disk unavailable")

        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=_State(),
            cleanup_deleted_files_use_case=None,
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda _file_path: False,
            deferred_persistence_manager=deferred,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
            ui_state_manager=SimpleNamespace(selected_file_path="a.mdb"),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
        self.assertEqual(saves, [[False], [True]])
        self.assertEqual(deferred.cancel_calls, [])
        warning.assert_called_once_with(
            None,
            "Unload File",
            "The database could not be unloaded and its saved Open Files state "
            "could not be restored.",
        )


class FileOperationHandlerSqlCleanupTests(unittest.TestCase):
    def test_offline_removed_sql_does_not_require_repository_unload(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor)
        updates = []
        state = type(
            "State",
            (),
            {
                "file_entries": [entry],
                "reload": lambda self: None,
                "update_entries": lambda self, entries: updates.append(list(entries)),
            },
        )()

        class _Dialog:
            maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                _icon_provider,
                _parent,
                _file_entries,
                _working_directory_service,
                workspace_state_model,
                sql_catalog=None,
                credential_store=None,
                sql_database_creator=None,
                schema_change_allowed_fn=None,
                maintenance_allowed_fn=None,
            ):
                _ = (
                    workspace_state_model,
                    sql_catalog,
                    credential_store,
                    sql_database_creator,
                    schema_change_allowed_fn,
                    maintenance_allowed_fn,
                )

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return []

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        stops = []
        unloads = []
        handler = _cleanup_support_FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=type(
                "Cleanup", (), {"execute_and_save": lambda self: 0}
            )(),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloads.append(locator) or False,
            deferred_persistence_manager=type(
                "Deferred",
                (),
                {
                    "flush_for_file": lambda self, _locator: True,
                    "cancel_for_file": lambda self, _locator: None,
                },
            )(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda database_id, reason, callback=None: stops.append(
                    (database_id, reason, callback)
                )
            ),
            credential_store=_cleanup_support__CredentialStore(),
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler."
                "OpenFilesDialog",
                _Dialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ),
        ):
            handler.open_files()
        self.assertEqual(updates, [[]])
        self.assertEqual(unloads, [])
        self.assertEqual(
            [(database_id, reason) for database_id, reason, _callback in stops],
            [(descriptor.database_id, "connection-removed")],
        )

    def test_removed_sql_descriptor_waits_for_collaboration_drain(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _cleanup_support__CredentialStore()
        callbacks = []

        class _State:
            file_entries = [entry]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                _icon_provider,
                _parent,
                _file_entries,
                _working_directory_service,
                workspace_state_model,
                sql_catalog=None,
                credential_store=None,
                sql_database_creator=None,
                schema_change_allowed_fn=None,
                maintenance_allowed_fn=None,
            ):
                _ = (
                    workspace_state_model,
                    sql_catalog,
                    credential_store,
                    sql_database_creator,
                    schema_change_allowed_fn,
                    maintenance_allowed_fn,
                )

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return []

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = _cleanup_support_FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: True),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda _database_id, callback: callback(
                    True, ""
                ),
                stop_database_async=lambda _database_id, _reason, callback: callbacks.append(
                    callback
                ),
            ),
            credential_store=credentials,
            database_descriptor_registry=registry,
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        self.assertEqual(credentials.deleted, [])
        self.assertEqual(handler._file_state_model.file_entries, [])
        self.assertEqual(len(callbacks), 1)
        callbacks[0](True, "")
        self.assertIsNone(registry.resolve(descriptor.database_id))
        self.assertEqual(
            credentials.deleted,
            [credential_target_for(descriptor.database_id)],
        )

    def test_completed_old_drain_does_not_remove_readded_sql_descriptor(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _cleanup_support__CredentialStore()
        callbacks = []
        starts = []

        class _State:
            file_entries = [entry]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                _icon_provider,
                _parent,
                _file_entries,
                _working_directory_service,
                workspace_state_model,
                sql_catalog=None,
                credential_store=None,
                sql_database_creator=None,
                schema_change_allowed_fn=None,
                maintenance_allowed_fn=None,
            ):
                _ = (
                    workspace_state_model,
                    sql_catalog,
                    credential_store,
                    sql_database_creator,
                    schema_change_allowed_fn,
                    maintenance_allowed_fn,
                )

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return []

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        handler = _cleanup_support_FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: True),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda _database_id, callback: callback(
                    True, ""
                ),
                stop_database_async=lambda _database_id, _reason, callback: callbacks.append(
                    callback
                ),
                start_database=lambda database_id: starts.append(database_id),
            ),
            credential_store=credentials,
            database_descriptor_registry=registry,
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        state.file_entries = [entry]
        registry.register(descriptor)
        callbacks[0](True, "")
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        self.assertEqual(credentials.deleted, [])
        self.assertEqual(starts, [descriptor.database_id])

    def test_offline_sql_drain_still_removes_descriptor_and_credential(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _cleanup_support__CredentialStore()

        class _State:
            file_entries = []

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()
        handler = _cleanup_support_FileOperationHandler.__new__(
            _cleanup_support_FileOperationHandler
        )
        handler.window = None
        handler._file_state_model = state
        handler._database_descriptor_registry = registry
        handler._credential_store = credentials
        handler._sql_collaboration = SimpleNamespace(start_database=lambda _id: None)
        disconnected = []
        handler._database_capability_service = SimpleNamespace(
            mark_disconnected=disconnected.append
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler._complete_sql_connection_removal(
                entry, False, "session cleanup failed"
            )
        self.assertIsNone(registry.resolve(descriptor.database_id))
        self.assertEqual(
            credentials.deleted, [credential_target_for(descriptor.database_id)]
        )
        self.assertEqual(state.file_entries, [])
        self.assertEqual(disconnected, [descriptor.database_id])
        warning.assert_not_called()

    def test_retained_sql_descriptor_reconnects_through_coordinator(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor)

        class _State:
            file_entries = [entry]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog:
            maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                _icon_provider,
                _parent,
                _file_entries,
                _working_directory_service,
                workspace_state_model,
                sql_catalog=None,
                credential_store=None,
                sql_database_creator=None,
                schema_change_allowed_fn=None,
                maintenance_allowed_fn=None,
            ):
                _ = (
                    workspace_state_model,
                    sql_catalog,
                    credential_store,
                    sql_database_creator,
                    schema_change_allowed_fn,
                    maintenance_allowed_fn,
                )

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                return [entry]

            def commit_credential_changes(self):
                return {entry.database_id}

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        connected = []
        published = []
        stop_callbacks = []
        starts = []

        def mark_connected(database_id):
            connected.append(database_id)

        handler = _cleanup_support_FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(
                publish=lambda event, **kwargs: published.append((event, kwargs))
            ),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda database_id, reason, callback: stop_callbacks.append(
                    (database_id, reason, callback)
                ),
                start_database=lambda database_id: starts.append(database_id),
            ),
            database_capability_service=SimpleNamespace(
                is_editable=lambda _database_id: False,
                mark_connected=mark_connected,
            ),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertEqual(connected, [])
        self.assertEqual(published, [])
        self.assertEqual(len(stop_callbacks), 1)
        database_id, reason, callback = stop_callbacks[0]
        self.assertEqual(database_id, entry.database_id)
        self.assertEqual(reason, "reconfigured")
        callback(True, "")
        self.assertEqual(starts, [entry.database_id])

    def test_sql_connection_restarts_only_for_changed_descriptor(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        changed_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(
                server="localhost", database="OSTV_TEST", command_timeout_seconds=45
            ),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor)
        self.assertEqual(descriptor.database_id, changed_descriptor.database_id)
        for label, selected, expected_restarts in (
            ("unchanged", original, []),
            (
                "changed descriptor",
                FileEntry.for_descriptor(changed_descriptor),
                [(descriptor.database_id, "reconfigured")],
            ),
        ):
            with self.subTest(label):
                stops = []
                starts = []

                class _State:
                    file_entries = [original]

                    def reload(self):
                        pass

                    def update_entries(self, entries):
                        self.file_entries = list(entries)

                class _Dialog(_startup_database__OpenFilesDialogStub):
                    def get_file_entries(self):
                        return [selected]

                    def commit_credential_changes(self):
                        return set()

                handler = _startup_database_StartupFileOperationHandler(
                    window=None,
                    icon_provider=None,
                    event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
                    file_state_model=_State(),
                    cleanup_deleted_files_use_case=SimpleNamespace(
                        execute_and_save=lambda: None
                    ),
                    file_loading_service=SimpleNamespace(
                        is_loaded=lambda _locator: False
                    ),
                    working_directory_service=None,
                    unload_file_fn=lambda _locator: self.fail("no unload expected"),
                    deferred_persistence_manager=SimpleNamespace(),
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                    sql_collaboration_coordinator=SimpleNamespace(
                        stop_database_async=lambda database_id, reason, callback: (
                            stops.append((database_id, reason)),
                            callback(True, ""),
                        ),
                        start_database=starts.append,
                    ),
                )
                with patch(
                    "ost_visualizer.presentation.handlers.file_operation_handler."
                    "OpenFilesDialog",
                    _Dialog,
                ):
                    handler.open_files()
                self.assertEqual(stops, expected_restarts)
                self.assertEqual(
                    starts, [descriptor.database_id for _restart in expected_restarts]
                )
                self.assertEqual(handler._file_state_model.file_entries, [selected])


class FileOperationHandlerSqlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _database_foundation_support__app()
        cls.icon_provider = _database_foundation_support__IconProvider()

    def test_sql_creation_persists_only_after_properties_acceptance(self):
        password = secrets.token_urlsafe(24)
        location = SqlServerDatabaseLocation(
            server="localhost",
            database="OSTV_TEST_CREATED",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="test-user",
            database_guid="00000000-0000-0000-0000-000000000456",
        )
        properties_result = SqlDatabasePropertiesResult(
            location, SQL_SCHEMA_V1.version, password
        )

        class _State:
            def __init__(self):
                self.file_entries = []

            def update_entries(self, entries):
                self.file_entries = list(entries)

            def reload(self):
                pass

        class _PropertiesDialog:
            accepted = True

            def __init__(
                self,
                _icon_provider,
                _mode,
                _sql_catalog,
                _sql_database_creator,
                _parent=None,
                *,
                connection=None,
                databases=(),
                schema_change_allowed_fn=None,
            ):
                _ = connection, databases, schema_change_allowed_fn

            def exec(self):
                if self.accepted:
                    return QtWidgets.QDialog.DialogCode.Accepted
                return QtWidgets.QDialog.DialogCode.Rejected

            def result_data(self):
                return properties_result if self.accepted else None

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        state = _State()
        store = _database_foundation_support__CredentialStore()
        handler = _database_foundation_support_FileOperationHandler(
            window=None,
            icon_provider=self.icon_provider,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=None,
            file_loading_service=SimpleNamespace(
                is_loaded=lambda _locator: False,
                load_file=lambda _locator: SimpleNamespace(
                    success=True, file_path=location.database_guid
                ),
            ),
            working_directory_service=None,
            unload_file_fn=lambda _locator: False,
            deferred_persistence_manager=None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda _database_id, _reason, callback: callback(
                    True, ""
                ),
                start_database=lambda _database_id, **kwargs: (
                    kwargs["on_initial_open"](True, "") or True
                ),
            ),
            database_catalog=_database_foundation_support__Catalog([]),
            credential_store=store,
            database_descriptor_registry=DatabaseDescriptorRegistry(),
            sql_database_creator=_database_foundation_support__SqlDatabaseCreator(),
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler."
                "SqlDatabasePropertiesDialog",
                _PropertiesDialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            self.assertTrue(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            self.assertTrue(state.file_entries[0].is_checked)
            target = credential_target_for(state.file_entries[0].database_id)
            self.assertEqual(store.passwords[target], ("test-user", password))
            warning.assert_not_called()
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            warning.assert_called_once_with(
                None,
                "SQL Server",
                "This SQL Server database is already in Open Files.",
            )
            _PropertiesDialog.accepted = False
            empty_state = _State()
            handler._file_state_model = empty_state
            store.passwords.clear()
            warning.reset_mock()
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(empty_state.file_entries, [])
            self.assertEqual(store.passwords, {})
            warning.assert_not_called()
            self.assertFalse(handler.sql_creation_pending)


class FileOperationHandlerCreationDialogIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_creation_opens_properties_directly_and_cancel_has_no_side_effects(self):
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler.icon_provider = Mock()
        handler._ui_access_manager = Mock()
        handler._ui_access_manager.is_allowed.return_value = True
        handler._database_catalog = create_autospec(IDatabaseCatalog, instance=True)
        handler._credential_store = create_autospec(ICredentialStore, instance=True)
        handler._sql_database_creator = create_autospec(
            ISqlDatabaseCreator, instance=True
        )
        properties_dialog = Mock()
        properties_dialog.exec.return_value = QtWidgets.QDialog.DialogCode.Rejected
        with (
            patch(
                "ost_visualizer.presentation.dialogs.sql_database_dialog.SqlConnectionDialog"
            ) as connection_factory,
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                return_value=properties_dialog,
            ) as properties_factory,
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            self.assertIs(handler._create_sql_database(), False)
        warning.assert_not_called()
        connection_factory.assert_not_called()
        properties_factory.assert_called_once()
        self.assertEqual(
            properties_factory.call_args.args[1], SqlDatabasePropertiesMode.CREATE
        )
        self.assertNotIn("connection", properties_factory.call_args.kwargs)
        properties_dialog.exec.assert_called_once()
        properties_dialog.cleanup.assert_called_once()
        properties_dialog.deleteLater.assert_called_once()
        properties_dialog.result_data.assert_not_called()
        handler._sql_database_creator.create_database_for_client.assert_not_called()
        handler._sql_database_creator.create_database.assert_not_called()
        handler._credential_store.write_password.assert_not_called()
        handler._credential_store.delete_password.assert_not_called()

    def test_creation_marks_file_operation_pending_only_while_it_runs(self):
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler._file_operation_pending = False
        handler._file_operation_serial = 0
        handler._sql_creation_active = False
        observed = []

        def create():
            observed.append(
                (handler.sql_creation_pending, handler._file_operation_pending)
            )
            return False

        handler._create_sql_database = create
        self.assertFalse(handler.create_sql_database())
        self.assertEqual(observed, [(True, True)])
        self.assertEqual(
            (handler.sql_creation_pending, handler._file_operation_pending),
            (False, False),
        )

        def failing_create():
            raise RuntimeError("dialog failed")

        handler._create_sql_database = failing_create
        with self.assertRaises(RuntimeError):
            handler.create_sql_database()
        self.assertEqual(
            (handler.sql_creation_pending, handler._file_operation_pending),
            (False, False),
        )

    def test_creation_is_refused_while_another_file_operation_is_pending(self):
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler._file_operation_pending = True
        handler._file_operation_serial = 4
        handler._sql_creation_active = False
        handler._create_sql_database = lambda: self.fail("creation must not start")
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            self.assertIs(handler.create_sql_database(), False)
        warning.assert_called_once_with(
            None,
            "Database Operation Pending",
            "Wait for the current database operation to finish before changing "
            "Open Files again.",
        )
        self.assertTrue(handler._file_operation_pending)
        self.assertEqual(handler._file_operation_serial, 4)

    def test_created_database_waits_for_open_result_and_retains_connection_on_failure(
        self,
    ):
        entry = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                replace(
                    _creation_handoff_support__CREATOR,
                    database="Created",
                    database_guid=_creation_handoff_support__GUID,
                    username="client",
                ),
                schema_version=1,
            )
        )
        for ready in (True, False):
            handler = object.__new__(FileOperationHandler)
            handler.window = None
            delivered = []

            def start(database_id, *, retry_initial_failure, on_initial_open):
                self.assertEqual(database_id, entry.database_id)
                self.assertFalse(retry_initial_failure)

                def deliver():
                    delivered.append(ready)
                    on_initial_open(
                        ready, "Connection interrupted" if not ready else ""
                    )

                QtCore.QTimer.singleShot(10, deliver)
                return True

            handler._sql_collaboration = SimpleNamespace(start_database=start)
            handler._file_state_model = SimpleNamespace(file_entries=[entry])
            with patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning:
                self.assertEqual(handler._open_created_sql_database(entry), ready)
            self.assertEqual(delivered, [ready])
            self.assertEqual(handler._file_state_model.file_entries, [entry])
            self.assertTrue(entry.is_checked)
            if not ready:
                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[1], "SQL database not ready")
                self.assertEqual(
                    warning.call_args.args[2],
                    _not_ready_message("Connection interrupted"),
                )
            else:
                warning.assert_not_called()


class FileOperationHandlerCreationReleaseBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _entry(self):
        return FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                replace(
                    _CREATOR,
                    username=_RUNTIME.username,
                    database="Created",
                    database_guid=_GUID,
                ),
                schema_version=1,
            )
        )

    def test_health_delivered_after_worker_timeout_before_gui_completion_wins(self):
        entry = self._entry()
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler._sql_collaboration = create_autospec(
            SqlCollaborationCoordinator, instance=True
        )
        callback = []

        def start(_database_id, **kwargs):
            callback.append(kwargs["on_initial_open"])
            return True

        handler._sql_collaboration.start_database.side_effect = start
        completed = Mock()
        completed.wait.return_value = False
        completed.is_set.side_effect = lambda: completed.set.called

        class _TimeoutThenHealthy(
            _creation_release_readiness_support__ImmediateProgress
        ):
            def exec(self):
                super().exec()
                callback[0](True, "")

        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.threading.Event",
                return_value=completed,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog",
                _TimeoutThenHealthy,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            self.assertTrue(handler._open_created_sql_database(entry))
        warning.assert_not_called()
        completed.wait.assert_called_once_with(75)
        handler._sql_collaboration.stop_database_async.assert_not_called()
        handler._sql_collaboration.start_database.assert_called_once()

    def test_open_timeout_retains_connection_and_late_callback_does_not_restart(self):
        entry = self._entry()
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler._sql_collaboration = create_autospec(
            SqlCollaborationCoordinator, instance=True
        )
        handler._file_state_model = SimpleNamespace(file_entries=[entry])
        callbacks = []
        handler._sql_collaboration.start_database.side_effect = lambda _id, **kwargs: (
            callbacks.append(kwargs["on_initial_open"]) or True
        )
        completed = Mock()
        completed.wait.return_value = False
        completed.is_set.return_value = False
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.threading.Event",
                return_value=completed,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog",
                _creation_release_readiness_support__ImmediateProgress,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            self.assertFalse(handler._open_created_sql_database(entry))
            warning.assert_called_once()
            self.assertEqual(warning.call_args.args[1], "SQL database not ready")
            self.assertEqual(
                warning.call_args.args[2],
                _not_ready_message(
                    "Opening has not completed within the waiting period."
                ),
            )
            callbacks[0](True, "")
            warning.assert_called_once()
        self.assertEqual(handler._file_state_model.file_entries, [entry])
        self.assertTrue(entry.is_checked)
        handler._sql_collaboration.start_database.assert_called_once_with(
            entry.database_id,
            retry_initial_failure=False,
            on_initial_open=callbacks[0],
        )
        handler._sql_collaboration.stop_database_async.assert_not_called()
        handler._sql_collaboration.drain_database_mutations_async.assert_not_called()

    def test_credential_and_state_save_failures_never_register_or_open(self):
        for boundary in ("credential", "state", "credential_cleanup"):
            with self.subTest(boundary=boundary):
                repository = Mock()
                repository.load.return_value = FileState()
                state = FileStateAggregate(repository)
                handler = object.__new__(FileOperationHandler)
                handler.window = None
                handler.icon_provider = Mock()
                handler._ui_access_manager = Mock()
                handler._ui_access_manager.is_allowed.return_value = True
                handler._database_catalog = create_autospec(
                    IDatabaseCatalog, instance=True
                )
                handler._sql_database_creator = create_autospec(
                    ISqlDatabaseCreator, instance=True
                )
                handler._credential_store = create_autospec(
                    ICredentialStore, instance=True
                )
                handler._file_state_model = state
                handler._database_descriptor_registry = DatabaseDescriptorRegistry()
                handler._open_created_sql_database = Mock()
                entry = self._entry()
                dialog = Mock()
                dialog.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
                dialog.result_data.return_value = SqlDatabasePropertiesResult(
                    entry.descriptor.sql_location, 1, _RUNTIME.password
                )
                if boundary == "credential":
                    handler._credential_store.write_password.side_effect = OSError(
                        "credential store unavailable"
                    )
                else:
                    repository.save.side_effect = OSError("state storage unavailable")
                if boundary == "credential_cleanup":
                    handler._credential_store.delete_password.side_effect = OSError(
                        "credential cleanup unavailable"
                    )
                with (
                    patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                        return_value=dialog,
                    ),
                    patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
                    ) as warning,
                ):
                    self.assertFalse(handler._create_sql_database())
                self.assertEqual(state.file_entries, [])
                self.assertIsNone(
                    handler._database_descriptor_registry.resolve(entry.database_id)
                )
                handler._open_created_sql_database.assert_not_called()
                self.assertEqual(
                    handler._credential_store.write_password.call_args.args[1:],
                    (_RUNTIME.username, _RUNTIME.password),
                )
                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[1], "SQL Server")
                expected = (
                    "The database was created, but its saved connection could not "
                    "be stored. The server database was not deleted."
                )
                if boundary == "credential_cleanup":
                    expected += (
                        " The temporary Windows credential could not be removed; "
                        "remove it through Windows Credential Manager."
                    )
                self.assertEqual(warning.call_args.args[2], expected)
                if boundary == "credential":
                    handler._credential_store.delete_password.assert_not_called()
                else:
                    handler._credential_store.delete_password.assert_called_once_with(
                        credential_target_for(entry.database_id)
                    )

    def test_retry_after_saved_open_failure_reuses_descriptor_and_drains_before_restart(
        self,
    ):
        entry = self._entry()
        handler = object.__new__(FileOperationHandler)
        handler.window = None
        handler.icon_provider = Mock()
        handler._ui_access_manager = Mock()
        handler._ui_access_manager.is_allowed.return_value = True
        handler._database_catalog = create_autospec(IDatabaseCatalog, instance=True)
        handler._sql_database_creator = create_autospec(
            ISqlDatabaseCreator, instance=True
        )
        handler._credential_store = create_autospec(ICredentialStore, instance=True)
        repository = Mock()
        repository.load.return_value = FileState()
        handler._file_state_model = FileStateAggregate(repository)
        handler._database_descriptor_registry = DatabaseDescriptorRegistry()
        handler._open_created_sql_database = Mock(return_value=False)
        dialog = Mock()
        dialog.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
        dialog.result_data.return_value = SqlDatabasePropertiesResult(
            entry.descriptor.sql_location, 1, _RUNTIME.password
        )
        with (
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                return_value=dialog,
            ),
            patch(
                "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
            ) as warning,
        ):
            self.assertFalse(handler._create_sql_database())
            warning.assert_not_called()
            self.assertFalse(handler._create_sql_database())
        warning.assert_called_once_with(
            None,
            "SQL Server",
            "This SQL Server database is already in Open Files.",
        )
        self.assertEqual(len(handler._file_state_model.file_entries), 1)
        repository.save.assert_called_once()
        handler._credential_store.write_password.assert_called_once()
        handler._open_created_sql_database.assert_called_once()
        self.assertEqual(
            handler._database_descriptor_registry.resolve(entry.database_id),
            entry.descriptor,
        )
        handler._file_loading_service = Mock()
        handler._file_loading_service.is_loaded.return_value = False
        handler._sql_collaboration = create_autospec(
            SqlCollaborationCoordinator, instance=True
        )
        stopped = []
        handler._sql_collaboration.stop_database_async.side_effect = (
            lambda _id, _reason, callback: stopped.append(callback)
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as restart_warning:
            handler._restart_sql_connection(entry.database_id)
            handler._sql_collaboration.start_database.assert_not_called()
            stopped[0](True, "")
        restart_warning.assert_not_called()
        handler._sql_collaboration.start_database.assert_called_once_with(
            entry.database_id
        )
        handler._credential_store.write_password.assert_called_once()


class OpenFilesWorkspaceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _header_support__app()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp_dir.name) / "workspace_state.json"
        self.model = WorkspaceStateAggregate(
            JsonWorkspaceStateRepository(self.state_path)
        )

    def tearDown(self):
        self.app.processEvents()
        self.temp_dir.cleanup()

    def test_open_files_workflow_receives_the_required_workspace_aggregate(self):
        received_models = []

        class Dialog:
            maintenance_requested = SimpleNamespace(connect=lambda _callback: None)

            def __init__(
                self,
                _icon_provider,
                _parent,
                _entries,
                _working_directory_service,
                *,
                workspace_state_model,
                sql_catalog,
                credential_store,
                sql_database_creator,
                schema_change_allowed_fn,
                maintenance_allowed_fn,
            ):
                received_models.append(workspace_state_model)

            def exec(self):
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        file_state = SimpleNamespace(file_entries=[], reload=lambda: None)
        handler = FileOperationHandler(
            window=None,
            icon_provider=_header_support__IconProvider(),
            event_bus=object(),
            file_state_model=file_state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=object(),
            working_directory_service=object(),
            unload_file_fn=lambda _database_id: True,
            deferred_persistence_manager=object(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=object(),
            workspace_state_model=self.model,
        )
        with mock.patch(
            "ost_visualizer.presentation.handlers.file_operation_handler."
            "OpenFilesDialog",
            Dialog,
        ):
            handler.open_files()
        self.assertEqual(len(received_models), 1)
        self.assertIs(received_models[0], self.model)


class StartupDatabaseRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_open_files_return_tolerates_destroyed_parent(self):
        window = QtWidgets.QDialog()
        cleanups = []

        class _State:
            file_entries = []

            def __init__(self):
                self.reloads = 0

            def reload(self):
                self.reloads += 1

        state = _State()

        class _Dialog(QtWidgets.QDialog):
            maintenance_requested = QtCore.Signal(object)

            def __init__(self, _icon, parent, *_args, **_kwargs):
                super().__init__(parent)

            def exec(self):
                delete(window)
                return QtWidgets.QDialog.DialogCode.Accepted

            def get_file_entries(self):
                raise AssertionError("a destroyed dialog must not be read")

            def cleanup(self):
                cleanups.append(True)

        handler = _startup_database_StartupFileOperationHandler(
            window=window,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=SimpleNamespace(),
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.OpenFilesDialog",
            _Dialog,
        ):
            handler.open_files()
        self.assertFalse(isValid(window))
        self.assertEqual(cleanups, [True])
        self.assertEqual(state.reloads, 2)

    def test_unchecking_unavailable_sql_does_not_require_repository_unload(self):
        sql_descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(sql_descriptor, is_checked=True)
        unchecked = original.with_checked(False)
        stopped = []
        cancelled = []
        disconnected = []

        class _State:
            file_entries = [original]

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                return set()

        handler = _startup_database_StartupFileOperationHandler(
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
                mark_disconnected=disconnected.append
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
        self.assertEqual(disconnected, [sql_descriptor.database_id])

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
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                return set()

        handler = _startup_database_StartupFileOperationHandler(
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
        self.assertEqual(drain_callbacks[0][0], descriptor.database_id)
        self.assertEqual(handler._file_state_model.file_entries, [original])
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.open_files()
        warning.assert_called_once_with(
            None,
            "Database Operation Pending",
            "Wait for the current database operation to finish before changing "
            "Open Files again.",
        )
        self.assertEqual(unloads, [])
        drain_callbacks[0][1](True, "")
        self.assertEqual(unloads, [descriptor.database_id])
        self.assertEqual(cancelled, [descriptor.database_id])
        self.assertEqual(handler._file_state_model.file_entries, [unchecked])
        self.assertFalse(handler._file_operation_pending)

    def test_open_files_uncheck_of_loaded_sql_stays_checked_when_critical_drain_fails(
        self,
    ):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="LOADED_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)
        unchecked = original.with_checked(False)

        def drain_reports_failure(_database_id, callback):
            callback(False, "writes pending")

        def drain_without_message(_database_id, callback):
            callback(False, "")

        def drain_raises(_database_id, _callback):
            raise RuntimeError("coordinator closed")

        def drain_must_not_run(_database_id, _callback):
            raise AssertionError("no drain after a failed flush")

        cases = (
            (
                "flush failure",
                False,
                drain_must_not_run,
                "A critical database setting could not be submitted before unload.",
            ),
            ("drain reports failure", True, drain_reports_failure, "writes pending"),
            (
                "drain failure without message",
                True,
                drain_without_message,
                "A critical database setting could not be saved before unload.",
            ),
            ("drain raises", True, drain_raises, "coordinator closed"),
        )
        for label, flush_result, drain, expected_message in cases:
            with self.subTest(label):
                unloads = []
                cancelled = []

                class _State:
                    file_entries = [original]

                    def reload(self):
                        pass

                    def update_entries(self, entries):
                        self.file_entries = list(entries)

                class _Dialog(_startup_database__OpenFilesDialogStub):
                    def get_file_entries(self):
                        return [unchecked]

                    def commit_credential_changes(self):
                        return set()

                handler = _startup_database_StartupFileOperationHandler(
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
                        flush_for_file=lambda _locator, result=flush_result: result,
                        cancel_for_file=cancelled.append,
                    ),
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                    sql_collaboration_coordinator=SimpleNamespace(
                        drain_database_mutations_async=drain
                    ),
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
                self.assertEqual(unloads, [])
                self.assertEqual(cancelled, [])
                self.assertEqual(handler._file_state_model.file_entries, [original])
                self.assertTrue(handler._file_state_model.file_entries[0].is_checked)
                warning.assert_called_once_with(None, "Unload File", expected_message)
                self.assertFalse(handler._file_operation_pending)

    def test_loaded_sql_unload_rejects_duplicate_action_while_drain_is_pending(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="LOADED_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        original = FileEntry.for_descriptor(descriptor, is_checked=True)
        drain_callbacks = []
        unloads = []

        class _State:
            file_entries = [original]

            def update_entries(self, entries):
                self.file_entries = list(entries)

        handler = _startup_database_StartupFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(),
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: True),
            working_directory_service=None,
            unload_file_fn=lambda locator: unloads.append(locator) or True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                drain_database_mutations_async=lambda _database_id, callback: (
                    drain_callbacks.append(callback)
                )
            ),
            ui_state_manager=SimpleNamespace(selected_file_path=descriptor.database_id),
        )
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler.unload_file()
            handler.unload_file()
        self.assertEqual(len(drain_callbacks), 1)
        self.assertEqual(unloads, [])
        warning.assert_called_once_with(
            None,
            "Database Operation Pending",
            "Wait for the current database operation to finish before changing "
            "Open Files again.",
        )
        self.assertTrue(handler._file_operation_pending)
        drain_callbacks[0](True, "")
        self.assertEqual(unloads, [descriptor.database_id])
        self.assertEqual(
            handler._file_state_model.file_entries, [original.with_checked(False)]
        )
        self.assertFalse(handler._file_operation_pending)

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
        handler = _startup_database_StartupFileOperationHandler(
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

        handler = _startup_database_StartupFileOperationHandler(
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
        warning.assert_called_once_with(
            None,
            "Unload File",
            "The Open Files state could not be saved, so the database was not "
            "unloaded.",
        )
        self.assertFalse(handler._file_operation_pending)

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
        handler = _startup_database_StartupFileOperationHandler(
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
        ) as warning:
            handler.unload_file()
        self.assertEqual(state.file_entries, [original])
        self.assertEqual(cancelled, [])
        self.assertEqual(flushed, [descriptor.database_id])
        self.assertEqual(drains, [descriptor.database_id])
        warning.assert_called_once_with(
            None, "No File Loaded", "There is no file currently loaded."
        )

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

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                credential_commits.append(True)
                return set()

        handler = _startup_database_StartupFileOperationHandler(
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
        warning.assert_called_once_with(
            None,
            "Open Files",
            "The Open Files state could not be saved, so no database changes were "
            "applied.",
        )

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

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                raise OSError("credential store unavailable")

        state = _State()
        handler = _startup_database_StartupFileOperationHandler(
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
        warning.assert_called_once_with(
            None,
            "Open Files",
            "The SQL credentials could not be finalized, so no database changes "
            "were applied.",
        )

    def test_open_files_reports_when_credential_failure_cannot_restore_selection(self):
        original = FileEntry("C:/projects/active.mdb", is_checked=True)
        unchecked = original.with_checked(False)
        unloads = []
        saves = []

        class _State:
            file_entries = [original]

            def reload(self):
                pass

            def update_entries(self, entries):
                saves.append([entry.is_checked for entry in entries])
                if len(saves) == 2:
                    raise OSError("disk unavailable")
                self.file_entries = list(entries)

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [unchecked]

            def commit_credential_changes(self):
                raise OSError("credential store unavailable")

        handler = _startup_database_StartupFileOperationHandler(
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
        self.assertEqual(saves, [[False], [True]])
        self.assertEqual(unloads, [])
        warning.assert_called_once_with(
            None,
            "Open Files",
            "The SQL credentials could not be finalized and the previous Open Files "
            "state could not be restored.",
        )

    def test_failed_load_checkbox_rollback_save_failure_is_contained(self):
        checked = FileEntry("C:/projects/unavailable.mdb", is_checked=True)

        class _State:
            file_entries = []

            def __init__(self):
                self.update_count = 0
                self.saved = []

            def reload(self):
                pass

            def update_entries(self, entries):
                self.update_count += 1
                if self.update_count == 2:
                    raise OSError("disk unavailable")
                self.file_entries = list(entries)
                self.saved.append(
                    [(entry.database_id, entry.is_checked) for entry in entries]
                )

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [checked]

            def commit_credential_changes(self):
                return set()

        state = _State()
        handler = _startup_database_StartupFileOperationHandler(
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
        self.assertEqual(state.update_count, 2)
        self.assertEqual(state.saved, [[(checked.database_id, True)]])
        self.assertEqual(
            [call.args[1:] for call in warning.call_args_list],
            [
                (
                    "Error Loading File",
                    f"Failed to load {checked.descriptor.display_name}:\nunavailable",
                ),
                (
                    "Open Files",
                    "A database could not be loaded and its checked state could "
                    "not be cleared.",
                ),
            ],
        )

    def test_failed_load_clears_the_persisted_checkbox(self):
        checked = FileEntry("C:/projects/unavailable.mdb", is_checked=True)

        class _State:
            file_entries = []

            def __init__(self):
                self.saved = []

            def reload(self):
                pass

            def update_entries(self, entries):
                self.file_entries = list(entries)
                self.saved.append(
                    [(entry.database_id, entry.is_checked) for entry in entries]
                )

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [checked]

            def commit_credential_changes(self):
                return set()

        state = _State()
        disconnected = []
        handler = _startup_database_StartupFileOperationHandler(
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
            database_capability_service=SimpleNamespace(
                mark_disconnected=disconnected.append
            ),
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
        database_id = checked.database_id
        self.assertEqual(state.saved, [[(database_id, True)], [(database_id, False)]])
        self.assertEqual(disconnected, [database_id])
        warning.assert_called_once()
        self.assertEqual(warning.call_args.args[1], "Error Loading File")

    def test_sql_retry_uses_coordinator_without_loading_on_qt_thread(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="UNAVAILABLE_SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        entry = FileEntry.for_descriptor(descriptor, is_checked=True)
        restarts = []

        def stop_database(database_id, reason, callback):
            restarts.append(("stop", database_id, reason, threading.get_ident()))
            callback(True, "")

        handler = _startup_database_StartupFileOperationHandler.__new__(
            _startup_database_StartupFileOperationHandler
        )
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
        self.assertEqual(
            [call[:2] for call in restarts],
            [
                ("stop", descriptor.database_id),
                ("start", descriptor.database_id),
            ],
        )
        self.assertEqual(restarts[0][2], "reconfigured")

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

        class _Dialog(_startup_database__OpenFilesDialogStub):
            def get_file_entries(self):
                return [checked]

            def commit_credential_changes(self):
                return set()

        state = _State()
        handler = _startup_database_StartupFileOperationHandler(
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
        handler = _startup_database_StartupFileOperationHandler.__new__(
            _startup_database_StartupFileOperationHandler
        )
        handler._file_state_model = SimpleNamespace(file_entries=[])
        handler._sql_collaboration = SimpleNamespace(start_database=starts.append)
        handler._complete_sql_connection_restart(
            "removed-sql-database",
            True,
            "",
        )
        self.assertEqual(starts, [])

    def test_stale_sql_restart_failure_does_not_warn_after_removal(self):
        handler = _startup_database_StartupFileOperationHandler.__new__(
            _startup_database_StartupFileOperationHandler
        )
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
        handler = _startup_database_StartupFileOperationHandler.__new__(
            _startup_database_StartupFileOperationHandler
        )
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _cleanup_support__CredentialStore()
        disconnected = []
        handler._file_state_model = SimpleNamespace(
            file_entries=[entry.with_checked(False)]
        )
        handler._sql_collaboration = SimpleNamespace(start_database=starts.append)
        handler._database_descriptor_registry = registry
        handler._credential_store = credentials
        handler._database_capability_service = SimpleNamespace(
            mark_disconnected=disconnected.append
        )
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(starts, [])
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        self.assertEqual(credentials.deleted, [])
        self.assertEqual(disconnected, [])

    def test_sql_restart_callback_starts_only_enabled_entries_and_reports_failure(
        self,
    ):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="SQL"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        checked = FileEntry.for_descriptor(descriptor, is_checked=True)
        unchecked = checked.with_checked(False)
        closed_safely = (
            "The existing SQL collaboration session could not be closed safely."
        )
        cases = (
            (
                "checked entry restarts",
                [checked],
                True,
                "",
                [descriptor.database_id],
                None,
            ),
            ("unchecked entry stays stopped", [unchecked], True, "", [], None),
            (
                "checked failure reports its message",
                [checked],
                False,
                "drain timed out",
                [],
                "drain timed out",
            ),
            (
                "checked failure reports the default message",
                [checked],
                False,
                "",
                [],
                closed_safely,
            ),
            ("unchecked failure stays silent", [unchecked], False, "late", [], None),
        )
        for label, entries, success, message, expected_starts, warned in cases:
            with self.subTest(label):
                starts = []
                handler = _startup_database_StartupFileOperationHandler.__new__(
                    _startup_database_StartupFileOperationHandler
                )
                handler.window = None
                handler._file_state_model = SimpleNamespace(file_entries=entries)
                handler._sql_collaboration = SimpleNamespace(
                    start_database=starts.append
                )
                with patch(
                    "ost_visualizer.presentation.handlers.file_operation_handler."
                    "show_warning"
                ) as warning:
                    handler._complete_sql_connection_restart(
                        descriptor.database_id, success, message
                    )
                self.assertEqual(starts, expected_starts)
                if warned is None:
                    warning.assert_not_called()
                else:
                    warning.assert_called_once_with(
                        None, "Reconnect SQL Server Database", warned
                    )


_FOH = "ost_visualizer.presentation.handlers.file_operation_handler"


def _not_ready_message(detail):
    return (
        "The database was created and its connection saved, but it is not ready "
        "for editing. " + detail + " Reconnect through Open Files. "
        "The server database and saved runtime credentials were retained."
    )


_AUTOSPECS = {}


def _shared_autospec(cls):
    """A signature-enforcing mock of ``cls``, reset on every use.
    Building an autospec of the large coordinator/access classes costs about as much
    as running a whole test, so each is built once per process and fully reset
    (calls, return values and side effects) whenever a test asks for it.
    """
    mock = _AUTOSPECS.get(cls)
    if mock is None:
        mock = _AUTOSPECS[cls] = create_autospec(cls, instance=True)
    mock.reset_mock(return_value=True, side_effect=True)
    return mock


class _MaintenanceDialog(QtWidgets.QDialog):
    """Minimal real Qt dialog exposing the OpenFilesDialog maintenance surface."""

    def __init__(self, parent, entry):
        super().__init__(parent)
        self.entry = entry
        self.busy = []
        self.refreshed = []

    def maintenance_target(self):
        return self.entry

    def set_maintenance_busy(self, busy):
        self.busy.append(busy)

    def refresh_database_metadata(self, database_id):
        self.refreshed.append(database_id)


class _RecordingProgress:
    """ProgressDialog stand-in that runs the task synchronously on exec()."""

    instances = []
    on_exec = None

    def __init__(self, name, task, **kwargs):
        self.name, self.task, self.kwargs = name, task, kwargs
        self.result = None
        self.error = None
        self.cleaned = 0
        self.deleted = 0
        type(self).instances.append(self)

    def exec(self):
        if type(self).on_exec is not None:
            type(self).on_exec(self)
        try:
            self.result = self.task()
        except Exception as exc:
            self.error = exc

    def cleanup(self):
        self.cleaned += 1

    def deleteLater(self):
        self.deleted += 1


class FileOperationHandlerCompactDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        _RecordingProgress.instances = []
        _RecordingProgress.on_exec = None
        self.entry = FileEntry("C:/projects/compact.mdb", is_checked=True)
        self.window = QtWidgets.QWidget()
        self.addCleanup(lambda: isValid(self.window) and delete(self.window))
        self.dialog = _MaintenanceDialog(self.window, self.entry)
        self.events = []
        self.target = object()
        self.prepared = object()
        self.maintenance = _shared_autospec(DatabaseMaintenanceService)
        self.maintenance.unavailable_reason.return_value = ""
        self.maintenance.capture_target.side_effect = (
            lambda locator: self.events.append(("capture", locator)) or self.target
        )
        self.maintenance.is_target_current.return_value = True
        self.maintenance.prepare.side_effect = (
            lambda target: self.events.append(("prepare", target)) or self.prepared
        )
        self.maintenance.finish.return_value = DatabaseMaintenanceResult(True, "Done.")
        self.deferred = _shared_autospec(DeferredPersistenceManager)
        self.deferred.flush_for_file.return_value = True
        self.access = _shared_autospec(UIAccessManager)
        self.access.can_maintain_database.return_value = True
        self.unload = lambda _locator: True
        self.handler = FileOperationHandler(
            self.window,
            _shared_autospec(IWindowIconProvider),
            _shared_autospec(EventBus),
            SimpleNamespace(file_entries=[self.entry]),
            None,
            None,
            None,
            self.unload,
            self.deferred,
            self.access,
            _shared_autospec(SqlCollaborationCoordinator),
            make_workspace_state_model(),
            database_maintenance_service=self.maintenance,
        )
        self.confirm_answer = True
        self.warnings, self.infos, self.confirms = [], [], []

        def confirm(parent, title, message):
            self.events.append("confirm")
            self.confirms.append((parent, title, message))
            return self.confirm_answer

        patches = [
            patch(f"{_FOH}.ProgressDialog", _RecordingProgress),
            patch(f"{_FOH}.confirm", confirm),
            patch(
                f"{_FOH}.show_warning",
                lambda parent, title, message: self.warnings.append(
                    (parent, title, message)
                ),
            ),
            patch(
                f"{_FOH}.show_info",
                lambda parent, title, message: self.infos.append(
                    (parent, title, message)
                ),
            ),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def compact(self):
        self.handler._compact_database(self.dialog, self.entry)

    def assert_inert(self):
        self.assertEqual(self.maintenance.mock_calls, [])
        self.assertEqual(self.dialog.busy, [])
        self.assertFalse(self.handler.maintenance_pending)
        self.assertFalse(self.handler._file_operation_pending)
        self.assertEqual(self.handler._file_operation_serial, 0)
        self.assertEqual((self.warnings, self.infos, self.confirms), ([], [], []))

    def test_fake_collaborators_match_the_real_signatures(self):
        for name in (
            "unavailable_reason",
            "capture_target",
            "is_target_current",
            "prepare",
            "finish",
            "discard",
            "release_target",
        ):
            self.assertTrue(callable(getattr(DatabaseMaintenanceService, name)))
        self.assertEqual(
            list(inspect.signature(DatabaseMaintenanceService.finish).parameters),
            ["self", "target", "prepared", "unload_file"],
        )

    def test_a_successful_compaction_runs_every_step_in_order_and_cleans_up(self):
        observed = []
        self.maintenance.finish.side_effect = lambda target, prepared, unload: (
            observed.append(
                (
                    self.handler.maintenance_pending,
                    self.handler._file_operation_pending,
                    list(self.dialog.busy),
                )
            )
            or DatabaseMaintenanceResult(True, "Compacted 3 MB.")
        )
        self.compact()
        locator = self.entry.runtime_locator
        self.assertEqual(
            self.events, [("capture", locator), "confirm", ("prepare", self.target)]
        )
        self.maintenance.unavailable_reason.assert_called_once_with(locator)
        self.deferred.flush_for_file.assert_called_once_with(locator)
        self.maintenance.is_target_current.assert_called_once_with(self.target)
        self.maintenance.finish.assert_called_once_with(
            self.target, self.prepared, self.unload
        )
        self.maintenance.discard.assert_not_called()
        self.maintenance.release_target.assert_called_once_with(self.target)
        # While the operation runs the handler reports busy and the dialog is busy.
        self.assertEqual(observed, [(True, True, [True])])
        self.assertEqual(self.dialog.busy, [True, False])
        self.assertEqual(self.dialog.refreshed, [self.entry.database_id])
        self.assertEqual(
            self.infos, [(self.dialog, "Compact/Repair", "Compacted 3 MB.")]
        )
        self.assertEqual(self.warnings, [])
        self.assertFalse(self.handler.maintenance_pending)
        self.assertFalse(self.handler._file_operation_pending)
        (parent, title, message) = self.confirms[0]
        self.assertEqual((parent, title), (self.dialog, "Compact/Repair"))
        self.assertEqual(
            message,
            "Compact and repair the selected database? Close this database in other "
            "applications first. It will be unavailable during maintenance and "
            "refreshed afterward.",
        )
        (progress,) = _RecordingProgress.instances
        self.assertEqual(progress.name, self.entry.descriptor.display_name)
        self.assertEqual(
            progress.kwargs,
            {"parent": self.dialog, "action_text": "Compacting/repairing"},
        )
        self.assertEqual((progress.cleaned, progress.deleted), (1, 1))

    def test_a_failed_compaction_warns_with_the_message_and_does_not_refresh(self):
        self.maintenance.finish.return_value = DatabaseMaintenanceResult(
            False, "The file is locked."
        )
        self.compact()
        self.assertEqual(
            self.warnings, [(self.dialog, "Compact/Repair", "The file is locked.")]
        )
        self.assertEqual(self.infos, [])
        self.assertEqual(self.dialog.refreshed, [])
        self.maintenance.release_target.assert_called_once_with(self.target)

    def test_entry_conditions_that_are_not_met_leave_everything_untouched(self):
        other = FileEntry("C:/projects/other.mdb")
        equal = FileEntry("C:/projects/compact.mdb", is_checked=True)
        self.assertEqual(equal, self.entry)
        self.assertIsNot(equal, self.entry)
        cases = {
            "another entry is targeted": lambda: setattr(self.dialog, "entry", other),
            "the entry was replaced by an equal one": lambda: setattr(
                self.dialog, "entry", equal
            ),
            "access denied": lambda: setattr(
                self.access.can_maintain_database, "return_value", False
            ),
            "operation already pending": lambda: setattr(
                self.handler, "_file_operation_pending", True
            ),
            "no maintenance service": lambda: setattr(
                self.handler, "_database_maintenance", None
            ),
            "window destroyed": lambda: (
                self.dialog.setParent(None),
                delete(self.window),
            ),
        }
        for label, arrange in cases.items():
            with self.subTest(label):
                self.setUp()
                arrange()
                pending_before = self.handler._file_operation_pending
                self.compact()
                self.assertEqual(self.maintenance.mock_calls, [])
                self.assertEqual(self.dialog.busy if isValid(self.dialog) else [], [])
                self.assertEqual(self.handler._file_operation_serial, 0)
                self.assertFalse(self.handler.maintenance_pending)
                self.assertEqual(self.handler._file_operation_pending, pending_before)
                self.assertEqual(self.warnings + self.infos + self.confirms, [])

    def test_a_destroyed_dialog_is_not_driven(self):
        delete(self.dialog)
        self.compact()
        self.assertEqual(self.maintenance.mock_calls, [])
        self.assertEqual(self.handler._file_operation_serial, 0)

    def test_an_unavailable_database_warns_and_stops_before_flushing(self):
        self.maintenance.unavailable_reason.return_value = "Not available on SQL."
        self.compact()
        self.assertEqual(
            self.warnings, [(self.dialog, "Compact/Repair", "Not available on SQL.")]
        )
        self.deferred.flush_for_file.assert_not_called()
        self.maintenance.capture_target.assert_not_called()
        self.maintenance.release_target.assert_not_called()
        self.assertEqual(self.dialog.busy, [True, False])
        self.assertFalse(self.handler._file_operation_pending)
        self.assertFalse(self.handler.maintenance_pending)

    def test_other_visible_dialogs_block_maintenance_but_hidden_ones_do_not(self):
        hidden = QtWidgets.QDialog(self.window)
        shown = QtWidgets.QDialog(self.window)
        self.dialog.show()
        shown.show()
        self.assertFalse(hidden.isVisible())
        self.compact()
        self.assertEqual(len(self.warnings), 1)
        self.assertEqual(self.warnings[0][:2], (self.dialog, "Compact/Repair"))
        self.assertEqual(
            self.warnings[0][2],
            "Close other editors before database maintenance. Unsaved drafts will "
            "not be discarded.",
        )
        self.deferred.flush_for_file.assert_not_called()
        self.assertFalse(self.handler._file_operation_pending)
        self.warnings.clear()
        shown.hide()
        self.compact()
        self.assertEqual(self.warnings, [])
        self.maintenance.finish.assert_called_once()

    def test_a_failed_deferred_flush_stops_silently_before_capturing_a_target(self):
        self.deferred.flush_for_file.return_value = False
        self.compact()
        self.maintenance.capture_target.assert_not_called()
        self.assertEqual(self.warnings + self.infos + self.confirms, [])
        self.assertEqual(self.dialog.busy, [True, False])
        self.assertFalse(self.handler._file_operation_pending)

    def test_declining_the_confirmation_releases_the_captured_target(self):
        self.confirm_answer = False
        self.compact()
        self.maintenance.prepare.assert_not_called()
        self.assertEqual(_RecordingProgress.instances, [])
        self.maintenance.release_target.assert_called_once_with(self.target)

    def test_context_changes_during_the_confirmation_abandon_the_run(self):
        other = FileEntry("C:/projects/other.mdb")
        equal = FileEntry("C:/projects/compact.mdb", is_checked=True)
        cases = {
            "target changed": lambda: setattr(self.dialog, "entry", other),
            "target replaced by an equal entry": lambda: setattr(
                self.dialog, "entry", equal
            ),
            "access revoked": lambda: setattr(
                self.access.can_maintain_database, "return_value", False
            ),
            "dialog destroyed": lambda: delete(self.dialog),
            "window destroyed": lambda: (
                self.dialog.setParent(None),
                delete(self.window),
            ),
        }
        for label, arrange in cases.items():
            with self.subTest(label):
                self.setUp()
                self.confirm_answer = True

                def confirm(parent, title, message, arrange=arrange):
                    arrange()
                    return True

                with patch(f"{_FOH}.confirm", confirm):
                    self.compact()
                self.maintenance.is_target_current.assert_not_called()
                self.maintenance.prepare.assert_not_called()
                self.assertEqual(_RecordingProgress.instances, [])
                self.maintenance.release_target.assert_called_once_with(self.target)

    def test_a_target_that_is_no_longer_current_is_released_without_preparing(self):
        self.maintenance.is_target_current.return_value = False
        self.compact()
        self.maintenance.prepare.assert_not_called()
        self.assertEqual(_RecordingProgress.instances, [])
        self.maintenance.release_target.assert_called_once_with(self.target)
        self.assertFalse(self.handler._file_operation_pending)

    def test_context_changes_during_preparation_discard_the_prepared_work(self):
        other = FileEntry("C:/projects/other.mdb")
        equal = FileEntry("C:/projects/compact.mdb", is_checked=True)
        cases = {
            "target changed": lambda: setattr(self.dialog, "entry", other),
            "target replaced by an equal entry": lambda: setattr(
                self.dialog, "entry", equal
            ),
            "access revoked": lambda: setattr(
                self.access.can_maintain_database, "return_value", False
            ),
            "dialog destroyed": lambda: delete(self.dialog),
            "window destroyed": lambda: (
                self.dialog.setParent(None),
                delete(self.window),
            ),
        }
        for label, arrange in cases.items():
            with self.subTest(label):
                self.setUp()
                _RecordingProgress.on_exec = (
                    lambda _progress, arrange=arrange: arrange()
                )
                self.compact()
                self.maintenance.prepare.assert_called_once_with(self.target)
                self.maintenance.finish.assert_not_called()
                self.maintenance.discard.assert_called_once_with(self.prepared)
                self.maintenance.release_target.assert_called_once_with(self.target)
                self.assertFalse(self.handler._file_operation_pending)
                self.assertFalse(self.handler.maintenance_pending)

    def test_preparation_errors_are_reported_without_finishing(self):
        for label, error, expected in (
            ("with a message", RuntimeError("Disk full."), "Disk full."),
            ("without a message", RuntimeError(), "Database maintenance failed."),
        ):
            with self.subTest(label):
                self.setUp()
                self.maintenance.prepare.side_effect = error
                self.compact()
                self.assertEqual(
                    self.warnings, [(self.dialog, "Compact/Repair", expected)]
                )
                self.maintenance.finish.assert_not_called()
                self.maintenance.discard.assert_not_called()
                self.maintenance.release_target.assert_called_once_with(self.target)
                self.assertEqual(self.dialog.busy, [True, False])
                (progress,) = _RecordingProgress.instances
                self.assertEqual((progress.cleaned, progress.deleted), (1, 1))

    def test_a_missing_preparation_result_is_an_error(self):
        self.maintenance.prepare.side_effect = lambda target: None
        self.compact()
        self.assertEqual(
            self.warnings,
            [(self.dialog, "Compact/Repair", "Database maintenance did not complete.")],
        )
        self.maintenance.finish.assert_not_called()
        self.maintenance.discard.assert_not_called()

    def test_finish_failures_are_reported_and_the_consumed_work_is_not_discarded(self):
        self.maintenance.finish.side_effect = RuntimeError("Commit failed.")
        self.compact()
        self.assertEqual(
            self.warnings, [(self.dialog, "Compact/Repair", "Commit failed.")]
        )
        self.maintenance.discard.assert_not_called()
        self.maintenance.release_target.assert_called_once_with(self.target)
        self.assertFalse(self.handler._file_operation_pending)

    def test_cleanup_failures_are_surfaced_once_and_never_skip_the_release(self):
        self.maintenance.release_target.side_effect = OSError("handle busy")
        self.compact()
        self.assertEqual(
            self.warnings,
            [
                (
                    self.dialog,
                    "Compact/Repair",
                    "Temporary-file cleanup failed: handle busy",
                )
            ],
        )
        self.assertEqual(len(self.infos), 1)
        self.assertEqual(self.dialog.busy, [True, False])
        self.assertFalse(self.handler._file_operation_pending)

    def test_a_cleanup_failure_after_a_reported_error_is_only_logged(self):
        self.maintenance.finish.side_effect = RuntimeError("Commit failed.")
        self.maintenance.release_target.side_effect = OSError("handle busy")
        with self.assertLogs(_FOH, level="WARNING") as logs:
            self.compact()
        self.assertEqual(
            self.warnings, [(self.dialog, "Compact/Repair", "Commit failed.")]
        )
        self.assertIn(
            "Maintenance temporary-file cleanup failed: handle busy", logs.output[0]
        )

    def test_a_cleanup_failure_for_a_changed_target_is_only_logged(self):
        self.maintenance.release_target.side_effect = OSError("handle busy")

        def finish(target, prepared, unload):
            self.dialog.entry = FileEntry("C:/projects/other.mdb")
            return DatabaseMaintenanceResult(True, "Done.")

        self.maintenance.finish.side_effect = finish
        with self.assertLogs(_FOH, level="WARNING"):
            self.compact()
        self.assertEqual(self.warnings, [])

    def test_discard_failure_does_not_prevent_releasing_the_target(self):
        self.maintenance.discard.side_effect = OSError("close failed")
        _RecordingProgress.on_exec = lambda _progress: delete(self.dialog)
        with self.assertLogs(_FOH, level="WARNING"):
            self.compact()
        self.maintenance.discard.assert_called_once_with(self.prepared)
        self.maintenance.release_target.assert_called_once_with(self.target)

    def test_a_dialog_destroyed_before_the_final_report_is_not_driven_again(self):
        self.maintenance.finish.side_effect = lambda *_args: (
            delete(self.dialog) or DatabaseMaintenanceResult(True, "Done.")
        )
        self.compact()
        self.assertEqual(self.dialog.busy, [True])
        self.maintenance.release_target.assert_called_once_with(self.target)
        self.assertFalse(self.handler._file_operation_pending)
        self.assertFalse(self.handler.maintenance_pending)

    def test_begin_and_finish_use_a_serial_so_only_the_latest_operation_completes(
        self,
    ):
        first = self.handler._begin_pending_file_operation()
        second = self.handler._begin_pending_file_operation()
        self.assertNotEqual(first, second)
        self.assertIs(self.handler._finish_pending_file_operation(first), False)
        self.assertTrue(self.handler._file_operation_pending)
        self.assertIs(self.handler._finish_pending_file_operation(second), True)
        self.assertFalse(self.handler._file_operation_pending)
        self.assertEqual(self.handler._file_operation_serial, 2)

    def test_a_fresh_handler_reports_no_pending_operation(self):
        self.assertIs(self.handler.sql_creation_pending, False)
        self.assertIs(self.handler.maintenance_pending, False)
        self.assertIs(self.handler._file_operation_pending, False)
        self.assertEqual(self.handler._file_operation_serial, 0)

    def test_maintenance_is_allowed_only_with_a_service_no_pending_operation_and_access(
        self,
    ):
        allowed = self.handler._maintenance_allowed
        self.assertIs(allowed(self.entry), True)
        self.access.can_maintain_database.assert_called_with(self.entry.runtime_locator)
        self.handler._file_operation_pending = True
        self.assertIs(allowed(self.entry), False)
        self.handler._file_operation_pending = False
        self.access.can_maintain_database.return_value = False
        self.assertIs(allowed(self.entry), False)
        self.access.can_maintain_database.return_value = True
        self.handler._database_maintenance = None
        self.assertIs(allowed(self.entry), False)


class _FlowState:
    """In-memory Open Files state recording every save; saves can be made to fail."""

    def __init__(self, entries, fail_saves=()):
        self.file_entries = list(entries)
        self.saves = []
        self.reloads = 0
        self.fail_saves = set(fail_saves)

    def reload(self):
        self.reloads += 1

    def update_entries(self, entries):
        self.saves.append([(entry.database_id, entry.is_checked) for entry in entries])
        if len(self.saves) in self.fail_saves:
            raise OSError("disk unavailable")
        self.file_entries = list(entries)


def _flow_dialog(selected, *, credential_ids=frozenset(), on_exec=None, log=None):
    class _FlowDialog:
        maintenance_requested = SimpleNamespace(connect=lambda _callback: None)
        instances = []

        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs
            self.cleaned = 0
            self.deleted = 0
            type(self).instances.append(self)

        def exec(self):
            if log is not None:
                log.append("exec")
            if on_exec is not None:
                on_exec(self)
            return QtWidgets.QDialog.DialogCode.Accepted

        def get_file_entries(self):
            return list(selected)

        def commit_credential_changes(self):
            return set(credential_ids)

        def refresh_maintenance_access(self):
            pass

        def cleanup(self):
            self.cleaned += 1

        def deleteLater(self):
            self.deleted += 1

    return _FlowDialog


def _sql_entry(name, *, checked=True):
    return FileEntry.for_descriptor(
        DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database=name),
            schema_version=SQL_SCHEMA_V1.version,
        ),
        is_checked=checked,
    )


class _FlowFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.log = []
        self.loaded = set()
        self.warnings = []
        self.published = []
        self.unloads = []
        self.unload_ok = True
        self.registry = DatabaseDescriptorRegistry()
        self.window = QtWidgets.QWidget()
        self.addCleanup(lambda: isValid(self.window) and delete(self.window))
        self.deferred = _shared_autospec(DeferredPersistenceManager)
        self.deferred.flush_for_file.side_effect = (
            lambda locator: self.log.append(("flush", locator)) or True
        )
        self.deferred.cancel_for_file.side_effect = lambda locator: self.log.append(
            ("cancel", locator)
        )
        self.collab = _shared_autospec(SqlCollaborationCoordinator)
        self.drains = []
        self.collab.drain_database_mutations_async.side_effect = (
            lambda database_id, callback: self.drains.append((database_id, callback))
        )
        self.stops = []
        self.collab.stop_database_async.side_effect = (
            lambda database_id, reason="closed", callback=None: self.stops.append(
                (database_id, reason, callback)
            )
        )
        self.collab.start_database.return_value = True
        self.files = _shared_autospec(FileLoadingService)
        self.files.is_loaded.side_effect = lambda locator: locator in self.loaded
        self.files.load_file.side_effect = lambda locator: FileLoadResultDto(
            success=True, file_path=locator
        )
        self.capability = SimpleNamespace(
            disconnected=[],
            mark_disconnected=lambda database_id: self.capability.disconnected.append(
                database_id
            ),
        )
        self.access = _shared_autospec(UIAccessManager)
        self.access.is_allowed.return_value = True
        self.cleanup_uc = SimpleNamespace(
            execute_and_save=lambda: self.log.append("cleanup")
        )
        self.events = _shared_autospec(EventBus)
        self.events.publish.side_effect = lambda event, **kwargs: self.published.append(
            (event, kwargs)
        )
        self.warning_parents = []
        patcher = patch(
            f"{_FOH}.show_warning",
            lambda parent, title, message: (
                self.warning_parents.append(parent),
                self.warnings.append((title, message)),
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        # Every modal warning of these flows belongs to the handler's owning window.
        for parent in self.warning_parents:
            self.assertIs(parent, self.window)
        super().tearDown()

    def handler(self, state, **overrides):
        options = dict(
            window=self.window,
            icon_provider=_shared_autospec(IWindowIconProvider),
            event_bus=self.events,
            file_state_model=state,
            cleanup_deleted_files_use_case=self.cleanup_uc,
            file_loading_service=self.files,
            working_directory_service=None,
            unload_file_fn=lambda locator: self.unloads.append(locator)
            or self.unload_ok,
            deferred_persistence_manager=self.deferred,
            ui_access_manager=self.access,
            sql_collaboration_coordinator=self.collab,
            workspace_state_model=make_workspace_state_model(),
            database_descriptor_registry=self.registry,
            database_capability_service=self.capability,
        )
        options.update(overrides)
        return FileOperationHandler(**options)

    def open_files(self, handler, dialog_class):
        with patch(f"{_FOH}.OpenFilesDialog", dialog_class):
            handler.open_files()


class FileOperationHandlerOpenFilesFlowTests(_FlowFixture):
    def test_open_files_refreshes_state_registers_entries_and_releases_the_dialog(
        self,
    ):
        sql = _sql_entry("REGISTERED")
        original = [FileEntry("C:/projects/a.mdb", is_checked=False), sql]
        state = _FlowState(original)
        state.reload = lambda: self.log.append("reload")
        seen_at_exec = []
        selected = [original[0], sql, _sql_entry("ADDED")]
        dialog_class = _flow_dialog(
            selected,
            log=self.log,
            on_exec=lambda _dialog: seen_at_exec.append(
                self.registry.resolve(sql.database_id)
            ),
        )
        handler = self.handler(state)
        self.open_files(handler, dialog_class)
        self.assertEqual(self.log[:4], ["reload", "cleanup", "reload", "exec"])
        # The original entries are registered before the dialog opens...
        self.assertEqual(seen_at_exec, [sql.descriptor])
        # ...and the accepted selection afterwards.
        self.assertEqual(
            self.registry.resolve(selected[2].database_id), selected[2].descriptor
        )
        (dialog,) = dialog_class.instances
        self.assertEqual((dialog.cleaned, dialog.deleted), (1, 1))
        self.assertEqual(
            state.saves, [[(e.database_id, e.is_checked) for e in selected]]
        )

    def test_the_dialog_is_given_the_handlers_collaborators_and_permission_checks(
        self,
    ):
        original = [FileEntry("C:/projects/a.mdb")]
        state = _FlowState(original)
        dialog_class = _flow_dialog([])
        handler = self.handler(
            state,
            database_catalog="catalog",
            credential_store="credentials",
            sql_database_creator="creator",
        )
        self.open_files(handler, dialog_class)
        (dialog,) = dialog_class.instances
        icon, parent, entries, working_directory = dialog.args
        self.assertIs(parent, self.window)
        self.assertEqual(entries, original)
        self.assertIs(
            dialog.kwargs["workspace_state_model"], handler._workspace_state_model
        )
        self.assertEqual(dialog.kwargs["sql_catalog"], "catalog")
        self.assertEqual(dialog.kwargs["credential_store"], "credentials")
        self.assertEqual(dialog.kwargs["sql_database_creator"], "creator")
        self.assertEqual(
            dialog.kwargs["maintenance_allowed_fn"], handler._maintenance_allowed
        )
        self.assertIs(dialog.kwargs["schema_change_allowed_fn"](), True)
        self.access.is_allowed.assert_called_with(Feature.CREATE_DATABASE)
        self.access.is_allowed.return_value = False
        self.assertIs(dialog.kwargs["schema_change_allowed_fn"](), False)

    def test_access_changes_refresh_the_dialog_only_while_maintenance_is_available(
        self,
    ):
        for maintenance, expected in (
            (None, []),
            (object(), ["subscribe", "unsubscribe"]),
        ):
            with self.subTest(maintenance=maintenance is not None):
                access = _shared_autospec(UIAccessManager)
                calls = []
                access.subscribe_access_state_changed.side_effect = (
                    lambda callback: calls.append(("subscribe", callback))
                )
                access.unsubscribe_access_state_changed.side_effect = (
                    lambda callback: calls.append(("unsubscribe", callback))
                )
                dialog_class = _flow_dialog([])
                handler = self.handler(
                    _FlowState([]),
                    ui_access_manager=access,
                    database_maintenance_service=maintenance,
                )
                self.open_files(handler, dialog_class)
                (dialog,) = dialog_class.instances
                self.assertEqual([name for name, _cb in calls], expected)
                for _name, callback in calls:
                    self.assertEqual(callback, dialog.refresh_maintenance_access)

    def test_a_maintenance_request_is_forwarded_with_the_dialog_first(self):
        requested = []

        class _SignalDialog(QtWidgets.QDialog):
            maintenance_requested = QtCore.Signal(object)

            def __init__(self, *args, **kwargs):
                super().__init__(args[1])

            def exec(self):
                self.maintenance_requested.emit("the-entry")
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

        handler = self.handler(_FlowState([]))
        handler._compact_database = lambda dialog, entry: requested.append(
            (type(dialog), entry)
        )
        self.open_files(handler, _SignalDialog)
        self.assertEqual(requested, [(_SignalDialog, "the-entry")])

    def test_a_destroyed_window_or_dialog_ends_the_operation_without_reading_it(self):
        for label in ("window", "dialog"):
            with self.subTest(label):
                state = _FlowState([FileEntry("C:/projects/a.mdb")])
                reads = []

                class _Dialog(QtWidgets.QDialog):
                    maintenance_requested = QtCore.Signal(object)

                    def __init__(self, *args, **kwargs):
                        super().__init__(None)

                    def exec(inner):
                        delete(self.window if label == "window" else inner)
                        return QtWidgets.QDialog.DialogCode.Accepted

                    def get_file_entries(self):
                        reads.append("get_file_entries")
                        return []

                    def cleanup(self):
                        pass

                self.window = QtWidgets.QWidget()
                handler = self.handler(state)
                self.open_files(handler, _Dialog)
                self.assertEqual(reads, [])
                self.assertEqual(state.saves, [])
                self.assertEqual(self.warnings, [])

    def test_unchecking_a_loaded_access_entry_flushes_unloads_and_disconnects(self):
        entry = FileEntry("C:/projects/a.mdb")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
        self.assertEqual(
            [item for item in self.log if item != "cleanup"],
            [("flush", entry.runtime_locator), ("cancel", entry.runtime_locator)],
        )
        self.assertEqual(self.unloads, [entry.runtime_locator])
        self.assertEqual(self.capability.disconnected, [entry.database_id])
        # Only the dialog's own save: nothing is re-saved and no SQL drain starts.
        self.assertEqual(state.saves, [[(entry.database_id, False)]])
        self.assertEqual(self.drains, [])
        self.assertEqual(self.stops, [])
        self.assertEqual(self.warnings, [])

    def test_a_failed_flush_or_unload_keeps_an_access_entry_checked_and_saved(self):
        for label in ("flush", "unload"):
            with self.subTest(label):
                self.setUp()
                self.unloads.clear()
                entry = FileEntry("C:/projects/a.mdb")
                self.loaded.add(entry.runtime_locator)
                state = _FlowState([entry])
                if label == "flush":
                    self.deferred.flush_for_file.side_effect = lambda _locator: False
                else:
                    self.unload_ok = False
                handler = self.handler(state)
                self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
                self.assertEqual(
                    state.saves,
                    [[(entry.database_id, False)], [(entry.database_id, True)]],
                )
                self.assertTrue(state.file_entries[0].is_checked)
                self.assertEqual(self.capability.disconnected, [])
                if label == "flush":
                    self.assertEqual(self.unloads, [])
                    self.assertEqual(self.warnings, [])
                else:
                    self.assertEqual(
                        self.warnings,
                        [("Unload File", f"Failed to unload {entry.runtime_locator}.")],
                    )

    def test_unchecking_an_access_entry_that_is_not_loaded_still_attempts_the_unload(
        self,
    ):
        entry = FileEntry("C:/projects/a.mdb")
        self.unload_ok = False
        state = _FlowState([entry])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
        self.assertEqual(self.unloads, [entry.runtime_locator])
        self.assertEqual(self.stops, [])
        self.assertTrue(state.file_entries[0].is_checked)

    def test_only_unchecked_loaded_sql_entries_are_drained(self):
        gone, kept, offline = (
            _sql_entry("GONE"),
            _sql_entry("KEPT"),
            _sql_entry("OFFLINE"),
        )
        access = FileEntry("C:/projects/a.mdb")
        self.loaded.update(
            {gone.runtime_locator, kept.runtime_locator, access.runtime_locator}
        )
        state = _FlowState([gone, kept, offline, access])
        handler = self.handler(state)
        self.open_files(
            handler,
            _flow_dialog(
                [
                    gone.with_checked(False),
                    kept,
                    offline.with_checked(False),
                    access.with_checked(False),
                ]
            ),
        )
        self.assertEqual(
            [database_id for database_id, _cb in self.drains], [gone.database_id]
        )
        # The loaded Access entry is not part of the SQL drain.
        self.assertEqual(self.unloads, [])
        self.assertEqual(
            state.saves[1],
            [
                (gone.database_id, True),
                (kept.database_id, True),
                (offline.database_id, False),
                (access.database_id, False),
            ],
        )

    def test_the_interim_checked_state_cannot_be_saved_so_nothing_is_unloaded(self):
        entry = _sql_entry("LOADED")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry], fail_saves={2})
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
        self.assertEqual(
            self.warnings,
            [
                (
                    "Open Files",
                    "The checked SQL state could not be preserved while critical "
                    "writes drain, so no databases were unloaded.",
                )
            ],
        )
        self.assertEqual(self.drains, [])
        self.assertEqual(self.unloads, [])
        self.assertFalse(handler._file_operation_pending)

    def test_all_sql_drains_must_finish_and_the_changes_apply_exactly_once(self):
        first, second = _sql_entry("FIRST"), _sql_entry("SECOND")
        self.loaded.update({first.runtime_locator, second.runtime_locator})
        state = _FlowState([first, second])
        handler = self.handler(state)
        self.open_files(
            handler,
            _flow_dialog([first.with_checked(False), second.with_checked(False)]),
        )
        done = dict(self.drains)
        self.assertEqual(set(done), {first.database_id, second.database_id})
        first_done, second_done = done[first.database_id], done[second.database_id]
        self.assertTrue(handler._file_operation_pending)
        first_done(True, "")
        self.assertEqual(self.unloads, [])
        self.assertTrue(handler._file_operation_pending)
        second_done(True, "")
        self.assertEqual(
            sorted(self.unloads),
            sorted([first.runtime_locator, second.runtime_locator]),
        )
        self.assertFalse(handler._file_operation_pending)
        count = len(self.unloads)
        second_done(True, "")
        first_done(True, "")
        self.assertEqual(len(self.unloads), count)

    def test_a_drain_completion_for_a_superseded_operation_applies_nothing(self):
        entry = _sql_entry("LOADED")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
        ((_database_id, done),) = self.drains
        # A newer file operation started before the drain finished.
        handler._begin_pending_file_operation()
        done(True, "")
        self.assertEqual(self.unloads, [])
        self.assertEqual(state.file_entries[0].is_checked, True)
        self.assertTrue(handler._file_operation_pending)

    def test_one_failed_drain_restores_only_that_entry_and_reports_it(self):
        failing, passing = _sql_entry("FAILING"), _sql_entry("PASSING")
        self.loaded.update({failing.runtime_locator, passing.runtime_locator})
        state = _FlowState([failing, passing])
        handler = self.handler(state)
        self.open_files(
            handler,
            _flow_dialog([failing.with_checked(False), passing.with_checked(False)]),
        )
        done = dict(self.drains)
        done[failing.database_id](False, "")
        done[passing.database_id](True, "")
        self.assertEqual(
            self.warnings,
            [
                (
                    "Unload File",
                    "A critical database setting could not be saved before unload.",
                )
            ],
        )
        self.assertEqual(self.unloads, [passing.runtime_locator])
        self.assertEqual(state.file_entries[0].is_checked, True)
        self.assertEqual(
            state.saves[-1], [(failing.database_id, True), (passing.database_id, False)]
        )
        self.assertEqual(self.capability.disconnected, [passing.database_id])

    def test_a_removed_loaded_sql_entry_whose_drain_fails_is_added_back_checked(self):
        entry = _sql_entry("REMOVED")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([]))
        ((_database_id, done),) = self.drains
        done(False, "writes pending")
        self.assertEqual(self.warnings, [("Unload File", "writes pending")])
        self.assertEqual(state.saves[-1], [(entry.database_id, True)])
        self.assertEqual(self.stops, [])

    def test_the_final_checked_state_save_failure_is_reported_and_stops_loading(self):
        entry = _sql_entry("LOADED")
        added = FileEntry("C:/projects/new.mdb")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry], fail_saves={3})
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry.with_checked(False), added]))
        ((_database_id, done),) = self.drains
        done(True, "")
        self.assertEqual(
            self.warnings,
            [
                (
                    "Open Files",
                    "The final checked database state could not be saved after "
                    "applying Open Files changes.",
                )
            ],
        )
        self.files.load_file.assert_not_called()

    def test_loaded_files_publish_file_opened_and_failed_loads_are_unchecked(self):
        good = FileEntry("C:/projects/good.mdb")
        bad = FileEntry("C:/projects/bad.mdb")
        self.files.load_file.side_effect = lambda locator: (
            FileLoadResultDto(success=True, file_path=locator)
            if locator == good.runtime_locator
            else FileLoadResultDto(success=False, error_message="corrupt")
        )
        state = _FlowState([])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([good, bad]))
        self.assertEqual(
            self.published,
            [(AppEvents.FILE_OPENED, {"file_path": good.runtime_locator})],
        )
        self.assertEqual(self.capability.disconnected, [bad.database_id])
        self.assertEqual(
            state.saves[-1], [(good.database_id, True), (bad.database_id, False)]
        )
        self.assertEqual(
            self.warnings,
            [
                (
                    "Error Loading File",
                    f"Failed to load {bad.descriptor.display_name}:\ncorrupt",
                )
            ],
        )

    def test_a_checked_sql_entry_is_started_through_the_coordinator_not_loaded(self):
        entry = _sql_entry("NEW")
        state = _FlowState([])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([entry]))
        self.files.load_file.assert_not_called()
        self.assertEqual(
            [(database_id, reason) for database_id, reason, _cb in self.stops],
            [(entry.database_id, "reconfigured")],
        )
        self.assertEqual(state.saves, [[(entry.database_id, True)]])

    def test_only_sql_entries_are_restarted_when_their_settings_change(self):
        sql = _sql_entry("SQLDB")
        access = FileEntry("C:/projects/a.mdb")
        state = _FlowState([sql, access])
        handler = self.handler(state)
        self.open_files(
            handler,
            _flow_dialog([sql, access], credential_ids={access.database_id}),
        )
        self.assertEqual(self.stops, [])
        self.open_files(
            handler, _flow_dialog([sql, access], credential_ids={sql.database_id})
        )
        self.assertEqual(
            [(database_id, reason) for database_id, reason, _cb in self.stops],
            [(sql.database_id, "reconfigured")],
        )

    def test_removed_entries_are_cleaned_up_per_backend(self):
        access = FileEntry("C:/projects/a.mdb")
        sql = _sql_entry("REMOVED")
        kept = FileEntry("C:/projects/b.mdb")
        self.registry.register_all([access.descriptor, sql.descriptor])
        state = _FlowState([access, sql, kept])
        handler = self.handler(state)
        self.open_files(handler, _flow_dialog([kept]))
        self.assertIsNone(self.registry.resolve(access.database_id))
        # The SQL entry stays registered until its session has stopped.
        self.assertEqual(self.registry.resolve(sql.database_id), sql.descriptor)
        self.assertEqual(
            [(database_id, reason) for database_id, reason, _cb in self.stops],
            [(sql.database_id, "connection-removed")],
        )

    def test_without_a_registry_removed_access_entries_are_simply_dropped(self):
        access = FileEntry("C:/projects/a.mdb")
        state = _FlowState([access])
        handler = self.handler(state, database_descriptor_registry=None)
        self.open_files(handler, _flow_dialog([]))
        self.assertEqual(self.stops, [])
        self.assertEqual(self.warnings, [])


class FileOperationHandlerSqlRestartRemovalAndUnloadTests(_FlowFixture):
    def test_restart_stops_the_session_directly_when_the_database_is_not_loaded(self):
        loaded, idle = _sql_entry("LOADED"), _sql_entry("IDLE")
        self.loaded.add(loaded.runtime_locator)
        handler = self.handler(_FlowState([loaded, idle]))
        handler._restart_sql_connection(idle.database_id)
        self.assertEqual(self.deferred.flush_for_file.call_count, 0)
        self.assertEqual(self.drains, [])
        self.assertEqual(
            [(database_id, reason) for database_id, reason, _cb in self.stops],
            [(idle.database_id, "reconfigured")],
        )
        handler._restart_sql_connection("not-in-the-state")
        self.assertEqual(len(self.stops), 2)
        self.assertEqual(self.drains, [])

    def test_restart_of_a_loaded_database_flushes_drains_then_stops(self):
        loaded, other = _sql_entry("LOADED"), _sql_entry("OTHER")
        self.loaded.update({loaded.runtime_locator, other.runtime_locator})
        handler = self.handler(_FlowState([other, loaded]))
        handler._restart_sql_connection(loaded.database_id)
        self.assertEqual(self.log, [("flush", loaded.runtime_locator)])
        ((database_id, done),) = self.drains
        self.assertEqual(database_id, loaded.database_id)
        self.assertEqual(self.stops, [])
        done(True, "")
        self.assertEqual(
            [(d, reason) for d, reason, _cb in self.stops],
            [(loaded.database_id, "reconfigured")],
        )
        self.assertEqual(self.warnings, [])

    def test_a_failed_flush_before_a_restart_warns_and_never_drains(self):
        loaded = _sql_entry("LOADED")
        self.loaded.add(loaded.runtime_locator)
        self.deferred.flush_for_file.side_effect = lambda _locator: False
        handler = self.handler(_FlowState([loaded]))
        handler._restart_sql_connection(loaded.database_id)
        self.assertEqual(
            self.warnings,
            [
                (
                    "Reconnect SQL Server Database",
                    "A critical database setting could not be submitted before "
                    "reconnecting.",
                )
            ],
        )
        self.assertEqual((self.drains, self.stops), ([], []))

    def test_a_failed_drain_before_a_restart_warns_and_keeps_the_session(self):
        handler = self.handler(_FlowState([]))
        for message, shown in (
            ("writes pending", "writes pending"),
            ("", "A critical database setting could not be saved before reconnecting."),
        ):
            with self.subTest(message=message):
                self.warnings.clear()
                handler._restart_sql_connection_after_drain("db", False, message)
                self.assertEqual(
                    self.warnings, [("Reconnect SQL Server Database", shown)]
                )
        self.assertEqual(self.stops, [])
        handler._restart_sql_connection_after_drain("db", True, "ignored")
        self.assertEqual(
            [(d, reason) for d, reason, _cb in self.stops], [("db", "reconfigured")]
        )

    def test_a_finished_restart_only_starts_entries_that_are_still_checked_sql(self):
        checked, unchecked = _sql_entry("CHECKED"), _sql_entry(
            "UNCHECKED", checked=False
        )
        access = FileEntry("C:/projects/a.mdb")
        handler = self.handler(_FlowState([unchecked, access, checked]))
        for entry, expected in ((checked, 1), (unchecked, 1), (access, 1)):
            handler._complete_sql_connection_restart(entry.database_id, True, "")
            self.assertEqual(self.collab.start_database.call_count, expected)
        self.collab.start_database.assert_called_once_with(checked.database_id)

    def test_a_removed_session_that_was_re_added_unchecked_is_left_alone(self):
        entry = _sql_entry("READDED")
        credentials = _shared_autospec(ICredentialStore)
        self.registry.register(entry.descriptor)
        handler = self.handler(
            _FlowState([entry.with_checked(False)]), credential_store=credentials
        )
        handler._complete_sql_connection_removal(entry, True, "")
        self.collab.start_database.assert_not_called()
        self.assertEqual(self.registry.resolve(entry.database_id), entry.descriptor)
        credentials.delete_password.assert_not_called()
        self.assertEqual(self.capability.disconnected, [])

    def test_a_removed_session_that_was_re_added_checked_is_restarted(self):
        entry = _sql_entry("READDED")
        handler = self.handler(_FlowState([entry]))
        handler._complete_sql_connection_removal(entry, True, "")
        self.collab.start_database.assert_called_once_with(entry.database_id)

    def test_a_removed_session_is_unregistered_disconnected_and_its_credential_deleted(
        self,
    ):
        entry = _sql_entry("GONE")
        credentials = _shared_autospec(ICredentialStore)
        self.registry.register(entry.descriptor)
        handler = self.handler(_FlowState([]), credential_store=credentials)
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertIsNone(self.registry.resolve(entry.database_id))
        self.assertEqual(self.capability.disconnected, [entry.database_id])
        credentials.delete_password.assert_called_once_with(
            credential_target_for(entry.database_id)
        )
        self.assertEqual(self.warnings, [])

    def test_a_replaced_descriptor_survives_the_removal_of_an_older_entry(self):
        entry = _sql_entry("REPLACED")
        newer = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                SqlServerDatabaseLocation(
                    server="localhost", database="REPLACED", command_timeout_seconds=99
                ),
                schema_version=SQL_SCHEMA_V1.version,
            )
        )
        self.assertEqual(entry.database_id, newer.database_id)
        credentials = _shared_autospec(ICredentialStore)
        self.registry.register(newer.descriptor)
        handler = self.handler(_FlowState([]), credential_store=credentials)
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(self.registry.resolve(entry.database_id), newer.descriptor)
        credentials.delete_password.assert_not_called()

    def test_removal_without_registry_or_credential_store_still_disconnects(self):
        entry = _sql_entry("GONE")
        handler = self.handler(
            _FlowState([]), database_descriptor_registry=None, credential_store=None
        )
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(self.capability.disconnected, [entry.database_id])
        self.assertEqual(self.warnings, [])

    def test_an_unregistered_removed_entry_still_deletes_its_credential(self):
        entry = _sql_entry("GONE")
        credentials = _shared_autospec(ICredentialStore)
        handler = self.handler(_FlowState([]), credential_store=credentials)
        handler._complete_sql_connection_removal(entry, True, "")
        credentials.delete_password.assert_called_once()

    def test_a_credential_that_cannot_be_deleted_is_reported(self):
        entry = _sql_entry("GONE")
        credentials = _shared_autospec(ICredentialStore)
        credentials.delete_password.side_effect = OSError("denied")
        handler = self.handler(_FlowState([]), credential_store=credentials)
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(
            self.warnings,
            [
                (
                    "Remove SQL Server Connection",
                    "The saved database entry was removed, but its Windows "
                    "credential could not be deleted.",
                )
            ],
        )

    def test_unload_of_a_path_that_is_not_an_open_entry_unloads_without_disconnecting(
        self,
    ):
        state = _FlowState([FileEntry("C:/projects/known.mdb")])
        handler = self.handler(state)
        handler.unload_file_path("C:/projects/unknown.mdb")
        self.assertEqual(self.unloads, ["C:/projects/unknown.mdb"])
        self.assertEqual(
            self.log,
            [
                ("flush", "C:/projects/unknown.mdb"),
                ("cancel", "C:/projects/unknown.mdb"),
            ],
        )
        self.assertEqual(self.capability.disconnected, [])
        self.assertEqual(state.saves, [[(state.file_entries[0].database_id, True)]])

    def test_unload_of_an_open_access_entry_unchecks_unloads_and_disconnects(self):
        entry = FileEntry("C:/projects/a.mdb")
        state = _FlowState([entry])
        handler = self.handler(state)
        handler.unload_file_path(entry.runtime_locator)
        self.assertEqual(state.saves, [[(entry.database_id, False)]])
        self.assertEqual(self.unloads, [entry.runtime_locator])
        self.assertEqual(self.capability.disconnected, [entry.database_id])
        self.assertEqual(self.warnings, [])

    def test_unload_without_a_selected_file_reports_nothing_loaded(self):
        self.unload_ok = False
        state = _FlowState([FileEntry("C:/projects/a.mdb")])
        handler = self.handler(state, ui_state_manager=None)
        handler.unload_file()
        self.assertEqual(self.unloads, [None])
        self.assertEqual(
            self.warnings, [("No File Loaded", "There is no file currently loaded.")]
        )
        self.assertEqual(state.saves, [])

    def test_a_drain_that_cannot_even_start_reports_its_error_and_keeps_the_entry(
        self,
    ):
        entry = _sql_entry("LOADED")
        self.loaded.add(entry.runtime_locator)
        self.collab.drain_database_mutations_async.side_effect = RuntimeError(
            "coordinator closed"
        )
        state = _FlowState([entry])
        handler = self.handler(
            state,
            ui_state_manager=SimpleNamespace(selected_file_path=entry.runtime_locator),
        )
        handler.unload_file()
        self.assertEqual(self.warnings, [("Unload File", "coordinator closed")])
        self.assertEqual(self.unloads, [])
        self.assertEqual(state.saves, [])
        self.assertFalse(handler._file_operation_pending)

    def test_a_sql_unload_completion_for_a_superseded_operation_is_ignored(self):
        entry = _sql_entry("LOADED")
        self.loaded.add(entry.runtime_locator)
        state = _FlowState([entry])
        handler = self.handler(state)
        handler.unload_file_path(entry.runtime_locator)
        ((_database_id, done),) = self.drains
        handler._begin_pending_file_operation()
        done(True, "")
        self.assertEqual(self.unloads, [])
        self.assertEqual((state.saves, self.warnings), ([], []))
        self.assertTrue(handler._file_operation_pending)

    def test_a_sql_unload_drain_failure_reports_its_message_or_the_default(self):
        for message, shown in (
            ("writes pending", "writes pending"),
            ("", "A critical database setting could not be saved before unload."),
        ):
            with self.subTest(message=message):
                self.setUp()
                entry = _sql_entry("LOADED")
                self.loaded.add(entry.runtime_locator)
                handler = self.handler(_FlowState([entry]))
                handler.unload_file_path(entry.runtime_locator)
                ((_database_id, done),) = self.drains
                done(False, message)
                self.assertEqual(self.warnings, [("Unload File", shown)])
                self.assertEqual(self.unloads, [])
                self.assertFalse(handler._file_operation_pending)

    def test_a_failed_critical_flush_blocks_a_direct_unload(self):
        entry = FileEntry("C:/projects/a.mdb")
        self.deferred.flush_for_file.side_effect = lambda _locator: False
        state = _FlowState([entry])
        handler = self.handler(state)
        handler.unload_file_path(entry.runtime_locator)
        self.assertEqual((self.unloads, state.saves, self.warnings), ([], [], []))

    def test_an_unloaded_sql_entry_is_detached_locally(self):
        entry = _sql_entry("OFFLINE")
        state = _FlowState([entry])
        handler = self.handler(state)
        handler.unload_file_path(entry.runtime_locator)
        self.assertEqual(self.drains, [])
        self.assertEqual(
            [(d, reason) for d, reason, _cb in self.stops],
            [(entry.database_id, "unchecked")],
        )
        self.assertEqual(self.capability.disconnected, [entry.database_id])
        self.assertEqual(self.log, [("cancel", entry.runtime_locator)])
        self.assertEqual(state.saves, [[(entry.database_id, False)]])


class FileOperationHandlerSqlCreationContractTests(_FlowFixture):
    def creation_handler(self, state=None, **overrides):
        options = dict(
            database_catalog=_shared_autospec(IDatabaseCatalog),
            credential_store=_shared_autospec(ICredentialStore),
            sql_database_creator=_shared_autospec(ISqlDatabaseCreator),
        )
        options.update(overrides)
        return self.handler(state or _FlowState([]), **options)

    def creation_dialog(self, location, *, password="", on_exec=None):
        outcome = SqlDatabasePropertiesResult(location, 1, password)

        class _Properties:
            instances = []

            def __init__(inner, *args, **kwargs):
                inner.args, inner.kwargs = args, kwargs
                inner.cleaned = 0
                inner.deleted = 0
                type(inner).instances.append(inner)

            def exec(inner):
                if on_exec is not None:
                    on_exec(inner)
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(inner):
                return outcome

            def cleanup(inner):
                inner.cleaned += 1

            def deleteLater(inner):
                inner.deleted += 1

        return _Properties

    def location(self, **overrides):
        options = dict(server="localhost", database="CREATED", database_guid="g-1")
        options.update(overrides)
        return SqlServerDatabaseLocation(**options)

    def test_creation_without_permission_does_nothing_and_returns_false(self):
        self.access.is_allowed.return_value = False
        handler = self.creation_handler()
        dialog = self.creation_dialog(self.location())
        with (
            patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
            patch.object(
                handler, "_open_created_sql_database", return_value=True
            ) as opened,
        ):
            self.assertIs(handler.create_sql_database(), False)
        self.assertEqual(dialog.instances, [])
        opened.assert_not_called()
        self.access.is_allowed.assert_called_once_with(Feature.CREATE_DATABASE)
        self.assertEqual(self.warnings, [])
        self.assertFalse(handler.sql_creation_pending)
        self.assertFalse(handler._file_operation_pending)

    def test_each_missing_sql_collaborator_reports_unavailable_support(self):
        for missing in ("database_catalog", "credential_store", "sql_database_creator"):
            with self.subTest(missing=missing):
                self.warnings.clear()
                handler = self.creation_handler(**{missing: None})
                dialog = self.creation_dialog(self.location())
                with (
                    patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
                    patch.object(
                        handler, "_open_created_sql_database", return_value=True
                    ) as opened,
                ):
                    self.assertIs(handler.create_sql_database(), False)
                self.assertEqual(dialog.instances, [])
                opened.assert_not_called()
                self.assertEqual(
                    self.warnings,
                    [
                        (
                            "SQL Server",
                            "SQL Server support is unavailable in this installation.",
                        )
                    ],
                )

    def test_the_creation_dialog_is_given_the_catalog_creator_and_permission_check(
        self,
    ):
        handler = self.creation_handler()
        dialog = self.creation_dialog(self.location())
        with (
            patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
            patch.object(handler, "_open_created_sql_database", return_value=True),
        ):
            handler.create_sql_database()
        (instance,) = dialog.instances
        icon, mode, catalog, creator, parent = instance.args
        self.assertIs(mode, SqlDatabasePropertiesMode.CREATE)
        self.assertIs(catalog, handler._database_catalog)
        self.assertIs(creator, handler._sql_database_creator)
        self.assertIs(parent, self.window)
        self.assertIs(instance.kwargs["schema_change_allowed_fn"](), True)
        self.assertEqual((instance.cleaned, instance.deleted), (1, 1))

    def test_a_destroyed_window_or_dialog_after_the_dialog_means_no_creation(self):
        for label in ("window", "dialog"):
            with self.subTest(label):
                self.setUp()
                handler = self.creation_handler()
                state = handler._file_state_model

                class _Properties(QtWidgets.QDialog):
                    def __init__(inner, *args, **kwargs):
                        super().__init__(None)

                    def exec(inner):
                        delete(self.window if label == "window" else inner)
                        return QtWidgets.QDialog.DialogCode.Accepted

                    def result_data(inner):
                        raise AssertionError("a destroyed dialog must not be read")

                    def cleanup(inner):
                        pass

                with patch(f"{_FOH}.SqlDatabasePropertiesDialog", _Properties):
                    self.assertIs(handler.create_sql_database(), False)
                self.assertEqual(state.saves, [])

    def test_an_already_listed_database_is_refused_without_changes(self):
        location = self.location()
        existing = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(location, schema_version=1)
        )
        state = _FlowState([existing])
        handler = self.creation_handler(state)
        dialog = self.creation_dialog(location, password="secret")
        with patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog):
            self.assertIs(handler.create_sql_database(), False)
        self.assertEqual(
            self.warnings,
            [("SQL Server", "This SQL Server database is already in Open Files.")],
        )
        self.assertEqual(state.saves, [])
        handler._credential_store.write_password.assert_not_called()

    def test_a_password_is_stored_only_for_sql_authentication_with_a_password(self):
        cases = (
            ("sql auth with password", SqlAuthenticationMode.SQL_SERVER, "pw", True),
            ("sql auth without password", SqlAuthenticationMode.SQL_SERVER, "", False),
            ("windows auth with password", SqlAuthenticationMode.WINDOWS, "pw", False),
        )
        for label, mode, password, stored in cases:
            with self.subTest(label):
                self.setUp()
                location = self.location(
                    authentication_mode=mode,
                    username="user" if mode == SqlAuthenticationMode.SQL_SERVER else "",
                )
                state = _FlowState([])
                handler = self.creation_handler(state)
                dialog = self.creation_dialog(location, password=password)
                with (
                    patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
                    patch.object(
                        handler, "_open_created_sql_database", return_value=True
                    ) as opened,
                ):
                    self.assertIs(handler.create_sql_database(), True)
                writes = handler._credential_store.write_password
                if stored:
                    writes.assert_called_once()
                    self.assertEqual(writes.call_args.args[1:], ("user", "pw"))
                else:
                    writes.assert_not_called()
                (saved,) = state.saves
                self.assertEqual(len(saved), 1)
                opened.assert_called_once()

    def test_a_state_save_failure_reloads_state_and_removes_the_written_credential(
        self,
    ):
        location = self.location(
            authentication_mode=SqlAuthenticationMode.SQL_SERVER, username="user"
        )
        state = _FlowState([], fail_saves={1})
        handler = self.creation_handler(state)
        dialog = self.creation_dialog(location, password="pw")
        with (
            patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
            patch.object(handler, "_open_created_sql_database") as opened,
        ):
            self.assertIs(handler.create_sql_database(), False)
        self.assertEqual(state.reloads, 1)
        opened.assert_not_called()
        handler._credential_store.delete_password.assert_called_once()
        self.assertEqual(len(self.warnings), 1)

    def test_creation_registers_the_new_descriptor_before_opening_it(self):
        location = self.location()
        handler = self.creation_handler()
        dialog = self.creation_dialog(location)
        seen = []

        def opened(entry):
            seen.append(self.registry.resolve(entry.database_id))
            return True

        with (
            patch(f"{_FOH}.SqlDatabasePropertiesDialog", dialog),
            patch.object(handler, "_open_created_sql_database", opened),
        ):
            handler.create_sql_database()
        self.assertEqual(
            seen,
            [DatabaseDescriptor.for_sql_server(location, schema_version=1)],
        )

    def open_created(self, handler, entry, *, progress=_RecordingProgress):
        progress.instances = []
        with patch(f"{_FOH}.ProgressDialog", progress):
            return handler._open_created_sql_database(entry)

    def created_entry(self, **location_overrides):
        return FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                self.location(**location_overrides), schema_version=1
            )
        )

    def test_opening_that_cannot_start_reports_the_saved_connection(self):
        entry = self.created_entry()
        self.collab.start_database.return_value = False
        handler = self.creation_handler()
        completed = create_autospec(threading.Event, instance=True)
        completed.wait.return_value = False
        completed.is_set.return_value = False
        with patch(f"{_FOH}.threading.Event", return_value=completed):
            self.assertIs(self.open_created(handler, entry), False)
        completed.wait.assert_not_called()
        self.assertEqual(
            self.warnings,
            [
                (
                    "SQL Server",
                    "The database and connection were saved, but opening could "
                    "not start. Reconnect through Open Files. The server database "
                    "was retained.",
                )
            ],
        )
        self.assertEqual(_RecordingProgress.instances, [])

    def test_the_wait_for_the_first_open_is_never_shorter_than_thirty_seconds(self):
        for connection, command, expected in ((2, 3, 30), (20, 20, 100), (6, 6, 30)):
            with self.subTest(connection=connection, command=command):
                entry = self.created_entry(
                    connection_timeout_seconds=connection,
                    command_timeout_seconds=command,
                )
                handler = self.creation_handler()
                completed = create_autospec(threading.Event, instance=True)
                completed.wait.return_value = False
                completed.is_set.return_value = False
                with patch(f"{_FOH}.threading.Event", return_value=completed):
                    self.open_created(handler, entry)
                completed.wait.assert_called_once_with(expected)

    def test_opening_reports_each_way_the_progress_can_end(self):
        entry = self.created_entry()
        handler = self.creation_handler()
        # 1. the progress dialog itself failed: a generic detail is shown.
        self.collab.start_database.side_effect = lambda *_a, **_k: True
        _RecordingProgress.on_exec = None

        class _FailingProgress(_RecordingProgress):
            def exec(self):
                self.error = RuntimeError("worker died")

        self.assertIs(
            self.open_created(handler, entry, progress=_FailingProgress), False
        )
        message = self.warnings[-1]
        self.assertEqual(message[0], "SQL database not ready")
        self.assertEqual(message[1], _not_ready_message("Opening could not complete."))
        (progress,) = _FailingProgress.instances
        self.assertEqual((progress.cleaned, progress.deleted), (1, 1))
        self.assertEqual(progress.name, entry.descriptor.display_name)
        self.assertEqual(
            progress.kwargs,
            {"parent": self.window, "action_text": "Opening SQL database"},
        )

    def test_a_window_destroyed_during_the_open_wait_returns_false_quietly(self):
        entry = self.created_entry()
        handler = self.creation_handler()

        class _DestroyingProgress(_RecordingProgress):
            def exec(inner):
                delete(self.window)

        self.assertIs(
            self.open_created(handler, entry, progress=_DestroyingProgress), False
        )
        self.assertEqual(self.warnings, [])

    def test_a_ready_database_returns_true_even_if_the_wait_result_is_missing(self):
        entry = self.created_entry()
        handler = self.creation_handler()

        def start(database_id, *, retry_initial_failure, on_initial_open):
            on_initial_open(True, "")
            return True

        self.collab.start_database.side_effect = start

        class _NoResultProgress(_RecordingProgress):
            def exec(inner):
                inner.error = RuntimeError("ignored because the open completed")

        self.assertIs(
            self.open_created(handler, entry, progress=_NoResultProgress), True
        )
        self.assertEqual(self.warnings, [])


class FileOperationHandlerWarningOwnerTests(_FlowFixture):
    """The failure warnings are parented to the owning window (the older tests of these
    paths build the handler with window=None, where a dropped parent is invisible)."""

    def assert_single_warning(self, title, message):
        self.assertEqual(self.warnings, [(title, message)])
        self.assertEqual(self.warning_parents, [self.window])

    def raising_dialog(self, selected):
        class _Dialog(_flow_dialog(selected)):
            def commit_credential_changes(self):
                raise OSError("credential store unavailable")

        return _Dialog

    def test_open_files_state_save_failure_warns_on_the_window(self):
        entry = FileEntry("C:/projects/a.mdb")
        handler = self.handler(_FlowState([entry], fail_saves={1}))
        self.open_files(handler, _flow_dialog([entry.with_checked(False)]))
        self.assert_single_warning(
            "Open Files",
            "The Open Files state could not be saved, so no database changes were "
            "applied.",
        )

    def test_credential_commit_failures_warn_on_the_window(self):
        entry = FileEntry("C:/projects/a.mdb")
        for label, fail_saves, message in (
            (
                "state restored",
                set(),
                "The SQL credentials could not be finalized, so no database changes "
                "were applied.",
            ),
            (
                "state not restored",
                {2},
                "The SQL credentials could not be finalized and the previous Open "
                "Files state could not be restored.",
            ),
        ):
            with self.subTest(label):
                self.setUp()
                state = _FlowState([entry], fail_saves=fail_saves)
                handler = self.handler(state)
                self.open_files(
                    handler, self.raising_dialog([entry.with_checked(False)])
                )
                self.assert_single_warning("Open Files", message)
                self.assertEqual(self.unloads, [])

    def test_a_failed_load_whose_unchecked_state_cannot_be_saved_warns_on_the_window(
        self,
    ):
        bad = FileEntry("C:/projects/bad.mdb")
        self.files.load_file.side_effect = lambda _locator: FileLoadResultDto(
            success=False, error_message="corrupt"
        )
        handler = self.handler(_FlowState([], fail_saves={2}))
        self.open_files(handler, _flow_dialog([bad]))
        self.assertEqual(
            self.warnings[-1],
            (
                "Open Files",
                "A database could not be loaded and its checked state could not be "
                "cleared.",
            ),
        )
        self.assertEqual(self.warning_parents, [self.window] * 2)

    def test_a_failed_restart_close_warns_on_the_window(self):
        checked = _sql_entry("RESTARTED")
        handler = self.handler(_FlowState([checked]))
        handler._complete_sql_connection_restart(checked.database_id, False, "")
        self.assert_single_warning(
            "Reconnect SQL Server Database",
            "The existing SQL collaboration session could not be closed safely.",
        )

    def test_unload_state_save_failures_warn_on_the_window(self):
        entry = FileEntry("C:/projects/a.mdb")
        for label, unload_ok, fail_saves, message in (
            (
                "state not saved",
                True,
                {1},
                "The Open Files state could not be saved, so the database was not "
                "unloaded.",
            ),
            (
                "unload failed and state not restored",
                False,
                {2},
                "The database could not be unloaded and its saved Open Files state "
                "could not be restored.",
            ),
        ):
            with self.subTest(label):
                self.setUp()
                self.unload_ok = unload_ok
                handler = self.handler(_FlowState([entry], fail_saves=fail_saves))
                handler.unload_file_path(entry.runtime_locator)
                self.assert_single_warning("Unload File", message)

    def test_a_second_file_operation_is_refused_with_a_warning_on_the_window(self):
        handler = self.handler(_FlowState([]))
        handler._begin_pending_file_operation()
        handler.open_files()
        self.assert_single_warning(
            "Database Operation Pending",
            "Wait for the current database operation to finish before changing "
            "Open Files again.",
        )


class FileOperationHandlerDialogReleaseTests(_FlowFixture):
    """The modal dialogs are released through nested finally blocks: an error in one
    release step (or in exec itself) must not leak the dialog or its subscription."""

    def release_dialog(self, *, exec_error=None, cleanup_error=None):
        class _Dialog(_flow_dialog([])):
            def exec(inner):
                if exec_error is not None:
                    raise exec_error
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(inner):
                inner.cleaned += 1
                if cleanup_error is not None:
                    raise cleanup_error

        return _Dialog

    def test_open_files_releases_the_dialog_when_exec_cleanup_or_unsubscribe_fails(
        self,
    ):
        for label, exec_error, cleanup_error, unsubscribe_error in (
            ("exec fails", RuntimeError("exec"), None, None),
            ("cleanup fails", None, RuntimeError("cleanup"), None),
            ("unsubscribe fails", None, None, RuntimeError("unsubscribe")),
        ):
            with self.subTest(label):
                access = _shared_autospec(UIAccessManager)
                calls = []
                access.subscribe_access_state_changed.side_effect = (
                    lambda callback: calls.append("subscribe")
                )

                def unsubscribe(_callback, error=unsubscribe_error):
                    calls.append("unsubscribe")
                    if error is not None:
                        raise error

                access.unsubscribe_access_state_changed.side_effect = unsubscribe
                dialog_class = self.release_dialog(
                    exec_error=exec_error, cleanup_error=cleanup_error
                )
                handler = self.handler(
                    _FlowState([]),
                    ui_access_manager=access,
                    database_maintenance_service=object(),
                )
                with self.assertRaises(RuntimeError):
                    self.open_files(handler, dialog_class)
                (dialog,) = dialog_class.instances
                self.assertEqual(calls, ["subscribe", "unsubscribe"])
                self.assertEqual((dialog.cleaned, dialog.deleted), (1, 1))
                dialog_class.instances.clear()

    def test_creation_releases_the_dialog_when_exec_or_cleanup_fails(self):
        for label, exec_error, cleanup_error in (
            ("exec fails", RuntimeError("exec"), None),
            ("cleanup fails", None, RuntimeError("cleanup")),
        ):
            with self.subTest(label):
                creation = FileOperationHandlerSqlCreationContractTests
                handler = creation.creation_handler(self)
                dialog_class = creation.creation_dialog(
                    self, SqlServerDatabaseLocation(server="s", database="d")
                )

                class _Failing(dialog_class):
                    def exec(inner):
                        if exec_error is not None:
                            raise exec_error
                        return QtWidgets.QDialog.DialogCode.Rejected

                    def cleanup(inner):
                        inner.cleaned += 1
                        if cleanup_error is not None:
                            raise cleanup_error

                with patch(f"{_FOH}.SqlDatabasePropertiesDialog", _Failing):
                    with self.assertRaises(RuntimeError):
                        handler.create_sql_database()
                (instance,) = dialog_class.instances
                self.assertEqual((instance.cleaned, instance.deleted), (1, 1))
                self.assertFalse(handler.sql_creation_pending)
                self.assertFalse(handler._file_operation_pending)


class FileOperationHandlerSqlCreationSecretAndIdentityTests(_FlowFixture):
    """Real file_state.json persistence: SQL passwords stay in the credential store only
    and a database is identified by its DatabaseGuid, not by its server or name."""

    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "file_state.json"
        self.state = FileStateAggregate(JsonFileStateRepository(self.state_path))
        self.store = _database_foundation_support__CredentialStore()
        self.secret = "Sentinel-" + secrets.token_urlsafe(24)

    def location(self, **overrides):
        options = dict(
            server="localhost",
            database="CREATED",
            database_guid="00000000-0000-0000-0000-00000000aaa1",
            authentication_mode=SqlAuthenticationMode.SQL_SERVER,
            username="runtime-user",
        )
        options.update(overrides)
        return SqlServerDatabaseLocation(**options)

    def create(self, location, state=None, store=None):
        handler = self.handler(
            state or self.state,
            database_catalog=_shared_autospec(IDatabaseCatalog),
            credential_store=store or self.store,
            sql_database_creator=_shared_autospec(ISqlDatabaseCreator),
        )
        outcome = SqlDatabasePropertiesResult(location, 1, self.secret)

        class _Properties:
            def __init__(inner, *args, **kwargs):
                pass

            def exec(inner):
                return QtWidgets.QDialog.DialogCode.Accepted

            def result_data(inner):
                return outcome

            def cleanup(inner):
                pass

            def deleteLater(inner):
                pass

        with (
            patch(f"{_FOH}.SqlDatabasePropertiesDialog", _Properties),
            patch.object(handler, "_open_created_sql_database", return_value=True),
        ):
            return handler.create_sql_database()

    def test_the_saved_state_file_holds_the_descriptor_but_never_the_password(self):
        location = self.location()
        self.assertIs(self.create(location), True)
        text = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn(self.secret, text)
        self.assertNotIn("password", text.lower())
        saved = json.loads(text)
        (entry,) = saved["database_entries"]
        self.assertEqual(
            entry["descriptor"]["location"]["database_guid"], location.database_guid
        )
        self.assertEqual(entry["descriptor"]["location"]["username"], "runtime-user")
        self.assertIs(entry["is_checked"], True)
        (stored,) = self.state.file_entries
        self.assertEqual(
            self.store.passwords,
            {credential_target_for(stored.database_id): ("runtime-user", self.secret)},
        )
        self.assertEqual(self.warnings, [])

    def test_failure_warnings_never_contain_the_password(self):
        class _LeakyStore(_database_foundation_support__CredentialStore):
            def __init__(inner, secret, fail_write, fail_delete):
                super().__init__()
                inner.secret = secret
                inner.fail_write = fail_write
                inner.fail_delete = fail_delete

            def write_password(inner, target, username, password):
                if inner.fail_write:
                    raise OSError(f"cannot store {inner.secret}")
                super().write_password(target, username, password)

            def delete_password(inner, target):
                if inner.fail_delete:
                    raise OSError(f"cannot delete {inner.secret}")
                super().delete_password(target)

        for label, fail_write, fail_saves, fail_delete in (
            ("credential write fails", True, set(), False),
            ("state save fails", False, {1}, False),
            ("state save fails and cleanup fails", False, {1}, True),
        ):
            with self.subTest(label):
                self.setUp()
                store = _LeakyStore(self.secret, fail_write, fail_delete)
                state = _FlowState([], fail_saves=fail_saves)
                self.assertIs(self.create(self.location(), state, store), False)
                (warning,) = self.warnings
                self.assertEqual(warning[0], "SQL Server")
                self.assertNotIn(self.secret, " ".join(warning))
                self.assertEqual(state.file_entries, [])

    def test_the_same_database_guid_is_one_database_whatever_its_server_or_name(self):
        self.assertIs(self.create(self.location()), True)
        before = self.state_path.read_text(encoding="utf-8")
        self.assertIs(
            self.create(self.location(server="other-host", database="Renamed")), False
        )
        self.assertEqual(
            self.warnings,
            [("SQL Server", "This SQL Server database is already in Open Files.")],
        )
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), before)

    def test_a_new_database_guid_with_the_same_name_is_a_new_database(self):
        self.assertIs(self.create(self.location()), True)
        recreated = self.location(database_guid="00000000-0000-0000-0000-00000000aaa2")
        self.assertIs(self.create(recreated), True)
        self.assertEqual(self.warnings, [])
        entries = self.state.file_entries
        self.assertEqual(len(entries), 2)
        self.assertNotEqual(entries[0].database_id, entries[1].database_id)
        self.assertEqual(
            sorted(self.store.passwords),
            sorted(credential_target_for(entry.database_id) for entry in entries),
        )
