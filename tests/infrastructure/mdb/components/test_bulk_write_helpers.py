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


class BulkWriteHelperContractTests(unittest.TestCase):
    def test_correlation_errors_name_the_label_and_the_offending_uid(self):
        check = AccessBulkWriteMixin._require_unique_correlation_uids
        cases = (
            (["a", "a"], "New takeoff correlation UID a must be present and unique within one save."),
            ([None], "New takeoff correlation UID <missing> must be present and unique within one save."),
            ([""], "New takeoff correlation UID <missing> must be present and unique within one save."),
            (["x", 7, "7"], "New takeoff correlation UID 7 must be present and unique within one save."),
        )
        for values, message in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError) as caught:
                    check(values, "takeoff")
                self.assertEqual(str(caught.exception), message)

    def test_a_chunk_size_of_one_is_allowed_and_zero_is_refused_by_name(self):
        ops = _RecordingTakeoffOps()
        self.assertEqual(list(ops._iter_access_chunks([1, 2], 1)), [[1], [2]])
        for bad_size in (0, -3):
            with self.assertRaisesRegex(ValueError, "^chunk_size must be positive$"):
                list(ops._iter_access_chunks([1], bad_size))

    def test_chunks_are_lists_even_for_tuple_input(self):
        ops = _RecordingTakeoffOps()
        chunks = list(ops._iter_access_chunks((1, 2, 3), 2))
        self.assertEqual(chunks, [[1, 2], [3]])
        for chunk in chunks:
            self.assertIs(type(chunk), list)

    def test_the_uid_clause_hands_back_a_list_of_parameters(self):
        clause, params = AccessBulkWriteMixin._uid_where_clause("UID", (7, 8))
        self.assertEqual((clause, params), ("[UID] IN (?,?)", [7, 8]))
        self.assertIs(type(params), list)
        original = [7, 8]
        _clause, params = AccessBulkWriteMixin._uid_where_clause("UID", original)
        params.append(9)
        self.assertEqual(original, [7, 8])

    def test_only_access_resource_exhaustion_is_recognised_as_such(self):
        ops = _RecordingTakeoffOps()
        self.assertIs(ops._is_access_resource_exceeded(pyodbc.Error("HY001", "x")), True)
        self.assertIs(
            ops._is_access_resource_exceeded(pyodbc.Error("42000", "System resource exceeded.")), True
        )
        self.assertIs(
            ops._is_access_resource_exceeded(pyodbc.Error("HY000", "System resource exceeded")), True
        )
        self.assertIs(ops._is_access_resource_exceeded(pyodbc.Error("HYT00", "timeout")), False)
        self.assertIs(ops._is_access_resource_exceeded(RuntimeError("HY001")), False)
        self.assertIs(
            ops._is_access_resource_exceeded(RuntimeError("System resource exceeded")), False
        )

    def test_the_resource_message_is_found_in_the_error_text_even_without_arguments(self):
        class Quirky(pyodbc.Error):
            def __str__(self):
                return "[HY001] [Microsoft] System resource exceeded"

        self.assertIs(_RecordingTakeoffOps()._is_access_resource_exceeded(Quirky()), True)
