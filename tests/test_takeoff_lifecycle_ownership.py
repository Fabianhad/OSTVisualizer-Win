import sqlite3
import unittest
from types import SimpleNamespace
from ost_visualizer.application.dtos.insert_takeoff_spec_dto import InsertTakeoffSpec
from ost_visualizer.domain.dtos.raw_bid_data_dto import RawBidData
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.infrastructure.mdb.raw_bid_integrity import (
    validate_raw_bid_integrity,
)
from ost_visualizer.infrastructure.mdb.mdb_writer import MdbWriter
from tests.test_bid_data_reader import _owner_validation_reader
from tests.test_infrastructure_lifecycle import _SqliteDuplicateOps


class _SchemaCheckedTakeoffOps(_SqliteDuplicateOps):
    _require_write_columns = MdbWriter._require_write_columns


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

    def test_reader_rejects_parent_on_another_page(self):
        takeoffs = [
            Takeoff(uid="7", condition_uid="5", page_uid="3"),
            Takeoff(uid="8", condition_uid="5", page_uid="4", parent_uid="7"),
        ]
        reader = _owner_validation_reader(takeoffs)
        reader._parse_bid_pages_for_bid = lambda *_: {
            uid: SimpleNamespace(uid=uid) for uid in ("3", "4")
        }
        with self.assertRaisesRegex(RuntimeError, "Page|page"):
            reader.get_bid_data("malformed.mdb", "1")

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

    def test_raw_import_export_rejects_cross_page_parent(self):
        raw = RawBidData(
            bid_row={"UID": "1"},
            bid_tables={
                "BidConditions": [{"UID": "5", "BidUID": "1"}],
                "BidPages": [{"UID": "3", "BidUID": "1"}, {"UID": "4", "BidUID": "1"}],
            },
            page_tables={
                "BidTakeoffs": [
                    {
                        "UID": "7",
                        "BidUID": "1",
                        "BidConditionUID": "5",
                        "BidPageUID": "3",
                        "ParentUID": "0",
                    },
                    {
                        "UID": "8",
                        "BidUID": "1",
                        "BidConditionUID": "5",
                        "BidPageUID": "4",
                        "ParentUID": "7",
                    },
                ]
            },
        )
        issues = validate_raw_bid_integrity(raw)
        self.assertTrue(
            any("Page" in issue.format() and "8" in issue.format() for issue in issues),
            issues,
        )
