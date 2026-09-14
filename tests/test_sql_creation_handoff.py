import json
import re
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pyodbc
from PySide6 import QtCore, QtWidgets
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
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    SQL_CLIENT_PROTECTED_OSTV_TABLES,
    require_sql_client_editability,
)
from ost_visualizer.infrastructure.sql.client_provisioning import (
    SqlAuthenticatedClient,
    authenticate_runtime_client,
    provision_runtime_client,
    verify_runtime_client,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.descriptor_connection import (
    SqlDescriptorConnectionFactory,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
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
from tests.workspace_state_test_support import with_workspace_state
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.application.dtos.collaboration_dtos import SynchronizationState
from ost_visualizer.application.services.sql_collaboration_coordinator import (
    SqlCollaborationCoordinator,
    _DatabaseRuntime,
)

_GUID = "00000000-0000-0000-0000-000000000123"
_CREATOR = SqlServerDatabaseLocation(
    server="test-server",
    database="",
    authentication_mode=SqlAuthenticationMode.SQL_SERVER,
    username="setup-admin",
    encrypt=True,
    trust_server_certificate=False,
    connection_timeout_seconds=7,
    command_timeout_seconds=17,
)
_CLIENT = SqlAuthenticatedClient("client", b"client-sid", "test-server")
_RUNTIME = SqlDatabaseRuntimeCredentials(
    SqlAuthenticationMode.SQL_SERVER, "client", "runtime-test-secret"
)


def _snapshot():
    return [
        1,
        1,
        1,
        1,
        1,
        SQL_SCHEMA_V1.version,
        SQL_SCHEMA_V1.checksum,
        "READ_WRITE",
        "ost_visualizer_only",
        "disabled",
        None,
        1,
        1,
        1,
        1,
        len(SQL_CLIENT_DIRECT_WRITE_TABLES),
        0,
        0,
        1,
        1,
        0,
        0,
        1,
    ]


class _Lease:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, statement, *parameters):
        self.statements.append((statement, parameters))

    def fetchone(self):
        row = self.rows.pop(0)
        if isinstance(row, Exception):
            raise row
        return row

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _Connections:
    def __init__(self, *rows_per_connection):
        self.leases = [_Lease(rows) for rows in rows_per_connection]
        self.requests = []

    @contextmanager
    def connection(self, request, *, autocommit):
        lease = self.leases[len(self.requests)]
        self.requests.append((request, autocommit))
        yield lease


def _error():
    return SqlInfrastructureError(
        SqlErrorDetails(SqlErrorCode.PERMISSION_DENIED, "Client permission denied.")
    )


class SqlCreationHandoffTests(unittest.TestCase):
    def _create(self, connections, credentials=_RUNTIME):
        creator = SqlDatabaseCreator(connections)

        # Exercise the actual CREATE DATABASE and handoff, with bootstrap isolated;
        # full canonical bootstrap has separate schema/initialization tests.
        def initialize(location, password, **_kwargs):
            self.assertEqual(location.username, "setup-admin")
            self.assertEqual(password, "creator-test-secret")
            return SqlDatabaseCreationResult(
                replace(location, database_guid=_GUID), SQL_SCHEMA_V1.version
            )

        with patch.object(creator, "initialize_blank_database", side_effect=initialize):
            return creator.create_database_for_client(
                _CREATOR,
                "New database]",
                "creator-test-secret",
                runtime_credentials=credentials,
                application_version="test",
            )

    def _connections(self, *, client=_CLIENT, final_snapshot=None, provision_sid=None):
        return _Connections(
            [(1, b"creator-sid", "test-server")],
            [(client.login_name, client.sid, client.server_name, "S"), (0, 0, 0)],
            [(0,)],  # requested database does not exist
            [(0,), (_GUID,), (provision_sid or client.sid,)],
            [
                (_GUID,),
                (client.sid, client.login_name, 0, 0),
                (0, 0, 0),
                final_snapshot if final_snapshot is not None else _snapshot(),
            ],
        )

    def test_creator_creates_but_only_verified_runtime_identity_is_returned(self):
        connections = self._connections()
        result = self._create(connections)
        self.assertEqual(result.location.username, "client")
        self.assertEqual(result.location.database_guid, _GUID)
        self.assertEqual(
            result.location.authentication_mode, SqlAuthenticationMode.SQL_SERVER
        )
        self.assertEqual(
            [
                (r.location.username, r.database_override, auto)
                for r, auto in connections.requests
            ],
            [
                ("setup-admin", "master", True),
                ("client", "master", True),
                ("setup-admin", "master", True),
                ("setup-admin", None, False),
                ("client", None, True),
            ],
        )
        self.assertEqual(
            connections.leases[2].statements[-1][0], "CREATE DATABASE [New database]]]"
        )
        self.assertEqual(connections.leases[3].commits, 1)
        self.assertIn(
            "ostv_permission_snapshot", connections.leases[4].statements[-1][0]
        )
        grants, parameters = connections.leases[3].statements[-1]
        self.assertEqual(parameters, ("client",))
        for table in SQL_CLIENT_PROTECTED_OSTV_TABLES:
            self.assertIn(f"DENY INSERT, UPDATE, DELETE ON [ostv].[{table}]", grants)
        all_sql = " ".join(
            sql for lease in connections.leases for sql, _ in lease.statements
        )
        self.assertNotIn("ALTER AUTHORIZATION", all_sql)
        self.assertNotIn("CREATE LOGIN", all_sql)
        self.assertNotIn("ALTER ROLE [db_owner]", all_sql)
        self.assertNotIn("ALTER SERVER ROLE", all_sql)
        self.assertNotIn("DROP MEMBER", all_sql)
        self.assertNotIn("ADD MEMBER [setup-admin]", all_sql)
        serialized = json.dumps(
            DatabaseDescriptor.for_sql_server(
                result.location, schema_version=1
            ).to_dict()
        )
        for secret in ("creator-test-secret", _RUNTIME.password):
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, repr(connections.requests))
            self.assertNotIn(secret, repr(_RUNTIME))
            self.assertNotIn(secret, repr(result))

    def test_windows_runtime_uses_process_identity_and_preserves_security_settings(
        self,
    ):
        client = replace(_CLIENT, login_name="DOMAIN\\windows-user")
        connections = self._connections(client=client)
        connections.leases[1].rows[0] = (
            client.login_name,
            client.sid,
            client.server_name,
            "U",
        )
        result = self._create(connections, SqlDatabaseRuntimeCredentials())
        self.assertEqual(
            result.location.authentication_mode, SqlAuthenticationMode.WINDOWS
        )
        self.assertEqual(result.location.username, "")
        for index in (1, 4):
            request = connections.requests[index][0]
            self.assertEqual(request.password, "")
            self.assertEqual(request.location.username, "")
            self.assertEqual(request.location.encrypt, _CREATOR.encrypt)
            self.assertEqual(
                request.location.trust_server_certificate,
                _CREATOR.trust_server_certificate,
            )
            self.assertEqual(request.location.connection_timeout_seconds, 7)
            self.assertEqual(request.location.command_timeout_seconds, 17)
            connection_string = SqlConnectionManager(
                drivers=["ODBC Driver 18 for SQL Server"]
            ).build_connection_string(request)
            self.assertIn("Trusted_Connection=yes", connection_string)
            self.assertNotIn("PWD=", connection_string)
            self.assertNotIn("UID=", connection_string)
        self.assertEqual(connections.leases[3].statements[-1][1], (client.login_name,))

    def test_same_creator_sid_is_rejected_before_create_even_with_different_login_spelling(
        self,
    ):
        connections = self._connections(client=replace(_CLIENT, sid=b"creator-sid"))
        with self.assertRaisesRegex(SqlInfrastructureError, "different logins"):
            self._create(connections)
        self.assertEqual(len(connections.requests), 2)

    def test_creator_without_permission_fails_before_runtime_or_create(self):
        connections = _Connections([(0, b"creator-sid", "test-server")])
        with self.assertRaisesRegex(SqlInfrastructureError, "Cannot create a database"):
            self._create(connections)
        self.assertEqual(len(connections.requests), 1)

    def test_provisioning_failure_retains_initialized_database_and_returns_no_result(
        self,
    ):
        connections = self._connections(provision_sid=b"replacement-login-sid")
        with self.assertRaisesRegex(
            SqlInfrastructureError, "Runtime user provisioning failed"
        ) as raised:
            self._create(connections)
        self.assertIn("database was retained", str(raised.exception))
        self.assertIn("no connection was saved", str(raised.exception))
        self.assertEqual(connections.leases[3].commits, 0)
        self.assertEqual(connections.leases[3].rollbacks, 1)
        self.assertEqual(len(connections.requests), 4)
        self.assertFalse(
            any(
                "DROP DATABASE" in sql
                for lease in connections.leases
                for sql, _ in lease.statements
            )
        )

    def test_protected_table_write_permission_blocks_result_after_provisioning(self):
        snapshot = _snapshot()
        snapshot[17] = 1
        connections = self._connections(final_snapshot=snapshot)
        with self.assertRaisesRegex(
            SqlInfrastructureError, "Runtime permission verification failed"
        ):
            self._create(connections)
        self.assertEqual(connections.leases[3].commits, 1)

    def test_unsupported_name_never_connects(self):
        for method in ("create_database", "create_database_for_client"):
            connections = _Connections()
            creator = SqlDatabaseCreator(connections)
            kwargs = {"application_version": "test"}
            if method.endswith("for_client"):
                kwargs["runtime_credentials"] = _RUNTIME
            with self.assertRaisesRegex(ValueError, "75"):
                getattr(creator, method)(_CREATOR, "x" * 76, **kwargs)
            self.assertEqual(connections.requests, [])


