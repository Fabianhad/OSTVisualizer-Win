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
        conn.executemany("INSERT INTO BidProjects VALUES (?)", ((2,), (3,)))
        conn.execute("INSERT INTO Bids VALUES (10, 3, 2)")
        conn.execute("INSERT INTO Bids VALUES (11, 2, NULL)")
        self.assertTrue(_SqliteMdbOps(conn).delete_projects("bid.mdb", ["2"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(10, 3, None), (11, None, None)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects ORDER BY UID").fetchall(),
            [(3,)],
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
            "UPDATE Bids SET BidProjectUID = 2, OrigBidProjectUID = 2 WHERE UID = 10"
        )
        conn.execute(
            "UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 2 WHERE UID = 11"
        )
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2"]), True)
        self.assertEqual(_bids(conn), [(10, None, None), (11, 1, None)])
        self.assertEqual(conn.execute("SELECT UID FROM BidProjects").fetchall(), [(1,)])

    def test_deleting_projects_tolerates_a_bid_table_without_project_columns(self):
        for bids in (
            "UID INTEGER",
            "UID INTEGER, BidProjectUID INTEGER",
            "UID INTEGER, OrigBidProjectUID INTEGER",
        ):
            with self.subTest(bids=bids):
                conn = _project_db(bids=bids)
                self.assertIs(
                    RealContractOps(conn).delete_projects("x.mdb", ["2"]), True
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidProjects").fetchall(), [(1,)]
                )

    def test_deleting_projects_without_a_bid_table_still_deletes_them(self):
        conn = contract_db(
            "CREATE TABLE BidProjects (UID INTEGER, Name TEXT)",
            "INSERT INTO BidProjects VALUES (2, 'Two')",
        )
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2"]), True)
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


class _CountingOps(RealContractOps):
    """Counts the connections the operation opens."""

    def __init__(self, connection):
        super().__init__(connection)
        self.opened = 0

    def _connection(self, db_path):
        self.opened += 1
        return super()._connection(db_path)


class ProjectOperationFailurePathTests(unittest.TestCase):
    def test_a_uid_collection_that_cannot_be_read_is_refused_before_a_connection_opens(
        self,
    ):
        for name, call in (
            ("move", lambda ops, uids: ops.move_bids_to_project("x.mdb", uids, "1")),
            ("orphan", lambda ops, uids: ops.orphan_bids("x.mdb", uids)),
            ("delete", lambda ops, uids: ops.delete_projects("x.mdb", uids)),
        ):
            for bad in (5, ["1", "bad"]):
                with self.subTest(op=name, uids=bad):
                    conn = _project_db()
                    ops = _CountingOps(conn)
                    with self.assertLogs("test", "WARNING") as logs:
                        self.assertIs(call(ops, bad), False)
                    # A refused request is a warning, not a logged exception, and
                    # never reaches the database.
                    self.assertEqual(ops.opened, 0)
                    self.assertEqual(len(logs.records), 1)
                    self.assertEqual(logs.records[0].levelname, "WARNING")
                    self.assertIsNone(logs.records[0].exc_info)
                    self.assertEqual(
                        conn.execute("SELECT COUNT(*) FROM BidProjects").fetchall(),
                        [(2,)],
                    )
                    with self.assertRaises((TypeError, ValueError)):
                        call(_StrictPolicyOps(conn), bad)

    def test_refusal_and_failure_logs_name_the_operation_the_uids_and_the_database(
        self,
    ):
        broken_bids = {"bids": "UID INTEGER"}
        broken_projects = {"projects": "UID INTEGER"}
        cases = (
            (
                lambda ops: ops.move_bids_to_project("a.mdb", ["10", "10"], "2"),
                broken_bids,
                "Failed to move bids ['10', '10'] to project 2 in a.mdb",
            ),
            (
                lambda ops: ops.orphan_bids("a.mdb", ["10"]),
                broken_bids,
                "Failed to orphan bids ['10'] in a.mdb",
            ),
            (
                lambda ops: ops.create_project("a.mdb", "N"),
                broken_projects,
                "Failed to create project in a.mdb",
            ),
            (
                lambda ops: ops.rename_project("a.mdb", "1", "N"),
                broken_projects,
                "Failed to rename project 1 in a.mdb",
            ),
            (
                lambda ops: ops.delete_projects("a.mdb", ["1", "2"]),
                {"projects": "Name TEXT"},
                "Failed to delete projects ['1', '2'] from a.mdb",
            ),
            (
                lambda ops: ops.move_bids_to_project("a.mdb", ["x"], "2"),
                {},
                "Invalid bid uids passed to move_bids_to_project: ['x']",
            ),
            (
                lambda ops: ops.orphan_bids("a.mdb", ["x"]),
                {},
                "Invalid bid uids passed to orphan_bids: ['x']",
            ),
            (
                lambda ops: ops.delete_projects("a.mdb", ["x"]),
                {},
                "Invalid project uids passed to delete_projects: ['x']",
            ),
        )
        for call, broken, message in cases:
            with self.subTest(message=message):
                with self.assertLogs("test", "WARNING") as logs:
                    call(RealContractOps(_project_db(**broken)))
                self.assertEqual([r.getMessage() for r in logs.records], [message])

    def test_deleting_or_orphaning_a_project_or_bid_that_is_absent_changes_nothing(
        self,
    ):
        conn = _project_db(
            "UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 2",
        )
        before = _bids(conn)
        ops = RealContractOps(conn)
        self.assertIs(ops.delete_projects("x.mdb", ["99"]), True)
        self.assertIs(ops.orphan_bids("x.mdb", ["99"]), True)
        self.assertEqual(_bids(conn), before)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_deleting_several_projects_detaches_and_removes_every_one_of_them(self):
        conn = _project_db(
            "INSERT INTO BidProjects (UID) VALUES (3)",
            "INSERT INTO Bids (UID) VALUES (12)",
            "UPDATE Bids SET BidProjectUID = 2, OrigBidProjectUID = 1 WHERE UID = 10",
            "UPDATE Bids SET BidProjectUID = 3, OrigBidProjectUID = 2 WHERE UID = 11",
            "UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 3 WHERE UID = 12",
        )
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2", "3"]), True)
        # Every deleted project leaves both bid columns; the bystander project 1
        # and the bid that points at it keep their references.
        self.assertEqual(conn.execute("SELECT UID FROM BidProjects").fetchall(), [(1,)])
        self.assertEqual(_bids(conn), [(10, None, 1), (11, None, None), (12, 1, None)])

    def test_characterisation_renaming_an_absent_project_is_a_silent_success(self):
        # Pins current behaviour, not an endorsed contract: unlike
        # move_bids_to_project (which refuses an absent bid), rename_project reports
        # True for an absent project and changes nothing.
        conn = _project_db()
        conn.execute("UPDATE BidProjects SET Name = 'Keep'")
        self.assertIs(
            RealContractOps(conn).rename_project("x.mdb", "99", "Ghost"), True
        )
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            [(1, "Keep"), (2, "Keep")],
        )

    def test_a_batch_mixing_present_and_absent_projects_deletes_the_present_ones(self):
        conn = _project_db("UPDATE Bids SET BidProjectUID = 2 WHERE UID = 11")
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2", "99"]), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects ORDER BY UID").fetchall(),
            [(1,)],
        )
        self.assertEqual(_bids(conn, "UID, BidProjectUID"), [(10, None), (11, None)])


