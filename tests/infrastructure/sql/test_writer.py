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
import re
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
from tests.helpers.sql.strict_sql_fakes import strict_cursor, strict_manager
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
    manager = strict_manager(manager or _RecordingWriterManager())
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
                self.close_count = 0

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
                self.close_count += 1

        class _SettingsConnection:
            def __init__(self, rows):
                self.cursor_value = _SettingsCursor(rows)

            def cursor(self):
                return strict_cursor(self.cursor_value)

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
        reads = [
            sql
            for sql in (
                first_connection.cursor_value.executed
                + second_connection.cursor_value.executed
            )
            if "SELECT [NextBidNo]" in sql
        ]
        self.assertEqual(len(reads), 2)
        self.assertTrue(all("WITH (UPDLOCK, HOLDLOCK)" in sql for sql in reads))
        # every allocation opens one cursor and closes it again
        self.assertEqual(first_connection.cursor_value.close_count, 1)
        self.assertEqual(second_connection.cursor_value.close_count, 1)
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
                return strict_cursor(self.cursor_value)

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
                return strict_cursor(self.cursor_value)

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
                yield SimpleNamespace(cursor=lambda: strict_cursor(cursor))

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
                    yield SimpleNamespace(cursor=lambda: strict_cursor(cursor))

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
                    yield SimpleNamespace(cursor=lambda: strict_cursor(cursor))

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
                    yield SimpleNamespace(cursor=lambda: strict_cursor(cursor))

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
            SqlProjectWriter._validate_mutation_locks(
                state, strict_cursor(cursor), {resource}
            )
        self.assertEqual(cursor.execute_count, 1)
        self.assertIn("@RequiredTokens", cursor.sql)
        self.assertIn("@ExpectedVersions", cursor.sql)
        expected_payload = json.loads(cursor.parameters[2])
        self.assertEqual(expected_payload[0]["expected_token"], str(expected))
        self.assertEqual(raised.exception.resource, resource)
        self.assertEqual(raised.exception.expected, expected)
        self.assertEqual(raised.exception.actual, ConcurrencyToken(actual))
        # 13 owner/token/rowversion parameters + the trailing bid_lock_exempt flag
        # of the bid_locked branch (decision B1), False for an ordinary request
        self.assertEqual(len(cursor.parameters), 14)
        self.assertIs(cursor.parameters[-1], False)
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

        SqlProjectWriter._validate_mutation_locks(
            state, strict_cursor(_Cursor(None)), {resource}
        )
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
                    SqlProjectWriter._validate_mutation_locks(
                        state, strict_cursor(cursor), {resource}
                    )
                self.assertNotIsInstance(raised.exception, _OptimisticConflict)
                self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
                self.assertEqual(str(raised.exception), message)
                # Tokens are de-duplicated and compared case-insensitively.
                self.assertEqual(json.loads(cursor.parameters[1]), [token.lower()])
                self.assertEqual(cursor.parameters[5], True)
                self.assertEqual(cursor.parameters[7], True)
        deleted = _Cursor(("rowversion", None, 0, None))
        with self.assertRaises(_OptimisticConflict) as raised:
            SqlProjectWriter._validate_mutation_locks(
                state, strict_cursor(deleted), {resource}
            )
        self.assertIsNone(raised.exception.actual)
        self.assertEqual(raised.exception.expected, expected)
        with self.assertRaisesRegex(RuntimeError, "invalid ordinal"):
            SqlProjectWriter._validate_mutation_locks(
                state, strict_cursor(_Cursor(("rowversion", None, 5, None))), {resource}
            )

    def test_sql_write_failure_rolls_back_and_closes_all_cursors(self):
        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
            schema_version=SQL_SCHEMA_V1.version,
        )
        registry.register(descriptor)
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
            connection_manager=strict_manager(_cleanup_support__WriterManager()),
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
            connection_manager=strict_manager(_cleanup_support__WriterManager()),
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
                return strict_cursor(self.cursor_value)

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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
                manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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
        manager = strict_manager(_RecordingWriterManager())
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
        manager = strict_manager(_cleanup_support__WriterManager())
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


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    MAX_PARAMETERS,
    Reply,
    StrictSqlServer,
    StrictSqlViolation,
    applock_rules,
    sql_server_error,
)


class _StrictMutationServer(StrictSqlServer):
    """Strict pyodbc model that answers the SQL writer's mutation protocol.
    Only the statements `SqlProjectWriter.execute` issues are scripted (session
    context + permission snapshot, operation/resource application locks, lock
    validation, the version/feed/marker batch, session-context clear); anything
    else must be scripted by the test, otherwise the strict fake refuses it.
    """

    def __init__(self, *, marker=None, violation=None, session_alive=1, bid_locks=None):
        super().__init__()
        # a batch that leaves SET NOCOUNT OFF fronts its rows with count-only
        # results (strict_sql_fakes.count_dml_result_sets): fetchone would fail
        self.model_result_counts = True
        self.marker = marker
        self.violation = violation
        # BidLockState: Bids/JobStatuses rows the writer's bid_locked branch is run on
        self.bid_locks = bid_locks
        self.session_alive = session_alive
        self.versions = 0
        applock_rules(self)
        self.on("ostv_permission_snapshot", self._permission_snapshot)
        self.on("DECLARE @LockResult int", self._prepare)
        self.on("DECLARE @MutationResources TABLE", self._validate)
        self.on("DECLARE @Changes TABLE", self._finish)
        self.on("@key=N'ostv_session_id', @value=NULL", Reply())

    @staticmethod
    def _permission_snapshot(_call):
        return Reply.rows(_cleanup_support__canonical_writer_permission_snapshot())

    def _prepare(self, call):
        mode = re.search(r"@LockMode=N'(\w+)'", call.sql).group(1)
        code = self.applocks.acquire(call.connection, call.params[0], mode)
        if code < 0:
            return Reply.rows((code, None, None, None, None, self.session_alive))
        if self.marker is not None:
            return Reply.rows((code, *self.marker, self.session_alive))
        return Reply.rows((code, None, None, None, None, self.session_alive))

    def _validate(self, call):
        if self.violation is not None:
            return Reply.rows(self.violation)
        if self.bid_locks is not None:
            rows = self.bid_locks.violation_rows(call)
            if rows:
                return Reply.rows(rows[0])
        return Reply.rows()

    def _finish(self, call):
        rows = []
        for change in call.json(0):
            self.versions += 1
            rows.append((change["ordinal"], self.versions.to_bytes(8, "big")))
        return Reply.rows(*rows)

    def other_session(self):
        """A second physical connection (another client) for lock conflicts."""
        return self.connect("other-session", autocommit=False)


def _strict_writer(server=None, *, session="session-1"):
    server = server or _StrictMutationServer()
    registry = DatabaseDescriptorRegistry()
    descriptor = DatabaseDescriptor.for_sql_server(
        SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST"),
        schema_version=SQL_SCHEMA_V1.version,
    )
    registry.register(descriptor)
    sessions = DatabaseSessionRegistry()
    sessions.register(descriptor.database_id, session)
    writer = SqlProjectWriter(
        registry,
        _cleanup_support__CredentialStore(),
        connection_manager=server.manager(),
        session_registry=sessions,
    )
    return writer, descriptor, server


def _record_database_update(descriptor):
    resource = ResourceRef("database", descriptor.database_id)

    def mutate(recorder):
        recorder.record(resource, ChangeOperation.UPDATE)
        return True

    return resource, mutate


class WriterStrictTransactionTests(unittest.TestCase):
    """SqlProjectWriter.execute against the strict pyodbc/T-SQL model."""

    def _request(self, descriptor, **kwargs):
        return _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            **kwargs,
        )

    def test_successful_mutation_follows_the_transaction_protocol(self):
        writer, descriptor, server = _strict_writer()
        resource, mutate = _record_database_update(descriptor)
        request = self._request(descriptor, resources=(resource,))
        with server.patched():
            result = writer.execute(request, mutate)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            result.resulting_versions,
            {resource: ConcurrencyToken((1).to_bytes(8, "big"))},
        )
        self.assertFalse(server.connect_calls[0]["autocommit"])
        kinds = server.event_kinds(1)
        # the whole mutation is ONE transaction: exactly one commit, after every
        # cursor of the mutation was closed, followed only by the context clear
        self.assertEqual(kinds.count("commit"), 1)
        self.assertEqual(kinds.count("rollback"), 0)
        commit_index = kinds.index("commit")
        before = kinds[:commit_index]
        self.assertEqual(before.count("cursor_open"), before.count("cursor_close"))
        self.assertEqual(
            kinds[commit_index:],
            ["commit", "cursor_open", "execute", "cursor_close", "close"],
        )
        statements = server.statements(1)
        self.assertIn("ostv_permission_snapshot", statements[0])
        self.assertIn("DECLARE @LockResult int", statements[1])
        self.assertIn("DECLARE @RequestedLocks TABLE", statements[2])
        self.assertIn("DECLARE @MutationResources TABLE", statements[3])
        self.assertIn("DECLARE @Changes TABLE", statements[4])
        self.assertIn("@value=NULL", statements[5])
        # transaction-owned application locks are gone once the transaction ended
        self.assertEqual(
            server.applocks.holders(f"OSTV:operation:{request.operation_id}"), []
        )
        self.assertEqual(
            server.applocks.holders(f"OSTV:database:{descriptor.database_id}"), []
        )
        server.assert_everything_closed()

    def test_every_statement_stays_below_the_parameter_limit_for_large_mutations(self):
        # 2101 recorded resources (one above the 2100-parameter request limit)
        # travel as JSON, so the statement keeps a constant parameter count.
        writer, descriptor, server = _strict_writer()
        resources = tuple(
            ResourceRef("takeoff", str(uid), 8) for uid in range(MAX_PARAMETERS + 1)
        )

        def mutate(recorder):
            for resource in resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = self._request(descriptor, resources=resources)
        with server.patched():
            result = writer.execute(request, mutate)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(result.resulting_versions), MAX_PARAMETERS + 2)
        widest = max(
            len(params)
            for connection in server.connections
            for cursor in connection.cursors
            for _sql, params in cursor.executed
        )
        # the same statements (and parameter counts) as a one-resource mutation
        small_writer, small_descriptor, small_server = _strict_writer()
        small_resource, small_mutate = _record_database_update(small_descriptor)
        with small_server.patched():
            small_writer.execute(
                self._request(small_descriptor, resources=(small_resource,)),
                small_mutate,
            )
        small_widest = max(
            len(params)
            for connection in small_server.connections
            for cursor in connection.cursors
            for _sql, params in cursor.executed
        )
        self.assertEqual(widest, small_widest)
        self.assertLess(widest, MAX_PARAMETERS)

    def test_application_locks_are_taken_in_sorted_order_and_conflict_returns_lease_conflict(
        self,
    ):
        writer, descriptor, server = _strict_writer()
        takeoff = ResourceRef("takeoff", "10", 8)
        other_bid_takeoff = ResourceRef("takeoff", "11", 3)
        bid = ResourceRef("bid", "3", 3)
        database = ResourceRef("database", descriptor.database_id)
        request = self._request(
            descriptor, resources=(takeoff, other_bid_takeoff, bid, database)
        )
        holder = server.other_session()
        # another client already owns takeoff 11: the whole mutation must fail
        # with a lease conflict and release everything it had acquired
        server.applocks.acquire(holder, "OSTV:takeoff:11", "Exclusive")
        _resource, mutate = _record_database_update(descriptor)
        with server.patched():
            result = writer.execute(request, mutate)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(result.conflict.resource, request.resources[0])
        attempted = [
            (resource, code)
            for number, resource, _mode, code in server.applocks.log
            if number != holder.number
        ]
        self.assertEqual(
            attempted,
            [
                (f"OSTV:operation:{request.operation_id}", 0),
                ("OSTV:bid:3", 0),
                ("OSTV:bid:8", 0),
                (f"OSTV:database:{descriptor.database_id}", 0),
                ("OSTV:takeoff:10", 0),
                ("OSTV:takeoff:11", -1),
            ],
        )
        raw = next(c for c in server.connections if c is not holder)
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertNotIn(
            "DECLARE @Changes TABLE", " ".join(server.statements(raw.number))
        )
        # the failed attempt released its transaction-owned locks
        self.assertEqual(server.applocks.holders("OSTV:takeoff:10"), [])
        self.assertEqual(server.applocks.holders("OSTV:takeoff:11"), [holder.number])
        self.assertTrue(raw.closed)

    def test_same_operation_lock_held_elsewhere_is_a_conflict_not_a_second_write(self):
        writer, descriptor, server = _strict_writer()
        resource, mutate = _record_database_update(descriptor)
        request = self._request(descriptor, resources=(resource,))
        holder = server.other_session()
        server.applocks.acquire(
            holder, f"OSTV:operation:{request.operation_id}", "Exclusive"
        )
        executed = []
        with server.patched():
            result = writer.execute(
                request, lambda recorder: executed.append(1) or mutate(recorder)
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        # a refused operation lock is a LEASE conflict on the request's resource,
        # never a session expiry (the session itself is alive in this scenario)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(
            result.conflict.reason,
            "Another session is resolving the same SQL operation.",
        )
        self.assertEqual(result.conflict.resource, resource)
        self.assertEqual(executed, [])
        self.assertEqual(server.connections[0].commits, 0)
        self.assertNotIn(
            "DECLARE @RequestedLocks TABLE", " ".join(server.statements(1))
        )

    def test_expired_session_is_a_session_conflict_without_running_the_operation(self):
        server = _StrictMutationServer(session_alive=0)
        writer, descriptor, server = _strict_writer(server)
        resource, mutate = _record_database_update(descriptor)
        executed = []
        with server.patched():
            result = writer.execute(
                self._request(descriptor, resources=(resource,)),
                lambda recorder: executed.append(1) or mutate(recorder),
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.SESSION)
        self.assertEqual(executed, [])
        self.assertEqual(server.connections[0].commits, 0)

    def test_rowversion_mismatch_and_missing_row_are_distinct_optimistic_conflicts(
        self,
    ):
        resource = ResourceRef("takeoff", "10", 8)
        expected = ConcurrencyToken(b"\x01" * 8)
        for label, actual in (
            ("changed", b"\x02" * 8),
            ("row missing", None),
        ):
            with self.subTest(label=label):
                server = _StrictMutationServer(
                    violation=("rowversion", None, 0, actual)
                )
                writer, descriptor, server = _strict_writer(server)
                request = self._request(
                    descriptor,
                    resources=(resource,),
                    expected_versions=(ExpectedResourceVersion(resource, expected),),
                )
                _res, mutate = _record_database_update(descriptor)
                with server.patched():
                    result = writer.execute(request, mutate)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind,
                    SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
                )
                self.assertEqual(result.conflict.expected, expected)
                self.assertEqual(
                    result.conflict.actual,
                    None if actual is None else ConcurrencyToken(actual),
                )
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
                self.assertNotIn(
                    "DECLARE @Changes TABLE", " ".join(server.statements(1))
                )

    def test_uncertain_commit_is_reported_unknown_and_never_replayed(self):
        for committed in (True, False):
            with self.subTest(server_applied_commit=committed):
                writer, descriptor, server = _strict_writer()
                server.fail(
                    "commit",
                    sql_server_error("08S01", "Communication link failure"),
                    committed=committed,
                )
                _resource, mutate = _record_database_update(descriptor)
                with server.patched():
                    result = writer.execute(self._request(descriptor), mutate)
                self.assertEqual(
                    result.outcome_status, MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
                )
                self.assertTrue(result.commit_attempted)
                self.assertEqual(result.resulting_versions, {})
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                self.assertEqual(
                    sum("DECLARE @Changes TABLE" in s for s in server.statements(1)), 1
                )
                self.assertEqual(len(server.connections), 1)
                self.assertTrue(raw.closed)

    def test_interrupt_during_commit_is_not_followed_by_a_rollback(self):
        writer, descriptor, server = _strict_writer()
        server.fail("commit", KeyboardInterrupt())
        _resource, mutate = _record_database_update(descriptor)
        with server.patched():
            with self.assertRaises(KeyboardInterrupt):
                writer.execute(self._request(descriptor), mutate)
        raw = server.connections[0]
        # once the commit began its outcome is unknown: never roll back or retry
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        self.assertTrue(raw.closed)

    def test_failed_rollback_does_not_replace_the_operation_error(self):
        writer, descriptor, server = _strict_writer()
        server.fail("rollback", sql_server_error("08S01", "Communication link failure"))

        def fail(_recorder):
            raise RuntimeError("operation failed")

        with server.patched():
            with self.assertRaisesRegex(RuntimeError, "operation failed"):
                writer.execute(self._request(descriptor), fail)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertTrue(raw.closed)
        server.assert_everything_closed()

    def test_statement_errors_roll_back_once_and_are_classified_never_unknown_commit(
        self,
    ):
        for label, error, code in (
            (
                "foreign key",
                sql_server_error(
                    "23000",
                    "The INSERT statement conflicted with the FOREIGN KEY constraint",
                    547,
                ),
                SqlErrorCode.CONSTRAINT_FAILED,
            ),
            (
                "duplicate key",
                sql_server_error(
                    "23000", "Violation of PRIMARY KEY constraint 'PK_x'", 2627
                ),
                SqlErrorCode.CONSTRAINT_FAILED,
            ),
            (
                "deadlock victim",
                sql_server_error(
                    "40001",
                    "Transaction was deadlocked and has been chosen as the deadlock victim",
                    1205,
                ),
                SqlErrorCode.UNKNOWN,
            ),
            (
                "connection lost mid statement",
                sql_server_error("08S01", "Communication link failure"),
                SqlErrorCode.CONNECTION_FAILED,
            ),
            (
                "command timeout",
                sql_server_error("HYT00", "Query timeout expired"),
                SqlErrorCode.TIMEOUT,
            ),
        ):
            with self.subTest(label=label):
                writer, descriptor, server = _strict_writer()

                def boom(_call, error=error):
                    raise error

                server.on("INSERT INTO [dbo].[BidProjects]", boom)

                def mutate(recorder, writer=writer, descriptor=descriptor):
                    writer.create_project(descriptor.database_id, "Project")
                    recorder.record(ResourceRef("project", "1"), ChangeOperation.CREATE)
                    return True

                with server.patched():
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        writer.execute(self._request(descriptor), mutate)
                self.assertEqual(raised.exception.details.code, code)
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
                self.assertEqual(
                    sum(
                        "INSERT INTO [dbo].[BidProjects]" in s
                        for s in server.statements(1)
                    ),
                    1,
                    "a failed statement is never replayed",
                )
                self.assertNotIn(
                    "DECLARE @Changes TABLE", " ".join(server.statements(1))
                )
                server.assert_everything_closed()

    def test_recovered_marker_returns_the_committed_result_without_running_the_operation(
        self,
    ):
        server = _StrictMutationServer()
        writer, descriptor, server = _strict_writer(server)
        request = self._request(descriptor)
        server.marker = (
            request.mutation_type,
            request.request_hash,
            1,
            '{"value":["100"],"value_available":true}',
        )
        executed = []
        with server.patched():
            result = writer.execute(request, lambda _recorder: executed.append(1))
        self.assertEqual(executed, [])
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["100"])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertNotIn("DECLARE @Changes TABLE", " ".join(server.statements(1)))
        server.assert_everything_closed()

    def test_inherited_rowcount_checks_are_not_fooled_by_session_nocount(self):
        # The lock batches run SET NOCOUNT ON for the whole connection, so every
        # later DML in the same mutation reports rowcount -1. Shared (Access
        # oriented) writer code must not read -1 as "one row matched".
        calls = (
            (
                "show",
                lambda writer, db: writer.update_default_layer_show(db, "7", True),
            ),
            (
                "name",
                lambda writer, db: writer.update_default_layer_name(db, "7", "New"),
            ),
        )
        for label, call in calls:
            for template_row_exists in (False, True):
                with self.subTest(
                    update=label, template_row_exists=template_row_exists
                ):
                    writer, descriptor, server = _strict_writer()
                    server.on(
                        "AND [IsTemplate] <> 0 AND",
                        lambda _call: Reply.rows(
                            *(((7,),) if template_row_exists else ())
                        ),
                    )
                    server.on(
                        "UPDATE [BidLayers] SET",
                        Reply.dml(1 if template_row_exists else 0),
                    )
                    server.on("SELECT [UID] FROM [BidLayers]", Reply.rows((7,)))

                    def mutate(
                        recorder, writer=writer, descriptor=descriptor, call=call
                    ):
                        changed = call(writer, descriptor.database_id)
                        recorder.record(
                            ResourceRef("default_layers_collection", "database"),
                            ChangeOperation.UPDATE,
                        )
                        return changed

                    with server.patched():
                        result = writer.execute(self._request(descriptor), mutate)
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    # only a template row can be updated: no match, no change
                    self.assertIs(result.value, template_row_exists)
                    server.assert_everything_closed()


class WriterStrictStatementContractTests(unittest.TestCase):
    def test_marker_and_feed_rows_take_the_database_guid_from_the_single_row_identity(
        self,
    ):
        from tests.helpers.sql.strict_sql_fakes import (
            EXPECTED_DATABASE_METADATA_PREDICATE,
        )

        writer, descriptor, server = _strict_writer()
        resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            writer.execute(request, mutate)
        finish = next(s for s in server.statements(1) if "DECLARE @Changes TABLE" in s)
        self.assertIn(
            "DECLARE @DatabaseGuid uniqueidentifier=(SELECT m.[DatabaseGuid] FROM "
            "[ostv].[DatabaseMetadata] m WHERE "
            + EXPECTED_DATABASE_METADATA_PREDICATE
            + "); ",
            finish,
        )


