from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _RecordedMutation
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    AuthoritativeMutationResult,
    ChangeOperation,
    CollaborationMutationType,
    CollaborationPollingPolicy,
    CollaborationShutdownState,
    CollaborationStatus,
    ConcurrencyToken,
    DatabaseChange,
    DatabaseChangeBatch,
    DatabaseChangePollResult,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DatabaseSession,
    DurableOperationResult,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    HydratedDatabaseChangeBatch,
    MutationExecutionResult,
    MutationOutcomeStatus,
    PendingMutationState,
    PendingSqlOperationRecord,
    PresenceMode,
    QueuedMutationRequest,
    QueuedMutationResult,
    ReconciliationFailureKind,
    ReconciliationResult,
    ResourceLock,
    ResourceRef,
    SynchronizationConflict,
    SynchronizationConflictKind,
    SynchronizationState,
    queued_takeoff_preview_uid,
    session_identities_equal,
)
from types import SimpleNamespace
import uuid
import unittest
from ost_visualizer.infrastructure.database.descriptor_registry import (
    DatabaseDescriptorRegistry,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
    fetch_optional_global_settings_row,
)
from ost_visualizer.infrastructure.database.writer_router import DatabaseProjectWriter
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
import contextlib
import json
import os
from tests.paths import REPO_ROOT
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
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
    credential_target_for,
)
from ost_visualizer.infrastructure.database.settings_cardinality import (
    GlobalSettingsCardinalityError,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
)
from ost_visualizer.infrastructure.sql.client_permissions import (
    SQL_CLIENT_DATABASE_ROLES,
    SQL_CLIENT_DIRECT_WRITE_TABLES,
    _sql_integer_values_match,
    apply_sql_client_permissions,
)
from ost_visualizer.infrastructure.sql.schema_definition import SQL_SCHEMA_V1
from ost_visualizer.infrastructure.sql.write_schema import CurrentSqlWriteSchema
from ost_visualizer.infrastructure.sql.writer import (
    SqlProjectWriter,
    _OptimisticConflict,
    _RecordedMutation,
    _SqlMutationState,
)
from tests.helpers.sql.cleanup_support import (
    DatabaseMutationRequest as _cleanup_support_DatabaseMutationRequest,
    _CreationCursor as _cleanup_support__CreationCursor,
    _CredentialStore as _cleanup_support__CredentialStore,
    _RawCursor as _cleanup_support__RawCursor,
    _WriterCursor as _cleanup_support__WriterCursor,
    _WriterLease as _cleanup_support__WriterLease,
    _WriterManager as _cleanup_support__WriterManager,
    _canonical_writer_permission_snapshot as _cleanup_support__canonical_writer_permission_snapshot,
)
from ost_visualizer.application.dtos.collaboration_dtos import (
    CollaborationMutationType,
    DatabaseMutationRequest,
    DatabaseMutationResult,
    DurableOperationResult,
    MutationOutcomeStatus,
    PageSettingsPayload,
    PendingMutationState,
    PendingSqlOperationRecord,
    PlanPropertyPayload,
    ProjectImportPayload,
    ProjectWritePayload,
    QueuedMutationRequest,
    QueuedMutationResult,
    ResourceRef,
)
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter, _SqlMutationState
from ost_visualizer.application.dtos.collaboration_dtos import PlanTakeoffOwnership
from ost_visualizer.infrastructure.database.annotation_storage import (
    ANNOTATION_TABLE_BY_TYPE,
)
from ost_visualizer.infrastructure.mdb.components.constants import (
    TAKEOFF_REFERENCE_TABLES,
    TAKEOFF_SELF_REFERENCE_COLUMNS,
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


class _RecordingWriterCursor(_cleanup_support__WriterCursor):
    def execute(self, sql, *params):
        self.connection.statements.append((sql, params))
        return super().execute(sql, *params)


class _RecordingWriterLease(_cleanup_support__WriterLease):
    def __init__(self):
        super().__init__()
        self.statements = []

    def cursor(self):
        cursor = _RecordingWriterCursor(self)
        self.cursors.append(cursor)
        return cursor


class _RecordingWriterManager(_cleanup_support__WriterManager):
    def __init__(self):
        self.lease = _RecordingWriterLease()


def _recording_writer(manager=None):
    registry = DatabaseDescriptorRegistry()
    descriptor = DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
        schema_version=SQL_SCHEMA_V1.version,
    )
    registry.register(descriptor)
    manager = manager or _RecordingWriterManager()
    sessions = DatabaseSessionRegistry()
    sessions.register(descriptor.database_id, "session-1")
    writer = SqlProjectWriter(
        registry,
        _cleanup_support__CredentialStore(),
        connection_manager=manager,
        session_registry=sessions,
    )
    return writer, descriptor, manager


class SqlSettingsLockTests(unittest.TestCase):
    def test_sql_settings_reference_retains_transaction_lock_hint(self):
        cursor = _RecordingCursor([(31,)])
        row = fetch_optional_global_settings_row(
            cursor,
            "[NextBidNo]",
            table_sql=SqlProjectWriter._global_settings_read_table_sql(),
        )
        self.assertEqual(row, (31,))
        self.assertEqual(
            cursor.statements,
            ["SELECT [NextBidNo] FROM [dbo].[Settings] " "WITH (UPDLOCK, HOLDLOCK)"],
        )
        # Only the locking read carries the hint; the write targets the plain table.
        self.assertEqual(
            SqlProjectWriter._global_settings_write_table_sql(), "[dbo].[Settings]"
        )


