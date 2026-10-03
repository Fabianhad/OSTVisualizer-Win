import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    MutationOutcomeStatus,
    ResourceRef,
    SynchronizationConflictKind,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseBackend,
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    MissingBidOwnedUidError,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    fetch_optional_global_settings_row,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
)
from ost_visualizer.infrastructure.mdb.connection_manager import (
    MdbConnectionManager,
    WriteBlockedError,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests.helpers.sql.cleanup_support import (
    DatabaseMutationRequest as _cleanup_support_DatabaseMutationRequest,
    _AccessTransactionConnections as _cleanup_support__AccessTransactionConnections,
    _CredentialStore as _cleanup_support__CredentialStore,
    _WriterCursor as _cleanup_support__WriterCursor,
    _WriterLease as _cleanup_support__WriterLease,
    _WriterManager as _cleanup_support__WriterManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
)
from tests.helpers.sql.database_foundation_support import (
    _CredentialStore as _database_foundation_support__CredentialStore,
)


class _RecordingCursor:
    def __init__(self, rows):
        self._rows = iter(rows)
        self.statements = []

    def execute(self, sql):
        self.statements.append(sql)
        return self

    def fetchone(self):
        return next(self._rows, None)


class AccessSettingsTableReferenceTests(unittest.TestCase):
    @staticmethod
    def _routed_writer():
        return DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            object(),
            object(),
        )

    def test_access_router_supplies_plain_settings_table_reference(self):
        writer = self._routed_writer()
        cursor = _RecordingCursor([(27,)])
        with writer._backend_scope("normal.mdb"):
            row = fetch_optional_global_settings_row(
                cursor,
                "[NextBidNo]",
                table_sql=writer._global_settings_read_table_sql(),
            )
        self.assertEqual(row, (27,))
        self.assertEqual(
            cursor.statements,
            ["SELECT [NextBidNo] FROM [Settings]"],
        )
        self.assertNotIn("WITH OWNERACCESS OPTION", cursor.statements[0].upper())
        self.assertNotIn("WITH (", cursor.statements[0].upper())

    def test_routers_supply_backend_specific_settings_table_references(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(object(), registry, object(), object())
        with writer._backend_scope("normal.mdb"):
            self.assertEqual(writer._global_settings_read_table_sql(), "[Settings]")
            self.assertEqual(writer._global_settings_write_table_sql(), "[Settings]")
        with writer._backend_scope(descriptor.database_id):
            self.assertEqual(
                writer._global_settings_read_table_sql(),
                "[dbo].[Settings] WITH (UPDLOCK, HOLDLOCK)",
            )
            self.assertEqual(
                writer._global_settings_write_table_sql(), "[dbo].[Settings]"
            )
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._global_settings_read_table_sql()


class WriterRouterSqlCleanupTests(unittest.TestCase):
    def test_access_writer_uses_access_schema_inspector(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope("example.mdb"):
            self.assertIsInstance(writer._schema(object()), MdbSchemaInspector)

    def test_sql_writer_uses_the_canonical_sql_write_schema(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope(descriptor.database_id):
            self.assertIsInstance(writer._schema(object()), CurrentSqlWriteSchema)

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
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        cursor = _Cursor()
        with writer._backend_scope("example.mdb"):
            uid = writer._next_uid(cursor, "BidTakeoffs")
        self.assertEqual(uid, 42)
        self.assertEqual(cursor.sql, "SELECT MAX([UID]) FROM [BidTakeoffs]")

    def test_access_writer_reserves_one_contiguous_uid_batch(self):
        class _Cursor:
            def __init__(self):
                self.sql = []

            def execute(self, sql):
                self.sql.append(sql)

            @staticmethod
            def fetchone():
                return (41,)

        class _Schema:
            @staticmethod
            def optional_table_missing(_table):
                return True

        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        cursor = _Cursor()
        with writer._backend_scope("example.mdb"):
            uids = tuple(
                writer._next_uids_preserving_references(
                    cursor, _Schema(), "BidTakeoffs", 3
                )
            )
        self.assertEqual(uids, (42, 43, 44))
        self.assertEqual(cursor.sql, ["SELECT MAX([UID]) FROM [BidTakeoffs]"])

    def test_sql_writer_router_uses_the_common_uid_allocator_contract(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope(descriptor.database_id):
            uid = writer._next_uid(object(), "BidTakeoffs")
        self.assertIsInstance(uid, int)
        with self.assertRaisesRegex(RuntimeError, "has not been generated"):
            str(uid)

    def test_writer_router_dispatches_plan_item_preflight_by_backend(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter, "verify_plan_items_exist", autospec=True
            ) as access_verify,
            patch.object(
                SqlProjectWriter, "verify_plan_items_exist", autospec=True
            ) as sql_verify,
        ):
            writer.verify_plan_items_exist("example.mdb", "1", ("2",), ())
            writer.verify_plan_items_exist(
                descriptor.database_id, "3", ("4",), (("5", "rect"),)
            )
        access_verify.assert_called_once_with(
            writer, "example.mdb", "1", ("2",), (), takeoff_ownership=()
        )
        sql_verify.assert_called_once_with(
            writer,
            descriptor.database_id,
            "3",
            ("4",),
            (("5", "rect"),),
            takeoff_ownership=(),
        )

    def test_sql_writer_batch_keeps_each_identity_deferred(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope(descriptor.database_id):
            uids = writer._next_uids_preserving_references(
                object(), object(), "BidTakeoffs", 3
            )
        self.assertEqual(len(uids), 3)
        self.assertEqual(len(set(uids)), 3)
        for uid in uids:
            with self.assertRaisesRegex(RuntimeError, "has not been generated"):
                str(uid)

    def test_sql_writer_does_not_replace_deferred_identity_with_access_reference_max(
        self,
    ):
        class _Cursor:
            def __init__(self):
                self.execute_count = 0

            def execute(self, _sql):
                self.execute_count += 1

            @staticmethod
            def fetchone():
                return (42,)

        class _Schema:
            @staticmethod
            def optional_table_missing(_table):
                return False

            @staticmethod
            def column_exists(_table, _column):
                return True

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        cursor = _Cursor()
        with writer._backend_scope(descriptor.database_id):
            uid = writer._next_uid_preserving_references(cursor, _Schema(), "Bids")
        self.assertEqual(cursor.execute_count, 0)
        with self.assertRaisesRegex(RuntimeError, "has not been generated"):
            str(uid)

    def test_sql_writer_rejects_shared_page_navigation_and_view_state_paths(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(RuntimeError, "per-user workspace"):
            writer.save_page_view_state(
                descriptor.database_id,
                "107",
                2.0,
                10.0,
                20.0,
            )
        with self.assertRaisesRegex(RuntimeError, "per-user workspace"):
            writer.save_bid_selected_page(
                descriptor.database_id,
                "7",
                "107",
            )

    def test_access_writer_delegates_page_navigation_and_view_state_paths(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter, "save_page_view_state", autospec=True, return_value=True
            ) as view_state,
            patch.object(
                MdbWriter, "save_bid_selected_page", autospec=True, return_value=False
            ) as selected_page,
        ):
            self.assertIs(
                writer.save_page_view_state("example.mdb", "107", 2.0, 10.0, 20.0),
                True,
            )
            self.assertIs(
                writer.save_bid_selected_page("example.mdb", "7", "107"), False
            )
        view_state.assert_called_once_with(
            writer, "example.mdb", "107", 2.0, 10.0, 20.0
        )
        selected_page.assert_called_once_with(writer, "example.mdb", "7", "107")

    def test_writer_router_error_policy_uses_backend_not_sql_context_presence(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        original = RuntimeError("row failure")
        resource_error = pyodbc.Error("HY001", "System resource exceeded")
        mutation_state = SimpleNamespace(operation_error=None)
        mutation_token = writer._active_mutation.set(mutation_state)
        try:
            with writer._backend_scope("example.mdb"):
                self.assertIs(writer._record_caught_mutation_error(original), False)
                self.assertIs(writer._is_access_resource_exceeded(resource_error), True)
            self.assertIsNone(mutation_state.operation_error)
            with writer._backend_scope(descriptor.database_id):
                self.assertIs(writer._record_caught_mutation_error(original), True)
                self.assertIs(
                    writer._is_access_resource_exceeded(resource_error), False
                )
            self.assertIs(mutation_state.operation_error, original)
        finally:
            writer._active_mutation.reset(mutation_token)

    def test_access_import_lookup_never_uses_sql_table_qualification(self):
        connection = object()
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter,
                "_load_existing_uid_candidates_by_column",
                autospec=True,
                return_value={"concrete": ["12"]},
            ) as access_lookup,
            patch.object(
                SqlProjectWriter,
                "_load_existing_uid_candidates_by_column",
                autospec=True,
                side_effect=AssertionError("Access import dispatched to SQL"),
            ),
            writer._backend_scope("example.mdb"),
        ):
            result = writer._load_existing_uid_candidates_by_column(
                connection, "CdnTypes", "Name"
            )
        self.assertEqual(result, {"concrete": ["12"]})
        access_lookup.assert_called_once_with(writer, connection, "CdnTypes", "Name")

    def test_sql_import_lookup_never_uses_access_lookup(self):
        connection = object()
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter,
                "_load_existing_uid_candidates_by_column",
                autospec=True,
                side_effect=AssertionError("SQL import dispatched to Access"),
            ),
            patch.object(
                SqlProjectWriter,
                "_load_existing_uid_candidates_by_column",
                autospec=True,
                return_value={"concrete": ["12"]},
            ) as sql_lookup,
            writer._backend_scope(descriptor.database_id),
        ):
            result = writer._load_existing_uid_candidates_by_column(
                connection, "CdnTypes", "Name"
            )
        self.assertEqual(result, {"concrete": ["12"]})
        sql_lookup.assert_called_once_with(writer, connection, "CdnTypes", "Name")

    def test_writer_requires_an_explicit_backend_scope(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._current_backend()

    def test_backend_scope_restores_the_enclosing_scope_even_after_an_error(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with writer._backend_scope("outer.mdb") as outer:
            with self.assertRaisesRegex(RuntimeError, "inner failure"):
                with writer._backend_scope(descriptor.database_id) as inner:
                    self.assertNotEqual(inner, outer)
                    self.assertEqual(writer._current_backend(), inner)
                    raise RuntimeError("inner failure")
            self.assertEqual(writer._current_backend(), outer)
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._current_backend()
        with self.assertRaises(LookupError):
            with writer._backend_scope("unregistered-sql-id"):
                pass

    def test_access_router_scopes_preconnection_validation_as_access(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id="example.mdb", session_id=None
            ),
            lambda _recorder: writer.delete_takeoffs("example.mdb", ["not-a-uid"]),
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertFalse(result.value)
        self.assertEqual(connections.connection_value.commits, 1)

    def test_access_router_dispatches_valid_takeoff_delete_to_mdb_helper(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter,
                "_run_delete_takeoffs",
                autospec=True,
            ) as access_delete,
            patch.object(
                SqlProjectWriter,
                "_run_delete_takeoffs",
                autospec=True,
            ) as sql_delete,
        ):
            result = writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id="example.mdb", session_id=None
                ),
                lambda _recorder: writer.delete_takeoffs("example.mdb", ["42"]),
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertTrue(result.value)
        access_delete.assert_called_once_with(
            writer, "example.mdb", [42], ACCESS_BULK_CHUNK_SIZE
        )
        sql_delete.assert_not_called()
        self.assertEqual(connections.connection_value.commits, 1)

    def test_sql_router_dispatches_takeoff_delete_to_sql_helper(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with (
            patch.object(
                MdbWriter,
                "_run_delete_takeoffs",
                autospec=True,
            ) as access_delete,
            patch.object(
                SqlProjectWriter,
                "_run_delete_takeoffs",
                autospec=True,
            ) as sql_delete,
        ):
            writer._run_delete_takeoffs(
                descriptor.database_id, [42], ACCESS_BULK_CHUNK_SIZE
            )
        sql_delete.assert_called_once_with(
            writer, descriptor.database_id, [42], ACCESS_BULK_CHUNK_SIZE
        )
        access_delete.assert_not_called()

    def test_sql_router_scopes_preconnection_validation_as_sql(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            sessions,
        )
        writer._sql_connections = manager
        with self.assertRaisesRegex(ValueError, "Invalid takeoff UID"):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
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
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = DatabaseProjectWriter(
            object(), registry, _cleanup_support__CredentialStore(), sessions
        )
        writer._sql_connections = manager
        with self.assertRaisesRegex(ValueError, "invalid literal"):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
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
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id="example.mdb", session_id=None
            ),
            lambda _recorder: writer.update_bid_job_status(
                "example.mdb", "not-a-bid", None
            ),
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertFalse(result.value)
        self.assertEqual(connections.connection_value.commits, 1)

    def test_access_router_nested_writes_commit_once_for_one_mutation(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )

        def operation(_recorder):
            with writer._connection("example.mdb"):
                pass
            with writer._connection("example.mdb"):
                pass
            return "complete"

        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id="example.mdb", session_id=None
            ),
            operation,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, "complete")
        self.assertEqual(connections.lease_count, 3)
        self.assertEqual(connections.connection_value.commits, 1)
        self.assertEqual(connections.connection_value.rollbacks, 0)

    def test_access_router_nested_failure_rolls_back_once(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )

        def operation(_recorder):
            with writer._connection("example.mdb"):
                raise RuntimeError("forced composite failure")

        with self.assertRaisesRegex(RuntimeError, "forced composite failure"):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id="example.mdb", session_id=None
                ),
                operation,
            )
        self.assertEqual(connections.connection_value.commits, 0)
        self.assertEqual(connections.connection_value.rollbacks, 1)

    def test_access_router_rolls_back_runtime_error_caught_by_shared_operation(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        original = RuntimeError("access row failure")
        with (
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_bid_scoped_uid_matches"
            ),
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_unique_bid_owned_uid_matches"
            ),
            patch.object(writer, "_next_uid", return_value=1),
            patch.object(
                writer,
                "_execute_annotation_insert",
                side_effect=original,
            ),
            self.assertRaises(RuntimeError) as captured,
        ):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id="example.mdb", session_id=None
                ),
                lambda _recorder: writer.insert_annotations("example.mdb", "1", [spec]),
            )
        self.assertIs(captured.exception, original)
        self.assertEqual(connections.connection_value.commits, 0)
        self.assertEqual(connections.connection_value.rollbacks, 1)

    def test_access_caught_data_failure_preserves_original_and_healthy_handle(self):
        original = pyodbc.DataError("22018", "type mismatch")

        class _Cursor:
            def __init__(self):
                self.rows = []

            def execute(self, _sql, *params):
                self.rows = [(param,) for param in params]

            def fetchall(self):
                return list(self.rows)

            def close(self):
                pass

        class _Connection:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0
                self.closes = 0

            def cursor(self):
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

            def close(self):
                self.closes += 1

        class _Schema:
            @staticmethod
            def require_column(_table, _column):
                pass

            @staticmethod
            def column_exists(_table, _column):
                return False

        raw = _Connection()
        connections = MdbConnectionManager()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )

        def fail_update(
            _cursor,
            _schema,
            _table,
            _values,
            _required_columns,
            _where_sql,
            _params,
            _operation,
            allow_empty=False,
        ):
            del allow_empty
            raise original

        writer._schema = lambda _connection: _Schema()
        writer._execute_update_values = fail_update
        with patch("pyodbc.connect", return_value=raw):
            with self.assertRaises(pyodbc.DataError) as captured:
                writer.execute(
                    _cleanup_support_DatabaseMutationRequest(
                        database_id="example.mdb", session_id=None
                    ),
                    lambda _recorder: writer.save_cover_sheet(
                        "example.mdb", "7", {"job_name": "Bid"}
                    ),
                )
        self.assertIs(captured.exception, original)
        self.assertEqual(raw.commits, 0)
        self.assertEqual(raw.rollbacks, 1)
        self.assertEqual(raw.closes, 0)
        connections.close()
        self.assertEqual(raw.closes, 1)

    def test_access_routed_annotation_database_failure_is_not_swallowed(self):
        original = pyodbc.DataError("22018", "annotation type mismatch")
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        spec = InsertAnnotationSpec(
            page_uid="10",
            annotation_type="rect",
            position=[1.0, 2.0, 3.0, 4.0],
            color="#ff0000",
            width=1.0,
        )
        with (
            patch.object(writer, "_schema", return_value=object()),
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_bid_scoped_uid_matches"
            ),
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_unique_bid_owned_uid_matches"
            ),
            patch.object(writer, "_next_uid", return_value=1),
            patch.object(writer, "_execute_annotation_insert", side_effect=original),
            self.assertRaises(pyodbc.DataError) as captured,
        ):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id="example.mdb",
                    session_id=None,
                ),
                lambda _recorder: writer.insert_annotations("example.mdb", "1", [spec]),
            )
        self.assertIs(captured.exception, original)
        self.assertEqual(connections.connection_value.commits, 0)
        self.assertEqual(connections.connection_value.rollbacks, 1)

    def test_sql_import_table_metadata_comes_from_canonical_schema(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )

        class _NoMetadataConnection:
            def cursor(self):
                raise AssertionError("writer queried a second schema inventory")

        with writer._backend_scope(descriptor.database_id):
            columns, types = writer._get_table_info(_NoMetadataConnection(), "Bids")
        self.assertIn("UID", columns)
        self.assertEqual(types["UID"], "int")
        canonical = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema).table_info("Bids")
        self.assertEqual((columns, types), canonical)

    def test_every_backend_specific_inherited_contract_is_dispatched_explicitly(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        connection, cursor, schema = object(), object(), object()
        raw_data, transform = object(), object()
        scoped_calls = (
            ("_get_table_info", (connection, "Bids")),
            ("_assign_next_bid_no", (connection, raw_data)),
            ("_load_existing_employee_uid_candidates_by_key", (connection,)),
            ("_insert_page_area_selection", (cursor, schema, 7, 8, 1)),
            ("_next_uid_preserving_references", (cursor, schema, "Bids")),
            ("_next_uids_preserving_references", (cursor, schema, "Bids", 3)),
            (
                "_filter_existing_write_values",
                (schema, "Bids", {"UID": 1}, ("UID",), "op"),
            ),
            (
                "_execute_insert_values",
                (cursor, schema, "Bids", {"UID": 1}, ("UID",), "op"),
            ),
        )
        for name, arguments in scoped_calls:
            for locator, selected_class, other_class in (
                ("example.mdb", MdbWriter, SqlProjectWriter),
                (descriptor.database_id, SqlProjectWriter, MdbWriter),
            ):
                with self.subTest(method=name, locator=locator):
                    with (
                        patch.object(
                            selected_class, name, autospec=True, return_value="routed"
                        ) as selected,
                        patch.object(
                            other_class,
                            name,
                            autospec=True,
                            side_effect=AssertionError(f"{name} used wrong backend"),
                        ) as other,
                        writer._backend_scope(locator),
                    ):
                        result = getattr(writer, name)(*arguments)
                    self.assertEqual(result, "routed")
                    selected.assert_called_once_with(writer, *arguments)
                    other.assert_not_called()
        scopeless_calls = (
            ("create_project", ("PROJECT", "Name"), "routed-project"),
            ("import_ost_data", ("DB", raw_data, transform, "5"), True),
        )
        for name, arguments, returned in scopeless_calls:
            for locator, selected_class, other_class in (
                ("example.mdb", MdbWriter, SqlProjectWriter),
                (descriptor.database_id, SqlProjectWriter, MdbWriter),
            ):
                with self.subTest(method=name, locator=locator):
                    call_arguments = (locator, *arguments[1:])
                    with (
                        patch.object(
                            selected_class, name, autospec=True, return_value=returned
                        ) as selected,
                        patch.object(
                            other_class,
                            name,
                            autospec=True,
                            side_effect=AssertionError(f"{name} used wrong backend"),
                        ) as other,
                    ):
                        result = getattr(writer, name)(*call_arguments)
                    self.assertEqual(result, returned)
                    selected.assert_called_once_with(writer, *call_arguments)
                    other.assert_not_called()

    def test_access_execute_reports_invalid_owner_as_failed_before_commit(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        request = _cleanup_support_DatabaseMutationRequest(
            database_id="example.mdb", session_id=None
        )

        def reject_owner(_recorder):
            raise MissingBidOwnedUidError("Bids has no row for UID 9")

        with self.assertLogs(writer.logger, level="ERROR"):
            result = writer.execute(request, reject_owner)
        self.assertEqual(result.operation_id, request.operation_id)
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.FAILED_BEFORE_COMMIT
        )
        self.assertEqual(result.failure_reason, "Bids has no row for UID 9")
        self.assertIsNone(result.value)
        self.assertEqual(connections.connection_value.commits, 0)
        self.assertEqual(connections.connection_value.rollbacks, 1)

    def test_access_execute_accepts_recorded_changes_without_persisting_them(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections,
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )

        def operation(recorder):
            recorder.record(
                ResourceRef("condition", "5", 1),
                ChangeOperation.UPDATE,
                changed_fields=("Name",),
                payload="{}",
            )
            return "recorded"

        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id="example.mdb", session_id=None
            ),
            operation,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, "recorded")
        self.assertEqual(result.resulting_versions, {})
        self.assertEqual(connections.connection_value.commits, 1)


