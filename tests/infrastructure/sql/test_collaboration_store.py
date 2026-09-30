from tests.helpers.sql.collaboration import (
    SQL_SCHEMA_V1,
    DatabaseCapabilityService,
    DatabaseDescriptor,
    DatabaseDescriptorRegistry,
    DatabaseSessionRegistry,
    SqlServerDatabaseLocation,
    _CollaborationStore,
    _coordinator,
    _Dispatcher,
    _EventBus,
    _PermissionProbe,
    _Reconciliation,
    _RemoteReader,
    _shutdown_coordinator,
    _token_service,
)
from ost_visualizer.infrastructure.sql.connection_manager import (
    SqlConnectionManager,
    SqlConnectionRequest,
)
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore
from unittest.mock import Mock, patch
import unittest
import threading
import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
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
from ost_visualizer.domain.entities.database_descriptor import (
    DatabaseDescriptor,
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.collaboration_store import (
    SqlCollaborationStore,
    _change_from_row,
)
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlErrorDetails,
    SqlInfrastructureError,
)
from tests.helpers.sql.collaboration import (
    _ReadRequestFactory,
    _RemoteReader,
    _batch,
)


class SqlSessionConnectCancellationTests(unittest.TestCase):
    def test_connection_returning_after_stop_is_closed_without_session_sql(self):
        entered = threading.Event()
        release = threading.Event()
        stop = threading.Event()
        finished = threading.Event()
        raw = Mock()
        request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
        )
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = Mock()
        store._requests.request.return_value = request
        store._connections = SqlConnectionManager(
            drivers=["ODBC Driver 18 for SQL Server"]
        )
        results = []
        errors = []

        def connect(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Connection probe was not released")
            return raw

        def run():
            try:
                results.append(
                    store.start_session(
                        "database",
                        "session",
                        "client",
                        "user",
                        "machine",
                        "version",
                        stop_requested=stop.is_set,
                    )
                )
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        with patch(
            "ost_visualizer.infrastructure.sql.connection_manager.pyodbc.connect",
            side_effect=connect,
        ) as connector:
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                stop.set()
                self.assertFalse(finished.is_set())
                release.set()
                self.assertTrue(finished.wait(2))
            finally:
                release.set()
                worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, [None])
            raw.close.assert_called_once_with()
            raw.cursor.assert_not_called()
            raw.commit.assert_not_called()
            self.assertEqual(
                connector.call_args.kwargs, {"autocommit": False, "timeout": 10}
            )

    def test_stop_before_connect_does_not_open_connection(self):
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = Mock()
        store._connections = Mock()
        self.assertIsNone(
            store.start_session(
                "database",
                "session",
                "client",
                "user",
                "machine",
                "version",
                stop_requested=lambda: True,
            )
        )
        store._connections.connection.assert_not_called()


