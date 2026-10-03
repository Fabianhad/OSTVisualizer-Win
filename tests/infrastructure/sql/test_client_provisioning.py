from tests.helpers.sql.strict_sql_fakes import (
    StrictLeaseProxy,
    strict_cursor,
    strict_manager,
)
import traceback
import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock, patch
import pyodbc
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
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT as _creation_handoff_support__CLIENT,
    _CREATOR as _creation_handoff_support__CREATOR,
    _Connections as _creation_handoff_support__Connections,
    _GUID as _creation_handoff_support__GUID,
    _Lease as _creation_handoff_support__Lease,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _error as _creation_handoff_support__error,
    _snapshot as _creation_handoff_support__snapshot,
)


class ClientProvisioningRuntimeProvisioningTests(unittest.TestCase):
    def test_runtime_authentication_error_does_not_expose_driver_credentials(self):
        connections = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            replace(_creation_handoff_support__CREATOR, username="client"),
            _creation_handoff_support__RUNTIME.password,
            database_override="master",
        )
        secret = _creation_handoff_support__RUNTIME.password
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=pyodbc.Error("28000", f"Login failed: PWD={secret}"),
        ) as connect, self.assertRaises(SqlInfrastructureError) as raised:
            authenticate_runtime_client(strict_manager(connections), request)
        error = raised.exception
        self.assertEqual(connect.call_count, 1)
        self.assertIn(secret, connect.call_args.args[0])
        self.assertEqual(error.details.code, SqlErrorCode.AUTHENTICATION_FAILED)
        self.assertTrue(error.credential_required)
        self.assertNotIn(secret, str(error))
        self.assertNotIn(secret, repr(error))
        self.assertNotIn(secret, repr(error.details))
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)
        formatted = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        self.assertNotIn(secret, formatted)

    def test_login_mapping_is_parameterized_and_transactional(self):
        client = replace(
            _creation_handoff_support__CLIENT, login_name="client];--'name"
        )
        connections = _creation_handoff_support__Connections(
            [(0,), (_creation_handoff_support__GUID,), (client.sid,)]
        )
        provision_runtime_client(
            strict_manager(connections),
            SqlConnectionRequest(
                replace(
                    _creation_handoff_support__CREATOR,
                    database_guid=_creation_handoff_support__GUID,
                )
            ),
            client,
        )
        lease = connections.leases[0]
        self.assertFalse(connections.requests[0][1])
        sql, parameters = lease.statements[2]
        self.assertNotIn(client.login_name, sql)
        self.assertEqual(parameters, (client.login_name,))
        self.assertIn("QUOTENAME(@login)", sql)
        self.assertIn("DATABASE_PRINCIPAL_ID(@login) IS NOT NULL", sql)
        self.assertIn("CREATE USER", sql)
        permission_sql, permission_parameters = lease.statements[3]
        self.assertNotIn(client.login_name, permission_sql)
        self.assertEqual(permission_parameters, (client.login_name,))
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", permission_sql)
        self.assertEqual(len(lease.statements), 4)
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 0)

    def test_login_mapping_with_changed_sid_is_rolled_back_before_permissions(self):
        connections = _creation_handoff_support__Connections(
            [(0,), (_creation_handoff_support__GUID,), (b"other-sid",)]
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "login changed during creation"
        ) as raised:
            provision_runtime_client(
                strict_manager(connections),
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                _creation_handoff_support__CLIENT,
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        lease = connections.leases[0]
        self.assertEqual(len(lease.statements), 3)
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_missing_database_identity_prevents_any_provisioning(self):
        connections = _creation_handoff_support__Connections([(0,), None])
        with self.assertRaisesRegex(SqlInfrastructureError, "identity changed"):
            provision_runtime_client(
                strict_manager(connections),
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                _creation_handoff_support__CLIENT,
            )
        lease = connections.leases[0]
        self.assertEqual(len(lease.statements), 2)
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)
        self.assertFalse(
            any("CREATE USER" in statement for statement, _p in lease.statements)
        )

    def test_existing_user_failure_rolls_back_without_demoting_or_remapping(self):
        connections = _creation_handoff_support__Connections(
            [
                (0,),
                (_creation_handoff_support__GUID,),
                _creation_handoff_support__error(),
            ]
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            provision_runtime_client(
                strict_manager(connections),
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                _creation_handoff_support__CLIENT,
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        lease = connections.leases[0]
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)
        self.assertEqual(len(lease.statements), 3)
        self.assertIn("CREATE USER", lease.statements[2][0])
        self.assertFalse(
            any("ALTER USER" in statement for statement, _p in lease.statements)
        )

    def test_runtime_cannot_be_dbo_owner_or_ddl_admin(self):
        client = _creation_handoff_support__CLIENT
        dbo_client = replace(client, login_name="dbo")
        cases = (
            (dbo_client, client.sid, "dbo", 0, 0),
            (client, b"other-sid", "client", 0, 0),
            (client, client.sid, "other", 0, 0),
            (client, client.sid, "dbo", 0, 0),
            (client, client.sid, "client", 1, 0),
            (client, client.sid, "client", 0, 1),
        )
        for case_client, sid, user, owner, ddl in cases:
            with self.subTest(
                login=case_client.login_name, user=user, owner=owner, ddl=ddl
            ):
                connections = _creation_handoff_support__Connections(
                    [(_creation_handoff_support__GUID,), (sid, user, owner, ddl)]
                )
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "without database ownership"
                ):
                    verify_runtime_client(
                        strict_manager(connections),
                        SqlConnectionRequest(_creation_handoff_support__CREATOR),
                        case_client,
                    )
                self.assertEqual(len(connections.leases[0].statements), 2)
        connections = _creation_handoff_support__Connections(
            [(_creation_handoff_support__GUID,), None]
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "without database ownership"
        ):
            verify_runtime_client(
                strict_manager(connections),
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                client,
            )

    def test_verified_runtime_client_passes_identity_server_and_editability_checks(
        self,
    ):
        client = _creation_handoff_support__CLIENT
        connections = _creation_handoff_support__Connections(
            [
                (_creation_handoff_support__GUID,),
                (client.sid, client.login_name, 0, 0),
                (0, 0, 0),
                _creation_handoff_support__snapshot(),
            ]
        )
        verify_runtime_client(
            strict_manager(connections),
            SqlConnectionRequest(
                replace(
                    _creation_handoff_support__CREATOR,
                    database_guid=_creation_handoff_support__GUID,
                )
            ),
            client,
        )
        lease = connections.leases[0]
        self.assertTrue(connections.requests[0][1])
        self.assertEqual(len(lease.statements), 4)
        self.assertEqual(lease.statements[0][1], (_creation_handoff_support__GUID,))
        self.assertIn("ostv_permission_snapshot", lease.statements[3][0])
        self.assertEqual(lease.rows, [])

    def test_runtime_cannot_inherit_elevated_server_permissions(self):
        for permissions in ((1, 0, 0), (0, 1, 0), (0, 0, 1), None):
            with self.subTest(permissions=permissions):
                connections = _creation_handoff_support__Connections(
                    [
                        (
                            "client",
                            _creation_handoff_support__CLIENT.sid,
                            "test-server",
                            "S",
                        ),
                        permissions,
                    ]
                )
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "privileges will not be changed"
                ):
                    authenticate_runtime_client(
                        strict_manager(connections),
                        SqlConnectionRequest(_creation_handoff_support__CREATOR),
                    )

    def test_individual_logins_without_server_privileges_are_authenticated(self):
        for login_type in ("S", "U"):
            with self.subTest(login_type=login_type):
                connections = _creation_handoff_support__Connections(
                    [
                        (
                            "client",
                            _creation_handoff_support__CLIENT.sid,
                            "test-server",
                            login_type,
                        ),
                        (0, 0, 0),
                    ]
                )
                client = authenticate_runtime_client(
                    strict_manager(connections),
                    SqlConnectionRequest(_creation_handoff_support__CREATOR),
                )
                self.assertEqual(client, _creation_handoff_support__CLIENT)
                self.assertTrue(connections.requests[0][1])

    def test_group_only_windows_access_has_actionable_precreation_failure(self):
        sid = _creation_handoff_support__CLIENT.sid
        rows = (
            ("DOMAIN\\user", sid, "test-server", None),
            ("DOMAIN\\group", sid, "test-server", "G"),
            ("", sid, "test-server", "S"),
            ("client", None, "test-server", "S"),
            ("client", sid, "", "S"),
            None,
        )
        for row in rows:
            with self.subTest(row=row):
                connections = _creation_handoff_support__Connections([row])
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "Group-only Windows access"
                ) as raised:
                    authenticate_runtime_client(
                        strict_manager(connections),
                        SqlConnectionRequest(_creation_handoff_support__CREATOR),
                    )
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED
                )
                self.assertEqual(len(connections.leases[0].statements), 1)


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply,
    StrictSqlServer,
    applock_rules,
    sql_server_error,
)