class WriterStrictImportTests(unittest.TestCase):
    """Typed identity-graph import through the strict driver model."""

    def _server(self):
        server = _StrictMutationServer()
        identity = iter(range(100, 1000))
        server.on(
            "SELECT [NextBidNo] FROM [dbo].[Settings] WITH (UPDLOCK, HOLDLOCK)",
            Reply.rows((31,)),
        )
        server.on("UPDATE [dbo].[Settings] SET [NextBidNo] = ?", Reply.dml(1))
        server.on(
            "OUTPUT INSERTED.[UID] VALUES",
            lambda _call: Reply.rows((next(identity),)),
        )
        return server

    def _import(self, raw_data, server=None):
        server = server or self._server()
        writer, descriptor, server = _strict_writer(server)
        results = {}

        def mutate(recorder):
            results["import"] = writer.import_ost_data(
                descriptor.database_id, raw_data, lambda data, *_maps: data
            )
            recorder.record(ResourceRef("bid", "1", 1), ChangeOperation.CREATE)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_IMPORT.value,
            request_hash="a" * 64,
        )
        with server.patched():
            outcome = writer.execute(request, mutate)
        return outcome, results.get("import"), server

    def test_import_inserts_each_row_with_bound_typed_values_in_one_transaction(self):
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Imported", "BidNo": "0"},
            bid_tables={
                "BidLayers": [
                    {
                        "UID": "5",
                        "BidUID": "stale",
                        "Name": "Default",
                        "Show": "-1",
                        "IsLocked": "False",
                        "Sequence": "3",
                    }
                ]
            },
        )
        outcome, imported, server = self._import(raw_data)
        self.assertEqual(outcome.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(imported["table_uid_maps"]["Bids"], {"1": "100"})
        self.assertEqual(imported["table_uid_maps"]["BidLayers"], {"5": "101"})
        inserts = [
            (sql, params)
            for cursor in server.connections[0].cursors
            for sql, params in cursor.executed
            if sql.startswith("INSERT INTO [dbo].")
        ]
        self.assertEqual(
            [sql.split("]")[1] for sql, _ in inserts], [".[Bids", ".[BidLayers"]
        )
        layer_sql, layer_params = inserts[1]
        values = dict(
            zip(
                [
                    name.strip("[] ")
                    for name in layer_sql.split("(")[1].split(")")[0].split(",")
                ],
                layer_params,
            )
        )
        # bound as Python values, rebound to the INSERTED bid identity
        self.assertEqual(values["BidUID"], 100)
        self.assertEqual(values["Name"], "Default")
        self.assertIs(values["Show"], True)
        self.assertIs(values["IsLocked"], False)
        self.assertEqual(values["Sequence"], 3)
        self.assertEqual(
            sum(sql.startswith("INSERT INTO [dbo].[Bids]") for sql, _ in inserts), 1
        )
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        # the next bid number is allocated under the settings lock and advanced once
        self.assertEqual(
            [
                p
                for c in raw.cursors
                for s, p in c.executed
                if s.startswith("UPDATE [dbo].[Settings]")
            ],
            [(32,)],
        )
        server.assert_everything_closed()

    def test_import_failing_on_a_foreign_key_rolls_everything_back_exactly_once(self):
        server = self._server()
        rows = iter((1, 2))

        def reject_second_insert(call):
            index = next(rows)
            if index == 2:
                raise sql_server_error(
                    "23000", "The INSERT statement conflicted with the FOREIGN KEY", 547
                )
            return Reply.rows((100,))

        server.rules.insert(
            0, (lambda sql: "OUTPUT INSERTED.[UID] VALUES" in sql, reject_second_insert)
        )
        raw_data = RawBidData(
            bid_row={"UID": "1", "JobName": "Imported"},
            bid_tables={"BidLayers": [{"UID": "5", "BidUID": "1", "Name": "L"}]},
        )
        writer, descriptor, server = _strict_writer(server)

        def mutate(recorder):
            writer.import_ost_data(descriptor.database_id, raw_data, lambda d, *_m: d)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_IMPORT.value,
            request_hash="a" * 64,
        )
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                writer.execute(request, mutate)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONSTRAINT_FAILED)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertEqual(sum("INSERT INTO [dbo]" in s for s in server.statements(1)), 2)
        server.assert_everything_closed()


class WriterDefaultLayerMatchProbeTests(unittest.TestCase):
    def test_reported_row_counts_are_trusted_and_only_negative_counts_read_back(self):
        from ost_visualizer.infrastructure.mdb.components.layer_operations import (
            _default_layer_update_matched,
        )

        class _Cursor:
            def __init__(self, rowcount, stored):
                self.rowcount = rowcount
                self.stored = stored
                self.executed = []

            def execute(self, sql, *params):
                self.executed.append((sql, params))

            def fetchone(self):
                return (7,) if self.stored else None

        for rowcount, stored, expected, reads in (
            (1, False, True, 0),  # a reported match is final: no extra read
            (3, False, True, 0),
            (0, True, False, 0),  # a reported zero is final too
            (-1, True, True, 1),  # NOCOUNT: read the stored row back
            (-1, False, False, 1),
        ):
            with self.subTest(rowcount=rowcount, stored=stored):
                cursor = _Cursor(rowcount, stored)
                self.assertIs(
                    _default_layer_update_matched(cursor, "[Show] = ?", -1, 7), expected
                )
                self.assertEqual(len(cursor.executed), reads)
                if reads:
                    sql, params = cursor.executed[0]
                    self.assertIn("[IsTemplate] <> 0", sql)
                    self.assertIn("[Show] = ?", sql)
                    self.assertEqual(params, (7, -1))


from tests.helpers.sql.strict_sql_fakes import (
    _matcher as _conflict_pin__matcher,
)  # noqa: E402


class WriterTransactionConflictPinTests(unittest.TestCase):
    """Decision D12 (pin): the SQL writer never commits twice and never replays DML
    after a deadlock victim (1205), lock timeout (1222) or snapshot update conflict
    (3960). Raised before the commit the transaction is rolled back once and the
    classified error propagates; raised BY the commit the outcome is
    COMMIT_STATUS_UNKNOWN after exactly one commit attempt. Re-checking the
    operation marker is the coordinator's job (see
    SqlCollaborationCoordinatorTransactionConflictPinTests).
    Model limits: the strict fake only injects the pyodbc exception at the chosen
    statement/commit; it does not implement server deadlock detection, lock
    timeouts or row-version conflicts, so it proves the writer's reaction, not
    when SQL Server raises these errors.
    """

    ERRORS = (
        (
            "deadlock victim 1205",
            lambda: sql_server_error(
                "40001",
                "Transaction (Process ID 55) was deadlocked on lock resources with "
                "another process and has been chosen as the deadlock victim. Rerun "
                "the transaction.",
                1205,
            ),
        ),
        (
            "lock timeout 1222",
            lambda: sql_server_error(
                "42000", "Lock request time out period exceeded.", 1222
            ),
        ),
        (
            "snapshot update conflict 3960",
            lambda: sql_server_error(
                "42000",
                "Snapshot isolation transaction aborted due to update conflict. You "
                "cannot use snapshot isolation to access table 'dbo.BidProjects' "
                "directly or indirectly in database 'OSTV_TEST' to update, delete, "
                "or insert the row that has been modified or deleted by another "
                "transaction. Retry the transaction or change the isolation level "
                "for the update/delete statement.",
                3960,
            ),
        ),
    )
    DML = "INSERT INTO [dbo].[BidProjects]"
    PREPARE = "DECLARE @LockResult int"
    FINISH = "DECLARE @Changes TABLE"

    def _request(self, descriptor):
        return _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
        )

    def _count(self, server, text):
        return sum(text in statement for statement in server.statements(1))

    def _project_mutation(self, writer, descriptor):
        def mutate(recorder):
            writer.create_project(descriptor.database_id, "Project")
            recorder.record(ResourceRef("project", "1"), ChangeOperation.CREATE)
            return True

        return mutate

    def _raise_at(self, server, stage, error):
        def boom(_call):
            raise error

        # the mutation protocol rules are registered first and answer first: put
        # the failing rule in front of them
        pattern = {"prepare": self.PREPARE, "dml": self.DML, "finish": self.FINISH}[
            stage
        ]
        server.rules.insert(0, (_conflict_pin__matcher(pattern), boom))

    def _writer(self):
        writer, descriptor, server = _strict_writer()
        server.on(self.DML, Reply.rows((1,)))
        return writer, descriptor, server

    def test_error_raised_by_a_statement_rolls_back_once_and_is_never_replayed(self):
        for label, make_error in self.ERRORS:
            for stage in ("prepare", "dml", "finish"):
                with self.subTest(error=label, stage=stage):
                    writer, descriptor, server = self._writer()
                    self._raise_at(server, stage, make_error())
                    with server.patched():
                        with self.assertRaises(SqlInfrastructureError) as raised:
                            writer.execute(
                                self._request(descriptor),
                                self._project_mutation(writer, descriptor),
                            )
                    error = raised.exception
                    self.assertEqual(error.details.code, SqlErrorCode.UNKNOWN)
                    self.assertIsNone(error.details.native_code)
                    self.assertTrue(error.retryable)
                    # one connection, one transaction, one rollback, no commit
                    self.assertEqual(len(server.connect_calls), 1)
                    raw = server.connections[0]
                    self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
                    kinds = server.event_kinds(1)
                    self.assertEqual(kinds.count("commit"), 0)
                    self.assertEqual(kinds.count("rollback"), 1)
                    # no statement is run twice: the failing batch exactly once, and
                    # the DML only if the failure came after it
                    self.assertEqual(self._count(server, self.PREPARE), 1)
                    self.assertEqual(
                        self._count(server, self.DML), 0 if stage == "prepare" else 1
                    )
                    self.assertEqual(
                        self._count(server, self.FINISH), 1 if stage == "finish" else 0
                    )
                    server.assert_everything_closed()

    def test_error_raised_by_the_commit_is_unknown_after_exactly_one_commit_attempt(
        self,
    ):
        for label, make_error in self.ERRORS:
            for committed in (False, True):
                with self.subTest(error=label, server_applied_commit=committed):
                    writer, descriptor, server = self._writer()
                    server.fail("commit", make_error(), committed=committed)
                    with server.patched():
                        result = writer.execute(
                            self._request(descriptor),
                            self._project_mutation(writer, descriptor),
                        )
                    self.assertEqual(
                        result.outcome_status,
                        MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                    )
                    self.assertTrue(result.commit_attempted)
                    self.assertEqual(result.resulting_versions, {})
                    self.assertIsNone(result.conflict)
                    self.assertIsNone(result.value)
                    self.assertEqual(len(server.connect_calls), 1)
                    raw = server.connections[0]
                    self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                    kinds = server.event_kinds(1)
                    commit_index = kinds.index("commit")
                    # after the commit attempt only the session-context clear runs:
                    # no second commit, no rollback, no DML, no marker query
                    self.assertEqual(
                        kinds[commit_index:],
                        ["commit", "cursor_open", "execute", "cursor_close", "close"],
                    )
                    self.assertIn(
                        "@key=N'ostv_session_id', @value=NULL",
                        server.statements(1)[-1],
                    )
                    self.assertEqual(self._count(server, self.DML), 1)
                    self.assertEqual(self._count(server, self.FINISH), 1)
                    # the single marker lookup of the writer is the pre-operation
                    # idempotency check inside the prepare batch
                    self.assertEqual(self._count(server, self.PREPARE), 1)
                    server.assert_everything_closed()


from tests.helpers.sql.strict_sql_fakes import BidLockState  # noqa: E402
from ost_visualizer.application.dtos.collaboration_dtos import (  # noqa: E402
    BID_LOCKED_MESSAGE,
    MutationRejectionReason,
)


class WriterBidLockRuleTests(unittest.TestCase):
    """Decision B1/B2: the SQL writer transaction refuses a write that touches a
    non-'bid' resource carrying the UID of a LOCKED Bid (REJECTED, reason
    bid_locked) after the operation-marker check and the sorted application locks
    and before the operation, the ChangeLog/EntityVersions batch and the marker.
    Resource shape decides the exemptions: 'bid', project_bids, projects_collection,
    master data (no bid_uid) and import resources are allowed on a locked Bid.
    Locked state: Bids.JobStatusUID -> JobStatuses.Locked (bit, nullable): NULL
    Locked is LOCKED (the client parses the serialized NULL as locked), a dangling
    or NULL JobStatusUID is UNLOCKED.
    Race reasoning (not testable here): the check reads Bids/JobStatuses with plain
    READ COMMITTED reads and no UPDLOCK/HOLDLOCK. The child write holds the SHARED
    OSTV:bid:<uid> applock and the status writer needs the EXCLUSIVE one, so a
    status flip and a child write on the same Bid are serialised by the applock.
    Model limits: the bid_locked branch text the writer sent is executed on sqlite
    (see BidLockState); every other Violations branch is scripted. T-SQL is NOT
    verified against a live SQL Server (see the live-gated two-client acceptance
    test)."""

    TAKEOFF = ResourceRef("takeoff", "10", 8)
    # status UID -> Locked bit
    STATUSES = {1: 1, 2: 0, 3: None}

    def _locks(self, **bids):
        """Bid 8 locked (status 1), 9 unlocked (status 2), 10 NULL Locked (3)."""
        state = BidLockState()
        for uid, locked in self.STATUSES.items():
            state.set_status(uid, locked)
        state.set_bid(8, 1).set_bid(9, 2).set_bid(10, 3)
        for uid, status in bids.items():
            state.set_bid(int(uid.lstrip("b")), status)
        return state

    def _request(self, descriptor, resources, **kwargs):
        return _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources),
            **kwargs,
        )

    def _run(
        self,
        resources,
        *,
        state=None,
        exempt=False,
        marker=None,
        mutate=None,
        commit_error=None,
        violation=None,
    ):
        server = _StrictMutationServer(
            bid_locks=state if state is not None else self._locks(),
            marker=marker,
            violation=violation,
        )
        writer, descriptor, server = _strict_writer(server)
        if commit_error is not None:
            server.fail("commit", commit_error)
        executed = []
        _record, record_mutate = _record_database_update(descriptor)

        def operation(recorder):
            executed.append(1)
            if mutate is not None:
                mutate()
            return record_mutate(recorder)

        request = self._request(descriptor, resources, bid_lock_exempt=exempt)
        with server.patched():
            result = writer.execute(request, operation)
        return result, request, server, executed

    def assert_refused(self, result, server, executed, request):
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(result.rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertEqual(result.rejection_reason, "bid_locked")
        self.assertEqual(executed, [])
        self.assertIsNone(result.conflict)
        self.assertIsNone(result.value)
        self.assertIsNone(result.failure_reason)
        self.assertFalse(result.commit_attempted)
        self.assertEqual(result.resulting_versions, {})
        self.assertEqual(result.consumed_lock_tokens, ())
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        # nothing was written: the ChangeLog/EntityVersions/marker/lease batch is
        # ONE statement and it never ran
        self.assertNotIn("DECLARE @Changes TABLE", " ".join(server.statements(1)))
        # the transaction-owned applocks went with the rollback
        self.assertEqual(
            server.applocks.holders(f"OSTV:operation:{request.operation_id}"), []
        )
        for resource in request.resources:
            self.assertEqual(
                server.applocks.holders(
                    f"OSTV:{resource.resource_type}:{resource.resource_id}"
                ),
                [],
            )
        for bid_uid in {r.bid_uid for r in request.resources if r.bid_uid}:
            self.assertEqual(server.applocks.holders(f"OSTV:bid:{bid_uid}"), [])
        server.assert_everything_closed()

    def test_child_resource_of_a_locked_bid_is_rejected_bid_locked_and_rolled_back(
        self,
    ):
        result, request, server, executed = self._run([self.TAKEOFF])
        self.assert_refused(result, server, executed, request)
        # the refusal comes after the permission snapshot, the operation applock
        # + marker batch, the applock batch and the validation batch, in that order
        statements = server.statements(1)
        self.assertIn("ostv_permission_snapshot", statements[0])
        self.assertIn("DECLARE @LockResult int", statements[1])
        self.assertIn("DECLARE @RequestedLocks TABLE", statements[2])
        self.assertIn("DECLARE @MutationResources TABLE", statements[3])
        self.assertEqual(len(statements), 5)
        self.assertIn("@value=NULL", statements[4])
        self.assertEqual(
            [("OSTV:bid:8", "Shared"), ("OSTV:takeoff:10", "Exclusive")],
            [
                (resource, mode)
                for _n, resource, mode, _c in server.applocks.log
                if resource in {"OSTV:bid:8", "OSTV:takeoff:10"}
            ],
        )

    def test_refusal_is_a_rejection_never_a_conflict_failure_or_exception(self):
        result, _request, _server, _executed = self._run([self.TAKEOFF])
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertNotIn(
            result.outcome_status,
            {
                MutationOutcomeStatus.CONFLICT,
                MutationOutcomeStatus.FAILED_BEFORE_COMMIT,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            },
        )
        self.assertEqual(MutationRejectionReason.BID_LOCKED.value, "bid_locked")
        self.assertEqual(BID_LOCKED_MESSAGE, "The active bid is locked")

    def test_the_refusal_logs_one_warning_with_the_queue_time_message(self):
        with self.assertLogs(
            "ost_visualizer.infrastructure.sql.writer", level="WARNING"
        ) as logged:
            self._run([self.TAKEOFF])
        self.assertEqual(
            [record.getMessage() for record in logged.records],
            ["SQL write refused: The active bid is locked"],
        )

    def test_every_child_resource_type_of_a_locked_bid_is_refused(self):
        for resource_type in (
            "takeoff",
            "annotation",
            "page",
            "condition",
            "area",
            "layer",
            "cover_sheet",
            "takeoffs_collection",
            "annotations_collection",
            "pages_collection",
            "conditions_collection",
            "areas_collection",
            "condition_folder",
        ):
            with self.subTest(resource_type=resource_type):
                result, request, server, executed = self._run(
                    [ResourceRef(resource_type, "5", 8)]
                )
                self.assert_refused(result, server, executed, request)

    def test_project_level_master_data_and_import_shapes_are_allowed_on_a_locked_bid(
        self,
    ):
        locked_bid = ResourceRef("bid", "8", 8)
        shapes = {
            "status change (bid only)": [locked_bid],
            "bid delete": [locked_bid, ResourceRef("projects_collection", "database")],
            "bid duplicate (source bid)": [locked_bid],
            "bid move": [
                locked_bid,
                ResourceRef("project_bids", "3"),
                ResourceRef("project_bids", "4"),
            ],
            "project delete moving the bid": [
                ResourceRef("project", "3"),
                locked_bid,
                ResourceRef("projects_collection", "database"),
            ],
            "project rename": [ResourceRef("project", "3")],
            "project_bids only": [ResourceRef("project_bids", "3")],
            "projects_collection only": [
                ResourceRef("projects_collection", "database")
            ],
            "master data job status": [
                ResourceRef("job_status", "1"),
                ResourceRef("job_statuses_collection", "database"),
            ],
            "master data employee": [ResourceRef("employee", "2")],
            "master data default layers": [
                ResourceRef("default_layers_collection", "database")
            ],
            "import (new bids, no bid_uid)": [
                ResourceRef("project_bids", "orphan"),
                ResourceRef("condition_types_collection", "database"),
                ResourceRef("job_statuses_collection", "database"),
                ResourceRef("employees_collection", "database"),
                ResourceRef("pay_classes_collection", "database"),
            ],
        }
        for label, resources in shapes.items():
            with self.subTest(shape=label):
                result, _request, server, executed = self._run(resources)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertIsNone(result.rejection_reason)
                self.assertEqual(executed, [1])
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                server.assert_everything_closed()

    def test_lock_state_decides_per_bid_exactly_as_the_client_reads_it(self):
        # (Bids.JobStatusUID, {status uid: Locked bit}), expected refusal
        cases = (
            ("Locked bit 1", 1, {1: 1}, True),
            ("Locked bit 0", 1, {1: 0}, False),
            ("Locked NULL means locked", 1, {1: None}, True),
            ("dangling JobStatusUID means unlocked", 99, {1: 1}, False),
            ("NULL JobStatusUID means unlocked", None, {1: 1}, False),
            ("no job statuses at all", 1, {}, False),
        )
        for label, bid_status, statuses, refused in cases:
            with self.subTest(case=label):
                state = BidLockState()
                for uid, locked in statuses.items():
                    state.set_status(uid, locked)
                state.set_bid(8, bid_status)
                result, request, server, executed = self._run(
                    [self.TAKEOFF], state=state
                )
                if refused:
                    self.assert_refused(result, server, executed, request)
                else:
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    self.assertEqual(executed, [1])

    def test_a_bid_with_no_row_is_not_refused(self):
        result, _request, _server, executed = self._run(
            [ResourceRef("takeoff", "10", 77)]
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])

    def test_unlocked_and_null_locked_bids_are_told_apart_in_one_state(self):
        for bid_uid, refused in ((9, False), (10, True), (8, True)):
            with self.subTest(bid_uid=bid_uid):
                result, request, server, executed = self._run(
                    [ResourceRef("takeoff", "10", bid_uid)]
                )
                if refused:
                    self.assert_refused(result, server, executed, request)
                else:
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )

    def test_mixed_request_with_one_locked_and_one_unlocked_bid_is_refused_whole(self):
        for order in ((8, 9), (9, 8)):
            with self.subTest(order=order):
                resources = [
                    ResourceRef("takeoff", "10", order[0]),
                    ResourceRef("page", "20", order[1]),
                ]
                result, request, server, executed = self._run(resources)
                self.assert_refused(result, server, executed, request)

    def test_a_locked_bid_of_another_request_does_not_affect_this_write(self):
        result, _request, _server, executed = self._run(
            [ResourceRef("takeoff", "10", 9), ResourceRef("page", "20", 9)]
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])

    def test_a_committed_retry_is_recovered_not_refused_even_if_the_bid_is_locked_now(
        self,
    ):
        marker = (
            CollaborationMutationType.PROJECT_WRITE.value,
            "a" * 64,
            1,
            '{"value":["100"],"value_available":true}',
        )
        result, _request, server, executed = self._run([self.TAKEOFF], marker=marker)
        # the marker check precedes the lock check: the earlier commit stands
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["100"])
        self.assertIsNone(result.rejection_reason)
        self.assertEqual(executed, [])
        self.assertFalse(
            any(
                "DECLARE @MutationResources TABLE" in statement
                for statement in server.statements(1)
            ),
            "the lock validation batch must not run for a recovered operation",
        )
        server.assert_everything_closed()

    def test_the_narrow_exemption_passes_only_the_flagged_request(self):
        refused, request, server, executed = self._run([self.TAKEOFF])
        self.assert_refused(refused, server, executed, request)
        allowed, _request, server, executed = self._run([self.TAKEOFF], exempt=True)
        self.assertEqual(allowed.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])
        # the flag is the branch's own ?=0 parameter: 0 refuses, 1 exempts
        validation = next(
            statement
            for connection in server.connections
            for cursor in connection.cursors
            for statement in cursor.executed
            if "DECLARE @MutationResources TABLE" in statement[0]
        )
        self.assertIs(validation[1][-1], True)

    def test_the_exemption_skips_only_the_bid_lock_check_not_the_other_violations(self):
        result, _request, _server, executed = self._run(
            [self.TAKEOFF], exempt=True, violation=("item_owner", "Pat", None, None)
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertIsNone(result.rejection_reason)
        self.assertEqual(executed, [])

    def test_a_status_flip_in_the_same_transaction_passes_because_the_check_precedes_it(
        self,
    ):
        # Cover Sheet save: resources include 'bid' and cover-sheet children and the
        # save writes Bids.JobStatusUID. The check reads the PRE-transaction state.
        state = self._locks(b8=2)
        cover_sheet = [
            ResourceRef("bid", "8", 8),
            ResourceRef("cover_sheet", "8", 8),
            ResourceRef("pages_collection", "8", 8),
            ResourceRef("job_status", "1"),
        ]
        result, _request, _server, executed = self._run(
            cover_sheet, state=state, mutate=lambda: state.set_bid(8, 1)
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])
        # the Bid is locked now: the very next child write is refused
        second, request, server, executed = self._run(cover_sheet, state=state)
        self.assert_refused(second, server, executed, request)

    def test_a_cover_sheet_save_on_an_already_locked_bid_is_refused_status_change_is_not(
        self,
    ):
        # The same shape on a Bid that is ALREADY locked: the save's cover-sheet
        # children are refused; the status change (a 'bid'-only write) stays allowed.
        cover_sheet = [ResourceRef("bid", "8", 8), ResourceRef("cover_sheet", "8", 8)]
        result, request, server, executed = self._run(cover_sheet)
        self.assert_refused(result, server, executed, request)
        status_change, _r, _s, executed = self._run([ResourceRef("bid", "8", 8)])
        self.assertEqual(status_change.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])

    def test_an_uncertain_commit_after_a_passed_check_is_unknown_not_refused(self):
        result, _request, _server, executed = self._run(
            [self.TAKEOFF],
            state=self._locks(b8=2),
            commit_error=sql_server_error("08S01", "Communication link failure"),
        )
        self.assertEqual(
            result.outcome_status, MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
        )
        self.assertIsNone(result.rejection_reason)
        self.assertTrue(result.commit_attempted)
        self.assertEqual(executed, [1])

    def test_the_branch_is_in_the_validation_batch_reads_without_locking_and_wins_ordering(
        self,
    ):
        # Text-level pins of what the sqlite evaluation cannot show. UNVERIFIED on a
        # live SQL Server.
        result, _request, server, _executed = self._run([ResourceRef("bid", "8", 8)])
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        validation = next(
            s for s in server.statements(1) if "DECLARE @MutationResources TABLE" in s
        )
        self.assertIn("UNION ALL SELECT -1, N'bid_locked'", validation)
        branch = validation[validation.index("UNION ALL SELECT -1, N'bid_locked'") :]
        branch = branch[: branch.index(") SELECT TOP (1)")]
        self.assertIn("[dbo].[Bids]", branch)
        self.assertIn("[dbo].[JobStatuses]", branch)
        for hint in ("UPDLOCK", "HOLDLOCK", "TABLOCK", "XLOCK", "NOLOCK"):
            self.assertNotIn(hint, branch)
        # the only locking hints of the whole batch stay on EntityVersions
        self.assertEqual(validation.count("UPDLOCK"), 1)
        self.assertIn(
            "[ostv].[EntityVersions] versions WITH (UPDLOCK, HOLDLOCK)", validation
        )

    def test_without_the_branch_in_the_statement_the_fake_cannot_refuse(self):
        # Positive control for the fake: a batch lacking the bid_locked branch yields
        # no violation, so removing the check from the writer is observable.
        state = self._locks()
        original = state.violation_rows

        def stripped(call):
            call.sql = call.sql.replace("N'bid_locked'", "N'something_else'")
            return original(call)

        state.violation_rows = stripped
        result, _request, _server, executed = self._run([self.TAKEOFF], state=state)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])