class CollaborationStoreCollaborationTests(unittest.TestCase):
    def test_session_rejects_multiple_database_metadata_rows(self):
        expected_guid = "00000000-0000-0000-0000-000000000123"
        inserted_sessions = []

        class _Requests:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return SimpleNamespace(
                    location=SqlServerDatabaseLocation(
                        server="localhost",
                        database="TEST",
                        database_guid=expected_guid,
                    )
                )

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *parameters):
                self.last_sql = sql
                if "INSERT INTO [ostv].[Sessions]" in sql:
                    inserted_sessions.append(parameters)
                return self

            def fetchone(self):
                if "DatabaseMetadata" in self.last_sql:
                    if "COUNT_BIG(*)" in self.last_sql:
                        return None
                    return (expected_guid,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (8,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.assertFalse(autocommit)
                yield lease

            def assertFalse(self, value):
                self_test.assertFalse(value)

        self_test = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _Requests()
        store._connections = _Connections()
        with self.assertRaisesRegex(
            SqlInfrastructureError,
            "metadata is missing",
        ) as raised:
            store.start_session(
                "saved-database-id",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "test-user",
                "test-machine",
                "test-version",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(inserted_sessions, [])
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_session_rejects_database_recreated_with_saved_connection_identity(self):
        expected_guid = "00000000-0000-0000-0000-000000000123"
        replacement_guid = "00000000-0000-0000-0000-000000000456"
        inserted_sessions = []
        statements = []

        class _Requests:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return SimpleNamespace(
                    location=SqlServerDatabaseLocation(
                        server="localhost",
                        database="TEST",
                        database_guid=expected_guid,
                    )
                )

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *parameters):
                self.last_sql = sql
                statements.append(sql)
                if "INSERT INTO [ostv].[Sessions]" in sql:
                    inserted_sessions.append(parameters)
                return self

            def fetchone(self):
                if "DatabaseMetadata" in self.last_sql:
                    return (replacement_guid,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (8,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class _Lease:
            def __init__(self):
                self.commits = 0
                self.rollbacks = 0

            def cursor(self):
                return _Cursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.assertFalse(autocommit)
                yield lease

            def assertFalse(self, value):
                self_test.assertFalse(value)

        self_test = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _Requests()
        store._connections = _Connections()
        with self.assertRaisesRegex(
            SqlInfrastructureError,
            "replaced since this connection was saved",
        ) as raised:
            store.start_session(
                "saved-database-id",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "test-user",
                "test-machine",
                "test-version",
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        self.assertEqual(inserted_sessions, [])
        self.assertEqual(len(statements), 1)
        self.assertIn("COUNT_BIG(*)", statements[0])
        self.assertIn("sys.database_recovery_status", statements[0])
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_feed_uses_commit_version_when_earlier_identity_commits_last(self):
        transaction_id = "00000000-0000-0000-0000-000000000012"

        class _Cursor:
            def __init__(self):
                self.statements = []
                self.last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.statements.append(sql)
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch", 1)
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (1,)
                if "CHANGE_TRACKING_CURRENT_VERSION" in self.last_sql:
                    return (12,)
                raise AssertionError(f"Unexpected fetchone query: {self.last_sql}")

            def fetchall(self):
                if "CHANGETABLE" in self.last_sql:
                    return [(12, "I", transaction_id)]
                return [
                    (
                        1,
                        12,
                        transaction_id,
                        "other-session",
                        8,
                        "condition",
                        "42",
                        "update",
                        None,
                        None,
                        None,
                        "ost_visualizer",
                    )
                ]

            def __enter__(self):
                return self

            def __exit__(self, _exc_type, _exc_value, _traceback):
                return False

        class _Connections:
            def __init__(self):
                self.cursor = _Cursor()
                self.commits = 0
                self.rollbacks = 0

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                if autocommit:
                    raise AssertionError("Feed reads require one transaction.")
                owner = self

                class _Lease:
                    def cursor(self):
                        return owner.cursor

                    def commit(self):
                        owner.commits += 1

                    def rollback(self):
                        owner.rollbacks += 1

                yield _Lease()

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        hydration_connections = []

        class _RemoteReader:
            def hydrate_connection(self, batch, connection):
                self_batch = batch
                hydration_connections.append(connection)
                test_case.assertEqual(store._connections.commits, 1)
                return HydratedDatabaseChangeBatch(self_batch)

        test_case = self
        remote_reader = _RemoteReader()
        store._remote_reader = remote_reader
        result = store.poll_changes("database", 11, 10, "local-session")
        batch = result.observed_batch
        statements = " ".join(store._connections.cursor.statements)
        self.assertEqual(
            store._connections.cursor.statements[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(store._connections.commits, 2)
        self.assertEqual(store._connections.rollbacks, 0)
        self.assertIn("CHANGETABLE", statements)
        self.assertNotIn("[Sequence] > ?", statements)
        marker_query = next(
            statement
            for statement in store._connections.cursor.statements
            if "CHANGETABLE" in statement
        )
        self.assertRegex(
            marker_query,
            r"ORDER BY ct\.\[SYS_CHANGE_VERSION\]$",
            "Pagination must include every transaction sharing the checkpoint version.",
        )
        change_query = next(
            statement
            for statement in store._connections.cursor.statements
            if "MarkerVersions" in statement
        )
        self.assertNotIn(
            "READPAST",
            change_query,
            "A committed transaction must never be delivered with locked rows omitted.",
        )
        self.assertEqual(batch.changes[0].sequence, 1)
        self.assertEqual(batch.changes[0].commit_version, 12)
        self.assertEqual(result.remote_batch.batch.changes, batch.changes)
        self.assertEqual(len(hydration_connections), 1)

    def test_snapshot_feed_rolls_back_the_whole_poll_when_payload_is_missing(self):
        transaction_id = "00000000-0000-0000-0000-000000000099"

        class _Cursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch",)
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (1,)
                if "CURRENT_VERSION" in self.last_sql:
                    return (12,)
                raise AssertionError(self.last_sql)

            def fetchall(self):
                if "CHANGETABLE" in self.last_sql:
                    return [(12, "I", transaction_id)]
                return [
                    (
                        None,
                        12,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        cursor = _Cursor()

        class _Lease:
            commits = 0
            rollbacks = 0

            def cursor(self):
                return cursor

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield lease

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        with self.assertRaisesRegex(ValueError, "no ChangeLog records"):
            store.poll_changes("database", 11, 10, "local-session")
        self.assertFalse(store._connections.autocommit)
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 1)

    def test_production_collaboration_store_acquires_resource_locks_in_one_batch(self):
        class _WriteRequestFactory:
            @staticmethod
            def request(_database_id, *, read_only):
                self.assertFalse(read_only)
                return object()

        class _Cursor:
            def __init__(self):
                self.last_sql = ""
                self.parameters = ()

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.parameters = _parameters
                return self

            def fetchall(self):
                self.assert_canonical_lock_batch()
                requested = json.loads(self.parameters[0])
                return [
                    (0, item["ordinal"], None, item["lock_token"]) for item in requested
                ]

            def assert_canonical_lock_batch(self):
                test_case.assertIn("OPENJSON", self.last_sql)
                test_case.assertIn("sp_getapplock", self.last_sql)
                test_case.assertIn("INSERT INTO [ostv].[Locks]", self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

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

            @contextmanager
            def connection(self, _request, *, autocommit=False):
                test_case.assertFalse(autocommit)
                yield self.lease

        test_case = self
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _WriteRequestFactory()
        store._connections = _Connections()
        resources = (
            ResourceRef("takeoffs_collection", "8", 8),
            ResourceRef("takeoff", "19", 19),
        )
        locks = store.acquire_locks(
            "database", "session", resources, "takeoff-placement:test"
        )
        self.assertEqual(len(locks), 2)
        for lock, resource in zip(locks, sorted(resources), strict=True):
            self.assertEqual(lock.database_id, "database")
            self.assertEqual(lock.resource, resource)
            self.assertRegex(
                lock.lock_token,
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            )
        self.assertEqual(store._connections.lease.commits, 1)
        self.assertEqual(store._connections.lease.rollbacks, 0)
        store._connections.lease.cursor_value.assert_canonical_lock_batch()

    def test_snapshot_feed_rolls_back_a_retention_gap(self):
        class _Cursor:
            last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                return self

            def fetchone(self):
                if "ChangeFeedState" in self.last_sql:
                    return ("epoch",)
                if "MIN_VALID_VERSION" in self.last_sql:
                    return (20,)
                if "CURRENT_VERSION" in self.last_sql:
                    return (25,)
                raise AssertionError(self.last_sql)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        cursor = _Cursor()

        class _Lease:
            commits = 0
            rollbacks = 0

            def cursor(self):
                return cursor

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        lease = _Lease()

        class _Connections:
            @contextmanager
            def connection(self, _request, *, autocommit=False):
                self.autocommit = autocommit
                yield lease

        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _ReadRequestFactory()
        store._connections = _Connections()
        batch = store.poll_changes("database", 10, 10, "local-session").observed_batch
        self.assertEqual(batch.minimum_valid_version, 20)
        self.assertEqual(batch.delivered_through_version, 10)
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 1)

    def test_snapshot_feed_rejects_duplicate_resource_payloads(self):
        transaction_id = "00000000-0000-0000-0000-000000000099"

        class _Cursor:
            def execute(self, _sql, *_parameters):
                return self

            def fetchall(self):
                row = (
                    1,
                    12,
                    transaction_id,
                    "other-session",
                    8,
                    "condition",
                    "42",
                    "update",
                    None,
                    None,
                    None,
                    "ost_visualizer",
                )
                return (row, (2, *row[1:]))

        with self.assertRaisesRegex(ValueError, "duplicate resource payloads"):
            SqlCollaborationStore._load_transaction_changes(
                _Cursor(), ((transaction_id, 12),)
            )

    def test_transaction_log_uuid_text_is_canonicalized_before_marker_validation(self):
        transaction_id = "859945fa-fbf8-4b90-bafe-735976033238"
        session_id = "8b2ce0c5-90f8-4580-a5ee-b2f4fdc7581a"

        class _Cursor:
            def execute(self, _sql, *_parameters):
                return self

            @staticmethod
            def fetchall():
                return (
                    (
                        1,
                        12,
                        transaction_id.upper(),
                        session_id.upper(),
                        8,
                        "takeoff",
                        "501",
                        "create",
                        None,
                        None,
                        None,
                        "ost_visualizer",
                    ),
                )

        rows = SqlCollaborationStore._load_transaction_changes(
            _Cursor(), ((transaction_id, 12),)
        )
        change = _change_from_row(rows[0])
        self.assertEqual(change.transaction_id, transaction_id)
        self.assertEqual(change.source_session_id, session_id.upper())