def _provisioning_server(*, sid=None, identity_found=True):
    """Strict server answering the statements `provision_runtime_client` issues."""
    server = StrictSqlServer()
    applock_rules(server)
    guid_rows = ((_creation_handoff_support__GUID,),) if identity_found else ()
    server.on(
        "SELECT m.[DatabaseGuid] FROM [ostv].[DatabaseMetadata] m WHERE",
        Reply.rows(*guid_rows),
    )
    server.on(
        "CREATE USER",
        Reply.rows(((sid or _creation_handoff_support__CLIENT.sid),)),
    )
    server.on("DECLARE @database_user sysname", Reply())
    return server


class ClientProvisioningStrictServerTests(unittest.TestCase):
    """provision_runtime_client against the strict pyodbc model."""

    def _provision(self, server):
        request = SqlConnectionRequest(
            replace(
                _creation_handoff_support__CREATOR,
                database_guid=_creation_handoff_support__GUID,
            ),
            "creator-test-secret",
        )
        with server.patched():
            provision_runtime_client(
                server.manager(), request, _creation_handoff_support__CLIENT
            )

    def test_provisioning_runs_in_one_transaction_and_commits_after_permissions(self):
        server = _provisioning_server()
        self._provision(server)
        raw = server.connections[0]
        self.assertFalse(server.connect_calls[0]["autocommit"])
        statements = server.statements(1)
        self.assertEqual(len(statements), 4)
        self.assertIn("sp_getapplock", statements[0])
        self.assertIn("CREATE USER", statements[2])
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", statements[3])
        self.assertEqual(
            server.event_kinds(1),
            ["cursor_open"] + ["execute"] * 4 + ["cursor_close", "commit", "close"],
        )
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        server.assert_everything_closed()
        # the schema lock was transaction owned and is released by the commit
        self.assertEqual(
            server.applocks.holders("OSTVisualizer.SchemaInitialization"), []
        )

    def test_permission_statement_parameter_counts_match_for_every_statement(self):
        # The strict cursor rejects any marker/parameter mismatch (including the
        # 30+ parameters of the permission snapshot); a clean run proves counts.
        server = _provisioning_server()
        self._provision(server)
        self.assertEqual(len(server.connections), 1)

    def test_rollback_failure_does_not_replace_the_provisioning_error(self):
        # The login mapped to a different SID: provisioning must fail with that
        # explanation even when the connection died so the rollback also fails.
        server = _provisioning_server(sid=b"other-sid")
        server.fail("rollback", sql_server_error("08S01", "Communication link failure"))
        with self.assertRaisesRegex(
            SqlInfrastructureError, "login changed during creation"
        ) as raised:
            self._provision(server)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        server.assert_everything_closed()

    def test_commit_failure_after_provisioning_is_reported_and_rolled_back(self):
        server = _provisioning_server()
        server.fail("commit", sql_server_error("08S01", "Communication link failure"))
        with self.assertRaises(SqlInfrastructureError) as raised:
            self._provision(server)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
        server.assert_everything_closed()


