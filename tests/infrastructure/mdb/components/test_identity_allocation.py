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