class RuntimeProvisioningTests(unittest.TestCase):
    def test_runtime_authentication_error_does_not_expose_driver_credentials(self):
        connections = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            replace(_CREATOR, username="client"),
            _RUNTIME.password,
            database_override="master",
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=pyodbc.Error("28000", f"Login failed: PWD={_RUNTIME.password}"),
        ), self.assertRaises(SqlInfrastructureError) as raised:
            authenticate_runtime_client(connections, request)
        self.assertEqual(
            raised.exception.details.code, SqlErrorCode.AUTHENTICATION_FAILED
        )
        self.assertNotIn(_RUNTIME.password, str(raised.exception))
        self.assertNotIn(_RUNTIME.password, repr(raised.exception))

    def test_login_mapping_is_parameterized_and_transactional(self):
        client = replace(_CLIENT, login_name="client];--'name")
        connections = _Connections([(0,), (_GUID,), (client.sid,)])
        provision_runtime_client(
            connections,
            SqlConnectionRequest(replace(_CREATOR, database_guid=_GUID)),
            client,
        )
        sql, parameters = connections.leases[0].statements[2]
        self.assertNotIn(client.login_name, sql)
        self.assertEqual(parameters, (client.login_name,))
        self.assertIn("QUOTENAME(@login)", sql)
        self.assertIn("DATABASE_PRINCIPAL_ID(@login) IS NOT NULL", sql)
        self.assertEqual(connections.leases[0].commits, 1)

    def test_missing_database_identity_prevents_any_provisioning(self):
        connections = _Connections([(0,), None])
        with self.assertRaisesRegex(SqlInfrastructureError, "identity changed"):
            provision_runtime_client(
                connections, SqlConnectionRequest(_CREATOR), _CLIENT
            )
        self.assertEqual(len(connections.leases[0].statements), 2)
        self.assertEqual(connections.leases[0].rollbacks, 1)

    def test_existing_user_failure_rolls_back_without_demoting_or_remapping(self):
        connections = _Connections([(0,), (_GUID,), _error()])
        with self.assertRaises(SqlInfrastructureError):
            provision_runtime_client(
                connections, SqlConnectionRequest(_CREATOR), _CLIENT
            )
        self.assertEqual(connections.leases[0].rollbacks, 1)
        self.assertEqual(len(connections.leases[0].statements), 3)

    def test_runtime_cannot_be_dbo_owner_or_ddl_admin(self):
        for user, owner, ddl in (("dbo", 0, 0), ("client", 1, 0), ("client", 0, 1)):
            with self.subTest(user=user, owner=owner, ddl=ddl):
                connections = _Connections([(_GUID,), (_CLIENT.sid, user, owner, ddl)])
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "without database ownership"
                ):
                    verify_runtime_client(
                        connections, SqlConnectionRequest(_CREATOR), _CLIENT
                    )

    def test_runtime_cannot_inherit_elevated_server_permissions(self):
        for permissions in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            connections = _Connections(
                [("client", _CLIENT.sid, "test-server", "S"), permissions]
            )
            with self.assertRaisesRegex(
                SqlInfrastructureError, "privileges will not be changed"
            ):
                authenticate_runtime_client(connections, SqlConnectionRequest(_CREATOR))

    def test_group_only_windows_access_has_actionable_precreation_failure(self):
        connections = _Connections([("DOMAIN\\user", _CLIENT.sid, "test-server", None)])
        with self.assertRaisesRegex(
            SqlInfrastructureError, "Group-only Windows access"
        ):
            authenticate_runtime_client(connections, SqlConnectionRequest(_CREATOR))

    def test_production_gate_still_rejects_dbo_and_unprotected_metadata(self):
        for index, value in ((0, 0), (17, 1)):
            snapshot = _snapshot()
            snapshot[index] = value
            with self.assertRaises(SqlInfrastructureError):
                require_sql_client_editability(_Lease([snapshot]))
        require_sql_client_editability(_Lease([_snapshot()]))