class ClientProvisioningIdentityStatementTests(unittest.TestCase):
    def test_database_identity_check_uses_the_exact_single_row_identity_predicate(self):
        from tests.helpers.sql.strict_sql_fakes import (
            EXPECTED_DATABASE_METADATA_PREDICATE,
        )

        connections = _creation_handoff_support__Connections(
            [
                (0,),
                (_creation_handoff_support__GUID,),
                (_creation_handoff_support__CLIENT.sid,),
            ]
        )
        provision_runtime_client(
            strict_manager(connections),
            SqlConnectionRequest(
                replace(
                    _creation_handoff_support__CREATOR,
                    database_guid=_creation_handoff_support__GUID,
                )
            ),
            _creation_handoff_support__CLIENT,
        )
        sql, parameters = connections.leases[0].statements[1]
        self.assertEqual(
            sql,
            "SELECT m.[DatabaseGuid] FROM [ostv].[DatabaseMetadata] m WHERE "
            + EXPECTED_DATABASE_METADATA_PREDICATE
            + " AND m.[DatabaseGuid]=CONVERT(uniqueidentifier, ?)",
        )
        self.assertEqual(parameters, (_creation_handoff_support__GUID,))


class ClientProvisioningMissingRowTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over client_provisioning.py."""

    def test_authenticated_client_value_is_immutable(self):
        import dataclasses

        with self.assertRaises(dataclasses.FrozenInstanceError):
            _creation_handoff_support__CLIENT.login_name = "other"

    def test_missing_user_row_or_null_sid_after_create_user_is_a_login_change_not_a_crash(
        self,
    ):
        for label, row in (
            ("no row", None),
            ("null sid", (None,)),
            ("empty sid", (b"",)),
        ):
            with self.subTest(label=label):
                connections = _creation_handoff_support__Connections(
                    [(0,), (_creation_handoff_support__GUID,), row]
                )
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "login changed during creation"
                ) as raised:
                    provision_runtime_client(
                        strict_manager(connections),
                        SqlConnectionRequest(_creation_handoff_support__CREATOR),
                        _creation_handoff_support__CLIENT,
                    )
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED
                )
                lease = connections.leases[0]
                self.assertEqual((lease.commits, lease.rollbacks), (0, 1))
                self.assertEqual(len(lease.statements), 3)

    def test_verification_with_a_null_sid_is_refused_as_a_different_login(self):
        client = _creation_handoff_support__CLIENT
        connections = _creation_handoff_support__Connections(
            [(_creation_handoff_support__GUID,), (None, client.login_name, 0, 0)]
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "without database ownership"
        ):
            verify_runtime_client(
                strict_manager(connections),
                SqlConnectionRequest(_creation_handoff_support__CREATOR),
                client,
            )