class ProjectOperationsRealAccessTests(unittest.TestCase):
    """Real Access: NULL/Long parameter binding, batching and transaction rollback.

    The sqlite stand-ins cannot show how the ACE driver binds NULL and text uids
    against Long columns or that a failed delete rolls its detach updates back.
    """

    @staticmethod
    def _exercise_real_access():
        import tempfile
        from pathlib import Path
        import tests.helpers.mdb.schema_support as access
        from ost_visualizer.infrastructure.mdb.connection_manager import (
            MdbConnectionManager,
        )
        from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter

        class FailingDeleteWriter(MdbWriter):
            def _execute_uid_in_delete_chunks(self, *args, **kwargs):
                raise RuntimeError("injected failure after the detach updates")

        def expect(actual, expected, label):
            if actual != expected:
                raise AssertionError(f"{label}: {actual!r} != {expected!r}")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "projects.mdb"
            if not access.DatabaseCreator().create_database(path, "Projects"):
                raise AssertionError("database creation failed")
            source = str(path)
            manager = MdbConnectionManager()
            writer = MdbWriter(manager)

            def execute_all(target, statements):
                connection = access._connect_mdb(target)
                try:
                    cursor = connection.cursor()
                    for sql, *params in statements:
                        cursor.execute(sql, *params)
                    connection.commit()
                finally:
                    connection.close()

            def read():
                manager.close_database(source)
                connection = access._connect_mdb(path)
                try:
                    cursor = connection.cursor()
                    cursor.execute("SELECT [UID], [Name] FROM [BidProjects]")
                    projects = {int(r[0]): r[1] for r in cursor.fetchall()}
                    cursor.execute(
                        "SELECT [UID], [BidProjectUID], [OrigBidProjectUID] FROM [Bids]"
                    )
                    bids = {
                        int(r[0]): tuple(None if v is None else int(v) for v in r[1:])
                        for r in cursor.fetchall()
                    }
                finally:
                    connection.close()
                return projects, bids

            try:
                # The new file already holds the system project(s).
                system = read()[0]
                pa = writer.create_project(source, "Alpha")
                pb = writer.create_project(source, "Beta")
                pc = writer.create_project(source, "Gamma")
                for value in (pa, pb, pc):
                    if value is None:
                        raise AssertionError("project creation failed")
                a, b, c = int(pa), int(pb), int(pc)
                expect(len({a, b, c}), 3, "distinct project uids")
                connection = access._connect_mdb(path)
                try:
                    cursor = connection.cursor()
                    for uid, project, orig in (
                        (101, a, None),
                        (102, a, b),
                        (103, b, a),
                        (104, c, None),
                    ):
                        cursor.execute(
                            "INSERT INTO [Bids] ([UID], [JobName], "
                            "[BidProjectUID], [OrigBidProjectUID]) "
                            "VALUES (?, 'bid', ?, ?)",
                            uid,
                            project,
                            orig,
                        )
                    connection.commit()
                finally:
                    connection.close()
                seeded = {101: (a, None), 102: (a, b), 103: (b, a), 104: (c, None)}
                names = system | {a: "Alpha", b: "Beta", c: "Gamma"}
                expect(read(), (names, seeded), "seed")

                # Rename touches only the target project.
                expect(writer.rename_project(source, pa, "Renamed"), True, "rename")
                renamed = names | {a: "Renamed"}
                # Characterisation: renaming an absent project is a silent no-op.
                expect(writer.rename_project(source, "999", "Ghost"), True, "absent")
                expect(read(), (renamed, seeded), "after rename")

                # A failed delete rolls the already executed detach updates back.
                failing = FailingDeleteWriter(manager)
                expect(failing.delete_projects(source, [pb]), False, "failed delete")
                expect(read(), (renamed, seeded), "after rolled back delete")

                # A real delete detaches only the bids that reference the project
                # (either column) and never deletes a bid row.
                expect(writer.delete_projects(source, [pb]), True, "delete")
                without_beta = {u: n for u, n in renamed.items() if u != b}
                detached = {
                    101: (a, None),
                    102: (a, None),
                    103: (None, a),
                    104: (c, None),
                }
                expect(
                    read(),
                    (without_beta, detached),
                    "after delete",
                )
                # Deleting or orphaning something absent is a successful no-op.
                expect(writer.delete_projects(source, ["999"]), True, "absent delete")
                expect(writer.orphan_bids(source, ["999"]), True, "absent orphan")
                expect(read(), (without_beta, detached), "after absent")

                # Moving binds the project and the restore project to every bid in
                # the batch and leaves every other bid alone.
                expect(
                    writer.move_bids_to_project(source, ["101", "104"], pc, pa),
                    True,
                    "move",
                )
                moved = detached | {101: (c, a), 104: (c, a)}
                expect(read()[1], moved, "after move")
                expect(
                    writer.move_bids_to_project(source, ["102"], "999"),
                    False,
                    "move to absent project",
                )
                expect(
                    writer.move_bids_to_project(source, ["102", "998"], pc),
                    False,
                    "move absent bid",
                )
                expect(read()[1], moved, "after refused moves")
                expect(writer.orphan_bids(source, ["101"]), True, "orphan")
                expect(read()[1], moved | {101: (None, a)}, "after orphan")

                # Deleting several projects at once detaches and removes every one
                # of them (both columns) and leaves the bystander project and bid.
                pd = int(writer.create_project(source, "Delta"))
                pe = int(writer.create_project(source, "Epsilon"))
                execute_all(
                    path,
                    [
                        (
                            "INSERT INTO [Bids] ([UID], [JobName], [BidProjectUID], "
                            "[OrigBidProjectUID]) VALUES (?, 'multi', ?, ?)",
                            uid,
                            project,
                            orig,
                        )
                        for uid, project, orig in (
                            (201, pd, pe),
                            (202, pe, pd),
                            (203, pd, a),
                            (204, a, pe),
                            (205, a, c),
                        )
                    ],
                )
                before_multi = read()
                expect(
                    {u: before_multi[1][u] for u in range(201, 206)},
                    {
                        201: (pd, pe),
                        202: (pe, pd),
                        203: (pd, a),
                        204: (a, pe),
                        205: (a, c),
                    },
                    "multi seed",
                )
                expect(
                    writer.delete_projects(source, [str(pd), str(pe)]), True, "multi"
                )
                projects_now, bids_now = read()
                expect(projects_now, without_beta, "multi projects")
                expect(
                    {u: bids_now[u] for u in range(201, 206)},
                    {
                        201: (None, None),
                        202: (None, None),
                        203: (None, a),
                        204: (a, None),
                        205: (a, c),
                    },
                    "multi bids",
                )
                expect(
                    {u: v for u, v in bids_now.items() if u < 201},
                    {u: v for u, v in before_multi[1].items() if u < 201},
                    "multi bystanders",
                )

                # Batches larger than one chunk are applied completely.
                connection = access._connect_mdb(path)
                try:
                    cursor = connection.cursor()
                    for uid in range(1000, 1121):
                        cursor.execute(
                            "INSERT INTO [Bids] ([UID], [JobName], [BidProjectUID]) "
                            "VALUES (?, 'bulk', ?)",
                            uid,
                            a,
                        )
                    connection.commit()
                finally:
                    connection.close()
                batch = [str(uid) for uid in range(1000, 1120)]
                expect(
                    writer.move_bids_to_project(source, batch, pc), True, "bulk move"
                )
                after = read()[1]
                expect(
                    sorted(u for u, v in after.items() if u >= 1000 and v[0] == c),
                    list(range(1000, 1120)),
                    "bulk moved",
                )
                expect(after[1120], (a, None), "bulk bystander")
                expect(writer.orphan_bids(source, batch), True, "bulk orphan")
                after = read()[1]
                expect(
                    sorted(u for u, v in after.items() if u >= 1000 and v[0] is None),
                    list(range(1000, 1120)),
                    "bulk orphaned",
                )
                expect(after[1120], (a, None), "bulk bystander after orphan")
            finally:
                manager.close()

    def test_project_writes_scope_their_rows_and_roll_back_on_real_access(self):
        import subprocess
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.components.test_project_operations "
            "import ProjectOperationsRealAccessTests as Tests; "
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