from tests.helpers.sql.sqlite_lock_validation import LockDatabase  # noqa: E402


class _EvaluatedMutationServer(_StrictMutationServer):
    """The mutation server whose prepare and lock-validation batches are EVALUATED:
    the SQL the writer sent runs on sqlite over a ``LockDatabase`` instead of
    returning a scripted row (see tests/helpers/sql/sqlite_lock_validation.py)."""

    def __init__(self, database, **kwargs):
        super().__init__(**kwargs)
        self.database = database
        self.prepare_calls = []
        self.validation_calls = []

    def _prepare(self, call):
        mode = re.search(r"@LockMode=N'(\w+)'", call.sql).group(1)
        code = self.applocks.acquire(call.connection, call.params[0], mode)
        if code < 0:
            return Reply.rows((code, None, None, None, None, 1))
        self.prepare_calls.append(call)
        return Reply.rows(self.database.operation_context(call.sql, call.params, code))

    def _validate(self, call):
        self.validation_calls.append(call)
        row = self.database.violation(call.sql, call.params)
        return Reply.rows(row) if row is not None else Reply.rows()


class WriterLockValidationSemanticsTests(unittest.TestCase):
    """The writer's lock-validation SQL EVALUATED, not scripted.
    The older tests answer the validation batch with a scripted row and so prove
    only the Python mapping of that row. Here the statement the writer really sent
    (text and parameter binding order) runs on sqlite over described Locks,
    Sessions, Presence, EntityVersions, Bids and JobStatuses rows, so the
    production predicates, priorities and bound parameters decide the answer.
    Limits (see sqlite_lock_validation): sqlite is not T-SQL, there is no locking or
    rowversion generation, the clock is the injected server instant, and the text
    is UNVERIFIED against a live SQL Server."""

    ME = "session-1"
    TOKEN = "abcdef01-2345-6789-abcd-ef0123456789"
    TAKEOFF = ResourceRef("takeoff", "10", 8)
    BID = ResourceRef("bid", "8", 8)

    def _database(self):
        database = LockDatabase()
        database.add_session(self.ME, "Me")
        database.add_session("ana-session", "Ana")
        database.add_session("bob-session", "Bob")
        database.set_status(2, 0).set_bid(8, 2)
        return database

    def _run(self, database, resources, operation_id=None, **kwargs):
        server = _EvaluatedMutationServer(database)
        writer, descriptor, server = _strict_writer(server)
        executed = []
        _record, record_mutate = _record_database_update(descriptor)

        def operation(recorder):
            executed.append(1)
            return record_mutate(recorder)

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id=self.ME,
            operation_id=operation_id or str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources),
            **kwargs,
        )
        with server.patched():
            result = writer.execute(request, operation)
        return result, request, server, executed

    def _assert_lock_conflict(self, result, request, server, executed, message):
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(result.conflict.reason, message)
        self.assertEqual(result.conflict.resource, request.resources[0])
        self.assertEqual(executed, [])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertNotIn("DECLARE @Changes TABLE", " ".join(server.statements(1)))
        server.assert_everything_closed()

    def _assert_committed(self, result, server, executed):
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(executed, [1])
        self.assertEqual(
            (server.connections[0].commits, server.connections[0].rollbacks), (1, 0)
        )

    def test_a_live_lock_of_another_session_on_a_requested_resource_is_an_item_owner_conflict(
        self,
    ):
        database = self._database().add_lock(
            "takeoff", "10", "ana-session", self.TOKEN, bid_uid=8
        )
        self._assert_lock_conflict(
            *self._run(database, [self.TAKEOFF]),
            "This item is being edited by Ana.",
        )
        for label, resource in (
            ("other id", ResourceRef("takeoff", "11", 8)),
            ("other type", ResourceRef("page", "10", 8)),
        ):
            with self.subTest(control=label):
                result, _request, server, executed = self._run(database, [resource])
                self._assert_committed(result, server, executed)

    def test_a_lock_expires_at_the_server_instant_exactly(self):
        for expires_in, refused in ((1, True), (0, False), (-1, False)):
            with self.subTest(expires_in=expires_in):
                database = self._database().add_lock(
                    "takeoff",
                    "10",
                    "ana-session",
                    self.TOKEN,
                    bid_uid=8,
                    expires_in=expires_in,
                )
                result, request, server, executed = self._run(database, [self.TAKEOFF])
                if refused:
                    self._assert_lock_conflict(
                        result,
                        request,
                        server,
                        executed,
                        "This item is being edited by Ana.",
                    )
                else:
                    self._assert_committed(result, server, executed)

    def test_the_lock_owner_comparison_binds_the_requesting_session(self):
        database = self._database().add_lock(
            "takeoff", "10", self.ME, self.TOKEN, bid_uid=8
        )
        result, request, server, executed = self._run(database, [self.TAKEOFF])
        self._assert_lock_conflict(
            result,
            request,
            server,
            executed,
            "The mutation did not present its owned SQL edit lock.",
        )
        result, _request, server, executed = self._run(
            database, [self.TAKEOFF], required_lock_tokens=(self.TOKEN.upper(),)
        )
        self._assert_committed(result, server, executed)
        self.assertEqual(result.consumed_lock_tokens, (self.TOKEN.upper(),))

    def test_a_required_token_without_a_live_own_lock_is_an_expired_lock(self):
        cases = {
            "no lock at all": lambda db: db,
            "lock of another session": lambda db: db.add_lock(
                "takeoff", "10", "ana-session", self.TOKEN, bid_uid=8
            ),
            "own lock already expired": lambda db: db.add_lock(
                "takeoff", "10", self.ME, self.TOKEN, bid_uid=8, expires_in=0
            ),
        }
        for label, build in cases.items():
            with self.subTest(case=label):
                database = build(self._database())
                resources = [self.TAKEOFF]
                if label == "lock of another session":
                    resources = [ResourceRef("takeoff", "11", 8)]
                result, request, server, executed = self._run(
                    database, resources, required_lock_tokens=(self.TOKEN,)
                )
                self._assert_lock_conflict(
                    result,
                    request,
                    server,
                    executed,
                    "A required SQL edit lock expired before the write.",
                )

    def test_a_required_token_of_a_resource_outside_the_mutation_is_refused(self):
        database = self._database().add_lock(
            "takeoff", "99", self.ME, self.TOKEN, bid_uid=8
        )
        result, request, server, executed = self._run(
            database, [self.TAKEOFF], required_lock_tokens=(self.TOKEN,)
        )
        self._assert_lock_conflict(
            result,
            request,
            server,
            executed,
            "A SQL edit lock does not belong to this mutation.",
        )

    def test_a_live_lock_of_another_session_on_the_parent_bid_is_a_bid_owner_conflict(
        self,
    ):
        database = self._database().add_lock("bid", "8", "ana-session", self.TOKEN)
        self._assert_lock_conflict(
            *self._run(database, [self.TAKEOFF]),
            "This bid is being changed by Ana.",
        )
        # the bid resource itself is the item, not the parent: item_owner wins
        self._assert_lock_conflict(
            *self._run(database, [self.BID]),
            "This item is being edited by Ana.",
        )
        # a child of another bid is not affected
        result, _request, server, executed = self._run(
            database, [ResourceRef("takeoff", "10", 9)]
        )
        self._assert_committed(result, server, executed)

    def test_child_locks_block_a_bid_write_only_when_the_request_asks_for_it(self):
        database = self._database().add_lock(
            "takeoff", "10", "ana-session", self.TOKEN, bid_uid=8
        )
        result, _request, server, executed = self._run(database, [self.BID])
        self._assert_committed(result, server, executed)
        self._assert_lock_conflict(
            *self._run(database, [self.BID], block_bid_child_locks=True),
            "This bid contains an item being edited by Ana.",
        )
        # only a bid resource is blocked by its children; a takeoff of the bid is
        # an item_owner question and Ana's lock is on this very takeoff
        self._assert_lock_conflict(
            *self._run(database, [self.TAKEOFF], block_bid_child_locks=True),
            "This item is being edited by Ana.",
        )
        own = self._database().add_lock("takeoff", "10", self.ME, self.TOKEN, bid_uid=8)
        result, _request, server, executed = self._run(
            own, [self.BID], block_bid_child_locks=True
        )
        self._assert_committed(result, server, executed)

    def test_active_editors_block_a_bid_write_only_while_alive_and_editing(self):
        stale = 45
        cases = (
            ("editing and fresh", dict(), "editing", True),
            (
                "heartbeat exactly at the stale limit",
                dict(heartbeat_age=stale),
                "editing",
                True,
            ),
            (
                "heartbeat one second past the limit",
                dict(heartbeat_age=stale + 1),
                "editing",
                False,
            ),
            ("disconnected", dict(disconnected=True), "editing", False),
            ("viewing only", dict(), "viewing", False),
        )
        for label, session_kwargs, mode, refused in cases:
            with self.subTest(case=label):
                database = LockDatabase()
                database.add_session(self.ME, "Me")
                database.add_session("ana-session", "Ana", **session_kwargs)
                database.add_presence("ana-session", 8, mode)
                result, request, server, executed = self._run(
                    database, [self.BID], block_bid_active_editors=True
                )
                if refused:
                    self._assert_lock_conflict(
                        result,
                        request,
                        server,
                        executed,
                        "This bid is actively being edited by Ana.",
                    )
                else:
                    self._assert_committed(result, server, executed)
        database = LockDatabase().add_session(self.ME, "Me")
        database.add_session("ana-session", "Ana").add_presence(
            "ana-session", 8, "editing"
        )
        result, _request, server, executed = self._run(database, [self.BID])
        self._assert_committed(result, server, executed)
        own = (
            LockDatabase()
            .add_session(self.ME, "Me")
            .add_presence(self.ME, 8, "editing")
        )
        result, _request, server, executed = self._run(
            own, [self.BID], block_bid_active_editors=True
        )
        self._assert_committed(result, server, executed)
        other_bid = LockDatabase().add_session(self.ME, "Me")
        other_bid.add_session("ana-session", "Ana").add_presence(
            "ana-session", 9, "editing"
        )
        result, _request, server, executed = self._run(
            other_bid, [self.BID], block_bid_active_editors=True
        )
        self._assert_committed(result, server, executed)

    def test_expected_versions_decide_between_match_mismatch_and_missing_row(self):
        expected = ConcurrencyToken(b"\x01" * 8)
        for label, stored, matches in (
            ("matching token", b"\x01" * 8, True),
            ("changed token", b"\x02" * 8, False),
            ("row missing", None, False),
        ):
            with self.subTest(case=label):
                database = self._database()
                if stored is not None:
                    database.add_version("takeoff", "10", stored)
                result, request, server, executed = self._run(
                    database,
                    [self.TAKEOFF],
                    expected_versions=(
                        ExpectedResourceVersion(self.TAKEOFF, expected),
                    ),
                )
                if matches:
                    self._assert_committed(result, server, executed)
                    continue
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind,
                    SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY,
                )
                self.assertEqual(result.conflict.resource, self.TAKEOFF)
                self.assertEqual(result.conflict.expected, expected)
                self.assertEqual(
                    result.conflict.actual,
                    None if stored is None else ConcurrencyToken(stored),
                )
                self.assertEqual(executed, [])
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (0, 1))

    def test_the_conflicting_expected_version_is_found_by_its_request_ordinal(self):
        first = ResourceRef("takeoff", "10", 8)
        second = ResourceRef("takeoff", "11", 8)
        database = self._database()
        database.add_version("takeoff", "10", b"\x01" * 8)
        database.add_version("takeoff", "11", b"\x09" * 8)
        for expectations, culprit, actual in (
            ((first, second), second, b"\x09" * 8),
            ((second, first), second, b"\x09" * 8),
        ):
            with self.subTest(order=[r.resource_id for r in expectations]):
                result, _request, _server, _executed = self._run(
                    database,
                    [first, second],
                    expected_versions=tuple(
                        ExpectedResourceVersion(resource, ConcurrencyToken(b"\x01" * 8))
                        for resource in expectations
                    ),
                )
                self.assertEqual(result.conflict.resource, culprit)
                self.assertEqual(result.conflict.actual, ConcurrencyToken(actual))

    def test_violations_are_reported_in_priority_order(self):
        ana, bob = "ana-session", "bob-session"
        takeoff_10 = ResourceRef("takeoff", "10", 8)
        takeoff_11 = ResourceRef("takeoff", "11", 8)
        missing_version = ExpectedResourceVersion(
            takeoff_10, ConcurrencyToken(b"\x07" * 8)
        )
        cases = (
            (
                "lower request ordinal first",
                lambda db: db.add_lock(
                    "takeoff",
                    "11",
                    ana,
                    "11111111-0000-0000-0000-000000000001",
                    bid_uid=8,
                ).add_lock(
                    "takeoff",
                    "10",
                    bob,
                    "11111111-0000-0000-0000-000000000002",
                    bid_uid=8,
                ),
                [takeoff_10, takeoff_11],
                {},
                "This item is being edited by Bob.",
            ),
            (
                "item owner before bid owner of the same resource",
                lambda db: db.add_lock(
                    "takeoff",
                    "10",
                    ana,
                    "11111111-0000-0000-0000-000000000001",
                    bid_uid=8,
                ).add_lock("bid", "8", bob, "11111111-0000-0000-0000-000000000002"),
                [takeoff_10],
                {},
                "This item is being edited by Ana.",
            ),
            (
                "bid owner of an earlier resource before an item owner of a later one",
                lambda db: db.add_lock(
                    "bid", "8", bob, "11111111-0000-0000-0000-000000000002"
                ).add_lock(
                    "takeoff",
                    "11",
                    ana,
                    "11111111-0000-0000-0000-000000000001",
                    bid_uid=8,
                ),
                [takeoff_10, takeoff_11],
                {},
                "This bid is being changed by Bob.",
            ),
            (
                "an owner conflict before a missing token",
                lambda db: db.add_lock(
                    "takeoff",
                    "10",
                    ana,
                    "11111111-0000-0000-0000-000000000001",
                    bid_uid=8,
                ),
                [takeoff_10],
                {"required_lock_tokens": (self.TOKEN,)},
                "This item is being edited by Ana.",
            ),
            (
                "an expired token before a foreign token",
                lambda db: db.add_lock(
                    "takeoff",
                    "99",
                    self.ME,
                    "11111111-0000-0000-0000-000000000003",
                    bid_uid=8,
                ),
                [takeoff_10],
                {
                    "required_lock_tokens": (
                        self.TOKEN,
                        "11111111-0000-0000-0000-000000000003",
                    )
                },
                "A required SQL edit lock expired before the write.",
            ),
            (
                "a foreign token before an omitted own lock",
                lambda db: db.add_lock(
                    "takeoff",
                    "99",
                    self.ME,
                    "11111111-0000-0000-0000-000000000003",
                    bid_uid=8,
                ).add_lock(
                    "takeoff",
                    "10",
                    self.ME,
                    "11111111-0000-0000-0000-000000000004",
                    bid_uid=8,
                ),
                [takeoff_10],
                {"required_lock_tokens": ("11111111-0000-0000-0000-000000000003",)},
                "A SQL edit lock does not belong to this mutation.",
            ),
            (
                "an omitted own lock before a stale version",
                lambda db: db.add_lock(
                    "takeoff",
                    "10",
                    self.ME,
                    "11111111-0000-0000-0000-000000000004",
                    bid_uid=8,
                ),
                [takeoff_10],
                {"expected_versions": (missing_version,)},
                "The mutation did not present its owned SQL edit lock.",
            ),
        )
        for label, build, resources, kwargs, message in cases:
            with self.subTest(case=label):
                database = build(self._database())
                result, request, server, executed = self._run(
                    database, resources, **kwargs
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(result.conflict.reason, message)
                self.assertEqual(executed, [])

    def test_a_locked_bid_outranks_every_other_violation(self):
        database = self._database().set_status(1, 1).set_bid(8, 1)
        database.add_lock("takeoff", "10", "ana-session", self.TOKEN, bid_uid=8)
        result, _request, server, executed = self._run(
            database,
            [self.TAKEOFF],
            required_lock_tokens=("11111111-0000-0000-0000-000000000009",),
            expected_versions=(
                ExpectedResourceVersion(self.TAKEOFF, ConcurrencyToken(b"\x07" * 8)),
            ),
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(result.rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertEqual(executed, [])
        exempt, _request, _server, _executed = self._run(
            database,
            [self.TAKEOFF],
            bid_lock_exempt=True,
        )
        self.assertEqual(exempt.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(exempt.conflict.reason, "This item is being edited by Ana.")

    def test_session_liveness_is_judged_by_the_server_clock_and_the_stale_window(self):
        stale = 45
        for label, session_kwargs, alive in (
            ("fresh", dict(), True),
            ("exactly at the window", dict(heartbeat_age=stale), True),
            ("one second past the window", dict(heartbeat_age=stale + 1), False),
            ("disconnected", dict(disconnected=True), False),
        ):
            with self.subTest(case=label):
                database = LockDatabase().add_session(self.ME, "Me", **session_kwargs)
                result, _request, server, executed = self._run(database, [self.BID])
                if alive:
                    self._assert_committed(result, server, executed)
                    continue
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind, SynchronizationConflictKind.SESSION
                )
                self.assertEqual(
                    result.conflict.reason,
                    "The SQL collaboration session expired before the write.",
                )
                self.assertEqual(executed, [])
        unknown = LockDatabase().add_session("someone-else", "Else")
        result, _request, _server, executed = self._run(unknown, [self.BID])
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.SESSION)
        self.assertEqual(executed, [])

    def test_the_operation_marker_is_looked_up_by_the_operation_id_only(self):
        payload = '{"value":["100"],"value_available":true}'
        write = CollaborationMutationType.PROJECT_WRITE.value
        database = self._database().add_marker(
            str(uuid.uuid4()), write, "a" * 64, 1, payload
        )
        result, _request, server, executed = self._run(database, [self.BID])
        self._assert_committed(result, server, executed)
        operation_id = str(uuid.uuid4())
        database.add_marker(operation_id, write, "a" * 64, 1, payload)
        result, _request, server, executed = self._run(
            database, [self.BID], operation_id=operation_id
        )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(result.value, ["100"])
        self.assertEqual(executed, [])
        self.assertEqual(server.validation_calls, [])

    def test_no_statement_binds_a_client_clock_value(self):
        import datetime

        database = self._database().add_lock(
            "takeoff", "10", self.ME, self.TOKEN, bid_uid=8
        )
        result, _request, server, executed = self._run(
            database, [self.TAKEOFF], required_lock_tokens=(self.TOKEN,)
        )
        self._assert_committed(result, server, executed)
        bound = [
            param
            for connection in server.connections
            for cursor in connection.cursors
            for _sql, params in cursor.executed
            for param in params
        ]
        self.assertTrue(bound)
        self.assertFalse(
            [p for p in bound if isinstance(p, (datetime.date, datetime.time))],
            "lease expiry and session liveness must use SYSUTCDATETIME() on the server",
        )


class _CodedLockServer(_StrictMutationServer):
    """The mutation server with scripted ``sp_getapplock`` return codes: the
    operation lock (prepare batch) answers ``operation_code`` and the resource
    batch answers ``resource_codes[resource name]`` (default 0), stopping at the
    first negative code exactly as the T-SQL ``WHILE`` loop BREAKs."""

    def __init__(self, *, operation_code=0, resource_codes=None, truncate=False):
        super().__init__()
        self.operation_code = operation_code
        self.resource_codes = resource_codes or {}
        self.truncate = truncate
        self.attempted = []
        self.rules.insert(
            0, (lambda sql: "DECLARE @RequestedLocks TABLE" in sql, self._batch)
        )

    def _prepare(self, call):
        self.applocks.acquire(call.connection, call.params[0], "Exclusive")
        return Reply.rows((self.operation_code, None, None, None, None, 1))

    def _batch(self, call):
        results = []
        for item in call.json(0):
            self.attempted.append(item["resource"])
            code = self.resource_codes.get(item["resource"], 0)
            if code >= 0:
                self.applocks.acquire(call.connection, item["resource"], item["mode"])
            results.append((item["ordinal"], code))
            if code < 0:
                break
        if self.truncate:
            results = results[:-1]
        return Reply.rows(*results)


class WriterApplockResultCodeTests(unittest.TestCase):
    """sp_getapplock returns 0 (granted) and 1 (granted after waiting) as success
    and -1 (timeout), -2 (cancelled), -3 (deadlock victim), -999 (call error) as
    failures. The strict applock table only ever answers 0 or -1, so these codes
    are scripted here. Scripted by the test: the codes are modelled from the
    documented return values, not produced by a live server."""

    OPERATION_LOCKED = "Another session is resolving the same SQL operation."
    RESOURCE_LOCKED = "Another session is changing the same SQL resource."

    def _run(self, server):
        writer, descriptor, server = _strict_writer(server)
        resource = ResourceRef("takeoff", "10", 8)
        executed = []

        def operation(recorder):
            executed.append(1)
            recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            result = writer.execute(request, operation)
        return result, request, server, executed

    def _assert_refused(self, result, request, server, executed, message, *, later):
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(result.conflict.reason, message)
        self.assertEqual(result.conflict.resource, request.resources[0])
        self.assertEqual(executed, [])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        statements = " ".join(server.statements(1))
        for marker in later:
            self.assertNotIn(marker, statements)
        self.assertEqual(server.applocks.holders("OSTV:takeoff:10"), [])
        server.assert_everything_closed()

    def test_the_operation_lock_accepts_granted_codes_and_refuses_every_failure_code(
        self,
    ):
        for code in (0, 1):
            with self.subTest(granted=code):
                result, _request, server, executed = self._run(
                    _CodedLockServer(operation_code=code)
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(executed, [1])
        for code in (-1, -2, -3, -999):
            with self.subTest(refused=code):
                result, request, server, executed = self._run(
                    _CodedLockServer(operation_code=code)
                )
                self._assert_refused(
                    result,
                    request,
                    server,
                    executed,
                    self.OPERATION_LOCKED,
                    later=(
                        "DECLARE @RequestedLocks TABLE",
                        "DECLARE @MutationResources",
                    ),
                )

    def test_resource_locks_accept_granted_codes_and_refuse_every_failure_code(self):
        for code in (0, 1):
            with self.subTest(granted=code):
                result, _request, _server, executed = self._run(
                    _CodedLockServer(resource_codes={"OSTV:takeoff:10": code})
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
                self.assertEqual(executed, [1])
        for code in (-1, -2, -3, -999):
            with self.subTest(refused=code):
                result, request, server, executed = self._run(
                    _CodedLockServer(resource_codes={"OSTV:takeoff:10": code})
                )
                self._assert_refused(
                    result,
                    request,
                    server,
                    executed,
                    self.RESOURCE_LOCKED,
                    later=("DECLARE @MutationResources",),
                )

    def test_a_failure_on_an_earlier_resource_stops_before_the_later_ones(self):
        server = _CodedLockServer(resource_codes={"OSTV:bid:8": -3})
        result, request, server, executed = self._run(server)
        self._assert_refused(
            result,
            request,
            server,
            executed,
            self.RESOURCE_LOCKED,
            later=("DECLARE @MutationResources",),
        )
        self.assertEqual(server.attempted, ["OSTV:bid:8"])

    def test_a_lock_batch_that_answers_fewer_rows_than_requested_is_refused(self):
        result, request, server, executed = self._run(_CodedLockServer(truncate=True))
        self._assert_refused(
            result,
            request,
            server,
            executed,
            self.RESOURCE_LOCKED,
            later=("DECLARE @MutationResources",),
        )


class WriterFinishResultValidationTests(unittest.TestCase):
    """The version/feed/marker batch answers one (ordinal, token) row per version
    record; the writer refuses an incomplete, out-of-range, duplicated or non-token
    answer BEFORE committing (the strict model scripts these malformed answers; a
    live server cannot be made to produce them)."""

    def _run(self, rows, resources=1):
        server = _StrictMutationServer()
        server.rules.insert(
            0,
            (
                lambda sql: "DECLARE @Changes TABLE" in sql,
                lambda _call: Reply.rows(*rows),
            ),
        )
        writer, descriptor, server = _strict_writer(server)
        refs = [ResourceRef("takeoff", str(10 + n), 8) for n in range(resources)]
        executed = []

        def operation(recorder):
            executed.append(1)
            for ref in refs:
                recorder.record(ref, ChangeOperation.UPDATE)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(refs),
        )
        with server.patched():
            try:
                outcome = writer.execute(request, operation)
                error = None
            except Exception as exc:  # noqa: BLE001 - the class under test is the type
                outcome, error = None, exc
        return outcome, error, server, executed

    def _assert_refused_before_commit(
        self, outcome, error, server, executed, kind, text
    ):
        self.assertIsNone(outcome)
        self.assertIsInstance(error, kind)
        self.assertRegex(str(error), text)
        self.assertEqual(executed, [1])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        server.assert_everything_closed()

    def test_a_well_formed_answer_commits_and_maps_every_ordinal(self):
        rows = [(0, b"\x00" * 7 + b"\x05"), (1, b"\x00" * 7 + b"\x06")]
        outcome, error, server, executed = self._run(rows, resources=2)
        self.assertIsNone(error)
        self.assertEqual(outcome.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(
            outcome.resulting_versions,
            {
                ResourceRef("takeoff", "10", 8): ConcurrencyToken(
                    b"\x00" * 7 + b"\x05"
                ),
                ResourceRef("takeoff", "11", 8): ConcurrencyToken(
                    b"\x00" * 7 + b"\x06"
                ),
            },
        )

    def test_an_incomplete_or_oversized_answer_is_refused_before_commit(self):
        token = b"\x00" * 7 + b"\x01"
        for label, rows in (
            ("no rows", []),
            ("one row for two records", [(0, token)]),
            ("three rows for two records", [(0, token), (1, token), (2, token)]),
        ):
            with self.subTest(case=label):
                self._assert_refused_before_commit(
                    *self._run(rows, resources=2),
                    RuntimeError,
                    "incomplete authoritative result",
                )

    def test_an_ordinal_outside_the_records_is_refused_before_commit(self):
        token = b"\x00" * 7 + b"\x01"
        for ordinal in (-1, 2, 99):
            with self.subTest(ordinal=ordinal):
                self._assert_refused_before_commit(
                    *self._run([(0, token), (ordinal, token)], resources=2),
                    RuntimeError,
                    "invalid resource ordinal",
                )

    def test_the_last_valid_ordinal_is_accepted(self):
        token = b"\x00" * 7 + b"\x01"
        outcome, error, _server, _executed = self._run(
            [(1, token), (0, token)], resources=2
        )
        self.assertIsNone(error)
        self.assertEqual(outcome.outcome_status, MutationOutcomeStatus.COMMITTED)

    def test_a_duplicated_ordinal_is_refused_before_commit(self):
        token = b"\x00" * 7 + b"\x01"
        self._assert_refused_before_commit(
            *self._run([(1, token), (1, token)], resources=2),
            RuntimeError,
            "duplicate resource ordinal",
        )

    def test_an_answer_that_is_not_a_rowversion_is_refused_before_commit(self):
        for label, token in (
            ("text", "0000000000000001"),
            ("none", None),
            ("seven bytes", b"\x00" * 7),
        ):
            with self.subTest(token=label):
                self._assert_refused_before_commit(
                    *self._run([(0, token)]),
                    ValueError,
                    "rowversion",
                )


class WriterOperationResultPayloadTests(unittest.TestCase):
    """The operation result is stored in the marker so a retry can return it: only
    JSON-safe values are accepted, anything else aborts BEFORE the commit."""

    def test_json_safe_values_serialize_canonically(self):
        serialize = SqlProjectWriter._serialize_operation_result
        self.assertEqual(
            serialize({"b": (1, 2.5), "a": [None, True, "x"], 3: {"k": 1}}),
            '{"value":{"3":{"k":1},"a":[null,true,"x"],"b":[1,2.5]},'
            '"value_available":true}',
        )
        self.assertEqual(serialize(None), '{"value":null,"value_available":true}')
        self.assertEqual(serialize(False), '{"value":false,"value_available":true}')

    def test_values_a_retry_could_not_reconstruct_are_refused(self):
        serialize = SqlProjectWriter._serialize_operation_result
        for label, value in (
            ("set", {1}),
            ("bytes", b"x"),
            ("object", object()),
            ("nested object", {"k": [object()]}),
        ):
            with self.subTest(value=label):
                with self.assertRaises(TypeError):
                    serialize(value)

    def test_an_unserializable_result_rolls_back_without_a_marker(self):
        writer, descriptor, server = _strict_writer()
        resource = ResourceRef("database", descriptor.database_id)

        def operation(recorder):
            recorder.record(resource, ChangeOperation.UPDATE)
            return object()

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            with self.assertRaises(TypeError):
                writer.execute(request, operation)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertNotIn("DECLARE @Changes TABLE", " ".join(server.statements(1)))
        server.assert_everything_closed()


class WriterConnectionLeaseRuleTests(unittest.TestCase):
    def test_a_mutation_cannot_switch_databases_inside_its_transaction(self):
        writer, descriptor, server = _strict_writer()
        resource = ResourceRef("database", descriptor.database_id)

        def operation(recorder):
            recorder.record(resource, ChangeOperation.UPDATE)
            with writer._connection("another-database"):
                pass
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            with self.assertRaisesRegex(RuntimeError, "cannot switch databases"):
                writer.execute(request, operation)
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertEqual(len(server.connections), 1)

    def test_a_lock_conflict_without_request_resources_is_reported_on_the_database(
        self,
    ):
        writer = SqlProjectWriter.__new__(SqlProjectWriter)

        def fail(_request, _operation):
            raise SqlInfrastructureError(SqlErrorDetails(SqlErrorCode.LOCKED, "busy"))

        writer._execute_mutation_transaction = fail
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
        )
        result = writer.execute(request, lambda _recorder: True)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(result.conflict.resource, ResourceRef("database", "database"))
        self.assertEqual(result.conflict.reason, "busy")


class WriterBulkCoalescingTierTests(unittest.TestCase):
    """_coalesce_records tiers: exact records up to 450, then one collection per
    (family, bid) up to 450, then one database-wide collection per family."""

    @staticmethod
    def _conditions(bids, per_bid):
        return [
            _RecordedMutation(
                ResourceRef("condition", f"{bid}-{n}", bid), ChangeOperation.UPDATE
            )
            for bid in range(1, bids + 1)
            for n in range(per_bid)
        ]

    def test_exactly_450_bid_collections_are_kept_one_per_bid(self):
        coalesced = SqlProjectWriter._coalesce_records(self._conditions(450, 2))
        self.assertEqual(len(coalesced), 450)
        self.assertEqual(
            {(r.resource.resource_type, r.operation) for r in coalesced},
            {("conditions_collection", ChangeOperation.BULK_REFRESH)},
        )
        self.assertEqual(
            {(r.resource.resource_id, r.resource.bid_uid) for r in coalesced},
            {(str(bid), bid) for bid in range(1, 451)},
        )

    def test_451_bid_collections_collapse_to_one_database_wide_collection(self):
        coalesced = SqlProjectWriter._coalesce_records(self._conditions(451, 2))
        self.assertEqual(
            coalesced,
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_the_database_wide_collapse_keeps_one_collection_per_family(self):
        records = self._conditions(451, 1) + [
            _RecordedMutation(ResourceRef("takeoff", "t1", 1), ChangeOperation.UPDATE)
        ]
        self.assertEqual(
            SqlProjectWriter._coalesce_records(records),
            (
                _RecordedMutation(
                    ResourceRef("conditions_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
                _RecordedMutation(
                    ResourceRef("takeoffs_collection", "database"),
                    ChangeOperation.BULK_REFRESH,
                ),
            ),
        )

    def test_a_feed_of_exactly_450_records_keeps_every_record_as_a_feed_row(self):
        writer, descriptor, server = _strict_writer()
        resources = [ResourceRef("takeoff", str(uid), 8) for uid in range(450)]

        def operation(recorder):
            for resource in resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources),
        )
        with server.patched():
            result = writer.execute(request, operation)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        finish = next(
            call
            for connection in server.connections
            for cursor in connection.cursors
            for sql, call in cursor.executed
            if "DECLARE @Changes TABLE" in sql
        )
        changes = json.loads(finish[0])
        self.assertEqual(len(changes), 450)
        self.assertTrue(all(change["is_feed"] for change in changes))
        self.assertEqual({change["operation"] for change in changes}, {"update"})
        self.assertEqual(len(result.resulting_versions), 450)


from tests.helpers.sql.strict_sql_fakes import flatten_parameters  # noqa: E402


class _ScriptedCursor:
    """Canned pyodbc cursor: ``script(sql, params)`` answers the rows of each
    statement; every statement and every close() is recorded."""

    def __init__(self, script):
        self._script = script
        self._rows = []
        self.executed = []
        self.close_count = 0

    def execute(self, sql, *args):
        params = flatten_parameters(args)
        self.executed.append((sql, params))
        self._rows = list(self._script(sql, params))
        return self

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        self.close_count += 1


class _ScriptedConnection:
    """Hands out protocol-checked (strict_cursor) wrappers of fresh scripted cursors."""

    def __init__(self, script=lambda _sql, _params: ()):
        self._script = script
        self.cursors = []

    def cursor(self):
        inner = _ScriptedCursor(self._script)
        self.cursors.append(inner)
        return strict_cursor(inner)

    @property
    def executed(self):
        return [item for cursor in self.cursors for item in cursor.executed]

    def assert_every_cursor_closed_once(self, test):
        for cursor in self.cursors:
            test.assertEqual(cursor.close_count, 1)


def _plain_writer():
    return SqlProjectWriter(
        DatabaseDescriptorRegistry(),
        _cleanup_support__CredentialStore(),
        DatabaseSessionRegistry(),
    )


class WriterDeferredIdentityTests(unittest.TestCase):
    def test_placeholders_are_distinct_negative_ints_counting_down_from_minus_one(self):
        writer = _plain_writer()
        first = writer._next_uid(None, "BidLayers")
        second = writer._next_uid(None, "BidLayers")
        third = writer._next_uid_preserving_references(None, None, "BidLayers")
        self.assertEqual([int.__int__(x) for x in (first, second, third)], [-1, -2, -3])
        self.assertEqual((first, second, third), (-1, -2, -3))
        for placeholder in (first, second, third):
            self.assertIsInstance(placeholder, int)
        batch = writer._next_uids_preserving_references(None, None, "BidLayers", 3)
        self.assertEqual(batch, (-4, -5, -6))
        self.assertEqual(
            writer._next_uids_preserving_references(None, None, "X", 0), ()
        )

    def test_a_placeholder_has_no_value_until_the_server_identity_is_bound(self):
        writer = _plain_writer()
        placeholder = writer._next_uid(None, "BidLayers")
        with self.assertRaisesRegex(RuntimeError, "has not been generated yet"):
            int(placeholder)
        with self.assertRaisesRegex(RuntimeError, "has not been generated yet"):
            str(placeholder)
        with self.assertRaisesRegex(RuntimeError, "has not been generated yet"):
            SqlProjectWriter._resolve_deferred(placeholder)
        placeholder.bind("205")
        self.assertEqual(int(placeholder), 205)
        self.assertIs(type(placeholder.resolved), int)
        self.assertEqual(str(placeholder), "205")
        self.assertEqual(SqlProjectWriter._resolve_deferred(placeholder), 205)
        self.assertIs(type(SqlProjectWriter._resolve_deferred(placeholder)), int)

    def test_resolve_deferred_passes_everything_else_through_unchanged(self):
        marker = object()
        for value in (7, "7", None, 2.5, marker):
            self.assertIs(SqlProjectWriter._resolve_deferred(value), value)


class _RecordingInspector:
    """A schema inspector whose answers the test controls (IDatabaseSchemaInspector
    permits ``column_exists`` to answer False; CurrentSqlWriteSchema never does)."""

    def __init__(self, columns):
        self._columns = columns
        self.calls = []

    def require_table(self, table):
        self.calls.append(("require_table", table))

    def require_column(self, table, column):
        self.calls.append(("require_column", table, column))
        if column not in self._columns.get(table, ()):
            raise AssertionError(f"unexpected required column {table}.{column}")

    def column_exists(self, table, column):
        self.calls.append(("column_exists", table, column))
        return column in self._columns.get(table, ())


class WriterInsertValuesTests(unittest.TestCase):
    def _schema(self):
        return CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

    def _insert(self, values, required=("UID", "BidUID", "Name"), row=(205,)):
        writer = _plain_writer()
        connection = _ScriptedConnection(lambda _sql, _params: [row] if row else [])
        cursor = connection.cursor()
        generated = writer._execute_insert_values(
            cursor, self._schema(), "BidLayers", values, required, "insert_layer"
        )
        return generated, connection

    def test_the_insert_binds_resolved_values_without_the_uid_and_returns_the_identity(
        self,
    ):
        writer = _plain_writer()
        uid = writer._next_uid(None, "BidLayers")
        bid = writer._next_uid(None, "Bids")
        bid.bind(100)
        generated, connection = self._insert(
            {"UID": uid, "BidUID": bid, "Name": "Layer"}
        )
        self.assertEqual(generated, 205)
        self.assertEqual(
            connection.executed,
            [
                (
                    "INSERT INTO [dbo].[BidLayers] ([BidUID], [Name]) "
                    "OUTPUT INSERTED.[UID] VALUES (?, ?)",
                    (100, "Layer"),
                )
            ],
        )
        self.assertEqual(int(uid), 205)
        self.assertIs(type(connection.executed[0][1][0]), int)

    def test_a_plain_or_missing_identity_is_left_alone(self):
        generated, _connection = self._insert(
            {"UID": 12, "BidUID": 1, "Name": "L"}, row=(206,)
        )
        self.assertEqual(generated, 206)
        writer = _plain_writer()
        deferred = writer._next_uid(None, "BidLayers")
        generated, _connection = self._insert(
            {"UID": deferred, "BidUID": 1, "Name": "L"}, row=None
        )
        self.assertIsNone(generated)
        with self.assertRaises(RuntimeError):
            int(deferred)

    def test_a_missing_required_column_is_a_schema_mismatch_that_names_it(self):
        for values, missing in (
            ({"UID": 1, "BidUID": 1}, "Name"),
            ({"BidUID": 1}, "Name"),
            ({"Name": "x"}, "BidUID"),
        ):
            with self.subTest(values=sorted(values)):
                connection = _ScriptedConnection()
                with self.assertRaises(SqlInfrastructureError) as raised:
                    _plain_writer()._execute_insert_values(
                        connection.cursor(),
                        self._schema(),
                        "BidLayers",
                        values,
                        ("UID", "BidUID", "Name"),
                        "insert_layer",
                    )
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )
                self.assertIn(
                    f"BidLayers.{missing} for insert_layer", str(raised.exception)
                )
                self.assertEqual(connection.executed, [])

    def test_a_required_uid_may_be_absent_from_the_values(self):
        generated, connection = self._insert({"BidUID": 1, "Name": "L"})
        self.assertEqual(generated, 205)
        self.assertEqual(len(connection.executed), 1)

    def test_values_that_are_all_identity_have_no_writable_columns(self):
        connection = _ScriptedConnection()
        with self.assertRaisesRegex(
            SqlInfrastructureError, "no writable columns for insert_layer"
        ):
            _plain_writer()._execute_insert_values(
                connection.cursor(),
                self._schema(),
                "BidLayers",
                {"UID": 5},
                ("UID",),
                "insert_layer",
            )
        self.assertEqual(connection.executed, [])

    def test_a_value_for_an_unknown_column_is_refused_by_the_schema(self):
        connection = _ScriptedConnection()
        with self.assertRaisesRegex(SqlInfrastructureError, "dbo.BidLayers.Nope"):
            _plain_writer()._execute_insert_values(
                connection.cursor(),
                self._schema(),
                "BidLayers",
                {"Name": "L", "Nope": 1},
                ("Name",),
                "insert_layer",
            )
        self.assertEqual(connection.executed, [])

    def test_filtering_checks_the_table_and_required_columns_even_without_values(self):
        writer = _plain_writer()
        schema = self._schema()
        with self.assertRaisesRegex(SqlInfrastructureError, "dbo.NoSuchTable"):
            writer._filter_existing_write_values(schema, "NoSuchTable", {}, (), "op")
        with self.assertRaisesRegex(SqlInfrastructureError, "dbo.BidLayers.Nope"):
            writer._filter_existing_write_values(
                schema, "BidLayers", {}, ("Nope",), "op"
            )

    def test_filtering_returns_a_copy_and_asks_the_inspector_about_every_value(self):
        writer = _plain_writer()
        inspector = _RecordingInspector({"BidLayers": {"UID", "Name", "BidUID"}})
        values = {"Name": "L", "BidUID": 3}
        filtered = writer._filter_existing_write_values(
            inspector, "BidLayers", values, ("Name",), "op"
        )
        self.assertEqual(filtered, values)
        self.assertIsNot(filtered, values)
        self.assertEqual(
            inspector.calls,
            [
                ("require_table", "BidLayers"),
                ("require_column", "BidLayers", "Name"),
                ("column_exists", "BidLayers", "Name"),
                ("column_exists", "BidLayers", "BidUID"),
            ],
        )

    def test_an_inspector_that_reports_a_column_missing_is_a_schema_mismatch(self):
        writer = _plain_writer()
        inspector = _RecordingInspector({"BidLayers": {"Name"}})
        with self.assertRaises(SqlInfrastructureError) as raised:
            writer._filter_existing_write_values(
                inspector, "BidLayers", {"Name": "L", "Nope": 1, "Other": 2}, (), "op"
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(
            str(raised.exception),
            "The current SQL schema is missing BidLayers.Nope, Other.",
        )

    def test_a_page_area_selection_insert_binds_page_area_and_selection(self):
        writer = _plain_writer()
        connection = _ScriptedConnection(lambda _sql, _params: [(88,)])
        writer._insert_page_area_selection(
            connection.cursor(), self._schema(), 7, None, 1
        )
        writer._insert_page_area_selection(connection.cursor(), self._schema(), 8, 3, 0)
        self.assertEqual(
            connection.executed,
            [
                (
                    "INSERT INTO [dbo].[BidPageSettings] ([BidPageUID], "
                    "[BidAreaUID], [BidAreaSelected]) OUTPUT INSERTED.[UID] "
                    "VALUES (?, ?, ?)",
                    (7, None, 1),
                ),
                (
                    "INSERT INTO [dbo].[BidPageSettings] ([BidPageUID], "
                    "[BidAreaUID], [BidAreaSelected]) OUTPUT INSERTED.[UID] "
                    "VALUES (?, ?, ?)",
                    (8, 3, 0),
                ),
            ],
        )


class WriterCaughtMutationErrorTests(unittest.TestCase):
    def test_the_first_swallowed_error_of_the_active_mutation_is_kept(self):
        writer = _plain_writer()
        state = SimpleNamespace(operation_error=None)
        token = writer._active_mutation.set(state)
        try:
            first, second = RuntimeError("first"), RuntimeError("second")
            self.assertIs(writer._record_caught_mutation_error(first), True)
            self.assertIs(state.operation_error, first)
            self.assertIs(writer._record_caught_mutation_error(second), True)
            self.assertIs(state.operation_error, first)
        finally:
            writer._active_mutation.reset(token)

    def test_without_an_active_mutation_the_error_is_only_acknowledged(self):
        writer = _plain_writer()
        self.assertIs(writer._record_caught_mutation_error(RuntimeError("x")), True)
        self.assertIsNone(writer._active_mutation.get())


class WriterConstructionTests(unittest.TestCase):
    def test_defaults_and_injected_collaborators(self):
        import logging
        from ost_visualizer.infrastructure.sql.connection_manager import (
            SqlConnectionManager,
        )

        writer = _plain_writer()
        self.assertIs(
            writer.logger, logging.getLogger("ost_visualizer.infrastructure.sql.writer")
        )
        self.assertIsInstance(writer._sql_connections, SqlConnectionManager)
        logger = logging.getLogger("sp3.injected")
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        writer = SqlProjectWriter(
            DatabaseDescriptorRegistry(),
            _cleanup_support__CredentialStore(),
            DatabaseSessionRegistry(),
            connection_manager=manager,
            logger=logger,
        )
        self.assertIs(writer.logger, logger)
        self.assertIs(writer._sql_connections, manager)

    def test_the_injected_logger_receives_the_bid_lock_refusal(self):
        import logging

        server = _StrictMutationServer(
            bid_locks=BidLockState().set_status(1, 1).set_bid(8, 1)
        )
        writer, descriptor, server = _strict_writer(server)
        writer.logger = logging.getLogger("sp3.refusals")
        resource = ResourceRef("takeoff", "10", 8)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with self.assertLogs("sp3.refusals", level="WARNING") as logged:
            with server.patched():
                result = writer.execute(request, lambda _recorder: True)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(len(logged.records), 1)

    def test_the_write_connection_is_not_read_only_and_not_autocommit(self):
        writer, descriptor, server = _strict_writer()
        _resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(ResourceRef("database", descriptor.database_id),),
        )
        with server.patched():
            writer.execute(request, mutate)
        self.assertEqual(len(server.connect_calls), 1)
        self.assertNotIn(
            "ApplicationIntent=ReadOnly", server.connect_calls[0]["connection_string"]
        )
        self.assertIs(server.connect_calls[0]["autocommit"], False)

    def test_the_mutation_context_ends_with_the_mutation_on_every_path(self):
        for fail in (False, True):
            with self.subTest(operation_fails=fail):
                writer, descriptor, server = _strict_writer()
                resource = ResourceRef("database", descriptor.database_id)

                def operation(recorder):
                    recorder.record(resource, ChangeOperation.UPDATE)
                    if fail:
                        raise RuntimeError("boom")
                    return True

                request = _DatabaseMutationRequest(
                    database_id=descriptor.database_id,
                    session_id="session-1",
                    operation_id=str(uuid.uuid4()),
                    mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                    request_hash="a" * 64,
                    resources=(resource,),
                )
                with server.patched():
                    if fail:
                        with self.assertRaises(RuntimeError):
                            writer.execute(request, operation)
                    else:
                        writer.execute(request, operation)
                self.assertIsNone(writer._active_mutation.get())
                with self.assertRaises(SqlInfrastructureError) as raised:
                    writer.create_project(descriptor.database_id, "after")
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SESSION_EXPIRED
                )


class WriterImportConversionTests(unittest.TestCase):
    def test_values_convert_by_the_target_column_type(self):
        from datetime import datetime
        from ost_visualizer.infrastructure.mdb.components.serialization import (
            encode_annotation_text,
            encode_text_blob,
        )

        writer = _plain_writer()
        convert = writer._convert_sql_import_value
        cases = (
            ("2024 3 5 14 30 9", "datetime2", datetime(2024, 3, 5, 14, 30, 9)),
            ("2024 3 5 14 30 9", "DateTime2", datetime(2024, 3, 5, 14, 30, 9)),
            ("", "datetime2", None),
            ("NULL", "datetime2", None),
            (None, "datetime2", None),
            ("abc", "varbinary", encode_text_blob("abc")),
            ("", "varbinary", None),
            ("NULL", "varbinary", None),
            ("7", "int", 7),
            ("-3", "smallint", -3),
            ("9000000000", "bigint", 9000000000),
            ("", "int", None),
            ("NULL", "int", None),
            (None, "bigint", None),
            ("2.5", "float", 2.5),
            ("1e3", "float", 1000.0),
            ("", "float", None),
            ("NULL", "float", None),
            ("1", "bit", True),
            ("-1", "bit", True),
            ("True", "bit", True),
            ("true", "bit", True),
            ("0", "bit", False),
            ("False", "bit", False),
            ("false", "bit", False),
            ("", "bit", False),
            ("NULL", "bit", None),
            ("text", "nvarchar", "text"),
            ("", "varchar", ""),
            ("x", "CHAR", "x"),
            ("NULL", "nvarchar", None),
            (None, "nvarchar", None),
            (5, "int", 5),
            (5, "datetime2", 5),
            (True, "bit", True),
            (b"raw", "varbinary", b"raw"),
            (2.5, "float", 2.5),
        )
        for value, type_name, expected in cases:
            with self.subTest(value=value, type=type_name):
                converted = convert(value, type_name)
                self.assertEqual(converted, expected)
                self.assertIs(type(converted), type(expected))
        self.assertEqual(
            convert("hello", "varbinary", table="BidTexts", column="Name"),
            encode_annotation_text("hello"),
        )
        self.assertEqual(
            convert("hello", "varbinary", table="BidLayers", column="Name"),
            encode_text_blob("hello"),
        )

    def test_values_that_cannot_convert_are_refused_loudly(self):
        writer = _plain_writer()
        convert = writer._convert_sql_import_value
        for value, type_name, error, text in (
            ("not a date", "datetime2", ValueError, "date value is invalid"),
            ("2024 13 40 1 1 1", "datetime2", ValueError, "date value is invalid"),
            ("abc", "int", ValueError, "invalid literal"),
            ("abc", "float", ValueError, "could not convert"),
            ("maybe", "bit", ValueError, "Boolean value is invalid"),
            ("x", "uniqueidentifier", RuntimeError, "Unsupported SQL import type"),
            ("x", "", RuntimeError, "Unsupported SQL import type"),
        ):
            with self.subTest(value=value, type=type_name):
                with self.assertRaisesRegex(error, text):
                    convert(value, type_name)


class WriterInsertIdentityRawTests(unittest.TestCase):
    def _info(self, table):
        return CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema).table_info(table)

    def test_a_row_is_inserted_with_typed_values_and_returns_the_server_identity(self):
        writer = _plain_writer()
        connection = _ScriptedConnection(lambda _sql, _params: [(41,)])
        uid = writer._insert_identity_raw(
            connection,
            "BidLayers",
            {"UID": "5", "BidUID": 100, "Name": "L", "Show": "1", "Sequence": "3"},
            self._info("BidLayers"),
        )
        self.assertEqual(uid, 41)
        self.assertEqual(
            connection.executed,
            [
                (
                    "INSERT INTO [dbo].[BidLayers] ([BidUID], [Name], [Show], "
                    "[Sequence]) OUTPUT INSERTED.[UID] VALUES (?, ?, ?, ?)",
                    (100, "L", True, 3),
                )
            ],
        )
        connection.assert_every_cursor_closed_once(self)

    def test_a_missing_identity_row_is_an_error_and_the_cursor_is_still_closed(self):
        writer = _plain_writer()
        connection = _ScriptedConnection()
        with self.assertRaisesRegex(
            RuntimeError, "SQL Server did not return an identity for BidLayers"
        ):
            writer._insert_identity_raw(
                connection, "BidLayers", {"Name": "L"}, self._info("BidLayers")
            )
        connection.assert_every_cursor_closed_once(self)

    def test_unsupported_and_identity_only_rows_never_reach_the_server(self):
        writer = _plain_writer()
        connection = _ScriptedConnection()
        with self.assertRaisesRegex(
            RuntimeError,
            r"Imported BidLayers row contains unsupported columns: Alpha, Beta",
        ):
            writer._insert_identity_raw(
                connection,
                "BidLayers",
                {"Name": "L", "Beta": 1, "Alpha": 2},
                self._info("BidLayers"),
            )
        with self.assertRaisesRegex(
            RuntimeError, "No importable columns for BidLayers"
        ):
            writer._insert_identity_raw(
                connection, "BidLayers", {"UID": "5"}, self._info("BidLayers")
            )
        self.assertEqual(connection.executed, [])
        self.assertEqual(connection.cursors, [])


class WriterMasterDataResolutionTests(unittest.TestCase):
    def _writer(self):
        return _plain_writer()

    def _resolve(self, table, column, incoming, existing, inserted=None):
        writer = self._writer()
        sequence = iter(range(101, 200))
        connection = _ScriptedConnection(lambda _sql, _params: list(existing))
        raw = RawBidData(bid_row={"UID": "1"}, global_tables={table: incoming})
        with patch.object(
            writer,
            "_insert_identity_raw",
            side_effect=lambda *_args: next(sequence),
        ) as insert:
            result = writer._resolve_global_by_column(connection, raw, table, column)
        return result, insert, connection

    def test_each_lookup_runs_its_select_once_and_closes_its_cursor(self):
        for table, column in (
            ("JobStatuses", "Name"),
            ("AccessLevels", "Description"),
            ("CdnTypes", "Name"),
            ("PayClasses", "Name"),
        ):
            with self.subTest(table=table):
                result, insert, connection = self._resolve(
                    table, column, [{"UID": "9", column: "Open"}], [(50, "Open")]
                )
                self.assertEqual(result, {"9": "50"})
                insert.assert_not_called()
                self.assertEqual(
                    connection.executed,
                    [(f"SELECT [UID], [{column}] FROM [dbo].[{table}]", ())],
                )
                connection.assert_every_cursor_closed_once(self)

    def test_a_missing_master_row_is_inserted_with_the_real_table_info(self):
        result, insert, _connection = self._resolve(
            "JobStatuses", "Name", [{"UID": "9", "Name": "New"}], []
        )
        self.assertEqual(result, {"9": "101"})
        insert.assert_called_once()
        args = insert.call_args.args
        self.assertEqual(args[1:3], ("JobStatuses", {"UID": "9", "Name": "New"}))
        self.assertEqual(
            args[3],
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema).table_info("JobStatuses"),
        )

    def test_empty_names_of_access_levels_and_pay_classes_are_never_matched(self):
        for table, column in (("AccessLevels", "Description"), ("PayClasses", "Name")):
            with self.subTest(table=table):
                result, insert, _connection = self._resolve(
                    table,
                    column,
                    [{"UID": "1", column: ""}, {"UID": "2", column: ""}],
                    [(7, "")],
                )
                self.assertEqual(result, {"1": "101", "2": "102"})
                self.assertEqual(insert.call_count, 2)

    def test_an_empty_name_of_any_other_master_table_matches_like_a_name(self):
        result, insert, _connection = self._resolve(
            "JobStatuses", "Name", [{"UID": "1", "Name": ""}], [(7, "")]
        )
        self.assertEqual(result, {"1": "7"})
        insert.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "ambiguous.*JobStatuses.Name"):
            self._resolve(
                "JobStatuses",
                "Name",
                [{"UID": "1", "Name": ""}, {"UID": "2", "Name": ""}],
                [],
            )

    def test_a_repeated_identical_incoming_row_is_inserted_once(self):
        # the incoming-identity preflight accepts the SAME UID twice (one candidate),
        # so the second occurrence must resolve to the row the first one inserted
        for table, column in (("JobStatuses", "Name"), ("CdnTypes", "Name")):
            with self.subTest(table=table):
                result, insert, _connection = self._resolve(
                    table,
                    column,
                    [{"UID": "9", column: "New"}, {"UID": "9", column: "New"}],
                    [],
                )
                self.assertEqual(result, {"9": "101"})
                self.assertEqual(insert.call_count, 1)

    def test_employee_lookups_select_the_business_key_columns_and_close_the_cursor(
        self,
    ):
        writer = self._writer()
        connection = _ScriptedConnection(
            lambda _sql, _params: [(60, "E100", "Alice", "One", "")]
        )
        raw = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"Employees": [{"UID": "95", "EmployeeNo": "e100"}]},
        )
        with patch.object(writer, "_insert_identity_raw") as insert:
            result = writer._resolve_sql_employees(connection, raw, {}, {})
        self.assertEqual(result, {"95": "60"})
        insert.assert_not_called()
        self.assertEqual(
            connection.executed,
            [
                (
                    "SELECT [UID], [EmployeeNo], [FirstName], [LastName], [EMail] "
                    "FROM [dbo].[Employees]",
                    (),
                )
            ],
        )
        connection.assert_every_cursor_closed_once(self)

    def test_a_missing_employee_is_inserted_with_the_real_table_info(self):
        writer = self._writer()
        connection = _ScriptedConnection()
        raw = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"Employees": [{"UID": "95", "EmployeeNo": "E9"}]},
        )
        with patch.object(writer, "_insert_identity_raw", return_value=88) as insert:
            result = writer._resolve_sql_employees(connection, raw, {}, {})
        self.assertEqual(result, {"95": "88"})
        self.assertEqual(
            insert.call_args.args[3],
            CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema).table_info("Employees"),
        )

    def test_no_incoming_employees_is_an_empty_mapping_without_a_lookup(self):
        writer = self._writer()
        connection = _ScriptedConnection()
        result = writer._resolve_sql_employees(
            connection, RawBidData(bid_row={"UID": "1"}), {}, {}
        )
        self.assertEqual(result, {})
        self.assertEqual(connection.cursors, [])

    def test_two_incoming_employees_with_one_business_key_are_ambiguous(self):
        writer = self._writer()
        connection = _ScriptedConnection()
        raw = RawBidData(
            bid_row={"UID": "1"},
            global_tables={
                "Employees": [
                    {"UID": "95", "EmployeeNo": "E1"},
                    {"UID": "96", "EmployeeNo": " e1 "},
                ]
            },
        )
        with patch.object(writer, "_insert_identity_raw") as insert:
            with self.assertRaisesRegex(RuntimeError, "ambiguous.*Employees"):
                writer._resolve_sql_employees(connection, raw, {}, {})
        insert.assert_not_called()
        self.assertEqual(connection.cursors, [])

    def test_employees_without_any_business_key_are_each_inserted(self):
        writer = self._writer()
        connection = _ScriptedConnection(lambda _sql, _params: [(60, "", "", "", "")])
        raw = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"Employees": [{"UID": "95"}, {"UID": "96"}]},
        )
        sequence = iter((88, 89))
        with patch.object(
            writer, "_insert_identity_raw", side_effect=lambda *_a: next(sequence)
        ) as insert:
            result = writer._resolve_sql_employees(connection, raw, {}, {})
        self.assertEqual(result, {"95": "88", "96": "89"})
        self.assertEqual(insert.call_count, 2)

    def test_a_repeated_identical_incoming_employee_is_inserted_once(self):
        writer = self._writer()
        connection = _ScriptedConnection()
        row = {"UID": "95", "EmployeeNo": "E9"}
        raw = RawBidData(
            bid_row={"UID": "1"}, global_tables={"Employees": [dict(row), dict(row)]}
        )
        with patch.object(writer, "_insert_identity_raw", return_value=88) as insert:
            result = writer._resolve_sql_employees(connection, raw, {}, {})
        self.assertEqual(result, {"95": "88"})
        insert.assert_called_once()

    def test_an_authoritative_employee_uid_present_twice_stops_the_import(self):
        writer = self._writer()
        connection = _ScriptedConnection(
            lambda _sql, _params: [(60, "E1", "", "", ""), (60, "E2", "", "", "")]
        )
        raw = RawBidData(
            bid_row={"UID": "1"},
            global_tables={"Employees": [{"UID": "95", "EmployeeNo": "E9"}]},
        )
        with patch.object(writer, "_insert_identity_raw") as insert:
            with self.assertRaisesRegex(RuntimeError, "duplicate UID 60"):
                writer._resolve_sql_employees(connection, raw, {}, {})
        insert.assert_not_called()
        connection.assert_every_cursor_closed_once(self)


