import contextlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.database_creator import (
    SqlDatabaseCreator,
    _add_exception_note,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidationReport,
    SqlSchemaValidator,
)
from tests.helpers.sql.cleanup_support import (
    _CreationCursor as _cleanup_support__CreationCursor,
    _CreationLease as _cleanup_support__CreationLease,
    _CreationManager as _cleanup_support__CreationManager,
    _empty_inventory as _cleanup_support__empty_inventory,
)
import json
from contextlib import contextmanager
from dataclasses import replace
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
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT as _creation_handoff_support__CLIENT,
    _CREATOR as _creation_handoff_support__CREATOR,
    _Connections as _creation_handoff_support__Connections,
    _GUID as _creation_handoff_support__GUID,
    _Lease as _creation_handoff_support__Lease,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _snapshot as _creation_handoff_support__snapshot,
)
import re
from tests.helpers.sql.creation_handoff_support import (
    _CREATOR as _creation_handoff_support__CREATOR,
    _Connections as _creation_handoff_support__Connections,
    _Lease as _creation_handoff_support__Lease,
    _RUNTIME as _creation_handoff_support__RUNTIME,
    _error as _creation_handoff_support__error,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlAuthenticationMode,
    validate_sql_database_creation_name,
)
from ost_visualizer.infrastructure.sql.errors import SqlInfrastructureError
from tests.helpers.sql.creation_handoff_support import (
    _CLIENT,
    _CREATOR,
    _GUID,
    _RUNTIME,
    _Connections,
    _error,
    _snapshot,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class DatabaseCreatorSqlCleanupTests(unittest.TestCase):
    def test_sql_database_seed_writes_are_explicitly_qualified_to_dbo(self):
        creator = SqlDatabaseCreator(_cleanup_support__CreationManager())
        cursor = _cleanup_support__CreationCursor()
        creator._insert_seed_data(cursor, "OSTV_TEST")
        seed_statements = [
            sql
            for sql in cursor.executed
            if sql.lstrip().upper().startswith("INSERT INTO")
        ]
        self.assertGreaterEqual(len(seed_statements), 4)
        self.assertTrue(
            all("INSERT INTO [dbo].[" in sql for sql in seed_statements),
            seed_statements,
        )

    def test_schema_validation_failure_rolls_back_before_commit(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        self.assertTrue(
            any(
                "SET CHANGE_TRACKING = OFF" in statement
                for statement in manager.lease.cursor_value.executed
            )
        )

    def test_failed_creator_does_not_disable_tracking_owned_by_another_creator(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        disable_statement = next(
            statement
            for statement in manager.lease.cursor_value.executed
            if "SET CHANGE_TRACKING = OFF" in statement
        )
        self.assertIn("IF NOT EXISTS", disable_statement)
        self.assertIn("s.[name]=N'ostv'", disable_statement)

    def test_failed_creator_restores_snapshot_isolation_it_enabled(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with (
            patch.object(creator, "_validate_blank_candidate"),
            patch.object(creator, "_ensure_snapshot_isolation", return_value=True),
            patch.object(
                creator, "_ensure_database_change_tracking", return_value=True
            ),
            patch.object(
                creator,
                "_insert_seed_data",
                side_effect=RuntimeError("schema initialization failed"),
            ),
            patch.object(creator, "_disable_database_change_tracking") as disable_ct,
            patch.object(
                creator, "_disable_snapshot_isolation", create=True
            ) as disable_snapshot,
        ):
            with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                creator.initialize_blank_database(
                    location,
                    application_version="test",
                )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        disable_ct.assert_called_once_with(location, "")
        disable_snapshot.assert_called_once_with(location, "")

    def test_failed_creator_cleanup_does_not_replace_initialization_error(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        original = RuntimeError("schema initialization failed")
        with (
            patch.object(creator, "_validate_blank_candidate"),
            patch.object(creator, "_ensure_snapshot_isolation", return_value=True),
            patch.object(
                creator, "_ensure_database_change_tracking", return_value=True
            ),
            patch.object(creator, "_insert_seed_data", side_effect=original),
            patch.object(
                creator,
                "_disable_database_change_tracking",
                side_effect=SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONNECTION_FAILED,
                        "change tracking cleanup failed",
                    )
                ),
            ),
            patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot,
        ):
            with self.assertRaises(RuntimeError) as raised:
                creator.initialize_blank_database(
                    location,
                    application_version="test",
                )
        self.assertIs(raised.exception, original)
        self.assertTrue(
            any(
                "change tracking cleanup failed" in note
                for note in raised.exception.__notes__
            )
        )
        disable_snapshot.assert_called_once_with(location, "")

    def test_created_container_preserves_initialization_error_classification(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        original = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.TIMEOUT, "initialization timed out")
        )
        location = SqlServerDatabaseLocation(server="localhost", database="")
        with (
            patch.object(
                creator,
                "initialize_blank_database",
                side_effect=original,
            ),
            self.assertRaises(SqlInfrastructureError) as raised,
        ):
            creator.create_database(
                location,
                "OSTV_TEST",
                application_version="1.0",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.TIMEOUT)
        self.assertIn("container was created", str(raised.exception).casefold())
        self.assertTrue(
            any(
                "CREATE DATABASE [OSTV_TEST]" in sql
                for sql in manager.lease.cursor_value.executed
            )
        )

    def test_snapshot_enable_verification_failure_restores_owned_setting(self):
        class _SnapshotVerificationCursor(_cleanup_support__CreationCursor):
            def __init__(self):
                super().__init__()
                self._snapshot_reads = 0

            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    self._snapshot_reads += 1
                    return (0,)
                return super().fetchone()

        manager = _cleanup_support__CreationManager()
        manager.lease.cursor_value = _SnapshotVerificationCursor()
        creator = SqlDatabaseCreator(manager)
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot:
            with self.assertRaisesRegex(
                SqlInfrastructureError, "snapshot isolation could not be enabled"
            ):
                creator._ensure_snapshot_isolation(location, "")
        disable_snapshot.assert_called_once_with(location, "")

    def test_snapshot_verification_driver_failure_restores_owned_setting(self):
        class _SnapshotVerificationCursor(_cleanup_support__CreationCursor):
            def __init__(self):
                super().__init__()
                self._snapshot_reads = 0

            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    self._snapshot_reads += 1
                    if self._snapshot_reads == 1:
                        return (0,)
                    raise pyodbc.Error("08S01", "verification connection failed")
                return super().fetchone()

        manager = _cleanup_support__CreationManager()
        manager.lease.cursor_value = _SnapshotVerificationCursor()
        creator = SqlDatabaseCreator(manager)
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot:
            with self.assertRaises(SqlInfrastructureError):
                creator._ensure_snapshot_isolation(location, "")
        disable_snapshot.assert_called_once_with(location, "")

    def test_exception_note_helper_uses_base_exception_contract(self):
        modern_exception = RuntimeError("initialization failed")
        _add_exception_note(modern_exception, "cleanup failed")
        self.assertIn("cleanup failed", modern_exception.__notes__)

    def test_snapshot_cleanup_failure_preserves_verification_error(self):
        class _SnapshotVerificationCursor(_cleanup_support__CreationCursor):
            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    return (0,)
                return super().fetchone()

        manager = _cleanup_support__CreationManager()
        manager.lease.cursor_value = _SnapshotVerificationCursor()
        creator = SqlDatabaseCreator(manager)
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        cleanup_error = SqlInfrastructureError(
            SqlErrorDetails(
                SqlErrorCode.CONNECTION_FAILED,
                "snapshot cleanup failed",
            )
        )
        with patch.object(
            creator, "_disable_snapshot_isolation", side_effect=cleanup_error
        ):
            with self.assertRaises(SqlInfrastructureError) as raised:
                creator._ensure_snapshot_isolation(location, "")
        self.assertIn("could not be enabled", str(raised.exception))
        self.assertTrue(
            any(
                "snapshot cleanup failed" in note for note in raised.exception.__notes__
            )
        )

    def test_blank_sql_database_creation_applies_client_roles_transactionally(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = lambda _lease: SimpleNamespace(
            database_guid="00000000-0000-0000-0000-000000000001"
        )
        creator._validator.validate = lambda _inventory: SqlSchemaValidationReport()
        creator.initialize_blank_database(
            SqlServerDatabaseLocation(
                server="localhost",
                database="OSTV_TEST_AUDIT",
                username="OSTV_CLIENT",
            ),
            application_version="test",
        )
        statements = " ".join(manager.lease.cursor_value.executed)
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", statements)
        self.assertIn("ALTER ROLE [db_datawriter] ADD MEMBER", statements)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)

    def test_schema_creation_rolls_back_failed_canonical_validation(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        creator._validator.validate = lambda _inventory: SqlSchemaValidationReport(
            ("ostv.SchemaMigrations.Checksum",),
        )
        with self.assertRaisesRegex(Exception, "validation failed"):
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)


class DatabaseCreatorSqlCreationHandoffTests(unittest.TestCase):
    def _create(self, connections, credentials=_creation_handoff_support__RUNTIME):
        creator = SqlDatabaseCreator(connections)

        # Exercise the actual CREATE DATABASE and handoff, with bootstrap isolated;
        # full canonical bootstrap has separate schema/initialization tests.
        def initialize(location, password, **_kwargs):
            self.assertEqual(location.username, "setup-admin")
            self.assertEqual(password, "creator-test-secret")
            return SqlDatabaseCreationResult(
                replace(location, database_guid=_creation_handoff_support__GUID),
                SQL_SCHEMA_V1.version,
            )

        with patch.object(creator, "initialize_blank_database", side_effect=initialize):
            return creator.create_database_for_client(
                _creation_handoff_support__CREATOR,
                "New database]",
                "creator-test-secret",
                runtime_credentials=credentials,
                application_version="test",
            )

    def _connections(
        self,
        *,
        client=_creation_handoff_support__CLIENT,
        final_snapshot=None,
        provision_sid=None,
    ):
        return _creation_handoff_support__Connections(
            [(1, b"creator-sid", "test-server")],
            [(client.login_name, client.sid, client.server_name, "S"), (0, 0, 0)],
            [(0,)],  # requested database does not exist
            [(0,), (_creation_handoff_support__GUID,), (provision_sid or client.sid,)],
            [
                (_creation_handoff_support__GUID,),
                (client.sid, client.login_name, 0, 0),
                (0, 0, 0),
                (
                    final_snapshot
                    if final_snapshot is not None
                    else _creation_handoff_support__snapshot()
                ),
            ],
        )

    def test_creator_creates_but_only_verified_runtime_identity_is_returned(self):
        connections = self._connections()
        result = self._create(connections)
        self.assertEqual(result.location.username, "client")
        self.assertEqual(result.location.database_guid, _creation_handoff_support__GUID)
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
        for secret in (
            "creator-test-secret",
            _creation_handoff_support__RUNTIME.password,
        ):
            self.assertNotIn(secret, serialized)
            self.assertNotIn(secret, repr(connections.requests))
            self.assertNotIn(secret, repr(_creation_handoff_support__RUNTIME))
            self.assertNotIn(secret, repr(result))

    def test_windows_runtime_uses_process_identity_and_preserves_security_settings(
        self,
    ):
        client = replace(
            _creation_handoff_support__CLIENT, login_name="DOMAIN\\windows-user"
        )
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
            self.assertEqual(
                request.location.encrypt, _creation_handoff_support__CREATOR.encrypt
            )
            self.assertEqual(
                request.location.trust_server_certificate,
                _creation_handoff_support__CREATOR.trust_server_certificate,
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
        connections = self._connections(
            client=replace(_creation_handoff_support__CLIENT, sid=b"creator-sid")
        )
        with self.assertRaisesRegex(SqlInfrastructureError, "different logins"):
            self._create(connections)
        self.assertEqual(len(connections.requests), 2)

    def test_creator_without_permission_fails_before_runtime_or_create(self):
        connections = _creation_handoff_support__Connections(
            [(0, b"creator-sid", "test-server")]
        )
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
        snapshot = _creation_handoff_support__snapshot()
        snapshot[17] = 1
        connections = self._connections(final_snapshot=snapshot)
        with self.assertRaisesRegex(
            SqlInfrastructureError, "Runtime permission verification failed"
        ):
            self._create(connections)
        self.assertEqual(connections.leases[3].commits, 1)

    def test_unsupported_name_never_connects(self):
        for method in ("create_database", "create_database_for_client"):
            connections = _creation_handoff_support__Connections()
            creator = SqlDatabaseCreator(connections)
            kwargs = {"application_version": "test"}
            if method.endswith("for_client"):
                kwargs["runtime_credentials"] = _creation_handoff_support__RUNTIME
            with self.assertRaisesRegex(ValueError, "75"):
                getattr(creator, method)(
                    _creation_handoff_support__CREATOR, "x" * 76, **kwargs
                )
            self.assertEqual(connections.requests, [])


class DatabaseCreatorCreationPermissionAndNameTests(unittest.TestCase):
    def test_effective_creation_permission_alternatives_including_master(self):
        # Model HAS_PERMS_BY_NAME results, including dbcreator's effective
        # ALTER ANY DATABASE and sysadmin's effective server permissions.
        alternatives = {
            "HAS_PERMS_BY_NAME(NULL, NULL, N'CREATE ANY DATABASE')",
            "HAS_PERMS_BY_NAME(NULL, NULL, N'ALTER ANY DATABASE')",
            "HAS_PERMS_BY_NAME(N'master', N'DATABASE', N'CREATE DATABASE')",
        }
        for grant in (*alternatives, None):
            connections = _creation_handoff_support__Connections([])
            lease = connections.leases[0]

            def permission_row():
                sql = lease.statements[-1][0]
                expressions = set(re.findall(r"HAS_PERMS_BY_NAME\([^)]*\)", sql))
                self.assertEqual(expressions, alternatives)
                return (int(grant in expressions), b"creator-sid", "test-server")

            lease.fetchone = permission_row
            with (
                patch(
                    "ost_visualizer.infrastructure.sql.database_creator.authenticate_runtime_client",
                    side_effect=_creation_handoff_support__error(),
                ) as authenticate,
                self.assertRaises(SqlInfrastructureError),
            ):
                SqlDatabaseCreator(connections).create_database_for_client(
                    _creation_handoff_support__CREATOR,
                    "New database",
                    "creator-test-secret",
                    runtime_credentials=_creation_handoff_support__RUNTIME,
                    application_version="test",
                )
            self.assertEqual(authenticate.called, grant is not None)
            self.assertEqual(connections.requests[0][0].database_override, "master")


class DatabaseCreatorCreationServerBoundaryTests(unittest.TestCase):
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