def _large_db(bids, projects, extra=()):
    conn = contract_db(
        "CREATE TABLE Bids (UID INTEGER, BidProjectUID INTEGER, "
        "OrigBidProjectUID INTEGER)",
        "CREATE TABLE BidProjects (UID INTEGER, Name TEXT)",
    )
    conn.executemany("INSERT INTO Bids VALUES (?, ?, ?)", bids)
    conn.executemany("INSERT INTO BidProjects (UID) VALUES (?)", projects)
    for statement in extra:
        conn.execute(statement)
    return conn


class ProjectOperationsLargeBatchTests(unittest.TestCase):
    """Batches span three chunks of 50 uids (50 + 50 + 20)."""

    def test_a_large_move_and_orphan_apply_to_every_bid_in_every_chunk(self):
        batch = list(range(1, 121))
        conn = _large_db(
            [(uid, 901, None) for uid in batch] + [(500, 901, None)],
            [(901,), (902,), (903,)],
        )
        ops = RealContractOps(conn)
        everyone = [str(uid) for uid in batch]
        rows = "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
        self.assertIs(ops.move_bids_to_project("x.mdb", everyone, "902", "903"), True)
        self.assertEqual(
            conn.execute(rows).fetchall(),
            [(uid, 902, 903) for uid in batch] + [(500, 901, None)],
        )
        # Without a restore project the restore column keeps what it had.
        self.assertIs(ops.move_bids_to_project("x.mdb", everyone, "901"), True)
        self.assertEqual(
            conn.execute(rows).fetchall(),
            [(uid, 901, 903) for uid in batch] + [(500, 901, None)],
        )
        self.assertIs(ops.orphan_bids("x.mdb", everyone), True)
        self.assertEqual(
            conn.execute(rows).fetchall(),
            [(uid, None, 903) for uid in batch] + [(500, 901, None)],
        )

    def test_a_large_project_delete_detaches_and_removes_every_project(self):
        projects = list(range(2, 122))
        conn = _large_db(
            [(1000 + uid, uid, uid) for uid in projects] + [(2000, 500, 500)],
            [(uid,) for uid in projects] + [(500,)],
        )
        self.assertIs(
            RealContractOps(conn).delete_projects(
                "x.mdb", [str(uid) for uid in projects]
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidProjects").fetchall(), [(500,)]
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidProjectUID, OrigBidProjectUID FROM Bids ORDER BY UID"
            ).fetchall(),
            [(1000 + uid, None, None) for uid in projects] + [(2000, 500, 500)],
        )

    def test_a_missing_or_duplicated_uid_in_a_late_chunk_refuses_the_whole_batch(self):
        batch = list(range(2, 122))
        everyone = [str(uid) for uid in batch]
        # move: bid 110 does not exist.
        conn = _large_db(
            [(uid, 901, None) for uid in batch if uid != 110], [(901,), (902,)]
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                RealContractOps(conn).move_bids_to_project("x.mdb", everyone, "902"),
                False,
            )
        self.assertIn("Bids has no row for UID 110", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM Bids WHERE BidProjectUID = 901"
            ).fetchone(),
            (119,),
        )
        # orphan: bid 110 exists twice.
        conn = _large_db(
            [(uid, 901, None) for uid in batch] + [(110, 5, None)], [(901,)]
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(RealContractOps(conn).orphan_bids("x.mdb", everyone), False)
        self.assertIn("Bids contains duplicate UID 110", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM Bids WHERE BidProjectUID IS NULL"
            ).fetchone(),
            (0,),
        )
        # delete: project 110 exists twice.
        conn = _large_db(
            [(1000 + uid, uid, uid) for uid in batch],
            [(uid,) for uid in batch] + [(110,)],
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                RealContractOps(conn).delete_projects("x.mdb", everyone), False
            )
        self.assertIn("BidProjects contains duplicate UID 110", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidProjects").fetchone(), (121,)
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM Bids WHERE BidProjectUID IS NULL"
            ).fetchone(),
            (0,),
        )


