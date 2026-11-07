import logging
import sqlite3
import unittest
from tests.helpers.mdb.real_write_contract import RealContractOps, contract_db
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    DuplicateBidOwnedUidError,
)
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


class _StrictPolicyOps(RealContractOps):
    """The strict error policy re-raises what the tolerant one swallows."""

    def _record_caught_mutation_error(self, exc):
        return True


def _project_db(
    *extra,
    bids="UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER",
    projects="UID INTEGER, Name TEXT",
):
    conn = contract_db(
        f"CREATE TABLE Bids ({bids})",
        f"CREATE TABLE BidProjects ({projects})",
    )
    # A table that lacks the UID column simply starts empty.
    for statement in (
        "INSERT INTO BidProjects (UID) VALUES (1)",
        "INSERT INTO BidProjects (UID) VALUES (2)",
        "INSERT INTO Bids (UID) VALUES (10)",
        "INSERT INTO Bids (UID) VALUES (11)",
        *extra,
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    return conn


def _bids(conn, columns="UID, BidProjectUID, OrigBidProjectUID"):
    return conn.execute(f"SELECT {columns} FROM Bids ORDER BY UID").fetchall()


class ProjectOperationContractTests(unittest.TestCase):
    def test_empty_uid_lists_succeed_without_touching_the_database(self):
        ops = RealContractOps(contract_db())
        self.assertIs(ops.move_bids_to_project("x.mdb", [], "1"), True)
        self.assertIs(ops.orphan_bids("x.mdb", []), True)
        self.assertIs(ops.delete_projects("x.mdb", []), True)

    def test_unusable_uid_lists_are_refused_with_the_table_named_when_the_policy_is_strict(
        self,
    ):
        for call, label in (
            (lambda ops: ops.move_bids_to_project("x.mdb", ["x"], "1"), "Bids"),
            (lambda ops: ops.orphan_bids("x.mdb", ["x"]), "Bids"),
            (lambda ops: ops.delete_projects("x.mdb", ["x"]), "BidProjects"),
        ):
            with self.subTest(label=label):
                conn = _project_db()
                with self.assertLogs("test", "WARNING"):
                    self.assertIs(call(RealContractOps(conn)), False)
                with self.assertRaisesRegex(
                    ValueError, "^Invalid " + label + " UID: 'x'$"
                ):
                    call(_StrictPolicyOps(conn))

    def test_move_assigns_the_project_and_the_restore_project(self):
        conn = _project_db()
        ops = RealContractOps(conn)
        self.assertIs(ops.move_bids_to_project("x.mdb", ["10"], "2", "1"), True)
        self.assertEqual(_bids(conn), [(10, 2, 1), (11, None, None)])
        self.assertEqual(ops.skips, [])

    def test_move_without_a_restore_project_leaves_the_restore_column_alone(self):
        conn = _project_db()
        conn.execute("UPDATE Bids SET OrigBidProjectUID = 7")
        ops = RealContractOps(conn)
        self.assertIs(ops.move_bids_to_project("x.mdb", ["10"], "2"), True)
        self.assertEqual(_bids(conn), [(10, 2, 7), (11, None, 7)])
        self.assertEqual(ops.skips, [])

    def test_a_missing_restore_column_is_reported_only_when_a_restore_project_is_given(
        self,
    ):
        for restore, expected in (
            ("1", [("Bids", "OrigBidProjectUID", "move_bids_to_project")]),
            (None, []),
        ):
            with self.subTest(restore=restore):
                conn = _project_db(bids="UID INTEGER, BidProjectUID INTEGER")
                ops = RealContractOps(conn)
                self.assertIs(
                    ops.move_bids_to_project("x.mdb", ["10"], "2", restore), True
                )
                self.assertEqual(ops.skips, expected)
                self.assertEqual(
                    _bids(conn, "UID, BidProjectUID"), [(10, 2), (11, None)]
                )

    def test_orphaning_clears_the_project_only(self):
        conn = _project_db()
        conn.execute("UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 7")
        self.assertIs(RealContractOps(conn).orphan_bids("x.mdb", ["11"]), True)
        self.assertEqual(_bids(conn), [(10, 1, 7), (11, None, 7)])

    def test_a_project_is_created_with_the_next_uid_and_its_name(self):
        conn = _project_db()
        self.assertEqual(RealContractOps(conn).create_project("x.mdb", "Three"), "3")
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            [(1, None), (2, None), (3, "Three")],
        )

    def test_renaming_changes_the_name_of_the_target_project_only(self):
        conn = _project_db()
        self.assertIs(
            RealContractOps(conn).rename_project("x.mdb", "2", "Renamed"), True
        )
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            [(1, None), (2, "Renamed")],
        )

    def test_deleting_projects_detaches_their_bids_and_restore_references(self):
        conn = _project_db()
        conn.execute(
            "UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 1 WHERE UID = 10"
        )
        conn.execute(
            "UPDATE Bids SET BidProjectUID = 2, OrigBidProjectUID = 1 WHERE UID = 11"
        )
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["1"]), True)
        self.assertEqual(_bids(conn), [(10, None, None), (11, 2, None)])
        self.assertEqual(conn.execute("SELECT UID FROM BidProjects").fetchall(), [(2,)])

    def test_deleting_projects_tolerates_a_bid_table_without_project_columns(self):
        for bids in (
            "UID INTEGER",
            "UID INTEGER, BidProjectUID INTEGER",
            "UID INTEGER, OrigBidProjectUID INTEGER",
        ):
            with self.subTest(bids=bids):
                conn = _project_db(bids=bids)
                self.assertIs(
                    RealContractOps(conn).delete_projects("x.mdb", ["1"]), True
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidProjects").fetchall(), [(2,)]
                )

    def test_deleting_projects_without_a_bid_table_still_deletes_them(self):
        conn = contract_db(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT)",
            "INSERT INTO BidProjects VALUES (1, 'One')",
        )
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["1"]), True)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidProjects").fetchall(), [(0,)]
        )

    def test_a_duplicated_project_uid_blocks_the_delete(self):
        conn = _project_db("INSERT INTO BidProjects (UID) VALUES (2)")
        with self.assertLogs("test", "ERROR"):
            self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2"]), False)
        with self.assertRaises(DuplicateBidOwnedUidError):
            _StrictPolicyOps(conn).delete_projects("x.mdb", ["2"])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidProjects").fetchall(), [(3,)]
        )

    def test_failures_return_the_documented_value_and_follow_the_error_policy(self):
        cases = (
            (
                "move",
                lambda ops: ops.move_bids_to_project("x.mdb", ["10"], "2"),
                False,
                {"bids": "UID INTEGER"},
            ),
            (
                "orphan",
                lambda ops: ops.orphan_bids("x.mdb", ["10"]),
                False,
                {"bids": "UID INTEGER"},
            ),
            (
                "create",
                lambda ops: ops.create_project("x.mdb", "N"),
                None,
                {"projects": "UID INTEGER"},
            ),
            (
                "rename",
                lambda ops: ops.rename_project("x.mdb", "1", "N"),
                False,
                {"projects": "UID INTEGER"},
            ),
            (
                "delete",
                lambda ops: ops.delete_projects("x.mdb", ["1"]),
                False,
                {"projects": "Name TEXT"},
            ),
        )
        for name, call, expected, broken in cases:
            with self.subTest(op=name):
                conn = _project_db(**broken)
                with self.assertLogs("test", "ERROR"):
                    result = call(RealContractOps(conn))
                self.assertIs(result, expected)
                with self.assertRaises(Exception):
                    call(_StrictPolicyOps(conn))

    def test_a_missing_destination_project_blocks_the_move(self):
        conn = _project_db()
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                RealContractOps(conn).move_bids_to_project("x.mdb", ["10"], "99"), False
            )
        self.assertEqual(_bids(conn, "UID, BidProjectUID"), [(10, None), (11, None)])

    def test_each_write_names_the_missing_column_it_needs(self):
        cases = (
            (
                lambda ops: ops.move_bids_to_project("x.mdb", ["10"], "2"),
                {"bids": "UID INTEGER"},
                "BidProjectUID",
            ),
            (
                lambda ops: ops.move_bids_to_project("x.mdb", ["10"], "2"),
                {"bids": "BidProjectUID INTEGER"},
                "UID",
            ),
            (
                lambda ops: ops.orphan_bids("x.mdb", ["10"]),
                {"bids": "UID INTEGER"},
                "BidProjectUID",
            ),
            (
                lambda ops: ops.orphan_bids("x.mdb", ["10"]),
                {"bids": "BidProjectUID INTEGER"},
                "UID",
            ),
            (
                lambda ops: ops.create_project("x.mdb", "N"),
                {"projects": "UID INTEGER"},
                "Name",
            ),
            (
                lambda ops: ops.create_project("x.mdb", "N"),
                {"projects": "Name TEXT"},
                "UID",
            ),
            (
                lambda ops: ops.rename_project("x.mdb", "1", "N"),
                {"projects": "UID INTEGER"},
                "Name",
            ),
            (
                lambda ops: ops.rename_project("x.mdb", "1", "N"),
                {"projects": "Name TEXT"},
                "UID",
            ),
            (
                lambda ops: ops.delete_projects("x.mdb", ["1"]),
                {"projects": "Name TEXT"},
                "UID",
            ),
        )
        for call, kwargs, column in cases:
            with self.subTest(column=column, tables=kwargs):
                conn = _project_db(**kwargs)
                with self.assertRaises(Exception) as caught:
                    call(_StrictPolicyOps(conn))
                self.assertIn(column, str(caught.exception))
                # The guard reports the schema gap itself; a raw database error would mean the
                # write was attempted against a table that cannot take it.
                self.assertNotIsInstance(caught.exception, sqlite3.OperationalError)
