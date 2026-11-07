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
    ACCESS_BULK_CHUNK_SIZE,
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
                if missing == "UID":
                    # Not the required-column guard: the new uid is allocated
                    # (SELECT MAX([UID])) before the guard runs, so the allocator's
                    # own database error is what the caller sees. The 'UID' entry
                    # of the guard's required tuple is therefore unreachable.
                    self.assertIsInstance(caught.exception, sqlite3.OperationalError)
                else:
                    self.assertEqual(
                        str(caught.exception), f"Missing BidConditionFolders.{missing}"
                    )

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


class _CountingOps(RealContractOps):
    """Counts the connections the operation opens."""

    def __init__(self, connection):
        super().__init__(connection)
        self.opened = 0

    def _connection(self, db_path):
        self.opened += 1
        return super()._connection(db_path)


class ConditionFolderDeleteSafetyTests(unittest.TestCase):
    def test_a_uid_collection_that_cannot_be_read_is_refused_before_a_connection_opens(
        self,
    ):
        for bad in (5, ["5", "bad"]):
            with self.subTest(uids=bad):
                conn = _folder_db()
                conn.execute(
                    "INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Keep', -1)"
                )
                ops = _CountingOps(conn)
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertIs(ops.delete_condition_folders("x.mdb", bad), False)
                self.assertEqual(ops.opened, 0)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].levelname, "WARNING")
                self.assertIsNone(logs.records[0].exc_info)
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidConditionFolders").fetchall(),
                    [(5,)],
                )
                with self.assertRaises((TypeError, ValueError)):
                    _StrictOps(conn).delete_condition_folders("x.mdb", bad)

    def test_refusal_and_failure_logs_name_the_operation_the_uids_and_the_database(
        self,
    ):
        used = _folder_db()
        used.execute("INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Used', -1)")
        used.execute("INSERT INTO BidConditionFolders VALUES (6, 1, NULL, 'Free', -1)")
        used.execute("INSERT INTO BidConditions VALUES (1, 5)")
        cases = (
            (
                lambda ops: ops.insert_condition_folder("a.mdb", "99", "N"),
                _folder_db(),
                "Failed to insert condition folder in a.mdb",
            ),
            (
                lambda ops: ops.rename_condition_folder("a.mdb", "99", "N"),
                _folder_db(),
                "Failed to rename condition folder 99 in a.mdb",
            ),
            (
                lambda ops: ops.delete_condition_folders("a.mdb", ["99", "98"]),
                _folder_db(),
                "Failed to delete condition folders ['99', '98'] in a.mdb",
            ),
            (
                lambda ops: ops.delete_condition_folders("a.mdb", ["x"]),
                _folder_db(),
                "Invalid folder uids passed to delete_condition_folders: ['x']",
            ),
            (
                lambda ops: ops.delete_condition_folders("a.mdb", ["6", "5", "6"]),
                used,
                "Refusing to delete condition folders in use: [6, 5]",
            ),
        )
        for call, conn, message in cases:
            with self.subTest(message=message):
                with self.assertLogs("test", "WARNING") as logs:
                    call(RealContractOps(conn))
                self.assertEqual([r.getMessage() for r in logs.records], [message])

    @staticmethod
    def _many_folders(count=120):
        conn = _folder_db()
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, NULL, 'F', -1)",
            ((uid,) for uid in range(1, count + 1)),
        )
        return conn

    def test_a_folder_in_use_blocks_the_delete_wherever_it_sits_in_a_batch(self):
        # 120 folders are checked in chunks of 50: positions on both sides of every
        # chunk boundary, including the first and last uid of each chunk.
        batch = [str(uid) for uid in range(1, 121)]
        for in_use in (1, 49, 50, 51, 75, 100, 101, 120):
            with self.subTest(in_use=in_use):
                conn = self._many_folders()
                conn.execute("INSERT INTO BidConditions VALUES (1, ?)", (in_use,))
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertIs(
                        RealContractOps(conn).delete_condition_folders("x.mdb", batch),
                        False,
                    )
                # The refusal names every folder of the batch, not a prefix.
                self.assertEqual(
                    logs.records[0].getMessage(),
                    "Refusing to delete condition folders in use: "
                    + str(list(range(1, 121))),
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone(),
                    (120,),
                )

    def test_children_of_every_deleted_folder_move_to_the_root_across_chunks(self):
        conn = _folder_db()
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, NULL, 'P', -1)",
            ((uid,) for uid in range(1, 61)),
        )
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?, 'C', -1)",
            ((uid + 100, uid) for uid in range(1, 61)),
        )
        batch = [str(uid) for uid in range(1, 61)]
        self.assertIs(
            RealContractOps(conn).delete_condition_folders("x.mdb", batch), True
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(uid + 100, None) for uid in range(1, 61)],
        )

    def test_every_statement_of_a_large_delete_binds_at_most_one_chunk_of_uids(self):
        conn = self._many_folders()
        ops = _LoggedOps(conn)
        batch = [str(uid) for uid in range(1, 121)]
        self.assertIs(ops.delete_condition_folders("x.mdb", batch), True)
        size = ACCESS_BULK_CHUNK_SIZE

        def bound(prefix):
            return [len(params) for sql, params in ops.log if sql.startswith(prefix)]

        chunks = [size, size, 120 - 2 * size]
        self.assertEqual(
            bound("SELECT [BidConditionFolderUID] FROM [BidConditions]"), chunks
        )
        self.assertEqual(
            bound("UPDATE [BidConditionFolders] SET [ParentUID]=?"),
            [1 + n for n in chunks],
        )
        self.assertEqual(bound("DELETE FROM [BidConditionFolders]"), chunks)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone(), (0,)
        )

    def test_a_folder_of_another_bid_in_a_late_chunk_refuses_the_whole_batch(self):
        conn = self._many_folders()
        conn.execute("INSERT INTO Bids VALUES (2)")
        conn.execute("UPDATE BidConditionFolders SET BidUID = 2 WHERE UID = 110")
        batch = [str(uid) for uid in range(1, 121)]
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                RealContractOps(conn).delete_condition_folders("x.mdb", batch), False
            )
        self.assertIs(logs.records[0].exc_info[0], IncoherentBidOwnedScopeError)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone(), (120,)
        )

    def test_a_refused_delete_leaves_the_folder_hierarchy_untouched(self):
        conn = _folder_db()
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?, ?, -1)",
            ((1, None, "Top"), (2, 1, "Child"), (3, None, "Used")),
        )
        conn.execute("INSERT INTO BidConditions VALUES (1, 3)")
        with self.assertLogs("test", "WARNING"):
            self.assertIs(
                RealContractOps(conn).delete_condition_folders("x.mdb", ["1", "3"]),
                False,
            )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidConditionFolders ORDER BY UID"
            ).fetchall(),
            [(1, None, "Top"), (2, 1, "Child"), (3, None, "Used")],
        )

    def test_folders_can_be_deleted_from_a_file_without_a_condition_table(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidConditionFolders "
            "(UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)",
            "INSERT INTO BidConditionFolders VALUES (5, 1, NULL, 'Gone')",
            "INSERT INTO BidConditionFolders VALUES (6, 1, 5, 'Kid')",
        )
        self.assertIs(
            RealContractOps(conn).delete_condition_folders("x.mdb", ["5"]), True
        )
        self.assertEqual(
            conn.execute("SELECT UID, ParentUID FROM BidConditionFolders").fetchall(),
            [(6, None)],
        )

    def test_deleting_a_parent_and_its_grandchild_together_keeps_the_child(self):
        conn = _folder_db()
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, ?, ?, -1)",
            ((1, None, "Top"), (2, 1, "Mid"), (3, 2, "Leaf")),
        )
        self.assertIs(
            RealContractOps(conn).delete_condition_folders("x.mdb", ["1", "3"]), True
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidConditionFolders"
            ).fetchall(),
            [(2, None, "Mid")],
        )


