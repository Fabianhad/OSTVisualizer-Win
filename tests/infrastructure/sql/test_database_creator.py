from tests.helpers.sql.strict_sql_fakes import (
    StrictLeaseProxy,
    strict_cursor,
    strict_manager,
)
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
        class _RecordingCursor(_cleanup_support__CreationCursor):
            def __init__(self):
                super().__init__()
                self.recorded = []

            def execute(self, sql, *params):
                self.recorded.append((sql, params))
                return super().execute(sql, *params)

        creator = SqlDatabaseCreator(
            strict_manager(_cleanup_support__CreationManager())
        )
        cursor = _RecordingCursor()
        creator._insert_seed_data(cursor, "OSTV_TEST")
        seed_statements = [
            (sql, params)
            for sql, params in cursor.recorded
            if sql.lstrip().upper().startswith("INSERT INTO")
        ]
        self.assertEqual(len(seed_statements), len(cursor.recorded))
        tables = [
            re.match(r"INSERT INTO \[dbo\]\.\[(\w+)\]", sql).group(1)
            for sql, _params in seed_statements
        ]
        self.assertEqual(
            tables,
            ["Settings", "BidProjects"]
            + ["BidLayers"] * len(creator._default_layers)
            + ["SchemaRegistry"] * len(creator._schema_versions),
        )
        settings_sql, settings_params = seed_statements[0]
        self.assertEqual(settings_params, ("OSTV_TEST",))
        column_count = settings_sql[: settings_sql.index(") VALUES")].count("[") - 2
        values = settings_sql[settings_sql.index("VALUES (") + 8 : -1]
        self.assertEqual(len(values.split(", ")), column_count)
        layer_params = [
            params for sql, params in seed_statements if "[BidLayers]" in sql
        ]
        self.assertEqual(
            layer_params,
            [
                (name, bool(show), bool(locked), sequence)
                for name, show, locked, sequence in creator._default_layers
            ],
        )
        self.assertEqual(
            [params for sql, params in seed_statements if "[SchemaRegistry]" in sql],
            [(version,) for version in creator._schema_versions],
        )

    def test_schema_validation_failure_rolls_back_before_commit(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(strict_manager(manager))
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "initialization validation failed"
        ) as raised:
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
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
        creator = SqlDatabaseCreator(strict_manager(manager))
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        with self.assertRaisesRegex(SqlInfrastructureError, "validation failed"):
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
        self.assertLess(
            disable_statement.index("IF NOT EXISTS"),
            disable_statement.index("SET CHANGE_TRACKING = OFF"),
        )
        self.assertIn("sp_getapplock", disable_statement)
        # Snapshot isolation was already on, so this creator does not own it.
        self.assertFalse(
            any(
                "ALLOW_SNAPSHOT_ISOLATION OFF" in statement
                for statement in manager.lease.cursor_value.executed
            )
        )

    def test_failed_creator_restores_snapshot_isolation_it_enabled(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(strict_manager(manager))
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
            patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot,
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

    def test_failed_creator_leaves_preexisting_database_settings_untouched(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(strict_manager(manager))
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with (
            patch.object(creator, "_validate_blank_candidate"),
            patch.object(creator, "_ensure_snapshot_isolation", return_value=False),
            patch.object(
                creator, "_ensure_database_change_tracking", return_value=False
            ),
            patch.object(
                creator,
                "_insert_seed_data",
                side_effect=RuntimeError("schema initialization failed"),
            ),
            patch.object(creator, "_disable_database_change_tracking") as disable_ct,
            patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot,
        ):
            with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                creator.initialize_blank_database(
                    location,
                    application_version="test",
                )
        self.assertEqual(manager.lease.rollbacks, 1)
        disable_ct.assert_not_called()
        disable_snapshot.assert_not_called()

    def test_change_tracking_enable_failure_still_restores_snapshot_isolation(self):
        creator = SqlDatabaseCreator(
            strict_manager(_cleanup_support__CreationManager())
        )
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        cleanup_error = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.CONNECTION_FAILED, "cleanup failed")
        )
        with (
            patch.object(creator, "_validate_blank_candidate"),
            patch.object(creator, "_ensure_snapshot_isolation", return_value=True),
            patch.object(
                creator,
                "_ensure_database_change_tracking",
                side_effect=cleanup_error,
            ),
            patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot,
        ):
            with self.assertRaises(SqlInfrastructureError) as raised:
                creator.initialize_blank_database(location, application_version="test")
        # The enabling failure is the primary error; snapshot cleanup still ran.
        self.assertIs(raised.exception, cleanup_error)
        disable_snapshot.assert_called_once_with(location, "")

    def test_failed_creator_cleanup_does_not_replace_initialization_error(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(strict_manager(manager))
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
        creator = SqlDatabaseCreator(strict_manager(manager))
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
        self.assertTrue(raised.exception.retryable)
        self.assertIs(raised.exception.__cause__, original)
        message = str(raised.exception)
        self.assertTrue(message.startswith("initialization timed out"))
        self.assertIn("container was created", message.casefold())
        self.assertIn("No automatic drop was attempted", message)
        executed = manager.lease.cursor_value.executed
        self.assertTrue(any("CREATE DATABASE [OSTV_TEST]" in sql for sql in executed))
        self.assertFalse(any("DROP DATABASE" in sql for sql in executed))

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
        creator = SqlDatabaseCreator(strict_manager(manager))
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot:
            with self.assertRaisesRegex(
                SqlInfrastructureError, "snapshot isolation could not be enabled"
            ) as raised:
                creator._ensure_snapshot_isolation(location, "")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(
            sum(
                "ALLOW_SNAPSHOT_ISOLATION ON" in sql
                for sql in manager.lease.cursor_value.executed
            ),
            1,
        )
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
        creator = SqlDatabaseCreator(strict_manager(manager))
        location = SqlServerDatabaseLocation(
            server="localhost", database="OSTV_TEST_AUDIT"
        )
        with patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot:
            with self.assertRaises(SqlInfrastructureError) as raised:
                creator._ensure_snapshot_isolation(location, "")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        disable_snapshot.assert_called_once_with(location, "")

    def test_exception_note_helper_uses_base_exception_contract(self):
        modern_exception = RuntimeError("initialization failed")
        _add_exception_note(modern_exception, "cleanup failed")
        _add_exception_note(modern_exception, "second cleanup failed")
        self.assertEqual(
            modern_exception.__notes__, ["cleanup failed", "second cleanup failed"]
        )
        self.assertEqual(str(modern_exception), "initialization failed")

    def test_snapshot_cleanup_failure_preserves_verification_error(self):
        class _SnapshotVerificationCursor(_cleanup_support__CreationCursor):
            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    return (0,)
                return super().fetchone()

        manager = _cleanup_support__CreationManager()
        manager.lease.cursor_value = _SnapshotVerificationCursor()
        creator = SqlDatabaseCreator(strict_manager(manager))
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
        class _RecordingCursor(_cleanup_support__CreationCursor):
            def __init__(self):
                super().__init__()
                self.recorded = []

            def execute(self, sql, *params):
                self.recorded.append((sql, params))
                return super().execute(sql, *params)

        manager = _cleanup_support__CreationManager()
        cursor = _RecordingCursor()
        manager.lease.cursor_value = cursor
        original_commit = manager.lease.commit

        def commit():
            cursor.recorded.append(("<COMMIT>", ()))
            original_commit()

        manager.lease.commit = commit
        creator = SqlDatabaseCreator(strict_manager(manager))
        creator._inspector.inspect_connection = lambda _lease: SimpleNamespace(
            database_guid="00000000-0000-0000-0000-000000000001"
        )
        creator._validator.validate = lambda _inventory: SqlSchemaValidationReport()
        result = creator.initialize_blank_database(
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
        sql_text = [sql for sql, _params in cursor.recorded]
        commit_index = sql_text.index("<COMMIT>")
        self.assertEqual(commit_index, len(sql_text) - 1)
        permission_index = next(
            index
            for index, sql in enumerate(sql_text)
            if "ALTER ROLE [db_datareader] ADD MEMBER" in sql
        )
        schema_index = next(
            index
            for index, sql in enumerate(sql_text)
            if sql.startswith("CREATE TABLE [dbo]")
        )
        lock_index = next(
            index for index, sql in enumerate(sql_text) if "sp_getapplock" in sql
        )
        self.assertLess(lock_index, schema_index)
        self.assertLess(schema_index, permission_index)
        self.assertLess(permission_index, commit_index)
        self.assertEqual(cursor.recorded[permission_index][1], ("OSTV_CLIENT",))
        self.assertEqual(
            cursor.schema_record, (SQL_SCHEMA_V1.version, SQL_SCHEMA_V1.checksum)
        )
        self.assertEqual(
            result.location.database_guid, "00000000-0000-0000-0000-000000000001"
        )
        self.assertEqual(result.location.database, "OSTV_TEST_AUDIT")
        self.assertEqual(result.schema_version, SQL_SCHEMA_V1.version)

    def test_schema_creation_rolls_back_failed_canonical_validation(self):
        manager = _cleanup_support__CreationManager()
        creator = SqlDatabaseCreator(strict_manager(manager))
        creator._inspector.inspect_connection = (
            lambda _connection: _cleanup_support__empty_inventory()
        )
        creator._validator.validate = lambda _inventory: SqlSchemaValidationReport(
            ("ostv.SchemaMigrations.Checksum",),
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            creator.initialize_blank_database(
                SqlServerDatabaseLocation(
                    server="localhost", database="OSTV_TEST_AUDIT"
                ),
                application_version="test",
            )
        self.assertEqual(
            str(raised.exception),
            "SQL database initialization validation failed: Schema mismatch: "
            "ostv.SchemaMigrations.Checksum",
        )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)


class DatabaseCreatorPreconditionTests(unittest.TestCase):
    class _Cursor(_cleanup_support__CreationCursor):
        table_count = 0
        tracking_row = None
        snapshot_state = 1

        def fetchone(self):
            if "COUNT(*) FROM sys.tables" in self._last_sql:
                return (self.table_count,)
            if "retention_period" in self._last_sql:
                return self.tracking_row
            if "snapshot_isolation_state" in self._last_sql:
                return (self.snapshot_state,)
            return super().fetchone()

    def _creator(self, **attributes):
        manager = _cleanup_support__CreationManager()
        cursor = self._Cursor()
        for name, value in attributes.items():
            setattr(cursor, name, value)
        manager.lease.cursor_value = cursor
        return SqlDatabaseCreator(strict_manager(manager)), manager

    LOCATION = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")

    def test_non_blank_database_is_rejected_before_any_change(self):
        creator, manager = self._creator(table_count=3)
        with self.assertRaisesRegex(SqlInfrastructureError, "not blank") as raised:
            creator.initialize_blank_database(self.LOCATION, application_version="test")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        executed = manager.lease.cursor_value.executed
        self.assertFalse(any(sql.startswith("ALTER DATABASE") for sql in executed))
        self.assertFalse(any(sql.startswith("CREATE") for sql in executed))
        self.assertEqual(manager.lease.commits, 0)

    def test_database_populated_after_preflight_is_rejected_inside_the_lock(self):
        creator, manager = self._creator(table_count=2)
        with patch.object(creator, "_validate_blank_candidate"):
            with self.assertRaisesRegex(SqlInfrastructureError, "not blank"):
                creator.initialize_blank_database(
                    self.LOCATION, application_version="test"
                )
        executed = manager.lease.cursor_value.executed
        self.assertTrue(any("sp_getapplock" in sql for sql in executed))
        self.assertFalse(any(sql.startswith("CREATE") for sql in executed))
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_initialization_requires_valid_database_name_before_connecting(self):
        class _NeverConnects:
            def connection(self, _request, *, autocommit=False):
                raise AssertionError("must not connect")

        creator = SqlDatabaseCreator(_NeverConnects())
        for name in ("", "master", "x" * 76):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    creator.initialize_blank_database(
                        SqlServerDatabaseLocation(server="localhost", database=name),
                        application_version="test",
                    )

    def test_change_tracking_is_enabled_with_canonical_retention_when_absent(self):
        creator, manager = self._creator(tracking_row=None)
        self.assertTrue(creator._ensure_database_change_tracking(self.LOCATION, ""))
        self.assertEqual(
            manager.lease.cursor_value.executed[-1],
            "ALTER DATABASE CURRENT SET CHANGE_TRACKING = ON "
            "(CHANGE_RETENTION = 7 DAYS, AUTO_CLEANUP = ON)",
        )

    def test_canonical_existing_change_tracking_is_not_owned_or_altered(self):
        creator, manager = self._creator(tracking_row=(7, "DAYS", 1))
        self.assertFalse(creator._ensure_database_change_tracking(self.LOCATION, ""))
        self.assertFalse(
            any(
                sql.startswith("ALTER DATABASE")
                for sql in manager.lease.cursor_value.executed
            )
        )

    def test_noncanonical_existing_change_tracking_is_rejected_unchanged(self):
        for row in ((3, "DAYS", 1), (7, "HOURS", 1), (7, "DAYS", 0)):
            with self.subTest(row=row):
                creator, manager = self._creator(tracking_row=row)
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "seven-day retention"
                ) as raised:
                    creator._ensure_database_change_tracking(self.LOCATION, "")
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )
                self.assertFalse(
                    any(
                        sql.startswith("ALTER DATABASE")
                        for sql in manager.lease.cursor_value.executed
                    )
                )

    def test_existing_snapshot_isolation_is_not_owned_or_altered(self):
        creator, manager = self._creator(snapshot_state=1)
        self.assertFalse(creator._ensure_snapshot_isolation(self.LOCATION, ""))
        self.assertFalse(
            any(
                sql.startswith("ALTER DATABASE")
                for sql in manager.lease.cursor_value.executed
            )
        )

    def test_unresolvable_database_target_is_a_connection_failure(self):
        class _NoRowCursor(_cleanup_support__CreationCursor):
            def fetchone(self):
                return None

        manager = _cleanup_support__CreationManager()
        manager.lease.cursor_value = _NoRowCursor()
        creator = SqlDatabaseCreator(strict_manager(manager))
        with patch.object(creator, "_disable_snapshot_isolation") as disable:
            with self.assertRaises(SqlInfrastructureError) as raised:
                creator._ensure_snapshot_isolation(self.LOCATION, "")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        # Nothing was enabled by this call, so nothing is rolled back.
        disable.assert_not_called()