class WriterCollaborationTests(unittest.TestCase):
    def test_large_hierarchy_change_coalesces_to_global_hierarchy_resource(self):
        records = [
            _RecordedMutation(ResourceRef("project", str(uid)), ChangeOperation.UPDATE)
            for uid in range(451)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("projects_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_cross_bid_bulk_change_remains_bounded(self):
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(uid), uid),
                ChangeOperation.UPDATE,
            )
            for uid in range(451)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_bulk_coalescing_boundary_keeps_exact_records_up_to_450(self):
        records = [
            _RecordedMutation(ResourceRef("project", str(uid)), ChangeOperation.UPDATE)
            for uid in range(450)
        ]
        coalesced = SqlProjectWriter._coalesce_records(records)
        self.assertEqual(len(coalesced), 450)
        self.assertEqual({r.operation for r in coalesced}, {ChangeOperation.UPDATE})
        self.assertEqual({r.resource.resource_type for r in coalesced}, {"project"})

    def test_duplicate_records_keep_the_last_operation_in_resource_order(self):
        resource = ResourceRef("takeoff", "5", 8)
        other = ResourceRef("takeoff", "4", 8)
        records = [
            _RecordedMutation(resource, ChangeOperation.UPDATE),
            _RecordedMutation(other, ChangeOperation.CREATE),
            _RecordedMutation(resource, ChangeOperation.DELETE),
        ]
        self.assertEqual(
            SqlProjectWriter._deduplicate_records(records),
            (
                _RecordedMutation(other, ChangeOperation.CREATE),
                _RecordedMutation(resource, ChangeOperation.DELETE),
            ),
        )

    def test_single_bid_bulk_change_collapses_to_that_bids_collection(self):
        records = [
            _RecordedMutation(
                ResourceRef("condition", str(uid), 7), ChangeOperation.UPDATE
            )
            for uid in range(451)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "7", 7),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_mixed_family_bulk_change_keeps_one_collection_per_bid_and_family(self):
        records = [
            _RecordedMutation(
                ResourceRef("takeoff", str(uid), 1), ChangeOperation.UPDATE
            )
            for uid in range(300)
        ] + [
            _RecordedMutation(
                ResourceRef("condition", str(uid), 2), ChangeOperation.UPDATE
            )
            for uid in range(300)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "2", 2),
                    ChangeOperation.BULK_REFRESH,
                ),
                _RecordedMutation(
                    ResourceRef("takeoffs_collection", "1", 1),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_sql_writer_conflict_results_carry_resource_kind_and_versions(self):
        resource = ResourceRef("takeoff", "5", 8)
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )

        def run(error):
            writer = SqlProjectWriter.__new__(SqlProjectWriter)

            def fail(_request, _operation):
                raise error

            writer._execute_mutation_transaction = fail
            return writer.execute(request, lambda _recorder: True)

        locked = run(
            SqlInfrastructureError(SqlErrorDetails(SqlErrorCode.LOCKED, "held by Ana"))
        )
        self.assertEqual(locked.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(locked.operation_id, request.operation_id)
        self.assertEqual(locked.conflict.resource, resource)
        self.assertEqual(locked.conflict.reason, "held by Ana")
        self.assertEqual(locked.conflict.database_id, "database")
        self.assertIsNone(locked.conflict.expected)
        self.assertIsNone(locked.conflict.actual)
        expired = run(
            SqlInfrastructureError(
                SqlErrorDetails(SqlErrorCode.SESSION_EXPIRED, "session ended")
            )
        )
        self.assertEqual(expired.conflict.kind, SynchronizationConflictKind.SESSION)
        self.assertEqual(expired.conflict.resource, ResourceRef("database", "database"))
        expected = ConcurrencyToken(b"\x01" * 8)
        actual = ConcurrencyToken(b"\x02" * 8)
        optimistic = run(_OptimisticConflict(resource, expected, actual))
        self.assertEqual(
            optimistic.conflict.kind, SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY
        )
        self.assertEqual(optimistic.conflict.resource, resource)
        self.assertEqual(optimistic.conflict.expected, expected)
        self.assertEqual(optimistic.conflict.actual, actual)
        for code in (
            SqlErrorCode.TIMEOUT,
            SqlErrorCode.CONNECTION_FAILED,
            SqlErrorCode.PERMISSION_DENIED,
            SqlErrorCode.UNKNOWN,
        ):
            with self.subTest(code=code):
                error = SqlInfrastructureError(SqlErrorDetails(code, code.value))
                with self.assertRaises(SqlInfrastructureError) as raised:
                    run(error)
                self.assertIs(raised.exception, error)

    def test_sql_writer_classifies_session_and_lease_conflicts(self):
        sessions = DatabaseSessionRegistry()
        sessions.register("database", "current-session")
        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            SimpleNamespace(),
            session_registry=sessions,
        )
        session_result = writer.execute(
            DatabaseMutationRequest(
                database_id="database",
                session_id="stale-session",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="a" * 64,
            ),
            lambda _recorder: True,
        )
        self.assertEqual(session_result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(
            session_result.conflict.kind, SynchronizationConflictKind.SESSION
        )
        self.assertEqual(
            session_result.conflict.resource, ResourceRef("database", "database")
        )
        self.assertIn("session changed", session_result.conflict.reason)
        for error_code, expected_kind in (
            (SqlErrorCode.LOCKED, SynchronizationConflictKind.LEASE),
            (SqlErrorCode.SESSION_EXPIRED, SynchronizationConflictKind.SESSION),
        ):
            classified_writer = SqlProjectWriter.__new__(SqlProjectWriter)

            def fail(_request, _operation, code=error_code):
                raise SqlInfrastructureError(SqlErrorDetails(code, code.value))

            classified_writer._execute_mutation_transaction = fail
            result = classified_writer.execute(
                DatabaseMutationRequest(
                    database_id="database",
                    session_id=None,
                    operation_id=str(uuid.uuid4()),
                    mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                    request_hash="a" * 64,
                ),
                lambda _recorder: True,
            )
            self.assertEqual(result.conflict.kind, expected_kind)


class WriterSqlCleanupTests(unittest.TestCase):
    def test_sql_bid_sequence_uses_the_shared_zero_or_one_settings_contract(self):
        class _SettingsCursor:
            def __init__(self, rows):
                self.rows = rows
                self.read_index = 0
                self.executed = []

            def execute(self, sql, *params):
                self.executed.append(sql)
                if "SELECT [NextBidNo]" in sql:
                    self.read_index = 0
                elif "INSERT INTO [dbo].[Settings]" in sql:
                    self.rows.append(params[0])
                elif "UPDATE [dbo].[Settings]" in sql:
                    self.rows[:] = [params[0] for _row in self.rows]
                return self

            def fetchone(self):
                if self.read_index >= len(self.rows):
                    return None
                row = (self.rows[self.read_index],)
                self.read_index += 1
                return row

            def close(self):
                pass

        class _SettingsConnection:
            def __init__(self, rows):
                self.cursor_value = _SettingsCursor(rows)

            def cursor(self):
                return self.cursor_value

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        rows = []
        first = RawBidData(bid_row={})
        second = RawBidData(bid_row={})
        first_connection = _SettingsConnection(rows)
        second_connection = _SettingsConnection(rows)
        writer._assign_next_bid_no(first_connection, first)
        writer._assign_next_bid_no(second_connection, second)
        self.assertEqual(
            (first.bid_row["BidNo"], second.bid_row["BidNo"]),
            ("1", "2"),
        )
        self.assertEqual(rows, [3])
        self.assertTrue(
            all(
                "WITH (UPDLOCK, HOLDLOCK)" in sql
                for sql in (
                    first_connection.cursor_value.executed
                    + second_connection.cursor_value.executed
                )
                if "SELECT [NextBidNo]" in sql
            )
        )
        malformed = _SettingsConnection([7, 12])
        with self.assertRaises(GlobalSettingsCardinalityError):
            writer._assign_next_bid_no(malformed, RawBidData(bid_row={}))
        self.assertEqual(malformed.cursor_value.rows, [7, 12])

    def test_sql_mutation_uses_canonical_entity_version_token_column(self):
        source = (REPO_ROOT / "ost_visualizer/infrastructure/sql/writer.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("INSERTED.[Token] INTO @Versions", source)
        self.assertNotIn("OUTPUT INSERTED.[Version]", source)
        self.assertNotIn("MERGE [ostv].[EntityVersions]", source)

    def test_finish_mutation_writes_entity_versions_with_token_output(self):
        writer, descriptor, manager = _recording_writer()
        resource = ResourceRef("takeoff", "10", 8)
        state = _SqlMutationState(
            descriptor.database_id,
            manager.lease,
            _cleanup_support_DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
                resources=(resource,),
            ),
            records=[_RecordedMutation(resource, ChangeOperation.UPDATE)],
        )
        versions = writer._finish_mutation(state, "value")
        batch_sql = [
            sql for sql, _params in manager.lease.statements if "@Changes" in sql
        ]
        self.assertEqual(len(batch_sql), 1)
        self.assertEqual(batch_sql[0].count("INSERTED.[Token] INTO @Versions"), 2)
        self.assertNotIn("INSERTED.[Version]", batch_sql[0])
        self.assertEqual(versions, {resource: ConcurrencyToken((1).to_bytes(8, "big"))})

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

    def test_sql_plan_item_preflight_carries_expected_bid_into_locked_query(self):
        class _Cursor:
            def __init__(self):
                self.executed = None

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

            def execute(self, sql, *params):
                self.executed = (sql, params)

            @staticmethod
            def fetchone():
                return (0,)

        class _Lease:
            def __init__(self):
                self.cursor_value = _Cursor()

            def cursor(self):
                return self.cursor_value

        lease = _Lease()
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

        @contextlib.contextmanager
        def connection(_database_id):
            yield lease

        writer._connection = connection
        writer.verify_plan_items_exist("database", "8", ("101",), ())
        sql, params = lease.cursor_value.executed
        self.assertIn("DECLARE @ExpectedBidUID bigint=?", sql)
        self.assertIn("target.[BidUID]<>@ExpectedBidUID", sql)
        self.assertIn("WITH (UPDLOCK, HOLDLOCK)", sql)
        self.assertEqual(params[0], 8)
        self.assertEqual(json.loads(params[1]), [101])
        self.assertEqual(json.loads(params[2]), [])
        self.assertIn("1=0", sql)

    def test_sql_plan_item_preflight_reports_each_validation_status(self):
        annotation_type, annotation_table = next(iter(ANNOTATION_TABLE_BY_TYPE.items()))

        class _Cursor:
            def __init__(self, row):
                self.row = row
                self.executed = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *params):
                self.executed.append((sql, params))

            def fetchone(self):
                return self.row

        def verify(row, annotations=()):
            cursor = _Cursor(row)
            writer = SqlProjectWriter.__new__(SqlProjectWriter)
            writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

            @contextlib.contextmanager
            def connection(_database_id):
                yield SimpleNamespace(cursor=lambda: cursor)

            writer._connection = connection
            writer.verify_plan_items_exist(
                "database", "8", ("101", "101", "102"), annotations
            )
            return cursor

        cursor = verify((0,), ((" 5 ", annotation_type), ("5", annotation_type)))
        sql, params = cursor.executed[0]
        self.assertEqual(json.loads(params[1]), [101, 102])
        self.assertEqual(json.loads(params[2]), [{"table": annotation_table, "uid": 5}])
        self.assertIn(f"requested.[TableName]=N'{annotation_table}'", sql)
        self.assertNotIn("1=0", sql)
        for status, message, optimistic in (
            (1, "takeoff changed or was deleted", True),
            (2, "relationship graph changed", True),
            (3, "annotation changed or was deleted", False),
        ):
            with self.subTest(status=status):
                with self.assertRaisesRegex(SqlInfrastructureError, message) as raised:
                    verify((status,))
                self.assertEqual(raised.exception.details.code, SqlErrorCode.CONFLICT)
                self.assertEqual(
                    isinstance(raised.exception, _OptimisticConflict), optimistic
                )
                if optimistic:
                    self.assertEqual(
                        raised.exception.resource,
                        ResourceRef("takeoffs_collection", "8", 8),
                    )
        with self.assertRaisesRegex(RuntimeError, "invalid result"):
            verify((4,))
        with self.assertRaisesRegex(RuntimeError, "returned no result"):
            verify(None)
        with self.assertRaises(SqlInfrastructureError) as raised:
            verify((0,), (("5", "not-an-annotation-type"),))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONFLICT)

    def test_sql_property_preflight_checks_captured_ownership_after_graph_lock(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanTakeoffOwnership,
        )

        class Cursor:
            def __init__(self, rows):
                self.rows = rows
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *params):
                self.statements.append((sql, params))

            def fetchone(self):
                return (0,)

            def fetchall(self):
                return self.rows

        baseline = (
            PlanTakeoffOwnership("10", "20", "30", "1", "0"),
            PlanTakeoffOwnership("11", "20", "30", "1", "10"),
        )
        for parent_uid in (10, 12):
            with self.subTest(parent_uid=parent_uid):
                cursor = Cursor([(10, 20, 30, 1, None), (11, 20, 30, 1, parent_uid)])
                writer = SqlProjectWriter.__new__(SqlProjectWriter)
                writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

                @contextlib.contextmanager
                def connection(_database_id):
                    yield SimpleNamespace(cursor=lambda: cursor)

                writer._connection = connection
                if parent_uid == 10:
                    writer.verify_plan_items_exist(
                        "database", "7", ("10", "11"), (), takeoff_ownership=baseline
                    )
                else:
                    with self.assertRaises(SqlInfrastructureError) as caught:
                        writer.verify_plan_items_exist(
                            "database",
                            "7",
                            ("10", "11"),
                            (),
                            takeoff_ownership=baseline,
                        )
                    self.assertEqual(
                        caught.exception.details.code, SqlErrorCode.CONFLICT
                    )
                    self.assertIsInstance(caught.exception, _OptimisticConflict)
                    self.assertIn("ownership changed", str(caught.exception))
                self.assertIn("UPDLOCK, HOLDLOCK", cursor.statements[0][0])
                self.assertEqual(json.loads(cursor.statements[0][1][1]), [10, 11])
                self.assertIn(
                    "[BidPageUID], [BidConditionUID], [BidAreaUID], [ParentUID]",
                    cursor.statements[1][0],
                )

    def test_sql_property_preflight_rejects_each_ownership_drift(self):
        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, *_args):
                pass

            def fetchone(self):
                return (0,)

            def fetchall(self):
                return self.rows

        baseline = (PlanTakeoffOwnership("10", "20", "30", "1", "0"),)
        cases = (
            ("unchanged", [(10, 20, 30, 1, None)], False),
            ("page", [(10, 21, 30, 1, None)], True),
            ("condition", [(10, 20, 31, 1, None)], True),
            ("area", [(10, 20, 30, 2, None)], True),
            ("parent", [(10, 20, 30, 1, 9)], True),
            ("deleted", [], True),
        )
        for label, rows, rejected in cases:
            with self.subTest(label=label):
                cursor = Cursor(rows)
                writer = SqlProjectWriter.__new__(SqlProjectWriter)
                writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

                @contextlib.contextmanager
                def connection(_database_id):
                    yield SimpleNamespace(cursor=lambda: cursor)

                writer._connection = connection
                if not rejected:
                    writer.verify_plan_items_exist(
                        "database", "7", ("10",), (), takeoff_ownership=baseline
                    )
                    continue
                with self.assertRaises(_OptimisticConflict) as caught:
                    writer.verify_plan_items_exist(
                        "database", "7", ("10",), (), takeoff_ownership=baseline
                    )
                self.assertEqual(caught.exception.details.code, SqlErrorCode.CONFLICT)
                self.assertEqual(
                    caught.exception.resource,
                    ResourceRef("takeoffs_collection", "7", 7),
                )

    def test_sql_takeoff_snapshot_conflict_does_not_block_database_session(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            PlanTakeoffOwnership,
        )

        class Cursor:
            def __init__(self, status):
                self.status = status

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, _sql, *_params):
                pass

            def fetchone(self):
                return (self.status,)

            def fetchall(self):
                return [(10, 20, 30, 2, None)]

        for status in (0, 1, 2):
            with self.subTest(status=status):
                cursor = Cursor(status)
                writer = SqlProjectWriter.__new__(SqlProjectWriter)
                writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

                @contextlib.contextmanager
                def connection(_database_id):
                    yield SimpleNamespace(cursor=lambda: cursor)

                writer._connection = connection
                writer._execute_mutation_transaction = (
                    lambda _request, operation: operation(None)
                )
                result = writer.execute(
                    _cleanup_support_DatabaseMutationRequest(
                        database_id="database",
                        session_id="session",
                        resources=(ResourceRef("takeoff", "10", 7),),
                    ),
                    lambda _recorder: writer.verify_plan_items_exist(
                        "database",
                        "7",
                        ("10",),
                        (),
                        takeoff_ownership=(
                            PlanTakeoffOwnership("10", "20", "30", "1", "0"),
                        ),
                    ),
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind,
                    SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
                )
                self.assertEqual(
                    result.conflict.resource, ResourceRef("takeoffs_collection", "7", 7)
                )
                self.assertIn(
                    {
                        0: "ownership changed",
                        1: "takeoff changed or was deleted",
                        2: "relationship graph changed",
                    }[status],
                    result.conflict.reason,
                )

    def test_sql_lock_validation_batches_expected_rowversions(self):
        resource = ResourceRef("takeoffs_collection", "8", 8)
        expected = ConcurrencyToken(b"\x01" * 8)
        actual = b"\x02" * 8

        class _Cursor:
            def __init__(self):
                self.sql = ""
                self.parameters = ()
                self.execute_count = 0

            def execute(self, sql, *parameters):
                self.sql = sql
                self.parameters = parameters
                self.execute_count += 1
                return self

            @staticmethod
            def fetchone():
                return ("rowversion", None, 0, actual)

        request = _DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="a" * 64,
            resources=(resource,),
            expected_versions=(ExpectedResourceVersion(resource, expected),),
        )
        state = SimpleNamespace(request=request)
        cursor = _Cursor()
        with self.assertRaises(_OptimisticConflict) as raised:
            SqlProjectWriter._validate_mutation_locks(state, cursor, {resource})
        self.assertEqual(cursor.execute_count, 1)
        self.assertIn("@RequiredTokens", cursor.sql)
        self.assertIn("@ExpectedVersions", cursor.sql)
        expected_payload = json.loads(cursor.parameters[2])
        self.assertEqual(expected_payload[0]["expected_token"], str(expected))
        self.assertEqual(raised.exception.resource, resource)
        self.assertEqual(raised.exception.expected, expected)
        self.assertEqual(raised.exception.actual, ConcurrencyToken(actual))
        self.assertEqual(len(cursor.parameters), 13)
        self.assertEqual(
            json.loads(cursor.parameters[0]),
            [
                {
                    "ordinal": 0,
                    "resource_type": "takeoffs_collection",
                    "resource_id": "8",
                    "bid_uid": 8,
                }
            ],
        )
        self.assertEqual(cursor.parameters[3], "session-1")

    def test_sql_lock_validation_maps_every_violation_kind_to_its_message(self):
        resource = ResourceRef("takeoff", "10", 8)
        token = "ABCDEF01-2345-6789-ABCD-EF0123456789"
        expected = ConcurrencyToken(b"\x01" * 8)
        request = _DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="a" * 64,
            resources=(resource,),
            expected_versions=(ExpectedResourceVersion(resource, expected),),
            required_lock_tokens=(token, token.lower()),
            block_bid_child_locks=True,
            block_bid_active_editors=True,
        )
        state = SimpleNamespace(request=request)

        class _Cursor:
            def __init__(self, row):
                self.row = row
                self.parameters = ()

            def execute(self, _sql, *parameters):
                self.parameters = parameters

            def fetchone(self):
                return self.row

        SqlProjectWriter._validate_mutation_locks(state, _Cursor(None), {resource})
        for kind, owner, message in (
            ("item_owner", "Ana", "This item is being edited by Ana."),
            ("bid_owner", "Ana", "This bid is being changed by Ana."),
            ("child_owner", "Ana", "This bid contains an item being edited by Ana."),
            ("active_editor", "Ana", "This bid is actively being edited by Ana."),
            (
                "token_expired",
                None,
                "A required SQL edit lock expired before the write.",
            ),
            (
                "token_resource",
                None,
                "A SQL edit lock does not belong to this mutation.",
            ),
            (
                "owned_omitted",
                None,
                "The mutation did not present its owned SQL edit lock.",
            ),
            ("future_kind", None, "SQL edit-lock validation failed."),
        ):
            with self.subTest(kind=kind):
                cursor = _Cursor((kind, owner, None, None))
                with self.assertRaises(SqlInfrastructureError) as raised:
                    SqlProjectWriter._validate_mutation_locks(state, cursor, {resource})
                self.assertNotIsInstance(raised.exception, _OptimisticConflict)
                self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
                self.assertEqual(str(raised.exception), message)
                # Tokens are de-duplicated and compared case-insensitively.
                self.assertEqual(json.loads(cursor.parameters[1]), [token.lower()])
                self.assertEqual(cursor.parameters[5], True)
                self.assertEqual(cursor.parameters[7], True)
        deleted = _Cursor(("rowversion", None, 0, None))
        with self.assertRaises(_OptimisticConflict) as raised:
            SqlProjectWriter._validate_mutation_locks(state, deleted, {resource})
        self.assertIsNone(raised.exception.actual)
        self.assertEqual(raised.exception.expected, expected)
        with self.assertRaisesRegex(RuntimeError, "invalid ordinal"):
            SqlProjectWriter._validate_mutation_locks(
                state, _Cursor(("rowversion", None, 5, None)), {resource}
            )

    def test_sql_write_failure_rolls_back_and_closes_all_cursors(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with self.assertRaisesRegex(RuntimeError, "mid-operation"):

            def fail(_recorder):
                raise RuntimeError("mid-operation failure")

            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                fail,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        self.assertGreaterEqual(len(manager.lease.cursors), 3)
        self.assertTrue(
            all(cursor.close_count == 1 for cursor in manager.lease.cursors)
        )
        self.assertFalse(
            any(
                "INSERT INTO [ostv].[ChangeTransactions]" in sql
                for cursor in manager.lease.cursors
                for sql in cursor.executed
            )
        )

    def test_sql_write_without_record_fails_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
        with self.assertRaisesRegex(RuntimeError, "did not record"):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: True,
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)
        self.assertFalse(
            any(
                "INSERT INTO [ostv].[ChangeLog]" in sql
                for cursor in manager.lease.cursors
                for sql in cursor.executed
            )
        )

    def test_sql_mutation_locks_bids_first_and_shares_the_parent_bid(self):
        writer, descriptor, manager = _recording_writer()
        takeoff = ResourceRef("takeoff", "10", 8)
        other_bid_takeoff = ResourceRef("takeoff", "11", 3)
        bid = ResourceRef("bid", "3", 3)
        database = ResourceRef("database", descriptor.database_id)

        def mutate(recorder):
            recorder.record(takeoff, ChangeOperation.UPDATE)
            return True

        writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
                resources=(takeoff, other_bid_takeoff, bid, database),
            ),
            mutate,
        )
        _sql, params = next(
            statement
            for statement in manager.lease.statements
            if "DECLARE @RequestedLocks TABLE" in statement[0]
        )
        self.assertEqual(
            [
                (item["resource"], item["mode"])
                for item in sorted(json.loads(params[0]), key=lambda i: i["ordinal"])
            ],
            [
                # Bid resources first (Exclusive when targeted directly), then the
                # rest; a bid only implied by a child is locked Shared.
                ("OSTV:bid:3", "Exclusive"),
                ("OSTV:bid:8", "Shared"),
                ("OSTV:database:" + descriptor.database_id, "Exclusive"),
                ("OSTV:takeoff:10", "Exclusive"),
                ("OSTV:takeoff:11", "Exclusive"),
            ],
        )

    def test_sql_owned_lock_token_comparison_accepts_uuid_casing(self):
        lock_token = "abcdef01-2345-6789-abcd-ef0123456789"
        resource = ResourceRef("takeoffs_collection", "8", 8)
        writer, descriptor, manager = _recording_writer()
        with self.assertNoLogs(
            "ost_visualizer.infrastructure.sql.writer", level="DEBUG"
        ):
            result = writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                    resources=(resource,),
                    required_lock_tokens=(lock_token.upper(),),
                ),
                lambda recorder: (
                    recorder.record(resource, ChangeOperation.UPDATE),
                    True,
                )[1],
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.consumed_lock_tokens, (lock_token.upper(),))
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        validation_sql, validation_params = next(
            statement
            for statement in manager.lease.statements
            if "DECLARE @MutationResources TABLE" in statement[0]
        )
        # The server compares LOWER(token) against the lower-cased request tokens.
        self.assertIn("LOWER(CONVERT(nvarchar(36), locks.[LockToken]))", validation_sql)
        self.assertEqual(json.loads(validation_params[1]), [lock_token])
        _finish_sql, finish_params = next(
            statement
            for statement in manager.lease.statements
            if "DECLARE @Changes TABLE" in statement[0]
        )
        self.assertEqual(json.loads(finish_params[5]), [lock_token])

    def test_sql_mutation_preserves_error_swallowed_by_shared_mdb_operation(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
                _cleanup_support_DatabaseMutationRequest(
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
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )
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

    def test_sql_create_project_preserves_original_error_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
                _cleanup_support_DatabaseMutationRequest(
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

    def test_sql_create_project_inserts_through_the_mutation_connection(self):
        class _ProjectCursor(_RecordingWriterCursor):
            def fetchone(self):
                if "INSERT INTO [dbo].[BidProjects]" in self._last_sql:
                    return (41,)
                return super().fetchone()

        class _ProjectLease(_RecordingWriterLease):
            def cursor(self):
                cursor = _ProjectCursor(self)
                self.cursors.append(cursor)
                return cursor

        manager = _RecordingWriterManager()
        manager.lease = _ProjectLease()
        writer, descriptor, manager = _recording_writer(manager)

        def mutate(recorder):
            project_uid = writer.create_project(descriptor.database_id, "Project A")
            recorder.record(ResourceRef("project", project_uid), ChangeOperation.CREATE)
            return project_uid

        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id=descriptor.database_id, session_id="session-1"
            ),
            mutate,
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, "41")
        self.assertIn(ResourceRef("project", "41"), result.resulting_versions)
        self.assertEqual(
            [
                statement
                for statement in manager.lease.statements
                if "INSERT INTO [dbo].[BidProjects]" in statement[0]
            ],
            [
                (
                    "INSERT INTO [dbo].[BidProjects] ([Name]) "
                    "OUTPUT INSERTED.[UID] VALUES (?)",
                    ("Project A",),
                )
            ],
        )
        self.assertEqual(manager.lease.commits, 1)

    def test_sql_create_project_rejects_direct_write_outside_mutation_executor(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_cleanup_support__WriterManager(),
            session_registry=DatabaseSessionRegistry(),
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            writer.create_project(descriptor.database_id, "Project")
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SESSION_EXPIRED)

    def test_inherited_sql_takeoff_validation_error_is_raised_not_returned_as_false(
        self,
    ):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=_cleanup_support__WriterManager(),
            session_registry=DatabaseSessionRegistry(),
        )
        with self.assertRaisesRegex(ValueError, "Invalid takeoff UID"):
            writer.delete_takeoffs(descriptor.database_id, ["not-a-uid"])

    def test_sql_takeoff_delete_does_not_retry_access_driver_resource_error(self):
        writer, descriptor, manager = _recording_writer()
        with (
            patch.object(
                writer,
                "_run_delete_takeoffs",
                side_effect=pyodbc.Error("HY001", "System resource exceeded"),
            ) as delete,
            self.assertRaisesRegex(pyodbc.Error, "System resource exceeded"),
        ):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id, session_id="session-1"
                ),
                lambda _recorder: writer.delete_takeoffs(
                    descriptor.database_id, ["10"]
                ),
            )
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_takeoff_delete_clears_all_surviving_self_references(self):
        class Schema:
            def require_column(self, _table, _column):
                pass

        class Cursor:
            def __init__(self):
                self.sql = ""

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def execute(self, sql, *params):
                self.sql = sql
                self.params = params

            @staticmethod
            def fetchone():
                return (1,)

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc, _tb):
                return False

            def cursor(self):
                return self.cursor_value

        connection = Connection()
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._connection = lambda _database_id: connection
        writer._schema = lambda _connection: Schema()
        writer._run_delete_takeoffs("sql-db", [7, 7], ACCESS_BULK_CHUNK_SIZE)
        sql = connection.cursor_value.sql
        self.assertEqual(
            TAKEOFF_SELF_REFERENCE_COLUMNS,
            (
                "ParentUID",
                "TypGroupTakeoffUID",
                "TypPageTakeoffUID",
                "TypGroupMarkerUID",
            ),
        )
        final_delete = sql.index("DELETE target FROM [BidTakeoffs] target")
        for column in TAKEOFF_SELF_REFERENCE_COLUMNS:
            with self.subTest(column=column):
                self.assertIn(f"[{column}]=NULL", sql)
                # Survivors are cleared before the requested rows are deleted.
                self.assertLess(sql.index(f"[{column}]=NULL"), final_delete)
        for table in (*TAKEOFF_REFERENCE_TABLES, "BidPercents"):
            with self.subTest(table=table):
                self.assertIn(f"DELETE target FROM [{table}] target", sql)
                self.assertLess(
                    sql.index(f"DELETE target FROM [{table}]"), final_delete
                )
        self.assertIn("THROW 51000, 'The takeoff deletion was incomplete.'", sql)
        self.assertEqual(connection.cursor_value.params, ("[7]",))

    def test_sql_takeoff_delete_with_no_uids_does_not_touch_the_database(self):
        writer = SqlProjectWriter.__new__(SqlProjectWriter)

        def connection(_database_id):
            raise AssertionError("must not connect for an empty deletion")

        writer._connection = connection
        writer._run_delete_takeoffs("sql-db", [], ACCESS_BULK_CHUNK_SIZE)

    def test_sql_mutation_preserves_row_error_swallowed_inside_shared_mdb_operation(
        self,
    ):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
            patch(
                "ost_visualizer.infrastructure.mdb.components."
                "annotation_operations.require_existing_bid_scoped_uid_matches"
            ),
            patch.object(
                writer,
                "_execute_annotation_insert",
                side_effect=RuntimeError("nested annotation failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "nested annotation failure"),
        ):
            writer.execute(
                _cleanup_support_DatabaseMutationRequest(
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

    def test_sql_takeoff_write_does_not_retry_access_driver_resource_error(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
                _cleanup_support_DatabaseMutationRequest(
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

    def test_sql_page_rescale_cleanup_error_aborts_the_whole_mutation(self):
        class _RescaleCursor:
            @staticmethod
            def execute(_sql, *_params):
                raise pyodbc.Error("42000", "page rescale failure")

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
                _cleanup_support_DatabaseMutationRequest(
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
                    ),
                    schema_version=SQL_SCHEMA_V1.version,
                )
                registry.register(descriptor)
                manager = _cleanup_support__WriterManager()
                sessions = DatabaseSessionRegistry()
                sessions.register(descriptor.database_id, "session-1")
                writer = SqlProjectWriter(
                    registry,
                    _cleanup_support__CredentialStore(),
                    connection_manager=manager,
                    session_registry=sessions,
                )
                expected = f"{family} mutation failure"
                with (
                    patch.object(writer, helper, side_effect=RuntimeError(expected)),
                    self.assertRaisesRegex(RuntimeError, expected),
                ):
                    writer.execute(
                        _cleanup_support_DatabaseMutationRequest(
                            database_id=descriptor.database_id,
                            session_id="session-1",
                        ),
                        lambda _recorder: operation(writer, descriptor.database_id),
                    )
                self.assertEqual(manager.lease.commits, 0)
                self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_mutation_commits_exactly_one_transaction_marker(self):
        writer, descriptor, manager = _recording_writer()
        resource = ResourceRef("database", descriptor.database_id)

        def mutate(recorder):
            recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = _cleanup_support_DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
        )
        result = writer.execute(request, mutate)
        statements = [
            sql for cursor in manager.lease.cursors for sql in cursor.executed
        ]
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertIs(result.value, True)
        self.assertTrue(result.commit_attempted)
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
        self.assertEqual(
            result.resulting_versions,
            {resource: ConcurrencyToken((1).to_bytes(8, "big"))},
        )
        finish_sql, params = next(
            statement
            for statement in manager.lease.statements
            if "DECLARE @Changes TABLE" in statement[0]
        )
        self.assertEqual(
            json.loads(params[0]),
            [
                {
                    "ordinal": 0,
                    "resource_type": "database",
                    "resource_id": descriptor.database_id,
                    "bid_uid": None,
                    "is_deleted": False,
                    "is_feed": True,
                    "operation": "update",
                    "changed_fields": None,
                    "payload": None,
                }
            ],
        )
        self.assertEqual(
            params[1:5],
            ("session-1", "session-1", request.operation_id, "session-1"),
        )
        self.assertEqual(json.loads(params[5]), [])
        self.assertEqual(params[6:9], ("session-1", request.operation_id, "session-1"))
        self.assertEqual(json.loads(params[9]), ["database"])
        self.assertEqual(
            params[10:],
            (
                CollaborationMutationType.PROJECT_WRITE.value,
                "a" * 64,
                1,
                '{"value":true,"value_available":true}',
            ),
        )
        context_statements = [
            params
            for sql, params in manager.lease.statements
            if "sp_set_session_context" in sql
        ]
        # The permission probe binds the session/transaction; the final statement
        # clears them again so a pooled connection never keeps the identity.
        self.assertEqual(context_statements[0][:2], ("session-1", request.operation_id))
        self.assertEqual(context_statements[-1], ())

    def test_sql_commit_exception_is_classified_as_unknown_without_write_retry(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=manager,
            session_registry=sessions,
        )

        def fail_commit():
            manager.lease.commits += 1
            raise pyodbc.Error("08S01", "connection lost during commit")

        manager.lease.commit = fail_commit
        result = writer.execute(
            _cleanup_support_DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
            ),
            lambda recorder: (
                recorder.record(
                    ResourceRef("database", descriptor.database_id),
                    ChangeOperation.UPDATE,
                )
                or True
            ),
        )
        self.assertEqual(
            result.outcome_status,
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
        )
        self.assertTrue(result.commit_attempted)
        self.assertIsNone(result.value)
        self.assertEqual(result.resulting_versions, {})
        self.assertIsNone(result.conflict)
        self.assertEqual(manager.lease.commits, 1)
        self.assertEqual(manager.lease.rollbacks, 0)
        # The marker write ran exactly once; an uncertain commit is never replayed.
        self.assertEqual(
            sum(
                "INSERT INTO [ostv].[ChangeTransactions]" in sql
                for cursor in manager.lease.cursors
                for sql in cursor.executed
            ),
            1,
        )

    def test_bulk_feed_coalescing_preserves_every_entity_version(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _RecordingWriterManager()
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
            connection_manager=manager,
            session_registry=DatabaseSessionRegistry(),
        )
        resources = tuple(ResourceRef("takeoff", str(uid), 8) for uid in range(451))
        state = _SqlMutationState(
            descriptor.database_id,
            manager.lease,
            _cleanup_support_DatabaseMutationRequest(
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
        version_feed_batches = [
            sql for sql in statements if "DECLARE @Changes TABLE" in sql
        ]
        change_rows = [
            sql for sql in statements if "INSERT INTO [ostv].[ChangeLog]" in sql
        ]
        self.assertEqual(len(version_feed_batches), 1)
        self.assertNotIn("MERGE [ostv].[EntityVersions]", version_feed_batches[0])
        self.assertTrue(all(resource in versions for resource in resources))
        self.assertIn(ResourceRef("takeoffs_collection", "8", 8), versions)
        self.assertEqual(len(change_rows), 1)
        self.assertEqual(len(versions), 452)
        changes = json.loads(
            next(
                params
                for sql, params in manager.lease.statements
                if "DECLARE @Changes TABLE" in sql
            )[0]
        )
        self.assertEqual(len(changes), 452)
        feed = [change for change in changes if change["is_feed"]]
        self.assertEqual(
            [
                (c["resource_type"], c["resource_id"], c["bid_uid"], c["operation"])
                for c in feed
            ],
            [("takeoffs_collection", "8", 8, "bulk_refresh")],
        )
        self.assertEqual(
            sorted(c["resource_id"] for c in changes if not c["is_feed"]),
            sorted(str(uid) for uid in range(451)),
        )
        self.assertTrue(
            all(c["operation"] == "update" for c in changes if not c["is_feed"])
        )

    def test_sql_import_failure_preserves_original_error_and_rolls_back(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = _cleanup_support__WriterManager()
        sessions = DatabaseSessionRegistry()
        sessions.register(descriptor.database_id, "session-1")
        writer = SqlProjectWriter(
            registry,
            _cleanup_support__CredentialStore(),
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
                _cleanup_support_DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                ),
                lambda _recorder: writer.import_ost_data(
                    descriptor.database_id,
                    raw_data,
                    lambda data, _bid_offset, _cdn_map, _status_map, _employee_map, _pay_class_map: data,
                ),
            )
        self.assertEqual(manager.lease.commits, 0)
        self.assertEqual(manager.lease.rollbacks, 1)

    def test_sql_import_identity_result_keeps_table_scoped_annotation_uids(self):
        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        table_uid_maps = {
            "BidAnnotationRects": {"shared": "rect-new"},
            "BidAnnotationOvals": {"shared": "oval-new"},
        }
        with (
            patch.object(
                writer,
                "_connection",
                return_value=contextlib.nullcontext(object()),
            ),
            patch.object(writer, "_resolve_global_by_column", return_value={}),
            patch.object(writer, "_resolve_sql_employees", return_value={}),
            patch.object(writer, "_assign_next_bid_no"),
            patch.object(
                writer,
                "_write_remapped_identity_graph",
                return_value=table_uid_maps,
            ),
        ):
            result = writer.import_ost_data(
                "database",
                RawBidData(bid_row={"UID": "1"}),
                lambda data, *_maps: data,
            )
        self.assertEqual(
            result["annotation_uids"],
            {
                "rect/shared": "rect-new",
                "oval/shared": "oval-new",
            },
        )
        self.assertIs(result["table_uid_maps"], table_uid_maps)
        self.assertEqual(result["project_uids"], {})
        targeted = RawBidData(bid_row={"UID": "1"})
        with (
            patch.object(
                writer,
                "_connection",
                return_value=contextlib.nullcontext(object()),
            ),
            patch.object(writer, "_resolve_global_by_column", return_value={}),
            patch.object(writer, "_resolve_sql_employees", return_value={}),
            patch.object(writer, "_assign_next_bid_no"),
            patch.object(
                writer,
                "_write_remapped_identity_graph",
                return_value=table_uid_maps,
            ),
        ):
            targeted_result = writer.import_ost_data(
                "database", targeted, lambda data, *_maps: data, target_project_uid="9"
            )
        self.assertEqual(targeted_result["project_uids"], {"target": "9"})
        self.assertEqual(targeted.bid_row["BidProjectUID"], "9")
        self.assertIsNone(result["bid_uids"].get("1"))

    def test_sql_import_rebinds_bid_owned_rows_to_inserted_bid_identity(self):
        class _Connection:
            def cursor(self):
                return _cleanup_support__RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
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
            identity_maps = writer._write_remapped_identity_graph(
                _Connection(), raw_data
            )
        self.assertEqual(inserted[1][0], "BidLayers")
        self.assertEqual(inserted[1][1]["BidUID"], 101)
        self.assertEqual(
            identity_maps,
            {
                "Bids": {"source-bid": "101"},
                "BidLayers": {"source-layer": "202"},
            },
        )

    def test_sql_import_does_not_remap_resolved_global_identity(self):
        class _Connection:
            def cursor(self):
                return _cleanup_support__RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
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
                return _cleanup_support__RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
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

    def test_sql_import_reconstructs_takeoff_parent_identity(self):
        class _Connection:
            def cursor(self):
                return _cleanup_support__RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "Name": "Imported"},
            bid_tables={
                "BidPages": [{"UID": "20", "BidUID": "1", "Name": "Page"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": None,
                    },
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": "30",
                    },
                ]
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, row))
            return len(inserted) * 100 + 1

        def table_info(_connection, table):
            columns = {"UID", "BidUID", "Name"}
            if table == "BidPages":
                columns.add("BidPageUID")
            if table == "BidTakeoffs":
                columns.update({"BidPageUID", "ParentUID"})
            return columns, {}

        with (
            patch.object(writer, "_get_table_info", side_effect=table_info),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            writer._write_remapped_identity_graph(_Connection(), raw_data)
        child_row = inserted[3]
        self.assertEqual(child_row[0], "BidTakeoffs")
        self.assertEqual(child_row[1]["ParentUID"], 301)

    def test_sql_import_updates_takeoff_parent_inserted_after_its_child(self):
        class _Cursor:
            def __init__(self):
                self.executed = []

            def execute(self, sql, *params):
                self.executed.append((sql, params))

            def close(self):
                pass

        cursor = _Cursor()

        class _Connection:
            @staticmethod
            def cursor():
                return cursor

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "Name": "Imported"},
            bid_tables={"BidPages": [{"UID": "20", "BidUID": "1", "Name": "Page"}]},
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": "30",
                    },
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": None,
                    },
                ]
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, dict(row)))
            return len(inserted) * 100 + 1

        def table_info(_connection, table):
            columns = {"UID", "BidUID", "Name"}
            if table == "BidPages":
                columns.add("BidPageUID")
            if table == "BidTakeoffs":
                columns.update({"BidPageUID", "ParentUID"})
            return columns, {}

        with (
            patch.object(writer, "_get_table_info", side_effect=table_info),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            identity_maps = writer._write_remapped_identity_graph(
                _Connection(), raw_data
            )
        child, parent = inserted[2], inserted[3]
        self.assertIsNone(child[1]["ParentUID"])
        self.assertIsNone(parent[1]["ParentUID"])
        self.assertEqual(identity_maps["BidTakeoffs"], {"31": "301", "30": "401"})
        self.assertEqual(
            cursor.executed,
            [
                (
                    "UPDATE [dbo].[BidTakeoffs] SET [ParentUID]=? WHERE [UID]=?",
                    (401, 301),
                )
            ],
        )

    def test_sql_import_nulls_zero_empty_and_null_text_references(self):
        class _Connection:
            @staticmethod
            def cursor():
                return _cleanup_support__RawCursor()

        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "Name": "Imported"},
            bid_tables={"BidPages": [{"UID": "20", "BidUID": "1", "Name": "Page"}]},
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "30",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": "0",
                        "BidAreaUID": "",
                    },
                    {
                        "UID": "31",
                        "BidUID": "1",
                        "BidPageUID": "20",
                        "ParentUID": "NULL",
                        "BidAreaUID": "0",
                    },
                ]
            },
        )
        inserted = []

        def insert(_connection, table, row, _table_info):
            inserted.append((table, dict(row)))
            return len(inserted) * 100 + 1

        def table_info(_connection, table):
            columns = {"UID", "BidUID", "Name"}
            if table in ("BidPages", "BidTakeoffs"):
                columns.add("BidPageUID")
            if table == "BidTakeoffs":
                columns.update({"ParentUID", "BidAreaUID"})
            return columns, {}

        with (
            patch.object(writer, "_get_table_info", side_effect=table_info),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            writer._write_remapped_identity_graph(_Connection(), raw_data)
        takeoffs = [row for table, row in inserted if table == "BidTakeoffs"]
        self.assertEqual(len(takeoffs), 2)
        for row in takeoffs:
            self.assertIsNone(row["ParentUID"])
            self.assertIsNone(row["BidAreaUID"])
            # The page reference is remapped to the inserted page identity.
            self.assertEqual(row["BidPageUID"], 201)

    def test_writer_guard_rejects_stale_database_metadata(self):
        class _StaleMetadataCursor(_cleanup_support__WriterCursor):
            def fetchone(self):
                if "ostv_permission_snapshot" in self._last_sql:
                    return _cleanup_support__canonical_writer_permission_snapshot(
                        metadata=(
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
                    )
                return super().fetchone()

        class _StaleMetadataLease(_cleanup_support__WriterLease):
            def cursor(self):
                cursor = _StaleMetadataCursor(self)
                self.cursors.append(cursor)
                return cursor

        lease = _StaleMetadataLease()
        with self.assertRaisesRegex(SqlInfrastructureError, "not writable") as raised:
            SqlProjectWriter._require_sql_client_editability(lease)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(len(lease.cursors), 1)
        self.assertTrue(all(cursor.close_count == 1 for cursor in lease.cursors))

    def test_writer_guard_rejects_disabled_change_tracking(self):
        class _TrackingDisabledCursor(_cleanup_support__WriterCursor):
            def fetchone(self):
                if "ostv_permission_snapshot" in self._last_sql:
                    return _cleanup_support__canonical_writer_permission_snapshot(
                        metadata=(
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
                    )
                return super().fetchone()

        class _TrackingDisabledLease(_cleanup_support__WriterLease):
            def cursor(self):
                cursor = _TrackingDisabledCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(SqlInfrastructureError, "not writable") as raised:
            SqlProjectWriter._require_sql_client_editability(_TrackingDisabledLease())
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)

    def test_writer_guard_rejects_missing_builtin_client_role(self):
        class _MissingRoleCursor(_cleanup_support__WriterCursor):
            def fetchone(self):
                if "ostv_permission_snapshot" in self._last_sql:
                    return _cleanup_support__canonical_writer_permission_snapshot(
                        roles=(1, 0, 1, 1, 1)
                    )
                return super().fetchone()

        class _MissingRoleLease(_cleanup_support__WriterLease):
            def cursor(self):
                cursor = _MissingRoleCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(
            SqlInfrastructureError, "required SQL database roles"
        ) as raised:
            SqlProjectWriter._require_sql_client_editability(_MissingRoleLease())
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertTrue(raised.exception.read_only_required)

    def test_writer_guard_rejects_missing_collaboration_marker_permission(self):
        class _MissingMarkerPermissionCursor(_cleanup_support__WriterCursor):
            def fetchone(self):
                if "ostv_permission_snapshot" in self._last_sql:
                    return _cleanup_support__canonical_writer_permission_snapshot(
                        marker=(1, 1, 0, 0, 0)
                    )
                return super().fetchone()

        class _MissingMarkerPermissionLease(_cleanup_support__WriterLease):
            def cursor(self):
                cursor = _MissingMarkerPermissionCursor(self)
                self.cursors.append(cursor)
                return cursor

        with self.assertRaisesRegex(
            SqlInfrastructureError, "collaboration permissions"
        ) as raised:
            SqlProjectWriter._require_sql_client_editability(
                _MissingMarkerPermissionLease()
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)

    def test_writer_guard_accepts_canonical_snapshot_and_binds_session_context(self):
        request = _cleanup_support_DatabaseMutationRequest(
            database_id="database", session_id="session-9"
        )
        lease = _RecordingWriterLease()
        state = _SqlMutationState("database", lease, request)
        SqlProjectWriter._require_sql_client_editability(lease, state)
        self.assertEqual(len(lease.statements), 1)
        sql, params = lease.statements[0]
        self.assertTrue(sql.startswith("EXEC sys.sp_set_session_context"))
        self.assertEqual(params[:2], ("session-9", request.operation_id))
        self.assertTrue(all(cursor.close_count == 1 for cursor in lease.cursors))
        unbound = _RecordingWriterLease()
        SqlProjectWriter._require_sql_client_editability(unbound)
        self.assertNotIn("sp_set_session_context", unbound.statements[0][0])

    def test_writer_guard_rejects_each_noncanonical_permission_snapshot(self):
        canonical_metadata = (
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
        cases = (
            (
                "wrong checksum",
                {"metadata": (1, "0" * 64) + canonical_metadata[2:]},
                SqlErrorCode.SCHEMA_MISMATCH,
            ),
            (
                "read-only database",
                {
                    "metadata": canonical_metadata[:2]
                    + ("READ_ONLY",)
                    + canonical_metadata[3:]
                },
                SqlErrorCode.SCHEMA_MISMATCH,
            ),
            (
                "unvalidated mixed writer",
                {
                    "metadata": canonical_metadata[:3]
                    + ("mixed_application", "disabled")
                    + canonical_metadata[5:]
                },
                SqlErrorCode.SCHEMA_MISMATCH,
            ),
            (
                "snapshot isolation off",
                {"metadata": canonical_metadata[:8] + (0, 1)},
                SqlErrorCode.SCHEMA_MISMATCH,
            ),
            (
                "direct writes to protected table",
                {"collaboration": (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 0, 1)},
                SqlErrorCode.PERMISSION_DENIED,
            ),
            (
                "invalid writable table grants",
                {"collaboration": (len(SQL_CLIENT_DIRECT_WRITE_TABLES), 1, 0)},
                SqlErrorCode.PERMISSION_DENIED,
            ),
            (
                "missing writable table",
                {"collaboration": (len(SQL_CLIENT_DIRECT_WRITE_TABLES) - 1, 0, 0)},
                SqlErrorCode.PERMISSION_DENIED,
            ),
            (
                "marker table writable",
                {"marker": (1, 1, 1, 0, 1)},
                SqlErrorCode.PERMISSION_DENIED,
            ),
            (
                "default schema not dbo",
                {"roles": (1, 1, 1, 1, 0)},
                SqlErrorCode.PERMISSION_DENIED,
            ),
        )
        for label, overrides, code in cases:
            with self.subTest(label=label):

                class _Cursor(_cleanup_support__WriterCursor):
                    snapshot = _cleanup_support__canonical_writer_permission_snapshot(
                        **overrides
                    )

                    def fetchone(self):
                        if "ostv_permission_snapshot" in self._last_sql:
                            return self.snapshot
                        return super().fetchone()

                class _Lease(_cleanup_support__WriterLease):
                    def cursor(self):
                        cursor = _Cursor(self)
                        self.cursors.append(cursor)
                        return cursor

                lease = _Lease()
                with self.assertRaises(SqlInfrastructureError) as raised:
                    SqlProjectWriter._require_sql_client_editability(lease)
                self.assertEqual(raised.exception.details.code, code)
                self.assertTrue(all(c.close_count == 1 for c in lease.cursors))


class SqlWriterRecoveryIdentityTests(unittest.TestCase):
    def test_recovered_operation_requires_matching_request_identity(self):
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="1" * 64,
        )
        state = _SqlMutationState("database", object(), request)
        result = SqlProjectWriter._recovered_operation_result(
            state,
            (
                request.mutation_type,
                request.request_hash,
                1,
                '{"value":["100"],"value_available":true}',
            ),
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["100"])
        self.assertTrue(result.commit_attempted)
        self.assertEqual(result.operation_id, request.operation_id)
        self.assertEqual(result.consumed_lock_tokens, ())
        with self.assertRaisesRegex(Exception, "reused with a different request"):
            SqlProjectWriter._recovered_operation_result(
                state,
                (request.mutation_type, "2" * 64, 1, "{}"),
            )

    def test_recovered_operation_rejects_each_mismatched_or_corrupt_record(self):
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="1" * 64,
        )
        state = _SqlMutationState("database", object(), request)
        payload = '{"value":true,"value_available":true}'
        other_type = CollaborationMutationType.PROJECT_WRITE.value
        self.assertNotEqual(other_type, request.mutation_type)
        for label, row, error_type, text in (
            (
                "mutation type",
                (other_type, request.request_hash, 1, payload),
                SqlInfrastructureError,
                "reused with a different request",
            ),
            (
                "request hash",
                (request.mutation_type, "2" * 64, 1, payload),
                SqlInfrastructureError,
                "reused with a different request",
            ),
            (
                "format version",
                (request.mutation_type, request.request_hash, 2, payload),
                SqlInfrastructureError,
                "reused with a different request",
            ),
            (
                "invalid json",
                (request.mutation_type, request.request_hash, 1, "not json"),
                RuntimeError,
                "invalid result payload",
            ),
            (
                "null payload",
                (request.mutation_type, request.request_hash, 1, None),
                RuntimeError,
                "invalid result payload",
            ),
            (
                "value unavailable",
                (
                    request.mutation_type,
                    request.request_hash,
                    1,
                    '{"value":true,"value_available":false}',
                ),
                RuntimeError,
                "cannot reconstruct",
            ),
            (
                "missing availability flag",
                (request.mutation_type, request.request_hash, 1, '{"value":true}'),
                RuntimeError,
                "cannot reconstruct",
            ),
            (
                "unexpected extra key",
                (
                    request.mutation_type,
                    request.request_hash,
                    1,
                    '{"value":true,"value_available":true,"extra":1}',
                ),
                RuntimeError,
                "cannot reconstruct",
            ),
        ):
            with self.subTest(label=label):
                with self.assertRaisesRegex(error_type, text) as raised:
                    SqlProjectWriter._recovered_operation_result(state, row)
                if error_type is SqlInfrastructureError:
                    self.assertEqual(
                        raised.exception.details.code, SqlErrorCode.CONFLICT
                    )


class WriterRelationshipTests(unittest.TestCase):
    def test_sql_import_rejects_ambiguous_master_name(self):
        cursor = SimpleNamespace(
            execute=lambda *_args: None,
            fetchall=lambda: [(50, "Open"), (51, "Open")],
            close=lambda: None,
        )
        connection = SimpleNamespace(cursor=lambda: cursor)
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._get_table_info = lambda *_args: (set(), {})
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"JobStatuses": [{"UID": "94", "Name": "Open"}]},
        )
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*JobStatuses.Name"):
            writer._resolve_global_by_column(
                connection, raw_data, "JobStatuses", "Name"
            )

    def test_sql_import_rejects_ambiguous_employee_business_key(self):
        cursor = SimpleNamespace(
            execute=lambda *_args: None,
            fetchall=lambda: [
                (60, "E100", "Alice", "One", ""),
                (61, "e100", "Alex", "Two", ""),
            ],
            close=lambda: None,
        )
        connection = SimpleNamespace(cursor=lambda: cursor)
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._get_table_info = lambda *_args: (set(), {})
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "95", "EmployeeNo": "E100", "FirstName": "Imported"}
                ]
            },
        )
        with (
            patch.object(writer, "_insert_identity_raw") as insert,
            self.assertRaisesRegex(RuntimeError, "ambiguous.*Employees"),
        ):
            writer._resolve_sql_employees(connection, raw_data, {}, {})
        insert.assert_not_called()

    def test_sql_import_reuses_existing_master_rows_and_inserts_a_missing_one_once(
        self,
    ):
        def connection_with(rows):
            cursor = SimpleNamespace(
                execute=lambda *_args: None,
                fetchall=lambda: rows,
                close=lambda: None,
            )
            return SimpleNamespace(cursor=lambda: cursor)

        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._get_table_info = lambda *_args: (set(), {})
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "JobStatuses": [
                    {"UID": "94", "Name": "Open"},
                    {"UID": "95", "Name": "Closed"},
                ],
                "CdnTypes": [{"UID": "7", "Name": "concrete"}],
            },
        )
        with patch.object(writer, "_insert_identity_raw", return_value=77) as insert:
            statuses = writer._resolve_global_by_column(
                connection_with([(50, "Open")]), raw_data, "JobStatuses", "Name"
            )
            # CdnTypes names match case-insensitively; other masters do not.
            cdn_types = writer._resolve_global_by_column(
                connection_with([(60, " Concrete ")]), raw_data, "CdnTypes", "Name"
            )
        self.assertEqual(statuses, {"94": "50", "95": "77"})
        self.assertEqual(cdn_types, {"7": "60"})
        self.assertEqual(insert.call_count, 1)
        self.assertEqual(
            insert.call_args.args[1:3],
            ("JobStatuses", {"UID": "95", "Name": "Closed"}),
        )
        self.assertEqual(
            writer._resolve_global_by_column(
                connection_with([]),
                RawBidData(bid_row={"UID": "1"}),
                "JobStatuses",
                "Name",
            ),
            {},
        )

    def test_sql_import_rejects_ambiguous_incoming_master_names_before_inserting(self):
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._get_table_info = lambda *_args: (set(), {})
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "JobStatuses": [
                    {"UID": "94", "Name": "Open"},
                    {"UID": "95", "Name": "Open"},
                ]
            },
        )
        connection = SimpleNamespace(
            cursor=lambda: SimpleNamespace(
                execute=lambda *_args: None, fetchall=lambda: [], close=lambda: None
            )
        )
        with (
            patch.object(writer, "_insert_identity_raw") as insert,
            self.assertRaisesRegex(RuntimeError, "ambiguous.*JobStatuses.Name"),
        ):
            writer._resolve_global_by_column(
                connection, raw_data, "JobStatuses", "Name"
            )
        insert.assert_not_called()

    def test_sql_import_maps_new_employee_references_and_rejects_unknown_ones(self):
        def connection_with(rows):
            cursor = SimpleNamespace(
                execute=lambda *_args: None,
                fetchall=lambda: rows,
                close=lambda: None,
            )
            return SimpleNamespace(cursor=lambda: cursor)

        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._get_table_info = lambda *_args: (set(), {})
        existing = [(60, "E100", "Alice", "One", "")]
        raw_data = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "95", "EmployeeNo": " e100 "},
                    {
                        "UID": "96",
                        "EmployeeNo": "E200",
                        "PayClassUID": "1",
                        "AccessLevelUID": "0",
                    },
                ]
            },
        )
        with patch.object(writer, "_insert_identity_raw", return_value=88) as insert:
            result = writer._resolve_sql_employees(
                connection_with(existing), raw_data, {"1": "9"}, {}
            )
        self.assertEqual(result, {"95": "60", "96": "88"})
        insert.assert_called_once()
        inserted_row = insert.call_args.args[2]
        self.assertEqual(inserted_row["PayClassUID"], "9")
        self.assertIsNone(inserted_row["AccessLevelUID"])
        with (
            patch.object(writer, "_insert_identity_raw") as insert,
            self.assertRaisesRegex(RuntimeError, "unknown PayClassUID"),
        ):
            writer._resolve_sql_employees(connection_with(existing), raw_data, {}, {})
        insert.assert_not_called()
