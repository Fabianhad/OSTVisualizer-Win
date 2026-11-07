import logging
import re
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
from tests.helpers.mdb.real_write_contract import (
    ListParamConnection,
    ListParamCursor,
    RealContractOps,
    contract_db,
)
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
                (7, b"10.0;20.0\n", 0.0, "Original"),
                (8, b"30.0;40.0\n", 0.0, "Original"),
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
                    self.assertIs(mutate(_SqliteDuplicateOps(conn)), False)
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
                self.assertIs(mutate(_SqliteDuplicateOps(conn)), True)
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
            self.assertIs(
                _SqliteMdbOps(conn).set_takeoffs_negative("malformed.mdb", ["7"], True),
                False,
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
            self.assertIs(
                _SqliteMdbOps(conn).delete_takeoffs("malformed.mdb", ["7"]),
                False,
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
        self.assertIs(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["7"]), True)
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
        self.assertIs(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["1"]), True)
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
        for index, table in enumerate(
            ("BidDimensions", "BidALines", "BidArrows"), start=1
        ):
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
        self.assertIs(_SqliteMdbOps(conn).delete_takeoffs("bid.mdb", ["2"]), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(1,), (3,)],
        )
        for index, table in enumerate(
            ("BidDimensions", "BidALines", "BidArrows"), start=1
        ):
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
                with self.assertLogs("test", level="ERROR") as logs:
                    if method_name == "save_takeoffs_condition":
                        result = operations.save_takeoffs_condition(
                            "malformed.mdb", ["1", "2"], target_uid
                        )
                    else:
                        result = operations.save_takeoffs_area(
                            "malformed.mdb", ["1", "2"], target_uid
                        )
                self.assertIs(result, False)
                self.assertIn(
                    "BidTakeoffs mutation targets do not belong to one "
                    "authoritative Bid",
                    logs.output[0],
                )
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
                    self.assertIs(
                        update("malformed.mdb", ["1", "2"], target_uid), False
                    )
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
                self.assertIs(
                    update("malformed.mdb", ["1", "2"], same_bid_target), True
                )
                self.assertEqual(
                    conn.execute(
                        f"SELECT [{expected_column}] FROM BidTakeoffs ORDER BY UID"
                    ).fetchall(),
                    [(int(same_bid_target),), (int(same_bid_target),)],
                )

    def test_empty_takeoff_area_assignment_does_not_open_connection(self):
        ops = _RecordingTakeoffOps()
        self.assertIs(ops.save_takeoffs_area("bid.mdb", [], "1"), True)
        self.assertEqual(ops.connection_count, 0)
        self.assertEqual(ops.executions, [])

    def test_unassigned_area_assignment_writes_null_for_single_takeoff(self):
        ops = _RecordingTakeoffOps()
        self.assertIs(ops.save_takeoffs_area("bid.mdb", ["1"], "0"), True)
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
        self.assertIs(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "7"), True)
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
        self.assertIs(ops.save_takeoffs_area("bid.mdb", takeoff_uids, "7"), True)
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 1)
        self.assertEqual(ops.rollbacks, 0)
        self.assertEqual(len(ops.executions), 7)
        self.assertIs(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidAreaUID]=?")
                for query, _params in ops.executions
            ),
            True,
        )
        self.assertIs(all(len(params) <= 51 for _query, params in ops.executions), True)
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
        self.assertIs(
            condition_ops.save_takeoffs_condition("bid.mdb", takeoff_uids, "22"),
            True,
        )
        self.assertIs(
            negative_ops.set_takeoffs_negative("bid.mdb", takeoff_uids, True),
            True,
        )
        self.assertEqual(len(condition_ops.executions), 3)
        self.assertEqual(len(negative_ops.executions), 3)
        for ops, value in ((condition_ops, 22), (negative_ops, True)):
            self.assertEqual({params[0] for _query, params in ops.executions}, {value})
            self.assertEqual(
                [uid for _query, params in ops.executions for uid in params[1:]],
                list(range(1, 102)),
            )
        self.assertIs(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [BidConditionUID]=?")
                for query, _params in condition_ops.executions
            ),
            True,
        )
        self.assertIs(
            all(
                query.startswith("UPDATE [BidTakeoffs] SET [IsNegativeQuantity]=?")
                for query, _params in negative_ops.executions
            ),
            True,
        )

    def test_takeoff_bulk_update_failure_rolls_back_all_chunks(self):
        ops = _RecordingTakeoffOps(fail_on_execute=2)
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR") as logs:
            self.assertIs(
                ops.save_takeoffs_area(
                    "bid.mdb", [str(uid) for uid in range(1, 102)], "3"
                ),
                False,
            )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to save takeoffs area in bid.mdb"],
        )
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(ops.connection_count, 1)
        # The failure stops the chunk loop: the third chunk is never attempted.
        self.assertEqual(len(ops.executions), 2)

    def test_takeoff_bulk_update_hy001_retries_row_by_row_fresh_transaction(self):
        ops = _RecordingTakeoffOps(fail_once_hy001=True)
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING") as logs:
            self.assertIs(ops.save_takeoffs_area("bid.mdb", ["1", "2", "3"], "9"), True)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Access resource limit while saving takeoffs area for 3 takeoffs "
                "with chunk size 50; retrying row-by-row in a fresh transaction."
            ],
        )
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
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING") as logs:
            self.assertIs(ops.save_takeoffs_area("bid.mdb", ["1", "2"], "9"), False)
        self.assertEqual(
            [(record.levelname, record.getMessage()) for record in logs.records],
            [
                (
                    "WARNING",
                    "Access resource limit while saving takeoffs area for 2 "
                    "takeoffs with chunk size 50; retrying row-by-row in a fresh "
                    "transaction.",
                ),
                ("ERROR", "Failed to save takeoffs area row-by-row in bid.mdb"),
            ],
        )
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
                    self.assertIs(call(ops), False)
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
        self.assertIs(
            ops.delete_takeoffs("bid.mdb", [str(uid) for uid in range(1, 102)]), True
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
        self.assertIs(
            ops.executions[2][0].endswith("WHERE [BidTakeoffFromUID]=?"), True
        )
        self.assertIs(ops.executions[11][0].endswith("WHERE [UID]=?"), True)

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
        self.assertIs(ops.delete_takeoffs("bid.mdb", ["4", "5"]), True)
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
        with self.assertLogs("tests.recording_takeoff_ops", level="WARNING") as logs:
            self.assertIs(ops.delete_takeoffs("bid.mdb", ["1", "2"]), True)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Access resource limit while deleting 2 takeoffs with chunk size "
                "50; retrying row-by-row in a fresh transaction."
            ],
        )
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
        with self.assertLogs("tests.recording_takeoff_ops", level="ERROR") as logs:
            self.assertIs(ops.delete_takeoffs("bid.mdb", ["1", "2"]), False)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Failed to delete takeoffs in bid.mdb"],
        )
        self.assertEqual(ops.connection_count, 1)
        self.assertEqual(ops.commits, 0)
        self.assertEqual(ops.rollbacks, 1)
        self.assertEqual(len(ops.executions), 1)