class DatabaseCreatorSqlCreationHandoffTests(unittest.TestCase):
    def _create(self, connections, credentials=_creation_handoff_support__RUNTIME):
        creator = SqlDatabaseCreator(strict_manager(connections))

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
        with self.assertRaisesRegex(
            SqlInfrastructureError, "different logins"
        ) as raised:
            self._create(connections)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertEqual(len(connections.requests), 2)

    def test_runtime_login_on_a_different_server_is_rejected_before_create(self):
        connections = self._connections(
            client=replace(
                _creation_handoff_support__CLIENT, server_name="other-server"
            )
        )
        with self.assertRaisesRegex(SqlInfrastructureError, "same SQL Server"):
            self._create(connections)
        self.assertEqual(len(connections.requests), 2)
        self.assertFalse(
            any(
                sql.startswith("CREATE DATABASE")
                for lease in connections.leases
                for sql, _ in lease.statements
            )
        )

    def test_creator_without_permission_fails_before_runtime_or_create(self):
        connections = _creation_handoff_support__Connections(
            [(0, b"creator-sid", "test-server")]
        )
        with self.assertRaisesRegex(SqlInfrastructureError, "Cannot create a database"):
            self._create(connections)
        self.assertEqual(len(connections.requests), 1)

    def test_incomplete_creator_identity_fails_before_runtime_or_create(self):
        for row in (None, (1, b"", "test-server"), (1, b"creator-sid", "")):
            with self.subTest(row=row):
                connections = _creation_handoff_support__Connections([row])
                with self.assertRaisesRegex(
                    SqlInfrastructureError, "Cannot create a database"
                ):
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
        self.assertIn("login changed during creation", str(raised.exception))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
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
        ) as raised:
            self._create(connections)
        self.assertIn("database was retained", str(raised.exception))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertEqual(connections.leases[3].commits, 1)
        self.assertEqual(len(connections.requests), 5)

    def test_unsupported_name_never_connects(self):
        for method in ("create_database", "create_database_for_client"):
            connections = _creation_handoff_support__Connections()
            creator = SqlDatabaseCreator(strict_manager(connections))
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
                condition = re.search(
                    r"CASE WHEN (.*) THEN 1 ELSE 0 END, SUSER_SID\(\)", sql
                ).group(1)
                self.assertNotIn(" AND ", condition)
                terms = condition.split(" OR ")
                self.assertEqual({term[: -len("=1")] for term in terms}, alternatives)
                self.assertTrue(all(term.endswith("=1") for term in terms))
                # Any single effective permission is sufficient on its own.
                allowed = any(term == f"{grant}=1" for term in terms)
                return (int(allowed), b"creator-sid", "test-server")

            lease.fetchone = permission_row
            with (
                patch(
                    "ost_visualizer.infrastructure.sql.database_creator.authenticate_runtime_client",
                    side_effect=_creation_handoff_support__error(),
                ) as authenticate,
                self.assertRaises(SqlInfrastructureError),
            ):
                SqlDatabaseCreator(
                    strict_manager(connections)
                ).create_database_for_client(
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
                creator = SqlDatabaseCreator(strict_manager(connections))
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
                    if boundary == "runtime_auth":
                        self.assertTrue(
                            str(raised.exception).startswith(
                                "Normal-use authentication preflight failed."
                            )
                        )
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
                    creator = SqlDatabaseCreator(strict_manager(connections))
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
                            request.location.username,
                            (
                                credentials.username
                                if index in (1, 4)
                                else location.username
                            ),
                        )
                        self.assertEqual(
                            request.database_override,
                            "master" if index < 3 else None,
                        )
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
            creator = SqlDatabaseCreator(strict_manager(connections))
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


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply,
    StrictSqlServer,
    StrictSqlViolation,
    applock_rules,
    sql_server_error,
)