class WriterRouterDatabaseDescriptorTests(unittest.TestCase):
    def test_writer_uses_one_inherited_operation_surface(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = DatabaseProjectWriter(
            object(),
            registry,
            _database_foundation_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        self.assertFalse(writer._is_sql("sample.mdb"))
        self.assertTrue(writer._is_sql(descriptor.database_id))
        self.assertNotIn("delete_bids", DatabaseProjectWriter.__dict__)
        self.assertNotIn("save_takeoff_positions", DatabaseProjectWriter.__dict__)

    def test_sql_import_conversion_rejects_noncanonical_values(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _database_foundation_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        self.assertEqual(writer._convert_sql_import_value("12", "int"), 12)
        self.assertIsNone(writer._convert_sql_import_value("", "int"))
        self.assertIsNone(writer._convert_sql_import_value("NULL", "int"))
        self.assertEqual(writer._convert_sql_import_value("1.5", "float"), 1.5)
        self.assertIs(writer._convert_sql_import_value("True", "bit"), True)
        self.assertIs(writer._convert_sql_import_value("-1", "bit"), True)
        self.assertIs(writer._convert_sql_import_value("False", "bit"), False)
        self.assertIs(writer._convert_sql_import_value("", "bit"), False)
        self.assertEqual(writer._convert_sql_import_value("text", "nvarchar"), "text")
        self.assertEqual(writer._convert_sql_import_value(5, "int"), 5)
        with self.assertRaisesRegex(ValueError, "Boolean"):
            writer._convert_sql_import_value("maybe", "bit")
        with self.assertRaises(ValueError):
            writer._convert_sql_import_value("12x", "int")
        with self.assertRaisesRegex(ValueError, "date value is invalid"):
            writer._convert_sql_import_value("not-a-date", "datetime2")
        with self.assertRaisesRegex(RuntimeError, "Unsupported SQL import type"):
            writer._convert_sql_import_value("value", "xml")


def _sql_descriptor_registry():
    registry = DatabaseDescriptorRegistry()
    descriptor = DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
        schema_version=SQL_SCHEMA_V1.version,
    )
    registry.register(descriptor)
    return registry, descriptor


class WriterRouterBackendBoundaryTests(unittest.TestCase):
    """Second pass: explicit dispatch, scope ownership and mutation boundaries.
    Access runs through the real MdbWriter code on fake or sqlite/real-Access
    connections; SQL runs through the real SqlProjectWriter code on fake leases
    (no live SQL Server exists here, so only the routing and the writer-side
    boundary logic are proven, never server behaviour).
    """

    def test_every_backend_divergent_member_is_overridden_by_the_router(self):
        # Python resolves DatabaseProjectWriter -> SqlProjectWriter -> MdbWriter,
        # so an Access locator would silently run SQL Server code for any
        # inherited member the two backends implement differently unless the
        # router dispatches it. Compare the two backends' own resolution.
        def resolved(cls, name):
            member = getattr(cls, name, None)
            return getattr(member, "__func__", member)

        names = {
            name
            for cls in (MdbWriter, SqlProjectWriter)
            for name in dir(cls)
            if not (name.startswith("__") and name.endswith("__"))
        }
        divergent = {
            name
            for name in names
            if name in dir(MdbWriter)
            and resolved(MdbWriter, name) is not resolved(SqlProjectWriter, name)
        }
        self.assertTrue(
            {
                "_connection",
                "_schema",
                "_next_uid",
                "_next_uid_preserving_references",
                "_next_uids_preserving_references",
                "_record_caught_mutation_error",
                "_is_access_resource_exceeded",
                "_global_settings_read_table_sql",
                "_global_settings_write_table_sql",
                "_execute_insert_values",
                "_filter_existing_write_values",
                "_assign_next_bid_no",
                "_get_table_info",
                "_load_existing_uid_candidates_by_column",
                "_load_existing_employee_uid_candidates_by_key",
                "_insert_page_area_selection",
                "_run_delete_takeoffs",
                "verify_plan_items_exist",
                "create_project",
                "import_ost_data",
            }
            <= divergent
        )
        self.assertEqual(divergent - set(vars(DatabaseProjectWriter)), set())
        # Backend-specific members that exist only on the SQL side must never
        # be reachable from the Access path except through SQL-guarded code.
        self.assertIn("execute", vars(DatabaseProjectWriter))

    def test_active_backend_scope_wins_over_the_current_registry(self):
        registry, descriptor = _sql_descriptor_registry()
        writer = DatabaseProjectWriter(object(), registry, object(), object())
        self.assertIs(writer._is_sql(descriptor.database_id), True)
        self.assertIs(writer._is_sql("example.mdb"), False)
        with writer._backend_scope("example.mdb"):
            self.assertIs(writer._is_sql(descriptor.database_id), False)
            self.assertEqual(writer._backend("anything"), DatabaseBackend.ACCESS)
            registry.unregister(descriptor.database_id)
        registry.register(descriptor)
        with writer._backend_scope(descriptor.database_id):
            self.assertIs(writer._is_sql("example.mdb"), True)
            registry.unregister(descriptor.database_id)
            self.assertIs(writer._is_sql(descriptor.database_id), True)
        with self.assertRaises(LookupError):
            writer._is_sql(descriptor.database_id)

    def test_access_connection_dispatches_to_the_transaction_owner_and_resets_scope(
        self,
    ):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections, DatabaseDescriptorRegistry(), object(), object()
        )
        with writer._connection("example.mdb") as connection:
            self.assertEqual(writer._current_backend(), DatabaseBackend.ACCESS)
            self.assertIs(connections.asserted_autocommit, False)
            self.assertEqual(connections.connection_value.commits, 0)
            self.assertIsNotNone(connection)
        self.assertEqual(connections.connection_value.commits, 1)
        self.assertEqual(connections.connection_value.rollbacks, 0)
        with self.assertRaises(RuntimeError):
            writer._current_backend()
        with self.assertRaisesRegex(ValueError, "failed body"):
            with writer._connection("example.mdb"):
                raise ValueError("failed body")
        self.assertEqual(connections.connection_value.commits, 1)
        self.assertEqual(connections.connection_value.rollbacks, 1)
        with self.assertRaises(RuntimeError):
            writer._current_backend()

    def test_sql_connection_outside_a_mutation_is_refused_and_scope_is_reset(self):
        registry, descriptor = _sql_descriptor_registry()

        class _NoAccessManager:
            def connection(self, *_args, **_kwargs):
                raise AssertionError("a SQL operation opened an Access connection")

        writer = DatabaseProjectWriter(
            _NoAccessManager(), registry, object(), DatabaseSessionRegistry()
        )
        with self.assertRaisesRegex(
            SqlInfrastructureError, "collaboration mutation transaction"
        ) as refused:
            with writer._connection(descriptor.database_id):
                self.fail("a SQL write connection was granted outside a mutation")
        self.assertEqual(refused.exception.details.code, SqlErrorCode.SESSION_EXPIRED)
        with self.assertRaises(RuntimeError):
            writer._current_backend()

    def test_sql_connection_inside_a_mutation_is_the_transaction_lease(self):
        registry, descriptor = _sql_descriptor_registry()
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")

        class _NoAccessManager:
            def connection(self, *_args, **_kwargs):
                raise AssertionError("a SQL operation opened an Access connection")

        writer = DatabaseProjectWriter(
            _NoAccessManager(), registry, _cleanup_support__CredentialStore(), sessions
        )
        writer._sql_connections = manager
        observed = []

        def operation(_recorder):
            with writer._connection(descriptor.database_id) as lease:
                observed.append(("lease", lease))
            with self.assertRaisesRegex(RuntimeError, "cannot switch databases"):
                with writer._connection("another-database-id"):
                    self.fail("a SQL mutation switched databases")
            return "unrecorded"

        # The operation records no affected resource, so the writer must roll
        # the transaction back; what matters here is the lease identity.
        with self.assertRaisesRegex(RuntimeError, "did not record"):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id, session_id="session-1"
                ),
                operation,
            )
        self.assertEqual(observed, [("lease", manager.lease)])
        self.assertIs(observed[0][1], manager.lease)
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        with self.assertRaises(RuntimeError):
            writer._current_backend()

    def test_sql_mutation_boundary_rejects_missing_or_changed_sessions_unopened(self):
        registry, descriptor = _sql_descriptor_registry()
        for label, registered in (
            ("no session registered", None),
            ("different session registered", "session-2"),
        ):
            with self.subTest(case=label):
                manager = _cleanup_support__WriterManager()
                sessions = DatabaseSessionRegistry()
                if registered is not None:
                    sessions.register(descriptor.database_id, registered)
                writer = DatabaseProjectWriter(
                    object(),
                    registry,
                    _cleanup_support__CredentialStore(),
                    sessions,
                )
                writer._sql_connections = manager
                calls = []
                result = writer.execute(
                    _cleanup_support_DatabaseMutationRequest(
                        database_id=descriptor.database_id,
                        session_id="session-1",
                    ),
                    lambda _recorder: calls.append("ran"),
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind, SynchronizationConflictKind.SESSION
                )
                self.assertEqual(calls, [])
                self.assertFalse(hasattr(manager, "autocommit"))
                self.assertEqual(manager.lease.cursors, [])
                self.assertEqual(
                    (manager.lease.commits, manager.lease.rollbacks), (0, 0)
                )

    def test_access_mutation_boundary_rejects_writes_while_ost_blocks_them(self):
        manager = MdbConnectionManager()
        manager.set_write_blocked(True)
        writer = DatabaseProjectWriter(
            manager, DatabaseDescriptorRegistry(), object(), object()
        )
        calls = []
        with patch("pyodbc.connect", side_effect=AssertionError("connection opened")):
            with self.assertRaises(WriteBlockedError):
                writer.execute(
                    _cleanup_support_DatabaseMutationRequest(
                        database_id="blocked.mdb", session_id=None
                    ),
                    lambda _recorder: calls.append("ran"),
                )
        self.assertEqual(calls, [])
        self.assertEqual(manager._active_leases, {})
        with self.assertRaises(RuntimeError):
            writer._current_backend()

    def test_access_execute_resets_its_backend_scope_after_every_outcome(self):
        connections = _cleanup_support__AccessTransactionConnections()
        writer = DatabaseProjectWriter(
            connections, DatabaseDescriptorRegistry(), object(), object()
        )
        request = _cleanup_support_DatabaseMutationRequest(
            database_id="example.mdb", session_id=None
        )
        seen = []

        def ok(_recorder):
            seen.append(writer._current_backend())
            return "ok"

        def failing(_recorder):
            seen.append(writer._current_backend())
            raise ValueError("operation failed")

        self.assertEqual(writer.execute(request, ok).value, "ok")
        with self.assertRaisesRegex(ValueError, "operation failed"):
            writer.execute(request, failing)
        self.assertEqual(seen, [DatabaseBackend.ACCESS, DatabaseBackend.ACCESS])
        self.assertIsNone(writer._active_backend.get())

    def test_router_scope_decides_uid_allocation_for_the_same_cursor_and_schema(self):
        # One fixture, both backends: Access scans MAX(UID) and the inbound
        # references (reference-safe range); SQL hands out database-generated
        # deferred identities and must not run any scan at all.
        registry, descriptor = _sql_descriptor_registry()
        writer = DatabaseProjectWriter(object(), registry, object(), object())
        statements = []

        class _Cursor:
            def execute(self, sql, *params):
                statements.append(sql)
                self._sql = sql

            def fetchone(self):
                # UID column max is 7; BidPages.MasterPageUID already names 12.
                return (12,) if "MasterPageUID" in self._sql else (7,)

        class _Schema:
            @staticmethod
            def optional_table_missing(table):
                return table != "BidPages"

            @staticmethod
            def column_exists(table, column):
                return (table, column) == ("BidPages", "MasterPageUID")

        with writer._backend_scope("example.mdb"):
            access_range = tuple(
                writer._next_uids_preserving_references(
                    _Cursor(), _Schema(), "BidPages", 3
                )
            )
            access_single = writer._next_uid_preserving_references(
                _Cursor(), _Schema(), "BidPages"
            )
        self.assertEqual(access_range, (13, 14, 15))
        self.assertEqual(access_single, 13)
        self.assertEqual(
            statements,
            [
                "SELECT MAX([UID]) FROM [BidPages]",
                "SELECT MAX([MasterPageUID]) FROM [BidPages]",
                "SELECT MAX([UID]) FROM [BidPages]",
                "SELECT MAX([MasterPageUID]) FROM [BidPages]",
            ],
        )
        del statements[:]
        with writer._backend_scope(descriptor.database_id):
            sql_range = writer._next_uids_preserving_references(
                _Cursor(), _Schema(), "BidPages", 3
            )
            sql_single = writer._next_uid_preserving_references(
                _Cursor(), _Schema(), "BidPages"
            )
            sql_plain = writer._next_uid(_Cursor(), "BidPages")
        self.assertEqual(statements, [])
        self.assertEqual(len(sql_range), 3)
        for identity in (*sql_range, sql_single, sql_plain):
            with self.assertRaisesRegex(RuntimeError, "has not been generated"):
                str(identity)
        self.assertEqual(len({*sql_range, sql_single, sql_plain}), 5)

    def test_access_chunk_size_stays_inside_the_access_parameter_limit(self):
        # Independent literals: Access allows ~255 parameters per statement and
        # bid-owned/bulk UID sets are bounded at 50 (one below, at, one above
        # are exercised by the persistence tests).
        self.assertEqual(ACCESS_BULK_CHUNK_SIZE, 50)
        self.assertLess(ACCESS_BULK_CHUNK_SIZE, 255)

    def test_access_error_policy_records_only_odbc_errors_inside_a_transaction(self):
        writer = DatabaseProjectWriter(
            object(), DatabaseDescriptorRegistry(), object(), object()
        )
        odbc_error = pyodbc.DataError("22018", "type mismatch")
        plain_error = ValueError("not a driver error")
        with writer._backend_scope("example.mdb"):
            # Outside an Access transaction nothing is recorded or re-raised.
            self.assertIs(writer._record_caught_mutation_error(odbc_error), False)
            token = writer._access_transaction_depth.set(1)
            try:
                self.assertIs(writer._record_caught_mutation_error(odbc_error), True)
                self.assertIs(writer._record_caught_mutation_error(plain_error), False)
            finally:
                writer._access_transaction_depth.reset(token)
            self.assertIs(writer._is_access_resource_exceeded(plain_error), False)
            self.assertIs(
                writer._is_access_resource_exceeded(
                    pyodbc.Error("42000", "System resource exceeded.")
                ),
                True,
            )
            self.assertIs(writer._is_access_resource_exceeded(odbc_error), False)

    def test_sql_mutation_boundary_refuses_a_client_without_write_permission(self):
        registry, descriptor = _sql_descriptor_registry()
        denied_snapshots = {
            "missing writer role": _cleanup_support__canonical_writer_permission_snapshot(
                roles=(0, 1, 1, 1, 1)
            ),
            "read-only database": _cleanup_support__canonical_writer_permission_snapshot(
                metadata=(
                    SQL_SCHEMA_V1.version,
                    SQL_SCHEMA_V1.checksum,
                    "READ_ONLY",
                    "ost_visualizer_only",
                    "disabled",
                    None,
                    1,
                    1,
                    1,
                    1,
                )
            ),
            "no marker write permission": _cleanup_support__canonical_writer_permission_snapshot(
                marker=(1, 0, 0, 0, 1)
            ),
        }
        for label, snapshot in denied_snapshots.items():
            with self.subTest(case=label):

                class _DeniedCursor(_cleanup_support__WriterCursor):
                    def fetchone(self, _snapshot=snapshot):
                        if "ostv_permission_snapshot" in self._last_sql:
                            return _snapshot
                        return super().fetchone()

                class _DeniedLease(_cleanup_support__WriterLease):
                    def cursor(self):
                        cursor = _DeniedCursor(self)
                        self.cursors.append(cursor)
                        return cursor

                manager = _cleanup_support__WriterManager()
                manager.lease = _DeniedLease()
                sessions = DatabaseSessionRegistry()
                sessions.register(descriptor.database_id, "session-1")
                writer = DatabaseProjectWriter(
                    object(),
                    registry,
                    _cleanup_support__CredentialStore(),
                    sessions,
                )
                writer._sql_connections = manager
                calls = []
                with self.assertRaises(SqlInfrastructureError):
                    writer.execute(
                        _cleanup_support_DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id="session-1",
                        ),
                        lambda _recorder: calls.append("ran"),
                    )
                self.assertEqual(calls, [])
                self.assertEqual(manager.lease.commits, 0)
                self.assertEqual(manager.lease.rollbacks, 1)