class TakeoffTextStylePersistenceTests(unittest.TestCase):
    def test_takeoff_text_styles_write_bid_takeoff_font_columns(self):
        writer = _text_style_support__TakeoffTextStyleWriter()
        self.assertIs(
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
            ),
            True,
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
        self.assertIs(writer.save_takeoff_text_properties("bid.mdb", []), True)
        self.assertEqual(writer.calls, [])
        self.assertIs(
            writer.save_takeoff_text_properties(
                "bid.mdb",
                [
                    ("9200", {"unknown_property": 1}),
                    ("9201", {"name_font_italic": True, "unknown_property": 1}),
                ],
            ),
            True,
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
            self.assertIs(
                _SchemaCheckedTakeoffOps(conn).set_takeoff_curve(
                    "legacy.mdb", "7", [0, 0, 5, 5, 2, 4], 0
                ),
                False,
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
        self.assertIs(
            _SchemaCheckedTakeoffOps(conn).set_takeoff_curve(
                "bid.mdb", "7", position, 0
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Position, Curve FROM BidTakeoffs").fetchall(),
            [(b"0.0;0.0;5.0;5.0;2.0;4.0\n", 0)],
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


class _RollingBackConnection(ListParamConnection):
    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        return False


class _TransactionalContractOps(RealContractOps):
    def _connection(self, _db_path):
        return _RollingBackConnection(self._connection_ref)


class _PropagatingContractOps(RealContractOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class _PlannedCursor(ListParamCursor):
    def __init__(self, connection, plan, statements):
        super().__init__(connection)
        self._plan = plan
        self._statements = statements

    def execute(self, query, *params):
        if query.lstrip().upper().startswith(("UPDATE", "DELETE")):
            index = len(self._statements)
            self._statements.append((query, params))
            error = self._plan(index)
            if error is not None:
                raise error
        return super().execute(query, *params)


class _PlannedConnection(_RollingBackConnection):
    def __init__(self, connection, plan, statements, events):
        super().__init__(connection)
        self._plan = plan
        self._statements = statements
        self._events = events

    def cursor(self):
        return _PlannedCursor(self._connection, self._plan, self._statements)

    def __exit__(self, exc_type, exc, tb):
        self._events.append("commit" if exc_type is None else "rollback")
        return super().__exit__(exc_type, exc, tb)


class _PlannedFailureOps(RealContractOps):
    """Transactional sqlite ops whose Nth write statement can be made to fail."""

    def __init__(self, connection, plan):
        super().__init__(connection)
        self.plan = plan
        self.statements = []
        self.events = []

    def _connection(self, _db_path):
        return _PlannedConnection(
            self._connection_ref, self.plan, self.statements, self.events
        )


def _hy001():
    return pyodbc.OperationalError(
        "HY001",
        "[HY001] [Microsoft][ODBC Microsoft Access Driver] System resource exceeded.",
    )


_TAKEOFF_COLUMNS = (
    "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, BidPageUID INTEGER, "
    "BidAreaUID INTEGER, Position BLOB, Rotation REAL, Curve INTEGER, "
    "ParentUID INTEGER, IsNegativeQuantity INTEGER, GUID TEXT, "
    "BidZoneUID INTEGER DEFAULT 99, TypGroupUID INTEGER DEFAULT 99, "
    "BidTypAreaUID INTEGER DEFAULT 99, TypGroupTakeoffUID INTEGER, "
    "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER, "
    "FontName TEXT, NameFontName TEXT, NameFontSize REAL"
)


def _takeoff_database(*extra):
    return contract_db(
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "INSERT INTO Bids VALUES (2)",
        "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidConditions VALUES (5, 1)",
        "INSERT INTO BidConditions VALUES (6, 2)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (3, 1)",
        "INSERT INTO BidPages VALUES (4, 1)",
        "INSERT INTO BidPages VALUES (9, 2)",
        "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidAreas VALUES (30, 1)",
        "INSERT INTO BidAreas VALUES (31, 2)",
        f"CREATE TABLE BidTakeoffs ({_TAKEOFF_COLUMNS})",
        *extra,
    )


_GUID_PATTERN = re.compile(
    r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$"
)


class TakeoffInsertPersistenceTests(unittest.TestCase):
    def database(self, *extra):
        conn = _takeoff_database(
            "INSERT INTO BidTakeoffs (UID, BidUID, BidConditionUID, BidPageUID, "
            "Position, ParentUID) VALUES (7, 1, 5, 3, X'00', 0)",
            *extra,
        )
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def rows(conn, columns, where="UID<>7"):
        return conn.execute(
            f"SELECT {columns} FROM BidTakeoffs WHERE {where} ORDER BY UID"
        ).fetchall()

    def test_insert_persists_every_typed_value_and_allocates_consecutive_uids(self):
        conn = self.database()
        result = RealContractOps(conn).insert_takeoffs(
            "x.mdb",
            "1",
            [
                InsertTakeoffSpec(
                    "5",
                    "3",
                    "30",
                    [1.5, 2.25, 3, 4],
                    parent_uid="7",
                    curve=0,
                    rotation=0.5,
                    is_negative=True,
                ),
                InsertTakeoffSpec("5", "4", "0", [0, 0, 1, 1]),
            ],
        )
        self.assertEqual(result, ["8", "9"])
        self.assertEqual(
            self.rows(
                conn,
                "UID, BidUID, BidConditionUID, BidPageUID, BidAreaUID, Position, "
                "Rotation, Curve, ParentUID, IsNegativeQuantity",
            ),
            [
                (8, 1, 5, 3, 30, b"1.5;2.25;3.0;4.0\n", 0.5, 0, 7, 1),
                (9, 1, 5, 4, None, b"0.0;0.0;1.0;1.0\n", 0.0, -1, 0, 0),
            ],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs WHERE UID=7"
            ).fetchall(),
            [(7, 0)],
        )

    def test_insert_preserves_unrounded_position_precision(self):
        conn = self.database()
        result = RealContractOps(conn).insert_takeoffs(
            "x.mdb", "1", [InsertTakeoffSpec("5", "3", None, [0.1234567, 100.0005])]
        )
        self.assertEqual(result, ["8"])
        self.assertEqual(self.rows(conn, "Position"), [(b"0.1234567;100.0005\n",)])

    def test_zero_like_parent_uids_store_zero_without_validation(self):
        conn = self.database()
        result = RealContractOps(conn).insert_takeoffs(
            "x.mdb",
            "1",
            [
                InsertTakeoffSpec("5", "3", "0", [0, 0, 1, 1], parent_uid=parent)
                for parent in (None, "", 0, "0")
            ],
        )
        self.assertEqual(result, ["8", "9", "10", "11"])
        self.assertEqual(
            self.rows(conn, "UID, ParentUID"), [(8, 0), (9, 0), (10, 0), (11, 0)]
        )

    _EXTRAS = {
        # Typed and undeclared columns come first: skipping them must not stop the scan.
        "UID": 999,
        "NotAColumn": 1,
        "BidUID": 2,
        "BidConditionUID": 6,
        "BidPageUID": 9,
        "BidAreaUID": 31,
        "Position": b"x",
        "Rotation": 9.0,
        "Curve": 5,
        "ParentUID": 123,
        "IsNegativeQuantity": 1,
        "GUID": "{OLD-GUID}",
        "BidZoneUID": 77,
        "TypGroupUID": 5,
        "BidTypAreaUID": 6,
        "TypGroupTakeoffUID": 7,
        "TypPageTakeoffUID": 8,
        "TypGroupMarkerUID": 9,
        "FontName": "Arial",
    }

    def test_raw_extras_keep_declared_columns_and_regenerate_the_guid(self):
        for source_bid in (None, "1", 1):
            with self.subTest(source_bid_uid=source_bid):
                conn = self.database()
                result = RealContractOps(conn).insert_takeoffs(
                    "x.mdb",
                    "1",
                    [
                        InsertTakeoffSpec(
                            "5",
                            "3",
                            "0",
                            [0, 0, 1, 1],
                            raw_extras=dict(self._EXTRAS),
                            source_bid_uid=source_bid,
                        )
                        for _ in range(2)
                    ],
                )
                self.assertEqual(result, ["8", "9"])
                rows = self.rows(
                    conn,
                    "UID, BidUID, BidConditionUID, BidPageUID, BidAreaUID, Position, "
                    "Rotation, Curve, ParentUID, IsNegativeQuantity, BidZoneUID, "
                    "TypGroupUID, BidTypAreaUID, TypGroupTakeoffUID, "
                    "TypPageTakeoffUID, TypGroupMarkerUID, FontName, GUID",
                )
                self.assertEqual(
                    [row[:-1] for row in rows],
                    [
                        (
                            uid,
                            1,
                            5,
                            3,
                            None,
                            b"0.0;0.0;1.0;1.0\n",
                            0.0,
                            -1,
                            0,
                            0,
                            77,
                            5,
                            6,
                            7,
                            8,
                            9,
                            "Arial",
                        )
                        for uid in (8, 9)
                    ],
                )
                guids = [row[-1] for row in rows]
                self.assertEqual(len(set(guids)), 2)
                for guid in guids:
                    self.assertRegex(guid, _GUID_PATTERN)

    def test_raw_extras_from_another_bid_drop_bid_scoped_references_only(self):
        conn = self.database()
        result = RealContractOps(conn).insert_takeoffs(
            "x.mdb",
            "1",
            [
                InsertTakeoffSpec(
                    "5",
                    "3",
                    "0",
                    [0, 0, 1, 1],
                    raw_extras=dict(self._EXTRAS),
                    source_bid_uid="2",
                )
            ],
        )
        self.assertEqual(result, ["8"])
        row = self.rows(
            conn,
            "BidZoneUID, TypGroupUID, BidTypAreaUID, TypGroupTakeoffUID, "
            "TypPageTakeoffUID, TypGroupMarkerUID, FontName, GUID",
        )[0]
        self.assertEqual(row[:7], (None, None, None, None, None, None, "Arial"))
        self.assertRegex(row[7], _GUID_PATTERN)

    def test_a_failing_spec_rolls_back_the_whole_batch(self):
        conn = self.database()
        with self.assertLogs("test", level="ERROR") as logs:
            result = _TransactionalContractOps(conn).insert_takeoffs(
                "x.mdb",
                "1",
                [
                    InsertTakeoffSpec("5", "3", "0", [0, 0, 1, 1]),
                    InsertTakeoffSpec("5", "3", "0", ["not-a-number"]),
                ],
            )
        self.assertEqual(result, [])
        self.assertEqual(
            logs.records[0].getMessage(), "Failed to bulk insert takeoffs in x.mdb"
        )
        self.assertEqual(self.rows(conn, "UID", where="1=1"), [(7,)])

    def test_empty_batch_returns_empty_without_opening_the_database(self):
        class Unreachable(RealContractOps):
            def _connection(self, _db_path):
                raise AssertionError("must not connect")

        self.assertEqual(
            Unreachable(self.database()).insert_takeoffs("x.mdb", "1", []), []
        )

    def test_malformed_bid_uid_is_reported_without_inserting(self):
        conn = self.database()
        with self.assertLogs("test", level="ERROR") as logs:
            result = RealContractOps(conn).insert_takeoffs(
                "x.mdb", "abc", [InsertTakeoffSpec("5", "3", "0", [0, 0, 1, 1])]
            )
        self.assertEqual(result, [])
        self.assertEqual(
            logs.records[0].getMessage(), "Failed to bulk insert takeoffs in x.mdb"
        )
        self.assertEqual(self.rows(conn, "UID", where="1=1"), [(7,)])

    def test_fatal_mutation_errors_propagate_from_insert(self):
        conn = self.database()
        with self.assertRaisesRegex(
            RuntimeError, r"BidConditions\.UID=6 does not belong to Bids\.UID=1"
        ):
            _PropagatingContractOps(conn).insert_takeoffs(
                "x.mdb", "1", [InsertTakeoffSpec("6", "3", "0", [0, 0, 1, 1])]
            )
        self.assertEqual(self.rows(conn, "UID", where="1=1"), [(7,)])

    def test_unassigned_area_and_zero_parent_need_no_optional_columns(self):
        for area, parent in ((None, None), ("", ""), ("0", 0), ("0", "0")):
            with self.subTest(area=area, parent=parent):
                conn = contract_db(
                    "CREATE TABLE Bids (UID INTEGER)",
                    "INSERT INTO Bids VALUES (1)",
                    "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
                    "INSERT INTO BidConditions VALUES (5, 1)",
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                    "INSERT INTO BidPages VALUES (3, 1)",
                    "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, "
                    "BidConditionUID INTEGER, BidPageUID INTEGER, Position BLOB)",
                )
                self.addCleanup(conn.close)
                ops = RealContractOps(conn)
                result = ops.insert_takeoffs(
                    "x.mdb",
                    "1",
                    [
                        InsertTakeoffSpec(
                            "5", "3", area, [0, 0, 1, 1], parent_uid=parent
                        )
                    ],
                )
                self.assertEqual(result, ["1"])
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, BidUID, BidConditionUID FROM BidTakeoffs"
                    ).fetchall(),
                    [(1, 1, 5)],
                )
                self.assertEqual(
                    ops.skips,
                    [
                        ("BidTakeoffs", column, "insert_takeoffs")
                        for column in (
                            "BidAreaUID",
                            "Rotation",
                            "Curve",
                            "ParentUID",
                            "IsNegativeQuantity",
                        )
                    ],
                )

    def test_missing_required_columns_are_reported_before_ownership_problems(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidConditions VALUES (6, 2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (3, 1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, "
            "BidPageUID INTEGER, Position BLOB)",
        )
        self.addCleanup(conn.close)
        with self.assertLogs("test", level="ERROR") as logs:
            result = RealContractOps(conn).insert_takeoffs(
                "x.mdb", "1", [InsertTakeoffSpec("6", "3", "0", [0, 0, 1, 1])]
            )
        self.assertEqual(result, [])
        self.assertEqual(
            str(logs.records[0].exc_info[1]), "Missing BidTakeoffs.BidConditionUID"
        )

    def test_a_missing_bid_is_reported_before_the_owners_of_its_children(self):
        conn = self.database("INSERT INTO BidConditions VALUES (50, 99)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = RealContractOps(conn).insert_takeoffs(
                "x.mdb", "99", [InsertTakeoffSpec("5", "3", "0", [0, 0, 1, 1])]
            )
        self.assertEqual(result, [])
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "Bids has no row for UID 99; the requested authoritative owner does "
            "not exist.",
        )


class TakeoffFieldSavePersistenceTests(unittest.TestCase):
    def database(self):
        conn = _takeoff_database(
            "INSERT INTO BidTakeoffs (UID, BidUID, Position, Rotation, "
            "NameFontName, NameFontSize, FontName) VALUES "
            "(1, 1, X'01', 0.0, 'A', 10.0, 'F1')",
            "INSERT INTO BidTakeoffs (UID, BidUID, Position, Rotation, "
            "NameFontName, NameFontSize, FontName) VALUES "
            "(2, 1, X'02', 0.0, 'B', 11.0, 'F2')",
            "INSERT INTO BidTakeoffs (UID, BidUID, Position, Rotation, "
            "NameFontName, NameFontSize, FontName) VALUES "
            "(3, 2, X'03', 0.0, 'C', 12.0, 'F3')",
        )
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def rows(conn, columns):
        return conn.execute(
            f"SELECT {columns} FROM BidTakeoffs ORDER BY UID"
        ).fetchall()

    def test_curve_change_stores_unrounded_geometry_and_flag_for_one_takeoff(self):
        conn = self.database()
        self.assertIs(
            RealContractOps(conn).set_takeoff_curve(
                "x.mdb", "1", [0, 0, 5.5, 5, 2.123456, 4], 0
            ),
            True,
        )
        self.assertEqual(
            self.rows(conn, "UID, Position, Curve"),
            [
                (1, b"0.0;0.0;5.5;5.0;2.123456;4.0\n", 0),
                (2, b"\x02", None),
                (3, b"\x03", None),
            ],
        )

    def test_curve_change_failures_are_logged_and_leave_rows_untouched(self):
        conn = self.database()
        before = self.rows(conn, "*")
        for takeoff_uid, regex in (
            ("99", "BidTakeoffs has no row for UID 99"),
            ("abc", "malformed UID abc"),
        ):
            with self.subTest(takeoff_uid=takeoff_uid):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(
                        RealContractOps(conn).set_takeoff_curve(
                            "x.mdb", takeoff_uid, [0, 0, 1, 1], 0
                        ),
                        False,
                    )
                self.assertEqual(
                    logs.records[0].getMessage(),
                    "Failed to set takeoff curve in x.mdb",
                )
                self.assertRegex(str(logs.records[0].exc_info[1]), regex)
                self.assertEqual(self.rows(conn, "*"), before)
        with self.assertRaisesRegex(RuntimeError, "BidTakeoffs has no row for UID 99"):
            _PropagatingContractOps(conn).set_takeoff_curve(
                "x.mdb", "99", [0, 0, 1, 1], 0
            )

    def test_bulk_positions_are_saved_unrounded_for_the_listed_takeoffs(self):
        conn = self.database()
        self.assertIs(
            RealContractOps(conn).save_takeoff_positions(
                "x.mdb", [("1", [10, 20.123456]), (2, (30.5, 40))]
            ),
            True,
        )
        self.assertEqual(
            self.rows(conn, "UID, Position"),
            [(1, b"10.0;20.123456\n"), (2, b"30.5;40.0\n"), (3, b"\x03")],
        )

    def test_bulk_position_save_of_nothing_succeeds_without_scope_validation(self):
        conn = self.database()
        before = self.rows(conn, "*")
        self.assertIs(RealContractOps(conn).save_takeoff_positions("x.mdb", []), True)
        self.assertIs(RealContractOps(conn).save_takeoff_rotations("x.mdb", []), True)
        self.assertEqual(self.rows(conn, "*"), before)

    def test_bulk_position_and_rotation_failures_roll_back_and_log(self):
        conn = self.database()
        before = self.rows(conn, "*")
        cases = (
            (
                "positions",
                lambda ops: ops.save_takeoff_positions(
                    "x.mdb", [(1, [1, 2]), (2, ["bad"])]
                ),
                "Failed to bulk save takeoff positions in x.mdb",
            ),
            (
                "positions of a missing takeoff",
                lambda ops: ops.save_takeoff_positions(
                    "x.mdb", [(1, [1, 2]), (99, [3, 4])]
                ),
                "Failed to bulk save takeoff positions in x.mdb",
            ),
            (
                "rotations of a missing takeoff",
                lambda ops: ops.save_takeoff_rotations("x.mdb", [(1, 1.0), (99, 2.0)]),
                "Failed to bulk save takeoff rotations in x.mdb",
            ),
        )
        for label, call, message in cases:
            with self.subTest(case=label):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(call(_TransactionalContractOps(conn)), False)
                self.assertEqual(logs.records[0].getMessage(), message)
                self.assertEqual(self.rows(conn, "*"), before)

    def test_bulk_rotations_are_saved_for_the_listed_takeoffs(self):
        conn = self.database()
        self.assertIs(
            RealContractOps(conn).save_takeoff_rotations(
                "x.mdb", [("1", 1.5), (2, -90.0)]
            ),
            True,
        )
        self.assertEqual(
            self.rows(conn, "UID, Rotation"), [(1, 1.5), (2, -90.0), (3, 0.0)]
        )

    def test_missing_position_or_rotation_columns_fail_the_bulk_saves(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (1, 1)",
        )
        self.addCleanup(conn.close)
        for call, column in (
            (
                lambda ops: ops.save_takeoff_positions("x.mdb", [(1, [1, 2])]),
                "Position",
            ),
            (lambda ops: ops.save_takeoff_rotations("x.mdb", [(1, 1.0)]), "Rotation"),
        ):
            with self.subTest(column=column):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(call(RealContractOps(conn)), False)
                self.assertRegex(
                    str(logs.records[0].exc_info[1]), f"Missing BidTakeoffs.{column}"
                )

    def test_bulk_saves_propagate_fatal_mutation_errors(self):
        conn = self.database()
        ops = _PropagatingContractOps(conn)
        for call in (
            lambda: ops.save_takeoff_positions("x.mdb", [(99, [1, 2])]),
            lambda: ops.save_takeoff_rotations("x.mdb", [(99, 1.0)]),
            lambda: ops.save_takeoff_text_properties(
                "x.mdb", [(99, {"name_font_name": "N"})]
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError, "BidTakeoffs has no row for UID 99"
            ):
                call()

    def test_text_properties_write_only_known_keys_for_each_takeoff(self):
        conn = self.database()
        self.assertIs(
            RealContractOps(conn).save_takeoff_text_properties(
                "x.mdb",
                [
                    ("1", {"name_font_name": "Arial", "name_font_size": 48}),
                    (2, {"unknown": "x"}),
                ],
            ),
            True,
        )
        self.assertEqual(
            self.rows(conn, "UID, NameFontName, NameFontSize, FontName"),
            [(1, "Arial", 48.0, "F1"), (2, "B", 11.0, "F2"), (3, "C", 12.0, "F3")],
        )

    def test_text_properties_skip_optional_columns_the_database_lacks(self):
        conn = self.database()
        ops = RealContractOps(conn)
        self.assertIs(
            ops.save_takeoff_text_properties(
                "x.mdb", [(1, {"name_font_name": "Arial", "dimension_font_bold": True})]
            ),
            True,
        )
        self.assertEqual(self.rows(conn, "UID, NameFontName")[0], (1, "Arial"))
        self.assertEqual(
            ops.skips, [("BidTakeoffs", "FontBold", "save_takeoff_text_properties")]
        )

    def test_text_properties_roll_back_earlier_takeoffs_when_a_later_one_cannot_write(
        self,
    ):
        conn = self.database()
        before = self.rows(conn, "*")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                _TransactionalContractOps(conn).save_takeoff_text_properties(
                    "x.mdb",
                    [
                        (1, {"name_font_name": "Changed"}),
                        (2, {"dimension_font_underline": True}),
                    ],
                ),
                False,
            )
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to bulk save takeoff text properties in x.mdb",
        )
        self.assertRegex(
            str(logs.records[0].exc_info[1]),
            "no writable columns for save_takeoff_text_properties",
        )
        self.assertEqual(self.rows(conn, "*"), before)

    def test_text_property_save_of_nothing_succeeds_without_connecting(self):
        class Unreachable(RealContractOps):
            def _connection(self, _db_path):
                raise AssertionError("must not connect")

        self.assertIs(
            Unreachable(self.database()).save_takeoff_text_properties("x.mdb", []), True
        )

    def test_relationship_updates_store_real_values_for_the_selected_takeoffs(self):
        conn = self.database()
        ops = RealContractOps(conn)
        self.assertIs(ops.save_takeoffs_area("x.mdb", ["1", "2"], "30"), True)
        self.assertIs(ops.save_takeoffs_condition("x.mdb", ["2"], "5"), True)
        self.assertIs(ops.set_takeoffs_negative("x.mdb", ["1"], True), True)
        self.assertEqual(
            self.rows(conn, "UID, BidAreaUID, BidConditionUID, IsNegativeQuantity"),
            [(1, 30, None, 1), (2, 30, 5, None), (3, None, None, None)],
        )
        self.assertIs(ops.save_takeoffs_area("x.mdb", [1], "0"), True)
        self.assertIs(ops.set_takeoffs_negative("x.mdb", ["1"], False), True)
        self.assertEqual(
            self.rows(conn, "UID, BidAreaUID, IsNegativeQuantity"),
            [(1, None, 0), (2, 30, None), (3, None, None)],
        )

    def test_relationship_updates_deduplicate_uids_and_accept_empty_selections(self):
        conn = self.database()
        ops = _PlannedFailureOps(conn, lambda _index: None)
        self.assertIs(ops.save_takeoffs_area("x.mdb", ["1", 1, "1"], "30"), True)
        self.assertEqual(
            ops.statements,
            [("UPDATE [BidTakeoffs] SET [BidAreaUID]=? WHERE [UID]=?", (30, 1))],
        )
        ops = _PlannedFailureOps(conn, lambda _index: None)
        self.assertIs(ops.set_takeoffs_negative("x.mdb", [], True), True)
        self.assertEqual((ops.statements, ops.events), ([], []))

    def test_relationship_updates_reject_missing_columns_and_targets(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (1, 1)",
        )
        self.addCleanup(conn.close)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                RealContractOps(conn).set_takeoffs_negative("x.mdb", ["1"], True), False
            )
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to save takeoffs negative flag in x.mdb",
        )
        self.assertRegex(
            str(logs.records[0].exc_info[1]), "Missing BidTakeoffs.IsNegativeQuantity"
        )

    def test_relationship_updates_reject_unsupported_columns_before_connecting(self):
        class Unreachable(RealContractOps):
            def _connection(self, _db_path):
                raise AssertionError("must not connect")

        ops = Unreachable(self.database())
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                ops._update_selected_takeoffs_value(
                    "x.mdb", ["1"], "Position", b"x", "takeoffs position"
                ),
                False,
            )
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            ["Unsupported selected takeoff update column: Position"],
        )

    def test_invalid_identifier_warnings_name_the_offending_values(self):
        conn = self.database()
        ops = RealContractOps(conn)
        cases = (
            (
                lambda: ops.save_takeoffs_area("x.mdb", ["1"], "abc"),
                "Invalid area uid for takeoff assignment: abc",
            ),
            (
                lambda: ops.save_takeoffs_condition("x.mdb", ["1"], None),
                "Invalid condition uid for takeoff assignment: None",
            ),
            (
                lambda: ops.save_takeoffs_condition("x.mdb", ["1"], "abc"),
                "Invalid condition uid for takeoff assignment: abc",
            ),
            (
                lambda: ops.save_takeoffs_area("x.mdb", ["x"], "30"),
                "Invalid takeoff uids passed to takeoffs area: ['x']",
            ),
            (
                lambda: ops.save_takeoffs_condition("x.mdb", ["x"], "5"),
                "Invalid takeoff uids passed to takeoffs condition: ['x']",
            ),
            (
                lambda: ops.set_takeoffs_negative("x.mdb", ["x"], True),
                "Invalid takeoff uids passed to takeoffs negative flag: ['x']",
            ),
            (
                lambda: ops.delete_takeoffs("x.mdb", ["x"]),
                "Invalid takeoff uids passed to delete_takeoffs: ['x']",
            ),
        )
        before = self.rows(conn, "*")
        for call, message in cases:
            with self.subTest(message=message):
                with self.assertLogs("test", level="WARNING") as logs:
                    self.assertIs(call(), False)
                self.assertEqual([r.getMessage() for r in logs.records], [message])
                self.assertEqual(self.rows(conn, "*"), before)

    def test_invalid_identifiers_propagate_when_the_error_is_fatal(self):
        ops = _PropagatingContractOps(self.database())
        for call, message in (
            (
                lambda: ops.save_takeoffs_area("x.mdb", ["1"], "abc"),
                "invalid literal for int",
            ),
            (
                lambda: ops.save_takeoffs_condition("x.mdb", ["1"], "abc"),
                "invalid literal for int",
            ),
            (
                lambda: ops.save_takeoffs_area("x.mdb", ["x"], "30"),
                "^Invalid takeoff UID: 'x'$",
            ),
            (
                lambda: ops.delete_takeoffs("x.mdb", ["x"]),
                "^Invalid takeoff UID: 'x'$",
            ),
        ):
            with self.assertRaisesRegex(ValueError, message):
                call()
        with self.assertRaisesRegex(RuntimeError, "BidTakeoffs has no row for UID 99"):
            ops.save_takeoffs_area("x.mdb", ["99"], "30")
        with self.assertRaisesRegex(RuntimeError, "BidTakeoffs has no row for UID 99"):
            ops.delete_takeoffs("x.mdb", ["99"])


