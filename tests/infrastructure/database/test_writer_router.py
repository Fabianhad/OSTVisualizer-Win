from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
    fetch_optional_global_settings_row,
)
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
import unittest
import contextlib
import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import patch
import pyodbc
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    ConcurrencyToken,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    DatabaseMutationRequest as _DatabaseMutationRequest,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    ExpectedResourceVersion,
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
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.database.connection_wrapper import ConnectionWrapper
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
)
from ost_visualizer.infrastructure.mdb.connection_manager import MdbConnectionManager
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from ost_visualizer.infrastructure.mdb.schema_compatibility import MdbSchemaInspector
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.writer import (
    SqlProjectWriter,
    _OptimisticConflict,
    _RecordedMutation,
    _SqlMutationState,
)
from tests.helpers.sql.cleanup_support import (
    DatabaseMutationRequest as _cleanup_support_DatabaseMutationRequest,
    _AccessTransactionConnection as _cleanup_support__AccessTransactionConnection,
    _AccessTransactionConnections as _cleanup_support__AccessTransactionConnections,
    _CreationCursor as _cleanup_support__CreationCursor,
    _CredentialStore as _cleanup_support__CredentialStore,
    _RawCursor as _cleanup_support__RawCursor,
    _WriterCursor as _cleanup_support__WriterCursor,
    _WriterLease as _cleanup_support__WriterLease,
    _WriterManager as _cleanup_support__WriterManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
from tests.helpers.sql.database_foundation_support import (
    _CredentialStore as _database_foundation_support__CredentialStore,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
            patch.object(MdbWriter, "verify_plan_items_exist") as access_verify,
            patch.object(SqlProjectWriter, "verify_plan_items_exist") as sql_verify,
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
                return_value={"concrete": ["12"]},
            ) as access_lookup,
            patch.object(
                SqlProjectWriter,
                "_load_existing_uid_candidates_by_column",
                side_effect=AssertionError("Access import dispatched to SQL"),
            ),
            writer._backend_scope("example.mdb"),
        ):
            result = writer._load_existing_uid_candidates_by_column(
                connection, "CdnTypes", "Name"
            )
        self.assertEqual(result, {"concrete": ["12"]})
        access_lookup.assert_called_once_with(writer, connection, "CdnTypes", "Name")

    def test_writer_requires_an_explicit_backend_scope(self):
        writer = DatabaseProjectWriter(
            object(),
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(RuntimeError, "backend scope"):
            writer._current_backend()

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
        self.assertIs(writer._convert_sql_import_value("True", "bit"), True)
        with self.assertRaisesRegex(ValueError, "Boolean"):
            writer._convert_sql_import_value("maybe", "bit")
        with self.assertRaisesRegex(RuntimeError, "Unsupported SQL import type"):
            writer._convert_sql_import_value("value", "xml")
