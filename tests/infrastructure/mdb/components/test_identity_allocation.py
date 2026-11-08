import logging
import sqlite3
import unittest
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)


class IdentityAllocationPersistenceTests(unittest.TestCase):
    def test_self_reference_uid_allocation_prevents_late_binding(self):
        for table, reference_column in (
            ("BidPages", "MasterPageUID"),
            ("BidComments", "ParentCommentUID"),
        ):
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    f"CREATE TABLE {table} (UID INTEGER, {reference_column} INTEGER)"
                )
                conn.execute(f"INSERT INTO {table} VALUES (7, 8)")
                ops = _SqliteDuplicateOps(conn)
                self.assertEqual(
                    ops._next_uid_preserving_references(
                        _SqliteCursorWrapper(conn), ops._schema_ref, table
                    ),
                    9,
                )

    def test_uid_allocation_ignores_empty_zero_null_and_lower_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, MasterPageUID INTEGER)")
        ops = _SqliteDuplicateOps(conn)
        cursor = _SqliteCursorWrapper(conn)
        self.assertEqual(
            ops._next_uid_preserving_references(cursor, ops._schema_ref, "BidPages"), 1
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?)", ((3, 0), (4, None), (5, 2))
        )
        self.assertEqual(
            ops._next_uid_preserving_references(cursor, ops._schema_ref, "BidPages"), 6
        )

    def test_bulk_uid_allocation_returns_contiguous_range_past_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, MasterPageUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (7, 12)")
        ops = _SqliteDuplicateOps(conn)
        cursor = _SqliteCursorWrapper(conn)
        self.assertEqual(
            list(
                ops._next_uids_preserving_references(
                    cursor, ops._schema_ref, "BidPages", 3
                )
            ),
            [13, 14, 15],
        )
        for count in (0, -2):
            with self.subTest(count=count):
                self.assertEqual(
                    list(
                        ops._next_uids_preserving_references(
                            cursor, ops._schema_ref, "BidPages", count
                        )
                    ),
                    [],
                )