class TakeoffDeleteSchemaVariantTests(unittest.TestCase):
    def database(self, *statements):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, ParentUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (1, 1, NULL)",
            "INSERT INTO BidTakeoffs VALUES (2, 1, NULL)",
            "INSERT INTO BidTakeoffs VALUES (3, 1, 1)",
            *statements,
        )
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    def test_delete_handles_each_annotation_table_and_endpoint_independently(self):
        # BidDimensions is absent, BidALines only has the To endpoint and BidArrows
        # has both: each must be cleaned although an earlier one is not available.
        conn = self.database(
            "CREATE TABLE BidALines (UID INTEGER, BidTakeoffToUID INTEGER)",
            "INSERT INTO BidALines VALUES (10, 1)",
            "INSERT INTO BidALines VALUES (11, 2)",
            "CREATE TABLE BidArrows (UID INTEGER, BidTakeoffFromUID INTEGER, "
            "BidTakeoffToUID INTEGER)",
            "INSERT INTO BidArrows VALUES (20, 1, 2)",
            "INSERT INTO BidArrows VALUES (21, 2, 3)",
            "INSERT INTO BidArrows VALUES (22, 3, 3)",
        )
        self.assertIs(RealContractOps(conn).delete_takeoffs("x.mdb", ["1"]), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidALines ORDER BY UID").fetchall(), [(11,)]
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidArrows ORDER BY UID").fetchall(),
            [(21,), (22,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs ORDER BY UID"
            ).fetchall(),
            [(2, None), (3, None)],
        )

    def test_percent_rows_are_removed_only_when_the_table_has_a_takeoff_column(self):
        conn = self.database(
            "CREATE TABLE BidPercents (UID INTEGER, BidTakeoffUID INTEGER)",
            "INSERT INTO BidPercents VALUES (10, 1)",
            "INSERT INTO BidPercents VALUES (11, 2)",
        )
        self.assertIs(RealContractOps(conn).delete_takeoffs("x.mdb", ["1"]), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPercents").fetchall(), [(11,)]
        )
        legacy = self.database(
            "CREATE TABLE BidPercents (UID INTEGER, Other INTEGER)",
            "INSERT INTO BidPercents VALUES (10, 1)",
        )
        self.assertIs(RealContractOps(legacy).delete_takeoffs("x.mdb", ["1"]), True)
        self.assertEqual(
            legacy.execute("SELECT UID FROM BidPercents").fetchall(), [(10,)]
        )

    def test_delete_requires_a_takeoff_uid_column(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "CREATE TABLE BidTakeoffs (BidUID INTEGER)",
        )
        self.addCleanup(conn.close)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(RealContractOps(conn).delete_takeoffs("x.mdb", ["1"]), False)
        self.assertEqual(str(logs.records[0].exc_info[1]), "Missing BidTakeoffs.UID")


class TakeoffChunkedWriteRecoveryTests(unittest.TestCase):
    """HY001 recovery against real sqlite state and real rollbacks."""

    COUNT = 130

    def database(self):
        conn = _takeoff_database(
            "CREATE TABLE BidDimensions (UID INTEGER, BidTakeoffFromUID INTEGER, "
            "BidTakeoffToUID INTEGER)",
            "CREATE TABLE BidPercents (UID INTEGER, BidTakeoffUID INTEGER)",
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidUID, Position, ParentUID) "
            "VALUES (?, 1, X'00', NULL)",
            ((uid,) for uid in range(1, self.COUNT + 1)),
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidUID, Position, ParentUID) "
            "VALUES (?, 1, X'00', ?)",
            ((500, 1), (501, None)),
        )
        conn.executemany(
            "INSERT INTO BidDimensions VALUES (?, ?, ?)",
            [(uid, uid, 501) for uid in range(1, self.COUNT + 1)]
            + [(1000, 501, 500), (1001, 500, 501)],
        )
        conn.executemany(
            "INSERT INTO BidPercents VALUES (?, ?)",
            [(uid, uid) for uid in range(1, self.COUNT + 1)] + [(2000, 501)],
        )
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def area_values(conn):
        return {
            row[0]
            for row in conn.execute("SELECT BidAreaUID FROM BidTakeoffs WHERE UID<=130")
        }

    def test_resource_exhaustion_midway_retries_row_by_row_and_finishes(self):
        conn = self.database()
        ops = _PlannedFailureOps(conn, lambda index: _hy001() if index == 1 else None)
        with self.assertLogs("test", level="WARNING") as logs:
            result = ops.save_takeoffs_area(
                "x.mdb", [str(uid) for uid in range(1, self.COUNT + 1)], "30"
            )
        self.assertIs(result, True)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Access resource limit while saving takeoffs area for 130 takeoffs "
                "with chunk size 50; retrying row-by-row in a fresh transaction."
            ],
        )
        self.assertEqual(ops.events, ["rollback", "commit"])
        self.assertEqual(len(ops.statements), 2 + self.COUNT)
        self.assertEqual(self.area_values(conn), {30})
        self.assertEqual(
            conn.execute("SELECT BidAreaUID FROM BidTakeoffs WHERE UID>130").fetchall(),
            [(None,), (None,)],
        )

    def test_a_failed_retry_rolls_back_the_first_attempts_partial_chunks_too(self):
        conn = self.database()

        def plan(index):
            if index == 1:
                return _hy001()
            if index == 12:
                return RuntimeError("retry failure")
            return None

        ops = _PlannedFailureOps(conn, plan)
        with self.assertLogs("test", level="WARNING") as logs:
            result = ops.save_takeoffs_area(
                "x.mdb", [str(uid) for uid in range(1, self.COUNT + 1)], "30"
            )
        self.assertIs(result, False)
        self.assertEqual(
            [(record.levelname, record.getMessage()) for record in logs.records],
            [
                (
                    "WARNING",
                    "Access resource limit while saving takeoffs area for 130 "
                    "takeoffs with chunk size 50; retrying row-by-row in a fresh "
                    "transaction.",
                ),
                ("ERROR", "Failed to save takeoffs area row-by-row in x.mdb"),
            ],
        )
        self.assertEqual(ops.events, ["rollback", "rollback"])
        self.assertEqual(len(ops.statements), 13)
        self.assertEqual(self.area_values(conn), {None})

    def test_other_failures_roll_back_and_are_not_retried(self):
        conn = self.database()
        ops = _PlannedFailureOps(
            conn, lambda index: RuntimeError("boom") if index == 1 else None
        )
        with self.assertLogs("test", level="WARNING") as logs:
            result = ops.save_takeoffs_area(
                "x.mdb", [str(uid) for uid in range(1, self.COUNT + 1)], "30"
            )
        self.assertIs(result, False)
        self.assertEqual(
            [(record.levelname, record.getMessage()) for record in logs.records],
            [("ERROR", "Failed to save takeoffs area in x.mdb")],
        )
        self.assertEqual(ops.events, ["rollback"])
        self.assertEqual(len(ops.statements), 2)
        self.assertEqual(self.area_values(conn), {None})

    def test_delete_retries_row_by_row_after_resource_exhaustion(self):
        conn = self.database()
        ops = _PlannedFailureOps(conn, lambda index: _hy001() if index == 4 else None)
        with self.assertLogs("test", level="WARNING") as logs:
            result = ops.delete_takeoffs(
                "x.mdb", [str(uid) for uid in range(1, self.COUNT + 1)]
            )
        self.assertIs(result, True)
        self.assertEqual(
            [record.getMessage() for record in logs.records],
            [
                "Access resource limit while deleting 130 takeoffs with chunk size "
                "50; retrying row-by-row in a fresh transaction."
            ],
        )
        self.assertEqual(ops.events, ["rollback", "commit"])
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidTakeoffs ORDER BY UID"
            ).fetchall(),
            [(500, None), (501, None)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidDimensions ORDER BY UID").fetchall(),
            [(1000,), (1001,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPercents ORDER BY UID").fetchall(),
            [(2000,)],
        )

    def test_delete_failures_leave_every_table_untouched(self):
        conn = self.database()

        def snapshot():
            return [
                conn.execute(f"SELECT * FROM {table} ORDER BY UID").fetchall()
                for table in ("BidTakeoffs", "BidDimensions", "BidPercents")
            ]

        before = snapshot()
        cases = (
            ("generic", lambda index: RuntimeError("boom") if index == 7 else None, 1),
            (
                "failed retry",
                lambda index: (
                    _hy001()
                    if index == 4
                    else RuntimeError("again") if index == 20 else None
                ),
                2,
            ),
        )
        for label, plan, rollbacks in cases:
            with self.subTest(case=label):
                ops = _PlannedFailureOps(conn, plan)
                with self.assertLogs("test", level="WARNING") as logs:
                    self.assertIs(
                        ops.delete_takeoffs(
                            "x.mdb", [str(uid) for uid in range(1, self.COUNT + 1)]
                        ),
                        False,
                    )
                self.assertEqual(ops.events, ["rollback"] * rollbacks)
                self.assertEqual(
                    logs.records[-1].getMessage(),
                    (
                        "Failed to delete takeoffs in x.mdb"
                        if rollbacks == 1
                        else "Failed to delete takeoffs row-by-row in x.mdb"
                    ),
                )
                self.assertEqual(snapshot(), before)

    def test_delete_with_no_targets_succeeds_without_connecting(self):
        ops = _PlannedFailureOps(self.database(), lambda _index: None)
        self.assertIs(ops.delete_takeoffs("x.mdb", []), True)
        self.assertEqual((ops.statements, ops.events), ([], []))
