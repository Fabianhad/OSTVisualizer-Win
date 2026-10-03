"""Live two-client acceptance of the SQL writer's locked-Bid refusal (decision B1).
Skipped unless the disposable-SQL environment of tests/helpers/sql/integration_support
is configured (OSTV_SQL_INTEGRATION=1 and the OSTV_SQL_* variables). It has NEVER been
run in this repository's development environment (no SQL Server available): it is
py_compile-checked only. Its job is to confirm on a real server what the strict-fake
tests in tests/infrastructure/sql/test_writer.py can only model: the T-SQL of the
``bid_locked`` Violations branch, the NULL/dangling status semantics, the Shared/Exclusive
``OSTV:bid:<uid>`` application-lock serialisation of a status flip against an in-flight
child write, and the resource-shape exemptions.
"""

import threading
import unittest
import uuid
import pyodbc
from ost_visualizer.application.dtos.collaboration_dtos import (
    ChangeOperation,
    CollaborationMutationType,
    DatabaseMutationRequest,
    MutationOutcomeStatus,
    MutationRejectionReason,
    ResourceRef,
    SynchronizationConflictKind,
)
from ost_visualizer.application.services.database_session_registry import (
    DatabaseSessionRegistry,
)
from ost_visualizer.infrastructure.sql.collaboration_store import SqlCollaborationStore
from ost_visualizer.infrastructure.sql.connection_manager import SqlConnectionRequest
from ost_visualizer.infrastructure.sql.remote_change_reader import SqlRemoteChangeReader
from ost_visualizer.infrastructure.sql.writer import SqlProjectWriter
from tests.helpers.sql.integration_support import (
    DisposableSqlConfiguration,
    DisposableSqlDatabase,
)

# the module, not its TestCase class: importing the class here would make test
# discovery run the acceptance tests of that module a second time
import tests.integration.sql.test_collaboration_acceptance as _acceptance


class _Client:
    """One SQL login with its own session and writer (a second OST Visualizer)."""

    def __init__(self, test, database, configuration, label):
        (
            self.descriptor,
            registry,
            credentials,
            admin,
            windows_master,
            login,
        ) = _acceptance.SqlCollaborationIntegrationTests._create_test_client(
            database, configuration, label
        )
        test.addCleanup(
            _acceptance.SqlCollaborationIntegrationTests._drop_test_login,
            admin,
            windows_master,
            login,
        )
        self.database_id = self.descriptor.database_id
        self.store = SqlCollaborationStore(
            registry,
            credentials,
            SqlRemoteChangeReader(registry, credentials, database.connections),
            database.connections,
        )
        session = self.store.start_session(
            self.database_id,
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            f"bid-lock-{label}",
            "test-machine",
            "integration-test",
        )
        self.session_id = session.session_id
        test.addCleanup(
            self.store.close_session,
            self.database_id,
            self.session_id,
            "integration-test-complete",
        )
        sessions = DatabaseSessionRegistry()
        sessions.register(self.database_id, self.session_id)
        self.writer = SqlProjectWriter(
            registry, credentials, sessions, database.connections
        )

    def request(self, resources, *, exempt=False):
        return DatabaseMutationRequest(
            database_id=self.database_id,
            session_id=self.session_id,
            operation_id=str(uuid.uuid4()),
            mutation_type=CollaborationMutationType.PROJECT_WRITE.value,
            request_hash="b" * 64,
            resources=tuple(resources),
            bid_lock_exempt=exempt,
        )

    def write(self, resources, *, exempt=False, before_commit=None):
        """Execute a write whose operation only records the resources it names."""
        executed = []

        def operation(recorder):
            executed.append(True)
            if before_commit is not None:
                before_commit()
            for resource in resources:
                recorder.record(resource, ChangeOperation.UPDATE)
            return True

        request = self.request(resources, exempt=exempt)
        return self.writer.execute(request, operation), request, executed