class IdentityAllocationScopeTests(unittest.TestCase):
    def _alloc(self, conn, table):
        ops = _SqliteDuplicateOps(conn)
        return ops._next_uid_preserving_references(
            _SqliteCursorWrapper(conn), ops._schema_ref, table
        )

    def test_references_that_point_at_other_parent_tables_never_reserve_uids(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER)")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (1, 500)")
        conn.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)")
        conn.execute("INSERT INTO BidTakeoffs VALUES (1, 40)")
        self.assertEqual(self._alloc(conn, "BidPages"), 41)
        self.assertEqual(self._alloc(conn, "BidLayers"), 501)

    def test_dangling_child_references_reserve_the_highest_referenced_uid_plus_one(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("CREATE TABLE BidComments (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("CREATE TABLE BidTexts (UID INTEGER, BidLayerUID INTEGER)")
        conn.executemany("INSERT INTO BidComments VALUES (?, ?)", ((1, 20), (2, 70)))
        conn.execute("INSERT INTO BidTexts VALUES (1, 55)")
        conn.execute("INSERT INTO BidLayers VALUES (10)")
        self.assertEqual(self._alloc(conn, "BidLayers"), 71)

    def test_child_tables_missing_the_reference_column_or_the_table_are_skipped(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (4)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (900)")
        self.assertEqual(self._alloc(conn, "BidLayers"), 5)

    def test_blank_text_references_are_ignored_and_numeric_text_is_honoured(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID)")
        conn.execute("INSERT INTO BidLayers VALUES (4)")
        for stored in ("", "0"):
            conn.execute("DELETE FROM BidConditions")
            conn.execute("INSERT INTO BidConditions VALUES (1, ?)", (stored,))
            with self.subTest(stored=stored):
                self.assertEqual(self._alloc(conn, "BidLayers"), 5)
        conn.execute("DELETE FROM BidConditions")
        conn.execute("INSERT INTO BidConditions VALUES (1, '12')")
        self.assertEqual(self._alloc(conn, "BidLayers"), 13)

    def test_a_bulk_allocation_of_one_returns_one_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, MasterPageUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (2, 6)")
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            list(
                ops._next_uids_preserving_references(
                    _SqliteCursorWrapper(conn), ops._schema_ref, "BidPages", 1
                )
            ),
            [7],
        )


class IdentityAllocationReferenceEdgeTests(unittest.TestCase):
    def _alloc(self, conn, table):
        ops = _SqliteDuplicateOps(conn)
        return ops._next_uid_preserving_references(
            _SqliteCursorWrapper(conn), ops._schema_ref, table
        )

    def test_a_reference_of_one_to_an_empty_parent_table_still_reserves_uid_one(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("CREATE TABLE BidComments (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidComments VALUES (1, 1)")
        self.assertEqual(self._alloc(conn, "BidLayers"), 2)

    def test_a_blank_reference_in_one_child_table_does_not_hide_a_later_dangling_one(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (1, NULL)")
        conn.execute("CREATE TABLE BidZones (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidZones VALUES (1, 60)")
        self.assertEqual(self._alloc(conn, "BidLayers"), 61)

    def test_an_empty_child_table_does_not_hide_a_later_dangling_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("CREATE TABLE BidZones (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidZones VALUES (1, 60)")
        self.assertEqual(self._alloc(conn, "BidLayers"), 61)

    def test_every_blank_spelling_of_a_reference_is_skipped_not_just_the_first_table(
        self,
    ):
        for blank in ("''", "0", "'0'", "NULL"):
            with self.subTest(blank=blank):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
                conn.execute("INSERT INTO BidLayers VALUES (3)")
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID)")
                conn.execute(f"INSERT INTO BidConditions VALUES (1, {blank})")
                conn.execute("CREATE TABLE BidZones (UID INTEGER, BidLayerUID)")
                conn.execute("INSERT INTO BidZones VALUES (1, 9)")
                self.assertEqual(self._alloc(conn, "BidLayers"), 10)

    def test_the_relationship_table_has_no_repeated_reference_so_the_dedupe_guard_is_inert(
        self,
    ):
        # _next_uid_preserving_references skips a (child table, child column) it has
        # already queried. That guard (and its checked.add) is only unobservable
        # while the relationship list never repeats a reference for one parent.
        from collections import Counter
        from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
            BID_RELATIONSHIPS,
        )

        counts = Counter(
            (r.parent_table, r.parent_column, r.child_table, r.child_column)
            for r in BID_RELATIONSHIPS
        )
        self.assertEqual([key for key, n in counts.items() if n > 1], [])
        self.assertEqual({r.parent_column for r in BID_RELATIONSHIPS}, {"UID"})


class IdentityAllocationTextUidTests(unittest.TestCase):
    def test_a_uid_column_that_reports_text_still_allocates_the_next_integer(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID)")
        conn.execute("INSERT INTO BidPages VALUES ('5')")
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(
            ops._next_uid_preserving_references(
                _SqliteCursorWrapper(conn), ops._schema_ref, "BidPages"
            ),
            6,
        )


class IdentityAllocationSchemaAndBulkContractTests(unittest.TestCase):
    def test_a_non_positive_bulk_count_allocates_nothing_without_a_database_query(
        self,
    ):
        # The connection has no tables at all, so any allocation query would raise.
        conn = sqlite3.connect(":memory:")
        ops = _SqliteDuplicateOps(conn)
        cursor = _SqliteCursorWrapper(conn)
        for count in (0, -1, -2):
            with self.subTest(count=count):
                result = ops._next_uids_preserving_references(
                    cursor, ops._schema_ref, "BidPages", count
                )
                self.assertEqual(list(result), [])
        with self.assertRaises(sqlite3.OperationalError):
            ops._next_uids_preserving_references(cursor, ops._schema_ref, "BidPages", 1)

    def test_missing_child_tables_are_found_before_their_columns_are_asked_for(self):
        class _StrictSchema(_SqliteSchema):
            """column_exists rejects unknown tables, like the SQL Server schema."""

            def __init__(self, connection):
                super().__init__(connection)
                self.column_checks = []

            def column_exists(self, table_name, column_name):
                if self.optional_table_missing(table_name):
                    raise AssertionError(f"column asked for missing {table_name}")
                self.column_checks.append((table_name, column_name))
                return super().column_exists(table_name, column_name)

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (4)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidLayerUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (1, 30)")
        ops = _SqliteDuplicateOps(conn)
        schema = _StrictSchema(conn)
        self.assertEqual(
            ops._next_uid_preserving_references(
                _SqliteCursorWrapper(conn), schema, "BidLayers"
            ),
            31,
        )
        self.assertEqual(schema.column_checks, [("BidConditions", "BidLayerUID")])
