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
from ost_visualizer.infrastructure.mdb.components.serialization import encode_position
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import BID_RELATIONSHIPS
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
        expected_after_success = {
            "positions": [
                (7, encode_position((10.0, 20.0), preserve_indices=frozenset((0, 1))))
                + (0.0, "Original"),
                (8, encode_position((30.0, 40.0), preserve_indices=frozenset((0, 1))))
                + (0.0, "Original"),
            ],
            "rotations": [(7, None, 45.0, "Original"), (8, None, 90.0, "Original")],
            "text properties": [
                (7, None, 0.0, "First"),
                (8, None, 0.0, "Second"),
            ],
        }
        for operation, mutate in operations:
            with self.subTest(operation=operation):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, Position BLOB, "
                    "Rotation REAL, NameFontName TEXT)"
                )
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, ?, NULL, 0, 'Original')",
                    ((7, 1), (8, 2)),
                )
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertFalse(mutate(_SqliteDuplicateOps(conn)))
                self.assertIn(
                    "BidTakeoffs mutation targets do not belong to one "
                    "authoritative Bid",
                    logs.output[0],
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position, Rotation, NameFontName "
                        "FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(7, None, 0.0, "Original"), (8, None, 0.0, "Original")],
                )
                # Control: the identical batch succeeds once both rows share a Bid.
                conn.execute("UPDATE BidTakeoffs SET BidUID=1")
                self.assertTrue(mutate(_SqliteDuplicateOps(conn)))
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position, Rotation, NameFontName "
                        "FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    expected_after_success[operation],
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
            (
                (7, None, None, None, None),
                (8, 7, 7, 7, 7),
                (9, 8, 8, 8, 8),
                (10, 7, 8, 7, 8),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs ORDER BY UID"
            ).fetchall(),
            [
                (8, None, None, None, None),
                (9, 8, 8, 8, 8),
                (10, None, 8, None, 8),
            ],
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
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (3, 1, NULL)"
        )
        conn.execute(
            "INSERT INTO BidTakeoffs (UID, BidUID, ParentUID) VALUES (4, 1, 3)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["1"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs ORDER BY UID"
            ).fetchall(),
            [(2, None), (3, None), (4, 3)],
        )

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
            conn.executemany(
                f"""
                INSERT INTO [{table}]
                    (UID, BidTakeoffFromUID, BidTakeoffToUID)
                VALUES (?, ?, ?)
                """,
                (
                    (index * 10 + 1, 1, 2),
                    (index * 10 + 2, 2, 3),
                    (index * 10 + 3, 1, 3),
                ),
            )
        self.assertTrue(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["2"]))
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(1,), (3,)],
        )
        for index, table in enumerate(TAKEOFF_REFERENCE_TABLES, start=1):
            with self.subTest(table=table):
                # Rows ending at the deleted takeoff and rows starting at it are
                # both removed; the link between two survivors remains.
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidTakeoffFromUID, BidTakeoffToUID "
                        f"FROM [{table}] ORDER BY UID"
                    ).fetchall(),
                    [(index * 10 + 3, 1, 3)],
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

    def test_takeoff_insert_reserves_every_inbound_takeoff_reference_column(self):
        references = sorted(
            {
                (relationship.child_table, relationship.child_column)
                for relationship in BID_RELATIONSHIPS
                if relationship.parent_table == "BidTakeoffs"
                and relationship.parent_column == "UID"
            }
        )
        self.assertEqual(
            references,
            [
                ("BidALines", "BidTakeoffFromUID"),
                ("BidALines", "BidTakeoffToUID"),
                ("BidArrows", "BidTakeoffFromUID"),
                ("BidArrows", "BidTakeoffToUID"),
                ("BidDimensions", "BidTakeoffFromUID"),
                ("BidDimensions", "BidTakeoffToUID"),
                ("BidPercents", "BidTakeoffUID"),
                ("BidTakeoffs", "ParentUID"),
                ("BidTakeoffs", "TypGroupMarkerUID"),
                ("BidTakeoffs", "TypGroupTakeoffUID"),
                ("BidTakeoffs", "TypPageTakeoffUID"),
            ],
        )
        for child_table, child_column in references:
            with self.subTest(table=child_table, column=child_column):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
                conn.execute("INSERT INTO BidConditions VALUES (5, 1)")
                conn.execute("INSERT INTO BidPages VALUES (3, 1)")
                takeoff_columns = (
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidPageUID INTEGER, Position BLOB, ParentUID INTEGER"
                )
                if child_table == "BidTakeoffs" and child_column != "ParentUID":
                    takeoff_columns += f", {child_column} INTEGER"
                conn.execute(f"CREATE TABLE BidTakeoffs ({takeoff_columns})")
                conn.execute(
                    "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, "
                    "BidPageUID, Position) VALUES (7, 1, 5, 3, X'00')"
                )
                if child_table == "BidTakeoffs":
                    conn.execute(f"UPDATE BidTakeoffs SET {child_column}=8 WHERE UID=7")
                else:
                    conn.execute(
                        f"CREATE TABLE [{child_table}] (UID INTEGER, {child_column} INTEGER)"
                    )
                    conn.execute(f"INSERT INTO [{child_table}] VALUES (70, 8)")
                result = _SqliteDuplicateOps(conn).insert_takeoffs(
                    "malformed.mdb",
                    "1",
                    [InsertTakeoffSpec("5", "3", None, [0.0, 0.0, 1.0, 1.0])],
                )
                self.assertEqual(result, ["9"])

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
        self.assertEqual(result, [str(uid) for uid in range(1, 101)])
        self.assertEqual(len(max_uid_queries), 2)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(uid,) for uid in range(1, 101)],
        )

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
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).insert_takeoffs(
                "malformed.mdb",
                "1",
                [
                    InsertTakeoffSpec("10", "20", "30", [0.0, 0.0, 1.0, 1.0]),
                    InsertTakeoffSpec("11", "20", "30", [1.0, 1.0, 2.0, 2.0]),
                ],
            )
        self.assertEqual(result, [])
        self.assertIn(
            "BidConditions.UID=11 does not belong to Bids.UID=1", logs.output[0]
        )
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
        statements = []
        conn.set_trace_callback(statements.append)
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
            [sql for sql in statements if "MAX(" in sql.upper()],
            [],
        )
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
                owner_table = {
                    "condition": "BidConditions",
                    "page": "BidPages",
                    "area": "BidAreas",
                    "parent": "BidTakeoffs",
                }[relationship]
                owner_uid = {
                    "condition": 11,
                    "page": 21,
                    "area": 31,
                    "parent": 40,
                }[relationship]
                with self.assertLogs("test", level="ERROR") as logs:
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
                self.assertIn(
                    f"{owner_table}.UID={owner_uid} does not belong to Bids.UID=1",
                    logs.output[0],
                )
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
                    [(40,)],
                )

    def test_takeoff_insert_accepts_same_bid_owners(self):
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
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((10, 1), (11, 2)))
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((20, 1), (21, 2)))
        conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (40, 1, 10, 20, 30, X'00', NULL)")
        result = _SqliteDuplicateOps(conn).insert_takeoffs(
            "malformed.mdb",
            "1",
            [
                InsertTakeoffSpec(
                    "10", "20", "30", [0.0, 0.0, 1.0, 1.0], parent_uid="40"
                )
            ],
        )
        self.assertEqual(result, ["41"])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidConditionUID, BidPageUID, BidAreaUID, "
                "ParentUID FROM BidTakeoffs WHERE UID=41"
            ).fetchall(),
            [(41, 1, 10, 20, 30, 40)],
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

    def test_takeoff_relationship_updates_reject_cross_bid_target_owner(self):
        for method_name, target_uid, expected_column, owner_message in (
            (
                "save_takeoffs_condition",
                "11",
                "BidConditionUID",
                "BidConditions.UID=11 does not belong to Bids.UID=1",
            ),
            (
                "save_takeoffs_area",
                "31",
                "BidAreaUID",
                "BidAreas.UID=31 does not belong to Bids.UID=1",
            ),
        ):
            with self.subTest(method=method_name):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.execute(
                    "CREATE TABLE BidTakeoffs ("
                    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
                    "BidAreaUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
                conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
                conn.executemany(
                    "INSERT INTO BidTakeoffs VALUES (?, 1, 10, 30)", ((1,), (2,))
                )
                conn.executemany(
                    "INSERT INTO BidConditions VALUES (?, ?)",
                    ((10, 1), (11, 2), (12, 1)),
                )
                conn.executemany(
                    "INSERT INTO BidAreas VALUES (?, ?)", ((30, 1), (31, 2), (32, 1))
                )
                operations = _SqliteDuplicateOps(conn)
                update = {
                    "save_takeoffs_condition": operations.save_takeoffs_condition,
                    "save_takeoffs_area": operations.save_takeoffs_area,
                }[method_name]
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertFalse(update("malformed.mdb", ["1", "2"], target_uid))
                self.assertIn(owner_message, logs.output[0])
                original = 10 if expected_column == "BidConditionUID" else 30
                self.assertEqual(
                    conn.execute(
                        f"SELECT [{expected_column}] FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(original,), (original,)],
                )
                # Control: a same-bid target updates the whole selected set.
                same_bid_target = "12" if expected_column == "BidConditionUID" else "32"
                self.assertTrue(update("malformed.mdb", ["1", "2"], same_bid_target))
                self.assertEqual(
                    conn.execute(
                        f"SELECT [{expected_column}] FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(int(same_bid_target),), (int(same_bid_target),)],
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
        self.assertEqual(
            [len(params) - 1 for _query, params in ops.executions],
            [50, 50, 50, 50, 50, 50, 1],
        )
        self.assertEqual(
            [uid for _query, params in ops.executions for uid in params[1:]],
            list(range(1, 302)),
        )
        self.assertEqual({params[0] for _query, params in ops.executions}, {7})
        self.assertEqual(
            ops.executions[-1][0],
            "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?",
        )

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
        for ops, value in ((condition_ops, 22), (negative_ops, True)):
            self.assertEqual({params[0] for _query, params in ops.executions}, {value})
            self.assertEqual(
                [uid for _query, params in ops.executions for uid in params[1:]],
                list(range(1, 102)),
            )
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
        # The failure stops the chunk loop: the third chunk is never attempted.
        self.assertEqual(len(ops.executions), 2)

    def test_takeoff_bulk_update_hy001_retries_row_by_row_fresh_transaction(self):
        ops = _RecordingTakeoffOps(fail_once_hy001=True)
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING"):
            self.assertTrue(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "9"))
        self.assertEqual(ops.connection_count, 2)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(
            ops.executions[0],
            (
                "UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID] IN (?,?,?)",
                (9, 1, 2, 3),
            ),
        )
        self.assertEqual(
            ops.executions[1:],
            [
                ("UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?", (9, 1)),
                ("UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?", (9, 2)),
                ("UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?", (9, 3)),
            ],
        )

    def test_takeoff_bulk_update_retry_failure_returns_false_and_rolls_back(self):
        class AlwaysFailing(_RecordingTakeoffOps):
            @property
            def fail_on_execute(self):
                return self.execute_count

            @fail_on_execute.setter
            def fail_on_execute(self, _value):
                pass

            def _is_access_resource_exceeded(self, _exc):
                return True

        ops = AlwaysFailing()
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR"):
            self.assertFalse(ops.save_takeoffs_area("bid.mdb", ["1", "2"], "9"))
        self.assertEqual(ops.connection_count, 2)
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 2)
        self.assertEqual(len(ops.executions), 2)

    def test_takeoff_assignment_rejects_invalid_identifiers_without_connection(self):
        for label, call in (
            ("area", lambda ops: ops.save_takeoffs_area("bid.mdb", ["1"], "abc")),
            (
                "condition",
                lambda ops: ops.save_takeoffs_condition("bid.mdb", ["1"], "abc"),
            ),
            ("takeoff", lambda ops: ops.save_takeoffs_area("bid.mdb", ["x"], "7")),
            (
                "string collection",
                lambda ops: ops.save_takeoffs_area("bid.mdb", "12", "7"),
            ),
            ("negative", lambda ops: ops.set_takeoffs_negative("bid.mdb", ["x"], True)),
            ("delete", lambda ops: ops.delete_takeoffs("bid.mdb", ["x"])),
        ):
            with self.subTest(label=label):
                ops = _RecordingTakeoffOps()
                with self.assertLogs("tests.recording_takeoff_ops", level="WARNING"):
                    self.assertFalse(call(ops))
                self.assertEqual(ops.connection_count, 0)
                self.assertEqual(ops.executions, [])

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
        for start in (0, 3, 6, 9):
            phase = ops.executions[start : start + 3]
            offset = 1 if start == 6 else 0
            self.assertEqual(
                [uid for _query, params in phase for uid in params[offset:]],
                list(range(1, 102)),
            )
        self.assertEqual(
            {params[0] for _query, params in ops.executions[6:9]},
            {None},
        )
        self.assertEqual(
            [query.split(" WHERE ")[0] for query, _params in ops.executions[:1]],
            ["DELETE FROM [BidDimensions]"],
        )
        self.assertIn("[BidTakeoffFromUID]", ops.executions[0][0])
        self.assertIn("[BidTakeoffUID]", ops.executions[3][0])
        self.assertIn("WHERE [ParentUID] IN", ops.executions[6][0])
        self.assertTrue(ops.executions[2][0].endswith("WHERE [BidTakeoffFromUID]=?"))
        self.assertTrue(ops.executions[11][0].endswith("WHERE [UID]=?"))

    def test_delete_takeoffs_covers_both_endpoints_and_every_self_reference(self):
        schema = _RecordingSchema(
            {
                "BidTakeoffs": {
                    "UID",
                    "ParentUID",
                    "TypGroupTakeoffUID",
                    "TypPageTakeoffUID",
                    "TypGroupMarkerUID",
                },
                "BidDimensions": {"BidTakeoffFromUID", "BidTakeoffToUID"},
                "BidALines": {"BidTakeoffFromUID", "BidTakeoffToUID"},
                "BidArrows": {"BidTakeoffFromUID", "BidTakeoffToUID"},
                "BidPercents": {"BidTakeoffUID"},
            }
        )
        ops = _RecordingTakeoffOps(schema=schema)
        self.assertTrue(ops.delete_takeoffs("bid.mdb", ["4", "5"]))
        self.assertEqual(
            ops.executions,
            [
                (
                    "DELETE FROM [BidDimensions] WHERE [BidTakeoffFromUID] IN (?,?)",
                    (4, 5),
                ),
                (
                    "DELETE FROM [BidDimensions] WHERE [BidTakeoffToUID] IN (?,?)",
                    (4, 5),
                ),
                ("DELETE FROM [BidALines] WHERE [BidTakeoffFromUID] IN (?,?)", (4, 5)),
                ("DELETE FROM [BidALines] WHERE [BidTakeoffToUID] IN (?,?)", (4, 5)),
                ("DELETE FROM [BidArrows] WHERE [BidTakeoffFromUID] IN (?,?)", (4, 5)),
                ("DELETE FROM [BidArrows] WHERE [BidTakeoffToUID] IN (?,?)", (4, 5)),
                ("DELETE FROM [BidPercents] WHERE [BidTakeoffUID] IN (?,?)", (4, 5)),
                (
                    "UPDATE [BidTakeoffs] SET [ParentUID]=? WHERE [ParentUID] IN (?,?)",
                    (None, 4, 5),
                ),
                (
                    "UPDATE [BidTakeoffs] SET [TypGroupTakeoffUID]=? "
                    "WHERE [TypGroupTakeoffUID] IN (?,?)",
                    (None, 4, 5),
                ),
                (
                    "UPDATE [BidTakeoffs] SET [TypPageTakeoffUID]=? "
                    "WHERE [TypPageTakeoffUID] IN (?,?)",
                    (None, 4, 5),
                ),
                (
                    "UPDATE [BidTakeoffs] SET [TypGroupMarkerUID]=? "
                    "WHERE [TypGroupMarkerUID] IN (?,?)",
                    (None, 4, 5),
                ),
                ("DELETE FROM [BidTakeoffs] WHERE [UID] IN (?,?)", (4, 5)),
            ],
        )

    def test_delete_takeoffs_hy001_retries_row_by_row_in_fresh_transaction(self):
        schema = _RecordingSchema({"BidTakeoffs": {"UID"}})
        ops = _RecordingTakeoffOps(schema=schema, fail_once_hy001=True)
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING"):
            self.assertTrue(ops.delete_takeoffs("bid.mdb", ["1", "2"]))
        self.assertEqual(ops.connection_count, 2)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(
            ops.executions,
            [
                ("DELETE FROM [BidTakeoffs] WHERE [UID] IN (?,?)", (1, 2)),
                ("DELETE FROM [BidTakeoffs] WHERE [UID]=?", (1,)),
                ("DELETE FROM [BidTakeoffs] WHERE [UID]=?", (2,)),
            ],
        )

    def test_delete_takeoffs_non_resource_failure_rolls_back_without_retry(self):
        schema = _RecordingSchema({"BidTakeoffs": {"UID"}})
        ops = _RecordingTakeoffOps(schema=schema, fail_on_execute=1)
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR"):
            self.assertFalse(ops.delete_takeoffs("bid.mdb", ["1", "2"]))
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(len(ops.executions), 1)


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
        self.assertEqual(
            values,
            {
                "FontName": "Arial",
                "FontColor": 16711680,
                "FontSize": 72,
                "FontBold": True,
                "FontItalic": False,
                "FontUnderline": False,
                "NameFontName": "Arial",
                "NameFontColor": 8388608,
                "NameFontSize": 48,
                "NameFontBold": True,
                "NameFontItalic": False,
                "NameFontUnderline": False,
            },
        )

    def test_takeoff_text_styles_ignore_unknown_keys_and_skip_empty_updates(self):
        writer = _text_style_support__TakeoffTextStyleWriter()
        self.assertTrue(writer.save_takeoff_text_properties("bid.mdb", []))
        self.assertEqual(writer.calls, [])
        self.assertTrue(
            writer.save_takeoff_text_properties(
                "bid.mdb",
                [
                    ("9200", {"unknown_property": 1}),
                    ("9201", {"name_font_italic": True, "unknown_property": 1}),
                ],
            )
        )
        self.assertEqual(
            writer.calls,
            [
                (
                    "BidTakeoffs",
                    {"NameFontItalic": True},
                    ("UID",),
                    "[UID]=?",
                    [9201],
                    "save_takeoff_text_properties",
                )
            ],
        )


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
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SchemaCheckedTakeoffOps(conn).set_takeoff_curve(
                    "legacy.mdb", "7", [0, 0, 5, 5, 2, 4], 0
                )
            )
        self.assertIn("Missing BidTakeoffs.Curve", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Position FROM BidTakeoffs").fetchone()[0], b"\x00"
        )

    def test_curve_change_writes_geometry_and_curve_flag_together(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);
            CREATE TABLE BidTakeoffs (
                UID INTEGER, BidUID INTEGER, Position BLOB, Curve INTEGER);
            INSERT INTO BidTakeoffs VALUES (7,1,X'00',-1);
        """
        )
        position = [0, 0, 5, 5, 2, 4]
        self.assertTrue(
            _SchemaCheckedTakeoffOps(conn).set_takeoff_curve(
                "bid.mdb", "7", position, 0
            )
        )
        self.assertEqual(
            conn.execute("SELECT Position, Curve FROM BidTakeoffs").fetchall(),
            [
                (
                    encode_position(position, preserve_indices=frozenset(range(6))),
                    0,
                )
            ],
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
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertEqual(
                        _SchemaCheckedTakeoffOps(conn).insert_takeoffs(
                            "legacy.mdb", "1", [spec]
                        ),
                        [],
                    )
                self.assertIn(f"Missing BidTakeoffs.{column}", logs.output[0])
                self.assertEqual(
                    conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(7,)]
                )

    def test_legacy_schema_accepts_insert_that_requests_no_optional_state(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        conn.executescript(
            """
            CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);
            CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER); INSERT INTO BidConditions VALUES (5,1);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER); INSERT INTO BidPages VALUES (3,1);
            CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, BidPageUID INTEGER, Position BLOB);
            INSERT INTO BidTakeoffs VALUES (7,1,5,3,X'00');
        """
        )
        self.assertEqual(
            _SchemaCheckedTakeoffOps(conn).insert_takeoffs(
                "legacy.mdb", "1", [InsertTakeoffSpec("5", "3", "0", [1, 1, 2, 2])]
            ),
            ["8"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidConditionUID, BidPageUID FROM BidTakeoffs "
                "WHERE UID=8"
            ).fetchall(),
            [(8, 1, 5, 3)],
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
        with self.assertLogs("test", level="ERROR") as logs:
            result = writer.insert_takeoffs(
                "database",
                "1",
                [InsertTakeoffSpec("5", "4", "0", [0, 0, 1, 1], parent_uid="7")],
            )
        self.assertEqual(result, [])
        self.assertIn(
            "A Takeoff and its parent must belong to the same Page", logs.output[0]
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(7,)])
        same_page = writer.insert_takeoffs(
            "database",
            "1",
            [InsertTakeoffSpec("5", "3", "0", [0, 0, 1, 1], parent_uid="7")],
        )
        self.assertEqual(same_page, ["8"])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageUID, ParentUID FROM BidTakeoffs"
            ).fetchall(),
            [(7, 3, 0), (8, 3, 7)],
        )
