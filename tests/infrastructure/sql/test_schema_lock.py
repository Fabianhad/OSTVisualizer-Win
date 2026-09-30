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
                cursor = Mock()
                cursor.fetchone.return_value = (0,)
                acquire(cursor, *args)
                cursor.execute.assert_called_once()
                query, captured = cursor.execute.call_args.args
                self.assertIn("@LockOwner=N'Transaction'", query)
                self.assertEqual(captured, resource)
                cursor.commit.assert_not_called()

    def test_missing_or_rejected_lock_results_fail_closed(self):
        for acquire, args in (
            (acquire_schema_transaction_lock, ()),
            (acquire_operation_transaction_lock, ("operation-1",)),
        ):
            for result in (None, (-1,), (-3,)):
                with self.subTest(acquire=acquire.__name__, result=result):
                    cursor = Mock()
                    cursor.fetchone.return_value = result
                    with self.assertRaises(SqlInfrastructureError) as raised:
                        acquire(cursor, *args)
                    self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)


class ResourceTransactionLockTests(unittest.TestCase):
    def setUp(self):
        self.resources = (
            (ResourceRef("takeoffs_collection", "8", 8), "Shared"),
            (ResourceRef("takeoff", "19", 8), "Exclusive"),
        )

    def test_resources_use_one_ordered_request_without_committing(self):
        cursor = Mock()
        cursor.fetchall.return_value = [(0, 0), (1, 1)]
        acquire_resource_transaction_locks(cursor, self.resources)
        cursor.execute.assert_called_once()
        query, payload = cursor.execute.call_args.args
        self.assertIn("@LockOwner=N'Transaction'", query)
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
        cursor.commit.assert_not_called()

    def test_invalid_mode_is_rejected_before_any_query(self):
        cursor = Mock()
        with self.assertRaises(ValueError):
            acquire_resource_transaction_locks(
                cursor, ((self.resources[0][0], "invalid"),)
            )
        cursor.execute.assert_not_called()

    def test_partial_and_failed_result_sets_cannot_count_as_success(self):
        for rows in ([], [(0, 0)], [(0, 0), (1, -1)]):
            with self.subTest(rows=rows):
                cursor = Mock()
                cursor.fetchall.return_value = rows
                with self.assertRaises(SqlInfrastructureError) as raised:
                    acquire_resource_transaction_locks(cursor, self.resources)
                self.assertEqual(raised.exception.details.code, SqlErrorCode.LOCKED)