class SqlBidLockEnforcementIntegrationTests(unittest.TestCase):
    def _scenario(self):
        configuration = DisposableSqlConfiguration.from_environment()
        database = DisposableSqlDatabase(configuration)
        return configuration, database

    @staticmethod
    def _admin_cursor(database, configuration):
        return database.connections.connection(
            SqlConnectionRequest(database.location, password=configuration.password),
            autocommit=True,
        )

    @staticmethod
    def _status(cursor, locked):
        cursor.execute(
            "INSERT INTO [dbo].[JobStatuses] ([Locked], [Name], [Sequence]) "
            "OUTPUT INSERTED.[UID] VALUES (?, ?, 1)",
            locked,
            f"status-{uuid.uuid4().hex[:8]}",
        )
        return int(cursor.fetchone()[0])

    @staticmethod
    def _bid(cursor, status_uid):
        cursor.execute(
            "INSERT INTO [dbo].[Bids] ([JobStatusUID]) OUTPUT INSERTED.[UID] "
            "VALUES (?)",
            status_uid,
        )
        return int(cursor.fetchone()[0])

    @staticmethod
    def _log_rows(cursor, operation_id):
        cursor.execute(
            "SELECT (SELECT COUNT(*) FROM [ostv].[ChangeLog] WHERE "
            "[TransactionId]=?), (SELECT COUNT(*) FROM [ostv].[ChangeTransactions] "
            "WHERE [TransactionId]=?)",
            operation_id,
            operation_id,
        )
        return tuple(int(value) for value in cursor.fetchone())

    def assert_refused(self, result, request, database, configuration):
        self.assertEqual(result.outcome_status, MutationOutcomeStatus.REJECTED)
        self.assertEqual(result.rejection_reason, MutationRejectionReason.BID_LOCKED)
        self.assertIsNone(result.conflict)
        with self._admin_cursor(database, configuration) as lease:
            with lease.cursor() as cursor:
                # a refusal rolls back: no ChangeLog row, no operation marker
                self.assertEqual(self._log_rows(cursor, request.operation_id), (0, 0))

    def test_locked_bid_refuses_child_writes_and_allows_project_level_shapes(self):
        configuration, database = self._scenario()
        with database:
            client = _Client(self, database, configuration, "LOCKED_SHAPES")
            with self._admin_cursor(database, configuration) as lease:
                with lease.cursor() as cursor:
                    locked_status = self._status(cursor, 1)
                    unlocked_status = self._status(cursor, 0)
                    null_status = self._status(cursor, None)
                    locked_bid = self._bid(cursor, locked_status)
                    unlocked_bid = self._bid(cursor, unlocked_status)
                    null_bid = self._bid(cursor, null_status)
                    no_status_bid = self._bid(cursor, None)
            takeoff = lambda bid: ResourceRef("takeoff", "1", bid)  # noqa: E731
            for label, bid in (("locked", locked_bid), ("NULL Locked", null_bid)):
                with self.subTest(refused=label):
                    result, request, executed = client.write([takeoff(bid)])
                    self.assertEqual(executed, [])
                    self.assert_refused(result, request, database, configuration)
            for label, bid in (
                ("unlocked", unlocked_bid),
                ("NULL JobStatusUID", no_status_bid),
            ):
                with self.subTest(allowed=label):
                    result, _request, executed = client.write([takeoff(bid)])
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    self.assertEqual(executed, [True])
            shapes = {
                "status change": [ResourceRef("bid", str(locked_bid), locked_bid)],
                "bid delete": [
                    ResourceRef("bid", str(locked_bid), locked_bid),
                    ResourceRef("projects_collection", "database"),
                ],
                "duplicate (source bid)": [
                    ResourceRef("bid", str(locked_bid), locked_bid)
                ],
                "move": [
                    ResourceRef("bid", str(locked_bid), locked_bid),
                    ResourceRef("project_bids", "orphan"),
                ],
                "master data": [ResourceRef("job_statuses_collection", "database")],
                "import shape": [
                    ResourceRef("project_bids", "orphan"),
                    ResourceRef("employees_collection", "database"),
                ],
            }
            for label, resources in shapes.items():
                with self.subTest(allowed_on_locked_bid=label):
                    result, _request, executed = client.write(resources)
                    self.assertEqual(
                        result.outcome_status, MutationOutcomeStatus.COMMITTED
                    )
                    self.assertEqual(executed, [True])
            with self.subTest("narrow exemption"):
                result, _request, executed = client.write(
                    [takeoff(locked_bid)], exempt=True
                )
                self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)

    def test_dangling_job_status_is_unlocked(self):
        configuration, database = self._scenario()
        with database:
            client = _Client(self, database, configuration, "DANGLING")
            with self._admin_cursor(database, configuration) as lease:
                with lease.cursor() as cursor:
                    try:
                        bid = self._bid(cursor, 987654)
                    except pyodbc.IntegrityError as exc:  # a foreign key forbids it
                        self.skipTest(f"the schema forbids a dangling status: {exc}")
            result, _request, executed = client.write(
                [ResourceRef("takeoff", "1", bid)]
            )
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
            self.assertEqual(executed, [True])

    def test_status_flip_inside_one_transaction_passes_and_the_next_write_is_refused(
        self,
    ):
        # A cover-sheet-shaped save that locks the Bid in its own transaction: the
        # check reads the state before the write, so it passes; the next write is
        # refused. Also covers lock-then-unlock through the 'bid'-only status change.
        configuration, database = self._scenario()
        with database:
            client = _Client(self, database, configuration, "FLIP")
            with self._admin_cursor(database, configuration) as lease:
                with lease.cursor() as cursor:
                    locked_status = self._status(cursor, 1)
                    unlocked_status = self._status(cursor, 0)
                    bid = self._bid(cursor, unlocked_status)
            resources = [
                ResourceRef("bid", str(bid), bid),
                ResourceRef("cover_sheet", str(bid), bid),
            ]

            def lock_the_bid():
                with client.writer._connection(client.database_id) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE [dbo].[Bids] SET [JobStatusUID]=? WHERE [UID]=?",
                            locked_status,
                            bid,
                        )

            result, _request, executed = client.write(
                resources, before_commit=lock_the_bid
            )
            self.assertEqual(result.outcome_status, MutationOutcomeStatus.COMMITTED)
            self.assertEqual(executed, [True])
            refused, request, executed = client.write(resources)
            self.assertEqual(executed, [])
            self.assert_refused(refused, request, database, configuration)

            def unlock_the_bid():
                with client.writer._connection(client.database_id) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "UPDATE [dbo].[Bids] SET [JobStatusUID]=? WHERE [UID]=?",
                            unlocked_status,
                            bid,
                        )

            status_change, _request, executed = client.write(
                [ResourceRef("bid", str(bid), bid)], before_commit=unlock_the_bid
            )
            self.assertEqual(
                status_change.outcome_status, MutationOutcomeStatus.COMMITTED
            )
            after, _request, executed = client.write([ResourceRef("takeoff", "1", bid)])
            self.assertEqual(after.outcome_status, MutationOutcomeStatus.COMMITTED)

    def test_a_status_change_waits_for_an_in_flight_child_write_and_is_serialised(self):
        # Client A holds the SHARED OSTV:bid:<uid> applock inside an unlocked-Bid
        # child write; client B's status change needs the EXCLUSIVE one, so it cannot
        # lock the Bid underneath A. B's request times out on the applock (a LEASE
        # conflict), A commits against the state it validated, and a retry of B then
        # succeeds and refuses the next child write.
        configuration, database = self._scenario()
        with database:
            writer_client = _Client(self, database, configuration, "RACE_WRITER")
            status_client = _Client(self, database, configuration, "RACE_STATUS")
            with self._admin_cursor(database, configuration) as lease:
                with lease.cursor() as cursor:
                    locked_status = self._status(cursor, 1)
                    unlocked_status = self._status(cursor, 0)
                    bid = self._bid(cursor, unlocked_status)
            in_flight = threading.Event()
            proceed = threading.Event()
            outcome = {}

            def hold():
                in_flight.set()
                proceed.wait(timeout=40)

            def run_child_write():
                outcome["child"] = writer_client.write(
                    [ResourceRef("takeoff", "1", bid)], before_commit=hold
                )

            thread = threading.Thread(target=run_child_write)
            thread.start()
            try:
                self.assertTrue(in_flight.wait(timeout=30))

                def lock_the_bid():
                    with status_client.writer._connection(
                        status_client.database_id
                    ) as connection:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "UPDATE [dbo].[Bids] SET [JobStatusUID]=? "
                                "WHERE [UID]=?",
                                locked_status,
                                bid,
                            )

                blocked, _request, executed = status_client.write(
                    [ResourceRef("bid", str(bid), bid)], before_commit=lock_the_bid
                )
                self.assertEqual(blocked.outcome_status, MutationOutcomeStatus.CONFLICT)
                self.assertEqual(
                    blocked.conflict.kind, SynchronizationConflictKind.LEASE
                )
                self.assertEqual(executed, [])
            finally:
                proceed.set()
                thread.join(timeout=60)
            child, _request, executed = outcome["child"]
            self.assertEqual(child.outcome_status, MutationOutcomeStatus.COMMITTED)
            retry, _request, _executed = status_client.write(
                [ResourceRef("bid", str(bid), bid)], before_commit=lock_the_bid
            )
            self.assertEqual(retry.outcome_status, MutationOutcomeStatus.COMMITTED)
            refused, request, executed = writer_client.write(
                [ResourceRef("takeoff", "1", bid)]
            )
            self.assertEqual(executed, [])
            self.assert_refused(refused, request, database, configuration)


if __name__ == "__main__":
    unittest.main()