class _StrictCreationServer(StrictSqlServer):
    """Strict model of the server statements database creation issues.
    Database options start disabled and flip when the ALTER DATABASE statement
    runs, so a statement issued on the wrong connection mode, or a cleanup that
    does not run, is visible in `snapshot_isolation` / `change_tracking`.
    """

    def __init__(self, *, snapshot=0, tracking=None, tables=0, database_exists=0):
        super().__init__()
        self.snapshot_isolation = snapshot
        self.change_tracking = tracking
        self.tables = tables
        applock_rules(self)
        self.on(
            "SELECT CASE WHEN HAS_PERMS_BY_NAME",
            Reply.rows((1, b"creator-sid", "test-server")),
        )
        self.on(
            "SELECT CASE WHEN DB_ID(?) IS NULL",
            Reply.rows((database_exists,)),
        )
        self.on("CREATE DATABASE", Reply())
        self.on(
            "SELECT COUNT(*) FROM sys.tables", lambda _c: Reply.rows((self.tables,))
        )
        self.on(
            "SELECT [snapshot_isolation_state]",
            lambda _c: Reply.rows((self.snapshot_isolation,)),
        )
        self.on("ALLOW_SNAPSHOT_ISOLATION ON", self._enable_snapshot)
        self.on(
            "FROM sys.change_tracking_databases",
            lambda _c: Reply.rows(
                *(() if self.change_tracking is None else (self.change_tracking,))
            ),
        )
        self.on("SET CHANGE_TRACKING = ON", self._enable_tracking)
        self.on(
            "@LockOwner=N'Session'",
            self._session_cleanup,
        )
        self.on(
            "SELECT CONVERT(uniqueidentifier, database_guid)",
            Reply.rows(("00000000-0000-0000-0000-000000000001",)),
        )
        self.on("DECLARE @database_user sysname", Reply())
        self.on("INSERT INTO", Reply.dml(1))
        self.on(lambda sql: sql.startswith("CREATE "), Reply())
        self.on(lambda sql: sql.startswith("ALTER TABLE"), Reply())
        self.on("ostv_permission_snapshot", Reply.rows((1,) * 5 + (0,) * 18))

    def _enable_snapshot(self, _call):
        self.snapshot_isolation = 1
        return Reply()

    def _enable_tracking(self, _call):
        self.change_tracking = (7, "DAYS", 1)
        return Reply()

    def _session_cleanup(self, call):
        # models the guarded cleanup: only switches the option off while no
        # ostv table exists (the failed creation was rolled back)
        if "ALLOW_SNAPSHOT_ISOLATION OFF" in call.sql and self.tables == 0:
            self.snapshot_isolation = 0
        if "SET CHANGE_TRACKING = OFF" in call.sql and self.tables == 0:
            self.change_tracking = None
        return Reply()


