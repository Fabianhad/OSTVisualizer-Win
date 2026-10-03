"""Transaction-owned SQL application locks and complete batch acceptance."""

import json
import unittest
from unittest.mock import Mock
from ost_visualizer.application.dtos.collaboration_dtos import ResourceRef
from ost_visualizer.infrastructure.sql.errors import (
    SqlErrorCode,
    SqlInfrastructureError,
)
from ost_visualizer.infrastructure.sql.schema_lock import (
    SQL_SCHEMA_LOCK_RESOURCE,
    acquire_operation_transaction_lock,
    acquire_resource_transaction_locks,
    acquire_schema_transaction_lock,
)


class SchemaTransactionLockTests(unittest.TestCase):
    def test_schema_and_operation_locks_belong_to_callers_transaction(self):
        for acquire, args, resource in (
            (acquire_schema_transaction_lock, (), SQL_SCHEMA_LOCK_RESOURCE),
            (
                acquire_operation_transaction_lock,
                ("operation-1",),
                "OSTV:operation:operation-1",
            ),
        ):
            with self.subTest(resource=resource):
                cursor = Mock(spec=["execute", "fetchone"])
                cursor.fetchone.return_value = (0,)
                acquire(cursor, *args)
                cursor.execute.assert_called_once()
                query, captured = cursor.execute.call_args.args
                self.assertIn("sys.sp_getapplock", query)
                self.assertIn("@LockMode=N'Exclusive'", query)
                self.assertIn("@LockOwner=N'Transaction'", query)
                self.assertNotIn("COMMIT", query.upper())
                self.assertEqual(captured, resource)
                cursor.fetchone.assert_called_once_with()

    def test_lock_granted_after_waiting_is_accepted(self):
        # sp_getapplock returns 1 when the lock is granted after waiting.
        for acquire, args in (
            (acquire_schema_transaction_lock, ()),
            (acquire_operation_transaction_lock, ("operation-1",)),
        ):
            with self.subTest(acquire=acquire.__name__):
                cursor = Mock(spec=["execute", "fetchone"])
                cursor.fetchone.return_value = (1,)
                acquire(cursor, *args)

    def test_missing_or_rejected_lock_results_fail_closed(self):
        for acquire, args in (
            (acquire_schema_transaction_lock, ()),
            (acquire_operation_transaction_lock, ("operation-1",)),
        ):
            for result in (None, (-1,), (-2,), (-3,), (-999,)):
                with self.subTest(acquire=acquire.__name__, result=result):
                    cursor = Mock(spec=["execute", "fetchone"])
                    cursor.fetchone.return_value = result
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        acquire(cursor, *args)
                    self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)

    def test_a_refused_operation_lock_tells_the_user_to_reconnect(self):
        # G2 (user decision): the marker-lookup lock failure is shown to the user
        # as the disconnected-state message, so it says what to do. The error
        # class, code and flags are unchanged (non-retryable LOCKED).
        for result in (None, (-1,), (-2,), (-3,), (-999,)):
            with self.subTest(result=result):
                cursor = Mock(spec=["execute", "fetchone"])
                cursor.fetchone.return_value = result
                with self.assertRaises(SqlInfrastructureError) as raised:
                    acquire_operation_transaction_lock(cursor, "operation-1")
                error = raised.exception
                self.assertEqual(
                    str(error),
                    "Another session is resolving the same SQL operation. Reconnect to the database to finish resolving it.",
                )
                self.assertEqual(error.details.user_message, str(error))
                self.assertIn("reconnect", str(error).lower())
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

    def test_the_other_lock_messages_are_unchanged(self):
        # Control for G2: only the operation lock message gained the guidance.
        cursor = Mock(spec=["execute", "fetchone", "fetchall"])
        cursor.fetchone.return_value = (-1,)
        with self.assertRaises(SqlInfrastructureError) as schema:
            acquire_schema_transaction_lock(cursor)
        self.assertEqual(
            str(schema.exception),
            "Another client is initializing this database schema.",
        )
        cursor.fetchall.return_value = [(0, -1)]
        with self.assertRaises(SqlInfrastructureError) as resource:
            acquire_resource_transaction_locks(
                cursor, ((ResourceRef("takeoff", "1", 1), "Exclusive"),)
            )
        self.assertEqual(
            str(resource.exception),
            "Another session is changing the same SQL resource.",
        )


class ResourceTransactionLockTests(unittest.TestCase):
    def setUp(self):
        self.resources = (
            (ResourceRef("takeoffs_collection", "8", 8), "Shared"),
            (ResourceRef("takeoff", "19", 8), "Exclusive"),
        )

    def test_resources_use_one_ordered_request_without_committing(self):
        cursor = Mock(spec=["execute", "fetchall"])
        cursor.fetchall.return_value = [(0, 0), (1, 1)]
        acquire_resource_transaction_locks(cursor, self.resources)
        cursor.execute.assert_called_once()
        query, payload = cursor.execute.call_args.args
        self.assertIn("@LockOwner=N'Transaction'", query)
        self.assertIn("ORDER BY [Ordinal]", query)
        self.assertNotIn("COMMIT", query.upper())
        self.assertEqual(
            json.loads(payload),
            [
                {
                    "ordinal": 0,
                    "resource": "OSTV:takeoffs_collection:8",
                    "mode": "Shared",
                },
                {"ordinal": 1, "resource": "OSTV:takeoff:19", "mode": "Exclusive"},
            ],
        )

    def test_invalid_mode_is_rejected_before_any_query(self):
        cursor = Mock(spec=["execute", "fetchall"])
        for mode in ("invalid", "shared", ""):
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):
                    acquire_resource_transaction_locks(
                        cursor, (self.resources[0], (self.resources[1][0], mode))
                    )
        cursor.execute.assert_not_called()

    def test_partial_and_failed_result_sets_cannot_count_as_success(self):
        for rows in (
            [],
            [(0, 0)],
            [(0, 0), (1, -1)],
            [(0, -1), (1, 0)],
            [(0, 0), (1, 0), (2, 0)],
        ):
            with self.subTest(rows=rows):
                cursor = Mock(spec=["execute", "fetchall"])
                cursor.fetchall.return_value = rows
                with self.assertRaises(SqlInfrastructureError) as raised:
                    acquire_resource_transaction_locks(cursor, self.resources)
                self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)


