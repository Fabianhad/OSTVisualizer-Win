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


class ConditionFolderOperationsPersistenceTests(unittest.TestCase):
    def test_delete_condition_folder_refuses_folder_used_by_conditions(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (1, 1, 'Used')"
        )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidConditionFolderUID) VALUES (10, 1)"
        )
        with self.assertLogs("test", level="WARNING"):
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"])
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            1,
        )

    def test_delete_condition_folder_allows_unused_folder(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                BidConditionFolderUID INTEGER REFERENCES BidConditionFolders(UID)
            )
            """
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (1, 1, 'Unused')"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            0,
        )

    def test_delete_condition_folder_reparents_surviving_child_to_root(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?, ?)",
            ((1, "Parent", None), (2, "Child", 1)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(2, None)],
        )

    def test_insert_condition_folder_rejects_missing_or_cross_bid_parent(self):
        for parent_rows in ((), ((7, 2),)):
            with self.subTest(parent_rows=parent_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute(
                    "CREATE TABLE BidConditionFolders ("
                    "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
                    "Name TEXT, ExpandState INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders "
                    "(UID, BidUID, Name) VALUES (?, ?, 'Other')",
                    parent_rows,
                )
                self.assertIsNone(
                    _SqliteDuplicateOps(conn).insert_condition_folder(
                        "malformed.mdb", "1", "Child", "7"
                    )
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, BidUID, ParentUID FROM BidConditionFolders "
                        "WHERE BidUID=1"
                    ).fetchall(),
                    [],
                )

    def test_insert_condition_folder_accepts_same_bid_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, ExpandState INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) "
            "VALUES (7, 1, 'Parent')"
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "valid.mdb", "1", "Child", "7"
            ),
            "8",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, ParentUID FROM BidConditionFolders " "WHERE UID=8"
            ).fetchone(),
            (8, 1, 7),
        )

    def test_insert_condition_folder_rejects_parent_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ExpandState INTEGER)"
        )
        conn.execute("INSERT INTO BidConditionFolders VALUES (7, 1, 'Parent', -1)")
        self.assertIsNone(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "legacy.mdb", "1", "Child", "7"
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(7, 1, "Parent")],
        )
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "legacy.mdb", "1", "Root", None
            ),
            "8",
        )

    def test_condition_folder_insert_reserves_dangling_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, ExpandState INTEGER)"
        )
        conn.execute("INSERT INTO BidConditionFolders VALUES (7, 1, 8, 'Orphan', -1)")
        self.assertEqual(
            _SqliteDuplicateOps(conn).insert_condition_folder(
                "malformed.mdb", "1", "Unrelated", None
            ),
            "9",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(7, 8), (9, None)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidConditionFolders AS child "
                "INNER JOIN BidConditionFolders AS parent "
                "ON child.ParentUID=parent.UID"
            ).fetchone()[0],
            0,
        )
