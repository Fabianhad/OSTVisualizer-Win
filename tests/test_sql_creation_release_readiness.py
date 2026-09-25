"""Deterministic release-boundary checks; no live databases or timed waits."""

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.domain.aggregates.file_state_aggregate import FileStateAggregate
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    validate_sql_database_creation_name,
)
from ost_visualizer.domain.entities.file_state import FileEntry, FileState
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialogResult,
)
from ost_visualizer.presentation.dialogs.sql_database_dialog import (
    SqlDatabasePropertiesDialog,
    SqlDatabasePropertiesMode,
    SqlDatabasePropertiesResult,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)
from PySide6 import QtWidgets
from tests.test_sql_creation_handoff import (
    _CLIENT,
    _CREATOR,
    _GUID,
    _RUNTIME,
    _Connections,
    _error,
    _snapshot,
)


class _ImmediateProgress:
    def __init__(self, _name, task, **_kwargs):
        self.task = task
        self.result = None
        self.error = None

    def exec(self):
        self.result = self.task()

    def cleanup(self):
        self.task = None

    def deleteLater(self):
        pass


class CreationReleaseBoundaryTests(unittest.TestCase):
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

        class _TimeoutThenHealthy(_ImmediateProgress):
            def exec(self):
                super().exec()
                callback[0](True, "")

        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.threading.Event",
            return_value=completed,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog",
            _TimeoutThenHealthy,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            self.assertTrue(handler._open_created_sql_database(entry))
        warning.assert_not_called()
        completed.wait.assert_called_once_with(75)
        handler._sql_collaboration.stop_database_async.assert_not_called()
        handler._sql_collaboration.start_database.assert_called_once()

    def test_properties_cleanup_while_setup_completes_cannot_accept_result(self):
        creator = Mock()
        creator.create_database_for_client.return_value = SqlDatabaseCreationResult(
            self._entry().descriptor.sql_location, 1
        )
        properties = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        self.addCleanup(properties.deleteLater)
        self.addCleanup(properties.cleanup)
        properties.server_input.setText(_CREATOR.server)
        properties.database_name_input.setText("Created")
        properties.sql_auth_radio.setChecked(True)
        properties.username_input.setText(_RUNTIME.username)
        properties.password_input.setText(_RUNTIME.password)

        class _CleanedOwner(_ImmediateProgress):
            def exec(self):
                super().exec()
                properties.cleanup()

        with patch.object(
            properties,
            "_request_creator_connection",
            return_value=SqlConnectionDialogResult(_CREATOR, "creator-test-secret"),
        ), patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.ProgressDialog",
            _CleanedOwner,
        ):
            properties._accept_if_valid()
        creator.create_database_for_client.assert_called_once()
        self.assertIsNone(properties.result_data())
        self.assertNotEqual(properties.result(), QtWidgets.QDialog.DialogCode.Accepted)

    def test_close_request_during_creation_keeps_dialog_owned(self):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            Mock(),
        )
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(dialog.cleanup)
        dialog.show()
        dialog._creation_in_progress = True
        self.assertFalse(dialog.close())
        self.assertTrue(dialog.isVisible())
        self.assertIsNone(dialog.result_data())
        dialog._creation_in_progress = False
        dialog.reject()
        self.assertFalse(dialog.isVisible())

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
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.threading.Event",
            return_value=completed,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.ProgressDialog",
            _ImmediateProgress,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
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
                with patch(
                    "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                    return_value=dialog,
                ), patch(
                    "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
                ) as warning:
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
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
            return_value=dialog,
        ), patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
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