class DeletedBidsProjectGuardTests(unittest.TestCase):
    """The system project "Deleted Bids" (UID 1) cannot be deleted by the writer.

    The tree view and the write handler already refuse it; the writer is the last
    line of defence for every other caller (MCP, scripts, a future screen).
    """

    @staticmethod
    def _database():
        conn = _project_db()
        conn.execute("UPDATE BidProjects SET Name = 'Deleted Bids' WHERE UID = 1")
        conn.execute(
            "UPDATE Bids SET BidProjectUID = 1, OrigBidProjectUID = 2 WHERE UID = 10"
        )
        conn.execute(
            "UPDATE Bids SET BidProjectUID = 2, OrigBidProjectUID = 1 WHERE UID = 11"
        )
        return conn

    @staticmethod
    def _state(conn):
        return (
            conn.execute("SELECT UID, Name FROM BidProjects ORDER BY UID").fetchall(),
            _bids(conn),
        )

    def test_the_system_project_is_refused_and_every_row_is_left_untouched(self):
        for uids in (["1"], [1], [" 1 "], ["01"], ["1", "1"]):
            with self.subTest(uids=uids):
                conn = self._database()
                before = self._state(conn)
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertIs(
                        RealContractOps(conn).delete_projects("x.mdb", uids), False
                    )
                self.assertIn("Deleted Bids", logs.output[0])
                self.assertEqual(self._state(conn), before)

    def test_one_system_project_in_a_batch_refuses_the_whole_batch(self):
        for uids in (["2", "1"], ["1", "2"]):
            with self.subTest(uids=uids):
                conn = self._database()
                before = self._state(conn)
                with self.assertLogs("test", "WARNING"):
                    self.assertIs(
                        RealContractOps(conn).delete_projects("x.mdb", uids), False
                    )
                self.assertEqual(self._state(conn), before)

    def test_the_refusal_happens_before_the_database_is_opened(self):
        class _NoConnectionOps(RealContractOps):
            def _connection(self, _db_path):
                raise AssertionError(
                    "the guard must refuse before opening a connection"
                )

        with self.assertLogs("test", "WARNING"):
            self.assertIs(
                _NoConnectionOps(self._database()).delete_projects("x.mdb", ["1"]),
                False,
            )

    def test_the_refusal_follows_the_strict_error_policy(self):
        conn = self._database()
        before = self._state(conn)
        with self.assertRaisesRegex(
            ValueError, r"^Cannot delete the system project 'Deleted Bids' \(UID 1\)$"
        ):
            _StrictPolicyOps(conn).delete_projects("x.mdb", ["1"])
        self.assertEqual(self._state(conn), before)

    def test_other_projects_are_still_deleted_and_the_system_project_survives(self):
        conn = self._database()
        self.assertIs(RealContractOps(conn).delete_projects("x.mdb", ["2"]), True)
        self.assertEqual(
            self._state(conn),
            ([(1, "Deleted Bids")], [(10, 1, None), (11, None, 1)]),
        )

    def test_moving_bids_into_or_out_of_the_system_project_is_unaffected(self):
        conn = self._database()
        ops = RealContractOps(conn)
        self.assertIs(ops.move_bids_to_project("x.mdb", ["11"], "1", "2"), True)
        self.assertEqual(_bids(conn), [(10, 1, 2), (11, 1, 2)])
        self.assertIs(ops.orphan_bids("x.mdb", ["10"]), True)
        self.assertEqual(_bids(conn), [(10, None, 2), (11, 1, 2)])
