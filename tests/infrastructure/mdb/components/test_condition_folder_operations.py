import logging
import sqlite3
import unittest
from tests.helpers.mdb.real_write_contract import (
    ListParamConnection,
    ListParamCursor,
    RealContractOps,
    contract_db,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    IncoherentBidOwnedScopeError,
    MissingBidOwnedUidError,
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


class ConditionFolderOperationsPersistenceTests(unittest.TestCase):
    def test_delete_condition_folder_refuses_folder_used_by_conditions(self):
        conn = sqlite3.connect(":memory:")
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
                BidConditionFolderUID INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders (UID, BidUID, Name) VALUES (?, 1, ?)",
            ((1, "Used"), (2, "Unused")),
        )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidConditionFolderUID) VALUES (10, 1)"
        )
        # No foreign key: only the production in-use guard can refuse the delete.
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1", "2"])
            )
        self.assertEqual(len(logs.records), 1)
        self.assertIn("Refusing to delete condition folders in use", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(1, "Used"), (2, "Unused")],
        )

    def test_delete_condition_folder_in_use_check_covers_every_uid_chunk(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidConditionFolderUID INTEGER)"
        )
        folder_uids = list(range(1, 121))
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, 'F')",
            ((uid,) for uid in folder_uids),
        )
        conn.execute("INSERT INTO BidConditions VALUES (10, 120)")
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders(
                    "bid.mdb", [str(uid) for uid in folder_uids]
                )
            )
        self.assertIn("Refusing to delete condition folders in use", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[0],
            120,
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
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
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
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(
                        _SqliteDuplicateOps(conn).insert_condition_folder(
                            "malformed.mdb", "1", "Child", "7"
                        )
                    )
                self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, BidUID, ParentUID, Name "
                        "FROM BidConditionFolders ORDER BY UID"
                    ).fetchall(),
                    [(uid, bid, None, "Other") for uid, bid in parent_rows],
                )

    def test_insert_condition_folder_rejects_missing_bid_without_allocating(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "Name TEXT, ExpandState INTEGER)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(
                _SqliteDuplicateOps(conn).insert_condition_folder(
                    "malformed.mdb", "99", "Ownerless", None
                )
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertEqual(
            conn.execute("SELECT * FROM BidConditionFolders").fetchall(), []
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
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIsNone(
                _SqliteDuplicateOps(conn).insert_condition_folder(
                    "legacy.mdb", "1", "Child", "7"
                )
            )
        self.assertIs(logs.records[0].exc_info[0], RuntimeError)
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "This OST database does not support Condition folder "
            "hierarchy persistence.",
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

    def test_rename_condition_folder_updates_only_target_name(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?)",
            ((1, "Old"), (2, "Other")),
        )
        self.assertTrue(
            _SqliteMdbOps(conn).rename_condition_folder("bid.mdb", "1", "New")
        )
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidConditionFolders").fetchall(),
            [(1, "New"), (2, "Other")],
        )

    def test_rename_condition_folder_rejects_missing_folder(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute("INSERT INTO BidConditionFolders VALUES (1, 1, 'Old')")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).rename_condition_folder("bid.mdb", "9", "New")
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidConditionFolders").fetchall(),
            [(1, "Old")],
        )

    def test_delete_condition_folders_empty_request_is_a_noop_success(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (1)")
        self.assertTrue(_SqliteMdbOps(conn).delete_condition_folders("bid.mdb", []))
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditionFolders").fetchall(), [(1,)]
        )

    def test_delete_condition_folders_rejects_invalid_uid_without_deleting(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (1)")
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1", "bad"])
            )
        self.assertIn("Invalid folder uids", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditionFolders").fetchall(), [(1,)]
        )

    def test_delete_condition_folders_rejects_folders_from_different_bids(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?, 'F')", ((1, 1), (2, 2))
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_condition_folders("bid.mdb", ["1", "2"])
            )
        self.assertIs(logs.records[0].exc_info[0], IncoherentBidOwnedScopeError)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditionFolders ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )


class _LoggedCursor(ListParamCursor):
    log = None

    def execute(self, query, *params):
        flat = (
            tuple(params[0])
            if len(params) == 1 and isinstance(params[0], (list, tuple))
            else params
        )
        self.log.append((" ".join(query.split()), flat))
        return super().execute(query, *params)


class _LoggedConnection(ListParamConnection):
    log = None

    def cursor(self):
        cursor = _LoggedCursor(self._connection)
        cursor.log = self.log
        return cursor


