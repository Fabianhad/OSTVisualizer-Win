from tests.helpers.sql.strict_sql_fakes import StrictLeaseProxy, strict_manager
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
from ost_visualizer.infrastructure.sql.database_metadata_contract import (
    DATABASE_METADATA_CURRENT_DATABASE_PREDICATE,
)
from ost_visualizer.infrastructure.sql.descriptor_connection import (
    SqlDescriptorConnectionFactory,
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


class _StoreCursor:
    def __init__(self, fetchone=None, fetchall=None):
        self.executions = []
        self.last_sql = ""
        self._fetchone = fetchone or (lambda _sql: None)
        self._fetchall = fetchall or (lambda _sql: [])

    def execute(self, sql, *parameters):
        self.last_sql = sql
        self.executions.append((sql, parameters))
        return self

    def fetchone(self):
        return self._fetchone(self.last_sql)

    def fetchall(self):
        return self._fetchall(self.last_sql)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _StoreLease:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _StoreConnections:
    def __init__(self, lease):
        self.lease = lease
        self.autocommits = []

    @contextmanager
    def connection(self, _request, *, autocommit=False):
        self.autocommits.append(autocommit)
        yield self.lease


class _StoreRequests:
    def __init__(self, request):
        self._request = request
        self.calls = []

    def request(self, database_id, *, read_only):
        self.calls.append((database_id, read_only))
        return self._request


class _RecordingRemoteReader:
    def __init__(self, lease):
        self._lease = lease
        self.hydrated = []

    def hydrate_connection(self, batch, connection):
        self.hydrated.append((batch, connection, self._lease.commits))
        return HydratedDatabaseChangeBatch(batch)


def _store_with(cursor, request=None, remote_reader=None):
    lease = _StoreLease(cursor)
    store = SqlCollaborationStore.__new__(SqlCollaborationStore)
    store._requests = _StoreRequests(request)
    store._connections = strict_manager(_StoreConnections(lease))
    if remote_reader is not None:
        store._remote_reader = remote_reader(lease)
    return store, lease


def _feed_fetchone(epoch=("epoch",), minimum=(1,), high_water=(12,)):
    def handler(sql):
        if "ChangeFeedState" in sql:
            return epoch
        if "MIN_VALID_VERSION" in sql:
            return minimum
        if "CHANGE_TRACKING_CURRENT_VERSION" in sql:
            return high_water
        raise AssertionError(sql)

    return handler


def _feed_fetchall(markers=(), log_rows=()):
    def handler(sql):
        if "CHANGETABLE" in sql:
            return list(markers)
        return list(log_rows)

    return handler


def _log_row(sequence, version, transaction_id, session_id, resource_id):
    return (
        sequence,
        version,
        transaction_id,
        session_id,
        8,
        "condition",
        resource_id,
        "update",
        None,
        None,
        None,
        "ost_visualizer",
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
        store._requests = Mock(spec=SqlDescriptorConnectionFactory)
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
            store._requests.request.assert_called_once_with("database", read_only=False)
            raw.close.assert_called_once_with()
            raw.cursor.assert_not_called()
            raw.commit.assert_not_called()
            self.assertEqual(
                connector.call_args.kwargs, {"autocommit": False, "timeout": 10}
            )

    def test_stop_before_connect_does_not_open_connection(self):
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = Mock(spec=SqlDescriptorConnectionFactory)
        store._connections = Mock(spec=SqlConnectionManager)
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
        store._connections = strict_manager(_Connections())
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
        self.assertEqual(len(statements), 1)
        self.assertIn(DATABASE_METADATA_CURRENT_DATABASE_PREDICATE, statements[0])
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
        store._connections = strict_manager(_Connections())
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
        self.assertIn(DATABASE_METADATA_CURRENT_DATABASE_PREDICATE, statements[0])
        self.assertIn("COUNT_BIG(*)", statements[0])
        self.assertIn("sys.database_recovery_status", statements[0])
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_feed_uses_commit_version_when_earlier_identity_commits_last(self):
        transaction_id = "00000000-0000-0000-0000-000000000012"

        class _Cursor:
            def __init__(self):
                self.statements = []
                self.parameters = {}
                self.last_sql = ""

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.statements.append(sql)
                self.parameters[sql] = _parameters
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
        store._connections = strict_manager(_Connections())
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
        self.assertEqual(store._connections.cursor.parameters[marker_query], (11, 12))
        self.assertEqual(
            store._connections.cursor.parameters[change_query], (transaction_id, 12)
        )
        self.assertEqual(batch.database_id, "database")
        self.assertEqual(batch.feed_epoch, "epoch")
        self.assertEqual(batch.minimum_valid_version, 1)
        self.assertEqual(batch.high_water_version, 12)
        self.assertEqual(batch.delivered_through_version, 12)
        self.assertEqual(len(batch.changes), 1)
        self.assertEqual(batch.changes[0].sequence, 1)
        self.assertEqual(batch.changes[0].commit_version, 12)
        self.assertEqual(batch.changes[0].transaction_id, transaction_id)
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
        store._connections = strict_manager(_Connections())
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
                self.executions = []

            def execute(self, sql, *_parameters):
                self.last_sql = sql
                self.parameters = _parameters
                self.executions.append((sql, _parameters))
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
        store._connections = strict_manager(_Connections())
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
        executions = store._connections.lease.cursor_value.executions
        self.assertEqual(len(executions), 1)
        sql, parameters = executions[0]
        self.assertEqual(sql.count("?"), len(parameters))
        payload = json.loads(parameters[0])
        self.assertEqual(
            [
                (item["ordinal"], item["resource_type"], item["resource_id"])
                for item in payload
            ],
            [(0, "takeoff", "19"), (1, "takeoffs_collection", "8")],
        )
        self.assertEqual([item["bid_uid"] for item in payload], [19, 8])
        self.assertEqual(parameters[1:], ("session",) * 5 + ("takeoff-placement:test",))
        self.assertEqual(
            [lock.lock_token for lock in locks],
            [item["lock_token"] for item in payload],
        )
        self.assertEqual(len({item["lock_token"] for item in payload}), 2)

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
        store._connections = strict_manager(_Connections())
        result = store.poll_changes("database", 10, 10, "local-session")
        batch = result.observed_batch
        self.assertEqual(batch.minimum_valid_version, 20)
        self.assertEqual(batch.high_water_version, 25)
        self.assertEqual(batch.delivered_through_version, 10)
        self.assertEqual(batch.changes, ())
        self.assertEqual(result.remote_batch.batch, batch)
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
        self.assertTrue(session_identities_equal(change.source_session_id, session_id))
        self.assertEqual(change.resource, ResourceRef("takeoff", "501", 8))
        self.assertEqual(change.operation, ChangeOperation.CREATE)

    def test_transaction_changes_allow_one_resource_in_distinct_transactions(self):
        first_transaction = "859945fa-fbf8-4b90-bafe-735976033238"
        second_transaction = "0e2b1ff2-7e6d-4d5c-9f4c-1c0d8f4a9b11"
        session_id = "8b2ce0c5-90f8-4580-a5ee-b2f4fdc7581a"
        cursor = _StoreCursor(
            fetchall=lambda _sql: [
                _log_row(1, 12, first_transaction, session_id, "42"),
                _log_row(2, 13, second_transaction, session_id, "42"),
            ]
        )
        rows = SqlCollaborationStore._load_transaction_changes(
            cursor, ((first_transaction, 12), (second_transaction, 13))
        )
        self.assertEqual([row[0] for row in rows], [1, 2])
        sql, parameters = cursor.executions[0]
        self.assertEqual(sql.count("?"), len(parameters))
        self.assertEqual(
            parameters,
            (first_transaction, 12, second_transaction, 13),
        )

    def test_transaction_changes_without_markers_do_not_query(self):
        cursor = _StoreCursor()
        rows = SqlCollaborationStore._load_transaction_changes(cursor, ())
        self.assertEqual(rows, ())
        self.assertEqual(cursor.executions, [])

    def test_session_start_registers_canonical_guid_after_cleanup_and_commits(self):
        expected_guid = "859945fa-fbf8-4b90-bafe-735976033238"
        cursor = _StoreCursor(
            fetchone=lambda sql: (
                (expected_guid.upper(),)
                if "DatabaseMetadata" in sql
                else (8,) if "CHANGE_TRACKING_CURRENT_VERSION" in sql else None
            )
        )
        request = SimpleNamespace(
            location=SqlServerDatabaseLocation(
                server="localhost", database="TEST", database_guid=expected_guid
            )
        )
        store, lease = _store_with(cursor, request)
        session_id = str(uuid.uuid4())
        client_id = str(uuid.uuid4())
        session = store.start_session(
            "saved-database-id",
            session_id,
            client_id,
            "test-user",
            "test-machine",
            "test-version",
        )
        self.assertEqual(
            session,
            DatabaseSession(
                database_id="saved-database-id",
                session_id=session_id,
                last_acknowledged_version=8,
            ),
        )
        self.assertEqual(store._requests.calls, [("saved-database-id", False)])
        self.assertEqual(store._connections.autocommits, [False])
        statements = [sql for sql, _parameters in cursor.executions]
        self.assertEqual(len(statements), 4)
        self.assertIn("DatabaseMetadata", statements[0])
        self.assertIn("[CloseReason]=N'expired'", statements[1])
        self.assertIn("CHANGE_TRACKING_CURRENT_VERSION", statements[2])
        self.assertIn("INSERT INTO [ostv].[Sessions]", statements[3])
        self.assertEqual(
            cursor.executions[3][1],
            (
                session_id,
                expected_guid,
                client_id,
                "test-user",
                "test-machine",
                "test-version",
                8,
            ),
        )
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 0)

    def test_session_rejects_saved_connection_without_valid_database_identity(self):
        cursor = _StoreCursor(
            fetchone=lambda _sql: ("00000000-0000-0000-0000-000000000123",)
        )
        request = SimpleNamespace(
            location=SqlServerDatabaseLocation(
                server="localhost", database="TEST", database_guid=""
            )
        )
        store, lease = _store_with(cursor, request)
        with self.assertRaisesRegex(
            SqlInfrastructureError, "no valid database identity"
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
        self.assertEqual(len(cursor.executions), 1)
        self.assertEqual(lease.commits, 0)
        self.assertEqual(lease.rollbacks, 1)

    def test_lock_acquisition_failures_roll_back_and_name_the_blocking_session(self):
        resources = (
            ResourceRef("takeoffs_collection", "8", 8),
            ResourceRef("takeoff", "19", 19),
        )
        cases = (
            (
                [(-1, -1, None, None)],
                SqlErrorCode.LOCKED,
                "Another session is changing the same SQL resource.",
            ),
            (
                [(-2, -1, None, None)],
                SqlErrorCode.SESSION_EXPIRED,
                "The SQL collaboration session expired. Reconnect before editing.",
            ),
            (
                [(-3, 1, "Alice", None)],
                SqlErrorCode.LOCKED,
                "takeoffs_collection 8 is being edited by Alice.",
            ),
        )
        for rows, code, message in cases:
            with self.subTest(status=rows[0][0]):
                cursor = _StoreCursor(fetchall=lambda _sql, rows=rows: rows)
                store, lease = _store_with(cursor)
                with self.assertRaises(SqlInfrastructureError) as raised:
                    store.acquire_locks("database", "session", resources, "edit")
                self.assertEqual(raised.exception.details.code, code)
                self.assertEqual(raised.exception.details.user_message, message)
                self.assertEqual(lease.commits, 0)
                self.assertEqual(lease.rollbacks, 1)

    def test_lock_acquisition_rejects_empty_and_incomplete_results(self):
        resources = (ResourceRef("takeoff", "19", 19), ResourceRef("takeoff", "20", 19))
        token = str(uuid.uuid4())
        cases = (
            ([], "returned no result"),
            ([(0, 0, None, token)], "incomplete result"),
            ([(0, 0, None, token), (0, 2, None, token)], "incomplete result"),
            ([(0, 0, None, token), (1, 1, None, token)], "incomplete result"),
        )
        for rows, message in cases:
            with self.subTest(rows=rows):
                cursor = _StoreCursor(fetchall=lambda _sql, rows=rows: rows)
                store, lease = _store_with(cursor)
                with self.assertRaisesRegex(RuntimeError, message):
                    store.acquire_locks("database", "session", resources, "edit")
                self.assertEqual(lease.commits, 0)
                self.assertEqual(lease.rollbacks, 1)

    def test_lock_acquisition_deduplicates_resources_and_bounds_description(self):
        resource = ResourceRef("takeoff", "19", 19)
        token = str(uuid.uuid4())
        cursor = _StoreCursor(fetchall=lambda _sql: [(0, 0, None, token)])
        store, lease = _store_with(cursor)
        locks = store.acquire_locks(
            "database", "session", (resource, resource), "x" * 300
        )
        self.assertEqual(
            locks,
            (
                ResourceLock(
                    database_id="database", resource=resource, lock_token=token
                ),
            ),
        )
        _sql, parameters = cursor.executions[0]
        self.assertEqual(len(json.loads(parameters[0])), 1)
        self.assertEqual(parameters[-1], "x" * 256)
        self.assertEqual(lease.commits, 1)

    def test_lock_acquisition_without_resources_does_not_connect(self):
        cursor = _StoreCursor()
        store, lease = _store_with(cursor)
        self.assertEqual(store.acquire_locks("database", "session", (), "edit"), ())
        self.assertEqual(store._requests.calls, [])
        self.assertEqual(store._connections.autocommits, [])
        self.assertEqual(cursor.executions, [])

    def test_snapshot_feed_rolls_back_a_checkpoint_ahead_of_the_high_water_version(
        self,
    ):
        cursor = _StoreCursor(fetchone=_feed_fetchone(minimum=(20,), high_water=(25,)))
        store, lease = _store_with(cursor, object(), _RecordingRemoteReader)
        result = store.poll_changes("database", 30, 10, "local-session")
        batch = result.observed_batch
        self.assertEqual(batch.delivered_through_version, 30)
        self.assertEqual(batch.high_water_version, 25)
        self.assertEqual(batch.changes, ())
        self.assertEqual(result.remote_batch.batch, batch)
        self.assertFalse(
            any("CHANGETABLE" in sql for sql, _parameters in cursor.executions)
        )
        self.assertEqual(store._remote_reader.hydrated, [])
        self.assertEqual(lease.commits, 1)
        self.assertEqual(lease.rollbacks, 1)

    def test_snapshot_feed_zero_checkpoint_is_read_only_while_history_from_zero_is_retained(
        self,
    ):
        # Decision D3 (supersedes "checkpoint 0 is never a gap"): 0 is a real
        # checkpoint. With the history retained from version 0 it reads the
        # markers; with a higher minimum valid version CHANGETABLE is never asked
        # (SQL Server would reject the last_sync_version) and the poll rolls back
        # as a retention gap.
        cursor = _StoreCursor(
            fetchone=_feed_fetchone(minimum=(0,), high_water=(25,)),
            fetchall=_feed_fetchall(),
        )
        store, lease = _store_with(cursor, object(), _RecordingRemoteReader)
        result = store.poll_changes("database", 0, 10, "local-session")
        batch = result.observed_batch
        marker_executions = [
            parameters for sql, parameters in cursor.executions if "CHANGETABLE" in sql
        ]
        self.assertEqual(marker_executions, [(0, 25)])
        self.assertEqual(batch.delivered_through_version, 25)
        self.assertEqual(len(store._remote_reader.hydrated), 1)
        self.assertEqual(store._remote_reader.hydrated[0][2], 1)
        self.assertEqual(lease.commits, 2)
        self.assertEqual(lease.rollbacks, 0)
        gap_cursor = _StoreCursor(
            fetchone=_feed_fetchone(minimum=(20,), high_water=(25,)),
            fetchall=_feed_fetchall(),
        )
        gap_store, gap_lease = _store_with(gap_cursor, object(), _RecordingRemoteReader)
        gap = gap_store.poll_changes("database", 0, 10, "local-session").observed_batch
        self.assertFalse(
            any("CHANGETABLE" in sql for sql, _parameters in gap_cursor.executions)
        )
        self.assertEqual((gap.minimum_valid_version, gap.high_water_version), (20, 25))
        self.assertEqual(gap.delivered_through_version, 0)
        self.assertEqual(gap.changes, ())
        self.assertEqual(gap_store._remote_reader.hydrated, [])
        self.assertEqual((gap_lease.commits, gap_lease.rollbacks), (1, 1))

    def test_snapshot_feed_page_ends_at_last_marker_version_and_limit_is_bounded(self):
        first_transaction = "00000000-0000-0000-0000-000000000011"
        second_transaction = "00000000-0000-0000-0000-000000000012"
        session_id = "8b2ce0c5-90f8-4580-a5ee-b2f4fdc7581a"
        cursor = _StoreCursor(
            fetchone=_feed_fetchone(high_water=(20,)),
            fetchall=_feed_fetchall(
                markers=[(12, "I", first_transaction), (13, "I", second_transaction)],
                log_rows=[
                    _log_row(1, 12, first_transaction, session_id, "1"),
                    _log_row(2, 13, second_transaction, session_id, "2"),
                ],
            ),
        )
        store, lease = _store_with(cursor, object(), _RecordingRemoteReader)
        batch = store.poll_changes("database", 11, 2, "local-session").observed_batch
        self.assertEqual(batch.delivered_through_version, 13)
        self.assertEqual(batch.high_water_version, 20)
        self.assertEqual([change.commit_version for change in batch.changes], [12, 13])
        self.assertIn(
            "SELECT TOP (2) WITH TIES",
            next(sql for sql, _p in cursor.executions if "CHANGETABLE" in sql),
        )
        for requested, expected in ((0, 1), (-5, 1), (10_000, 500)):
            with self.subTest(requested=requested):
                bounded = _StoreCursor(
                    fetchone=_feed_fetchone(), fetchall=_feed_fetchall()
                )
                bounded_store, _lease = _store_with(
                    bounded, object(), _RecordingRemoteReader
                )
                bounded_store.poll_changes("database", 11, requested, "local")
                self.assertIn(
                    f"SELECT TOP ({expected}) WITH TIES",
                    next(sql for sql, _p in bounded.executions if "CHANGETABLE" in sql),
                )

    def test_snapshot_feed_hides_own_session_changes_from_remote_batch_only(self):
        transaction_id = "00000000-0000-0000-0000-000000000011"
        local_session = "8b2ce0c5-90f8-4580-a5ee-b2f4fdc7581a"
        other_session = "1f0c9e4a-0f6d-4a64-8c3a-5f8b3f1d2a77"
        cursor = _StoreCursor(
            fetchone=_feed_fetchone(),
            fetchall=_feed_fetchall(
                markers=[(12, "I", transaction_id)],
                log_rows=[
                    _log_row(1, 12, transaction_id, local_session.upper(), "1"),
                    _log_row(2, 12, transaction_id, other_session.upper(), "2"),
                ],
            ),
        )
        store, lease = _store_with(cursor, object(), _RecordingRemoteReader)
        result = store.poll_changes("database", 11, 10, local_session)
        self.assertEqual(
            [change.resource.resource_id for change in result.observed_batch.changes],
            ["1", "2"],
        )
        self.assertEqual(
            [
                change.resource.resource_id
                for change in result.remote_batch.batch.changes
            ],
            ["2"],
        )
        self.assertEqual(
            result.remote_batch.batch.delivered_through_version,
            result.observed_batch.delivered_through_version,
        )
        self.assertEqual(lease.commits, 2)

    def test_snapshot_feed_rejects_missing_metadata_and_invalid_markers(self):
        transaction_id = "00000000-0000-0000-0000-000000000011"
        cases = (
            (
                {"epoch": None},
                _feed_fetchall(),
                SqlInfrastructureError,
                "change-feed metadata is missing",
            ),
            (
                {"minimum": (None,)},
                _feed_fetchall(),
                ValueError,
                "Change Tracking metadata is unavailable",
            ),
            (
                {"high_water": None},
                _feed_fetchall(),
                ValueError,
                "Change Tracking metadata is unavailable",
            ),
            (
                {},
                _feed_fetchall(markers=[(12, "U", transaction_id)]),
                ValueError,
                "invalid change",
            ),
            (
                {},
                _feed_fetchall(
                    markers=[
                        (12, "I", transaction_id),
                        (13, "I", transaction_id.upper()),
                    ]
                ),
                ValueError,
                "duplicate transaction identity",
            ),
        )
        for fetchone_arguments, fetchall, error_type, message in cases:
            with self.subTest(message=message, arguments=fetchone_arguments):
                cursor = _StoreCursor(
                    fetchone=_feed_fetchone(**fetchone_arguments), fetchall=fetchall
                )
                store, lease = _store_with(cursor, object(), _RecordingRemoteReader)
                with self.assertRaisesRegex(error_type, message):
                    store.poll_changes("database", 11, 10, "local-session")
                self.assertEqual(store._remote_reader.hydrated, [])
                self.assertEqual(lease.commits, 1)
                self.assertEqual(lease.rollbacks, 1)


import pyodbc  # noqa: E402
from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    MAX_PARAMETERS,
    Reply,
    StrictSqlServer,
    applock_rules,
    snapshot_transaction_rules,
    sql_server_error,
)

_STRICT_GUID = "859945fa-fbf8-4b90-bafe-735976033238"


class _StrictStoreFixture:
    """Real SqlCollaborationStore + real connection manager over the strict model."""

    def __init__(self, *, high_water=12, minimum=1, markers=(), log_rows=()):
        self.high_water = high_water
        self.minimum = minimum
        self.markers = list(markers)
        self.log_rows = list(log_rows)
        self.hydrated = []
        self.server = StrictSqlServer()
        server = self.server
        snapshot_transaction_rules(server)
        applock_rules(server)
        server.on("SELECT m.[DatabaseGuid]", Reply.rows((_STRICT_GUID,)))
        server.on(
            lambda sql: sql.startswith("UPDATE [ostv].[Sessions] SET [DisconnectedAt]"),
            Reply(),
        )
        server.on(
            "SELECT CHANGE_TRACKING_CURRENT_VERSION()",
            lambda _call: Reply.rows((self.high_water,)),
        )
        server.on("INSERT INTO [ostv].[Sessions]", Reply.dml(1))
        server.on(
            "SELECT CONVERT(nvarchar(36), f.[FeedEpoch])", Reply.rows(("epoch-1",))
        )
        server.on(
            "CHANGE_TRACKING_MIN_VALID_VERSION",
            lambda _call: Reply.rows((self.minimum,)),
        )
        server.on("FROM CHANGETABLE(", lambda _call: Reply.rows(*self.markers))
        server.change_tracking_minimum = lambda: self.minimum
        server.on("WITH MarkerVersions", lambda _call: Reply.rows(*self.log_rows))
        self.store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        location = SqlServerDatabaseLocation(
            server="localhost", database="TEST", database_guid=_STRICT_GUID
        )
        self.store._requests = _StoreRequests(SqlConnectionRequest(location))
        self.store._connections = server.manager()
        fixture = self

        class _Remote:
            def hydrate_connection(self, batch, connection):
                raw = connection._connection
                fixture.hydrated.append((batch, raw.commits))
                return HydratedDatabaseChangeBatch(batch)

        self.store._remote_reader = _Remote()

    def run(self, call):
        with self.server.patched():
            return call(self.store)

    @property
    def raw(self):
        return self.server.connections[-1]


class StoreStrictSessionTests(unittest.TestCase):
    def _start(self, fixture, **kwargs):
        return fixture.run(
            lambda store: store.start_session(
                "db",
                str(uuid.uuid4()),
                str(uuid.uuid4()),
                "user",
                "host",
                "1.0",
                **kwargs,
            )
        )

    def test_start_session_is_one_committed_transaction_with_every_cursor_closed(self):
        fixture = _StrictStoreFixture(high_water=8)
        session = self._start(fixture)
        self.assertEqual(session.last_acknowledged_version, 8)
        raw = fixture.raw
        self.assertFalse(fixture.server.connect_calls[0]["autocommit"])
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        self.assertEqual(
            fixture.server.event_kinds(1),
            ["cursor_open"] + ["execute"] * 4 + ["cursor_close", "commit", "close"],
        )
        fixture.server.assert_everything_closed()

    def test_stop_after_connect_opens_no_cursor_and_closes_the_connection(self):
        fixture = _StrictStoreFixture()
        result = self._start(fixture, stop_requested=lambda: True)
        self.assertIsNone(result)
        self.assertEqual(fixture.server.connections, [])
        # stop only after the physical connection was made
        calls = []

        def stop_after_connect():
            calls.append(1)
            return len(calls) > 1

        result = self._start(fixture, stop_requested=stop_after_connect)
        self.assertIsNone(result)
        self.assertEqual(fixture.server.statements(), [])
        self.assertEqual(fixture.server.event_kinds(1), ["close"])
        fixture.server.assert_everything_closed()

    def test_duplicate_session_error_rolls_back_and_is_a_constraint_failure(self):
        fixture = _StrictStoreFixture()

        def duplicate(_call):
            raise sql_server_error(
                "23000", "Violation of PRIMARY KEY constraint 'PK_ostv_Sessions'", 2627
            )

        fixture.server.rules.insert(
            0, (lambda sql: "INSERT INTO [ostv].[Sessions]" in sql, duplicate)
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            self._start(fixture)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONSTRAINT_FAILED)
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        fixture.server.assert_everything_closed()

    def test_commit_failure_after_session_insert_rolls_back_and_never_reports_a_session(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.fail(
            "commit", sql_server_error("08S01", "Communication link failure")
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            self._start(fixture)
        self.assertEqual(raised.exception.details.code, SqlErrorCode.CONNECTION_FAILED)
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
        fixture.server.assert_everything_closed()

    def test_heartbeat_updates_presence_in_one_transaction_and_returns_server_checkpoint(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "OUTPUT INSERTED.[LastAcknowledgedVersion]", Reply.rows((17,))
        )
        fixture.server.on("MERGE [ostv].[Presence]", Reply.dml(1))
        session = fixture.run(
            lambda store: store.heartbeat(
                "db", "session-1", 15, 8, 20, PresenceMode.EDITING
            )
        )
        # the server keeps the greater checkpoint; the client never lowers it
        self.assertEqual(session.last_acknowledged_version, 17)
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        executed = fixture.server.statements(1)
        self.assertEqual(len(executed), 3)
        self.assertIn("[CloseReason]", executed[0])
        self.assertIn("MERGE [ostv].[Presence]", executed[2])
        # the first statement is not preceded by SET NOCOUNT: a fresh connection
        self.assertFalse(raw.nocount)
        fixture.server.assert_everything_closed()

    def test_expired_session_heartbeat_is_a_session_error_and_never_writes_presence(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.on("OUTPUT INSERTED.[LastAcknowledgedVersion]", Reply.rows())
        fixture.server.on("MERGE [ostv].[Presence]", Reply.dml(1))
        with self.assertRaises(SqlInfrastructureError) as raised:
            fixture.run(
                lambda store: store.heartbeat(
                    "db", "session-1", 15, None, None, PresenceMode.VIEWING
                )
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SESSION_EXPIRED)
        self.assertFalse(any("MERGE" in sql for sql in fixture.server.statements()))
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        fixture.server.assert_everything_closed()

    def test_close_session_truncates_reason_and_commits_once(self):
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "DELETE FROM [ostv].[Locks] WHERE [OwnerSessionId]=?", Reply.dml(1)
        )
        fixture.run(lambda store: store.close_session("db", "session-1", "r" * 100))
        executed = fixture.raw.cursors[0].executed
        self.assertEqual(len(executed), 1)
        self.assertEqual(
            executed[0][1], ("session-1", "session-1", "r" * 64, "session-1")
        )
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
        fixture.server.assert_everything_closed()

    def test_close_session_failure_rolls_back_and_releases_the_connection(self):
        fixture = _StrictStoreFixture()

        def fail(_call):
            raise sql_server_error("08S01", "Communication link failure")

        fixture.server.on("DELETE FROM [ostv].[Locks] WHERE [OwnerSessionId]=?", fail)
        with self.assertRaises(SqlInfrastructureError):
            fixture.run(lambda store: store.close_session("db", "session-1", "bye"))
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        fixture.server.assert_everything_closed()


class StoreStrictReadTests(unittest.TestCase):
    def test_presence_and_lock_listing_use_autocommit_reads(self):
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s",
            Reply.rows(("S1", "Ana", "1.0", 8, None, "editing")),
        )
        fixture.server.on(
            "FROM [ostv].[Locks] l WHERE",
            Reply.rows(("takeoff", "10", 8, "TOKEN")),
        )
        presence = fixture.run(lambda store: store.list_presence("db", 8, "me"))
        locks = fixture.run(lambda store: store.list_locks("db", "me", 8))
        self.assertEqual(
            [(p.session_id, p.display_name, p.page_uid, p.mode) for p in presence],
            [("S1", "Ana", None, PresenceMode.EDITING)],
        )
        self.assertEqual(
            [(l.resource, l.lock_token) for l in locks],
            [(ResourceRef("takeoff", "10", 8), "TOKEN")],
        )
        self.assertEqual(
            [call["autocommit"] for call in fixture.server.connect_calls], [True, True]
        )
        fixture.server.assert_everything_closed()

    def test_release_lock_reports_whether_exactly_one_lock_row_was_deleted(self):
        for affected, expected in ((1, True), (0, False)):
            with self.subTest(affected=affected):
                fixture = _StrictStoreFixture()
                fixture.server.on(
                    "DELETE FROM [ostv].[Locks] WHERE [LockToken]=?",
                    Reply.dml(affected),
                )
                released = fixture.run(
                    lambda store: store.release_lock("db", "session-1", "token")
                )
                self.assertIs(released, expected)
                raw = fixture.raw
                self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                fixture.server.assert_everything_closed()

    def test_renew_lock_requires_a_live_session_and_a_live_unexpired_lock(self):
        for label, session_rows, renew_rows in (
            ("renewed", [(1,)], [("takeoff", "10", 8)]),
            ("session expired", [], [("takeoff", "10", 8)]),
            ("lock expired", [(1,)], []),
        ):
            with self.subTest(label=label):
                fixture = _StrictStoreFixture()
                fixture.server.on(
                    "SELECT 1 FROM [ostv].[Sessions]", Reply.rows(*session_rows)
                )
                fixture.server.on(
                    "UPDATE l SET [LastRenewedAt]", Reply.rows(*renew_rows)
                )
                if label == "renewed":
                    lock = fixture.run(
                        lambda store: store.renew_lock("db", "session-1", "token")
                    )
                    self.assertEqual(lock.resource, ResourceRef("takeoff", "10", 8))
                    self.assertEqual(lock.lock_token, "token")
                    raw = fixture.raw
                    self.assertEqual((raw.commits, raw.rollbacks), (1, 0))
                else:
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        fixture.run(
                            lambda store: store.renew_lock("db", "session-1", "token")
                        )
                    self.assertEqual(
                        raised.exception.details.code, SqlErrorCode.SESSION_EXPIRED
                    )
                    raw = fixture.raw
                    self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
                fixture.server.assert_everything_closed()

    def test_edit_lock_batch_is_sorted_conflicts_release_and_never_deadlock_prone(self):
        # A responder for the single acquire batch that takes the transaction
        # application locks in payload order (as the real batch loop does).
        def acquire_batch(call):
            results = []
            for item in call.json(0):
                resource = f"OSTV:{item['resource_type']}:{item['resource_id']}"
                code = call.server.applocks.acquire(
                    call.connection, resource, "Exclusive"
                )
                results.append((code, item))
                if code < 0:
                    return Reply.rows((-1, -1, None, None))
            return Reply.rows(
                *(
                    (0, item["ordinal"], None, item["lock_token"])
                    for _c, item in results
                )
            )

        resources_a = (
            ResourceRef("takeoff", "20", 8),
            ResourceRef("bid", "8", 8),
            ResourceRef("takeoff", "10", 8),
        )
        resources_b = tuple(reversed(resources_a))
        fixture = _StrictStoreFixture()
        fixture.server.on("DECLARE @Requested TABLE", acquire_batch)
        first = fixture.run(
            lambda store: store.acquire_locks("db", "session-A", resources_a, "edit")
        )
        second = fixture.run(
            lambda store: store.acquire_locks("db", "session-B", resources_b, "edit")
        )
        # both callers acquire in the same sorted order, whatever order they pass
        self.assertEqual(
            [lock.resource for lock in first], [lock.resource for lock in second]
        )
        self.assertEqual([lock.resource for lock in first], sorted(resources_a))
        # the first transaction committed, so its application locks are released
        self.assertEqual(fixture.server.applocks.holders("OSTV:takeoff:10"), [])
        # a concurrent holder makes the whole batch fail and nothing stays held
        holder = fixture.server.connect("x", autocommit=False)
        fixture.server.applocks.acquire(holder, "OSTV:takeoff:20", "Exclusive")
        with self.assertRaises(SqlInfrastructureError) as raised:
            fixture.run(
                lambda store: store.acquire_locks(
                    "db", "session-C", resources_a, "edit"
                )
            )
        self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
        failed = fixture.server.connections[3]
        self.assertEqual((failed.commits, failed.rollbacks), (0, 1))
        self.assertEqual(fixture.server.applocks.holders("OSTV:bid:8"), [])
        self.assertEqual(
            fixture.server.applocks.holders("OSTV:takeoff:20"), [holder.number]
        )


class StoreStrictOperationTests(unittest.TestCase):
    OPERATION = "859945fa-fbf8-4b90-bafe-735976033238"

    def test_query_operation_holds_the_operation_lock_then_always_rolls_back(self):
        for label, row in (
            ("found", ("project_write", "a" * 64, 1, '{"value":1}')),
            ("not found", None),
        ):
            with self.subTest(label=label):
                fixture = _StrictStoreFixture()
                fixture.server.on(
                    "FROM [ostv].[ChangeTransactions] WHERE [TransactionId]=?",
                    Reply.rows(*([row] if row else [])),
                )
                result = fixture.run(
                    lambda store: store.query_operation("db", self.OPERATION.upper())
                )
                self.assertEqual(result.found, row is not None)
                self.assertEqual(result.operation_id, self.OPERATION)
                raw = fixture.raw
                # a read-only recovery query never commits; ending the transaction
                # releases the transaction-owned operation lock
                self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
                self.assertFalse(fixture.server.connect_calls[0]["autocommit"])
                self.assertEqual(
                    fixture.server.applocks.holders(f"OSTV:operation:{self.OPERATION}"),
                    [],
                )
                fixture.server.assert_everything_closed()

    def test_query_operation_waits_out_a_writer_that_still_owns_the_operation_lock(
        self,
    ):
        fixture = _StrictStoreFixture()
        holder = fixture.server.connect("writer", autocommit=False)
        fixture.server.applocks.acquire(
            holder, f"OSTV:operation:{self.OPERATION}", "Exclusive"
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            fixture.run(lambda store: store.query_operation("db", self.OPERATION))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
        raw = fixture.server.connections[1]
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))
        self.assertFalse(
            any("ChangeTransactions" in sql for sql in fixture.server.statements(2))
        )

    def test_a_blocked_marker_lookup_tells_the_user_to_reconnect(self):
        # G2 (user decision): the message the user sees when the old writer still
        # holds the operation lock says to reconnect; class and flags unchanged.
        fixture = _StrictStoreFixture()
        holder = fixture.server.connect("writer", autocommit=False)
        fixture.server.applocks.acquire(
            holder, f"OSTV:operation:{self.OPERATION}", "Exclusive"
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            fixture.run(lambda store: store.query_operation("db", self.OPERATION))
        error = raised.exception
        self.assertEqual(
            str(error),
            "Another session is resolving the same SQL operation. Reconnect to the database to finish resolving it.",
        )
        self.assertEqual(error.details.code, SqlErrorCode.LOCKED)
        self.assertEqual(
            (
                error.retryable,
                error.credential_required,
                error.read_only_required,
                error.session_expired,
            ),
            (False, False, False, False),
        )

    def test_operation_id_must_be_a_uuid_before_any_connection(self):
        fixture = _StrictStoreFixture()
        with self.assertRaises(ValueError):
            fixture.run(lambda store: store.query_operation("db", "not-a-uuid"))
        with self.assertRaises(ValueError):
            fixture.run(lambda store: store.hydrate_operation("db", "not-a-uuid"))
        self.assertEqual(fixture.server.connections, [])

    def _snapshot_row(self, *, marker=True, with_log=True):
        log = (
            (
                1,
                12,
                self.OPERATION,
                _STRICT_GUID,
                8,
                "takeoff",
                "5",
                "create",
                (1).to_bytes(8, "big"),
                None,
                None,
                "ost_visualizer",
            )
            if with_log
            else None
        )
        return (
            12,
            "epoch-1",
            self.OPERATION if marker else None,
            *(log if log else (None,) * 12),
        )

    def test_hydrate_operation_reads_marker_and_payload_in_one_snapshot_then_hydrates(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "DECLARE @CommitVersion bigint=", Reply.rows(self._snapshot_row())
        )
        hydrated = fixture.run(
            lambda store: store.hydrate_operation("db", self.OPERATION)
        )
        batch = hydrated.batch
        self.assertEqual(batch.feed_epoch, "epoch-1")
        self.assertEqual(
            (
                batch.minimum_valid_version,
                batch.high_water_version,
                batch.delivered_through_version,
            ),
            (12, 12, 12),
        )
        self.assertEqual(
            [(c.resource, c.operation, c.commit_version) for c in batch.changes],
            [(ResourceRef("takeoff", "5", 8), ChangeOperation.CREATE, 12)],
        )
        raw = fixture.raw
        statements = fixture.server.statements(1)
        self.assertEqual(
            statements[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        # hydration happens inside the snapshot, before the final commit
        self.assertEqual(fixture.hydrated[0][1], 1)
        self.assertEqual((raw.commits, raw.rollbacks), (2, 0))
        fixture.server.assert_everything_closed()

    def test_hydrate_operation_rejects_missing_metadata_marker_and_changelog(self):
        cases = (
            ("no rows", [], "Change Tracking metadata is unavailable"),
            (
                "null version",
                [(None,) + (None,) * 14],
                "Change Tracking metadata is unavailable",
            ),
            (
                "marker missing",
                [self._snapshot_row(marker=False, with_log=False)],
                "marker is missing",
            ),
            (
                "marker without changelog",
                [self._snapshot_row(with_log=False)],
                "no ChangeLog records",
            ),
        )
        for label, rows, message in cases:
            with self.subTest(label=label):
                fixture = _StrictStoreFixture()
                fixture.server.on("DECLARE @CommitVersion bigint=", Reply.rows(*rows))
                with self.assertRaisesRegex(ValueError, message):
                    fixture.run(
                        lambda store: store.hydrate_operation("db", self.OPERATION)
                    )
                raw = fixture.raw
                self.assertEqual((raw.commits, raw.rollbacks), (1, 1))
                self.assertEqual(fixture.hydrated, [])
                fixture.server.assert_everything_closed()


class StoreStrictFeedTests(unittest.TestCase):
    def _marker(self, index):
        return str(uuid.UUID(int=index))

    def _poll(self, fixture, after, limit):
        return fixture.run(
            lambda store: store.poll_changes("db", after, limit, "local-session")
        )

    def test_poll_runs_in_one_snapshot_transaction_and_hydrates_before_the_commit(self):
        marker = self._marker(1)
        fixture = _StrictStoreFixture(
            markers=[(12, "I", marker)],
            log_rows=[
                (
                    1,
                    12,
                    marker,
                    "other",
                    8,
                    "condition",
                    "42",
                    "update",
                    None,
                    None,
                    None,
                    "ost_visualizer",
                )
            ],
        )
        result = self._poll(fixture, 11, 10)
        raw = fixture.raw
        self.assertFalse(fixture.server.connect_calls[0]["autocommit"])
        self.assertEqual(
            fixture.server.statements(1)[:2],
            ["SET TRANSACTION ISOLATION LEVEL SNAPSHOT", "BEGIN TRANSACTION"],
        )
        self.assertEqual(fixture.hydrated[0][1], 1)
        self.assertEqual((raw.commits, raw.rollbacks), (2, 0))
        self.assertEqual(result.observed_batch.delivered_through_version, 12)
        fixture.server.assert_everything_closed()

    def test_checkpoint_outside_the_retained_window_ends_with_a_rollback_and_no_hydration(
        self,
    ):
        for label, after, expected in (
            ("below minimum", 5, True),
            ("at minimum", 10, False),
            ("at high water", 25, False),
            ("above high water", 26, True),
        ):
            with self.subTest(label=label):
                fixture = _StrictStoreFixture(high_water=25, minimum=10)
                result = self._poll(fixture, after, 10)
                raw = fixture.raw
                invalid = (raw.commits, raw.rollbacks) == (1, 1)
                self.assertEqual(invalid, expected)
                self.assertEqual(
                    any("CHANGETABLE" in sql for sql in fixture.server.statements(1)),
                    not expected,
                )
                if expected:
                    self.assertEqual(
                        result.observed_batch.delivered_through_version, after
                    )
                    self.assertEqual(fixture.hydrated, [])
                else:
                    self.assertEqual(len(fixture.hydrated), 1)
                fixture.server.assert_everything_closed()

    def test_page_boundary_at_one_below_at_and_the_maximum_batch_size(self):
        # (requested limit, markers returned, high water, expected checkpoint)
        for limit, count, high_water, expected_through in (
            (3, 2, 25, 25),  # fewer markers than the limit: the page reaches high water
            (
                3,
                3,
                25,
                15,
            ),  # exactly the limit: more may follow, stop at the last marker
            (10_000, 499, 600, 600),  # requested limit is capped to 500
            (10_000, 500, 600, 512),  # a full capped page of 500 markers
        ):
            with self.subTest(limit=limit, markers=count):
                markers = [
                    (13 + index, "I", self._marker(index + 1)) for index in range(count)
                ]
                log_rows = [
                    (
                        index + 1,
                        marker[0],
                        marker[2],
                        "other",
                        8,
                        "condition",
                        str(index),
                        "update",
                        None,
                        None,
                        None,
                        "ost_visualizer",
                    )
                    for index, marker in enumerate(markers)
                ]
                fixture = _StrictStoreFixture(
                    high_water=high_water, markers=markers, log_rows=log_rows
                )
                result = self._poll(fixture, 12, limit)
                self.assertEqual(
                    result.observed_batch.delivered_through_version, expected_through
                )
                self.assertEqual(len(result.observed_batch.changes), count)
                # 500 markers send 1000 parameters: below the 2100 request limit
                loader = [
                    params
                    for cursor in fixture.raw.cursors
                    for sql, params in cursor.executed
                    if "MarkerVersions" in sql
                ][0]
                self.assertEqual(len(loader), 2 * count)
                self.assertLess(len(loader), MAX_PARAMETERS)
                fixture.server.assert_everything_closed()

    def test_database_without_snapshot_isolation_fails_the_poll_and_releases_the_connection(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.snapshot_enabled = False
        with self.assertRaises(SqlInfrastructureError):
            self._poll(fixture, 11, 10)
        raw = fixture.raw
        self.assertEqual(raw.rollbacks, 1)
        fixture.server.assert_everything_closed()

    def test_checkpoint_zero_is_a_real_checkpoint_checked_against_the_minimum_valid_version(
        self,
    ):
        # Decision D3: there is no "no checkpoint" sentinel. 0 is the version a
        # session starts from in a database that has no tracked change yet, so it
        # is valid only while the history from version 0 is still retained
        # (minimum valid version 0). Otherwise CHANGETABLE would raise on a real
        # server, so it is never asked and the poll reports the retention gap.
        for label, after, minimum, high_water, expected_gap in (
            ("0 with history retained from 0", 0, 0, 25, False),
            ("0 below the first retained version", 0, 1, 25, True),
            ("0 far below the retained range", 0, 20, 25, True),
            ("a real checkpoint one below the minimum", 19, 20, 25, True),
            ("a real checkpoint at the minimum", 20, 20, 25, False),
            ("0 in an empty database", 0, 0, 0, False),
        ):
            with self.subTest(label=label):
                fixture = _StrictStoreFixture(high_water=high_water, minimum=minimum)
                result = self._poll(fixture, after, 10)
                raw = fixture.raw
                queried = any(
                    "CHANGETABLE" in sql for sql in fixture.server.statements(1)
                )
                self.assertEqual(queried, not expected_gap)
                self.assertEqual(
                    (raw.commits, raw.rollbacks),
                    (1, 1) if expected_gap else (2, 0),
                )
                batch = result.observed_batch
                self.assertEqual(batch.minimum_valid_version, minimum)
                self.assertEqual(batch.high_water_version, high_water)
                if expected_gap:
                    # the unchanged checkpoint is what the coordinator compares
                    self.assertEqual(batch.delivered_through_version, after)
                    self.assertEqual(batch.changes, ())
                    self.assertEqual(fixture.hydrated, [])
                else:
                    self.assertEqual(len(fixture.hydrated), 1)
                fixture.server.assert_everything_closed()

    def test_strict_fake_rejects_changetable_below_the_minimum_valid_version(self):
        # The strict model must refuse what SQL Server refuses, otherwise the poll
        # tests above could not tell a fixed store from the unfixed one.
        server = StrictSqlServer()
        server.change_tracking_minimum = lambda: 5
        server.on("CHANGETABLE(", Reply.rows())
        cursor = server.connect("x", autocommit=True).cursor()
        sql = (
            "SELECT ct.[SYS_CHANGE_VERSION] FROM CHANGETABLE(CHANGES "
            "[ostv].[ChangeTransactions], ?) ct WHERE ct.[SYS_CHANGE_VERSION] <= ?"
        )
        for version in (0, 4):
            with self.subTest(version=version):
                with self.assertRaises(pyodbc.Error) as raised:
                    cursor.execute(sql, version, 25)
                self.assertIn("22002", raised.exception.args[1])
        for version in (5, 6):
            with self.subTest(version=version):
                cursor.execute(sql, version, 25)
        # NULL is the SQL Server spelling of "no checkpoint": never validated
        cursor.execute(sql, None, 25)
        cursor.execute(
            "SELECT 1 FROM CHANGETABLE(CHANGES [ostv].[ChangeTransactions], NULL) ct"
        )
        with self.assertRaises(pyodbc.Error):
            cursor.execute(
                "SELECT 1 FROM CHANGETABLE(CHANGES [ostv].[ChangeTransactions], 3) ct"
            )
        # without a configured minimum the rule is off (legacy canned fakes)
        server.change_tracking_minimum = None
        cursor.execute(sql, 0, 25)


class StoreStrictIdentityStatementTests(unittest.TestCase):
    def test_session_identity_read_uses_the_exact_single_row_identity_predicate(self):
        from tests.helpers.sql.strict_sql_fakes import (
            EXPECTED_DATABASE_METADATA_PREDICATE,
        )

        fixture = _StrictStoreFixture()
        fixture.run(
            lambda store: store.start_session(
                "db", str(uuid.uuid4()), str(uuid.uuid4()), "u", "m", "1"
            )
        )
        self.assertEqual(
            fixture.server.statements(1)[0],
            "SELECT m.[DatabaseGuid] FROM [ostv].[DatabaseMetadata] m WHERE "
            + EXPECTED_DATABASE_METADATA_PREDICATE,
        )


class StoreStrictSweepSurvivorTests(unittest.TestCase):
    """Survivors of the second-pass mutation sweep over collaboration_store.py."""

    OPERATION = "859945fa-fbf8-4b90-bafe-735976033238"

    def _full_fixture(self):
        fixture = _StrictStoreFixture()
        server = fixture.server

        def front(pattern, reply):
            matcher = (
                (lambda sql: pattern in sql) if isinstance(pattern, str) else pattern
            )
            server.rules.insert(0, (matcher, reply))

        server.on = front  # most specific rules first: the fixture's defaults are broad
        server.on("OUTPUT INSERTED.[LastAcknowledgedVersion]", Reply.rows((17,)))
        server.on("MERGE [ostv].[Presence]", Reply.dml(1))
        server.on("DELETE FROM [ostv].[Locks] WHERE [OwnerSessionId]=?", Reply.dml(1))
        server.on("DELETE FROM [ostv].[Locks] WHERE [LockToken]=?", Reply.dml(1))
        server.on("FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s", Reply.rows())
        server.on("FROM [ostv].[Locks] l WHERE", Reply.rows())
        server.on("SELECT 1 FROM [ostv].[Sessions]", Reply.rows((1,)))
        server.on("UPDATE l SET [LastRenewedAt]", Reply.rows(("takeoff", "10", 8)))
        server.on(
            "FROM [ostv].[ChangeTransactions] WHERE [TransactionId]=?", Reply.rows()
        )

        def acquire(call):
            return Reply.rows(
                *(
                    (0, item["ordinal"], None, item["lock_token"])
                    for item in call.json(0)
                )
            )

        server.on("DECLARE @Requested TABLE", acquire)
        marker = self.OPERATION
        server.on(
            "DECLARE @CommitVersion bigint=",
            Reply.rows(
                (
                    12,
                    "epoch-1",
                    marker,
                    1,
                    12,
                    marker,
                    "859945fa-fbf8-4b90-bafe-735976033238",
                    8,
                    "takeoff",
                    "5",
                    "create",
                    (1).to_bytes(8, "big"),
                    None,
                    None,
                    "ost_visualizer",
                )
            ),
        )
        return fixture

    def test_every_operation_requests_the_right_database_connection_mode(self):
        resource = ResourceRef("takeoff", "10", 8)
        operations = (
            (
                "start_session",
                lambda s: s.start_session("db", "S", "C", "u", "m", "1"),
                False,
                False,
            ),
            (
                "heartbeat",
                lambda s: s.heartbeat("db", "S", 1, 8, 9, PresenceMode.VIEWING),
                False,
                False,
            ),
            (
                "close_session",
                lambda s: s.close_session("db", "S", "bye"),
                False,
                False,
            ),
            ("list_presence", lambda s: s.list_presence("db", 8, "me"), True, True),
            ("list_locks", lambda s: s.list_locks("db", "me"), True, True),
            (
                "acquire_locks",
                lambda s: s.acquire_locks("db", "S", (resource,), "edit"),
                False,
                False,
            ),
            ("renew_lock", lambda s: s.renew_lock("db", "S", "token"), False, False),
            (
                "release_lock",
                lambda s: s.release_lock("db", "S", "token"),
                False,
                False,
            ),
            ("poll_changes", lambda s: s.poll_changes("db", 11, 10, "me"), True, False),
            (
                "query_operation",
                lambda s: s.query_operation("db", self.OPERATION),
                False,
                False,
            ),
            (
                "hydrate_operation",
                lambda s: s.hydrate_operation("db", self.OPERATION),
                True,
                False,
            ),
        )
        for name, call, read_only, autocommit in operations:
            with self.subTest(operation=name):
                fixture = self._full_fixture()
                fixture.run(call)
                self.assertEqual(fixture.store._requests.calls, [("db", read_only)])
                self.assertEqual(
                    [c["autocommit"] for c in fixture.server.connect_calls],
                    [autocommit],
                )
                fixture.server.assert_everything_closed()

    def test_store_wires_the_descriptor_factory_manager_and_remote_reader(self):
        from ost_visualizer.domain.entities.database_descriptor import (
            DatabaseDescriptor,
        )
        from ost_visualizer.infrastructure.database.descriptor_registry import (
            DatabaseDescriptorRegistry,
        )

        registry = DatabaseDescriptorRegistry()
        descriptor = DatabaseDescriptor.for_sql_server(
            SqlServerDatabaseLocation(server="localhost", database="DB"),
            schema_version=1,
        )
        registry.register(descriptor)
        remote = object()
        store = SqlCollaborationStore(registry, SimpleNamespace(), remote)
        self.assertIsInstance(store._connections, SqlConnectionManager)
        self.assertIs(store._remote_reader, remote)
        request = store._requests.request(descriptor.database_id, read_only=False)
        self.assertEqual(request.location, descriptor.sql_location)
        manager = SqlConnectionManager(drivers=["ODBC Driver 18 for SQL Server"])
        store = SqlCollaborationStore(
            registry, SimpleNamespace(), remote, connection_manager=manager
        )
        self.assertIs(store._connections, manager)

    def test_start_session_edge_values(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            COLLABORATION_STALE_SECONDS,
        )

        # a provided stop probe that says "keep going" must not stop the start
        fixture = _StrictStoreFixture(high_water=0)
        session = fixture.run(
            lambda s: s.start_session(
                "db", "S", "C", "u", "m", "1", stop_requested=lambda: False
            )
        )
        self.assertEqual(session.last_acknowledged_version, 0)
        # a NULL guid column is a metadata failure, not a crash
        nulls = _StrictStoreFixture()
        nulls.server.rules.insert(
            0,
            (
                lambda sql: sql.startswith("SELECT m.[DatabaseGuid]"),
                Reply.rows((None,)),
            ),
        )
        with self.assertRaises(SqlInfrastructureError) as raised:
            nulls.run(lambda s: s.start_session("db", "S", "C", "u", "m", "1"))
        self.assertEqual(raised.exception.details.code, SqlErrorCode.SCHEMA_MISMATCH)
        # a NULL change-tracking version starts the checkpoint at zero
        none_version = _StrictStoreFixture()
        none_version.server.rules.insert(
            0,
            (
                lambda sql: sql == "SELECT CHANGE_TRACKING_CURRENT_VERSION()",
                Reply.rows((None,)),
            ),
        )
        started = none_version.run(
            lambda s: s.start_session("db", "S", "C", "u", "m", "1")
        )
        self.assertEqual(started.last_acknowledged_version, 0)
        # the stale-session cutoff is bound as a NEGATIVE number of seconds
        cleanup = [
            params
            for cursor in fixture.raw.cursors
            for sql, params in cursor.executed
            if sql.startswith("UPDATE [ostv].[Sessions] SET [DisconnectedAt]")
        ][0]
        self.assertEqual(cleanup, (-COLLABORATION_STALE_SECONDS,))
        self.assertLess(cleanup[0], 0)

    def test_stale_cutoffs_are_negative_seconds_in_every_liveness_statement(self):
        from ost_visualizer.application.dtos.collaboration_dtos import (
            COLLABORATION_STALE_SECONDS,
        )

        fixture = self._full_fixture()
        fixture.run(lambda s: s.heartbeat("db", "S", 5, 8, 9, PresenceMode.EDITING))
        heartbeat = [
            params
            for cursor in fixture.raw.cursors
            for sql, params in cursor.executed
            if "OUTPUT INSERTED.[LastAcknowledgedVersion]" in sql
        ][0]
        self.assertEqual(heartbeat, (5, 5, "S", -COLLABORATION_STALE_SECONDS))
        fixture = self._full_fixture()
        fixture.run(lambda s: s.list_presence("db", 8, "me"))
        presence = [
            params
            for cursor in fixture.raw.cursors
            for sql, params in cursor.executed
            if "FROM [ostv].[Presence] p" in sql
        ][0]
        self.assertEqual(presence, (8, "me", -COLLABORATION_STALE_SECONDS))
        fixture = self._full_fixture()
        fixture.run(lambda s: s.renew_lock("db", "S", "token"))
        liveness = [
            params
            for cursor in fixture.raw.cursors
            for sql, params in cursor.executed
            if sql.startswith("SELECT 1 FROM [ostv].[Sessions]")
        ][0]
        self.assertEqual(liveness, ("S", -COLLABORATION_STALE_SECONDS))

    def test_presence_and_lock_rows_map_each_catalog_column_to_its_own_field(self):
        fixture = self._full_fixture()
        fixture.server.rules.insert(
            0,
            (
                lambda sql: "FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s" in sql,
                Reply.rows(
                    ("SA", "Ana", "1.2.3", 8, 31, "editing"),
                    ("SB", "Bob", "4.5.6", None, None, "viewing"),
                ),
            ),
        )
        fixture.server.rules.insert(
            0,
            (
                lambda sql: "FROM [ostv].[Locks] l WHERE" in sql,
                Reply.rows(
                    ("takeoff", "10", 8, "TOKEN-1"), ("bid", "9", None, "TOKEN-2")
                ),
            ),
        )
        presence = fixture.run(lambda s: s.list_presence("db", 8, "me"))
        self.assertEqual(
            [
                (
                    p.session_id,
                    p.display_name,
                    p.application_version,
                    p.bid_uid,
                    p.page_uid,
                    p.mode,
                )
                for p in presence
            ],
            [
                ("SA", "Ana", "1.2.3", 8, 31, PresenceMode.EDITING),
                ("SB", "Bob", "4.5.6", None, None, PresenceMode.VIEWING),
            ],
        )
        locks = fixture.run(lambda s: s.list_locks("db", "me"))
        self.assertEqual(
            [(l.resource, l.lock_token) for l in locks],
            [
                (ResourceRef("takeoff", "10", 8), "TOKEN-1"),
                (ResourceRef("bid", "9"), "TOKEN-2"),
            ],
        )

    def test_renew_lock_maps_the_renewed_resource_columns(self):
        for bid, expected in ((8, 8), (None, None)):
            with self.subTest(bid=bid):
                fixture = self._full_fixture()
                fixture.server.rules.insert(
                    0,
                    (
                        lambda sql: "UPDATE l SET [LastRenewedAt]" in sql,
                        Reply.rows(("takeoff", "10", bid)),
                    ),
                )
                lock = fixture.run(lambda s: s.renew_lock("db", "S", "token"))
                self.assertEqual(lock.resource, ResourceRef("takeoff", "10", expected))

    def test_release_lock_failure_is_rolled_back_not_committed(self):
        fixture = self._full_fixture()

        def fail(_call):
            raise sql_server_error("08S01", "Communication link failure")

        fixture.server.rules.insert(
            0,
            (lambda sql: "DELETE FROM [ostv].[Locks] WHERE [LockToken]=?" in sql, fail),
        )
        with self.assertRaises(SqlInfrastructureError):
            fixture.run(lambda s: s.release_lock("db", "S", "token"))
        raw = fixture.raw
        self.assertEqual((raw.commits, raw.rollbacks), (0, 1))

    def test_unavailable_change_tracking_rows_are_a_value_error_in_every_shape(self):
        for label, arguments in (
            ("minimum row missing", {"minimum": None}),
            ("minimum NULL", {"minimum": (None,)}),
            ("high water row missing", {"high_water": None}),
            ("high water NULL", {"high_water": (None,)}),
        ):
            with self.subTest(label=label):
                fixture = _StrictStoreFixture()
                # _StrictStoreFixture scripts these rows; override with the bad shape
                if "minimum" in arguments:
                    fixture.server.rules.insert(
                        0,
                        (
                            lambda sql: "CHANGE_TRACKING_MIN_VALID_VERSION" in sql,
                            Reply.rows(
                                *(
                                    [arguments["minimum"]]
                                    if arguments["minimum"]
                                    else []
                                )
                            ),
                        ),
                    )
                else:
                    fixture.server.rules.insert(
                        0,
                        (
                            lambda sql: sql
                            == "SELECT CHANGE_TRACKING_CURRENT_VERSION()",
                            Reply.rows(
                                *(
                                    [arguments["high_water"]]
                                    if arguments["high_water"]
                                    else []
                                )
                            ),
                        ),
                    )
                with self.assertRaisesRegex(
                    ValueError, "Change Tracking metadata is unavailable"
                ):
                    fixture.run(lambda s: s.poll_changes("db", 11, 10, "me"))
                raw = fixture.raw
                self.assertEqual((raw.commits, raw.rollbacks), (1, 1))

    def test_change_rows_map_every_column_and_validate_changed_fields(self):
        row = (
            101,
            202,
            "859945FA-FBF8-4B90-BAFE-735976033238",
            "8B2CE0C5-90F8-4580-A5EE-B2F4FDC7581A",
            303,
            "takeoff",
            "404",
            "update",
            (7).to_bytes(8, "big"),
            '["Position", "Color"]',
            "payload-text",
            "ost_visualizer",
        )
        change = _change_from_row(row)
        self.assertEqual(
            (
                change.sequence,
                change.commit_version,
                change.transaction_id,
                change.source_session_id,
                change.resource,
                change.operation,
                change.resulting_version,
                change.changed_fields,
                change.payload,
                change.source_kind.value,
            ),
            (
                101,
                202,
                "859945fa-fbf8-4b90-bafe-735976033238",
                "8B2CE0C5-90F8-4580-A5EE-B2F4FDC7581A",
                ResourceRef("takeoff", "404", 303),
                ChangeOperation.UPDATE,
                ConcurrencyToken((7).to_bytes(8, "big")),
                ("Position", "Color"),
                "payload-text",
                "ost_visualizer",
            ),
        )
        # NULL / empty optional columns
        bare = _change_from_row(
            (
                1,
                2,
                row[2],
                None,
                None,
                "takeoff",
                "9",
                "create",
                None,
                None,
                None,
                "ost_visualizer",
            )
        )
        self.assertEqual(
            (
                bare.source_session_id,
                bare.resource.bid_uid,
                bare.resulting_version,
                bare.changed_fields,
                bare.payload,
            ),
            (None, None, None, (), ""),
        )
        self.assertEqual(
            _change_from_row(row[:9] + ("", "", "ost_visualizer")).changed_fields, ()
        )
        for invalid in ('{"a": 1}', "[1, 2]", '["a", 1]', "not json"):
            with self.subTest(changed_fields=invalid):
                with self.assertRaises(ValueError):
                    _change_from_row(row[:9] + (invalid, None, "ost_visualizer"))

    def test_query_operation_returns_every_marker_column(self):
        fixture = self._full_fixture()
        fixture.server.rules.insert(
            0,
            (
                lambda sql: "FROM [ostv].[ChangeTransactions] WHERE [TransactionId]=?"
                in sql,
                Reply.rows(("takeoff_placement", "b" * 64, 1, '{"value":["1"]}')),
            ),
        )
        result = fixture.run(lambda s: s.query_operation("db", self.OPERATION))
        self.assertEqual(
            (
                result.found,
                result.mutation_type,
                result.request_hash,
                result.result_format_version,
                result.result_payload,
            ),
            (True, "takeoff_placement", "b" * 64, 1, '{"value":["1"]}'),
        )

    def test_snapshot_rows_without_a_change_log_are_rejected_in_the_real_left_join_shape(
        self,
    ):
        marker = self.OPERATION
        # LEFT JOIN with no ChangeLog row: the variable columns stay populated
        no_log = (
            12,
            "epoch-1",
            marker,
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
        for label, rows, message in (
            ("no log rows", [no_log], "no ChangeLog records"),
            (
                "version NULL only",
                [(None, "epoch-1", marker) + no_log[3:]],
                "metadata is unavailable",
            ),
        ):
            with self.subTest(label=label):
                fixture = self._full_fixture()
                fixture.server.rules.insert(
                    0,
                    (
                        lambda sql: "DECLARE @CommitVersion bigint=" in sql,
                        Reply.rows(*rows),
                    ),
                )
                with self.assertRaisesRegex(ValueError, message):
                    fixture.run(lambda s: s.hydrate_operation("db", self.OPERATION))

    def test_resource_identity_for_duplicates_is_type_and_id_within_one_transaction(
        self,
    ):
        transaction = "859945fa-fbf8-4b90-bafe-735976033238"

        def row(sequence, resource_type, resource_id, bid):
            return (
                sequence,
                12,
                transaction,
                None,
                bid,
                resource_type,
                resource_id,
                "update",
                None,
                None,
                None,
                "ost_visualizer",
            )

        distinct = (
            row(1, "condition", "5", 8),
            row(2, "takeoff", "5", 8),  # same id and bid, other type
            row(3, "takeoff", "6", 9),  # other id and bid
        )
        SqlCollaborationStore._validate_transaction_change_rows(
            distinct, ((transaction, 12),)
        )
        with self.assertRaisesRegex(ValueError, "duplicate resource payloads"):
            SqlCollaborationStore._validate_transaction_change_rows(
                (row(1, "takeoff", "5", 8), row(2, "takeoff", "5", 8)),
                ((transaction, 12),),
            )
        # a LEFT JOIN row for a marker without changes is not a change row
        other = "0e2b1ff2-7e6d-4d5c-9f4c-1c0d8f4a9b11"
        empty = (None, 13, None, None, None, None, None, None, None, None, None, None)
        with self.assertRaisesRegex(ValueError, "no ChangeLog records"):
            SqlCollaborationStore._validate_transaction_change_rows(
                (row(1, "takeoff", "5", 8), empty), ((transaction, 12), (other, 13))
            )


class StoreStrictRowShapeTests(unittest.TestCase):
    """Remaining row-index survivors: columns that are populated independently."""

    def test_presence_rows_with_a_page_but_no_bid_keep_each_nullable_column_separate(
        self,
    ):
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s",
            Reply.rows(("SA", "Ana", "1.0", None, 31, "viewing")),
        )
        presence = fixture.run(lambda s: s.list_presence("db", 8, "me"))
        self.assertEqual((presence[0].bid_uid, presence[0].page_uid), (None, 31))
        fixture = _StrictStoreFixture()
        fixture.server.on(
            "FROM [ostv].[Presence] p JOIN [ostv].[Sessions] s",
            Reply.rows(("SA", "Ana", "1.0", 8, None, "viewing")),
        )
        presence = fixture.run(lambda s: s.list_presence("db", 8, "me"))
        self.assertEqual((presence[0].bid_uid, presence[0].page_uid), (8, None))

    def test_change_rows_with_independent_nullable_columns(self):
        transaction = "859945fa-fbf8-4b90-bafe-735976033238"
        token = (9).to_bytes(8, "big")
        # no session, but a bid, a result version and NO changed fields
        change = _change_from_row(
            (
                1,
                2,
                transaction,
                None,
                303,
                "takeoff",
                "9",
                "create",
                token,
                None,
                None,
                "ost_visualizer",
            )
        )
        self.assertEqual(
            (
                change.source_session_id,
                change.resource.bid_uid,
                change.resulting_version,
                change.changed_fields,
            ),
            (None, 303, ConcurrencyToken(token), ()),
        )
        # a session and changed fields but no bid and no result version
        change = _change_from_row(
            (
                1,
                2,
                transaction,
                "S1",
                None,
                "takeoff",
                "9",
                "delete",
                None,
                '["a"]',
                None,
                "ost_visualizer",
            )
        )
        self.assertEqual(
            (
                change.source_session_id,
                change.resource.bid_uid,
                change.resulting_version,
                change.changed_fields,
            ),
            ("S1", None, None, ("a",)),
        )


from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    collaboration_lock_batch_rule,
)
from tests.infrastructure.sql.test_writer import (  # noqa: E402
    _DatabaseMutationRequest as _WriterMutationRequest,
    _strict_writer,
    _StrictMutationServer,
)


class StoreWriterLockOrderTests(unittest.TestCase):
    """Decision D1: ONE application-lock order shared by the store and the writer.
    The store's edit-lock batch and the writer's mutation locks both take
    `sp_getapplock` locks named `OSTV:<type>:<id>`, so a request that touches the
    same resources from two transactions deadlocks when they ask in opposite
    orders. Real: the production store, writer and connection manager; fake: the
    strict pyodbc model (its lock table never blocks, it records request order).
    """

    BID = ResourceRef("bid", "8", 8)
    ANNOTATION = ResourceRef("annotation", "line/7", 8)
    AREA = ResourceRef("area", "3", 8)
    TAKEOFF = ResourceRef("takeoff", "10", 8)
    BID_FIRST = [
        "OSTV:bid:8",
        "OSTV:annotation:line/7",
        "OSTV:area:3",
        "OSTV:takeoff:10",
    ]

    def _transactions(self, resources):
        server = _StrictMutationServer()
        collaboration_lock_batch_rule(server)
        writer, descriptor, _ = _strict_writer(server)
        store = SqlCollaborationStore.__new__(SqlCollaborationStore)
        store._requests = _StoreRequests(
            SqlConnectionRequest(
                SqlServerDatabaseLocation(server="localhost", database="OSTV_TEST")
            )
        )
        store._connections = server.manager()
        store._remote_reader = None
        request = _WriterMutationRequest(
            database_id=descriptor.database_id,
            session_id="session-1",
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="a" * 64,
            resources=tuple(resources),
        )

        def mutate(recorder):
            for resource in resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return True

        with server.patched():
            store_locks = store.acquire_locks(
                "db", "session-1", tuple(resources), "edit"
            )
            result = writer.execute(request, mutate)
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
        return server, store_locks, request

    def test_mixed_request_takes_the_bid_lock_first_in_the_store_and_the_writer(self):
        resources = (self.AREA, self.ANNOTATION, self.TAKEOFF, self.BID)
        server, store_locks, request = self._transactions(resources)
        orders = server.applocks.acquisition_orders()
        store_connection, writer_connection = 1, 2
        self.assertEqual(orders[store_connection], self.BID_FIRST)
        self.assertEqual(
            orders[writer_connection],
            [f"OSTV:operation:{request.operation_id}", *self.BID_FIRST],
        )
        self.assertEqual(server.applocks.order_inversions(), [])
        # the store reports one lock per requested resource, in that same order
        self.assertEqual(
            [lock.resource for lock in store_locks],
            [self.BID, self.ANNOTATION, self.AREA, self.TAKEOFF],
        )
        server.assert_everything_closed()

    def test_the_inversion_detector_reports_opposite_request_orders(self):
        server = StrictSqlServer()
        first = server.connect("a", autocommit=False)
        second = server.connect("b", autocommit=False)
        server.applocks.acquire(first, "OSTV:bid:8", "Exclusive")
        server.applocks.acquire(first, "OSTV:area:3", "Exclusive")
        server.applocks.acquire(second, "OSTV:area:3", "Exclusive")
        server.applocks.acquire(second, "OSTV:bid:8", "Exclusive")
        self.assertEqual(
            server.applocks.order_inversions(),
            [("OSTV:bid:8", "OSTV:area:3", first.number, second.number)],
        )