class CreationPermissionAndNameTests(unittest.TestCase):
    def test_effective_creation_permission_alternatives_including_master(self):
        # Model HAS_PERMS_BY_NAME results, including dbcreator's effective
        # ALTER ANY DATABASE and sysadmin's effective server permissions.
        alternatives = {
            "HAS_PERMS_BY_NAME(NULL, NULL, N'CREATE ANY DATABASE')",
            "HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY DATABASE')",
            "HAS_PERMS_BY_NAME(N'master', N'DATABASE', N'CREATE DATABASE')",
        }
        for grant in (*alternatives, None):
            connections = _Connections([])
            lease = connections.leases[0]

            def permission_row():
                sql = lease.statements[-1][0]
                expressions = set(re.findall(r"HAS_PERMS_BY_NAME\([^)]*\)", sql))
                self.assertEqual(expressions, alternatives)
                return (int(grant in expressions), b"creator-sid", "test-server")

            lease.fetchone = permission_row
            with patch(
                "ost_visualizer.infrastructure.sql.database_creator.authenticate_runtime_client",
                side_effect=_error(),
            ) as authenticate, self.assertRaises(SqlInfrastructureError):
                SqlDatabaseCreator(connections).create_database_for_client(
                    _CREATOR,
                    "New database",
                    "creator-test-secret",
                    runtime_credentials=_RUNTIME,
                    application_version="test",
                )
            self.assertEqual(authenticate.called, grant is not None)
            self.assertEqual(connections.requests[0][0].database_override, "master")

    def test_creation_limits_full_name_to_settings_capacity_without_truncation(self):
        for name in ("a" * 75, "Database [west]", "漢" * 75, "😀" * 37 + "x"):
            validate_sql_database_creation_name(name)
        for name in ("a" * 76, "漢" * 76, "😀" * 38, "", "master"):
            with self.assertRaises(ValueError):
                validate_sql_database_creation_name(name)
        # Existing connections keep the SQL identifier contract.
        validate_sql_database_name("a" * 128)


