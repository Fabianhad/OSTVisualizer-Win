import contextlib
import logging
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets
from ost_visualizer.application.events.app_events import AppEvents
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.domain.entities.file_state import FileEntry
from ost_visualizer.domain.entities.hierarchy_data import HierarchyFileEntry
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.database.reader_router import DatabaseProjectReader
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.providers import RepositoryProvider
from ost_visualizer.infrastructure.sql.reader import SqlProjectReader
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionLease
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.database_creator import SqlDatabaseCreator
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.permissions import SqlDatabasePermissionProbe
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_COLLABORATION_WRITE_TABLES,
    SQL_CLIENT_DATABASE_ROLES,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.schema_inspector import (
    SqlSchemaInspector,
    SqlSchemaInventory,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    DatabaseMutationRequest,
    ResourceRef,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.infrastructure.sql.schema_validator import (
    SqlSchemaValidationReport,
    SqlSchemaValidator,
)
from ost_visualizer.infrastructure.sql.writer import (
    SqlProjectWriter,
    _RecordedMutation,
    _SqlMutationState,
)
from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
    SqlConnectionDialog,
)
from ost_visualizer.presentation.handlers.file_operation_handler import (
    FileOperationHandler,
)


class _CredentialStore:
    def __init__(self):
        self.deleted = []

    def read_password(self, _target):
        return None

    def write_password(self, _target, _username, _password):
        return None

    def delete_password(self, target):
        self.deleted.append(target)


class _RawCursor:
    def __init__(self):
        self.close_count = 0
        self.timeout = 0

    def close(self):
        self.close_count += 1


class _RawConnection:
    def __init__(self):
        self.raw_cursor = _RawCursor()
        self.close_count = 0

    def cursor(self):
        return self.raw_cursor

    def close(self):
        self.close_count += 1


class _InspectionCursor:
    def __init__(self):
        self._last_sql = ""
        self.executed = []

    def execute(self, sql, *_params):
        self._last_sql = sql
        self.executed.append(sql)
        if "SELECT s.name, t.name, i.name" in sql:
            if "FROM sys.indexes i" not in sql:
                raise AssertionError("index inventory query has no FROM sys.indexes")
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        return None

    def fetchall(self):
        return []

    def close(self):
        return None


class _InspectionLease:
    def __init__(self):
        self.cursor_value = _InspectionCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _InspectionManager:
    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        self.lease = _InspectionLease()
        yield self.lease


class _CreationCursor:
    def __init__(self):
        self._last_sql = ""
        self.executed = []
        self.schema_record = None

    def execute(self, sql, *params):
        self._last_sql = sql
        self.executed.append(sql)
        if "INSERT INTO [ostv].[SchemaMigrations]" in sql:
            self.schema_record = (params[0], params[2])
        return self

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

    def fetchone(self):
        if (
            "[ostv].[DatabaseMetadata]" in self._last_sql
            and "[ostv].[SchemaMigrations]" in self._last_sql
        ):
            return (
                *self.schema_record,
                "READ_WRITE",
                "ost_visualizer_only",
                "disabled",
                None,
                1,
                1,
                1,
                1,
            )
        if "snapshot_isolation_state" in self._last_sql:
            return (1,)
        if "retention_period" in self._last_sql:
            return None
        if "IS_ROLEMEMBER" in self._last_sql:
            return (1, 1, 1, 1, 1)
        if "COUNT(*) FROM sys.tables" in self._last_sql:
            return (0,)
        if "FROM sys.tables" in self._last_sql:
            return (len(SQL_CLIENT_COLLABORATION_WRITE_TABLES), 0, 0)
        if "VIEW CHANGE TRACKING" in self._last_sql:
            return (1, 1, 0, 0, 1)
        if "sp_getapplock" in self._last_sql:
            return (0,)
        if "FROM [ostv].[Sessions]" in self._last_sql:
            return (1,)
        if "database_guid" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        return (0,)

    def close(self):
        return None


class _CreationLease:
    def __init__(self):
        self.cursor_value = _CreationCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _CreationManager:
    def __init__(self):
        self.lease = _CreationLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


class _WriterCursor(_CreationCursor):
    def __init__(self, connection):
        super().__init__()
        self.connection = connection
        self.close_count = 0

    def fetchone(self):
        if "IS_ROLEMEMBER" in self._last_sql:
            return (1, 1, 1, 1, 1)
        if "SchemaMigrations" in self._last_sql:
            return (
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
            )
        if "FROM sys.tables" in self._last_sql:
            return (len(SQL_CLIENT_COLLABORATION_WRITE_TABLES), 0, 0)
        if "VIEW CHANGE TRACKING" in self._last_sql:
            return (1, 1, 0, 0, 1)
        if "sp_getapplock" in self._last_sql:
            return (0,)
        if "FROM [ostv].[Sessions]" in self._last_sql:
            return (1,)
        if "SELECT TOP (1) [DatabaseGuid]" in self._last_sql:
            return ("00000000-0000-0000-0000-000000000001",)
        if "SELECT MAX([RefNo])" in self._last_sql:
            return (None,)
        if "OUTPUT INSERTED.[Token]" in self._last_sql:
            return (b"\x00\x00\x00\x00\x00\x00\x00\x01",)
        return None

    def close(self):
        self.close_count += 1


class _WriterLease:
    def __init__(self):
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        cursor = _WriterCursor(self)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _WriterManager:
    def __init__(self):
        self.lease = _WriterLease()

    @contextlib.contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommit = autocommit
        yield self.lease


def _empty_inventory():
    return SqlSchemaInventory(
        database_guid="00000000-0000-0000-0000-000000000001",
        schema_version=0,
        schema_checksum="",
        tables=frozenset(),
        columns=(),
        foreign_keys=(),
        indexes=(),
        views=(),
        triggers=(),
        procedures=(),
        functions=(),
    )


