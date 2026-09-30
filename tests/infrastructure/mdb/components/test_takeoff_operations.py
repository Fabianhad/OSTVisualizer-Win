import logging
import sqlite3
import unittest
from contextlib import contextmanager
import pyodbc
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
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
from ost_visualizer.infrastructure.mdb.components.constants import (
    TAKEOFF_REFERENCE_TABLES,
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
    _RecordingConnection,
    _RecordingCursor,
    _RecordingSchema,
    _RecordingTakeoffOps,
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from tests.integration.mdb.text_style_support import (
    _FakeConnection as _text_style_support__FakeConnection,
    _FakeCursor as _text_style_support__FakeCursor,
    _TakeoffTextStyleWriter as _text_style_support__TakeoffTextStyleWriter,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.helpers.mdb.operations import _SqliteDuplicateOps


class _SchemaCheckedTakeoffOps(_SqliteDuplicateOps):
    _require_write_columns = MdbWriter._require_write_columns


class TakeoffOperationsPersistenceTests(unittest.TestCase):
    def test_takeoff_bulk_saves_reject_cross_bid_batches_atomically(self):
        operations = (
            (
                "positions",
                lambda writer: writer.save_takeoff_positions(
                    "malformed.mdb", [(7, (10.0, 20.0)), (8, (30.0, 40.0))]
                ),
            ),
            (
                "rotations",
                lambda writer: writer.save_takeoff_rotations(
                    "malformed.mdb", [(7, 45.0), (8, 90.0)]
                ),
            ),
            (
                "text properties",
                lambda writer: writer.save_takeoff_text_properties(
                    "malformed.mdb",
                    [
                        (7, {"name_font_name": "First"}),
                        (8, {"name_font_name": "Second"}),
                    ],
                ),
            ),
        )
        for operation, mutate in operations:
            with self.subTest(operation=operation):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, Position BLOB, "
                    "Rotation REAL, NameFontName TEXT)"
                )
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, ?, NULL, 0, 'Original')",
                    ((7, 1), (8, 2)),
                )
                self.assertFalse(mutate(_SqliteDuplicateOps(conn)))
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position, Rotation, NameFontName "
                        "FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(7, None, 0.0, "Original"), (8, None, 0.0, "Original")],
                )

    def test_takeoff_update_rejects_duplicate_physical_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, IsNegativeQuantity INTEGER)"
        )
        conn.executemany("INSERT INTO BidTakeoffs VALUES (7, ?, ?)", ((1, 0), (2, -1)))
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).set_takeoffs_negative("malformed.mdb", ["7"], True)
            )
        self.assertIn("BidTakeoffs contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, IsNegativeQuantity FROM BidTakeoffs ORDER BY rowid"
            ).fetchall(),
            [(1, 0), (2, -1)],
        )

    def test_takeoff_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, ParentUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidTakeoffs VALUES (7, 1, NULL)", ((), ()))
        conn.execute("INSERT INTO BidTakeoffs VALUES (8, 1, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_takeoffs("malformed.mdb", ["7"])
            )
        self.assertIn("BidTakeoffs contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs ORDER BY rowid"
            ).fetchall(),
            [(7, None), (7, None), (8, 7)],
        )

    def test_takeoff_delete_clears_all_surviving_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, "
            "TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?, ?, ?, ?)",
            ((7, None, None, None, None), (8, 7, 7, 7, 7)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(8, None, None, None, None)],
        )

    def test_delete_parent_takeoff_clears_child_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                ParentUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (1, 1, NULL)"
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (2, 1, 1)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["1"]))
        child = conn.execute(
            "SELECT ParentUID FROM BidTakeoffs WHERE UID = 2"
        ).fetchone()
        self.assertIsNone(child[0])

    def test_delete_takeoff_removes_annotations_linked_by_either_endpoint(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidTakeoffs (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                ParentUID INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (?, 1, NULL)",
            ((1,), (2,), (3,)),
        )
        for index, table in enumerate(TAKEOFF_REFERENCE_TABLES, start=1):
            conn.execute(
                f"""
                CREATE TABLE [{table}] (
                    UID INTEGER PRIMARY KEY,
                    BidTakeoffFromUID INTEGER,
                    BidTakeoffToUID INTEGER
                )
                """
            )
            conn.execute(
                f"""
                INSERT INTO [{table}]
                    (UID, BidTakeoffFromUID, BidTakeoffToUID)
                VALUES (?, 1, 2)
                """,
                (index,),
            )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["2"]))
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(1,), (3,)],
        )
        for table in TAKEOFF_REFERENCE_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    0,
                )

    def test_takeoff_insert_reserves_dangling_annotation_endpoint_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidDimensions " "(UID INTEGER, BidTakeoffFromUID INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (5, 1)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute("INSERT INTO BidTakeoffs VALUES (7, 1, 5, 3, X'00', NULL)")
        conn.execute("INSERT INTO BidDimensions VALUES (70, 8)")
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "malformed.mdb",
            "1",
            [
                InsertTakeoffSpec(
                    condition_uid="5",
                    page_uid="3",
                    area_uid=None,
                    position=[0.0, 0.0, 1.0, 1.0],
                )
            ],
        )
        self.assertEqual(result, ["9"])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidDimensions AS dimension "
                "INNER JOIN BidTakeoffs AS takeoff "
                "ON dimension.BidTakeoffFromUID=takeoff.UID"
            ).fetchone()[0],
            0,
        )

    def test_bulk_takeoff_insert_scans_uid_space_once(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (2, 1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "large.mdb",
            "1",
            [
                InsertTakeoffSpec("2", "3", None, [0.0, 0.0, 1.0, 1.0])
                for _index in range(100)
            ],
        )
        max_uid_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        self.assertEqual(len(result), 100)
        self.assertEqual(len(max_uid_queries), 2)

    def test_takeoff_insert_rejects_cross_bid_batch_before_any_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, BidAreaUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2)))
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((20, 1), (21, 2)))
        conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2)))
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "malformed.mdb",
            "1",
            [
                InsertTakeoffSpec("10", "20", "30", [0.0, 0.0, 1.0, 1.0]),
                InsertTakeoffSpec("11", "20", "30", [1.0, 1.0, 2.0, 2.0]),
            ],
        )
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_takeoff_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (10, 99)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).insert_takeoffs(
                "malformed.mdb",
                "99",
                [
                    InsertTakeoffSpec(
                        condition_uid="10",
                        page_uid="20",
                        area_uid=None,
                        position=[0.0, 0.0, 1.0, 1.0],
                    )
                ],
            )
        self.assertEqual(result, [])
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 0
        )

    def test_takeoff_insert_rejects_each_cross_bid_owner(self):
        for relationship in ("condition", "page", "area", "parent"):
            with self.subTest(relationship=relationship):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidPageUID INTEGER, BidAreaUID INTEGER, Position BLOB, "
                    "ParentUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2))
                )
                conn.executemany(
                    "INSERT INTO BidPages VALUES (?, ?)", ((20, 1), (21, 2))
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2))
                )
                conn.execute(
                    "INSERT INTO BidTakeoffs VALUES (40, 2, 11, 21, 31, X'00', NULL)"
                )
                condition_uid = "11" if relationship == "condition" else "10"
                page_uid = "21" if relationship == "page" else "20"
                area_uid = "31" if relationship == "area" else "30"
                parent_uid = "40" if relationship == "parent" else None
                result = _SqliteDuplicateOps(conn).insert_takeoffs(
                    "malformed.mdb",
                    "1",
                    [
                        InsertTakeoffSpec(
                            condition_uid,
                            page_uid,
                            area_uid,
                            [0.0, 0.0, 1.0, 1.0],
                            parent_uid=parent_uid,
                        )
                    ],
                )
                self.assertEqual(result, [])
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
                    [(40,)],
                )

    def test_takeoff_relationship_updates_reject_cross_bid_sets_atomically(self):
        for method_name, target_uid, expected_column in (
            ("save_takeoffs_condition", "11", "BidConditionUID"),
            ("save_takeoffs_area", "31", "BidAreaUID"),
        ):
            with self.subTest(method=method_name):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidAreaUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, ?, 10, 30)",
                    ((1, 1), (2, 2)),
                )
                conn.executemany(
                    "INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2))
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2))
                )
                operations = _SqliteDuplicateOps(conn)
                if method_name == "save_takeoffs_condition":
                    result = operations.save_takeoffs_condition(
                        "malformed.mdb", ["1", "2"], target_uid
                    )
                else:
                    result = operations.save_takeoffs_area(
                        "malformed.mdb", ["1", "2"], target_uid
                    )
                self.assertFalse(result)
                self.assertEqual(
                    conn.execute(
                        f"SELECT [{expected_column}] FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [
                        (10 if expected_column == "BidConditionUID" else 30,),
                        (10 if expected_column == "BidConditionUID" else 30,),
                    ],
                )

    def test_empty_takeoff_area_assignment_does_not_open_connection(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", [], "1"))
        self.assertEqual(ops.connection_count, 0)
        self.assertEqual(ops.executions, [])

    def test_unassigned_area_assignment_writes_null_for_single_takeoff(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1"], "0"))
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 1)
        query, params = ops.executions[0]
        self.assertEqual(
            query,
            "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
        )
        self.assertEqual(params, (None, 1))

    def test_small_takeoff_area_assignment_uses_one_chunked_statement(self):
        ops = _RecordingTakeoffOps()
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "7"))
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(len(ops.executions), 1)
        query, params = ops.executions[0]
        self.assertEqual(
            query,
            "UPDATE [BidTakeoffs] SET [BidAreaUID]=? " "WHERE [UID] IN (?,?,?)",
        )
        self.assertEqual(params, (7, 1, 2, 3))

    def test_large_takeoff_area_assignment_uses_access_safe_chunks(self):
        ops = _RecordingTakeoffOps()
        takeoff_uids = [str(uid) for uid in range(1, 302)]
        self.assertTrue(ops.save_takeoffs_area("bid.mdb", takeoff_uids, "7"))
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 7)
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidAreaUID]=?")
                for query, _params in ops.executions
            )
        )
        self.assertTrue(all(len(params) <= 51 for _query, params in ops.executions))
        self.assertEqual(ops.executions[0][1], tuple([7] + list(range(1, 51))))

    def test_condition_and_negative_updates_share_chunked_takeoff_path(self):
        condition_ops = _RecordingTakeoffOps()
        negative_ops = _RecordingTakeoffOps()
        takeoff_uids = [str(uid) for uid in range(1, 102)]
        self.assertTrue(
            condition_ops.save_takeoffs_condition("bid.mdb", takeoff_uids, "22")
        )
        self.assertTrue(
            negative_ops.set_takeoffs_negative("bid.mdb", takeoff_uids, True)
        )
        self.assertEqual(len(condition_ops.executions), 3)
        self.assertEqual(len(negative_ops.executions), 3)
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidConditionUID]=?")
                for query, _params in condition_ops.executions
            )
        )
        self.assertTrue(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [IsNegativeQuantity]=?")
                for query, _params in negative_ops.executions
            )
        )

    def test_takeoff_bulk_update_failure_rolls_back_all_chunks(self):
        ops = _RecordingTakeoffOps(fail_on_execute=2)
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR"):
            self.assertFalse(
                ops.save_takeoffs_area(
                    "bid.mdb", [str(uid) for uid in range(1, 102)], "3"
                )
            )
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.connection_count, 1)

    def test_takeoff_bulk_update_hy001_retries_row_by_row_fresh_transaction(self):
        ops = _RecordingTakeoffOps(fail_once_hy001=True)
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING"):
            self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "9"))
        self.assertEqual(ops.connection_count, 2)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.commits, 1)
        retry_queries = [query for query, _params in ops.executions[1:]]
        self.assertEqual(
            retry_queries,
            [
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
            ],
        )

    def test_delete_takeoffs_chunks_references_parent_cleanup_and_final_delete(self):
        schema = _RecordingSchema(
            {
                "BidTakeoffs": {"UID", "ParentUID"},
                "BidDimensions": {"BidTakeoffFromUID"},
                "BidPercents": {"BidTakeoffUID"},
            }
        )
        ops = _RecordingTakeoffOps(schema=schema)
        self.assertTrue(
            ops.delete_takeoffs("bid.mdb", [str(uid) for uid in range(1, 102)])
        )
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 12)
        self.assertEqual(
            [len(params) for _query, params in ops.executions],
            [50, 50, 1, 50, 50, 1, 51, 51, 2, 50, 50, 1],
        )
        self.assertEqual(
            [query.split(" WHERE ")[0] for query, _params in ops.executions],
            [
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidDimensions]",
                "DELETE FROM [BidPercents]",
                "DELETE FROM [BidPercents]",
                "DELETE FROM [BidPercents]",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "UPDATE [BidTakeoffs] SET [ParentUID]=?",
                "DELETE FROM [BidTakeoffs]",
                "DELETE FROM [BidTakeoffs]",
                "DELETE FROM [BidTakeoffs]",
            ],
        )


