import logging
import unittest
from contextlib import contextmanager
import pyodbc
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    ACCESS_BULK_CHUNK_SIZE,
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
            (
                ["a", "a"],
                "New takeoff correlation UID a must be present and unique within one save.",
            ),
            (
                [None],
                "New takeoff correlation UID <missing> must be present and unique within one save.",
            ),
            (
                [""],
                "New takeoff correlation UID <missing> must be present and unique within one save.",
            ),
            (
                ["x", 7, "7"],
                "New takeoff correlation UID 7 must be present and unique within one save.",
            ),
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
        self.assertIs(
            ops._is_access_resource_exceeded(pyodbc.Error("HY001", "x")), True
        )
        self.assertIs(
            ops._is_access_resource_exceeded(
                pyodbc.Error("42000", "System resource exceeded.")
            ),
            True,
        )
        self.assertIs(
            ops._is_access_resource_exceeded(
                pyodbc.Error("HY000", "System resource exceeded")
            ),
            True,
        )
        self.assertIs(
            ops._is_access_resource_exceeded(pyodbc.Error("HYT00", "timeout")), False
        )
        self.assertIs(ops._is_access_resource_exceeded(RuntimeError("HY001")), False)
        self.assertIs(
            ops._is_access_resource_exceeded(RuntimeError("System resource exceeded")),
            False,
        )

    def test_the_resource_message_is_found_in_the_error_text_even_without_arguments(
        self,
    ):
        class Quirky(pyodbc.Error):
            def __str__(self):
                return "[HY001] [Microsoft] System resource exceeded"

        self.assertIs(
            _RecordingTakeoffOps()._is_access_resource_exceeded(Quirky()), True
        )

    def test_bad_uid_collections_and_values_are_refused_with_the_label_and_the_cause(
        self,
    ):
        ops = _RecordingTakeoffOps()
        for bad in ("123", b"123", None):
            with self.subTest(collection=bad):
                with self.assertRaises(ValueError) as caught:
                    ops._normalize_int_uids(bad, "takeoff")
                self.assertEqual(
                    str(caught.exception), f"Invalid takeoff UID collection: {bad!r}"
                )
        with self.assertRaises(ValueError) as caught:
            ops._normalize_int_uids(["1", "bad"], "page")
        self.assertEqual(str(caught.exception), "Invalid page UID: 'bad'")
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        with self.assertRaises(ValueError) as caught:
            ops._normalize_int_uids([None], "page")
        self.assertEqual(str(caught.exception), "Invalid page UID: None")
        self.assertIsInstance(caught.exception.__cause__, TypeError)

    def test_a_chunked_update_without_values_is_refused_by_name_and_touches_nothing(
        self,
    ):
        ops = _RecordingTakeoffOps()
        cursor = _RecordingConnection(ops).cursor()
        with self.assertRaisesRegex(
            ValueError, r"^No values supplied for chunked UID update\.$"
        ):
            ops._execute_uid_in_update_chunks(cursor, "BidTakeoffs", "UID", {}, [1])
        self.assertEqual(ops.executions, [])


class BulkWriteDefaultChunkingTests(unittest.TestCase):
    def test_default_chunking_bounds_every_statement_and_keeps_the_uid_order(self):
        # Two full chunks and a final single uid: equality for the last chunk,
        # IN for the others, every uid bound exactly once and in the given order.
        size = ACCESS_BULK_CHUNK_SIZE
        self.assertEqual(size, BID_OWNED_IDENTITY_QUERY_CHUNK_SIZE)
        uids = list(range(500, 500 + 2 * size + 1))
        chunks = [uids[:size], uids[size : 2 * size], uids[2 * size :]]
        self.assertEqual([len(chunk) for chunk in chunks], [size, size, 1])
        in_clause = "IN (" + ",".join("?" * size) + ")"
        update_in = f"UPDATE [T] SET [A]=?, [B]=? WHERE [UID] {in_clause}"
        update_one = "UPDATE [T] SET [A]=?, [B]=? WHERE [UID]=?"
        delete_in = f"DELETE FROM [T] WHERE [UID] {in_clause}"
        ops = _RecordingTakeoffOps()
        cursor = _RecordingConnection(ops).cursor()
        ops._execute_uid_in_update_chunks(cursor, "T", "UID", {"A": 7, "B": None}, uids)
        ops._execute_uid_in_delete_chunks(cursor, "T", "UID", uids)
        self.assertEqual(
            ops.executions,
            [
                (update_in, (7, None, *chunks[0])),
                (update_in, (7, None, *chunks[1])),
                (update_one, (7, None, *chunks[2])),
                (delete_in, tuple(chunks[0])),
                (delete_in, tuple(chunks[1])),
                ("DELETE FROM [T] WHERE [UID]=?", tuple(chunks[2])),
            ],
        )

    def test_the_default_chunk_size_is_the_one_the_iterator_uses(self):
        ops = _RecordingTakeoffOps()
        size = ACCESS_BULK_CHUNK_SIZE
        chunks = list(ops._iter_access_chunks(list(range(size + 1))))
        self.assertEqual([len(chunk) for chunk in chunks], [size, 1])

    def test_resource_exhaustion_is_found_when_the_error_carries_non_text_arguments(
        self,
    ):
        ops = _RecordingTakeoffOps()
        self.assertIs(
            ops._is_access_resource_exceeded(pyodbc.Error(-1305, "[HY001] memory")),
            True,
        )
        self.assertIs(
            ops._is_access_resource_exceeded(
                pyodbc.Error(42, "System resource exceeded")
            ),
            True,
        )
        self.assertIs(ops._is_access_resource_exceeded(pyodbc.Error(42, 7)), False)