class WriterImportGraphDetailTests(unittest.TestCase):
    def _run(self, raw_data, table_info):
        writer = _plain_writer()
        connection = _ScriptedConnection()
        inserted = []

        def insert(_connection, table, row, _info):
            inserted.append((table, dict(row)))
            return len(inserted) * 100 + 1

        with (
            patch.object(writer, "_get_table_info", side_effect=table_info),
            patch.object(writer, "_insert_identity_raw", side_effect=insert),
        ):
            maps = writer._write_remapped_identity_graph(connection, raw_data)
        return inserted, maps, connection

    @staticmethod
    def _info(*, bid_owned=True):
        def table_info(_connection, table):
            columns = {"UID", "Name", "Show", "Sequence"}
            if bid_owned and table != "Bids":
                columns.add("BidUID")
            return columns, {}

        return table_info

    def test_the_graph_cursor_is_closed_with_and_without_pending_references(self):
        raw = RawBidData(
            bid_row={"UID": "1", "Name": "B"},
            bid_tables={"BidLayers": [{"UID": "5", "BidUID": "1", "Name": "L"}]},
        )
        _inserted, _maps, connection = self._run(raw, self._info())
        self.assertEqual(len(connection.cursors), 1)
        connection.assert_every_cursor_closed_once(self)

    def test_plain_columns_with_zero_empty_or_null_text_are_not_reference_columns(self):
        raw = RawBidData(
            bid_row={"UID": "1", "Name": "0"},
            bid_tables={
                "BidLayers": [
                    {
                        "UID": "5",
                        "BidUID": "1",
                        "Name": "0",
                        "Show": "",
                        "Sequence": "NULL",
                    }
                ]
            },
        )
        inserted, _maps, _connection = self._run(raw, self._info())
        self.assertEqual(inserted[0], ("Bids", {"UID": "1", "Name": "0"}))
        self.assertEqual(
            inserted[1],
            (
                "BidLayers",
                {
                    "UID": "5",
                    "BidUID": 101,
                    "Name": "0",
                    "Show": "",
                    "Sequence": "NULL",
                },
            ),
        )

    def test_a_table_without_a_bid_column_gets_none_written(self):
        raw = RawBidData(
            bid_row={"UID": "1", "Name": "B"},
            bid_tables={"BidLayers": [{"UID": "5", "Name": "L"}]},
        )
        inserted, _maps, _connection = self._run(raw, self._info(bid_owned=False))
        self.assertEqual(inserted[1], ("BidLayers", {"UID": "5", "Name": "L"}))