class TakeoffTextStylePersistenceTests(unittest.TestCase):
    def test_takeoff_text_styles_write_bid_takeoff_font_columns(self):
        writer = _text_style_support__TakeoffTextStyleWriter()
        self.assertTrue(
            writer.save_takeoff_text_properties(
                "bid.mdb",
                [
                    (
                        "9200",
                        {
                            "dimension_font_name": "Arial",
                            "dimension_font_color": 16711680,
                            "dimension_font_size": 72,
                            "dimension_font_bold": True,
                            "dimension_font_italic": False,
                            "dimension_font_underline": False,
                            "name_font_name": "Arial",
                            "name_font_color": 8388608,
                            "name_font_size": 48,
                            "name_font_bold": True,
                            "name_font_italic": False,
                            "name_font_underline": False,
                        },
                    )
                ],
            )
        )
        self.assertEqual(len(writer.calls), 1)
        table, values, required_columns, where_sql, params, operation = writer.calls[0]
        self.assertEqual(table, "BidTakeoffs")
        self.assertEqual(required_columns, ("UID",))
        self.assertEqual(where_sql, "[UID]=?")
        self.assertEqual(params, [9200])
        self.assertEqual(operation, "save_takeoff_text_properties")
        self.assertEqual(values["FontName"], "Arial")
        self.assertEqual(values["FontColor"], 16711680)
        self.assertEqual(values["FontSize"], 72)
        self.assertTrue(values["FontBold"])
        self.assertEqual(values["NameFontName"], "Arial")
        self.assertEqual(values["NameFontColor"], 8388608)
        self.assertEqual(values["NameFontSize"], 48)
        self.assertTrue(values["NameFontBold"])