class SqlCleanupCorrectnessTests(unittest.TestCase):
    def test_sql_mutation_uses_canonical_entity_version_token_column(self):
        source = Path("ost_visualizer/infrastructure/sql/writer.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("OUTPUT INSERTED.[Token]", source)
        self.assertNotIn("OUTPUT INSERTED.[Version]", source)

    def test_sql_edit_probe_requires_built_in_roles_and_collaboration_permissions(
        self,
    ):
        class _PermissionCursor:
            def __init__(
                self,
                role_result,
                metadata_result,
                collaboration_result=(
                    len(SQL_CLIENT_COLLABORATION_WRITE_TABLES),
                    0,
                    0,
                ),
                marker_result=(1, 1, 0, 0, 1),
            ):
                self._role_result = role_result
                self._metadata_result = metadata_result
                self._collaboration_result = collaboration_result
                self._marker_result = marker_result
                self._last_sql = ""

            def execute(self, sql, *_params):
                self._last_sql = sql
                return self

            def fetchone(self):
                if "IS_ROLEMEMBER" in self._last_sql:
                    return self._role_result
                if "s.[name]=N'ostv'" in self._last_sql:
                    return self._collaboration_result
                if "VIEW CHANGE TRACKING" in self._last_sql:
                    return self._marker_result
                return self._metadata_result

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        class _PermissionManager:
            def __init__(
                self,
                role_result,
                metadata_result,
                collaboration_result=(
                    len(SQL_CLIENT_COLLABORATION_WRITE_TABLES),
                    0,
                    0,
                ),
                marker_result=(1, 1, 0, 0, 1),
            ):
                self._cursor = _PermissionCursor(
                    role_result,
                    metadata_result,
                    collaboration_result,
                    marker_result,
                )

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield SimpleNamespace(cursor=lambda: self._cursor)

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        current = (
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
        )
        complete = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager((1, 1, 1, 1, 1), current),
        )
        self.assertTrue(complete.can_edit(descriptor.database_id))
        for roles in (
            (0, 1, 1, 1, 1),
            (1, 0, 1, 1, 1),
            (1, 1, 1, 1, 0),
        ):
            with self.subTest(roles=roles):
                missing_role = SqlDatabasePermissionProbe(
                    registry,
                    _CredentialStore(),
                    connection_manager=_PermissionManager(roles, current),
                )
                self.assertFalse(missing_role.can_edit(descriptor.database_id))
        malformed_role = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager((1, 1, object(), 1, 1), current),
        )
        self.assertFalse(malformed_role.can_edit(descriptor.database_id))
        denied_change_log = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                (len(SQL_CLIENT_COLLABORATION_WRITE_TABLES), 1, 0),
            ),
        )
        self.assertFalse(denied_change_log.can_edit(descriptor.database_id))
        writable_schema_ledger = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                (len(SQL_CLIENT_COLLABORATION_WRITE_TABLES), 0, 1),
            ),
        )
        self.assertFalse(writable_schema_ledger.can_edit(descriptor.database_id))
        missing_marker_permission = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current,
                marker_result=(1, 1, 0, 0, 0),
            ),
        )
        self.assertFalse(missing_marker_permission.can_edit(descriptor.database_id))
        disabled_change_tracking = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                current[:6] + (0, 0, 1, 1),
            ),
        )
        self.assertFalse(disabled_change_tracking.can_edit(descriptor.database_id))
        read_only_database = SqlDatabasePermissionProbe(
            registry,
            _CredentialStore(),
            connection_manager=_PermissionManager(
                (1, 1, 1, 1, 1),
                (
                    SQL_SCHEMA_V1.version,
                    SQL_SCHEMA_V1.checksum,
                    "READ_ONLY",
                ),
            ),
        )
        self.assertFalse(read_only_database.can_edit(descriptor.database_id))

    def test_canonical_sql_client_permissions_use_built_in_roles_and_protect_ledgers(
        self,
    ):
        cursor = _CreationCursor()
        apply_sql_client_permissions(cursor, "OSTV_CLIENT")
        permission_sql = " ".join(cursor.executed)
        self.assertEqual(SQL_CLIENT_DATABASE_ROLES, ("db_datareader", "db_datawriter"))
        self.assertIn("ALTER USER", permission_sql)
        self.assertIn("WITH DEFAULT_SCHEMA=[dbo]", permission_sql)
        self.assertIn("ALTER ROLE [db_datareader] ADD MEMBER", permission_sql)
        self.assertIn("ALTER ROLE [db_datawriter] ADD MEMBER", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[dbo]", permission_sql)
        self.assertIn("GRANT VIEW DEFINITION ON SCHEMA::[ostv]", permission_sql)
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[DatabaseMetadata]", permission_sql
        )
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[SchemaMigrations]", permission_sql
        )
        self.assertIn(
            "DENY INSERT, UPDATE, DELETE ON [ostv].[ExternalAdapterState]",
            permission_sql,
        )
        self.assertNotIn("ostv_client_editor", permission_sql)

    def test_sql_edit_probe_treats_connection_failure_as_read_only(self):
        class _UnavailableConnection:
            def __enter__(self):
                raise SqlInfrastructureError(
                    SqlErrorDetails(
                        SqlErrorCode.CONNECTION_FAILED,
                        "The SQL Server is unavailable.",
                    )
                )

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

        class _UnavailableManager:
            def connection(self, _request, *, autocommit=False):
                del autocommit
                return _UnavailableConnection()

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        probe = SqlDatabasePermissionProbe(
            registry, _CredentialStore(), connection_manager=_UnavailableManager()
        )
        self.assertFalse(probe.can_edit(descriptor.database_id))

    def test_repository_uses_the_composed_database_reader(self):
        manager = object()
        reader = object()
        calls = []
        provider = RepositoryProvider(
            logging.getLogger("test"),
            project_reader_factory=lambda connection_manager: (
                calls.append(connection_manager) or reader
            ),
        )
        repository = provider.get_project_repository(manager)
        self.assertIs(repository.parser.parser, reader)
        self.assertEqual(calls, [manager])

    def test_access_writer_uses_access_schema_inspector(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope("example.mdb"):
            self.assertIsInstance(writer._schema(object()), MdbSchemaInspector)

    def test_database_reader_router_preserves_access_schema_and_error_contract(self):
        reader = DatabaseProjectReader(
            object(), DatabaseDescriptorRegistry(), _CredentialStore()
        )
        observed = {}

        def parse_access(active_reader, locator):
            observed["locator"] = locator
            observed["schema"] = active_reader._schema(object())
            observed["raises_optional_read_errors"] = (
                active_reader._record_caught_read_error(RuntimeError("optional"))
            )
            return HierarchyFileEntry(file_path=locator), []

        with patch.object(
            MdbReader, "parse_file", autospec=True, side_effect=parse_access
        ):
            reader.parse_file("example.mdb")
        self.assertEqual(observed["locator"], "example.mdb")
        self.assertIsInstance(observed["schema"], MdbSchemaInspector)
        self.assertFalse(observed["raises_optional_read_errors"])

    def test_database_reader_router_preserves_sql_schema_and_error_contract(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        reader = DatabaseProjectReader(object(), registry, _CredentialStore())
        observed = {}

        def parse_sql(active_reader, database_id):
            observed["database_id"] = database_id
            observed["schema"] = active_reader._schema(object())
            observed["raises_read_errors"] = active_reader._record_caught_read_error(
                RuntimeError("snapshot")
            )
            return HierarchyFileEntry(file_path=database_id), []

        with patch.object(
            SqlProjectReader, "parse_file", autospec=True, side_effect=parse_sql
        ):
            reader.parse_file(descriptor.database_id)
        self.assertEqual(observed["database_id"], descriptor.database_id)
        self.assertIsInstance(observed["schema"], CurrentSqlWriteSchema)
        self.assertTrue(observed["raises_read_errors"])

    def test_access_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("42S02", "optional Access table is missing")

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise original

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

        class _AccessConnections:
            @contextlib.contextmanager
            def connection(self, *_args, **_kwargs):
                yield _Connection()

        reader = DatabaseProjectReader(
            _AccessConnections(), DatabaseDescriptorRegistry(), _CredentialStore()
        )
        with patch.object(
            MdbReader,
            "_schema",
            return_value=CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        ):
            self.assertEqual(reader.get_pages_with_takeoffs("example.mdb", "1"), set())

    def test_sql_reader_router_keeps_backend_scope_for_outer_error_handler(self):
        original = pyodbc.Error("08S01", "snapshot read failed")

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise original

        class _Connection:
            @staticmethod
            def cursor():
                return _Cursor()

            @staticmethod
            def rollback():
                return None

        class _SqlConnections:
            @contextlib.contextmanager
            def connection(self, *_args, **_kwargs):
                yield _Connection()

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        reader = DatabaseProjectReader(object(), registry, _CredentialStore())
        reader._sql_connections = _SqlConnections()
        with self.assertRaises(pyodbc.Error) as raised:
            reader.get_pages_with_takeoffs(descriptor.database_id, "1")
        self.assertIs(raised.exception, original)

    def test_access_writer_uses_the_common_uid_allocator_contract(self):
        class _Cursor:
            def execute(self, sql):
                self.sql = sql

            @staticmethod
            def fetchone():
                return (41,)

        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        cursor = _Cursor()
        with writer._backend_scope("example.mdb"):
            uid = writer._next_uid(cursor, "BidTakeoffs")
        self.assertEqual(uid, 42)
        self.assertEqual(cursor.sql, "SELECT MAX([UID]) FROM [BidTakeoffs]")

    def test_sql_writer_router_uses_the_common_uid_allocator_contract(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope(descriptor.database_id):
            uid = writer._next_uid(object(), "BidTakeoffs")
        self.assertIsInstance(uid, int)
        with self.assertRaisesRegex(RuntimeError, "has not been generated"):
            str(uid)

    def test_writer_router_error_policy_uses_backend_not_sql_context_presence(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        original = RuntimeError("row failure")
        resource_error = pyodbc.Error("HY001", "System resource exceeded")
        mutation_token = writer._active_mutation.set(
            SimpleNamespace(operation_error=None)
        )
        try:
            with writer._backend_scope("example.mdb"):
                self.assertFalse(writer._record_caught_mutation_error(original))
                self.assertTrue(writer._is_access_resource_exceeded(resource_error))
            with writer._backend_scope(descriptor.database_id):
                self.assertTrue(writer._record_caught_mutation_error(original))
                self.assertFalse(writer._is_access_resource_exceeded(resource_error))
        finally:
            writer._active_mutation.reset(mutation_token)

    def test_sql_write_schema_exposes_columns_to_shared_write_mixins(self):
        schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)
        expected_columns = {
            "Bids": {"UID", "JobName"},
            "BidPages": {"UID", "BidUID"},
            "BidConditions": {"UID", "BidUID", "Name", "Type"},
            "BidTakeoffs": {"UID", "Position"},
        }
        for table, required in expected_columns.items():
            with self.subTest(table=table):
                self.assertTrue(required.issubset(schema.get_columns(table)))

    def test_sql_writer_permission_guard_does_not_reclassify_transport_failure(self):
        original = pyodbc.Error("08S01", "connection lost during permission probe")

        class _Cursor:
            closed = False

            def execute(self, _sql, *_params):
                raise original

            def close(self):
                self.closed = True

        class _Lease:
            cursor_value = _Cursor()

            def cursor(self):
                return self.cursor_value

        lease = _Lease()
        with self.assertRaises(pyodbc.Error) as captured:
            SqlProjectWriter._require_sql_client_editability(lease)
        self.assertIs(captured.exception, original)
        self.assertTrue(lease.cursor_value.closed)

    def test_sql_and_access_schemas_implement_every_shared_write_contract(self):
        implementations = (
            (
                CurrentSqlWriteSchema.table_exists,
                CurrentSqlWriteSchema.column_exists,
                CurrentSqlWriteSchema.get_columns,
                CurrentSqlWriteSchema.log_optional_write_skip,
                CurrentSqlWriteSchema.optional_column,
                CurrentSqlWriteSchema.optional_table_missing,
                CurrentSqlWriteSchema.order_by_existing,
                CurrentSqlWriteSchema.require_column,
                CurrentSqlWriteSchema.require_table,
            ),
            (
                MdbSchemaInspector.table_exists,
                MdbSchemaInspector.column_exists,
                MdbSchemaInspector.get_columns,
                MdbSchemaInspector.log_optional_write_skip,
                MdbSchemaInspector.optional_column,
                MdbSchemaInspector.optional_table_missing,
                MdbSchemaInspector.order_by_existing,
                MdbSchemaInspector.require_column,
                MdbSchemaInspector.require_table,
            ),
        )
        self.assertTrue(
            all(callable(method) for methods in implementations for method in methods)
        )

    def test_sql_schema_rejects_conflicting_core_table_outside_dbo(self):
        inventory = replace(
            _empty_inventory(),
            schema_version=SQL_SCHEMA_V1.version,
            schema_checksum=SQL_SCHEMA_V1.checksum,
            tables=frozenset({("custom", "Bids")}),
        )
        report = SqlSchemaValidator(SQL_SCHEMA_V1.core_schema).validate(inventory)
        self.assertIn("custom.Bids.shadows_dbo", report.problems)

    def test_sql_database_seed_writes_are_explicitly_qualified_to_dbo(self):
        creator = SqlDatabaseCreator(_CreationManager())
        cursor = _CreationCursor()
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

    def test_sql_shared_annotation_reader_does_not_acknowledge_partial_data(self):
        class _FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("08S01", "snapshot hydration failed")

        class _Connection:
            @staticmethod
            def cursor():
                return _FailingCursor()

        reader = SqlProjectReader.__new__(SqlProjectReader)
        reader.logger = logging.getLogger("tests.sql_strict_shared_reader")
        with self.assertRaisesRegex(pyodbc.Error, "snapshot hydration failed"):
            reader._parse_bid_annotations_for_bid(
                _Connection(),
                "1",
                [],
                CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
            )

    def test_sql_parse_file_uses_one_snapshot_transaction(self):
        class _Cursor:
            def __init__(self):
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_params):
                self.executed.append(sql)
                return self

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _CredentialStore(),
            connection_manager=connections,
        )
        with patch.object(
            reader,
            "parse_file_connection",
            return_value=("hierarchy", {}),
        ) as parse:
            result = reader.parse_file(descriptor.database_id)
        self.assertEqual(result, ("hierarchy", {}))
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.executed,
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)
        parse.assert_called_once_with(descriptor.database_id, connections.lease)

    def test_sql_parse_file_rolls_back_failed_snapshot(self):
        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _sql, *_params):
                return self

        class _Lease:
            def __init__(self):
                self.rollbacks = 0

            @staticmethod
            def cursor():
                return _Cursor()

            @staticmethod
            def commit():
                raise AssertionError("failed SQL parse must not commit")

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _CredentialStore(),
            connection_manager=connections,
        )
        with (
            patch.object(
                reader,
                "parse_file_connection",
                side_effect=RuntimeError("hierarchy failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "hierarchy failed"),
        ):
            reader.parse_file(descriptor.database_id)
        self.assertFalse(connections.autocommit)
        self.assertEqual(connections.lease.rollbacks, 1)

    def test_sql_shared_reader_connection_is_snapshot_scoped(self):
        class _Cursor:
            def __init__(self):
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *_params):
                self.executed.append(sql)
                return self

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return self.cursor_value

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        class _Connections:
            def __init__(self):
                self.lease = _Lease()
                self.autocommit = None

            @contextlib.contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield self.lease

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        connections = _Connections()
        reader = SqlProjectReader(
            registry,
            _CredentialStore(),
            connection_manager=connections,
        )
        with reader._connection(descriptor.database_id) as lease:
            self.assertIs(lease, connections.lease)
        self.assertFalse(connections.autocommit)
        self.assertEqual(
            connections.lease.cursor_value.executed,
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(connections.lease.commits, 2)
        self.assertEqual(connections.lease.rollbacks, 0)

    def test_access_shared_annotation_reader_retains_optional_table_tolerance(self):
        class _FailingCursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("42S02", "optional Access table is missing")

        class _Connection:
            @staticmethod
            def cursor():
                return _FailingCursor()

        reader = MdbReader.__new__(MdbReader)
        reader.logger = logging.getLogger("tests.access_tolerant_shared_reader")
        annotations = reader._parse_bid_annotations_for_bid(
            _Connection(),
            "1",
            [],
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
        )
        self.assertEqual(annotations, [])

    def test_access_import_lookup_never_uses_sql_table_qualification(self):
        connection = object()
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter,
                "_load_existing_uid_by_column",
                return_value={"Concrete": "12"},
            ) as access_lookup,
            patch.object(
                SqlProjectWriter,
                "_load_existing_uid_by_column",
                side_effect=AssertionError("Access import dispatched to SQL"),
            ),
            writer._backend_scope("example.mdb"),
        ):
            result = writer._load_existing_uid_by_column(connection, "CdnTypes", "Name")
        self.assertEqual(result, {"Concrete": "12"})
        access_lookup.assert_called_once_with(writer, connection, "CdnTypes", "Name")

    def test_writer_requires_an_explicit_backend_scope(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._current_backend()

    def test_missing_sql_descriptor_never_falls_through_to_access(self):
        registry = DatabaseDescriptorRegistry()
        writer = DatabaseProjectWriter(
            object(), registry, _CredentialStore(), DatabaseSessionRegistry()
        )
        with self.assertRaisesRegex(LookupError, "not registered"):
            writer._is_sql("unregistered-database-id")
        reader = DatabaseProjectReader(object(), registry, _CredentialStore())
        with self.assertRaisesRegex(LookupError, "not registered"):
            reader._is_sql("unregistered-database-id")

    def test_schema_inspector_index_query_has_canonical_from_clause(self):
        inspector = SqlSchemaInspector(_InspectionManager())
        inventory = inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        self.assertEqual(inventory.indexes, ())

    def test_schema_inspector_excludes_sql_server_internal_tables(self):
        manager = _InspectionManager()
        inspector = SqlSchemaInspector(manager)
        inspector.inspect(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        table_inventory_queries = [
            sql for sql in manager.lease.cursor_value.executed if "sys.tables" in sql
        ]
        self.assertTrue(table_inventory_queries)
        self.assertTrue(
            all(
                "is_ms_shipped" in sql.replace("[", "").replace("]", "") and "=0" in sql
                for sql in table_inventory_queries
            )
        )

    def test_sql_reader_rejects_invalid_schema_before_domain_queries(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        reader = SqlProjectReader(registry, _CredentialStore(), _InspectionManager())
        reader._inspector.inspect_request = lambda _request: _empty_inventory()
        with patch.object(
            MdbReader,
            "parse_file",
            side_effect=AssertionError("domain query ran before schema validation"),
        ):
            with self.assertRaisesRegex(Exception, "Schema mismatch"):
                reader.parse_file(descriptor.database_id)

    def test_sql_reader_returns_canonical_descriptor_hierarchy_identity(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            display_name="SQL Test Database",
        )
        registry.register(descriptor)
        reader = SqlProjectReader(registry, _CredentialStore(), _InspectionManager())
        reader._validator.validate = lambda _inventory: SimpleNamespace(is_valid=True)
        with (
            patch.object(
                reader,
                "_parse_hierarchy",
                return_value=HierarchyFileEntry(file_path=""),
            ),
            patch.object(reader, "_parse_cdn_types", return_value={}),
        ):
            hierarchy, _cdn_types = reader.parse_file(descriptor.database_id)
        self.assertEqual(hierarchy.file_path, descriptor.database_id)
        self.assertEqual(hierarchy.database_name, descriptor.display_name)
        self.assertEqual(hierarchy.display_name, descriptor.display_name)

    def test_sql_cursor_has_one_owner_and_is_closed_once(self):
        raw_connection = _RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        wrapper = ConnectionWrapper(lease, accepts_cursor_options=False)
        cursor = wrapper.cursor()
        cursor.close()
        lease.close()
        self.assertEqual(raw_connection.raw_cursor.close_count, 1)
        self.assertEqual(raw_connection.close_count, 1)

    def test_sql_connection_lease_close_is_idempotent(self):
        raw_connection = _RawConnection()
        lease = SqlConnectionLease(raw_connection, 30)
        lease.close()
        lease.close()
        self.assertEqual(raw_connection.close_count, 1)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            lease.cursor()

    def test_repeated_sql_connection_cycles_close_every_resource_once(self):
        connections = []

        def connect(*_args, **_kwargs):
            connection = _RawConnection()
            connections.append(connection)
            return connection

        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=connect,
        ):
            for _ in range(50):
                with manager.connection(request, autocommit=True) as lease:
                    with lease.cursor():
                        pass
        self.assertEqual(len(connections), 50)
        self.assertTrue(all(conn.close_count == 1 for conn in connections))
        self.assertTrue(all(conn.raw_cursor.close_count == 1 for conn in connections))

    def test_sql_write_failure_rolls_back_and_closes_all_cursors(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with self.assertRaisesRegex(RuntimeError, "mid-operation"):

            def fail(_recorder):
                raise RuntimeError("mid-operation failure")

            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                fail,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        self.assertTrue(
            all(cursor.close_count == 1 for cursor in manager.lease.cursors)
        )

    def test_sql_write_without_record_fails_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with self.assertRaisesRegex(RuntimeError, "did not record"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: True,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_mutation_preserves_error_swallowed_by_shared_mdb_operation(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )

        def shared_mdb_style_operation(_recorder):
            try:
                with writer._connection(descriptor.database_id):
                    raise RuntimeError("original shared-operation failure")
            except RuntimeError:
                return False

        with self.assertRaisesRegex(RuntimeError, "original shared-operation failure"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                shared_mdb_style_operation,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_preconnection_validation_error_is_not_replaced_by_resource_invariant(
        self,
    ):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with self.assertRaisesRegex(ValueError, "Invalid takeoff UID"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.delete_takeoffs(
                    descriptor.database_id, ["not-a-uid"]
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_create_project_preserves_original_error_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with (
            patch.object(
                writer,
                "_require_write_columns",
                side_effect=RuntimeError("project schema failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "project schema failure"),
        ):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.create_project(
                    descriptor.database_id,
                    "Project",
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_create_project_rejects_direct_write_outside_mutation_executor(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=_WriterManager(),
            session_registry=DatabaseSessionRegistry(),
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            writer.create_project(descriptor.database_id, "Project")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SESSION_EXPIRED)

    def test_inherited_sql_mutation_never_uses_access_error_fallback_directly(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=_WriterManager(),
            session_registry=DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(ValueError, "Invalid takeoff UID"):
            writer.delete_takeoffs(descriptor.database_id, ["not-a-uid"])

    def test_access_preconnection_validation_retains_established_false_result(self):
        writer = MdbWriter()
        self.assertFalse(writer.delete_takeoffs("example.mdb", ["not-a-uid"]))

    def test_access_router_scopes_preconnection_validation_as_access(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        result = writer.execute(
            DatabaseMutationRequest(database_id="example.mdb", session_id=None),
            lambda _recorder: writer.delete_takeoffs("example.mdb", ["not-a-uid"]),
        )
        self.assertTrue(result.success)
        self.assertFalse(result.value)

    def test_sql_router_scopes_preconnection_validation_as_sql(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _CredentialStore(),
            sessions,
        )
        writer._sql_connections = manager
        with self.assertRaisesRegex(ValueError, "Invalid takeoff UID"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.delete_takeoffs(
                    descriptor.database_id, ["not-a-uid"]
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_shared_master_data_conversion_error_escapes_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = DatabaseProjectWriter(object(), registry, _CredentialStore(), sessions)
        writer._sql_connections = manager
        with self.assertRaisesRegex(ValueError, "invalid literal"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.update_bid_job_status(
                    descriptor.database_id, "not-a-bid", None
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_access_shared_master_data_conversion_retains_false_result(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        result = writer.execute(
            DatabaseMutationRequest(database_id="example.mdb", session_id=None),
            lambda _recorder: writer.update_bid_job_status(
                "example.mdb", "not-a-bid", None
            ),
        )
        self.assertTrue(result.success)
        self.assertFalse(result.value)

    def test_sql_mutation_preserves_row_error_swallowed_inside_shared_mdb_operation(
        self,
    ):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        with (
            patch.object(
                writer,
                "_execute_annotation_insert",
                side_effect=RuntimeError("nested annotation failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "nested annotation failure"),
        ):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.insert_annotations(
                    descriptor.database_id,
                    "1",
                    [spec],
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_access_row_error_retains_established_best_effort_result(self):
        writer = MdbWriter(conn_manager=_WriterManager())
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        with (
            patch.object(writer, "_next_uid", return_value=1),
            patch.object(
                writer,
                "_execute_annotation_insert",
                side_effect=RuntimeError("access row failure"),
            ),
        ):
            result = writer.insert_annotations("example.mdb", "1", [spec])
        self.assertEqual(result, [])
        self.assertEqual(writer._conn_manager.lease.commits, 1)
        self.assertEqual(writer._conn_manager.lease.rollbacks, 0)

    def test_sql_takeoff_write_does_not_retry_access_driver_resource_error(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with (
            patch.object(
                writer,
                "_run_selected_takeoffs_value_update",
                side_effect=pyodbc.Error("HY001", "System resource exceeded"),
            ) as update,
            self.assertRaisesRegex(pyodbc.Error, "System resource exceeded"),
        ):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.save_takeoffs_area(
                    descriptor.database_id,
                    ["10"],
                    "20",
                ),
            )
        self.assertEqual(update.call_count, 1)
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_access_takeoff_write_retains_resource_limit_retry(self):
        writer = MdbWriter()
        with patch.object(
            writer,
            "_run_selected_takeoffs_value_update",
            side_effect=[
                pyodbc.Error("HY001", "System resource exceeded"),
                None,
            ],
        ) as update:
            result = writer.save_takeoffs_area("example.mdb", ["10"], "20")
        self.assertTrue(result)
        self.assertEqual(update.call_count, 2)

    def test_sql_page_rescale_cleanup_error_aborts_the_whole_mutation(self):
        class _RescaleCursor:
            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("42000", "page rescale failure")

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )

        def mutate(recorder):
            writer._rescale_page_positions(
                _RescaleCursor(),
                CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema),
                10,
                2.0,
            )
            recorder.record(
                ResourceRef("page", "10", 1),
                ChangeOperation.UPDATE,
            )
            return True

        with self.assertRaisesRegex(pyodbc.Error, "page rescale failure"):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                mutate,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_shared_mutation_families_preserve_their_original_errors(self):
        cases = (
            (
                "bid",
                "_execute_insert_values",
                lambda writer, database_id: writer.create_bid(
                    database_id, None, {"job_name": "Bid"}
                ),
            ),
            (
                "page",
                "_execute_update_values",
                lambda writer, database_id: writer.save_page_name(
                    database_id, "10", "Page"
                ),
            ),
            (
                "condition",
                "_execute_insert_values",
                lambda writer, database_id: writer.insert_condition(
                    database_id, "1", CreateConditionSpec(name="Condition")
                ),
            ),
            (
                "takeoff",
                "_execute_insert_values",
                lambda writer, database_id: writer.insert_takeoffs(
                    database_id,
                    "1",
                    [
                        InsertTakeoffSpec(
                            condition_uid="2",
                            page_uid="3",
                            area_uid=None,
                            position=[1.0, 2.0],
                        )
                    ],
                ),
            ),
            (
                "master_data",
                "_execute_update_values",
                lambda writer, database_id: writer.save_job_statuses(
                    database_id,
                    {
                        "new": [],
                        "updated": [{"uid": "4", "name": "Open"}],
                        "deleted_uids": [],
                    },
                ),
            ),
        )
        for family, helper, operation in cases:
            with self.subTest(family=family):
                registry = DatabaseDescriptorRegistry()
                descriptor = DatabaseDescriptor.for_sql_server(
                    SqlServerDatabaseLocation(
                        server="localhost", database=f"OSTV_TEST_{family.upper()}"
                    )
                )
                registry.register(descriptor)
                manager = _WriterManager()
                sessions = DatabaseSessionRegistry()
                sessions.register(descriptor.database_id, "session-1")
                writer = SqlProjectWriter(
                    registry,
                    _CredentialStore(),
                    connection_manager=manager,
                    session_registry=sessions,
                )
                expected = f"{family} mutation failure"
                with (
                    patch.object(writer, helper, side_effect=RuntimeError(expected)),
                    self.assertRaisesRegex(RuntimeError, expected),
                ):
                    writer.execute(
                        DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id="session-1",
                        ),
                        lambda _recorder: operation(writer, descriptor.database_id),
                    )
                self.assertEqual(manager.lease.commits, 0)
                self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_mutation_commits_exactly_one_transaction_marker(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )

        def mutate(recorder):
            recorder.record(
                ResourceRef("database", descriptor.database_id),
                ChangeOperation.UPDATE,
            )
            return True

        result = writer.execute(
            DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
            ),
            mutate,
        )
        statements = [
            sql for cursor in manager.lease.cursors for sql in cursor.executed
        ]
        self.assertTrue(result.success)
        self.assertEqual(
            sum("INSERT INTO [ostv].[ChangeLog]" in sql for sql in statements),
            1,
        )
        self.assertEqual(
            sum("INSERT INTO [ostv].[ChangeTransactions]" in sql for sql in statements),
            1,
        )
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)

    def test_bulk_feed_coalescing_preserves_every_entity_version(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=DatabaseSessionRegistry(),
        )
        resources = tuple(ResourceRef("takeoff", str(uid), 8) for uid in range(451))
        state = _SqlMutationState(
            descriptor.database_id,
            manager.lease,
            DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session",
                resources=resources,
            ),
            records=[
                _RecordedMutation(resource, ChangeOperation.UPDATE)
                for resource in resources
            ],
        )
        versions = writer._finish_mutation(state)
        statements = [
            sql for cursor in manager.lease.cursors for sql in cursor.executed
        ]
        version_writes = [
            sql for sql in statements if "MERGE [ostv].[EntityVersions]" in sql
        ]
        change_rows = [
            sql for sql in statements if "INSERT INTO [ostv].[ChangeLog]" in sql
        ]
        self.assertEqual(len(version_writes), 452)
        self.assertTrue(all(resource in versions for resource in resources))
        self.assertIn(ResourceRef("takeoffs_collection", "8", 8), versions)
        self.assertEqual(len(change_rows), 1)

    def test_sql_import_failure_preserves_original_error_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        manager = _WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        raw_data = RawBidData(bid_row={"UID": "1", "Name": "Imported"})
        with (
            patch.object(writer, "_assign_next_bid_no"),
            patch.object(
                writer,
                "_write_remapped_identity_graph",
                side_effect=RuntimeError("unsupported import column"),
            ),
            self.assertRaisesRegex(RuntimeError, "unsupported import column"),
        ):
            writer.execute(
                DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.import_ost_data(
                    descriptor.database_id,
                    raw_data,
                    lambda data, *_maps: data,
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_import_rebinds_bid_owned_rows_to_inserted_bid_identity(self):
        class _Connection:
            def cursor(self):
                return _RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "source-bid", "Name": "Imported"},
            bid_tables={
                "BidLayers": [
                    {
                        "UID": "source-layer",
                        "BidUID": "stale-bid",
                        "Name": "Default",
                    }
                ]
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, row))
            return 101 if table == "Bids" else 202

        with (
            patch.object(
                writer,
                "_get_table_info",
                side_effect=lambda _connection, table: (
                    ({"UID", "Name"}, {})
                    if table == "Bids"
                    else ({"UID", "BidUID", "Name"}, {})
                ),
            ),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            writer._write_remapped_identity_graph(_Connection(), raw_data)
        self.assertEqual(inserted[1][0], "BidLayers")
        self.assertEqual(inserted[1][1]["BidUID"], 101)

    def test_sql_import_does_not_remap_resolved_global_identity(self):
        class _Connection:
            def cursor(self):
                return _RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "5", "Name": "Imported"},
            bid_tables={
                "BidConditions": [
                    {
                        "UID": "6",
                        "BidUID": "5",
                        "CdnTypeUID": "5",
                        "Name": "Concrete",
                    }
                ]
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, row))
            return 101 if table == "Bids" else 202

        with (
            patch.object(
                writer,
                "_get_table_info",
                side_effect=lambda _connection, table: (
                    ({"UID", "Name"}, {})
                    if table == "Bids"
                    else ({"UID", "BidUID", "CdnTypeUID", "Name"}, {})
                ),
            ),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            writer._write_remapped_identity_graph(_Connection(), raw_data)
        self.assertEqual(inserted[1][0], "BidConditions")
        self.assertEqual(inserted[1][1]["BidUID"], 101)
        self.assertEqual(inserted[1][1]["CdnTypeUID"], "5")

    def test_sql_import_identity_map_is_scoped_to_parent_table(self):
        class _Connection:
            def cursor(self):
                return _RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "Name": "Imported"},
            bid_tables={
                "BidNamedViews": [{"UID": "7", "BidUID": "1", "Name": "View"}],
                "BidHotLinks": [
                    {"UID": "7", "BidUID": "1", "BidPageViewUID": "7"},
                    {"UID": "8", "BidUID": "1", "BidPageViewUID": "7"},
                ],
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, row))
            return len(inserted) * 100 + 1

        with (
            patch.object(
                writer,
                "_get_table_info",
                side_effect=lambda _connection, table: (
                    ({"UID", "Name"}, {})
                    if table == "Bids"
                    else (
                        (
                            {"UID", "BidUID", "Name"},
                            {},
                        )
                        if table == "BidNamedViews"
                        else ({"UID", "BidUID", "BidPageViewUID"}, {})
                    )
                ),
            ),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            writer._write_remapped_identity_graph(_Connection(), raw_data)
        self.assertEqual(inserted[1][0], "BidNamedViews")
        self.assertEqual(inserted[2][0], "BidHotLinks")
        self.assertEqual(inserted[3][0], "BidHotLinks")
        self.assertEqual(inserted[2][1]["BidPageViewUID"], 201)
        self.assertEqual(inserted[3][1]["BidPageViewUID"], 201)

    def test_writer_guard_rejects_stale_database_metadata(self):
        class _StaleMetadataCursor(_WriterCursor):
            def fetchone(self):
                if "DatabaseMetadata" in self._last_sql:
                    return (
                        2,
                        SQL_SCHEMA_V1.checksum,
                        "READ_WRITE",
                        "ost_visualizer_only",
                        "disabled",
                        None,
                        1,
                        1,
                        1,
                        1,
                    )
                return super().fetchone()

        class _StaleMetadataLease(_WriterLease):
            def cursor(self):
                cursor = _StaleMetadataCursor(self)
                self.cursors.append(cursor)
                return cursor

        lease = _StaleMetadataLease()
        with self.assertRaisesRegex(Exception, "not writable"):
            SqlProjectWriter._require_sql_client_editability(lease)
        self.assertTrue(all(cursor.close_count == 1 for cursor in lease.cursors))

    def test_writer_guard_rejects_disabled_change_tracking(self):
        class _TrackingDisabledCursor(_WriterCursor):
            def fetchone(self):
                if "DatabaseMetadata" in self._last_sql:
                    return (
                        SQL_SCHEMA_V1.version,
                        SQL_SCHEMA_V1.checksum,
                        "READ_WRITE",
                        "ost_visualizer_only",
                        "disabled",
                        None,
                        0,
                        0,
                        1,
                        1,
                    )
                return super().fetchone()

        class _TrackingDisabledLease(_WriterLease):
            def cursor(self):
                cursor = _TrackingDisabledCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(Exception, "not writable"):
            SqlProjectWriter._require_sql_client_editability(_TrackingDisabledLease())

    def test_writer_guard_rejects_missing_builtin_client_role(self):
        class _MissingRoleCursor(_WriterCursor):
            def fetchone(self):
                if "IS_ROLEMEMBER" in self._last_sql:
                    return (1, 0)
                return super().fetchone()

        class _MissingRoleLease(_WriterLease):
            def cursor(self):
                cursor = _MissingRoleCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(Exception, "required SQL database roles"):
            SqlProjectWriter._require_sql_client_editability(_MissingRoleLease())

    def test_writer_guard_rejects_missing_collaboration_marker_permission(self):
        class _MissingMarkerPermissionCursor(_WriterCursor):
            def fetchone(self):
                if "VIEW CHANGE TRACKING" in self._last_sql:
                    return (1, 1, 0, 0, 0)
                return super().fetchone()

        class _MissingMarkerPermissionLease(_WriterLease):
            def cursor(self):
                cursor = _MissingMarkerPermissionCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(Exception, "collaboration permissions"):
            SqlProjectWriter._require_sql_client_editability(
                _MissingMarkerPermissionLease()
            )

    def test_sql_import_table_metadata_comes_from_canonical_schema(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _CredentialStore(),
            DatabaseSessionRegistry(),
        )

        class _NoMetadataConnection:
            def cursor(self):
                raise AssertionError("writer queried a second schema inventory")

        with writer._backend_scope(descriptor.database_id):
            columns, types = writer._get_table_info(_NoMetadataConnection(), "Bids")
        self.assertIn("UID", columns)
        self.assertEqual(types["UID"], "int")

    def test_schema_validation_failure_rolls_back_before_commit(self):
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda *_args, **_kwargs: _empty_inventory()
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
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = (
            lambda *_args, **_kwargs: _empty_inventory()
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
        manager = _CreationManager()
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
        manager = _CreationManager()
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
                for note in getattr(raised.exception, "__notes__", ())
            )
        )
        disable_snapshot.assert_called_once_with(location, "")

    def test_created_container_preserves_initialization_error_classification(self):
        manager = _CreationManager()
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
        class _SnapshotVerificationCursor(_CreationCursor):
            def __init__(self):
                super().__init__()
                self._snapshot_reads = 0

            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    self._snapshot_reads += 1
                    return (0,)
                return super().fetchone()

        manager = _CreationManager()
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

    def test_snapshot_cleanup_failure_preserves_verification_error(self):
        class _SnapshotVerificationCursor(_CreationCursor):
            def fetchone(self):
                if "snapshot_isolation_state" in self._last_sql:
                    return (0,)
                return super().fetchone()

        manager = _CreationManager()
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
                "snapshot cleanup failed" in note
                for note in getattr(raised.exception, "__notes__", ())
            )
        )

    def test_blank_sql_database_creation_applies_client_roles_transactionally(self):
        manager = _CreationManager()
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
        manager = _CreationManager()
        creator = SqlDatabaseCreator(manager)
        creator._inspector.inspect_connection = lambda *_args: _empty_inventory()
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

    def test_failed_unload_retains_removed_checked_descriptor(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
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
            def __init__(self, *_args, **_kwargs):
                pass

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

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=type(
                "Cleanup", (), {"execute_and_save": lambda self: 0}
            )(),
            file_loading_service=None,
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
            sql_collaboration_coordinator=SimpleNamespace(),
            credential_store=_CredentialStore(),
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
        self.assertEqual(updates[-1], [entry])

    def test_removed_sql_descriptor_waits_for_collaboration_drain(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _CredentialStore()
        callbacks = []

        class _State:
            file_entries = [entry]

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
                return []

            def commit_credential_changes(self):
                return set()

            def cleanup(self):
                pass

            def deleteLater(self):
                pass

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=None,
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
                stop_database_async=lambda _database_id, _reason, callback: callbacks.append(
                    callback
                )
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
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _CredentialStore()
        callbacks = []
        starts = []

        class _State:
            file_entries = [entry]

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
                return []

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
            event_bus=None,
            file_state_model=state,
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=None,
            working_directory_service=None,
            unload_file_fn=lambda _locator: True,
            deferred_persistence_manager=SimpleNamespace(
                flush_for_file=lambda _locator: True,
                cancel_for_file=lambda _locator: None,
            ),
            ui_access_manager=SimpleNamespace(is_allowed=lambda _feature: True),
            sql_collaboration_coordinator=SimpleNamespace(
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

    def test_failed_sql_drain_retains_descriptor_and_credential(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        entry = FileEntry.for_descriptor(descriptor)
        registry = DatabaseDescriptorRegistry()
        registry.register(descriptor)
        credentials = _CredentialStore()

        class _State:
            file_entries = []

            def update_entries(self, entries):
                self.file_entries = list(entries)

        state = _State()
        handler = FileOperationHandler.__new__(FileOperationHandler)
        handler.window = None
        handler._file_state_model = state
        handler._database_descriptor_registry = registry
        handler._credential_store = credentials
        handler._sql_collaboration = SimpleNamespace(start_database=lambda _id: None)
        with patch(
            "ost_visualizer.presentation.handlers.file_operation_handler.show_warning"
        ) as warning:
            handler._complete_sql_connection_removal(
                entry, False, "session cleanup failed"
            )
        self.assertIs(registry.resolve(descriptor.database_id), descriptor)
        self.assertEqual(credentials.deleted, [])
        self.assertEqual(state.file_entries, [entry.with_checked(False)])
        warning.assert_called_once()

    def test_retained_sql_descriptor_reconnects_through_coordinator(self):
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
        )
        entry = FileEntry.for_descriptor(descriptor)

        class _State:
            file_entries = [entry]

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

        handler = FileOperationHandler(
            window=None,
            icon_provider=None,
            event_bus=SimpleNamespace(
                publish=lambda event, **kwargs: published.append((event, kwargs))
            ),
            file_state_model=_State(),
            cleanup_deleted_files_use_case=SimpleNamespace(
                execute_and_save=lambda: None
            ),
            file_loading_service=None,
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

    def test_connection_dialog_cleanup_releases_result_secret(self):
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        icon_provider = type(
            "IconProvider", (), {"set_window_icon": lambda self, _widget: None}
        )()
        dialog = SqlConnectionDialog(icon_provider)
        dialog.server_input.setText("localhost")
        dialog.sql_auth_radio.setChecked(True)
        dialog.username_input.setText("user")
        dialog.password_input.setText("temporary-secret")
        dialog._accept_if_valid()
        self.assertIsNotNone(dialog.result_data())
        dialog.cleanup()
        self.assertIsNone(dialog.result_data())
        dialog.deleteLater()

    def test_properties_dialog_cleanup_releases_initial_connection_secret(self):
        from ost_visualizer.presentation.dialogs.sql_connection_dialog import (
            SqlConnectionDialogResult,
        )
        from ost_visualizer.presentation.dialogs.sql_database_dialog import (
            SqlDatabasePropertiesDialog,
            SqlDatabasePropertiesMode,
        )

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.assertIsNotNone(app)
        icon_provider = type(
            "IconProvider", (), {"set_window_icon": lambda self, _widget: None}
        )()
        connection = SqlConnectionDialogResult(
            SqlServerDatabaseLocation(server="localhost", database=""),
            "temporary-secret",
        )
        dialog = SqlDatabasePropertiesDialog(
            icon_provider,
            SqlDatabasePropertiesMode.OPEN,
            object(),
            object(),
            connection=connection,
        )
        dialog.cleanup()
        self.assertIsNone(dialog._initial_connection)
        self.assertEqual(dialog.password_input.text(), "")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
