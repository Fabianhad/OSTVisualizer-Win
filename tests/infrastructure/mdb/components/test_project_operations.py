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


class ProjectOperationsPersistenceTests(unittest.TestCase):
    def test_delete_project_clears_deleted_bid_restore_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, BidProjectUID INTEGER, "
            "OrigBidProjectUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidProjects VALUES (?)", ((1,), (2,)))
        conn.execute("INSERT INTO Bids VALUES (10, 2, 1)")
        conn.execute("INSERT INTO Bids VALUES (11, 1, NULL)")
        self.assertTrue(_SqliteMdbOps(conn).delete_projects("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(10, 2, None), (11, None, None)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects ORDER BY UID").fetchall(),
            [(2,)],
        )

    def test_project_insert_does_not_claim_orphan_bid_project_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, JobName TEXT)"
        )
        conn.execute("INSERT INTO BidProjects VALUES (7, 'Existing')")
        conn.execute("INSERT INTO Bids VALUES (1, 8, 'Orphan')")
        new_uid = _SqliteDuplicateOps(conn).create_project("malformed.mdb", "New")
        self.assertEqual(new_uid, "9")
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            [(7, "Existing"), (9, "New")],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM Bids AS bid "
                "INNER JOIN BidProjects AS project "
                "ON bid.BidProjectUID=project.UID"
            ).fetchone()[0],
            0,
        )

    def test_project_rename_updates_only_the_target_project(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)", ((7, "First"), (8, "Second"))
        )
        self.assertTrue(_SqliteMdbOps(conn).rename_project("bid.mdb", "7", "Renamed"))
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            [(7, "Renamed"), (8, "Second")],
        )

    def test_project_rename_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO BidProjects VALUES (7, ?)",
            (("First",), ("Conflicting",)),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).rename_project(
                    "malformed.mdb", "7", "Unexpected mutation"
                )
            )
        self.assertIn("BidProjects contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidProjects ORDER BY rowid").fetchall(),
            [("First",), ("Conflicting",)],
        )

    def test_move_bid_rejects_missing_project_owner_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (11, NULL, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project("malformed.mdb", ["11"], "99")
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertIsNone(
            conn.execute("SELECT BidProjectUID FROM Bids WHERE UID=11").fetchone()[0]
        )

    def test_move_bid_rejects_missing_restore_project_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)", ((1, "Deleted"), (2, "Active"))
        )
        conn.execute("INSERT INTO Bids VALUES (11, 2, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project(
                    "malformed.mdb", ["11"], "1", "99"
                )
            )
        self.assertIn("BidProjects has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT BidProjectUID, OrigBidProjectUID FROM Bids WHERE UID=11"
            ).fetchone(),
            (2, None),
        )

    def test_move_bids_rejects_missing_batch_member_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)", ((1, "Source"), (2, "Target"))
        )
        conn.execute("INSERT INTO Bids VALUES (11, 1, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).move_bids_to_project(
                    "malformed.mdb", ["11", "99"], "2"
                )
            )
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT BidProjectUID FROM Bids WHERE UID=11").fetchone()[0],
            1,
        )

    def test_move_bids_assigns_project_and_restore_reference_to_every_batch_member(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidProjects (UID INTEGER, Name TEXT)")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidProjects VALUES (?, ?)",
            ((1, "Source"), (2, "Target"), (3, "Restore")),
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, NULL)", ((11, 1), (12, 1), (13, 1))
        )
        ops = _SqliteMdbOps(conn)
        self.assertTrue(ops.move_bids_to_project("bid.mdb", ["11", "12"], "2"))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(11, 2, None), (12, 2, None), (13, 1, None)],
        )
        self.assertTrue(ops.move_bids_to_project("bid.mdb", ["11"], "1", "3"))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(11, 1, 3), (12, 2, None), (13, 1, None)],
        )

    def test_orphan_bids_clears_project_and_rejects_duplicate_bid_uid_before_mutation(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, NULL)", ((11, 1), (12, 1), (13, 2))
        )
        ops = _SqliteMdbOps(conn)
        self.assertTrue(ops.orphan_bids("bid.mdb", ["11", "13"]))
        self.assertEqual(
            conn.execute("SELECT UID, BidProjectUID FROM Bids ORDER BY UID").fetchall(),
            [(11, None), (12, 1), (13, None)],
        )
        conn.execute("INSERT INTO Bids VALUES (12, 5, NULL)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(ops.orphan_bids("bid.mdb", ["12"]))
        self.assertIn("Bids contains duplicate UID 12", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID FROM Bids WHERE UID=12 ORDER BY rowid"
            ).fetchall(),
            [(12, 1), (12, 5)],
        )
