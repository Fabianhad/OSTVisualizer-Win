import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from ost_visualizer.application.interfaces.i_sql_database_creator import (
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

    def test_actual_dialog_registers_selected_runtime_and_reopens_with_its_credentials(
        self,
    ):
        for windows, fail in ((False, False), (True, False), (False, True)):
            with self.subTest(windows=windows, fail=fail):
                creator = Mock()
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

                state = SimpleNamespace(file_entries=[])

                def update_entries(entries):
                    state.file_entries = list(entries)

                state.update_entries = update_entries
                registry = DatabaseDescriptorRegistry()
                credentials = Mock()
                credentials.read_password.return_value = (
                    _creation_handoff_support__RUNTIME.password
                )
                starts = []
                factory = SqlDescriptorConnectionFactory(registry, credentials)
                handler = with_workspace_state(FileOperationHandler)(
                    window=None,
                    icon_provider=SimpleNamespace(set_window_icon=lambda _widget: None),
                    event_bus=SimpleNamespace(publish=lambda *_args, **_kwargs: None),
                    file_state_model=state,
                    cleanup_deleted_files_use_case=None,
                    file_loading_service=SimpleNamespace(
                        is_loaded=lambda _locator: False
                    ),
                    working_directory_service=None,
                    unload_file_fn=lambda _locator: False,
                    deferred_persistence_manager=None,
                    ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
                    sql_collaboration_coordinator=SimpleNamespace(
                        stop_database_async=lambda _id, _reason, callback: callback(
                            True, ""
                        ),
                        start_database=lambda database_id, **kwargs: (
                            starts.append(
                                factory.request(database_id, read_only=False)
                            ),
                            kwargs["on_initial_open"](True, ""),
                            True,
                        )[-1],
                    ),
                    database_catalog=Mock(),
                    credential_store=credentials,
                    database_descriptor_registry=registry,
                    sql_database_creator=creator,
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
                    credentials.write_password.assert_not_called()
                    continue
                self.assertEqual(len(state.file_entries), 1)
                self.assertEqual(starts[0].location, runtime_location)
                self.assertEqual(
                    starts[0].password,
                    "" if windows else _creation_handoff_support__RUNTIME.password,
                )
                if windows:
                    credentials.write_password.assert_not_called()
                    credentials.read_password.assert_not_called()
                else:
                    credentials.write_password.assert_called_once()
                    self.assertEqual(
                        credentials.write_password.call_args.args[1:],
                        (
                            _creation_handoff_support__RUNTIME.username,
                            _creation_handoff_support__RUNTIME.password,
                        ),
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