class DatabaseCreatorStrictServerTests(unittest.TestCase):
    LOCATION = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")

    def _creator(self, server, *, valid=True):
        creator = SqlDatabaseCreator(server.manager())
        inventory = _cleanup_support__empty_inventory()
        creator._inspector.inspect_connection = lambda _lease: inventory
        creator._validator.validate = lambda _inventory: (
            SqlSchemaValidationReport()
            if valid
            else SqlSchemaValidationReport(("ostv.Sessions",))
        )
        return creator

    def test_successful_initialization_enables_options_then_creates_schema_in_one_transaction(
        self,
    ):
        server = _StrictCreationServer()
        creator = self._creator(server)
        with server.patched():
            result = creator.initialize_blank_database(
                self.LOCATION, application_version="1.0", actor="tester"
            )
        self.assertEqual(result.schema_version, SQL_SCHEMA_V1.version)
        modes = [call["autocommit"] for call in server.connect_calls]
        # preflight read, snapshot option, tracking option: autocommit; schema: a transaction
        self.assertEqual(modes, [True, True, True, False])
        self.assertEqual(
            (server.snapshot_isolation, server.change_tracking), (1, (7, "DAYS", 1))
        )
        schema = server.connections[3]
        self.assertEqual((schema.commits, schema.rollbacks), (1, 0))
        kinds = server.event_kinds(4)
        # every cursor is closed before the single commit
        before = kinds[: kinds.index("commit")]
        self.assertEqual(before.count("cursor_open"), before.count("cursor_close"))
        statements = server.statements(4)
        self.assertIn("sp_getapplock", statements[0])
        self.assertTrue(
            all(
                not s.startswith(("ALTER DATABASE", "CREATE DATABASE"))
                for s in statements
            )
        )
        everything = " ".join(
            sql for cursor in schema.cursors for sql, _params in cursor.executed
        )
        # creation never demotes or re-owns anyone and never grants ownership
        for forbidden in (
            "DROP ",
            "REVOKE",
            "ALTER SERVER ROLE",
            "DROP MEMBER",
            "ALTER AUTHORIZATION",
            "db_owner",
            "sysadmin",
            "dbcreator",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, everything)
        server.assert_everything_closed()

    def test_validation_failure_rolls_back_and_restores_only_options_this_creator_enabled(
        self,
    ):
        for preexisting in (False, True):
            with self.subTest(preexisting_options=preexisting):
                server = _StrictCreationServer(
                    snapshot=1 if preexisting else 0,
                    tracking=(7, "DAYS", 1) if preexisting else None,
                )
                creator = self._creator(server, valid=False)
                with server.patched():
                    with self.assertRaisesRegex(
                        SqlInfrastructureError, "validation failed"
                    ):
                        creator.initialize_blank_database(
                            self.LOCATION, application_version="1.0"
                        )
                schema = next(
                    c
                    for c in server.connections
                    if not c.autocommit and c.commits + c.rollbacks
                )
                self.assertEqual((schema.commits, schema.rollbacks), (0, 1))
                if preexisting:
                    self.assertEqual(server.snapshot_isolation, 1)
                    self.assertEqual(server.change_tracking, (7, "DAYS", 1))
                else:
                    self.assertEqual(server.snapshot_isolation, 0)
                    self.assertIsNone(server.change_tracking)
                server.assert_everything_closed()

    def test_failed_rollback_does_not_hide_the_initialization_error(self):
        server = _StrictCreationServer()
        server.fail("rollback", sql_server_error("08S01", "Communication link failure"))
        creator = self._creator(server, valid=False)
        with server.patched():
            with self.assertRaisesRegex(SqlInfrastructureError, "validation failed"):
                creator.initialize_blank_database(
                    self.LOCATION, application_version="1.0"
                )
        server.assert_everything_closed()

    def test_statement_error_inside_schema_transaction_is_classified_and_cleaned_up(
        self,
    ):
        server = _StrictCreationServer()

        def fail(_call):
            raise sql_server_error(
                "42000", "CREATE TABLE permission denied in database", 262
            )

        server.rules.insert(0, (lambda sql: sql.startswith("CREATE TABLE [dbo]"), fail))
        creator = self._creator(server)
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                creator.initialize_blank_database(
                    self.LOCATION, application_version="1.0"
                )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertEqual((server.snapshot_isolation, server.change_tracking), (0, None))
        server.assert_everything_closed()

    def test_database_populated_between_preflight_and_lock_is_refused_inside_the_lock(
        self,
    ):
        server = _StrictCreationServer()
        calls = []

        def count(_call):
            calls.append(1)
            return Reply.rows((0 if len(calls) == 1 else 2,))

        server.rules.insert(
            0, (lambda sql: "SELECT COUNT(*) FROM sys.tables" in sql, count)
        )
        creator = self._creator(server)
        with server.patched():
            with self.assertRaisesRegex(SqlInfrastructureError, "not blank"):
                creator.initialize_blank_database(
                    self.LOCATION, application_version="1.0"
                )
        self.assertFalse(
            any(
                s.startswith("CREATE TABLE")
                for c in server.connections
                for cur in c.cursors
                for s, _ in cur.executed
            )
        )

    def test_create_database_issues_create_only_on_an_autocommit_master_connection(
        self,
    ):
        server = _StrictCreationServer()
        creator = self._creator(server)
        with server.patched():
            creator.create_database(
                self.LOCATION, "Fresh DB", application_version="1.0"
            )
        first = server.connections[0]
        self.assertTrue(server.connect_calls[0]["autocommit"])
        self.assertIn(
            "DATABASE=master",
            server.connect_calls[0]["connection_string"]
            .replace("{", "")
            .replace("}", ""),
        )
        statements = server.statements(1)
        self.assertEqual(statements[0].count("DB_ID(?)"), 1)
        self.assertEqual(statements[1], "CREATE DATABASE [Fresh DB]")
        self.assertTrue(first.closed)

    def test_existing_database_name_is_refused_without_issuing_create(self):
        server = _StrictCreationServer(database_exists=1)
        creator = self._creator(server)
        with server.patched():
            with self.assertRaisesRegex(SqlInfrastructureError, "already exists"):
                creator.create_database(
                    self.LOCATION, "Existing", application_version="1.0"
                )
        self.assertFalse(any("CREATE DATABASE" in s for s in server.statements()))
        server.assert_everything_closed()

    def test_database_options_cannot_be_changed_on_a_transactional_connection(self):
        # The strict connection refuses ALTER/CREATE DATABASE outside autocommit,
        # which is why the option helpers must keep autocommit=True.
        server = _StrictCreationServer()
        manager = server.manager()
        request = SqlConnectionRequest(self.LOCATION)
        with server.patched():
            with manager.connection(request, autocommit=False) as lease:
                with lease.cursor() as cursor:
                    with self.assertRaises(pyodbc.Error) as caught:
                        cursor.execute(
                            "ALTER DATABASE CURRENT SET ALLOW_SNAPSHOT_ISOLATION ON"
                        )
        self.assertIn(
            "(226)", caught.exception.args[1] if caught.exception.args else ""
        )


class DatabaseCreatorSweepSurvivorTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over database_creator.py."""

    LOCATION = SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")

    def _creator(self, server, *, valid=True):
        creator = SqlDatabaseCreator(server.manager())
        inventory = _cleanup_support__empty_inventory()
        creator._inspector.inspect_connection = lambda _lease: inventory
        creator._validator.validate = lambda _inventory: (
            SqlSchemaValidationReport()
            if valid
            else SqlSchemaValidationReport(("ostv.Sessions",))
        )
        return creator

    def test_creator_owns_a_real_connection_manager_unless_one_is_injected(self):
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        self.assertIsInstance(SqlDatabaseCreator()._connections, SqlConnectionManager)
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        self.assertIs(SqlDatabaseCreator(manager)._connections, manager)

    def test_progress_is_reported_in_stage_order_by_each_entry_point(self):
        connections = _creation_handoff_support__Connections(
            [(1, b"creator-sid", "test-server")],
            [(_CLIENT.login_name, _CLIENT.sid, _CLIENT.server_name, "S"), (0, 0, 0)],
            [(0,)],
            [(0,), (_GUID,), (_CLIENT.sid,)],
            [(_GUID,), (_CLIENT.sid, _CLIENT.login_name, 0, 0), (0, 0, 0), _snapshot()],
        )
        creator = SqlDatabaseCreator(strict_manager(connections))
        messages = []
        with patch.object(
            creator,
            "initialize_blank_database",
            return_value=SqlDatabaseCreationResult(
                replace(_CREATOR, database="Created", database_guid=_GUID), 1
            ),
        ):
            creator.create_database_for_client(
                _CREATOR,
                "Created",
                "creator-test-secret",
                runtime_credentials=_RUNTIME,
                application_version="test",
                progress=messages.append,
            )
        self.assertEqual(
            messages,
            [
                "Connecting and checking creation permissions",
                "Authenticating application user",
                "Creating database",
                "Initializing schema and reference data",
                "Provisioning application user",
                "Verifying runtime permissions",
            ],
        )
        standalone = []
        only_create = _creation_handoff_support__Connections([(0,)])
        creator = SqlDatabaseCreator(strict_manager(only_create))
        with patch.object(
            creator,
            "initialize_blank_database",
            return_value=SqlDatabaseCreationResult(
                replace(_CREATOR, database="Created", database_guid=_GUID), 1
            ),
        ):
            creator.create_database(
                _CREATOR,
                "Created",
                "x",
                application_version="t",
                progress=standalone.append,
            )
        self.assertEqual(standalone, ["Initializing schema and reference data"])

    def test_non_sql_failures_while_preparing_the_runtime_user_are_a_generic_permission_denial(
        self,
    ):
        for error in (OSError("credential store offline"), ValueError("bad name")):
            with self.subTest(error=type(error).__name__):
                connections = _creation_handoff_support__Connections(
                    [(1, b"creator-sid", "test-server")],
                    [
                        (_CLIENT.login_name, _CLIENT.sid, _CLIENT.server_name, "S"),
                        (0, 0, 0),
                    ],
                    [(0,)],
                )
                creator = SqlDatabaseCreator(strict_manager(connections))
                with (
                    patch.object(
                        creator,
                        "initialize_blank_database",
                        return_value=SqlDatabaseCreationResult(
                            replace(_CREATOR, database="Created", database_guid=_GUID),
                            1,
                        ),
                    ),
                    patch(
                        "ost_visualizer.infrastructure.sql.database_creator.provision_runtime_client",
                        side_effect=error,
                    ),
                    self.assertRaises(SqlInfrastructureError) as raised,
                ):
                    creator.create_database_for_client(
                        _CREATOR,
                        "Created",
                        "creator-test-secret",
                        runtime_credentials=_RUNTIME,
                        application_version="test",
                    )
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED
                )
                text = str(raised.exception)
                self.assertIn("Runtime user provisioning failed", text)
                self.assertIn("The normal-use connection could not be prepared.", text)
                self.assertIn("database was retained", text)
                self.assertNotIn(str(error), text)

    def test_change_tracking_the_creator_never_enabled_is_not_disabled_on_failure(self):
        creator = SqlDatabaseCreator(_cleanup_support__CreationManager())
        failure = SqlInfrastructureError(
            SqlErrorDetails(SqlErrorCode.CONNECTION_FAILED, "enable failed")
        )
        with (
            patch.object(creator, "_validate_blank_candidate"),
            patch.object(creator, "_ensure_snapshot_isolation", return_value=True),
            patch.object(
                creator, "_ensure_database_change_tracking", side_effect=failure
            ),
            patch.object(
                creator, "_disable_database_change_tracking"
            ) as disable_tracking,
            patch.object(creator, "_disable_snapshot_isolation") as disable_snapshot,
            self.assertRaises(SqlInfrastructureError),
        ):
            creator.initialize_blank_database(self.LOCATION, application_version="t")
        disable_tracking.assert_not_called()
        disable_snapshot.assert_called_once_with(self.LOCATION, "")

    def test_every_failed_cleanup_is_attached_to_the_initialization_error_in_order(
        self,
    ):
        creator = SqlDatabaseCreator(_cleanup_support__CreationManager())
        original = RuntimeError("schema initialization failed")

        def cleanup_error(text):
            return SqlInfrastructureError(
                SqlErrorDetails(SqlErrorCode.CONNECTION_FAILED, text)
            )

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
                side_effect=cleanup_error("tracking cleanup failed"),
            ),
            patch.object(
                creator,
                "_disable_snapshot_isolation",
                side_effect=cleanup_error("snapshot cleanup failed"),
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            creator.initialize_blank_database(self.LOCATION, application_version="t")
        self.assertIs(raised.exception, original)
        self.assertEqual(
            raised.exception.__notes__,
            [
                "SQL database initialization cleanup also failed: tracking cleanup failed",
                "SQL database initialization cleanup also failed: snapshot cleanup failed",
            ],
        )

    def test_enable_helpers_answer_with_real_booleans(self):
        server = _StrictCreationServer(tracking=(7, "DAYS", 1), snapshot=1)
        creator = self._creator(server)
        with server.patched():
            self.assertIs(
                creator._ensure_database_change_tracking(self.LOCATION, ""), False
            )
            self.assertIs(creator._ensure_snapshot_isolation(self.LOCATION, ""), False)
        fresh = _StrictCreationServer()
        creator = self._creator(fresh)
        with fresh.patched():
            self.assertIs(
                creator._ensure_database_change_tracking(self.LOCATION, ""), True
            )
            self.assertIs(creator._ensure_snapshot_isolation(self.LOCATION, ""), True)

    def test_snapshot_verification_without_a_row_is_a_failure_that_restores_the_option(
        self,
    ):
        server = _StrictCreationServer()
        reads = []

        def state(_call):
            reads.append(1)
            return Reply.rows((0,)) if len(reads) == 1 else Reply.rows()

        server.rules.insert(
            0, (lambda sql: "SELECT [snapshot_isolation_state]" in sql, state)
        )
        creator = self._creator(server)
        with server.patched():
            with self.assertRaisesRegex(SqlInfrastructureError, "could not be enabled"):
                creator._ensure_snapshot_isolation(self.LOCATION, "")
        self.assertEqual(server.snapshot_isolation, 0)

    def test_initialization_connection_modes_and_actor_attribution(self):
        cases = (
            ("explicit actor", "  Ana  ", "OSTV_CLIENT", "Ana"),
            ("login name", "", " OSTV_CLIENT ", "OSTV_CLIENT"),
            ("process user", "  ", "", "process-user"),
        )
        for label, actor, username, expected in cases:
            with self.subTest(label=label):
                server = _StrictCreationServer()
                creator = self._creator(server)
                location = replace(self.LOCATION, username=username)
                with (
                    server.patched(),
                    patch(
                        "ost_visualizer.infrastructure.sql.database_creator.getpass.getuser",
                        return_value="process-user",
                    ),
                ):
                    creator.initialize_blank_database(
                        location, application_version="2.5", actor=actor
                    )
                strings = [c["connection_string"] for c in server.connect_calls]
                # only the blank-database preflight is a read-only probe
                self.assertIn("ApplicationIntent=ReadOnly", strings[0])
                self.assertTrue(all("ApplicationIntent" not in s for s in strings[1:]))
                self.assertEqual(
                    [c["autocommit"] for c in server.connect_calls],
                    [True, True, True, False],
                )
                executed = [
                    (sql, params)
                    for cursor in server.connections[3].cursors
                    for sql, params in cursor.executed
                ]
                texts = [sql for sql, _params in executed]
                metadata = next(
                    i
                    for i, s in enumerate(texts)
                    if s.startswith("INSERT INTO [ostv].[DatabaseMetadata]")
                )
                migration = next(
                    i
                    for i, s in enumerate(texts)
                    if s.startswith("INSERT INTO [ostv].[SchemaMigrations]")
                )
                self.assertEqual(
                    executed[metadata][1],
                    (
                        "00000000-0000-0000-0000-000000000001",
                        SQL_SCHEMA_V1.version,
                        expected,
                        expected,
                    ),
                )
                self.assertEqual(
                    executed[migration][1],
                    (
                        SQL_SCHEMA_V1.version,
                        SQL_SCHEMA_V1.name,
                        SQL_SCHEMA_V1.checksum,
                        expected,
                        "2.5",
                    ),
                )
                # seed data, then the collaboration seeds, then the ledger, then permissions
                seed = next(
                    i
                    for i, s in enumerate(texts)
                    if s.startswith("INSERT INTO [dbo].[Settings]")
                )
                init = [
                    texts.index(statement)
                    for statement in SQL_SCHEMA_V1.collaboration_initialization_statements
                ]
                permissions = next(
                    i for i, s in enumerate(texts) if "DECLARE @database_user" in s
                )
                self.assertEqual(init, sorted(init))
                self.assertLess(seed, init[0])
                self.assertLess(init[-1], metadata)
                self.assertLess(metadata, migration)
                self.assertLess(migration, permissions)