class BulkWriteRealAccessTests(unittest.TestCase):
    """Real Access: the chunked UPDATE/DELETE helpers bind NULL and Long uids."""

    @staticmethod
    def _exercise_real_access():
        import tempfile
        from pathlib import Path
        import tests.helpers.mdb.schema_support as access

        class Spy:
            def __init__(self, cursor):
                self._cursor = cursor
                self.calls = []

            def execute(self, sql, *params):
                self.calls.append((sql, params))
                return self._cursor.execute(sql, *params)

        def expect(actual, expected, label):
            if actual != expected:
                raise AssertionError(f"{label}: {actual!r} != {expected!r}")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "bulk.mdb"
            if not access.DatabaseCreator().create_database(path, "Bulk"):
                raise AssertionError("database creation failed")
            connection = access._connect_mdb(path)
            try:
                cursor = connection.cursor()
                uids = list(range(1000, 1000 + 2 * ACCESS_BULK_CHUNK_SIZE + 1))
                for uid in uids:
                    cursor.execute(
                        "INSERT INTO [BidProjects] ([UID], [Name]) VALUES (?, 'old')",
                        uid,
                    )
                cursor.execute(
                    "INSERT INTO [BidProjects] ([UID], [Name]) VALUES (5000, 'keep')"
                )
                connection.commit()

                def rows():
                    cursor.execute(
                        "SELECT [UID], [Name] FROM [BidProjects] "
                        "WHERE [UID] >= 1000 ORDER BY [UID]"
                    )
                    return [tuple(row) for row in cursor.fetchall()]

                helper = AccessBulkWriteMixin()
                spy = Spy(cursor)
                helper._execute_uid_in_update_chunks(
                    spy, "BidProjects", "UID", {"Name": None}, uids
                )
                connection.commit()
                expect(
                    [len(params) for _sql, params in spy.calls],
                    [1 + ACCESS_BULK_CHUNK_SIZE, 1 + ACCESS_BULK_CHUNK_SIZE, 2],
                    "update parameter counts",
                )
                expect(
                    rows(),
                    [(uid, None) for uid in uids] + [(5000, "keep")],
                    "after update",
                )
                spy = Spy(cursor)
                helper._execute_uid_in_delete_chunks(spy, "BidProjects", "UID", uids)
                connection.commit()
                expect(
                    [len(params) for _sql, params in spy.calls],
                    [ACCESS_BULK_CHUNK_SIZE, ACCESS_BULK_CHUNK_SIZE, 1],
                    "delete parameter counts",
                )
                expect(rows(), [(5000, "keep")], "after delete")
            finally:
                connection.close()

    def test_chunked_update_and_delete_run_on_real_access(self):
        import subprocess
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.components.test_bulk_write_helpers "
            "import BulkWriteRealAccessTests as Tests; "
            "Tests._exercise_real_access()"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class BulkWriteCorrelationUidTests(unittest.TestCase):
    def test_the_first_offender_is_named_and_zero_and_case_are_distinct_values(self):
        check = AccessBulkWriteMixin._require_unique_correlation_uids
        # The scan stops at the first offender: the missing uid is reported, not
        # the later duplicate; the first repeated value, not the later one.
        with self.assertRaisesRegex(ValueError, "correlation UID <missing> must"):
            check([None, "a", "a"], "takeoff")
        with self.assertRaisesRegex(ValueError, "correlation UID 1 must"):
            check([1, 1, 2, 2], "takeoff")
        # 0 is a present value, and string comparison is exact.
        check([0, "A", "a", " a"], "takeoff")


class BulkWriteExplicitSizeTests(unittest.TestCase):
    def test_an_explicit_chunk_size_larger_than_the_default_is_honoured(self):
        uids = list(range(1, 121))
        ops = _RecordingTakeoffOps()
        cursor = _RecordingConnection(ops).cursor()
        ops._execute_uid_in_update_chunks(cursor, "T", "UID", {"A": 1}, uids, 100)
        ops._execute_uid_in_delete_chunks(cursor, "T", "UID", uids, 100)
        self.assertEqual(
            [len(params) for _sql, params in ops.executions], [101, 21, 100, 20]
        )
        self.assertEqual(ops.executions[2][1], tuple(uids[:100]))
        self.assertEqual(ops.executions[3][1], tuple(uids[100:]))

    def test_the_uid_clause_binds_every_uid_however_many_there_are(self):
        uids = list(range(1, 61))
        clause, params = AccessBulkWriteMixin._uid_where_clause("UID", uids)
        self.assertEqual(clause, "[UID] IN (" + ",".join("?" * 60) + ")")
        self.assertEqual(params, uids)