class WriterImportOrchestrationTests(unittest.TestCase):
    def test_the_transform_receives_the_resolved_maps_in_the_documented_order(self):
        writer = _plain_writer()
        calls = []
        maps = {
            "CdnTypes": {"c": "1"},
            "JobStatuses": {"s": "2"},
            "AccessLevels": {"a": "3"},
            "PayClasses": {"p": "4"},
        }

        def resolve(_connection, _raw, table, column):
            calls.append((table, column))
            return maps[table]

        employees = {"e": "5"}
        raw = RawBidData(bid_row={"UID": "1"})
        transform_args = []

        def transform(*args):
            transform_args.append(args)
            return raw

        with (
            patch.object(
                writer,
                "_connection",
                return_value=contextlib.nullcontext("connection"),
            ),
            patch.object(writer, "_resolve_global_by_column", side_effect=resolve),
            patch.object(
                writer, "_resolve_sql_employees", return_value=employees
            ) as resolve_employees,
            patch.object(writer, "_assign_next_bid_no") as assign,
            patch.object(writer, "_write_remapped_identity_graph", return_value={}),
        ):
            result = writer.import_ost_data("database", raw, transform)
        self.assertEqual(
            calls,
            [
                ("CdnTypes", "Name"),
                ("JobStatuses", "Name"),
                ("AccessLevels", "Description"),
                ("PayClasses", "Name"),
            ],
        )
        resolve_employees.assert_called_once_with(
            "connection", raw, maps["PayClasses"], maps["AccessLevels"]
        )
        self.assertEqual(
            transform_args,
            [
                (
                    raw,
                    0,
                    maps["CdnTypes"],
                    maps["JobStatuses"],
                    employees,
                    maps["PayClasses"],
                )
            ],
        )
        assign.assert_called_once_with("connection", raw)
        self.assertEqual(
            result["global_uid_maps"],
            {
                "condition_types": maps["CdnTypes"],
                "job_statuses": maps["JobStatuses"],
                "employees": employees,
                "pay_classes": maps["PayClasses"],
            },
        )
        self.assertIsNone(raw.bid_row["BidProjectUID"])