class ConditionFolderOperationsRealAccessTests(unittest.TestCase):
    """Real Access: folder scoping, in-use refusal, re-parenting and rollback.
    The sqlite stand-ins cannot show how the ACE driver binds the integer
    identifiers and NULL parents, nor that a failed delete rolls its re-parenting
    update back.
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
                raise RuntimeError("injected failure after the re-parenting update")

        def expect(actual, expected, label):
            if actual != expected:
                raise AssertionError(f"{label}: {actual!r} != {expected!r}")

        def execute_all(path, statements):
            connection = access._connect_mdb(path)
            try:
                cursor = connection.cursor()
                for sql, *params in statements:
                    cursor.execute(sql, *params)
                connection.commit()
            finally:
                connection.close()

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "folders.mdb"
            if not access.DatabaseCreator().create_database(path, "Folders"):
                raise AssertionError("database creation failed")
            source = str(path)
            manager = MdbConnectionManager()
            writer = MdbWriter(manager)

            def read():
                manager.close_database(source)
                connection = access._connect_mdb(path)
                try:
                    cursor = connection.cursor()
                    cursor.execute(
                        "SELECT [UID], [BidUID], [ParentUID], [Name], [ExpandState] "
                        "FROM [BidConditionFolders]"
                    )
                    folders = {
                        int(r[0]): (
                            int(r[1]),
                            None if r[2] is None else int(r[2]),
                            r[3],
                            r[4],
                        )
                        for r in cursor.fetchall()
                    }
                    cursor.execute(
                        "SELECT [UID], [BidConditionFolderUID] FROM [BidConditions]"
                    )
                    conditions = {
                        int(r[0]): None if r[1] is None else int(r[1])
                        for r in cursor.fetchall()
                    }
                finally:
                    connection.close()
                return folders, conditions

            try:
                execute_all(
                    path,
                    [
                        ("INSERT INTO [Bids] ([UID], [JobName]) VALUES (201, 'a')",),
                        ("INSERT INTO [Bids] ([UID], [JobName]) VALUES (202, 'b')",),
                    ],
                )
                top = writer.insert_condition_folder(source, "201", "Top")
                mid = writer.insert_condition_folder(source, "201", "Mid", top)
                leaf = writer.insert_condition_folder(source, "201", "Leaf", mid)
                other = writer.insert_condition_folder(source, "202", "Other")
                spare = writer.insert_condition_folder(source, "202", "Spare")
                ids = (top, mid, leaf, other, spare)
                if None in ids:
                    raise AssertionError(f"folder creation failed: {ids}")
                t, m, lf, o, sp = (int(value) for value in ids)
                expect(len({t, m, lf, o, sp}), 5, "distinct folder uids")
                for uid in (301, 302, 303):
                    owner, home = {301: (201, lf), 302: (202, o), 303: (201, None)}[uid]
                    execute_all(
                        path,
                        [
                            (
                                "INSERT INTO [BidConditions] "
                                "([UID], [BidUID], [BidConditionFolderUID], [Name]) "
                                "VALUES (?, ?, ?, 'cond')",
                                uid,
                                owner,
                                home,
                            )
                        ],
                    )
                folders = {
                    t: (201, None, "Top", True),
                    m: (201, t, "Mid", True),
                    lf: (201, m, "Leaf", True),
                    o: (202, None, "Other", True),
                    sp: (202, None, "Spare", True),
                }
                conditions = {301: lf, 302: o, 303: None}
                expect(read(), (folders, conditions), "seed")
                # Inserts that name an absent bid, an absent parent or a parent of
                # another bid are refused and add nothing.
                for args in (
                    ("999", "N", None),
                    ("201", "N", "999"),
                    ("201", "N", str(o)),
                ):
                    expect(writer.insert_condition_folder(source, *args), None, args)
                expect(read(), (folders, conditions), "after refused inserts")
                expect(
                    writer.rename_condition_folder(source, str(t), "Renamed"),
                    True,
                    "rename",
                )
                folders[t] = (201, None, "Renamed", True)
                expect(
                    writer.rename_condition_folder(source, "999", "X"),
                    False,
                    "absent rename",
                )
                expect(read(), (folders, conditions), "after rename")
                # Refusals: a folder holding conditions, a batch containing one,
                # a batch spanning two bids and an absent folder delete nothing.
                for batch in ([str(lf)], [str(m), str(lf)], [str(t), str(sp)], ["999"]):
                    expect(writer.delete_condition_folders(source, batch), False, batch)
                expect(read(), (folders, conditions), "after refused deletes")
                # A failure after the re-parenting update rolls that update back.
                failing = FailingDeleteWriter(manager)
                expect(
                    failing.delete_condition_folders(source, [str(m)]), False, "failed"
                )
                expect(read(), (folders, conditions), "after rolled back delete")
                # Deleting a folder removes only it: the child folder, the grandchild
                # and every condition survive, the child moves to the root.
                expect(
                    writer.delete_condition_folders(source, [str(m)]), True, "delete"
                )
                del folders[m]
                folders[lf] = (201, None, "Leaf", True)
                expect(read(), (folders, conditions), "after delete")
                expect(
                    writer.delete_condition_folders(source, [str(t)]),
                    True,
                    "delete top",
                )
                del folders[t]
                expect(read(), (folders, conditions), "after delete top")
                # A batch larger than one chunk is checked and applied completely.
                bulk = list(range(5000, 5120))
                execute_all(
                    path,
                    [
                        (
                            "INSERT INTO [BidConditionFolders] "
                            "([UID], [BidUID], [Name]) VALUES (?, 201, 'bulk')",
                            uid,
                        )
                        for uid in bulk
                    ],
                )
                # Child folders outside the batch hang under the first and last one.
                execute_all(
                    path,
                    [
                        (
                            "INSERT INTO [BidConditionFolders] "
                            "([UID], [BidUID], [ParentUID], [Name]) "
                            "VALUES (?, 201, ?, 'child')",
                            child,
                            parent,
                        )
                        for child, parent in ((6000, 5000), (6001, 5119))
                    ],
                )
                batch = [str(uid) for uid in bulk]
                for position in (5000, 5119):
                    execute_all(
                        path,
                        [
                            (
                                "INSERT INTO [BidConditions] "
                                "([UID], [BidUID], [BidConditionFolderUID], [Name]) "
                                "VALUES (399, 201, ?, 'late')",
                                position,
                            )
                        ],
                    )
                    expect(
                        writer.delete_condition_folders(source, batch),
                        False,
                        f"bulk in use at {position}",
                    )
                    kept = read()[0]
                    expect(
                        sorted(u for u in kept if u >= 5000),
                        bulk + [6000, 6001],
                        f"bulk kept in use at {position}",
                    )
                    expect(
                        (kept[6000][1], kept[6001][1]),
                        (5000, 5119),
                        "children stay put when refused",
                    )
                    execute_all(
                        path,
                        [("DELETE FROM [BidConditions] WHERE [UID] = 399",)],
                    )
                expect(
                    writer.delete_condition_folders(source, batch), True, "bulk delete"
                )
                # Raw inserts leave ExpandState at its column default (No).
                children = {
                    6000: (201, None, "child", False),
                    6001: (201, None, "child", False),
                }
                expect(read(), (folders | children, conditions), "after bulk delete")
            finally:
                manager.close()

    def test_folder_writes_scope_their_rows_and_roll_back_on_real_access(self):
        import subprocess
        import sys
        from tests.helpers.mdb.schema_support import _access_available
        from tests.paths import REPO_ROOT

        if not _access_available():
            self.skipTest("Access ODBC/ADOX is not available")
        code = (
            "from tests.infrastructure.mdb.components.test_condition_folder_operations "
            "import ConditionFolderOperationsRealAccessTests as Tests; "
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