class TakeoffLifecycleOwnershipTests(unittest.TestCase):
    def test_legacy_curve_change_cannot_save_geometry_without_curve_flag(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);
            CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, Position BLOB);
            INSERT INTO BidTakeoffs VALUES (7,1,X'00');
        """
        )
        self.assertFalse(
            _SchemaCheckedTakeoffOps(conn).set_takeoff_curve(
                "legacy.mdb", "7", [0, 0, 5, 5, 2, 4], 0
            )
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidTakeoffs").fetchone()[0], b"\x00"
        )

    def test_legacy_schema_cannot_silently_discard_requested_takeoff_state(self):
        from dataclasses import replace

        for column, change in (
            ("ParentUID", {"parent_uid": "7"}),
            ("Rotation", {"rotation": 0.25}),
            ("Curve", {"curve": 0}),
            ("IsNegativeQuantity", {"is_negative": True}),
            ("BidAreaUID", {"area_uid": "30"}),
        ):
            with self.subTest(column=column):
                conn = sqlite3.connect(":memory:")
                self.addCleanup(conn.close)
                conn.executescript(
                    """
                    CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);
                    CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER); INSERT INTO BidConditions VALUES (5,1);
                    CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER); INSERT INTO BidPages VALUES (3,1);
                    CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER); INSERT INTO BidAreas VALUES (30,1);
                """
                )
                optional = {
                    "ParentUID": "INTEGER",
                    "Rotation": "REAL",
                    "Curve": "INTEGER",
                    "IsNegativeQuantity": "INTEGER",
                    "BidAreaUID": "INTEGER",
                }
                optional.pop(column)
                definitions = ", ".join(
                    f"{name} {kind}" for name, kind in optional.items()
                )
                conn.execute(
                    f"CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, BidPageUID INTEGER, Position BLOB, {definitions})"
                )
                conn.execute(
                    "INSERT INTO BidTakeoffs (UID,BidUID,BidConditionUID,BidPageUID,Position) VALUES (7,1,5,3,X'00')"
                )
                spec = replace(InsertTakeoffSpec("5", "3", "0", [1, 1, 2, 2]), **change)
                self.assertEqual(
                    _SchemaCheckedTakeoffOps(conn).insert_takeoffs(
                        "legacy.mdb", "1", [spec]
                    ),
                    [],
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(7,)]
                )

    def test_insert_rejects_parent_on_another_page_before_any_write(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER);
            INSERT INTO Bids VALUES (1);
            CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidConditions VALUES (5, 1);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidPages VALUES (3, 1), (4, 1);
            CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER,
                BidConditionUID INTEGER, BidPageUID INTEGER, Position BLOB,
                ParentUID INTEGER);
            INSERT INTO BidTakeoffs VALUES (7, 1, 5, 3, X'00', 0);
        """
        )
        writer = _SqliteDuplicateOps(conn)
        result = writer.insert_takeoffs(
            "database",
            "1",
            [InsertTakeoffSpec("5", "4", "0", [0, 0, 1, 1], parent_uid="7")],
        )
        self.assertEqual(result, [])
        self.assertEqual(conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(7,)])