from ost_visualizer.infrastructure.mdb.components.constants import (  # noqa: E402
    TAKEOFF_ANNOTATION_REFERENCE_COLUMNS,
)


class _MissingColumnSchema(CurrentSqlWriteSchema):
    """The real write schema that additionally reports ONE (table, column) as absent
    and records every column the writer required."""

    def __init__(self, missing=None):
        super().__init__(SQL_SCHEMA_V1.core_schema)
        self.missing = missing
        self.required = []

    def require_column(self, table, column):
        self.required.append((table, column))
        if (table, column) == self.missing:
            self._raise_mismatch(f"dbo.{table}.{column}")
        super().require_column(table, column)


class WriterSchemaRequirementTests(unittest.TestCase):
    """Statements that name columns first require them from the schema: a database
    that lacks one fails with SCHEMA_MISMATCH before anything is sent."""

    def _writer(self, schema, cursor):
        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._write_schema = schema

        @contextlib.contextmanager
        def connection(_database_id):
            yield SimpleNamespace(cursor=lambda: strict_cursor(cursor))

        writer._connection = connection
        return writer

    def _plan_pairs(self):
        annotation_type, table = next(iter(ANNOTATION_TABLE_BY_TYPE.items()))
        pairs = [("BidTakeoffs", "UID"), ("BidTakeoffs", "BidUID")]
        pairs += [("BidTakeoffs", column) for column in TAKEOFF_SELF_REFERENCE_COLUMNS]
        pairs += [(table, "UID"), (table, "BidUID")]
        return annotation_type, pairs

    def test_plan_item_verification_requires_every_column_it_queries(self):
        annotation_type, pairs = self._plan_pairs()
        self.assertGreaterEqual(len(pairs), 6)
        schema = _MissingColumnSchema()
        cursor = _ScriptedCursor(lambda _sql, _params: [(0,)])
        self._writer(schema, cursor).verify_plan_items_exist(
            "database", "8", ("101",), (("5", annotation_type),)
        )
        self.assertEqual(sorted(set(schema.required)), sorted(pairs))
        for pair in pairs:
            with self.subTest(missing=pair):
                cursor = _ScriptedCursor(lambda _sql, _params: [(0,)])
                writer = self._writer(_MissingColumnSchema(pair), cursor)
                with self.assertRaises(SqlInfrastructureError) as raised:
                    writer.verify_plan_items_exist(
                        "database", "8", ("101",), (("5", annotation_type),)
                    )
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )
                self.assertIn(f"dbo.{pair[0]}.{pair[1]}", str(raised.exception))
                self.assertEqual(cursor.executed, [])

    def test_takeoff_deletion_requires_every_column_it_touches(self):
        pairs = [
            ("BidTakeoffs", "UID"),
            ("BidTakeoffs", "ParentUID"),
            ("BidPercents", "BidTakeoffUID"),
        ] + [
            (table, column)
            for table in TAKEOFF_REFERENCE_TABLES
            for column in TAKEOFF_ANNOTATION_REFERENCE_COLUMNS
        ]
        self.assertGreater(len(TAKEOFF_REFERENCE_TABLES), 0)
        self.assertGreater(len(TAKEOFF_ANNOTATION_REFERENCE_COLUMNS), 0)
        schema = _MissingColumnSchema()
        cursor = _ScriptedCursor(lambda _sql, _params: [(1,)])
        self._writer(schema, cursor)._run_delete_takeoffs("database", [7], 100)
        self.assertEqual(sorted(set(schema.required)), sorted(set(pairs)))
        for pair in pairs:
            with self.subTest(missing=pair):
                cursor = _ScriptedCursor(lambda _sql, _params: [(1,)])
                writer = self._writer(_MissingColumnSchema(pair), cursor)
                with self.assertRaises(SqlInfrastructureError) as raised:
                    writer._run_delete_takeoffs("database", [7], 100)
                self.assertEqual(
                    raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH
                )
                self.assertIn(f"dbo.{pair[0]}.{pair[1]}", str(raised.exception))
                self.assertEqual(cursor.executed, [])

    def test_a_deletion_result_of_no_row_is_refused(self):
        cursor = _ScriptedCursor(lambda _sql, _params: [])
        writer = self._writer(_MissingColumnSchema(), cursor)
        with self.assertRaisesRegex(
            RuntimeError, "takeoff deletion returned no result"
        ):
            writer._run_delete_takeoffs("database", [7], 100)
        self.assertEqual(cursor.close_count, 1)


class WriterPrepareAndValidationEdgeTests(unittest.TestCase):
    def test_a_prepare_batch_that_answers_nothing_is_a_lock_conflict(self):
        class _SilentPrepare(_StrictMutationServer):
            def _prepare(self, call):
                self.applocks.acquire(call.connection, call.params[0], "Exclusive")
                return Reply.rows()

        writer, descriptor, server = _strict_writer(_SilentPrepare())
        resource, mutate = _record_database_update(descriptor)
        executed = []
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            result = writer.execute(
                request, lambda recorder: executed.append(1) or mutate(recorder)
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(executed, [])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))

    def test_resources_known_only_through_expected_versions_are_locked_and_validated(
        self,
    ):
        writer, descriptor, server = _strict_writer()
        takeoff = ResourceRef("takeoff", "10", 8)
        _resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            expected_versions=(
                ExpectedResourceVersion(takeoff, ConcurrencyToken(b"\x01" * 8)),
            ),
        )
        with server.patched():
            result = writer.execute(request, mutate)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        locked = [
            (resource, mode)
            for number, resource, mode, _code in server.applocks.log
            if resource != f"OSTV:operation:{request.operation_id}"
        ]
        self.assertEqual(
            locked, [("OSTV:bid:8", "Shared"), ("OSTV:takeoff:10", "Exclusive")]
        )
        validation = next(
            call
            for connection in server.connections
            for cursor in connection.cursors
            for sql, call in cursor.executed
            if "DECLARE @MutationResources TABLE" in sql
        )
        self.assertEqual(
            json.loads(validation[0]),
            [
                {
                    "ordinal": 0,
                    "resource_type": "takeoff",
                    "resource_id": "10",
                    "bid_uid": 8,
                }
            ],
        )

    def test_a_rowversion_ordinal_outside_the_expectations_is_refused(self):
        resource = ResourceRef("takeoff", "10", 8)
        request = _DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="a" * 64,
            resources=(resource,),
            expected_versions=(
                ExpectedResourceVersion(resource, ConcurrencyToken(b"\x01" * 8)),
            ),
        )
        state = SimpleNamespace(request=request)

        class _Cursor:
            def __init__(self, row):
                self.row = row

            def execute(self, _sql, *_parameters):
                pass

            def fetchone(self):
                return self.row

        for ordinal in (-1, 1, 2):
            with self.subTest(ordinal=ordinal):
                with self.assertRaisesRegex(RuntimeError, "invalid ordinal"):
                    SqlProjectWriter._validate_mutation_locks(
                        state,
                        strict_cursor(_Cursor(("rowversion", None, ordinal, None))),
                        {resource},
                    )
        with self.assertRaises(_OptimisticConflict):
            SqlProjectWriter._validate_mutation_locks(
                state,
                strict_cursor(_Cursor(("rowversion", None, 0, b"\x02" * 8))),
                {resource},
            )

    def test_an_owner_conflict_without_a_display_name_still_reports_a_lock(self):
        resource = ResourceRef("takeoff", "10", 8)
        request = _DatabaseMutationRequest(
            database_id="database",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="a" * 64,
            resources=(resource,),
        )

        class _Cursor:
            def execute(self, _sql, *_parameters):
                pass

            def fetchone(self):
                return ("item_owner", None, None, None)

        with self.assertRaises(SqlInfrastructureError) as raised:
            SqlProjectWriter._validate_mutation_locks(
                SimpleNamespace(request=request), strict_cursor(_Cursor()), {resource}
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
        self.assertEqual(str(raised.exception), "This item is being edited by .")


class WriterFinishChangePayloadTests(unittest.TestCase):
    def _changes(self, records):
        writer, descriptor, manager = _recording_writer()
        state = _SqlMutationState(
            descriptor.database_id,
            manager.lease,
            _cleanup_support_DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
                resources=tuple(record.resource for record in records),
            ),
            records=list(records),
        )
        writer._finish_mutation(state, "value")
        _sql, params = next(
            statement
            for statement in manager.lease.statements
            if "DECLARE @Changes TABLE" in statement[0]
        )
        return json.loads(params[0])

    def test_feed_rows_carry_their_changed_fields_and_payload(self):
        takeoff = ResourceRef("takeoff", "10", 8)
        page = ResourceRef("page", "4", 8)
        changes = self._changes(
            [
                _RecordedMutation(
                    takeoff,
                    ChangeOperation.UPDATE,
                    changed_fields=("Name", "Show"),
                    payload='{"k":1}',
                ),
                _RecordedMutation(page, ChangeOperation.DELETE),
            ]
        )
        by_id = {change["resource_id"]: change for change in changes}
        self.assertEqual(json.loads(by_id["10"]["changed_fields"]), ["Name", "Show"])
        self.assertEqual(by_id["10"]["payload"], '{"k":1}')
        self.assertEqual(by_id["10"]["operation"], "update")
        self.assertIs(by_id["10"]["is_deleted"], False)
        self.assertIsNone(by_id["4"]["changed_fields"])
        self.assertIsNone(by_id["4"]["payload"])
        self.assertEqual(by_id["4"]["operation"], "delete")
        self.assertIs(by_id["4"]["is_deleted"], True)
        self.assertEqual([c["ordinal"] for c in changes], [0, 1])

    def test_entity_rows_behind_a_coalesced_feed_keep_neither_fields_nor_payload(self):
        records = [
            _RecordedMutation(
                ResourceRef("takeoff", str(uid), 8),
                ChangeOperation.UPDATE,
                changed_fields=("Name",),
                payload='{"k":1}',
            )
            for uid in range(451)
        ]
        changes = self._changes(records)
        feed = [change for change in changes if change["is_feed"]]
        entities = [change for change in changes if not change["is_feed"]]
        self.assertEqual(len(feed), 1)
        self.assertEqual(len(entities), 451)
        self.assertEqual(feed[0]["operation"], "bulk_refresh")
        self.assertIsNone(feed[0]["changed_fields"])
        self.assertIsNone(feed[0]["payload"])
        for change in entities:
            self.assertIsNone(change["changed_fields"])
            self.assertIsNone(change["payload"])
            self.assertEqual(change["operation"], "update")

    def test_family_collections_are_ordered_by_family_then_bid(self):
        records = [
            _RecordedMutation(
                ResourceRef("condition", f"c{n}", 9 if n % 2 == 0 else 2),
                ChangeOperation.UPDATE,
            )
            for n in range(460)
        ]
        # resource order (condition id) meets bid 9 before bid 2: the family tier must
        # still order its collections by bid, not by first appearance
        coalesced = SqlProjectWriter._coalesce_records(records)
        self.assertEqual(
            [(r.resource.resource_type, r.resource.bid_uid) for r in coalesced],
            [("conditions_collection", 2), ("conditions_collection", 9)],
        )


class WriterRecoveredPayloadShapeTests(unittest.TestCase):
    def test_json_that_is_not_the_documented_object_is_refused(self):
        request = DatabaseMutationRequest(
            database_id="database",
            session_id="session",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.TAKEOFF_PLACEMENT.value,
            request_hash="1" * 64,
        )
        state = _SqlMutationState("database", object(), request)
        for label, payload in (
            ("empty list", "[]"),
            ("null", "null"),
            ("number", "42"),
            ("string", '"value"'),
            ("list of the key names", '["value","value_available"]'),
            ("availability is 1, not true", '{"value":1,"value_available":1}'),
            ("availability is a string", '{"value":1,"value_available":"true"}'),
        ):
            with self.subTest(payload=label):
                with self.assertRaisesRegex(RuntimeError, "cannot reconstruct"):
                    SqlProjectWriter._recovered_operation_result(
                        state,
                        (request.mutation_type, request.request_hash, 1, payload),
                    )
        for value in ("0", "false", "null", "[]", '{"a":[1,2]}'):
            with self.subTest(value=value):
                result = SqlProjectWriter._recovered_operation_result(
                    state,
                    (
                        request.mutation_type,
                        request.request_hash,
                        1,
                        '{"value":' + value + ',"value_available":true}',
                    ),
                )
                self.assertEqual(result.value, json.loads(value))
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)


class WriterAccessFallbackHookTests(unittest.TestCase):
    def test_the_sql_writer_never_treats_a_driver_error_as_an_access_resource_limit(
        self,
    ):
        for error in (
            pyodbc.Error("HY001", "System resource exceeded"),
            pyodbc.Error("HY001", "Out of memory"),
            RuntimeError("System resource exceeded"),
        ):
            with self.subTest(error=str(error)):
                self.assertIs(
                    SqlProjectWriter._is_access_resource_exceeded(error), False
                )


import threading  # noqa: E402
from tests.helpers.sql.strict_sql_fakes import StrictRawConnection  # noqa: E402


class _PersistingConnection(StrictRawConnection):
    """A strict connection whose COMMIT makes the operation marker durable: the marker
    the finish batch inserted becomes visible to later transactions only when the
    server really applied the commit (an injected commit error with
    ``committed=True`` applies it, one without does not)."""

    def commit(self):
        queue = self.server._faults.get("commit")
        applied = True
        if queue and queue[0]["skip"] == 0 and not queue[0]["committed"]:
            applied = False
        try:
            super().commit()
        finally:
            if applied and self.number in self.server.pending_markers:
                self.server.marker = self.server.pending_markers[self.number]
            self.server.pending_markers.pop(self.number, None)

    def rollback(self):
        self.server.pending_markers.pop(self.number, None)
        super().rollback()