class CreationServerBoundaryTests(unittest.TestCase):
    def _connections(self):
        return _Connections(
            [(1, b"creator-sid", "test-server")],
            [(_CLIENT.login_name, _CLIENT.sid, _CLIENT.server_name, "S"), (0, 0, 0)],
            [(0,)],
            [(0,), (_GUID,), (_CLIENT.sid,)],
            [(_GUID,), (_CLIENT.sid, _CLIENT.login_name, 0, 0), (0, 0, 0), _snapshot()],
        )

    def test_each_server_failure_stops_before_subsequent_stage(self):
        for boundary, requests in (
            ("creator_auth", 1),
            ("runtime_auth", 2),
            ("create", 3),
            ("schema", 3),
            ("provision", 4),
            ("verify", 5),
        ):
            with self.subTest(boundary=boundary):
                connections = self._connections()
                if boundary == "creator_auth":
                    connections.leases[0].rows[0] = _error()
                elif boundary == "runtime_auth":
                    connections.leases[1].rows[0] = _error()
                elif boundary == "create":
                    execute = connections.leases[2].execute

                    def fail_create(statement, *parameters):
                        execute(statement, *parameters)
                        if statement.startswith("CREATE DATABASE "):
                            raise _error()

                    connections.leases[2].execute = fail_create
                elif boundary == "provision":
                    connections.leases[3].rows[2] = _error()
                elif boundary == "verify":
                    connections.leases[4].rows[0] = None
                creator = SqlDatabaseCreator(connections)
                initialized = SqlDatabaseCreationResult(
                    replace(_CREATOR, database="Created", database_guid=_GUID), 1
                )
                with patch.object(
                    creator, "initialize_blank_database", return_value=initialized
                ) as initialize:
                    if boundary == "schema":
                        initialize.side_effect = _error()
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        creator.create_database_for_client(
                            _CREATOR,
                            "Created",
                            "creator-test-secret",
                            runtime_credentials=_RUNTIME,
                            application_version="test",
                        )
                self.assertEqual(len(connections.requests), requests)
                sql = " ".join(
                    statement
                    for lease in connections.leases
                    for statement, _params in lease.statements
                )
                self.assertNotIn("DROP DATABASE", sql)
                if boundary in ("creator_auth", "runtime_auth", "create"):
                    initialize.assert_not_called()
                elif boundary == "schema":
                    self.assertIn("container was created", str(raised.exception))
                else:
                    self.assertIn("database was retained", str(raised.exception))
                    self.assertIn("no connection was saved", str(raised.exception))
                    self.assertIn("Open Files", str(raised.exception))

    def test_all_authentication_pairs_keep_selected_transport_and_runtime_identity(
        self,
    ):
        for creator_windows, runtime_windows in (
            (True, False),
            (False, True),
            (False, False),
        ):
            for encrypt, trust in (
                (True, True),
                (True, False),
                (False, False),
                (False, True),
            ):
                with self.subTest(
                    creator_windows=creator_windows,
                    runtime_windows=runtime_windows,
                    encrypt=encrypt,
                    trust=trust,
                ):
                    connections = self._connections()
                    location = replace(
                        _CREATOR,
                        encrypt=encrypt,
                        trust_server_certificate=trust,
                        authentication_mode=(
                            SqlAuthenticationMode.WINDOWS
                            if creator_windows
                            else SqlAuthenticationMode.SQL_SERVER
                        ),
                        username="" if creator_windows else _CREATOR.username,
                    )
                    credentials = (
                        SqlDatabaseRuntimeCredentials() if runtime_windows else _RUNTIME
                    )
                    creator_password = "" if creator_windows else "creator-test-secret"
                    if runtime_windows:
                        connections.leases[1].rows[0] = (
                            _CLIENT.login_name,
                            _CLIENT.sid,
                            _CLIENT.server_name,
                            "U",
                        )
                    creator = SqlDatabaseCreator(connections)
                    with patch.object(
                        creator,
                        "initialize_blank_database",
                        return_value=SqlDatabaseCreationResult(
                            replace(location, database="Created", database_guid=_GUID),
                            1,
                        ),
                    ):
                        result = creator.create_database_for_client(
                            location,
                            "Created",
                            creator_password,
                            runtime_credentials=credentials,
                            application_version="test",
                        )
                    self.assertEqual(
                        result.location.authentication_mode,
                        credentials.authentication_mode,
                    )
                    self.assertEqual(result.location.username, credentials.username)
                    for index, (request, _auto) in enumerate(connections.requests):
                        expected_password = (
                            credentials.password
                            if index in (1, 4)
                            else creator_password
                        )
                        self.assertEqual(request.password, expected_password)
                        self.assertEqual(
                            (
                                request.location.server,
                                request.location.encrypt,
                                request.location.trust_server_certificate,
                                request.location.connection_timeout_seconds,
                                request.location.command_timeout_seconds,
                            ),
                            (location.server, encrypt, trust, 7, 17),
                        )
                    payload = json.dumps(
                        DatabaseDescriptor.for_sql_server(
                            result.location, schema_version=1
                        ).to_dict()
                    )
                    self.assertNotIn("creator-test-secret", payload)
                    self.assertNotIn(_RUNTIME.password, payload)

    def test_names_and_existing_database_never_truncate_or_reinitialize(self):
        for name in (
            "a" * 75,
            "a" + "\U0001f600" * 37,
            "Name with spaces",
            "Name]with[brackets",
        ):
            validate_sql_database_creation_name(name)
            connections = _Connections([(1,)])
            creator = SqlDatabaseCreator(connections)
            with patch.object(creator, "initialize_blank_database") as initialize:
                with self.assertRaisesRegex(SqlInfrastructureError, "already exists"):
                    creator.create_database(
                        _CREATOR,
                        name,
                        "creator-test-secret",
                        application_version="test",
                    )
                initialize.assert_not_called()
            self.assertEqual(connections.leases[0].statements[0][1], (name,))
            self.assertEqual(len(connections.leases[0].statements), 1)
        for name in (
            "a" * 76,
            "aa" + "\U0001f600" * 37,
            "",
            "master",
            "MODEL",
            "msdb",
            "tempdb",
        ):
            with self.assertRaises(ValueError):
                validate_sql_database_creation_name(name)