class _LoggedOps(RealContractOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.log = []

    def _connection(self, _db_path):
        wrapper = _LoggedConnection(self._connection_ref)
        wrapper.log = self.log
        return wrapper


class _StrictOps(RealContractOps):
    def _record_caught_mutation_error(self, exc):
        return True


def _folder_db(
    folders="UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, ExpandState INTEGER",
    *extra,
):
    return contract_db(
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        f"CREATE TABLE BidConditionFolders ({folders})",
        "CREATE TABLE BidConditions (UID INTEGER, BidConditionFolderUID INTEGER)",
        *extra,
    )


class ConditionFolderContractTests(unittest.TestCase):
    def test_a_new_folder_stores_every_column_and_binds_identifiers_as_integers(self):
        conn = _folder_db()
        ops = _LoggedOps(conn)
        self.assertEqual(ops.insert_condition_folder("x.mdb", "1", "Root"), "1")
        self.assertEqual(ops.insert_condition_folder("x.mdb", "1", "Kid", "1"), "2")
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, ParentUID, Name, ExpandState FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(1, 1, None, "Root", -1), (2, 1, 1, "Kid", -1)],
        )
        self.assertEqual(ops.skips, [])
        inserts = [
            params
            for sql, params in ops.log
            if sql.startswith("INSERT INTO [BidConditionFolders]")
        ]
        self.assertEqual(len(inserts), 2)
        for params in inserts:
            self.assertEqual(params[1], 1)
            self.assertIs(type(params[1]), int)
        self.assertIs(type(inserts[1][2]), int)

    def test_a_flat_folder_table_reports_each_column_it_cannot_store(self):
        conn = _folder_db("UID INTEGER, BidUID INTEGER, Name TEXT")
        ops = RealContractOps(conn)
        self.assertEqual(ops.insert_condition_folder("x.mdb", "1", "Root"), "1")
        self.assertEqual(
            sorted(ops.skips),
            [
                ("BidConditionFolders", "ExpandState", "insert_condition_folder"),
                ("BidConditionFolders", "ParentUID", "insert_condition_folder"),
            ],
        )

    def test_a_folder_insert_needs_its_identity_and_name_columns(self):
        for columns, missing in (
            ("BidUID INTEGER, Name TEXT", "UID"),
            ("UID INTEGER, Name TEXT", "BidUID"),
            ("UID INTEGER, BidUID INTEGER", "Name"),
        ):
            with self.subTest(missing=missing):
                conn = _folder_db(columns)
                with self.assertLogs("test", "ERROR"):
                    self.assertIsNone(
                        RealContractOps(conn).insert_condition_folder("x.mdb", "1", "N")
                    )
                with self.assertRaises(Exception) as caught:
                    _StrictOps(conn).insert_condition_folder("x.mdb", "1", "N")
                self.assertIn(missing, str(caught.exception))

    def test_a_rename_binds_the_folder_as_an_integer_and_changes_the_name(self):
        conn = _folder_db()
        conn.execute("INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Old', -1)")
        ops = _LoggedOps(conn)
        self.assertIs(ops.rename_condition_folder("x.mdb", "5", "New"), True)
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditionFolders").fetchall(), [("New",)]
        )
        (update,) = [
            params
            for sql, params in ops.log
            if sql.startswith("UPDATE [BidConditionFolders]")
        ]
        self.assertEqual(update, ("New", 5))
        self.assertIs(type(update[1]), int)

    def test_rename_and_delete_need_the_columns_they_write(self):
        for call, columns, missing in (
            (
                lambda ops: ops.rename_condition_folder("x.mdb", "5", "N"),
                "BidUID INTEGER, Name TEXT",
                "UID",
            ),
            (
                lambda ops: ops.rename_condition_folder("x.mdb", "5", "N"),
                "UID INTEGER, BidUID INTEGER",
                "Name",
            ),
            (
                lambda ops: ops.delete_condition_folders("x.mdb", ["5"]),
                "BidUID INTEGER, Name TEXT",
                "UID",
            ),
        ):
            with self.subTest(missing=missing, call=call):
                conn = _folder_db(columns)
                with self.assertRaises(Exception) as caught:
                    call(_StrictOps(conn))
                self.assertEqual(
                    str(caught.exception), f"Missing BidConditionFolders.{missing}"
                )

    def test_failures_return_false_and_follow_the_error_policy(self):
        conn = _folder_db()
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                RealContractOps(conn).rename_condition_folder("x.mdb", "99", "N"), False
            )
        with self.assertRaises(MissingBidOwnedUidError):
            _StrictOps(conn).rename_condition_folder("x.mdb", "99", "N")
        with self.assertLogs("test", "WARNING"):
            self.assertIs(
                RealContractOps(conn).delete_condition_folders("x.mdb", ["x"]), False
            )
        with self.assertRaisesRegex(
            ValueError, "^Invalid BidConditionFolders UID: 'x'$"
        ):
            _StrictOps(conn).delete_condition_folders("x.mdb", ["x"])
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                RealContractOps(conn).delete_condition_folders("x.mdb", ["99"]), False
            )

    def test_a_folder_in_use_is_refused_with_false(self):
        conn = _folder_db()
        conn.execute("INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Used', -1)")
        conn.execute("INSERT INTO BidConditions VALUES (1, 5)")
        with self.assertLogs("test", "WARNING"):
            self.assertIs(
                RealContractOps(conn).delete_condition_folders("x.mdb", ["5"]), False
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchall(), [(1,)]
        )

    def test_an_unused_folder_is_deleted_and_its_children_move_to_the_root(self):
        conn = _folder_db()
        conn.execute("INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Gone', -1)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (6, 1, 5, 'Kid', -1)")
        self.assertIs(
            RealContractOps(conn).delete_condition_folders("x.mdb", ["5"]), True
        )
        self.assertEqual(
            conn.execute("SELECT UID, ParentUID FROM BidConditionFolders").fetchall(),
            [(6, None)],
        )
