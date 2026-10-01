import logging
import unittest
from contextlib import contextmanager
import pyodbc
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from tests.helpers.mdb.operations import (
    _RecordingConnection,
    _RecordingCursor,
    _RecordingSchema,
    _RecordingTakeoffOps,
)


class BulkWriteHelpersPersistenceTests(unittest.TestCase):
    def test_takeoff_bulk_uid_normalization_deduplicates_in_order(self):
        ops = _RecordingTakeoffOps()
        self.assertEqual(
            ops._normalize_int_uids(["2", 1, "2", "003"], "takeoff"),
            [2, 1, 3],
        )
        self.assertEqual(ops._normalize_int_uids([], "takeoff"), [])
        self.assertEqual(ops._normalize_int_uids(iter(("5", 5, 6)), "takeoff"), [5, 6])
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(["1", "bad"], "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(["1", None], "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids("123", "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(b"123", "takeoff")
        with self.assertRaises(ValueError):
            ops._normalize_int_uids(None, "takeoff")

    def test_access_chunks_split_on_exact_boundaries_and_reject_bad_size(self):
        ops = _RecordingTakeoffOps()
        self.assertEqual(list(ops._iter_access_chunks([], 2)), [])
        self.assertEqual(list(ops._iter_access_chunks([1, 2], 2)), [[1, 2]])
        self.assertEqual(
            list(ops._iter_access_chunks([1, 2, 3, 4, 5], 2)),
            [[1, 2], [3, 4], [5]],
        )
        for bad_size in (0, -1):
            with self.subTest(chunk_size=bad_size):
                with self.assertRaises(ValueError):
                    list(ops._iter_access_chunks([1], bad_size))

    def test_uid_where_clause_uses_equality_for_one_uid_and_in_for_many(self):
        self.assertEqual(
            AccessBulkWriteMixin._uid_where_clause("UID", [7]), ("[UID]=?", [7])
        )
        self.assertEqual(
            AccessBulkWriteMixin._uid_where_clause("ParentUID", [7, 8, 9]),
            ("[ParentUID] IN (?,?,?)", [7, 8, 9]),
        )

    def test_chunked_uid_update_and_delete_bind_every_uid_once_per_chunk(self):
        ops = _RecordingTakeoffOps()
        cursor = _RecordingConnection(ops).cursor()
        ops._execute_uid_in_update_chunks(
            cursor,
            "BidTakeoffs",
            "UID",
            {"BidAreaUID": None, "Name": "n"},
            [1, 2, 3],
            2,
        )
        ops._execute_uid_in_delete_chunks(cursor, "BidTakeoffs", "UID", [4, 5, 6], 2)
        self.assertEqual(
            ops.executions,
            [
                (
                    "UPDATE [BidTakeoffs] SET [BidAreaUID]=?, [Name]=? "
                    "WHERE [UID] IN (?,?)",
                    (None, "n", 1, 2),
                ),
                (
                    "UPDATE [BidTakeoffs] SET [BidAreaUID]=?, [Name]=? WHERE [UID]=?",
                    (None, "n", 3),
                ),
                ("DELETE FROM [BidTakeoffs] WHERE [UID] IN (?,?)", (4, 5)),
                ("DELETE FROM [BidTakeoffs] WHERE [UID]=?", (6,)),
            ],
        )

    def test_chunked_uid_update_and_delete_skip_empty_uids_and_reject_empty_values(
        self,
    ):
        ops = _RecordingTakeoffOps()
        cursor = _RecordingConnection(ops).cursor()
        ops._execute_uid_in_update_chunks(cursor, "BidTakeoffs", "UID", {"A": 1}, [])
        ops._execute_uid_in_update_chunks(cursor, "BidTakeoffs", "UID", {}, [])
        ops._execute_uid_in_delete_chunks(cursor, "BidTakeoffs", "UID", [])
        self.assertEqual(ops.executions, [])
        with self.assertRaises(ValueError):
            ops._execute_uid_in_update_chunks(cursor, "BidTakeoffs", "UID", {}, [1])
        self.assertEqual(ops.executions, [])

    def test_correlation_uids_must_be_present_and_unique(self):
        AccessBulkWriteMixin._require_unique_correlation_uids(["a", 1, "2"], "takeoff")
        for bad in (["a", "a"], ["1", 1], ["a", None], ["a", ""], [""]):
            with self.subTest(uids=bad):
                with self.assertRaises(ValueError):
                    AccessBulkWriteMixin._require_unique_correlation_uids(
                        bad, "takeoff"
                    )