class _MarkerServer(_StrictMutationServer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pending_markers = {}

    def connect(self, connection_string, *, autocommit=False, timeout=0):
        self.connect_calls.append(
            {
                "connection_string": connection_string,
                "autocommit": autocommit,
                "timeout": timeout,
            }
        )
        connection = _PersistingConnection(self, len(self.connections) + 1, autocommit)
        self.connections.append(connection)
        return connection

    def _finish(self, call):
        self.pending_markers[call.connection.number] = (
            call.params[10],
            call.params[11],
            call.params[12],
            call.params[13],
        )
        return super()._finish(call)


class WriterOperationReplayTests(unittest.TestCase):
    """An operation whose COMMIT outcome is unknown is never replayed blindly: the
    same operation id resolves through the durable marker. The marker is modelled by
    the strict connection (see _PersistingConnection); a live server is not used."""

    def _request(self, descriptor, operation_id, **kwargs):
        return _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=operation_id,
            mutation_type=kwargs.pop(
                "mutation_type", CollaborationMutationType.PROJECT_WRITE.value
            ),
            request_hash=kwargs.pop("request_hash", "a" * 64),
            resources=(ResourceRef("database", descriptor.database_id),),
        )

    def _operation(self, descriptor, ran):
        def operation(recorder):
            ran.append(1)
            recorder.record(
                ResourceRef("database", descriptor.database_id), ChangeOperation.UPDATE
            )
            return ["100", {"k": (1, 2)}]

        return operation

    def test_a_commit_the_server_applied_is_recovered_not_rewritten(self):
        writer, descriptor, server = _strict_writer(_MarkerServer())
        operation_id = str(uuid.uuid4())
        ran = []
        server.fail(
            "commit",
            sql_server_error("08S01", "Communication link failure"),
            committed=True,
        )
        with server.patched():
            first = writer.execute(
                self._request(descriptor, operation_id),
                self._operation(descriptor, ran),
            )
            self.assertEqual(
                first.outcome_status, MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
            )
            second = writer.execute(
                self._request(descriptor, operation_id),
                self._operation(descriptor, ran),
            )
        self.assertEqual(second.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(second.value, ["100", {"k": [1, 2]}])
        self.assertTrue(second.commit_attempted)
        self.assertEqual(
            ran, [1], "the operation ran once; the retry only read the marker"
        )
        inserts = [
            s
            for connection in server.connections
            for s in server.statements(connection.number)
            if "INSERT INTO [ostv].[ChangeTransactions]" in s
        ]
        self.assertEqual(len(inserts), 1)

    def test_a_commit_the_server_did_not_apply_is_written_by_the_retry(self):
        writer, descriptor, server = _strict_writer(_MarkerServer())
        operation_id = str(uuid.uuid4())
        ran = []
        server.fail(
            "commit",
            sql_server_error("08S01", "Communication link failure"),
            committed=False,
        )
        with server.patched():
            first = writer.execute(
                self._request(descriptor, operation_id),
                self._operation(descriptor, ran),
            )
            second = writer.execute(
                self._request(descriptor, operation_id),
                self._operation(descriptor, ran),
            )
        self.assertEqual(
            first.outcome_status, MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN
        )
        self.assertEqual(second.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(ran, [1, 1])
        self.assertEqual(
            server.marker[0], CollaborationMutationType.PROJECT_WRITE.value
        )

    def test_a_committed_operation_id_reused_for_another_request_is_a_conflict(self):
        writer, descriptor, server = _strict_writer(_MarkerServer())
        operation_id = str(uuid.uuid4())
        ran = []
        with server.patched():
            first = writer.execute(
                self._request(descriptor, operation_id),
                self._operation(descriptor, ran),
            )
            other = writer.execute(
                self._request(descriptor, operation_id, request_hash="b" * 64),
                self._operation(descriptor, ran),
            )
        self.assertEqual(first.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(other.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertIn("reused with a different request", other.conflict.reason)
        self.assertEqual(ran, [1])


class WriterLeaseIsolationTests(unittest.TestCase):
    def test_each_mutation_thread_writes_only_through_its_own_connection(self):
        writer, descriptor, server = _strict_writer()
        server.on("INSERT INTO [dbo].[BidProjects]", Reply.rows((1,)))
        barrier = threading.Barrier(2, timeout=20)
        inside_first = threading.Event()
        failures = []

        def run(name, project):
            resource = ResourceRef("project", project)

            def operation(recorder):
                if name == "first":
                    inside_first.set()
                barrier.wait()
                writer.create_project(descriptor.database_id, name)
                recorder.record(resource, ChangeOperation.CREATE)
                return name

            request = _DatabaseMutationRequest(
                database_id=descriptor.database_id,
                session_id="session-1",
                operation_id=str(uuid.uuid4()),
                mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
                request_hash="a" * 64,
                resources=(resource,),
            )
            try:
                result = writer.execute(request, operation)
                if result.outcome_status != MutationOutcomeStatus.COMMITTED:
                    failures.append((name, result.outcome_status))
            except BaseException as exc:  # noqa: BLE001 - reported below
                failures.append((name, exc))

        with server.patched():
            first = threading.Thread(target=run, args=("first", "1"))
            first.start()
            self.assertTrue(inside_first.wait(20))
            second = threading.Thread(target=run, args=("second", "2"))
            second.start()
            first.join(30)
            second.join(30)
        self.assertEqual(failures, [])
        self.assertEqual(len(server.connections), 2)
        written = {
            connection.number: [
                params
                for cursor in connection.cursors
                for sql, params in cursor.executed
                if "INSERT INTO [dbo].[BidProjects]" in sql
            ]
            for connection in server.connections
        }
        self.assertEqual(sorted(written.values()), [[("first",)], [("second",)]])
        server.assert_everything_closed()

    def test_a_thread_started_inside_a_mutation_cannot_borrow_its_lease(self):
        writer, descriptor, server = _strict_writer()
        outcome = {}
        resource = ResourceRef("database", descriptor.database_id)

        def operation(recorder):
            def borrow():
                try:
                    writer.create_project(descriptor.database_id, "stolen")
                except SqlInfrastructureError as exc:
                    outcome["code"] = exc.details.code

            worker = threading.Thread(target=borrow)
            worker.start()
            worker.join(20)
            recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            result = writer.execute(request, operation)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(outcome, {"code": SqlErrorCode.SESSION_EXPIRED})
        self.assertFalse(
            any("BidProjects" in s for s in server.statements(1)),
            "the foreign thread must not have sent a statement on the mutation connection",
        )


class WriterSessionAndTrustTests(unittest.TestCase):
    def _request(self, descriptor):
        return _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(ResourceRef("database", descriptor.database_id),),
        )

    def test_a_database_without_a_registered_session_is_a_session_conflict(self):
        writer, descriptor, server = _strict_writer()
        writer._session_registry.remove(descriptor.database_id)
        executed = []
        with server.patched():
            result = writer.execute(
                self._request(descriptor), lambda recorder: executed.append(1)
            )
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.SESSION)
        self.assertEqual(
            result.conflict.reason,
            "This SQL database has no active collaboration session and is read-only.",
        )
        self.assertEqual(executed, [])
        self.assertEqual(
            server.connections, [], "no connection is opened without a session"
        )

    def test_losing_write_trust_before_the_first_statement_aborts_the_mutation(self):
        class _Untrusted(_StrictMutationServer):
            @staticmethod
            def _permission_snapshot(_call):
                return Reply.rows(
                    _cleanup_support__canonical_writer_permission_snapshot(
                        roles=(1, 0, 1, 1, 1)
                    )
                )

        writer, descriptor, server = _strict_writer(_Untrusted())
        executed = []
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                writer.execute(
                    self._request(descriptor), lambda recorder: executed.append(1)
                )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.PERMISSION_DENIED)
        self.assertTrue(raised.exception.read_only_required)
        self.assertEqual(executed, [])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        statements = " ".join(server.statements(1))
        self.assertNotIn("sp_getapplock", statements)
        self.assertNotIn("DECLARE @Changes TABLE", statements)
        server.assert_everything_closed()

    def test_a_connection_lost_on_the_very_first_statement_is_classified_and_cleaned_up(
        self,
    ):
        writer, descriptor, server = _strict_writer()

        def lost(_call):
            raise sql_server_error("08S01", "Communication link failure")

        server.rules.insert(0, (lambda sql: "ostv_permission_snapshot" in sql, lost))
        executed = []
        with server.patched():
            with self.assertRaises(SqlInfrastructureError) as raised:
                writer.execute(self._request(descriptor), lambda r: executed.append(1))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        self.assertEqual(executed, [])
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertEqual(len(server.connections), 1)
        server.assert_everything_closed()


class WriterEvaluatedTablesTests(unittest.TestCase):
    def test_the_sqlite_stand_in_tables_use_only_columns_of_the_canonical_schema(self):
        canonical = {
            ("dbo", table.name): {column.name for column in table.columns}
            for table in SQL_SCHEMA_V1.core_schema.tables
        }
        canonical.update(
            {
                (table.schema, table.name): {column.name for column in table.columns}
                for table in SQL_SCHEMA_V1.tables
            }
        )
        self.assertTrue(LockDatabase.COLUMNS)
        for table, columns in LockDatabase.COLUMNS.items():
            with self.subTest(table=table):
                self.assertTrue(set(columns) <= canonical[table])


import hashlib  # noqa: E402
import re  # noqa: E402


class WriterLockValidationBoundaryTests(unittest.TestCase):
    """Per-branch expiry boundaries and ownership of the evaluated validation SQL
    (same harness as WriterLockValidationSemanticsTests)."""

    ME = WriterLockValidationSemanticsTests.ME
    TOKEN = WriterLockValidationSemanticsTests.TOKEN
    TAKEOFF = WriterLockValidationSemanticsTests.TAKEOFF
    BID = WriterLockValidationSemanticsTests.BID
    _database = WriterLockValidationSemanticsTests._database
    _run = WriterLockValidationSemanticsTests._run
    _assert_lock_conflict = WriterLockValidationSemanticsTests._assert_lock_conflict
    _assert_committed = WriterLockValidationSemanticsTests._assert_committed

    def _check(self, build, resources, expires_in_cases, message, **kwargs):
        """For each (expires_in, refused): the lock built with that expiry either
        refuses with ``message`` or lets the write commit."""
        for expires_in, refused in expires_in_cases:
            with self.subTest(expires_in=expires_in):
                database = build(self._database(), expires_in)
                result, request, server, executed = self._run(
                    database, resources, **kwargs
                )
                if refused:
                    self._assert_lock_conflict(
                        result, request, server, executed, message
                    )
                else:
                    self._assert_committed(result, server, executed)

    def test_a_parent_bid_lock_blocks_a_child_write_until_the_instant_it_expires(self):
        self._check(
            lambda db, e: db.add_lock(
                "bid", "8", "ana-session", self.TOKEN, expires_in=e
            ),
            [self.TAKEOFF],
            ((1, True), (0, False), (-1, False)),
            "This bid is being changed by Ana.",
        )

    def test_a_child_lock_blocks_a_bid_write_until_the_instant_it_expires(self):
        self._check(
            lambda db, e: db.add_lock(
                "takeoff", "10", "ana-session", self.TOKEN, bid_uid=8, expires_in=e
            ),
            [self.BID],
            ((1, True), (0, False), (-1, False)),
            "This bid contains an item being edited by Ana.",
            block_bid_child_locks=True,
        )

    def test_a_required_token_is_live_until_the_instant_its_lock_expires(self):
        self._check(
            lambda db, e: db.add_lock(
                "takeoff", "10", self.ME, self.TOKEN, bid_uid=8, expires_in=e
            ),
            [self.TAKEOFF],
            ((1, False), (0, True), (-1, True)),
            "A required SQL edit lock expired before the write.",
            required_lock_tokens=(self.TOKEN,),
        )

    def test_a_foreign_token_is_reported_only_while_its_lock_is_live(self):
        for expires_in, message in (
            (1, "A SQL edit lock does not belong to this mutation."),
            (0, "A required SQL edit lock expired before the write."),
        ):
            with self.subTest(expires_in=expires_in):
                database = self._database().add_lock(
                    "takeoff",
                    "99",
                    self.ME,
                    self.TOKEN,
                    bid_uid=8,
                    expires_in=expires_in,
                )
                result, request, server, executed = self._run(
                    database, [self.TAKEOFF], required_lock_tokens=(self.TOKEN,)
                )
                self._assert_lock_conflict(result, request, server, executed, message)

    def test_an_owned_lock_must_be_presented_only_while_it_is_live(self):
        self._check(
            lambda db, e: db.add_lock(
                "takeoff", "10", self.ME, self.TOKEN, bid_uid=8, expires_in=e
            ),
            [self.TAKEOFF],
            ((1, True), (0, False), (-1, False)),
            "The mutation did not present its owned SQL edit lock.",
        )

    def test_the_requesting_sessions_own_bid_lock_does_not_block_its_children(self):
        database = self._database().add_lock("bid", "8", self.ME, self.TOKEN)
        result, _request, server, executed = self._run(database, [self.TAKEOFF])
        self._assert_committed(result, server, executed)
        database = self._database().add_lock(
            "takeoff", "10", self.ME, self.TOKEN, bid_uid=8
        )
        result, _request, server, executed = self._run(
            database, [self.BID], block_bid_child_locks=True
        )
        self._assert_committed(result, server, executed)

    def test_tokens_are_matched_case_insensitively_against_the_stored_guid_text(self):
        database = self._database().add_lock(
            "takeoff", "10", self.ME, self.TOKEN, bid_uid=8
        )
        for token in (self.TOKEN, self.TOKEN.upper(), self.TOKEN.title()):
            with self.subTest(token=token):
                result, _request, server, executed = self._run(
                    database, [self.TAKEOFF], required_lock_tokens=(token,)
                )
                self._assert_committed(result, server, executed)


class WriterValidationPriorityTextTests(unittest.TestCase):
    """SQL Server resolves equal ORDER BY keys arbitrarily and sqlite breaks ties in
    branch order, so the evaluated tests cannot show a TIE: the priority of every
    Violations branch is pinned as text, per branch and pairwise distinct."""

    def _statement(self):
        writer, descriptor, server = _strict_writer(_StrictMutationServer())
        resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            writer.execute(request, mutate)
        return next(
            s for s in server.statements(1) if "DECLARE @MutationResources TABLE" in s
        )

    def test_every_violation_branch_has_its_own_priority_expression(self):
        sql = self._statement()
        found = dict(
            (kind, priority.strip())
            for priority, kind in re.findall(
                r"SELECT (-?\d+|[\w.\[\]*+]+)(?: AS \[Priority\])?, N'(\w+)'", sql
            )
        )
        self.assertEqual(
            found,
            {
                "item_owner": "resources.[Ordinal]*10",
                "bid_owner": "resources.[Ordinal]*10+1",
                "child_owner": "resources.[Ordinal]*10+2",
                "active_editor": "resources.[Ordinal]*10+3",
                "token_expired": "100000",
                "token_resource": "100001",
                "owned_omitted": "100010+resources.[Ordinal]",
                "rowversion": "200000+expected.[Ordinal]",
                "bid_locked": "-1",
            },
        )
        self.assertEqual(len(set(found.values())), len(found))

    def test_the_statement_selects_one_row_ordered_by_priority(self):
        sql = self._statement()
        self.assertTrue(
            sql.endswith(
                "SELECT TOP (1) [Kind], [Owner], [ExpectedOrdinal], [ActualToken] "
                "FROM Violations ORDER BY [Priority]"
            )
        )


def _normalized_digest(sql):
    return hashlib.sha256(" ".join(sql.split()).encode("utf-8")).hexdigest()


class WriterUnexecutableStatementPinTests(unittest.TestCase):
    """Change detectors for the T-SQL that no fake here can execute (table variables
    with OUTPUT INTO, UPDATE ... FROM, THROW, IF/ELSE batches): the whitespace
    normalised text of each is pinned by SHA-256. A failure means the statement
    changed: re-verify it against a live SQL Server (the live-gated
    tests/integration/sql suite) BEFORE updating the digest. These pins prove
    nothing about the SQL's correctness."""

    FINISH = "a96e0bb23aad5628f7a319d6890591c0d26ad36d870420c652098e1f4e7c7110"
    PREFLIGHT_NO_ANNOTATIONS = (
        "c118740eb077ab23123e58dd6a18bbec447140cb72db3a4587b9d6a0996a2646"
    )
    PREFLIGHT_ONE_TABLE = (
        "e7dce98989fb55feb7816dcbfa78fbc23b76491e077da8dc1062c069f46fd902"
    )
    PREFLIGHT_TWO_TABLES = (
        "50e5acc476f325dadeea6d26b07d51ac6812cfd36eabaeac6f6640f789c89c78"
    )
    DELETE_TAKEOFFS = "76ff0bfb7d50b89058c87c0ad1399ea33f5a473d6cc872db4790e9270183bfa6"

    def test_the_version_feed_marker_batch_text_is_pinned(self):
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
        writer._finish_mutation(state, "value")
        sql = next(s for s, _p in manager.lease.statements if "@Changes" in s)
        self.assertEqual(_normalized_digest(sql), self.FINISH)

    def _preflight(self, annotations):
        executed = []

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *params):
                executed.append(sql)

            @staticmethod
            def fetchone():
                return (0,)

        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

        @contextlib.contextmanager
        def connection(_database_id):
            yield SimpleNamespace(cursor=lambda: strict_cursor(_Cursor()))

        writer._connection = connection
        writer.verify_plan_items_exist("database", "8", ("1",), annotations)
        return executed[0]

    def test_the_plan_item_preflight_texts_are_pinned(self):
        first, second = list(ANNOTATION_TABLE_BY_TYPE)[:2]
        self.assertEqual(
            _normalized_digest(self._preflight(())), self.PREFLIGHT_NO_ANNOTATIONS
        )
        self.assertEqual(
            _normalized_digest(self._preflight((("5", first),))),
            self.PREFLIGHT_ONE_TABLE,
        )
        self.assertEqual(
            _normalized_digest(self._preflight((("5", first), ("6", second)))),
            self.PREFLIGHT_TWO_TABLES,
        )

    def test_the_takeoff_deletion_text_is_pinned(self):
        executed = []

        class _Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, *params):
                executed.append(sql)

            @staticmethod
            def fetchone():
                return (1,)

        writer = SqlProjectWriter.__new__(SqlProjectWriter)
        writer._write_schema = CurrentSqlWriteSchema(SQL_SCHEMA_V1.core_schema)

        @contextlib.contextmanager
        def connection(_database_id):
            yield SimpleNamespace(cursor=lambda: strict_cursor(_Cursor()))

        writer._connection = connection
        writer._run_delete_takeoffs("database", [7, 8], 100)
        self.assertEqual(_normalized_digest(executed[0]), self.DELETE_TAKEOFFS)

    def test_the_prepare_head_and_session_context_statements_are_pinned_verbatim(self):
        writer, descriptor, server = _strict_writer(_StrictMutationServer())
        resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            writer.execute(request, mutate)
        statements = server.statements(1)
        self.assertTrue(
            statements[1].startswith(
                "DECLARE @LockResult int; EXEC @LockResult=sys.sp_getapplock "
                "@Resource=?, @LockMode=N'Exclusive', @LockOwner=N'Transaction', "
                "@LockTimeout=10000; SELECT @LockResult, marker.[OperationType], "
                "marker.[RequestHash], marker.[ResultFormatVersion], "
                "marker.[ResultPayload], CASE WHEN EXISTS (SELECT 1 FROM "
                "[ostv].[Sessions] sessions WHERE sessions.[SessionId]=? AND "
                "sessions.[DisconnectedAt] IS NULL AND "
                "sessions.[LastHeartbeatAt]>=DATEADD(second, ?, SYSUTCDATETIME())) "
                "THEN 1 ELSE 0 END FROM (VALUES (1)) seed([Value]) LEFT JOIN "
                "[ostv].[ChangeTransactions] marker ON marker.[TransactionId]=?"
            )
        )
        self.assertEqual(
            statements[-1],
            "EXEC sys.sp_set_session_context @key=N'ostv_session_id', @value=NULL; "
            "EXEC sys.sp_set_session_context @key=N'ostv_transaction_id', @value=NULL",
        )


class WriterOperationLockModeTests(unittest.TestCase):
    """The operation lock must be EXCLUSIVE: two clients racing one operation id must
    not both proceed. The strict model takes the mode from the statement text."""

    def _run(self, holder_mode):
        class _ModeServer(_StrictMutationServer):
            def _prepare(self, call):
                mode = re.search(r"@LockMode=N'(\w+)'", call.sql).group(1)
                code = self.applocks.acquire(call.connection, call.params[0], mode)
                return Reply.rows((code, None, None, None, None, self.session_alive))

        server = _ModeServer()
        writer, descriptor, server = _strict_writer(server)
        resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        holder = server.other_session()
        server.applocks.acquire(
            holder, f"OSTV:operation:{request.operation_id}", holder_mode
        )
        executed = []
        with server.patched():
            result = writer.execute(
                request, lambda recorder: executed.append(1) or mutate(recorder)
            )
        return result, executed

    def test_a_shared_holder_of_the_operation_lock_still_blocks_the_writer(self):
        result, executed = self._run("Shared")
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(executed, [])

    def test_an_exclusive_holder_blocks_the_writer_too(self):
        result, executed = self._run("Exclusive")
        self.assertEqual(result.conflict.kind, SynchronizationConflictKind.LEASE)
        self.assertEqual(executed, [])


