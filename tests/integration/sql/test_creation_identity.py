import json
import os
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.interfaces.i_database_catalog import IDatabaseCatalog
from ost_visualizer.application.interfaces.i_sql_database_creator import (
    ISqlDatabaseCreator,
    SqlDatabaseCreationResult,
    SqlDatabaseRuntimeCredentials,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    SqlServerDatabaseLocation,
    validate_sql_database_creation_name,
    validate_sql_database_name,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.descriptor_connection import (
    SqlDescriptorConnectionFactory,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
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
from PySide6 import QtCore, QtWidgets
from tests.helpers.workspace_state import with_workspace_state
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _Connections as _creation_handoff_support__Connections,
    _GUID as _creation_handoff_support__GUID,
    _Lease as _creation_handoff_support__Lease,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _error as _creation_handoff_support__error,
)


class _RecordingCredentialStore:
    """In-memory credential store that records every write and read."""

    def __init__(self):
        self.passwords = {}
        self.writes = []
        self.reads = []

    def read_password(self, target):
        self.reads.append(target)
        return self.passwords.get(target)

    def write_password(self, target, username, password):
        self.writes.append((target, username, password))
        self.passwords[target] = password

    def delete_password(self, target):
        self.passwords.pop(target, None)


class CreationIdentityCreationDialogIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _dialog(self, creator, *, own_cleanup=True, prompt_creator=False):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            None,
            creator,
            schema_change_allowed_fn=lambda: True,
        )
        if own_cleanup:
            self.addCleanup(dialog.deleteLater)
            self.addCleanup(dialog.cleanup)
        dialog.server_input.setText(_creation_handoff_support__CREATOR.server)
        dialog.database_name_input.setText("Test database")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText(_creation_handoff_support__RUNTIME.username)
        dialog.password_input.setText(_creation_handoff_support__RUNTIME.password)
        if not prompt_creator:
            prompt = patch.object(
                dialog,
                "_request_creator_connection",
                return_value=(
                    SqlConnectionDialogResult(
                        _creation_handoff_support__CREATOR, "creator-test-secret"
                    )
                ),
            )
            prompt.start()
            self.addCleanup(prompt.stop)
        return dialog

    def test_windows_creator_cannot_become_its_own_restricted_runtime_user(self):
        connections = _creation_handoff_support__Connections(
            [(1, b"windows-sid", "test-server")],
            [("DOMAIN\\user", b"windows-sid", "test-server", "U"), (0, 0, 0)],
        )
        dialog = self._dialog(SqlDatabaseCreator(connections))
        dialog.windows_auth_radio.setChecked(True)
        dialog._request_creator_connection.return_value = SqlConnectionDialogResult(
            replace(
                _creation_handoff_support__CREATOR,
                authentication_mode=SqlAuthenticationMode.WINDOWS,
                username="",
            )
        )
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(len(connections.requests), 2)
        for request, _autocommit in connections.requests:
            self.assertEqual(
                request.location.authentication_mode, SqlAuthenticationMode.WINDOWS
            )
            self.assertEqual(request.password, "")
        self.assertIn("different logins", warning.call_args.args[2])
        self.assertFalse(
            any(
                statement.lstrip().startswith("CREATE DATABASE ")
                for lease in connections.leases
                for statement, _parameters in lease.statements
            )
        )

    def test_runtime_login_on_a_different_server_than_the_creator_is_refused(self):
        connections = _creation_handoff_support__Connections(
            [(1, b"creator-sid", "test-server")],
            [("client", b"client-sid", "other-server", "S"), (0, 0, 0)],
        )
        dialog = self._dialog(SqlDatabaseCreator(connections))
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(len(connections.requests), 2)
        self.assertEqual(len(warning.call_args_list), 1)
        self.assertIn("same SQL Server", warning.call_args.args[2])
        self.assertFalse(
            any(
                statement.lstrip().startswith("CREATE DATABASE ")
                for lease in connections.leases
                for statement, _parameters in lease.statements
            )
        )

    def _handler(self, creator, *, request_on_start=True):
        state = SimpleNamespace(file_entries=[])

        def update_entries(entries):
            state.file_entries = list(entries)

        state.update_entries = update_entries
        registry = DatabaseDescriptorRegistry()
        credentials = _RecordingCredentialStore()
        starts = []
        factory = SqlDescriptorConnectionFactory(registry, credentials)
        handler = with_workspace_state(FileOperationHandler)(
            window=None,
            icon_provider=SimpleNamespace(set_window_icon=lambda _widget: None),
            event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
            file_state_model=state,
            cleanup_deleted_files_use_case=None,
            file_loading_service=SimpleNamespace(is_loaded=lambda _locator: False),
            working_directory_service=None,
            unload_file_fn=lambda _locator: False,
            deferred_persistence_manager=None,
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda _id, _reason, callback: callback(True, ""),
                start_database=lambda database_id, **kwargs: (
                    starts.append(
                        factory.request(database_id, read_only=False)
                        if request_on_start
                        else database_id
                    ),
                    kwargs["on_initial_open"](True, ""),
                    True,
                )[-1],
            ),
            database_catalog=create_autospec(IDatabaseCatalog, instance=True),
            credential_store=credentials,
            database_descriptor_registry=registry,
            sql_database_creator=creator,
        )
        return handler, state, registry, credentials, starts, factory

    def test_a_password_is_saved_only_for_sql_authentication_with_a_password(self):
        runtime = replace(
            _creation_handoff_support__CREATOR,
            database="Test database",
            database_guid=_creation_handoff_support__GUID,
            username="client",
        )
        cases = (
            (
                "windows login with a password",
                SqlAuthenticationMode.WINDOWS,
                "leaked",
                False,
            ),
            (
                "sql login with a password",
                SqlAuthenticationMode.SQL_SERVER,
                "secret",
                True,
            ),
            (
                "sql login without a password",
                SqlAuthenticationMode.SQL_SERVER,
                "",
                False,
            ),
        )
        for label, mode, password, saved in cases:
            with self.subTest(label):
                creator = create_autospec(ISqlDatabaseCreator, instance=True)
                dialog = self._dialog(creator, own_cleanup=False)
                handler, state, _registry, credentials, starts, _factory = (
                    self._handler(creator, request_on_start=False)
                )
                result = SqlDatabasePropertiesResult(
                    replace(runtime, authentication_mode=mode), 1, password
                )
                with (
                    patch(
                        "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                        return_value=dialog,
                    ),
                    patch.object(
                        dialog,
                        "exec",
                        return_value=QtWidgets.QDialog.DialogCode.Accepted,
                    ),
                    patch.object(dialog, "result_data", return_value=result),
                ):
                    self.assertTrue(handler.create_sql_database())
                self.assertEqual(len(state.file_entries), 1)
                self.assertEqual(len(starts), 1)
                database_id = state.file_entries[0].database_id
                self.assertEqual(
                    credentials.writes,
                    (
                        [(f"OSTVisualizer/SqlServer/{database_id}", "client", password)]
                        if saved
                        else []
                    ),
                )

    def test_actual_dialog_registers_selected_runtime_and_reopens_with_its_credentials(
        self,
    ):
        for windows, fail in ((False, False), (True, False), (False, True)):
            with self.subTest(windows=windows, fail=fail):
                creator = create_autospec(ISqlDatabaseCreator, instance=True)
                dialog = self._dialog(creator, own_cleanup=False)
                if windows:
                    dialog.windows_auth_radio.setChecked(True)
                connection = dialog._connection_details()
                runtime_location = replace(
                    connection.location,
                    database="Test database",
                    database_guid=_creation_handoff_support__GUID,
                )
                if fail:
                    creator.create_database_for_client.side_effect = (
                        _creation_handoff_support__error()
                    )
                else:
                    creator.create_database_for_client.return_value = (
                        SqlDatabaseCreationResult(runtime_location, 1)
                    )

                # The handler owns this dialog's cleanup for this test.
                def execute_dialog():
                    dialog._accept_if_valid()
                    return dialog.result()

                handler, state, registry, credentials, starts, factory = self._handler(
                    creator
                )
                with patch(
                    "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
                    return_value=dialog,
                ) as properties_factory, patch.object(
                    dialog, "exec", side_effect=execute_dialog
                ), patch(
                    "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
                ):
                    self.assertEqual(handler.create_sql_database(), not fail)
                self.assertNotIn("connection", properties_factory.call_args.kwargs)
                if fail:
                    self.assertEqual(state.file_entries, [])
                    self.assertEqual(starts, [])
                    self.assertEqual(credentials.writes, [])
                    continue
                self.assertEqual(len(state.file_entries), 1)
                self.assertEqual(starts[0].location, runtime_location)
                self.assertEqual(
                    starts[0].password,
                    "" if windows else _creation_handoff_support__RUNTIME.password,
                )
                database_id = state.file_entries[0].database_id
                if windows:
                    self.assertEqual(credentials.writes, [])
                    self.assertEqual(credentials.reads, [])
                else:
                    # The reopen password comes from the credential the handler
                    # saved under the database's own target, not from a fixture.
                    self.assertEqual(
                        credentials.writes,
                        [
                            (
                                f"OSTVisualizer/SqlServer/{database_id}",
                                _creation_handoff_support__RUNTIME.username,
                                _creation_handoff_support__RUNTIME.password,
                            )
                        ],
                    )
                args, kwargs = creator.create_database_for_client.call_args
                self.assertEqual(
                    args[0],
                    replace(
                        connection.location,
                        authentication_mode=_creation_handoff_support__CREATOR.authentication_mode,
                        username=_creation_handoff_support__CREATOR.username,
                    ),
                )
                self.assertEqual(args[2], "creator-test-secret")
                self.assertEqual(
                    kwargs["runtime_credentials"],
                    (
                        SqlDatabaseRuntimeCredentials()
                        if windows
                        else _creation_handoff_support__RUNTIME
                    ),
                )
                reopened = factory.request(
                    state.file_entries[0].database_id, read_only=False
                )
                self.assertEqual(reopened, starts[0])
                payload = json.dumps(state.file_entries[0].descriptor.to_dict())
                self.assertNotIn("creator-test-secret", payload)
                self.assertNotIn(_creation_handoff_support__RUNTIME.password, payload)
                self.assertNotIn("setup-admin", payload)