class CreationDialogIdentityTests(unittest.TestCase):
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
        dialog.server_input.setText(_CREATOR.server)
        dialog.database_name_input.setText("Test database")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText(_RUNTIME.username)
        dialog.password_input.setText(_RUNTIME.password)
        if not prompt_creator:
            prompt = patch.object(
                dialog,
                "_request_creator_connection",
                return_value=(
                    SqlConnectionDialogResult(_CREATOR, "creator-test-secret")
                ),
            )
            prompt.start()
            self.addCleanup(prompt.stop)
        return dialog

    def test_create_uses_canonical_properties_width_and_content_height(self):
        from ost_visualizer.presentation import config
        from ost_visualizer.presentation.dialogs import sql_database_dialog

        dialog = self._dialog(Mock())
        self.assertIs(type(dialog), SqlDatabasePropertiesDialog)
        self.assertEqual(dialog.width(), config.SQL_DATABASE_PROPERTIES_DIALOG_WIDTH)
        self.assertEqual(dialog.height(), dialog.layout().sizeHint().height())
        for name in (
            "SQL_DATABASE_CREATION_DIALOG_WIDTH",
            "SQL_DATABASE_CREATION_DIALOG_HEIGHT",
            "SQL_DATABASE_PROPERTIES_DIALOG_HEIGHT",
        ):
            self.assertFalse(hasattr(config, name))
        self.assertFalse(hasattr(sql_database_dialog, "_RuntimeConnectionForm"))
        self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
        self.assertEqual(dialog.findChildren(QtWidgets.QGroupBox), [])
        self.assertEqual(
            dialog.button_box.buttons(), [dialog.ok_button, dialog.cancel_button]
        )
        self.assertFalse(hasattr(dialog, "runtime_auth_combo"))
        self.assertFalse(hasattr(dialog, "options_button"))
        self.assertFalse(dialog.encrypt_checkbox.isHidden())
        self.assertTrue(dialog.username_input.isEnabled())
        self.assertTrue(dialog.password_input.isEnabled())
        dialog.windows_auth_radio.setChecked(True)
        self.assertFalse(dialog.username_input.isEnabled())
        self.assertFalse(dialog.password_input.isEnabled())

    def test_both_dialog_heights_follow_font_metrics(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialog,
        )

        original_font = self.app.font()
        larger_font = self.app.font()
        larger_font.setPointSize(original_font.pointSize() + 4)
        normal = (self._dialog(Mock()), SqlConnectionDialog(Mock()))
        self.addCleanup(normal[1].deleteLater)
        self.addCleanup(normal[1].cleanup)
        try:
            self.app.setFont(larger_font)
            larger = (self._dialog(Mock()), SqlConnectionDialog(Mock()))
            self.addCleanup(larger[1].deleteLater)
            self.addCleanup(larger[1].cleanup)
            for before, after in zip(normal, larger):
                self.assertGreater(after.height(), before.height())
                self.assertEqual(after.height(), after.layout().sizeHint().height())
                self.assertFalse(hasattr(after, "options_button"))
        finally:
            self.app.setFont(original_font)

    def test_cancel_before_submission_does_not_provision(self):
        creator = Mock()
        dialog = self._dialog(creator)
        dialog.reject()
        creator.create_database_for_client.assert_not_called()
        self.assertIsNone(dialog.result_data())
        self.assertEqual(dialog.password_input.text(), "")

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
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.SqlConnectionDialog"
        ) as connection_factory, patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.SqlDatabasePropertiesDialog",
            return_value=properties_dialog,
        ) as properties_factory:
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

    def test_creation_properties_accept_server_authentication_and_database_directly(
        self,
    ):
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.CREATE,
            Mock(),
            Mock(),
        )
        try:
            self.assertEqual(dialog.windowTitle(), "Database Properties (SQL Server)")
            self.assertEqual(dialog.server_input.text(), "")
            self.assertTrue(dialog.windows_auth_radio.isChecked())
            self.assertFalse(dialog.server_input.isReadOnly())
            self.assertFalse(dialog.username_input.isReadOnly())
            self.assertFalse(dialog.password_input.isReadOnly())
            self.assertTrue(dialog.sql_auth_radio.isEnabled())
            self.assertFalse(dialog.database_name_input.isReadOnly())
            dialog.server_input.setText("chosen-server")
            dialog.database_name_input.setText("New database")
            dialog.sql_auth_radio.setChecked(True)
            dialog.username_input.setText(_RUNTIME.username)
            dialog.password_input.setText(_RUNTIME.password)
            selected = dialog._connection_details()
            self.assertEqual(selected.location.server, "chosen-server")
            self.assertEqual(
                selected.location.authentication_mode, SqlAuthenticationMode.SQL_SERVER
            )
            self.assertEqual(selected.location.username, _RUNTIME.username)
            self.assertEqual(selected.password, _RUNTIME.password)
            self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_creator_prompt_reuses_connection_dialog_without_runtime_secret(self):
        runtime = replace(_CREATOR, username=_RUNTIME.username)
        dialog = SqlConnectionDialog(Mock(), creator_for=runtime)
        try:
            self.assertEqual(
                dialog.windowTitle(), "Connect to SQL Server - Database Creator"
            )
            self.assertEqual(dialog.server_input.text(), runtime.server)
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertTrue(dialog.windows_auth_radio.isChecked())
            self.assertEqual(dialog.username_input.text(), "")
            self.assertEqual(dialog.password_input.text(), "")
            self.assertFalse(dialog.encrypt_checkbox.isEnabled())
            self.assertFalse(dialog.trust_certificate_checkbox.isEnabled())
            self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
            self.assertFalse(hasattr(dialog, "options_button"))
            dialog.sql_auth_radio.setChecked(True)
            dialog.username_input.setText(_CREATOR.username)
            dialog.password_input.setText("creator-test-secret")
            dialog._accept_if_valid()
            self.assertEqual(
                dialog.result_data(),
                SqlConnectionDialogResult(_CREATOR, "creator-test-secret"),
            )
            self.assertNotIn("creator-test-secret", repr(dialog.result_data()))
        finally:
            dialog.cleanup()
            self.assertEqual(dialog.password_input.text(), "")
            self.assertIsNone(dialog.result_data())
            dialog.deleteLater()

    def test_creator_prompt_cancel_leaves_runtime_form_and_database_untouched(self):
        creator = Mock()
        properties = self._dialog(creator, prompt_creator=True)
        prompts = []

        def cancel(dialog):
            prompts.append(dialog)
            self.assertTrue(properties._creation_in_progress)
            properties.reject()
            properties._accept_if_valid()  # Reentrant submission cannot open another prompt.
            dialog.password_input.setText("temporary-creator-secret")
            dialog.reject()
            return dialog.result()

        with patch.object(SqlConnectionDialog, "exec", new=cancel):
            properties._accept_if_valid()
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0].password_input.text(), "")
        self.assertIsNone(prompts[0].result_data())
        self.assertFalse(properties._creation_in_progress)
        self.assertEqual(properties.password_input.text(), _RUNTIME.password)
        self.assertIsNone(properties.result_data())
        creator.create_database_for_client.assert_not_called()

    def test_creator_prompt_accept_keeps_selected_runtime_for_both_authentication_modes(
        self,
    ):
        for windows in (False, True):
            with self.subTest(windows=windows):
                creator = Mock()
                properties = self._dialog(creator, prompt_creator=True)
                if windows:
                    properties.windows_auth_radio.setChecked(True)
                runtime = properties._connection_details()
                creator.create_database_for_client.return_value = (
                    SqlDatabaseCreationResult(
                        replace(
                            runtime.location,
                            database="Test database",
                            database_guid=_GUID,
                        ),
                        1,
                    )
                )
                prompts = []

                def accept(dialog):
                    prompts.append(dialog)
                    self.assertEqual(dialog.password_input.text(), "")
                    dialog.sql_auth_radio.setChecked(True)
                    dialog.username_input.setText(_CREATOR.username)
                    dialog.password_input.setText("creator-test-secret")
                    dialog._accept_if_valid()
                    return dialog.result()

                with patch.object(SqlConnectionDialog, "exec", new=accept):
                    properties._accept_if_valid()
                self.assertEqual(len(prompts), 1)
                self.assertIsNone(prompts[0].result_data())
                args, kwargs = creator.create_database_for_client.call_args
                self.assertEqual(
                    args[0],
                    replace(
                        runtime.location,
                        authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                        username=_CREATOR.username,
                    ),
                )
                self.assertEqual(args[2], "creator-test-secret")
                self.assertEqual(
                    kwargs["runtime_credentials"],
                    SqlDatabaseRuntimeCredentials() if windows else _RUNTIME,
                )
                self.assertEqual(properties.result_data().password, runtime.password)
                self.assertEqual(
                    properties.result_data().location.authentication_mode,
                    runtime.location.authentication_mode,
                )

    def test_destroyed_or_cleaned_properties_cannot_continue_after_creator_prompt(self):
        from shiboken6 import delete

        for destroy in (False, True):
            creator = Mock()
            properties = self._dialog(creator, prompt_creator=True, own_cleanup=False)
            from ost_visualizer.presentation.utils.dialog import delete_later_if_valid

            self.addCleanup(delete_later_if_valid, properties)
            self.addCleanup(properties.cleanup)

            def accept_after_close(dialog):
                dialog.sql_auth_radio.setChecked(True)
                dialog.username_input.setText(_CREATOR.username)
                dialog.password_input.setText("creator-test-secret")
                dialog._accept_if_valid()
                if destroy:
                    delete(properties)
                else:
                    properties.cleanup()
                return QtWidgets.QDialog.DialogCode.Accepted

            with patch.object(SqlConnectionDialog, "exec", new=accept_after_close):
                properties._accept_if_valid()
            creator.create_database_for_client.assert_not_called()
            self.assertIsNone(properties.result_data())

    def test_creation_worker_keeps_gui_responsive_and_cannot_be_cancelled_mid_setup(
        self,
    ):
        caller = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        worker_threads = []
        creator = Mock()

        def create(location, name, password, **kwargs):
            worker_threads.append(threading.get_ident())
            kwargs["progress"]("Verifying runtime permissions")
            entered.set()
            if not release.wait(3):
                raise AssertionError("The Qt event loop did not remain responsive")
            return SqlDatabaseCreationResult(
                replace(
                    location,
                    database=name,
                    database_guid=_GUID,
                    authentication_mode=SqlAuthenticationMode.WINDOWS,
                    username="",
                ),
                1,
            )

        creator.create_database_for_client.side_effect = create
        dialog = self._dialog(creator)
        gui_callbacks = []

        def release_from_gui():
            if not entered.is_set():
                QtCore.QTimer.singleShot(1, release_from_gui)
                return
            gui_callbacks.append(threading.get_ident())
            dialog.reject()
            dialog._accept_if_valid()
            release.set()

        QtCore.QTimer.singleShot(0, release_from_gui)
        dialog._accept_if_valid()
        self.assertEqual(gui_callbacks, [caller])
        self.assertNotEqual(worker_threads, [caller])
        creator.create_database_for_client.assert_called_once()
        self.assertIsNotNone(dialog.result_data())

    def test_tls_controls_preserve_timeouts_and_reach_creator_request(self):
        creator = Mock()
        creator.create_database_for_client.return_value = SqlDatabaseCreationResult(
            replace(_CREATOR, database="Test database", database_guid=_GUID), 1
        )
        dialog = self._dialog(creator)
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialogResult,
        )

        dialog._initial_connection = SqlConnectionDialogResult(
            _CREATOR, "creator-test-secret"
        )
        dialog._apply_initial_connection()
        self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
        dialog.encrypt_checkbox.setChecked(True)
        dialog._accept_if_valid()
        location = creator.create_database_for_client.call_args.args[0]
        self.assertTrue(location.encrypt)
        self.assertFalse(location.trust_server_certificate)
        self.assertEqual(location.connection_timeout_seconds, 7)
        self.assertEqual(location.command_timeout_seconds, 17)

    def test_existing_properties_restore_transport_without_creator_controls(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialogResult,
        )

        selected = SimpleNamespace(
            name="Existing", database_guid=_GUID, schema_version=1, is_compatible=True
        )
        catalog = Mock()
        catalog.get_database.return_value = selected
        dialog = SqlDatabasePropertiesDialog(
            SimpleNamespace(set_window_icon=lambda _widget: None),
            SqlDatabasePropertiesMode.OPEN,
            catalog,
            Mock(),
            connection=SqlConnectionDialogResult(_CREATOR, "existing-runtime-secret"),
            databases=(selected,),
        )
        try:
            self.assertEqual(dialog.findChildren(QtWidgets.QTabWidget), [])
            self.assertFalse(hasattr(dialog, "options_button"))
            self.assertFalse(hasattr(dialog, "runtime_auth_combo"))
            self.assertTrue(dialog.server_input.isReadOnly())
            self.assertTrue(dialog.password_input.isReadOnly())
            self.assertFalse(dialog.trust_certificate_checkbox.isChecked())
            dialog.trust_certificate_checkbox.setChecked(True)
            dialog._accept_if_valid()
            self.assertTrue(dialog.result_data().location.trust_server_certificate)
            self.assertEqual(dialog.result_data().location.database_guid, _GUID)
            self.assertEqual(dialog.result_data().location.command_timeout_seconds, 17)
            self.assertEqual(dialog.result_data().password, "existing-runtime-secret")
            self.assertTrue(
                catalog.get_database.call_args.args[0].trust_server_certificate
            )
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def test_shutdown_cannot_destroy_creation_owner_while_setup_is_pending(self):
        from PySide6 import QtGui
        from ost_visualizer.presentation.main_window import MainWindow

        host = SimpleNamespace(
            handlers=SimpleNamespace(
                file_ops=SimpleNamespace(
                    maintenance_pending=False,
                    sql_creation_pending=True,
                )
            )
        )
        event = QtGui.QCloseEvent()
        MainWindow.closeEvent(host, event)
        self.assertFalse(event.isAccepted())

    def test_created_database_waits_for_open_result_and_retains_connection_on_failure(
        self,
    ):
        entry = FileEntry.for_descriptor(
            DatabaseDescriptor.for_sql_server(
                replace(
                    _CREATOR, database="Created", database_guid=_GUID, username="client"
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

    def test_creation_preserves_selected_sql_runtime_and_never_returns_creator_secret(
        self,
    ):
        creator = Mock()
        creator.create_database_for_client.return_value = SqlDatabaseCreationResult(
            replace(
                _CREATOR,
                database="Test database",
                database_guid=_GUID,
                authentication_mode=SqlAuthenticationMode.SQL_SERVER,
                username=_RUNTIME.username,
            ),
            1,
        )
        dialog = self._dialog(creator)
        self.assertFalse(hasattr(dialog, "runtime_password_input"))
        self.assertEqual(
            dialog.password_input.echoMode(), QtWidgets.QLineEdit.EchoMode.Password
        )
        dialog._accept_if_valid()
        args, kwargs = creator.create_database_for_client.call_args
        self.assertEqual(args[0].authentication_mode, SqlAuthenticationMode.SQL_SERVER)
        self.assertEqual(args[0].username, _CREATOR.username)
        self.assertEqual(args[2], "creator-test-secret")
        self.assertEqual(kwargs["runtime_credentials"], _RUNTIME)
        self.assertEqual(dialog.result_data().password, _RUNTIME.password)
        self.assertEqual(dialog.result_data().location.username, _RUNTIME.username)
        self.assertEqual(
            dialog.result_data().location.authentication_mode,
            SqlAuthenticationMode.SQL_SERVER,
        )
        self.assertNotIn("creator-test-secret", repr(dialog.result_data()))
        dialog.reject()
        self.assertEqual(dialog.password_input.text(), "")

    def test_windows_creator_cannot_become_its_own_restricted_runtime_user(self):
        connections = _Connections(
            [(1, b"windows-sid", "test-server")],
            [("DOMAIN\\user", b"windows-sid", "test-server", "U"), (0, 0, 0)],
        )
        dialog = self._dialog(SqlDatabaseCreator(connections))
        dialog.windows_auth_radio.setChecked(True)
        dialog._request_creator_connection.return_value = SqlConnectionDialogResult(
            replace(
                _CREATOR, authentication_mode=SqlAuthenticationMode.WINDOWS, username=""
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

    def test_failed_handoff_cannot_accept_or_return_a_descriptor(self):
        creator = Mock()
        creator.create_database_for_client.side_effect = _error()
        dialog = self._dialog(creator)
        with patch(
            "ost_visualizer.presentation.dialogs.sql_database_dialog.show_warning"
        ) as warning:
            dialog._accept_if_valid()
        self.assertIsNone(dialog.result_data())
        self.assertNotEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)
        warning.assert_called_once()

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
                    connection.location, database="Test database", database_guid=_GUID
                )
                if fail:
                    creator.create_database_for_client.side_effect = _error()
                else:
                    creator.create_database_for_client.return_value = (
                        SqlDatabaseCreationResult(runtime_location, 1)
                    )

                # The handler owns this dialog's cleanup for this test.
                def execute_dialog():
                    dialog._accept_if_valid()
                    return dialog.result()

                state = SimpleNamespace(file_entries=[])
                state.update_entries = lambda entries: setattr(
                    state, "file_entries", list(entries)
                )
                registry = DatabaseDescriptorRegistry()
                credentials = Mock()
                credentials.read_password.return_value = _RUNTIME.password
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
                    starts[0].password, "" if windows else _RUNTIME.password
                )
                if windows:
                    credentials.write_password.assert_not_called()
                    credentials.read_password.assert_not_called()
                else:
                    credentials.write_password.assert_called_once()
                    self.assertEqual(
                        credentials.write_password.call_args.args[1:],
                        (_RUNTIME.username, _RUNTIME.password),
                    )
                args, kwargs = creator.create_database_for_client.call_args
                self.assertEqual(
                    args[0],
                    replace(
                        connection.location,
                        authentication_mode=_CREATOR.authentication_mode,
                        username=_CREATOR.username,
                    ),
                )
                self.assertEqual(args[2], "creator-test-secret")
                self.assertEqual(
                    kwargs["runtime_credentials"],
                    SqlDatabaseRuntimeCredentials() if windows else _RUNTIME,
                )
                reopened = factory.request(
                    state.file_entries[0].database_id, read_only=False
                )
                self.assertEqual(reopened, starts[0])
                payload = json.dumps(state.file_entries[0].descriptor.to_dict())
                self.assertNotIn("creator-test-secret", payload)
                self.assertNotIn(_RUNTIME.password, payload)
                self.assertNotIn("setup-admin", payload)


class InitialOpeningCompletionTests(unittest.TestCase):
    def _coordinator(self):
        callback = Mock()
        runtime = _DatabaseRuntime("database", 1, initial_open_callback=callback)
        coordinator = object.__new__(SqlCollaborationCoordinator)
        coordinator._lock = threading.Lock()
        coordinator._runtimes = {"database": runtime}
        coordinator._event_bus = Mock()
        coordinator._capabilities = Mock()
        coordinator._capabilities.is_editable.return_value = True
        return coordinator, runtime, callback

    def test_initial_completion_waits_for_healthy_and_fires_once(self):
        coordinator, runtime, callback = self._coordinator()
        coordinator._set_state("database", SynchronizationState.CONNECTING)
        coordinator._set_state("database", SynchronizationState.CATCHING_UP)
        callback.assert_not_called()
        coordinator._on_connection_restored(("database", runtime.generation + 1, 0))
        callback.assert_not_called()
        coordinator._set_state("database", SynchronizationState.HEALTHY)
        callback.assert_called_once_with(True, "")
        coordinator._set_state(
            "database", SynchronizationState.DISCONNECTED, "later outage"
        )
        callback.assert_called_once()

    def test_initial_failure_or_denied_editability_cannot_report_success(self):
        for state in (
            SynchronizationState.DISCONNECTED,
            SynchronizationState.READ_ONLY,
            SynchronizationState.RECONCILIATION_REQUIRED,
            SynchronizationState.HEALTHY,
        ):
            coordinator, runtime, callback = self._coordinator()
            coordinator._capabilities.is_editable.return_value = False
            coordinator._set_state("database", state, "not ready")
            callback.assert_called_once_with(False, "not ready")
            self.assertIsNone(runtime.initial_open_callback)

    def test_reentrant_state_publication_cannot_complete_replacement_runtime(self):
        coordinator, runtime, callback = self._coordinator()
        replacement_callback = Mock()
        replacement = _DatabaseRuntime(
            "database", 2, initial_open_callback=replacement_callback
        )
        coordinator._event_bus.publish.side_effect = (
            lambda *_args, **_kwargs: coordinator._runtimes.update(database=replacement)
        )
        coordinator._set_state("database", SynchronizationState.HEALTHY)
        callback.assert_not_called()
        replacement_callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