class WriterStrictBatchProtocolTests(unittest.TestCase):
    """The plan-item preflight and the takeoff deletion run inside a mutation on the
    strict server with result-count modelling: a batch that leaves NOCOUNT OFF
    would front its rows with count-only results that ``fetchone`` cannot read."""

    def _server(self, **rules):
        server = _StrictMutationServer()
        for marker, reply in rules.items():
            server.on(marker, reply)
        return server

    def _execute(self, server, operation, resources=()):
        writer, descriptor, server = _strict_writer(server)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources) or (ResourceRef("takeoff", "7", 8),),
        )
        with server.patched():
            result = writer.execute(
                request, lambda recorder: operation(writer, descriptor, recorder)
            )
        return result, server

    def test_the_preflight_reads_its_status_through_one_closed_cursor(self):
        seen = []

        def status(call):
            seen.append(call.params)
            return Reply.rows((0,))

        server = self._server()
        server.rules.insert(0, (lambda sql: "DECLARE @ExpectedBidUID" in sql, status))

        def operation(writer, descriptor, recorder):
            writer.verify_plan_items_exist(descriptor.database_id, "8", ("7", "7"), ())
            recorder.record(ResourceRef("takeoff", "7", 8), ChangeOperation.UPDATE)
            return True

        result, server = self._execute(server, operation)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], 8)
        self.assertEqual(json.loads(seen[0][1]), [7])
        self.assertEqual(json.loads(seen[0][2]), [])
        kinds = server.event_kinds(1)
        commit_at = kinds.index("commit")
        self.assertEqual(
            kinds[:commit_at].count("cursor_open"),
            kinds[:commit_at].count("cursor_close"),
        )
        server.assert_everything_closed()

    def test_a_preflight_status_aborts_the_mutation_as_an_optimistic_conflict(self):
        for status, optimistic in ((1, True), (2, True), (3, False)):
            with self.subTest(status=status):
                server = self._server()
                server.rules.insert(
                    0,
                    (
                        lambda sql: "DECLARE @ExpectedBidUID" in sql,
                        lambda _call, status=status: Reply.rows((status,)),
                    ),
                )

                def operation(writer, descriptor, recorder):
                    writer.verify_plan_items_exist(
                        descriptor.database_id, "8", ("7",), ()
                    )
                    recorder.record(
                        ResourceRef("takeoff", "7", 8), ChangeOperation.UPDATE
                    )
                    return True

                result, server = self._execute(server, operation)
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    result.conflict.kind,
                    (
                        SynchronizationConflictKind.OPTIMISTIC_CONCURRENCY
                        if optimistic
                        else SynchronizationConflictKind.SESSION
                    ),
                )
                raw = server.connections[0]
                self.assertEqual((raw.commits, raw.rollbacks), (0, 1))

    def test_a_takeoff_deletion_is_one_batch_with_deduplicated_uids(self):
        server = self._server()
        server.rules.insert(
            0, (lambda sql: "DECLARE @Requested TABLE" in sql, Reply.rows((3,)))
        )

        def operation(writer, descriptor, recorder):
            deleted = writer.delete_takeoffs(descriptor.database_id, ["7", "7", "8"])
            recorder.record(ResourceRef("takeoff", "7", 8), ChangeOperation.DELETE)
            return deleted

        result, server = self._execute(server, operation)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        self.assertIs(result.value, True)
        deletions = [
            (sql, params)
            for connection in server.connections
            for cursor in connection.cursors
            for sql, params in cursor.executed
            if "DECLARE @Requested TABLE" in sql
        ]
        self.assertEqual(len(deletions), 1)
        self.assertEqual(json.loads(deletions[0][1][0]), [7, 8])
        self.assertEqual(len(deletions[0][1]), 1)
        server.assert_everything_closed()

    def test_an_incomplete_deletion_raised_by_the_server_rolls_everything_back(self):
        def incomplete(_call):
            raise sql_server_error(
                "42000", "The takeoff deletion was incomplete.", 51000
            )

        server = self._server()
        server.rules.insert(
            0, (lambda sql: "DECLARE @Requested TABLE" in sql, incomplete)
        )

        def operation(writer, descriptor, recorder):
            writer.delete_takeoffs(descriptor.database_id, ["7"])
            recorder.record(ResourceRef("takeoff", "7", 8), ChangeOperation.DELETE)
            return True

        writer, descriptor, server = _strict_writer(server)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(ResourceRef("takeoff", "7", 8),),
        )
        with server.patched():
            with self.assertRaises(SqlInfrastructureError):
                writer.execute(
                    request, lambda recorder: operation(writer, descriptor, recorder)
                )
        raw = server.connections[0]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertEqual(
            sum("DECLARE @Requested TABLE" in s for s in server.statements(1)), 1
        )
        self.assertNotIn("DECLARE @Changes TABLE", " ".join(server.statements(1)))
        server.assert_everything_closed()

    def test_count_only_results_front_the_rows_of_a_batch_that_leaves_nocount_off(self):
        # Positive control for the protocol rule itself: the same server, a batch
        # without SET NOCOUNT ON that inserts before it selects.
        server = StrictSqlServer()
        server.model_result_counts = True
        server.on("INSERT INTO [dbo].[BidProjects]", Reply.rows((5,)))
        server.on("DECLARE @T TABLE", Reply.rows((9,)))
        connection = server.connect("x", autocommit=False)
        cursor = connection.cursor()
        cursor.execute(
            "DECLARE @T TABLE ([A] int); INSERT INTO @T VALUES (1); SELECT 9"
        )
        with self.assertRaises(pyodbc.ProgrammingError):
            cursor.fetchone()
        self.assertTrue(cursor.nextset())
        self.assertEqual(cursor.fetchone(), (9,))
        cursor.close()
        cursor = connection.cursor()
        cursor.execute(
            "SET NOCOUNT ON; DECLARE @T TABLE ([A] int); INSERT INTO @T VALUES (1); SELECT 9"
        )
        self.assertEqual(cursor.fetchone(), (9,))
        cursor.close()
        fresh = server.connect("x", autocommit=False)
        cursor = fresh.cursor()
        cursor.execute(
            "INSERT INTO [dbo].[BidProjects] ([Name]) OUTPUT INSERTED.[UID] VALUES (?)",
            "x",
        )
        self.assertEqual(cursor.fetchone(), (5,))
        cursor.close()


class WriterSchemaContractTests(unittest.TestCase):
    """The T-SQL the writer sends against the canonical ostv schema: table-variable
    widths, CHECK-constraint vocabularies and DTO limits must agree, otherwise SQL
    Server truncates (OPENJSON ... WITH widths) or a constraint rejects the batch at
    commit time. Static comparisons only: no server executes either side."""

    @staticmethod
    def _type(table, column):
        for definition in SQL_SCHEMA_V1.tables:
            if definition.name == table:
                return next(c.data_type for c in definition.columns if c.name == column)
        raise AssertionError(table)

    @staticmethod
    def _declarations(sql):
        found = {}
        for name, body in re.findall(
            r"DECLARE @(\w+) TABLE \(((?:[^()]|\([^()]*\))*)\)", sql
        ):
            found[name] = dict(
                (column, kind)
                for column, kind in re.findall(r"\[(\w+)\] (\w+(?:\(\w+\))?)", body)
            )
        return found

    def _statements(self):
        writer, descriptor, server = _strict_writer(_StrictMutationServer())
        resource, mutate = _record_database_update(descriptor)
        request = _DatabaseMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=(resource,),
        )
        with server.patched():
            writer.execute(request, mutate)
        statements = server.statements(1)
        finish = next(s for s in statements if "DECLARE @Changes TABLE" in s)
        validation = next(
            s for s in statements if "DECLARE @MutationResources TABLE" in s
        )
        return finish, validation

    def test_the_finish_batch_table_variables_are_as_wide_as_the_columns_they_fill(
        self,
    ):
        finish, _validation = self._statements()
        declared = self._declarations(finish)
        self.assertTrue(declared)
        changes = declared["Changes"]
        self.assertEqual(
            changes["ResourceType"], self._type("EntityVersions", "ResourceType")
        )
        self.assertEqual(
            changes["ResourceType"], self._type("ChangeLog", "ResourceType")
        )
        self.assertEqual(
            changes["ResourceId"], self._type("EntityVersions", "ResourceId")
        )
        self.assertEqual(changes["ResourceId"], self._type("ChangeLog", "ResourceId"))
        self.assertEqual(changes["Operation"], self._type("ChangeLog", "Operation"))
        self.assertEqual(
            changes["ChangedFields"], self._type("ChangeLog", "ChangedFields")
        )
        self.assertEqual(changes["Payload"], self._type("ChangeLog", "Payload"))
        self.assertEqual(changes["BidUID"], self._type("ChangeLog", "BidUID"))
        self.assertEqual(declared["Versions"]["Token"], "varbinary(8)")
        self.assertEqual(self._type("ChangeLog", "ResultVersion"), "varbinary(8)")
        self.assertEqual(self._type("EntityVersions", "Token"), "rowversion")
        self.assertEqual(declared["ConsumedTokens"]["LockToken"], "nvarchar(36)")
        self.assertEqual(self._type("Locks", "LockToken"), "uniqueidentifier")

    def test_the_validation_batch_table_variables_match_the_lock_and_version_columns(
        self,
    ):
        _finish, validation = self._statements()
        declared = self._declarations(validation)
        for variable in ("MutationResources", "ExpectedVersions"):
            self.assertEqual(
                declared[variable]["ResourceType"], self._type("Locks", "ResourceType")
            )
            self.assertEqual(
                declared[variable]["ResourceType"],
                self._type("EntityVersions", "ResourceType"),
            )
            self.assertEqual(
                declared[variable]["ResourceId"], self._type("Locks", "ResourceId")
            )
            self.assertEqual(
                declared[variable]["ResourceId"],
                self._type("EntityVersions", "ResourceId"),
            )
        self.assertEqual(declared["ExpectedVersions"]["ExpectedToken"], "varbinary(8)")
        self.assertEqual(declared["RequiredTokens"]["LockToken"], "nvarchar(36)")

    def test_the_resource_reference_limits_equal_the_schema_widths(self):
        self.assertEqual(self._type("EntityVersions", "ResourceType"), "nvarchar(64)")
        self.assertEqual(self._type("EntityVersions", "ResourceId"), "nvarchar(128)")
        ResourceRef("database", "x" * 128)
        with self.assertRaises(ValueError):
            ResourceRef("database", "x" * 129)
        with self.assertRaises(ValueError):
            ResourceRef("x" * 65, "1")

    def test_every_mutation_type_and_family_summary_fits_its_column(self):
        self.assertEqual(
            self._type("ChangeTransactions", "OperationType"), "nvarchar(64)"
        )
        for mutation_type in CollaborationMutationType:
            with self.subTest(mutation_type=mutation_type.value):
                self.assertLessEqual(len(mutation_type.value), 64)
        self.assertEqual(
            self._type("ChangeTransactions", "ResourceFamilySummary"), "nvarchar(1024)"
        )
        from ost_visualizer.application.dtos.collaboration_resource_catalog import (
            COLLABORATION_RESOURCE_CATALOG,
            coalesced_resource_type,
        )

        families = sorted(
            {coalesced_resource_type(kind) for kind in COLLABORATION_RESOURCE_CATALOG}
        )
        self.assertLessEqual(len(json.dumps(families)), 1024)
        self.assertEqual(self._type("ChangeTransactions", "RequestHash"), "char(64)")
        self.assertEqual(
            self._type("ChangeTransactions", "ResultFormatVersion"), "smallint"
        )

    def test_check_constraint_vocabularies_match_the_values_the_writer_sends(self):
        def allowed(table, constraint):
            definition = next(t for t in SQL_SCHEMA_V1.tables if t.name == table)
            expression = next(
                e for n, e in definition.check_constraints if n == constraint
            )
            return set(re.findall(r"N'([^']+)'", expression))

        self.assertEqual(
            allowed("ChangeLog", "CK_ostv_ChangeLog_Operation"),
            {operation.value for operation in ChangeOperation},
        )
        self.assertEqual(
            allowed("ChangeLog", "CK_ostv_ChangeLog_SourceKind"),
            {"external", "ost_visualizer"},
        )
        finish, validation = self._statements()
        self.assertIn("N'ost_visualizer'", finish)
        self.assertEqual(
            allowed("Presence", "CK_ostv_Presence_ActivityMode"), {"editing", "viewing"}
        )
        self.assertIn("presence.[ActivityMode]=N'editing'", validation)


import random  # noqa: E402
from ost_visualizer.infrastructure.sql.writer import _BidLockedRefusal  # noqa: E402


class _LockRulesOracle:
    """An INDEPENDENT restatement of the lock-validation rules, written from the rule
    descriptions (not from the SQL): which Violations branch fires for a state, with
    its priority. ``expected()`` is the lowest-priority entries or None."""

    STALE = 45

    def __init__(self, database, request, resources, me="session-1"):
        self.db = database
        self.request = request
        self.ordered = sorted(resources)
        self.me = me

    def expected(self):
        db, request, me = self.db, self.request, self.me
        now = db.at(0)
        alive_after = db.at(-self.STALE)
        names = {session[0]: session[1] for session in db.sessions}
        found = []
        locked_status = dict(db.statuses)
        if not request.bid_lock_exempt:
            for resource in self.ordered:
                if resource.resource_type == "bid" or resource.bid_uid is None:
                    continue
                for bid_uid, status_uid in db.bids:
                    if bid_uid == resource.bid_uid and status_uid in locked_status:
                        if (
                            locked_status[status_uid] is None
                            or locked_status[status_uid] == 1
                        ):
                            found.append((-1, "bid_locked", None))
        for ordinal, resource in enumerate(self.ordered):
            for lock in db.locks:
                if lock[5] <= now or lock[3] == me:
                    continue
                owner = names[lock[3]]
                if (lock[0], lock[1]) == (resource.resource_type, resource.resource_id):
                    found.append((ordinal * 10, "item_owner", {owner}))
                if (
                    resource.resource_type != "bid"
                    and resource.bid_uid is not None
                    and lock[0] == "bid"
                    and lock[1] == str(resource.bid_uid)
                ):
                    found.append((ordinal * 10 + 1, "bid_owner", {owner}))
                if (
                    request.block_bid_child_locks
                    and resource.resource_type == "bid"
                    and lock[2] is not None
                    and lock[2] == resource.bid_uid
                ):
                    found.append((ordinal * 10 + 2, "child_owner", {owner}))
            if request.block_bid_active_editors and resource.resource_type == "bid":
                for presence in db.presence:
                    session = next(s for s in db.sessions if s[0] == presence[0])
                    if (
                        presence[1] == resource.bid_uid
                        and presence[2] == "editing"
                        and presence[0] != me
                        and session[2] is None
                        and session[3] >= alive_after
                    ):
                        found.append(
                            (ordinal * 10 + 3, "active_editor", {names[presence[0]]})
                        )
        tokens = {token.casefold() for token in request.required_lock_tokens}
        own_live = [lock for lock in db.locks if lock[3] == me and lock[5] > now]
        requested = {(r.resource_type, r.resource_id) for r in self.ordered}
        for token in tokens:
            matching = [lock for lock in own_live if lock[4].lower() == token]
            if not matching:
                found.append((100000, "token_expired", None))
            for lock in matching:
                if (lock[0], lock[1]) not in requested:
                    found.append((100001, "token_resource", None))
        for ordinal, resource in enumerate(self.ordered):
            for lock in own_live:
                if (lock[0], lock[1]) == (resource.resource_type, resource.resource_id):
                    if lock[4].lower() not in tokens:
                        found.append((100010 + ordinal, "owned_omitted", None))
        for ordinal, expected in enumerate(request.expected_versions):
            key = (expected.resource.resource_type, expected.resource.resource_id)
            rows = [v for v in db.versions if (v[0], v[1]) == key]
            if not rows or rows[0][2] != expected.expected.value:
                found.append(
                    (
                        200000 + ordinal,
                        "rowversion",
                        (expected, rows[0][2] if rows else None),
                    )
                )
        if not found:
            return None
        best = min(priority for priority, _kind, _detail in found)
        return [entry for entry in found if entry[0] == best]


class WriterLockRulesOracleTests(unittest.TestCase):
    """Random schema-consistent states (every lock owner and presence session exists)
    run through the writer's REAL validation statement on sqlite and compared with the
    independent oracle above: any semantic edit of the SQL (join type, boundary,
    comparison, priority, parameter binding) or of the Python binding shows up as a
    disagreement. The oracle encodes the rules, so a failure can also mean the oracle
    is wrong: both were reconciled on the unmutated writer."""

    UNIVERSE = [
        ResourceRef("bid", "8", 8),
        ResourceRef("bid", "9", 9),
        ResourceRef("takeoff", "10", 8),
        ResourceRef("takeoff", "11", 8),
        ResourceRef("page", "20", 9),
        ResourceRef("project", "3"),
        ResourceRef("database", "d"),
    ]
    SESSIONS = {"session-1": "Me", "ana-session": "Ana", "bob-session": "Bob"}
    MESSAGES = {
        "item_owner": "This item is being edited by {}.",
        "bid_owner": "This bid is being changed by {}.",
        "child_owner": "This bid contains an item being edited by {}.",
        "active_editor": "This bid is actively being edited by {}.",
    }
    FIXED = {
        "token_expired": "A required SQL edit lock expired before the write.",
        "token_resource": "A SQL edit lock does not belong to this mutation.",
        "owned_omitted": "The mutation did not present its owned SQL edit lock.",
    }

    def _state(self, rng):
        database = LockDatabase()
        for session_id, name in self.SESSIONS.items():
            database.add_session(
                session_id,
                name,
                heartbeat_age=rng.choice((0, 44, 45, 46, 300)),
                disconnected=rng.random() < 0.2,
            )
        tokens = []
        for resource in self.UNIVERSE + [ResourceRef("takeoff", "99", 8)]:
            if rng.random() < 0.45:
                token = str(uuid.UUID(int=rng.getrandbits(128)))
                tokens.append(token)
                database.add_lock(
                    resource.resource_type,
                    resource.resource_id,
                    rng.choice(list(self.SESSIONS)),
                    token,
                    bid_uid=resource.bid_uid,
                    expires_in=rng.choice((-5, 0, 5)),
                )
        for session_id in self.SESSIONS:
            if rng.random() < 0.5:
                database.add_presence(
                    session_id,
                    rng.choice((8, 9, None)),
                    rng.choice(("editing", "viewing")),
                )
        for resource in self.UNIVERSE:
            if rng.random() < 0.6:
                database.add_version(
                    resource.resource_type,
                    resource.resource_id,
                    bytes([rng.randrange(1, 4)]) * 8,
                )
        for uid in (1, 2, 3):
            database.set_status(uid, rng.choice((None, 0, 1)))
        database.set_bid(8, rng.choice((1, 2, 3, 77, None)))
        database.set_bid(9, rng.choice((1, 2, 3, 77, None)))
        resources = [r for r in self.UNIVERSE if rng.random() < 0.5] or [
            self.UNIVERSE[2]
        ]
        wanted = [t for t in tokens if rng.random() < 0.4]
        if rng.random() < 0.2:
            wanted.append(str(uuid.UUID(int=rng.getrandbits(128))))
        wanted = [t.upper() if rng.random() < 0.5 else t for t in wanted]
        expected = tuple(
            ExpectedResourceVersion(
                r, ConcurrencyToken(bytes([rng.randrange(1, 4)]) * 8)
            )
            for r in resources
            if rng.random() < 0.4
        )
        request = _DatabaseMutationRequest(
            database_id="d",
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources),
            expected_versions=expected,
            required_lock_tokens=tuple(wanted),
            block_bid_child_locks=rng.random() < 0.5,
            block_bid_active_editors=rng.random() < 0.5,
            bid_lock_exempt=rng.random() < 0.3,
        )
        return database, request, set(resources)

    def _actual(self, database, request, resources):
        class _Cursor:
            row = None

            def execute(self, sql, *params):
                self.row = database.violation(sql, params)

            def fetchone(self):
                return self.row

        try:
            SqlProjectWriter._validate_mutation_locks(
                SimpleNamespace(request=request), _Cursor(), resources
            )
        except _BidLockedRefusal:
            return "bid_locked", None
        except _OptimisticConflict as exc:
            return "rowversion", exc
        except SqlInfrastructureError as exc:
            return "locked", str(exc)
        return None, None

    def test_the_evaluated_statement_agrees_with_the_independent_rules_oracle(self):
        rng = random.Random(2026100203)
        kinds_seen = set()
        for case in range(400):
            database, request, resources = self._state(rng)
            oracle = _LockRulesOracle(database, request, resources)
            expected = oracle.expected()
            kind, detail = self._actual(database, request, resources)
            with self.subTest(case=case):
                if expected is None:
                    self.assertEqual((kind, detail), (None, None))
                    kinds_seen.add(None)
                    continue
                best_kind = expected[0][1]
                kinds_seen.add(best_kind)
                if best_kind == "bid_locked":
                    self.assertEqual(kind, "bid_locked")
                elif best_kind == "rowversion":
                    self.assertEqual(kind, "rowversion")
                    entry = expected[0][2]
                    self.assertEqual(detail.resource, entry[0].resource)
                    self.assertEqual(detail.expected, entry[0].expected)
                    self.assertEqual(
                        detail.actual,
                        None if entry[1] is None else ConcurrencyToken(entry[1]),
                    )
                elif best_kind in self.FIXED:
                    self.assertEqual((kind, detail), ("locked", self.FIXED[best_kind]))
                else:
                    owners = set().union(*(entry[2] for entry in expected))
                    allowed = {self.MESSAGES[best_kind].format(name) for name in owners}
                    self.assertEqual(kind, "locked")
                    self.assertIn(detail, allowed)
        self.assertEqual(
            kinds_seen,
            {
                None,
                "bid_locked",
                "item_owner",
                "bid_owner",
                "child_owner",
                "active_editor",
                "token_expired",
                "token_resource",
                "owned_omitted",
                "rowversion",
            },
        )


class WriterLockValidationTokenIsolationTests(unittest.TestCase):
    ME = WriterLockValidationSemanticsTests.ME
    TOKEN = WriterLockValidationSemanticsTests.TOKEN
    TAKEOFF = WriterLockValidationSemanticsTests.TAKEOFF
    _database = WriterLockValidationSemanticsTests._database
    _run = WriterLockValidationSemanticsTests._run
    _assert_committed = WriterLockValidationSemanticsTests._assert_committed

    def test_another_sessions_unrelated_live_lock_does_not_invalidate_a_valid_token(
        self,
    ):
        database = (
            self._database()
            .add_lock("takeoff", "10", self.ME, self.TOKEN, bid_uid=8)
            .add_lock(
                "takeoff",
                "77",
                "ana-session",
                "11111111-1111-1111-1111-111111111111",
                bid_uid=9,
            )
        )
        result, _request, server, executed = self._run(
            database, [self.TAKEOFF], required_lock_tokens=(self.TOKEN,)
        )
        self._assert_committed(result, server, executed)
