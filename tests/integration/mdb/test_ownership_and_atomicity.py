import logging
import sqlite3
import unittest
from contextlib import contextmanager
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
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
    _ParameterLimitedSqliteConnectionWrapper,
    _ParameterLimitedSqliteCursorWrapper,
    _ParameterLimitedSqliteOps,
    _SqliteAnnotationOps,
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)


class OwnershipAndAtomicityPersistenceTests(unittest.TestCase):
    def test_bid_owned_bulk_deletes_reject_cross_bid_batches(self):
        fixtures = (
            (
                "condition folders",
                "CREATE TABLE BidConditionFolders ("
                "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
                "BidConditionFolders",
            ),
            (
                "pages",
                "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                "BidPages",
            ),
            (
                "takeoffs",
                "CREATE TABLE BidTakeoffs ("
                "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
                "BidTakeoffs",
            ),
        )
        for operation, create_sql, table in fixtures:
            with self.subTest(operation=operation):
                conn = sqlite3.connect(":memory:")
                conn.execute(create_sql)
                if table in {"BidConditionFolders", "BidTakeoffs"}:
                    conn.executemany(
                        f"INSERT INTO [{table}] VALUES (?, ?, NULL)",
                        ((7, 1), (8, 2)),
                    )
                else:
                    conn.executemany(
                        f"INSERT INTO [{table}] VALUES (?, ?)", ((7, 1), (8, 2))
                    )
                operations = _SqliteDuplicateOps(conn)
                if table == "BidConditionFolders":
                    result = operations.delete_condition_folders(
                        "malformed.mdb", ["7", "8"]
                    )
                elif table == "BidPages":
                    result = operations.delete_pages("malformed.mdb", ["7", "8"])
                else:
                    result = operations.delete_takeoffs("malformed.mdb", ["7", "8"])
                self.assertFalse(result)
                self.assertEqual(
                    conn.execute(f"SELECT UID FROM [{table}] ORDER BY UID").fetchall(),
                    [(7,), (8,)],
                )

    def test_root_hierarchy_inserts_require_authoritative_bid_before_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER)"
        )
        operations = _SqliteDuplicateOps(conn)
        self.assertIsNone(
            operations.insert_condition_folder(
                "malformed.mdb", "99", "Ownerless folder", None
            )
        )
        with self.assertRaises(RuntimeError):
            operations.insert_layer("malformed.mdb", "99", "Ownerless layer", 0)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditionFolders").fetchall(), []
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidLayers").fetchall(), [])

    def test_later_chunk_delete_failure_rolls_back_page_condition_and_folder_batches(
        self,
    ):
        class TransactionalOps(_SqliteDuplicateOps):
            @contextmanager
            def _connection(self, _db_path):
                wrapper = _SqliteConnectionWrapper(self._connection_ref)
                try:
                    yield wrapper
                except Exception:
                    self._connection_ref.rollback()
                    raise
                else:
                    self._connection_ref.commit()

        def connection_for(table, extra_columns=""):
            conn = sqlite3.connect(":memory:")
            conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO Bids VALUES (1)")
            conn.execute(
                f"CREATE TABLE [{table}] ("
                "UID INTEGER PRIMARY KEY, BidUID INTEGER"
                f"{extra_columns})"
            )
            conn.executemany(
                f"INSERT INTO [{table}] (UID, BidUID) VALUES (?, 1)",
                ((uid,) for uid in range(1, 52)),
            )
            conn.execute(
                f"CREATE TRIGGER fail_second_{table} BEFORE DELETE ON [{table}] "
                "WHEN OLD.UID=51 BEGIN SELECT RAISE(ABORT, 'later chunk'); END"
            )
            conn.commit()
            return conn

        page_conn = connection_for("BidPages", ", MasterPageUID INTEGER")
        page_conn.execute(
            "INSERT INTO BidPages (UID, BidUID, MasterPageUID) VALUES (100, 1, 1)"
        )
        page_conn.commit()
        with self.assertLogs("test", level="ERROR"):
            self.assertFalse(
                TransactionalOps(page_conn).delete_pages(
                    "large.mdb", [str(uid) for uid in range(1, 52)]
                )
            )
        self.assertEqual(
            page_conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 52
        )
        self.assertEqual(
            page_conn.execute(
                "SELECT MasterPageUID FROM BidPages WHERE UID=100"
            ).fetchone()[0],
            1,
        )
        condition_conn = connection_for("BidConditions")
        with self.assertLogs("test", level="ERROR"):
            self.assertFalse(
                TransactionalOps(condition_conn).delete_conditions(
                    "large.mdb", "1", [str(uid) for uid in range(1, 52)]
                )
            )
        self.assertEqual(
            condition_conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0],
            51,
        )
        folder_conn = connection_for("BidConditionFolders", ", ParentUID INTEGER")
        folder_conn.execute(
            "INSERT INTO BidConditionFolders (UID, BidUID, ParentUID) "
            "VALUES (100, 1, 1)"
        )
        folder_conn.commit()
        with self.assertLogs("test", level="ERROR"):
            self.assertFalse(
                TransactionalOps(folder_conn).delete_condition_folders(
                    "large.mdb", [str(uid) for uid in range(1, 52)]
                )
            )
        self.assertEqual(
            folder_conn.execute("SELECT COUNT(*) FROM BidConditionFolders").fetchone()[
                0
            ],
            52,
        )
        self.assertEqual(
            folder_conn.execute(
                "SELECT ParentUID FROM BidConditionFolders WHERE UID=100"
            ).fetchone()[0],
            1,
        )

    def test_large_condition_and_folder_deletes_stay_below_access_parameter_limit(
        self,
    ):
        row_count = 256
        uid_strings = [str(uid) for uid in range(1, row_count + 1)]
        condition_conn = sqlite3.connect(":memory:")
        condition_conn.execute("CREATE TABLE Bids (UID INTEGER)")
        condition_conn.execute("INSERT INTO Bids VALUES (1)")
        condition_conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)"
        )
        condition_conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        condition_statements = []
        condition_conn.set_trace_callback(condition_statements.append)
        self.assertTrue(
            _ParameterLimitedSqliteOps(condition_conn).delete_conditions(
                "large.mdb", "1", uid_strings
            )
        )
        self.assertEqual(
            sum(
                sql.lstrip().upper().startswith("DELETE FROM [BIDCONDITIONS]")
                for sql in condition_statements
            ),
            6,
        )
        folder_conn = sqlite3.connect(":memory:")
        folder_conn.execute("CREATE TABLE Bids (UID INTEGER)")
        folder_conn.execute("INSERT INTO Bids VALUES (1)")
        folder_conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        folder_conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, 1, NULL)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        folder_statements = []
        folder_conn.set_trace_callback(folder_statements.append)
        self.assertTrue(
            _ParameterLimitedSqliteOps(folder_conn).delete_condition_folders(
                "large.mdb", uid_strings
            )
        )
        folder_counts = {
            operation: sum(
                sql.lstrip().upper().startswith(operation) for sql in folder_statements
            )
            for operation in ("UPDATE", "DELETE")
        }
        self.assertEqual(folder_counts, {"UPDATE": 6, "DELETE": 6})

    def test_large_project_and_bid_batches_stay_below_access_parameter_limit(self):
        row_count = 256
        uid_strings = [str(uid) for uid in range(1, row_count + 1)]
        move_conn = sqlite3.connect(":memory:")
        move_conn.execute("CREATE TABLE BidProjects (UID INTEGER)")
        move_conn.executemany("INSERT INTO BidProjects VALUES (?)", ((900,), (901,)))
        move_conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        move_conn.executemany(
            "INSERT INTO Bids VALUES (?, 900, NULL)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        move_statements = []
        move_conn.set_trace_callback(move_statements.append)
        move_ops = _ParameterLimitedSqliteOps(move_conn)
        self.assertTrue(
            move_ops.move_bids_to_project(
                "large.mdb", uid_strings, "901", orig_project_uid="900"
            )
        )
        self.assertTrue(move_ops.orphan_bids("large.mdb", uid_strings))
        self.assertEqual(
            sum(
                sql.lstrip().upper().startswith("UPDATE [BIDS]")
                for sql in move_statements
            ),
            12,
        )
        project_conn = sqlite3.connect(":memory:")
        project_conn.execute("CREATE TABLE BidProjects (UID INTEGER)")
        project_conn.executemany(
            "INSERT INTO BidProjects VALUES (?)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        project_conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, BidProjectUID INTEGER, OrigBidProjectUID INTEGER)"
        )
        project_conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?)",
            ((1000 + uid, uid, uid) for uid in range(1, row_count + 1)),
        )
        project_statements = []
        project_conn.set_trace_callback(project_statements.append)
        self.assertTrue(
            _ParameterLimitedSqliteOps(project_conn).delete_projects(
                "large.mdb", uid_strings
            )
        )
        project_counts = {
            operation: sum(
                sql.lstrip().upper().startswith(operation) for sql in project_statements
            )
            for operation in ("UPDATE", "DELETE")
        }
        self.assertEqual(project_counts, {"UPDATE": 12, "DELETE": 6})
        bid_conn = sqlite3.connect(":memory:")
        bid_conn.execute("CREATE TABLE Bids (UID INTEGER)")
        bid_conn.executemany(
            "INSERT INTO Bids VALUES (?)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        bid_statements = []
        bid_conn.set_trace_callback(bid_statements.append)
        self.assertTrue(
            _ParameterLimitedSqliteOps(bid_conn).delete_bids("large.mdb", uid_strings)
        )
        self.assertEqual(
            sum(
                sql.lstrip().upper().startswith("DELETE FROM [BIDS]")
                for sql in bid_statements
            ),
            6,
        )

    def test_orphan_page_edit_and_delete_reject_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO BidPages VALUES (7, 99, 'Orphan page')")
        ops = _SqliteDuplicateOps(conn)
        with self.assertLogs("test", level="ERROR") as edit_logs:
            self.assertFalse(ops.save_page_name("malformed.mdb", "7", "Changed"))
        self.assertIn("Bids has no row for UID 99", edit_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidPages WHERE UID=7").fetchone()[0],
            "Orphan page",
        )
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_pages("malformed.mdb", ["7"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 1)

    def test_orphan_layer_and_folder_mutations_reject_before_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidLayers ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Show INTEGER)"
        )
        conn.execute("INSERT INTO BidLayers VALUES (7, 99, 'Orphan layer', 0)")
        conn.execute(
            "CREATE TABLE BidConditionFolders ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditionFolders VALUES (8, 99, 'Orphan folder', NULL)"
        )
        ops = _SqliteDuplicateOps(conn)
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_layer_name("malformed.mdb", "7", "Changed")
        with self.assertRaisesRegex(RuntimeError, "Bids has no row for UID 99"):
            ops.update_all_layers_show("malformed.mdb", "99", True)
        self.assertEqual(
            conn.execute("SELECT Name, Show FROM BidLayers WHERE UID=7").fetchone(),
            ("Orphan layer", 0),
        )
        with self.assertLogs("test", level="ERROR") as rename_logs:
            self.assertFalse(
                ops.rename_condition_folder("malformed.mdb", "8", "Changed")
            )
        self.assertIn("Bids has no row for UID 99", rename_logs.output[0])
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_condition_folders("malformed.mdb", ["8"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditionFolders WHERE UID=8").fetchone()[
                0
            ],
            "Orphan folder",
        )

    def test_orphan_takeoff_and_annotation_mutations_reject_before_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, IsNegativeQuantity INTEGER)"
        )
        conn.execute("INSERT INTO BidTakeoffs VALUES (7, 99, 0)")
        conn.execute(
            "CREATE TABLE BidNamedViews (" "UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (8, 99, 'Orphan view')")
        takeoff_ops = _SqliteDuplicateOps(conn)
        with self.assertLogs("test", level="ERROR") as takeoff_edit_logs:
            self.assertFalse(
                takeoff_ops.set_takeoffs_negative("malformed.mdb", ["7"], True)
            )
        self.assertIn("Bids has no row for UID 99", takeoff_edit_logs.output[0])
        with self.assertLogs("test", level="ERROR") as takeoff_delete_logs:
            self.assertFalse(takeoff_ops.delete_takeoffs("malformed.mdb", ["7"]))
        self.assertIn("Bids has no row for UID 99", takeoff_delete_logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT IsNegativeQuantity FROM BidTakeoffs WHERE UID=7"
            ).fetchone()[0],
            0,
        )
        annotation_ops = _SqliteAnnotationOps(conn)
        with self.assertLogs("test", level="ERROR") as annotation_edit_logs:
            self.assertFalse(
                annotation_ops.save_annotation_text_properties(
                    "malformed.mdb", [("8", "namedview", {"Text": "Changed"})]
                )
            )
        self.assertIn("Bids has no row for UID 99", annotation_edit_logs.output[0])
        with self.assertLogs("test", level="ERROR") as annotation_delete_logs:
            self.assertFalse(
                annotation_ops.delete_annotations("malformed.mdb", [("8", "namedview")])
            )
        self.assertIn("Bids has no row for UID 99", annotation_delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidNamedViews WHERE UID=8").fetchone()[0],
            "Orphan view",
        )