import pyodbc  # noqa: E402
from ost_visualizer.domain.entities.database_descriptor import (  # noqa: E402
    SqlServerDatabaseLocation,
)
from ost_visualizer.infrastructure.sql.connection_manager import (  # noqa: E402
    SqlConnectionRequest,
)
from tests.helpers.sql.strict_sql_fakes import (  # noqa: E402
    Reply,
    StrictSqlServer,
    StrictSqlViolation,
    applock_rules,
)


class StrictApplockSemanticsTests(unittest.TestCase):
    """The lock helpers against the strict `sp_getapplock` model (not Mock cursors)."""

    def setUp(self):
        self.server = StrictSqlServer()
        applock_rules(self.server)
        self.manager = self.server.manager()
        self.request = SqlConnectionRequest(
            SqlServerDatabaseLocation(server="localhost", database="TEST")
        )

    def _locked(self, call, *, autocommit=False):
        with self.server.patched():
            with self.manager.connection(self.request, autocommit=autocommit) as lease:
                with lease.cursor() as cursor:
                    call(cursor)
                    return lease

    def test_schema_lock_is_exclusive_across_connections_and_freed_by_each_transaction_end(
        self,
    ):
        with self.server.patched():
            with self.manager.connection(self.request) as first:
                with first.cursor() as cursor:
                    acquire_schema_transaction_lock(cursor)
                self.assertEqual(
                    self.server.applocks.holders(SQL_SCHEMA_LOCK_RESOURCE), [1]
                )
                with self.manager.connection(self.request) as second:
                    with second.cursor() as cursor:
                        with self.assertRaises(SqlInfrastructureError) as raised:
                            acquire_schema_transaction_lock(cursor)
                    self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
                first.rollback()
                self.assertEqual(
                    self.server.applocks.holders(SQL_SCHEMA_LOCK_RESOURCE), []
                )
                with self.manager.connection(self.request) as third:
                    with third.cursor() as cursor:
                        acquire_schema_transaction_lock(cursor)
                    third.commit()
                self.assertEqual(
                    self.server.applocks.holders(SQL_SCHEMA_LOCK_RESOURCE), []
                )

    def test_operation_lock_serialises_two_sessions_resolving_the_same_operation(self):
        with self.server.patched():
            with self.manager.connection(self.request) as first:
                with first.cursor() as cursor:
                    acquire_operation_transaction_lock(cursor, "op-1")
                with self.manager.connection(self.request) as other:
                    with other.cursor() as cursor:
                        # a different operation is independent
                        acquire_operation_transaction_lock(cursor, "op-2")
                        with self.assertRaises(SqlInfrastructureError):
                            acquire_operation_transaction_lock(cursor, "op-1")

    def test_transaction_owned_locks_require_a_transaction(self):
        with self.assertRaisesRegex(StrictSqlViolation, "autocommit"):
            self._locked(acquire_schema_transaction_lock, autocommit=True)
        with self.assertRaisesRegex(StrictSqlViolation, "autocommit"):
            self._locked(
                lambda cursor: acquire_resource_transaction_locks(
                    cursor, ((ResourceRef("takeoff", "1", 1), "Exclusive"),)
                ),
                autocommit=True,
            )

    def test_resource_batch_stops_at_the_first_refused_lock_and_keeps_none_after_rollback(
        self,
    ):
        resources = (
            (ResourceRef("bid", "3", 3), "Shared"),
            (ResourceRef("takeoff", "10", 3), "Exclusive"),
            (ResourceRef("takeoff", "11", 3), "Exclusive"),
        )
        with self.server.patched():
            holder = self.server.connect("holder", autocommit=False)
            self.server.applocks.acquire(holder, "OSTV:takeoff:10", "Exclusive")
            with self.manager.connection(self.request) as lease:
                with lease.cursor() as cursor:
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        acquire_resource_transaction_locks(cursor, resources)
                self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
                lease.rollback()
        mine = [
            (resource, code)
            for number, resource, _mode, code in self.server.applocks.log
            if number != holder.number
        ]
        # the batch stops at the refusal: takeoff 11 is never attempted
        self.assertEqual(mine, [("OSTV:bid:3", 0), ("OSTV:takeoff:10", -1)])
        self.assertEqual(self.server.applocks.holders("OSTV:bid:3"), [])

    def test_shared_locks_coexist_but_conflict_with_exclusive_requests(self):
        def lock(mode):
            def call(cursor):
                acquire_resource_transaction_locks(
                    cursor, ((ResourceRef("bid", "3", 3), mode),)
                )

            return call

        with self.server.patched():
            with self.manager.connection(self.request) as first:
                with first.cursor() as cursor:
                    lock("Shared")(cursor)
                with self.manager.connection(self.request) as second:
                    with second.cursor() as cursor:
                        lock("Shared")(cursor)
                        with self.assertRaises(SqlInfrastructureError):
                            lock("Exclusive")(cursor)
        self.assertEqual(self.server.applocks.holders("OSTV:bid:3"), [])

    def test_empty_resource_set_is_a_valid_complete_batch(self):
        self._locked(lambda cursor: acquire_resource_transaction_locks(cursor, ()))
        self.assertEqual(len(self.server.statements(1)), 1)
