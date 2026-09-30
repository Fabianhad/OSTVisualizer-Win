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
import tempfile
from pathlib import Path
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
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler as StartupFileOperationHandler,
)
from shiboken6 import delete
from tests.helpers.startup_database import (
    StartupFileOperationHandler as _startup_database_StartupFileOperationHandler,
    _OpenFilesDialogStub as _startup_database__OpenFilesDialogStub,
)

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
        unload_calls = []
        updates = []
        entries = [FileEntry("a.mdb", is_checked=True)]
        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=entries,
                update_entries=lambda next_entries: updates.append(next_entries),
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
        handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, ["a.mdb"])
        self.assertEqual(deferred.cancel_calls, ["a.mdb"])
        self.assertEqual(len(updates), 1)

    def test_project_unload_stops_when_deferred_flush_fails(self):
        deferred = RecordingDeferredPersistence()
        deferred.flush_result = False
        unload_calls = []
        handler = WorkspaceFileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=SimpleNamespace(
                file_entries=[],
                update_entries=lambda _: None,
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
        handler.unload_file()
        self.assertEqual(deferred.flush_calls, ["a.mdb"])
        self.assertEqual(unload_calls, [])

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
        warning.assert_called_once()

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
        ):
            handler.unload_file()
        self.assertEqual(len(updates), 2)
        self.assertFalse(updates[0][0].is_checked)
        self.assertTrue(updates[1][0].is_checked)
        self.assertTrue(state.file_entries[0].is_checked)
        self.assertEqual(deferred.cancel_calls, [])


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
            unload_file_fn=lambda _locator: False,
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
        self.assertEqual(updates[-1], [])
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
            ),
        ):
            self.assertTrue(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            target = credential_target_for(state.file_entries[0].database_id)
            self.assertEqual(store.passwords[target], ("test-user", password))
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(len(state.file_entries), 1)
            _PropertiesDialog.accepted = False
            empty_state = _State()
            handler._file_state_model = empty_state
            self.assertFalse(handler.create_sql_database())
            self.assertEqual(empty_state.file_entries, [])


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
        handler._database_catalog = Mock()
        handler._credential_store = Mock()
        handler._sql_database_creator = Mock()
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
        ):
            self.assertFalse(handler._create_sql_database())
        connection_factory.assert_not_called()
        properties_factory.assert_called_once()
        self.assertEqual(
            properties_factory.call_args.args[1], SqlDatabasePropertiesMode.CREATE
        )
        self.assertNotIn("connection", properties_factory.call_args.kwargs)
        properties_dialog.exec.assert_called_once()
        properties_dialog.cleanup.assert_called_once()
        handler._sql_database_creator.create_database_for_client.assert_not_called()
        handler._credential_store.write_password.assert_not_called()

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
                self.assertIn("Reconnect through Open Files", warning.call_args.args[2])
                self.assertIn("retained", warning.call_args.args[2])
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
        handler._sql_collaboration = Mock()
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
        handler._sql_collaboration = Mock()
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
            self.assertIn("retained", warning.call_args.args[2])
            callbacks[0](True, "")
            warning.assert_called_once()
        self.assertEqual(handler._file_state_model.file_entries, [entry])
        self.assertTrue(entry.is_checked)
        handler._sql_collaboration.start_database.assert_called_once()
        handler._sql_collaboration.stop_database_async.assert_not_called()
        handler._sql_collaboration.stop_database.assert_not_called()

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
                handler._database_catalog = Mock()
                handler._sql_database_creator = Mock()
                handler._credential_store = Mock()
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
                self.assertIn(
                    "server database was not deleted", warning.call_args.args[2]
                )
                if boundary != "credential":
                    handler._credential_store.delete_password.assert_called_once()
                if boundary == "credential_cleanup":
                    self.assertIn(
                        "Windows Credential Manager", warning.call_args.args[2]
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
        handler._database_catalog = Mock()
        handler._sql_database_creator = Mock()
        handler._credential_store = Mock()
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
            ),
        ):
            self.assertFalse(handler._create_sql_database())
            self.assertFalse(handler._create_sql_database())
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
        handler._sql_collaboration = Mock()
        stopped = []
        handler._sql_collaboration.stop_database_async.side_effect = (
            lambda _id, _reason, callback: stopped.append(callback)
        )
        handler._restart_sql_connection(entry.database_id)
        handler._sql_collaboration.start_database.assert_not_called()
        stopped[0](True, "")
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
        self.assertEqual(received_models, [self.model])


class StartupDatabaseRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_open_files_return_tolerates_destroyed_parent(self):
        window = QtWidgets.QDialog()

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
                return QtWidgets.QDialog.DialogCode.Rejected

            def cleanup(self):
                pass

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
        drain_callbacks[0][1](True, "")
        self.assertEqual(unloads, [descriptor.database_id])
        self.assertEqual(cancelled, [descriptor.database_id])

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
        warning.assert_called_once()
        drain_callbacks[0](True, "")
        self.assertEqual(unloads, [descriptor.database_id])
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
        self.assertEqual(state.file_entries, [checked])
        self.assertEqual(warning.call_count, 2)
        self.assertIn("checked state could not be cleared", warning.call_args.args[2])

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
        handler._file_state_model = SimpleNamespace(
            file_entries=[entry.with_checked(False)]
        )
        handler._sql_collaboration = SimpleNamespace(start_database=starts.append)
        handler._database_descriptor_registry = None
        handler._credential_store = None
        handler._database_capability_service = None
        handler._complete_sql_connection_removal(entry, True, "")
        self.assertEqual(starts, [])
