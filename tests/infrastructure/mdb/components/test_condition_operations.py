import logging
import re
import sqlite3
import unittest
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_LINEAR_BOTH_SIDES,
    CALC_LINEAR_LENGTH,
    CALC_VOLUME,
    UOM_CUBIC_FEET,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
    UOM_M2,
    UOM_M3,
    UOM_SQUARE_FEET,
)
from ost_visualizer.infrastructure.mdb.components.serialization import encode_text_blob
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
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    DuplicateBidOwnedUidError,
    MissingBidOwnedUidError,
)
from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from tests.helpers.mdb.real_write_contract import (
    ListParamConnection,
    ListParamCursor,
    RealContractOps,
)

_SqliteMdbOps = RealContractOps
_SqliteDuplicateOps = RealContractOps


class ConditionOperationsPersistenceTests(unittest.TestCase):
    def test_delete_condition_removes_all_ancillary_condition_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidLaborActivity ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidConditionUID INTEGER "
            "REFERENCES BidConditions(UID))"
        )
        conn.execute(
            "CREATE TABLE BidPercents ("
            "UID INTEGER PRIMARY KEY, BidLaborActivityUID INTEGER "
            "REFERENCES BidLaborActivity(UID))"
        )
        conn.execute(
            "CREATE TABLE BidTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidConditionUID INTEGER "
            "REFERENCES BidConditions(UID))"
        )
        conn.execute(
            "CREATE TABLE AffectDPCTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidTypGroupViewUID INTEGER "
            "REFERENCES BidTypGroupViews(UID))"
        )
        conn.executemany(
            "INSERT INTO BidConditions (UID, BidUID) VALUES (?, 1)", ((10,), (11,))
        )
        for table, deleted_uid, surviving_uid in (
            ("BidTakeoffTotals", 100, 300),
            ("BidTypicalGroupTotals", 101, 301),
        ):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
                "BidConditionUID INTEGER REFERENCES BidConditions(UID))"
            )
            conn.executemany(
                f"INSERT INTO {table} (UID, BidUID, BidConditionUID) VALUES (?, 1, ?)",
                ((deleted_uid, 10), (surviving_uid, 11)),
            )
        conn.executemany(
            "INSERT INTO BidLaborActivity "
            "(UID, BidUID, BidConditionUID) VALUES (?, 1, ?)",
            ((20, 10), (21, 11)),
        )
        conn.executemany(
            "INSERT INTO BidPercents (UID, BidLaborActivityUID) VALUES (?, ?)",
            ((30, 20), (31, 21)),
        )
        conn.executemany(
            "INSERT INTO BidTypGroupViews "
            "(UID, BidUID, BidConditionUID) VALUES (?, 1, ?)",
            ((40, 10), (41, 11)),
        )
        conn.executemany(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (?, ?)",
            ((50, 40), (51, 41)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        for table, surviving_uid in (
            ("BidPercents", 31),
            ("BidLaborActivity", 21),
            ("AffectDPCTypGroupViews", 51),
            ("BidTypGroupViews", 41),
            ("BidTakeoffTotals", 300),
            ("BidTypicalGroupTotals", 301),
            ("BidConditions", 11),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT UID FROM {table}").fetchall(),
                    [(surviving_uid,)],
                )

    def test_condition_delete_clears_surviving_takeoff_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, "
            "ParentUID INTEGER, TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, 1)", ((10,), (11,)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?, ?, ?, ?, ?)",
            (
                (70, 10, None, None, None, None),
                (80, 11, 70, 70, 70, 70),
                (81, 11, 80, 80, 80, 80),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs ORDER BY UID"
            ).fetchall(),
            [(80, None, None, None, None), (81, 80, 80, 80, 80)],
        )

    def test_condition_delete_removes_condition_user_companion_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditionUser ("
            "UID INTEGER, BidUID INTEGER, ConditionUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, 1)", ((10,), (11,)))
        conn.executemany(
            "INSERT INTO BidConditionUser VALUES (?, 1, ?)", ((20, 10), (21, 11))
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(
            conn.execute("SELECT * FROM BidConditionUser").fetchall(), [(21, 1, 11)]
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidConditions").fetchall(), [(11, 1)]
        )

    def test_condition_delete_removes_annotations_linked_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER, BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, 1)", ((10,), (11,)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)", ((70, 10), (80, 11))
        )
        conn.executemany(
            "INSERT INTO BidDimensions VALUES (?, ?, ?)",
            ((90, 80, 70), (91, 70, 80), (92, 80, 80)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(
            conn.execute("SELECT * FROM BidDimensions").fetchall(), [(92, 80, 80)]
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(80,)]
        )

    def test_condition_duplicate_reserves_dangling_ancillary_condition_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidConditionUID INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditions VALUES (7, 1, 'source-guid', 1, 'Source')"
        )
        conn.execute("INSERT INTO BidTakeoffTotals VALUES (1, 8)")
        new_uids = _SqliteDuplicateOps(conn).duplicate_conditions("bid.mdb", "1", ["7"])
        self.assertEqual(new_uids, ["9"])
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidTakeoffTotals AS totals "
                "INNER JOIN BidConditions AS conditions "
                "ON totals.BidConditionUID=conditions.UID"
            ).fetchone()[0],
            0,
        )

    def test_condition_duplicate_rejects_cross_bid_batch_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, 1, ?)",
            ((7, 1, "first-guid", "First"), (8, 2, "other-guid", "Other")),
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).duplicate_conditions(
                "malformed.mdb", "1", ["7", "8"]
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertIn("BidConditions.UID=8", logs.output[0])
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(7, 1), (8, 2)],
        )

    def test_condition_delete_rejects_cross_bid_batch_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 1, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).delete_conditions(
                "malformed.mdb", "1", ["7", "8"]
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertIn("BidConditions.UID=8", logs.output[0])
        self.assertFalse(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidConditions ORDER BY UID").fetchall(),
            [(7,), (8,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(70,)]
        )

    def test_condition_cross_bid_duplicate_requires_destination_bid_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "BidLayerUID INTEGER, BidConditionFolderUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "INSERT INTO BidConditions VALUES (7, 1, 'source-guid', 1, "
            "'Source', NULL, NULL)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).duplicate_conditions_to_bid(
                "malformed.mdb", "1", "99", ["7"]
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidConditions").fetchall(),
            [(7, 1)],
        )

    def test_condition_cross_bid_duplicate_normalizes_uom_for_destination_system(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?, ?)", ((1, 0), (2, 1), (3, 0)))
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "Quantity1 INTEGER, UOM1 INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    7,
                    1,
                    "imperial-guid",
                    1,
                    "Imperial",
                    CALC_LINEAR_LENGTH,
                    UOM_LINEAR_FEET,
                    5,
                    6,
                ),
                (8, 2, "metric-guid", 3, "Metric", CALC_LINEAR_LENGTH, UOM_M, 5, 6),
                (
                    9,
                    3,
                    "same-guid",
                    1,
                    "Same",
                    CALC_LINEAR_LENGTH,
                    UOM_LINEAR_FEET,
                    5,
                    6,
                ),
            ),
        )
        ops = _SqliteDuplicateOps(conn)
        result = ops.duplicate_conditions_to_bid("mixed.mdb", "1", "2", ["7"])
        self.assertEqual(len(result), 1)
        duplicated_uid = int(result["7"])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, Quantity1, UOM1, RefNo, Name, BidLayerUID, "
                "BidConditionFolderUID FROM BidConditions WHERE UID=?",
                (duplicated_uid,),
            ).fetchone(),
            (2, CALC_LINEAR_LENGTH, UOM_M, 4, "Imperial", None, None),
        )
        guid = conn.execute(
            "SELECT GUID FROM BidConditions WHERE UID=?", (duplicated_uid,)
        ).fetchone()[0]
        self.assertNotEqual(guid, "imperial-guid")
        self.assertRegex(guid, r"^\{[0-9A-F-]{36}\}$")
        # Metric source into an imperial bid maps back to an imperial linear unit.
        result = ops.duplicate_conditions_to_bid("mixed.mdb", "2", "3", ["8"])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, UOM1, RefNo FROM BidConditions WHERE UID=?",
                (int(result["8"]),),
            ).fetchone(),
            (3, UOM_LINEAR_FEET, 2),
        )
        # Same measurement system keeps the stored unit.
        result = ops.duplicate_conditions_to_bid("mixed.mdb", "3", "1", ["9"])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, UOM1 FROM BidConditions WHERE UID=?",
                (int(result["9"]),),
            ).fetchone(),
            (1, UOM_LINEAR_FEET),
        )

    def test_condition_insert_rejects_cross_bid_relationship_before_insert(self):
        for layer_uid, folder_uid in (("8", "9"), ("7", "10"), ("8", None)):
            with self.subTest(layer_uid=layer_uid, folder_uid=folder_uid):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidConditions ("
                    "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, "
                    "Name TEXT, Type INTEGER, BidLayerUID INTEGER, "
                    "BidConditionFolderUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)"
                )
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.executemany(
                    "INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2))
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
                )
                with self.assertLogs("test", level="ERROR") as logs:
                    result = _SqliteDuplicateOps(conn).insert_condition(
                        "malformed.mdb",
                        "1",
                        CreateConditionSpec(
                            name="Invalid",
                            condition_type=1,
                            layer_uid=layer_uid,
                            folder_uid=folder_uid,
                        ),
                    )
                self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
                self.assertIsNone(result)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 0
                )

    def test_condition_insert_persists_spec_with_next_identity_and_scoped_owners(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "Type INTEGER, Backout INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER, Notes BLOB, CdnTypeUID INTEGER, "
            "Width REAL)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("INSERT INTO BidLayers VALUES (7, 1)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (9, 1)")
        conn.executemany(
            "INSERT INTO BidConditions (UID, BidUID, RefNo) VALUES (?, ?, ?)",
            ((3, 1, 5), (4, 2, 40)),
        )
        new_uid = _SqliteDuplicateOps(conn).insert_condition(
            "bid.mdb",
            "1",
            CreateConditionSpec(
                name="Wall",
                condition_type=2,
                backout=True,
                layer_uid="7",
                folder_uid="9",
                notes="hello",
                width=3.5,
            ),
        )
        self.assertEqual(new_uid, "5")
        row = conn.execute(
            "SELECT UID, BidUID, RefNo, Name, Type, Backout, BidLayerUID, "
            "BidConditionFolderUID, Notes, CdnTypeUID, Width, GUID "
            "FROM BidConditions WHERE UID=5"
        ).fetchone()
        self.assertEqual(row[:11], (5, 1, 6, "Wall", 2, -1, 7, 9, b"hello", None, 3.5))
        self.assertRegex(row[11], r"^\{[0-9A-F-]{36}\}$")

    def test_condition_insert_defaults_root_layer_folder_and_empty_notes_to_null(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "Type INTEGER, Backout INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER, Notes BLOB)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        new_uid = _SqliteDuplicateOps(conn).insert_condition(
            "bid.mdb", "1", CreateConditionSpec(name="Plain", condition_type=1)
        )
        self.assertEqual(new_uid, "1")
        self.assertEqual(
            conn.execute(
                "SELECT RefNo, Backout, BidLayerUID, BidConditionFolderUID, Notes "
                "FROM BidConditions WHERE UID=1"
            ).fetchone(),
            (1, 0, None, None, None),
        )

    def test_condition_update_rejects_cross_bid_relationships_atomically(self):
        for layer_uid, folder_uid in (("8", "9"), ("7", "10"), ("8", "10")):
            with self.subTest(layer_uid=layer_uid, folder_uid=folder_uid):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidConditions ("
                    "UID INTEGER, BidUID INTEGER, Name TEXT, BidLayerUID INTEGER, "
                    "BidConditionFolderUID INTEGER)"
                )
                conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
                conn.execute(
                    "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)"
                )
                conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
                conn.execute(
                    "INSERT INTO BidConditions VALUES (50, 1, 'Original', 7, 9)"
                )
                conn.executemany(
                    "INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2))
                )
                conn.executemany(
                    "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
                )
                updates = UpdateConditionDto()
                updates.set("name", "Unexpected mutation")
                updates.set("layer_uid", layer_uid)
                updates.set("folder_uid", folder_uid)
                with self.assertLogs("test", level="ERROR") as logs:
                    success = _SqliteDuplicateOps(conn).update_condition(
                        "malformed.mdb", "1", "50", updates
                    )
                self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
                self.assertFalse(success)
                self.assertEqual(
                    conn.execute(
                        "SELECT Name, BidLayerUID, BidConditionFolderUID "
                        "FROM BidConditions WHERE UID=50"
                    ).fetchone(),
                    ("Original", 7, 9),
                )

    def test_condition_update_persists_mapped_fields_and_clears_empty_relationships(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER, Backout INTEGER, "
            "BidLayerUID INTEGER, BidConditionFolderUID INTEGER, Notes BLOB, "
            "CdnTypeUID INTEGER, UOM1 INTEGER)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("INSERT INTO BidLayers VALUES (8, 1)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (10, 1)")
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1, 'Original', 1, 0, 7, 9, X'41', 4, 0)",
            ((50,), (51,)),
        )
        ops = _SqliteDuplicateOps(conn)
        updates = UpdateConditionDto()
        updates.set("name", "Renamed")
        updates.set("backout", True)
        updates.set("layer_uid", "8")
        updates.set("folder_uid", "10")
        updates.set("notes", "note")
        updates.set("uom1", 13)
        updates.set("not_a_condition_field", "ignored")
        self.assertTrue(ops.update_condition("bid.mdb", "1", "50", updates))
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, Backout, BidLayerUID, BidConditionFolderUID, "
                "Notes, CdnTypeUID, UOM1 FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [
                (50, "Renamed", -1, 8, 10, b"note", 4, 13),
                (51, "Original", 0, 7, 9, b"A", 4, 0),
            ],
        )
        clearing = UpdateConditionDto()
        clearing.set("layer_uid", None)
        clearing.set("folder_uid", "")
        clearing.set("notes", "")
        clearing.set("cdn_type_uid", None)
        clearing.set("backout", False)
        self.assertTrue(ops.update_condition("bid.mdb", "1", "50", clearing))
        self.assertEqual(
            conn.execute(
                "SELECT Backout, BidLayerUID, BidConditionFolderUID, Notes, CdnTypeUID "
                "FROM BidConditions WHERE UID=50"
            ).fetchone(),
            (0, None, None, None, None),
        )

    def test_condition_update_without_persistable_changes_is_a_noop_success(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (50, 1, 'Original')")
        ops = _SqliteDuplicateOps(conn)
        unknown_only = UpdateConditionDto()
        unknown_only.set("not_a_condition_field", "ignored")
        self.assertTrue(
            ops.update_condition("bid.mdb", "1", "50", UpdateConditionDto())
        )
        self.assertTrue(ops.update_condition("bid.mdb", "1", "50", unknown_only))
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditions").fetchall(), [("Original",)]
        )

    def test_condition_update_ref_no_shifts_only_conflicting_peers(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, RefNo INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?)",
            ((50, 1, 4), (51, 1, 1), (52, 1, 2), (53, 1, 3), (60, 2, 2)),
        )
        updates = UpdateConditionDto()
        updates.set("ref_no", "2")
        self.assertTrue(
            _SqliteDuplicateOps(conn).update_condition("bid.mdb", "1", "50", updates)
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(50, 2), (51, 1), (52, 3), (53, 4), (60, 2)],
        )

    def test_condition_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidConditions VALUES (?, ?)", ((7, 1), (7, 1)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 1, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).delete_conditions("malformed.mdb", "1", ["7"])
            )
        self.assertIs(logs.records[0].exc_info[0], DuplicateBidOwnedUidError)
        self.assertIn("BidConditions contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 2
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 1
        )

    def test_duplicate_conditions_batches_source_reads_and_identity_scans(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1, ?, ?, ?)",
            ((uid, f"source-{uid}", uid, f"Condition {uid}") for uid in range(1, 101)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        result = _SqliteDuplicateOps(conn).duplicate_conditions(
            "large.mdb", "1", [str(uid) for uid in range(1, 101)]
        )
        max_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        source_queries = [
            sql
            for sql in statements
            if "FROM [BIDCONDITIONS]" in sql.upper()
            and "[GUID]" in sql.upper()
            and "[NAME]" in sql.upper()
        ]
        self.assertEqual(result, [str(uid) for uid in range(101, 201)])
        self.assertEqual(len(max_queries), 2)
        self.assertLessEqual(len(source_queries), 2)
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo, Name FROM BidConditions WHERE UID > 100 "
                "ORDER BY UID"
            ).fetchall(),
            [(uid + 100, uid + 100, f"Condition {uid}") for uid in range(1, 101)],
        )

    def test_orphan_condition_edit_and_delete_reject_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, RefNo INTEGER)"
        )
        conn.execute("INSERT INTO BidConditions VALUES (7, 99, 'Orphan condition', 4)")
        ops = _SqliteDuplicateOps(conn)
        updates = UpdateConditionDto()
        updates.set("name", "Changed")
        with self.assertLogs("test", level="ERROR") as edit_logs:
            self.assertFalse(ops.update_condition("malformed.mdb", "99", "7", updates))
        self.assertIn("Bids has no row for UID 99", edit_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditions WHERE UID=7").fetchone()[0],
            "Orphan condition",
        )
        with self.assertLogs("test", level="ERROR") as renumber_logs:
            self.assertFalse(ops.renumber_conditions("malformed.mdb", "99", ["7"]))
        self.assertIn("Bids has no row for UID 99", renumber_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT RefNo FROM BidConditions WHERE UID=7").fetchone()[0],
            4,
        )
        with self.assertLogs("test", level="ERROR") as delete_logs:
            self.assertFalse(ops.delete_conditions("malformed.mdb", "99", ["7"]))
        self.assertIn("Bids has no row for UID 99", delete_logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 1
        )

    def test_renumber_conditions_assigns_requested_order_and_leaves_other_conditions(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, RefNo INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?)",
            ((7, 1, 1), (8, 1, 2), (9, 1, 3), (10, 1, 9), (70, 2, 2)),
        )
        self.assertTrue(
            _SqliteDuplicateOps(conn).renumber_conditions(
                "bid.mdb", "1", ["9", "7", "8"]
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(7, 2), (8, 3), (9, 1), (10, 9), (70, 2)],
        )

    def test_renumber_conditions_rejects_foreign_bid_condition_without_changes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, RefNo INTEGER)"
        )
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?)", ((7, 1, 1), (8, 2, 2))
        )
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).renumber_conditions(
                    "bid.mdb", "1", ["8", "7"]
                )
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(7, 1), (8, 2)],
        )

    def test_condition_batch_operations_handle_empty_and_invalid_requests(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidConditions VALUES (7, 1)")
        ops = _SqliteDuplicateOps(conn)
        self.assertEqual(ops.duplicate_conditions("bid.mdb", "1", []), [])
        self.assertEqual(ops.duplicate_conditions_to_bid("bid.mdb", "1", "2", []), {})
        self.assertEqual(
            ops.duplicate_conditions_to_bid("bid.mdb", "1", "2", ["", None]), {}
        )
        self.assertTrue(ops.delete_conditions("bid.mdb", "1", []))
        self.assertTrue(ops.renumber_conditions("bid.mdb", "1", []))
        with self.assertLogs("test", level="WARNING") as logs:
            self.assertFalse(ops.delete_conditions("bid.mdb", "1", ["7", "bad"]))
            self.assertFalse(ops.delete_conditions("bid.mdb", "bad", ["7"]))
            self.assertFalse(ops.renumber_conditions("bid.mdb", "1", ["bad"]))
        self.assertEqual(len(logs.records), 3)
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidConditions").fetchall(), [(7, 1)]
        )


# ---------------------------------------------------------------------------
# Strict identifier binding for the whole module: Access Long columns do not take
# numeric text, but sqlite's INTEGER affinity silently coerces it, so a dropped
# int() on a bound uid would otherwise be invisible.
# ---------------------------------------------------------------------------
_ORIGINAL_CURSOR_EXECUTE = None
_ALLOW_COPIED_TEXT = False


def _strict_identifier_execute(self, query, *params):
    flat = (
        params[0]
        if len(params) == 1 and isinstance(params[0], (list, tuple))
        else params
    )
    if _ALLOW_COPIED_TEXT and query.startswith("INSERT INTO [BidConditions]"):
        # The copy of a stored row hands unchanged column values to the insert.
        return _ORIGINAL_CURSOR_EXECUTE(self, query, *params)
    for parameter in flat:
        if isinstance(parameter, str) and parameter.strip().lstrip("-").isdigit():
            raise AssertionError(
                f"numeric text bound as a parameter: {parameter!r} in {query[:80]}"
            )
    return _ORIGINAL_CURSOR_EXECUTE(self, query, *params)


def setUpModule():
    global _ORIGINAL_CURSOR_EXECUTE
    _ORIGINAL_CURSOR_EXECUTE = _SqliteCursorWrapper.execute
    _SqliteCursorWrapper.execute = _strict_identifier_execute


def tearDownModule():
    _SqliteCursorWrapper.execute = _ORIGINAL_CURSOR_EXECUTE


from tests.helpers.mdb.real_write_contract import (
    contract_db as _contract_db,
)  # noqa: E402
from ost_visualizer.application.dtos.update_condition_dto import (
    UpdateConditionDto,
)  # noqa: E402

_COLUMNS = (
    "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, IsTemplate INTEGER, Curve INTEGER, "
    "SnapToGrid INTEGER, ManualLength INTEGER, MatAmount INTEGER, LabAmount INTEGER, "
    "SubAmount INTEGER, FontName TEXT, FontSize INTEGER, FontBold INTEGER, FontItalic INTEGER, "
    "ShowTakeoff INTEGER, Backout INTEGER, Name TEXT, Type INTEGER, CdnTypeUID INTEGER, "
    "BidLayerUID INTEGER, Height REAL, Width REAL, Depth REAL, Thickness REAL, Rise REAL, "
    "Run REAL, DisplaySize REAL, Shape INTEGER, Pattern INTEGER, Spacing REAL, ColorFill INTEGER, "
    "UOM1 INTEGER, UOM2 INTEGER, UOM3 INTEGER, Quantity1 INTEGER, Quantity2 INTEGER, "
    "Quantity3 INTEGER, Notes BLOB, DropRun INTEGER, DropValue REAL, RoundQuantity INTEGER, "
    "RoundUp REAL, Trim INTEGER, IsCurvedSegment INTEGER, Grid INTEGER, GridSize1 REAL, "
    "GridSize2 REAL, Gap REAL, DisplayDimension INTEGER, DisplayName INTEGER, "
    "DisplayGridWhileDrawing INTEGER, BidConditionFolderUID INTEGER"
)
_ALL_COLUMN_NAMES = [part.split()[0] for part in _COLUMNS.split(", ")]


def _full_db(*extra):
    return _contract_db(
        "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
        "INSERT INTO Bids VALUES (1, 0)",
        "INSERT INTO Bids VALUES (2, 1)",
        "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidLayers VALUES (30, 1)",
        "CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidConditionFolders VALUES (40, 1)",
        f"CREATE TABLE BidConditions ({_COLUMNS})",
        *extra,
    )


_FULL_SPEC = dict(
    name="Wall",
    condition_type=3,
    backout=True,
    cdn_type_uid="7",
    layer_uid="30",
    height=1.5,
    width=2.5,
    depth=3.5,
    thickness=4.5,
    rise=5.5,
    run=6.5,
    display_size=7.5,
    shape=2,
    pattern=3,
    spacing=8.5,
    color_fill=9,
    uom1=1,
    uom2=2,
    uom3=3,
    calc_type1=4,
    calc_type2=5,
    calc_type3=6,
    notes="memo",
    drop_run=True,
    drop_value=9.5,
    round_quantity=True,
    round_up=10.5,
    trim=True,
    is_curved_segment=True,
    grid=True,
    grid_size1=11.5,
    grid_size2=12.5,
    gap=13.5,
    display_dimension=True,
    display_name=True,
    display_grid_while_drawing=True,
    folder_uid="40",
)
_COLUMN_OF_FIELD = {
    "name": "Name",
    "condition_type": "Type",
    "backout": "Backout",
    "cdn_type_uid": "CdnTypeUID",
    "layer_uid": "BidLayerUID",
    "height": "Height",
    "width": "Width",
    "depth": "Depth",
    "thickness": "Thickness",
    "rise": "Rise",
    "run": "Run",
    "display_size": "DisplaySize",
    "shape": "Shape",
    "pattern": "Pattern",
    "spacing": "Spacing",
    "color_fill": "ColorFill",
    "uom1": "UOM1",
    "uom2": "UOM2",
    "uom3": "UOM3",
    "calc_type1": "Quantity1",
    "calc_type2": "Quantity2",
    "calc_type3": "Quantity3",
    "notes": "Notes",
    "drop_run": "DropRun",
    "drop_value": "DropValue",
    "round_quantity": "RoundQuantity",
    "round_up": "RoundUp",
    "trim": "Trim",
    "is_curved_segment": "IsCurvedSegment",
    "grid": "Grid",
    "grid_size1": "GridSize1",
    "grid_size2": "GridSize2",
    "gap": "Gap",
    "display_dimension": "DisplayDimension",
    "display_name": "DisplayName",
    "display_grid_while_drawing": "DisplayGridWhileDrawing",
    "folder_uid": "BidConditionFolderUID",
}


def _cols(conn, names, where="1=1"):
    return conn.execute(
        f"SELECT {', '.join(names)} FROM BidConditions WHERE {where}"
    ).fetchone()


class ConditionInsertContractTests(unittest.TestCase):
    def test_every_spec_field_lands_in_its_own_column_and_the_fixed_columns_take_their_defaults(
        self,
    ):
        conn = _full_db()
        ops = RealContractOps(conn)
        new_uid = ops.insert_condition("x.mdb", "1", CreateConditionSpec(**_FULL_SPEC))
        self.assertEqual(new_uid, "1")
        self.assertEqual(ops.skips, [])
        row = dict(zip(_ALL_COLUMN_NAMES, _cols(conn, _ALL_COLUMN_NAMES, "UID = 1")))
        self.assertEqual(
            (
                row["UID"],
                row["BidUID"],
                row["RefNo"],
                row["IsTemplate"],
                row["Curve"],
                row["SnapToGrid"],
                row["ManualLength"],
                row["MatAmount"],
                row["LabAmount"],
                row["SubAmount"],
                row["FontName"],
                row["FontSize"],
                row["FontBold"],
                row["FontItalic"],
                row["ShowTakeoff"],
            ),
            (1, 1, 1, 0, 0, 0, 0, 0, 0, 0, "Arial", -16, 0, 0, -1),
        )
        self.assertRegex(
            row["GUID"], r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$"
        )
        self.assertEqual(row["Backout"], -1)
        self.assertEqual(row["Notes"], encode_text_blob("memo"))
        for field, column in _COLUMN_OF_FIELD.items():
            if column in ("Backout", "Notes"):
                continue
            expected = _FULL_SPEC[field]
            if field in ("cdn_type_uid", "layer_uid", "folder_uid"):
                expected = int(expected)
            elif isinstance(expected, bool):
                expected = int(expected)
            with self.subTest(field=field):
                self.assertEqual(row[column], expected)

    def test_a_default_spec_writes_no_backout_and_no_notes_and_numbers_conditions_in_sequence(
        self,
    ):
        conn = _full_db()
        ops = RealContractOps(conn)
        self.assertEqual(ops.insert_condition("x.mdb", "1", CreateConditionSpec()), "1")
        self.assertEqual(ops.insert_condition("x.mdb", "1", CreateConditionSpec()), "2")
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo, Backout, Notes, CdnTypeUID, BidLayerUID, BidConditionFolderUID "
                "FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(1, 1, 0, None, None, None, None), (2, 2, 0, None, None, None, None)],
        )

    def test_text_reference_numbers_are_counted_from_their_integer_value(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, RefNo, Name TEXT, Type INTEGER)",
            "INSERT INTO BidConditions VALUES (5, 1, '5', 'old', 0)",
        )
        self.assertEqual(
            RealContractOps(conn).insert_condition("x.mdb", "1", CreateConditionSpec()),
            "6",
        )
        self.assertEqual(
            conn.execute("SELECT RefNo FROM BidConditions WHERE UID = 6").fetchall(),
            [(6,)],
        )

    def test_missing_optional_columns_are_reported_under_the_insert_label(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, Type INTEGER)",
        )
        ops = RealContractOps(conn)
        self.assertEqual(ops.insert_condition("x.mdb", "1", CreateConditionSpec()), "1")
        self.assertIn(("BidConditions", "Height", "insert_condition"), ops.skips)
        self.assertEqual({op for _t, _c, op in ops.skips}, {"insert_condition"})

    def test_the_insert_needs_its_identity_name_and_type_columns(self):
        for dropped in ("UID", "BidUID", "Name", "Type"):
            with self.subTest(dropped=dropped):
                columns = [
                    c
                    for c in (
                        "UID INTEGER",
                        "BidUID INTEGER",
                        "Name TEXT",
                        "Type INTEGER",
                    )
                    if not c.startswith(dropped + " ")
                ]
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER)",
                    "INSERT INTO Bids VALUES (1)",
                    f"CREATE TABLE BidConditions ({', '.join(columns)})",
                )
                with self.assertLogs("test", "ERROR"):
                    self.assertIsNone(
                        RealContractOps(conn).insert_condition(
                            "x.mdb", "1", CreateConditionSpec()
                        )
                    )

    def test_a_layer_or_folder_of_another_bid_is_refused(self):
        conn = _full_db(
            "INSERT INTO BidLayers VALUES (31, 2)",
            "INSERT INTO BidConditionFolders VALUES (41, 2)",
        )
        for spec in (
            CreateConditionSpec(layer_uid="31"),
            CreateConditionSpec(folder_uid="41"),
        ):
            with self.assertLogs("test", "ERROR"):
                self.assertIsNone(
                    RealContractOps(conn).insert_condition("x.mdb", "1", spec)
                )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchall(), [(0,)]
        )


class ConditionUpdateContractTests(unittest.TestCase):
    def _seed(self):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'Old', 0)"
        )
        return conn

    def test_every_updatable_field_writes_its_own_column(self):
        for field, column in _COLUMN_OF_FIELD.items():
            if field == "ref_no":
                continue
            conn = self._seed()
            dto = UpdateConditionDto()
            value = _FULL_SPEC[field]
            dto.set(field, value)
            with self.subTest(field=field):
                self.assertIs(
                    RealContractOps(conn).update_condition("x.mdb", "1", "10", dto),
                    True,
                )
                stored = conn.execute(
                    f"SELECT {column} FROM BidConditions WHERE UID = 10"
                ).fetchone()[0]
                if column == "Notes":
                    self.assertEqual(stored, encode_text_blob(value))
                elif field in ("cdn_type_uid", "layer_uid", "folder_uid"):
                    self.assertEqual(stored, int(value))
                elif isinstance(value, bool):
                    self.assertEqual(stored, -1 if column == "Backout" else int(value))
                else:
                    self.assertEqual(stored, value)

    def test_clearing_a_reference_or_the_notes_writes_null_and_backout_false_writes_zero(
        self,
    ):
        conn = self._seed()
        conn.execute(
            "UPDATE BidConditions SET CdnTypeUID = 7, BidLayerUID = 30, BidConditionFolderUID = 40, "
            "Notes = 'x', Backout = -1"
        )
        dto = UpdateConditionDto()
        for field, value in (
            ("cdn_type_uid", None),
            ("layer_uid", ""),
            ("folder_uid", None),
            ("notes", ""),
            ("backout", False),
        ):
            dto.set(field, value)
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "10", dto), True
        )
        self.assertEqual(
            conn.execute(
                "SELECT CdnTypeUID, BidLayerUID, BidConditionFolderUID, Notes, Backout "
                "FROM BidConditions"
            ).fetchone(),
            (None, None, None, None, 0),
        )

    def test_an_empty_change_set_succeeds_without_writing(self):
        conn = self._seed()
        self.assertIs(
            RealContractOps(conn).update_condition(
                "x.mdb", "1", "10", UpdateConditionDto()
            ),
            True,
        )
        dto = UpdateConditionDto()
        dto.set("not_a_field", 1)
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "10", dto), True
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidConditions").fetchall(), [("Old",)]
        )

    def test_a_missing_column_is_reported_under_the_update_label_and_the_uid_columns_are_required(
        self,
    ):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidConditions VALUES (10, 1, 'Old')",
        )
        ops = RealContractOps(conn)
        dto = UpdateConditionDto()
        dto.set("name", "New")
        dto.set("height", 2.0)
        self.assertIs(ops.update_condition("x.mdb", "1", "10", dto), True)
        self.assertEqual(ops.skips, [("BidConditions", "Height", "update_condition")])
        for dropped in ("UID", "BidUID"):
            columns = [
                c
                for c in ("UID INTEGER", "BidUID INTEGER", "Name TEXT")
                if not c.startswith(dropped + " ")
            ]
            conn = _contract_db(
                "CREATE TABLE Bids (UID INTEGER)",
                "INSERT INTO Bids VALUES (1)",
                f"CREATE TABLE BidConditions ({', '.join(columns)})",
            )
            with self.subTest(dropped=dropped):
                with self.assertLogs("test", "ERROR"):
                    self.assertIs(
                        RealContractOps(conn).update_condition("x.mdb", "1", "10", dto),
                        False,
                    )

    def test_updating_a_condition_of_another_bid_or_into_another_bids_layer_is_refused(
        self,
    ):
        conn = self._seed()
        conn.execute("INSERT INTO BidLayers VALUES (31, 2)")
        conn.execute("INSERT INTO BidConditionFolders VALUES (41, 2)")
        for field, value in (("layer_uid", "31"), ("folder_uid", "41")):
            dto = UpdateConditionDto()
            dto.set(field, value)
            with self.subTest(field=field):
                with self.assertLogs("test", "ERROR"):
                    self.assertIs(
                        RealContractOps(conn).update_condition("x.mdb", "1", "10", dto),
                        False,
                    )
        dto = UpdateConditionDto()
        dto.set("name", "N")
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                RealContractOps(conn).update_condition("x.mdb", "2", "10", dto), False
            )

    def _refs(self, conn):
        return conn.execute(
            "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
        ).fetchall()

    def _numbered(self):
        conn = _full_db()
        for uid, ref in ((10, 1), (11, 2), (12, 3)):
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (?, 1, ?, 'c', 0)",
                (uid, ref),
            )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (20, 2, 1, 'other bid', 0)"
        )
        return conn

    def test_taking_a_reference_number_pushes_the_others_up(self):
        conn = self._numbered()
        dto = UpdateConditionDto()
        dto.set("ref_no", "1")
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "12", dto), True
        )
        self.assertEqual(self._refs(conn), [(10, 2), (11, 3), (12, 1), (20, 1)])

    def test_keeping_the_same_number_or_taking_a_free_one_shifts_nothing(self):
        conn = self._numbered()
        dto = UpdateConditionDto()
        dto.set("ref_no", 3)
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "12", dto), True
        )
        self.assertEqual(self._refs(conn), [(10, 1), (11, 2), (12, 3), (20, 1)])
        dto.set("ref_no", 9)
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "12", dto), True
        )
        self.assertEqual(self._refs(conn), [(10, 1), (11, 2), (12, 9), (20, 1)])


class ConditionRenumberContractTests(unittest.TestCase):
    def _db(self):
        conn = _full_db()
        for uid, ref in ((10, 1), (11, 2), (12, 3)):
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (?, 1, ?, 'c', 0)",
                (uid, ref),
            )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (20, 2, 7, 'other', 0)"
        )
        return conn

    def test_conditions_are_numbered_in_the_order_given_without_ever_colliding(self):
        conn = self._db()
        ops = RealContractOps(conn)
        self.assertIs(ops.renumber_conditions("x.mdb", "1", ["12", "10", "11"]), True)
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(10, 2), (11, 3), (12, 1), (20, 7)],
        )

    def test_the_temporary_numbers_start_above_every_existing_number(self):
        conn = self._db()
        conn.execute(
            "CREATE TRIGGER no_clash BEFORE UPDATE OF RefNo ON BidConditions WHEN NEW.BidUID = 1 AND "
            "(SELECT COUNT(*) FROM BidConditions WHERE BidUID = 1 AND RefNo = NEW.RefNo AND UID <> NEW.UID) > 0 "
            "BEGIN SELECT RAISE(ABORT, 'ref clash'); END"
        )
        self.assertIs(
            RealContractOps(conn).renumber_conditions("x.mdb", "1", ["12", "11", "10"]),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions WHERE BidUID = 1 ORDER BY UID"
            ).fetchall(),
            [(10, 3), (11, 2), (12, 1)],
        )

    def test_a_bid_without_conditions_still_renumbers_nothing_and_unusable_input_is_refused(
        self,
    ):
        conn = self._db()
        ops = RealContractOps(conn)
        self.assertIs(ops.renumber_conditions("x.mdb", "1", []), True)
        with self.assertLogs("test", "WARNING"):
            self.assertIs(ops.renumber_conditions("x.mdb", "1", ["x"]), False)
        with self.assertLogs("test", "ERROR"):
            self.assertIs(ops.renumber_conditions("x.mdb", "1", ["20"]), False)

    def test_the_renumber_needs_the_reference_column(self):
        for dropped in ("UID", "BidUID", "RefNo"):
            columns = [
                c
                for c in ("UID INTEGER", "BidUID INTEGER", "RefNo INTEGER")
                if not c.startswith(dropped + " ")
            ]
            conn = _contract_db(f"CREATE TABLE BidConditions ({', '.join(columns)})")
            with self.subTest(dropped=dropped):
                with self.assertLogs("test", "ERROR"):
                    self.assertIs(
                        RealContractOps(conn).renumber_conditions("x.mdb", "1", ["10"]),
                        False,
                    )


class ConditionDuplicateContractTests(unittest.TestCase):
    def _db(self, blob_typed=True):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, GUID, RefNo, Name, Type, Notes, BidLayerUID, "
            "BidConditionFolderUID, CdnTypeUID, UOM1, UOM2, UOM3, Quantity1, Quantity2, Quantity3) "
            "VALUES (10, 1, '{OLD}', 1, 'Wall', 2, 'memo', 30, 40, 7, ?, ?, ?, ?, ?, ?)",
            (
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                UOM_CUBIC_FEET,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
        )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, GUID, RefNo, Name, Type) VALUES (11, 1, '{TWO}', 2, 'Slab', 1)"
        )
        return conn

    def test_duplicates_get_fresh_identities_and_keep_every_other_value(self):
        conn = self._db()
        ops = RealContractOps(conn)
        self.assertEqual(
            ops.duplicate_conditions("x.mdb", "1", ["10", "11"]), ["12", "13"]
        )
        self.assertEqual(ops.skips, [])
        rows = conn.execute(
            "SELECT UID, GUID, RefNo, Name, Type, Notes, BidLayerUID, BidConditionFolderUID, CdnTypeUID "
            "FROM BidConditions WHERE UID > 11 ORDER BY UID"
        ).fetchall()
        self.assertEqual([r[0] for r in rows], [12, 13])
        self.assertEqual([r[2] for r in rows], [3, 4])
        self.assertEqual([r[3] for r in rows], ["Wall", "Slab"])
        self.assertEqual(rows[0][4:], (2, "memo", 30, 40, 7))
        for guid in (rows[0][1], rows[1][1]):
            self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertNotEqual(rows[0][1], rows[1][1])
        self.assertEqual(
            conn.execute(
                "SELECT GUID FROM BidConditions WHERE UID IN (10, 11)"
            ).fetchall(),
            [("{OLD}",), ("{TWO}",)],
        )

    def test_a_null_binary_value_is_copied_as_null(self):
        conn = self._db()
        self.assertEqual(
            RealContractOps(conn).duplicate_conditions("x.mdb", "1", ["11"]), ["12"]
        )
        self.assertEqual(
            conn.execute("SELECT Notes FROM BidConditions WHERE UID = 12").fetchall(),
            [(None,)],
        )

    def test_unknown_or_foreign_conditions_block_the_duplicate(self):
        conn = self._db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (20, 2, 1, 'f', 0)"
        )
        for uids in (["99"], ["20"]):
            with self.assertLogs("test", "ERROR"):
                self.assertEqual(
                    RealContractOps(conn).duplicate_conditions("x.mdb", "1", uids), []
                )
        self.assertEqual(
            RealContractOps(conn).duplicate_conditions("x.mdb", "1", []), []
        )

    def test_a_missing_optional_column_is_reported_under_the_duplicate_label(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidConditions VALUES (10, 1, 'Wall')",
        )
        ops = RealContractOps(conn)
        self.assertEqual(ops.duplicate_conditions("x.mdb", "1", ["10"]), ["11"])
        self.assertEqual(ops.skips, [])

    def test_the_duplicate_needs_the_identity_columns(self):
        for dropped in ("UID", "BidUID"):
            columns = [
                c
                for c in ("UID INTEGER", "BidUID INTEGER")
                if not c.startswith(dropped + " ")
            ]
            conn = _contract_db(f"CREATE TABLE BidConditions ({', '.join(columns)})")
            with self.subTest(dropped=dropped):
                with self.assertLogs("test", "ERROR"):
                    self.assertEqual(
                        RealContractOps(conn).duplicate_conditions(
                            "x.mdb", "1", ["10"]
                        ),
                        [],
                    )

    def _two_bids(self, measure_base, destination_layer=30):
        conn = _full_db()
        conn.execute("UPDATE Bids SET MeasureBase = ? WHERE UID = 2", (measure_base,))
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, GUID, RefNo, Name, Type, BidLayerUID, BidConditionFolderUID, "
            "UOM1, UOM2, UOM3, Quantity1, Quantity2, Quantity3) "
            "VALUES (10, 1, '{OLD}', 4, 'Wall', 2, 30, 40, ?, ?, ?, ?, ?, ?)",
            (
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                UOM_CUBIC_FEET,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
        )
        return conn

    def test_copying_to_another_bid_follows_that_bids_measure_system_and_drops_its_owner_references(
        self,
    ):
        conn = self._two_bids(1)
        ops = RealContractOps(conn)
        self.assertEqual(
            ops.duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"]), {"10": "11"}
        )
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, RefNo, BidLayerUID, BidConditionFolderUID, UOM1, UOM2, UOM3, Name "
                "FROM BidConditions WHERE UID = 11"
            ).fetchone(),
            (2, 1, None, None, UOM_M, UOM_M2, UOM_M3, "Wall"),
        )
        self.assertEqual(
            conn.execute(
                "SELECT BidLayerUID, BidConditionFolderUID, UOM1 FROM BidConditions WHERE UID = 10"
            ).fetchone(),
            (30, 40, UOM_LINEAR_FEET),
        )

    def test_copying_to_an_imperial_bid_or_one_without_a_measure_column_keeps_imperial_units(
        self,
    ):
        conn = self._two_bids(0)
        RealContractOps(conn).duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"])
        self.assertEqual(
            conn.execute("SELECT UOM1 FROM BidConditions WHERE UID = 11").fetchone(),
            (UOM_LINEAR_FEET,),
        )
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1 INTEGER, Quantity1 INTEGER)",
            f"INSERT INTO BidConditions VALUES (10, 1, 'Wall', {UOM_LINEAR_FEET}, {CALC_LINEAR_LENGTH})",
        )
        RealContractOps(conn).duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"])
        self.assertEqual(
            conn.execute("SELECT UOM1 FROM BidConditions WHERE UID = 11").fetchone(),
            (UOM_LINEAR_FEET,),
        )

    def test_text_measure_values_and_codes_are_read_as_numbers(self):
        global _ALLOW_COPIED_TEXT
        _ALLOW_COPIED_TEXT = True
        self.addCleanup(globals().__setitem__, "_ALLOW_COPIED_TEXT", False)
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, MeasureBase)",
            "INSERT INTO Bids VALUES (1, 0)",
            "INSERT INTO Bids VALUES (2, '1')",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1, UOM2, UOM3, "
            "Quantity1, Quantity2, Quantity3)",
            "INSERT INTO BidConditions VALUES (10, 1, 'Wall', ?, ?, ?, ?, ?, ?)".replace(
                "?", "'0'", 6
            ),
        )
        conn.execute(
            "UPDATE BidConditions SET UOM1 = ?, UOM2 = ?, UOM3 = ?, Quantity1 = ?, Quantity2 = ?, Quantity3 = ?",
            tuple(
                str(v)
                for v in (
                    UOM_LINEAR_FEET,
                    UOM_SQUARE_FEET,
                    UOM_CUBIC_FEET,
                    CALC_LINEAR_LENGTH,
                    CALC_LINEAR_BOTH_SIDES,
                    CALC_VOLUME,
                )
            ),
        )
        RealContractOps(conn).duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"])
        self.assertEqual(
            conn.execute(
                "SELECT UOM1, UOM2, UOM3 FROM BidConditions WHERE UID = 11"
            ).fetchone(),
            (UOM_M, UOM_M2, UOM_M3),
        )

    def test_blank_and_foreign_requests_are_refused_or_empty(self):
        conn = self._two_bids(0)
        ops = RealContractOps(conn)
        self.assertEqual(ops.duplicate_conditions_to_bid("x.mdb", "1", "2", []), {})
        self.assertEqual(
            ops.duplicate_conditions_to_bid("x.mdb", "1", "2", ["", None, 0]), {}
        )
        with self.assertLogs("test", "ERROR"):
            self.assertEqual(
                ops.duplicate_conditions_to_bid("x.mdb", "1", "9", ["10"]), {}
            )
        with self.assertLogs("test", "ERROR"):
            self.assertEqual(
                ops.duplicate_conditions_to_bid("x.mdb", "2", "1", ["10"]), {}
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone(), (1,)
        )

    def test_requests_are_deduplicated_and_ordered_as_given(self):
        conn = self._two_bids(0)
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (11, 1, 5, 'Slab', 1)"
        )
        ops = RealContractOps(conn)
        self.assertEqual(
            ops.duplicate_conditions_to_bid("x.mdb", "1", "2", ["11", "10", "11"]),
            {"11": "12", "10": "13"},
        )
        self.assertEqual(
            conn.execute(
                "SELECT Name, RefNo FROM BidConditions WHERE BidUID = 2 ORDER BY UID"
            ).fetchall(),
            [("Slab", 1), ("Wall", 2)],
        )

    def test_the_cross_bid_copy_needs_the_identity_columns_and_names_its_label(self):
        for dropped in ("UID", "BidUID"):
            columns = [
                c
                for c in ("UID INTEGER", "BidUID INTEGER")
                if not c.startswith(dropped + " ")
            ]
            conn = _contract_db(
                "CREATE TABLE Bids (UID INTEGER)",
                f"CREATE TABLE BidConditions ({', '.join(columns)})",
            )
            with self.subTest(dropped=dropped):
                with self.assertLogs("test", "ERROR"):
                    self.assertEqual(
                        RealContractOps(conn).duplicate_conditions_to_bid(
                            "x.mdb", "1", "2", ["10"]
                        ),
                        {},
                    )


class ConditionDeleteCascadeContractTests(unittest.TestCase):
    _CHILD_DDL = (
        "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER, ParentUID INTEGER, "
        "TypGroupTakeoffUID INTEGER, TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)",
        "CREATE TABLE BidDimensions (UID INTEGER, BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)",
        "CREATE TABLE BidALines (UID INTEGER, BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)",
        "CREATE TABLE BidArrows (UID INTEGER, BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)",
        "CREATE TABLE BidPercents (UID INTEGER, BidTakeoffUID INTEGER, BidLaborActivityUID INTEGER)",
        "CREATE TABLE BidLaborActivity (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)",
        "CREATE TABLE BidTypGroupViews (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)",
        "CREATE TABLE AffectDPCTypGroupViews (UID INTEGER, BidTypGroupViewUID INTEGER)",
        "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)",
        "CREATE TABLE BidTypicalGroupTotals (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)",
        "CREATE TABLE BidConditionUser (UID INTEGER, ConditionUID INTEGER)",
        "CREATE TABLE ConditionSetStyles (UID INTEGER, ConditionStyleUID INTEGER)",
    )

    def _db(self):
        conn = _full_db(*self._CHILD_DDL)
        for uid, bid in ((10, 1), (11, 1), (20, 2)):
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (?, ?, 1, 'c', 0)",
                (uid, bid),
            )
        conn.executescript(
            """
            INSERT INTO BidTakeoffs VALUES (100, 1, 10, NULL, NULL, NULL, NULL);
            INSERT INTO BidTakeoffs VALUES (101, 1, 11, 100, 100, 100, 100);
            INSERT INTO BidTakeoffs VALUES (102, 1, 11, 101, NULL, NULL, NULL);
            INSERT INTO BidTakeoffs VALUES (300, 2, 10, NULL, NULL, NULL, NULL);
            INSERT INTO BidDimensions VALUES (1, 100, 102);
            INSERT INTO BidDimensions VALUES (2, 102, 100);
            INSERT INTO BidDimensions VALUES (3, 101, 102);
            INSERT INTO BidALines VALUES (1, 100, 102);
            INSERT INTO BidALines VALUES (2, 102, 100);
            INSERT INTO BidALines VALUES (3, 101, 102);
            INSERT INTO BidArrows VALUES (1, 100, 102);
            INSERT INTO BidArrows VALUES (2, 102, 100);
            INSERT INTO BidArrows VALUES (3, 101, 102);
            INSERT INTO BidLaborActivity VALUES (1, 1, 10);
            INSERT INTO BidLaborActivity VALUES (2, 1, 11);
            INSERT INTO BidLaborActivity VALUES (3, 2, 10);
            INSERT INTO BidPercents VALUES (1, 100, NULL);
            INSERT INTO BidPercents VALUES (2, 102, 1);
            INSERT INTO BidPercents VALUES (3, 102, 2);
            INSERT INTO BidTypGroupViews VALUES (1, 1, 10);
            INSERT INTO BidTypGroupViews VALUES (2, 2, 10);
            INSERT INTO BidTypGroupViews VALUES (3, 1, 11);
            INSERT INTO AffectDPCTypGroupViews VALUES (1, 1);
            INSERT INTO AffectDPCTypGroupViews VALUES (2, 2);
            INSERT INTO AffectDPCTypGroupViews VALUES (3, 3);
            INSERT INTO BidTakeoffTotals VALUES (1, 1, 10);
            INSERT INTO BidTakeoffTotals VALUES (2, 2, 10);
            INSERT INTO BidTakeoffTotals VALUES (3, 1, 11);
            INSERT INTO BidTypicalGroupTotals VALUES (1, 1, 10);
            INSERT INTO BidTypicalGroupTotals VALUES (2, 2, 10);
            INSERT INTO BidTypicalGroupTotals VALUES (3, 1, 11);
            INSERT INTO BidConditionUser VALUES (1, 10);
            INSERT INTO BidConditionUser VALUES (2, 11);
            INSERT INTO ConditionSetStyles VALUES (1, 10);
            INSERT INTO ConditionSetStyles VALUES (2, 11);
            """
        )
        return conn

    def _uids(self, conn, table, where=""):
        return [
            r[0] for r in conn.execute(f"SELECT UID FROM {table} {where} ORDER BY UID")
        ]

    def test_deleting_a_condition_removes_every_dependent_of_that_condition_in_that_bid_only(
        self,
    ):
        conn = self._db()
        self.assertIs(
            RealContractOps(conn).delete_conditions("x.mdb", "1", ["10"]), True
        )
        self.assertEqual(self._uids(conn, "BidConditions"), [11, 20])
        self.assertEqual(self._uids(conn, "BidTakeoffs"), [101, 102, 300])
        for table in ("BidDimensions", "BidALines", "BidArrows"):
            with self.subTest(table=table):
                self.assertEqual(self._uids(conn, table), [3])
        self.assertEqual(self._uids(conn, "BidPercents"), [3])
        self.assertEqual(self._uids(conn, "BidLaborActivity"), [2, 3])
        self.assertEqual(self._uids(conn, "BidTypGroupViews"), [2, 3])
        self.assertEqual(self._uids(conn, "AffectDPCTypGroupViews"), [2, 3])
        for table in ("BidTakeoffTotals", "BidTypicalGroupTotals"):
            with self.subTest(table=table):
                self.assertEqual(self._uids(conn, table), [2, 3])
        self.assertEqual(self._uids(conn, "BidConditionUser"), [2])
        self.assertEqual(self._uids(conn, "ConditionSetStyles"), [2])
        self.assertEqual(
            conn.execute(
                "SELECT ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, TypGroupMarkerUID "
                "FROM BidTakeoffs WHERE UID = 101"
            ).fetchone(),
            (None, None, None, None),
        )
        self.assertEqual(
            conn.execute(
                "SELECT ParentUID FROM BidTakeoffs WHERE UID = 102"
            ).fetchone(),
            (101,),
        )

    def test_dependent_tables_that_cannot_be_matched_are_left_alone(self):
        for table in (
            "BidTakeoffs",
            "BidDimensions",
            "BidALines",
            "BidArrows",
            "BidPercents",
            "BidLaborActivity",
            "BidTypGroupViews",
            "AffectDPCTypGroupViews",
            "BidTakeoffTotals",
            "BidTypicalGroupTotals",
            "BidConditionUser",
            "ConditionSetStyles",
        ):
            with self.subTest(table=table):
                conn = _full_db(
                    f"CREATE TABLE {table} (UID INTEGER)",
                    f"INSERT INTO {table} VALUES (1)",
                )
                conn.execute(
                    "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'c', 0)"
                )
                ops = RealContractOps(conn)
                if table == "BidTakeoffs":
                    with self.assertLogs("test", "ERROR"):
                        self.assertIs(
                            ops.delete_conditions("x.mdb", "1", ["10"]), False
                        )
                else:
                    self.assertIs(ops.delete_conditions("x.mdb", "1", ["10"]), True)
                    self.assertEqual(self._uids(conn, table), [1])

    def test_a_schema_with_only_the_condition_table_deletes_the_condition(self):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'c', 0)"
        )
        self.assertIs(
            RealContractOps(conn).delete_conditions("x.mdb", "1", ["10"]), True
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone(), (0,)
        )

    def test_a_failing_style_cleanup_is_reported_but_never_stops_the_delete(self):
        conn = self._db()
        conn.execute("DROP TABLE ConditionSetStyles")
        conn.execute(
            "CREATE TABLE ConditionSetStyles (UID INTEGER, ConditionStyleUID INTEGER)"
        )
        conn.execute(
            "CREATE TRIGGER boom BEFORE DELETE ON ConditionSetStyles BEGIN SELECT RAISE(ABORT, 'locked'); END"
        )
        conn.execute("INSERT INTO ConditionSetStyles VALUES (1, 10)")
        with self.assertLogs("test", "WARNING") as logs:
            self.assertIs(
                RealContractOps(conn).delete_conditions("x.mdb", "1", ["10"]), True
            )
        self.assertIn("ConditionSetStyles", logs.output[0])
        self.assertEqual(self._uids(conn, "BidConditions"), [11, 20])

        class Strict(RealContractOps):
            def _record_caught_mutation_error(self, exc):
                return True

        conn = self._db()
        conn.execute("DROP TABLE ConditionSetStyles")
        conn.execute(
            "CREATE TABLE ConditionSetStyles (UID INTEGER, ConditionStyleUID INTEGER)"
        )
        conn.execute(
            "CREATE TRIGGER boom BEFORE DELETE ON ConditionSetStyles BEGIN SELECT RAISE(ABORT, 'locked'); END"
        )
        conn.execute("INSERT INTO ConditionSetStyles VALUES (1, 10)")
        with self.assertRaises(Exception):
            Strict(conn).delete_conditions("x.mdb", "1", ["10"])

    def test_unusable_requests_are_refused_by_name_when_the_policy_is_strict(self):
        class Strict(RealContractOps):
            def _record_caught_mutation_error(self, exc):
                return True

        conn = self._db()
        self.assertIs(RealContractOps(conn).delete_conditions("x.mdb", "1", []), True)
        for bid, uids in (("1", ["x"]), ("x", ["10"])):
            with self.subTest(bid=bid, uids=uids):
                with self.assertLogs("test", "WARNING"):
                    self.assertIs(
                        RealContractOps(conn).delete_conditions("x.mdb", bid, uids),
                        False,
                    )
        with self.assertRaisesRegex(ValueError, "^Invalid BidConditions UID: 'x'$"):
            Strict(conn).delete_conditions("x.mdb", "1", ["x"])
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                RealContractOps(conn).delete_conditions("x.mdb", "1", ["20"]), False
            )
        self.assertEqual(self._uids(conn, "BidConditions"), [10, 11, 20])


# ---------------------------------------------------------------------------
# Second-pass additions (AB): strict-policy guard messages, driver-typed reads,
# duplicate reference numbers, multi-condition cascade and numeric edge cases.
# ---------------------------------------------------------------------------
class _StrictRealOps(RealContractOps):
    """The strict error policy re-raises what the tolerant one logs."""

    def _record_caught_mutation_error(self, exc):
        return True


class _TextRowsCursor(ListParamCursor):
    """Hands chosen integer columns back as zero-padded text, like a driver that
    reports Access Long columns as strings; every other statement is untouched."""

    rules = (
        (
            r"^SELECT .* FROM \[BidConditions\] WHERE \[BidUID\] = \? AND",
            ("UID", "UOM1", "UOM2", "UOM3", "Quantity1", "Quantity2", "Quantity3"),
        ),
        (r"FROM \[BidTakeoffs\] WHERE \[BidConditionUID\]", None),
        (r"^SELECT \[RefNo\] FROM \[BidConditions\] WHERE \[UID\]", None),
        (r"^SELECT MAX\(\[RefNo\]\)", None),
    )

    def execute(self, query, *params):
        self._text_columns = False
        for pattern, columns in self.rules:
            if re.search(pattern, query):
                self._text_columns = True
                self._only = columns
                break
        return super().execute(query, *params)

    def _texted(self, row):
        if row is None or not self._text_columns:
            return row
        values = [
            (
                f"{value:04d}"
                if isinstance(value, int) and (self._only is None or name in self._only)
                else value
            )
            for name, value in zip(row._columns, row._values)
        ]
        return _SqliteRow(row._columns, values)

    def fetchone(self):
        return self._texted(super().fetchone())

    def fetchall(self):
        return [self._texted(row) for row in super().fetchall()]


class _TextRowsConnection(ListParamConnection):
    def cursor(self):
        return _TextRowsCursor(self._connection)


class _TextRowsOps(RealContractOps):
    def _connection(self, _db_path):
        return _TextRowsConnection(self._connection_ref)


class _BlobTypedCursor(ListParamCursor):
    """Reports bytearray type codes for the Notes column, like pyodbc over Access."""

    @property
    def description(self):
        base = super().description
        if base is None:
            return None
        return tuple(
            (column[0], bytearray if column[0] == "Notes" else str, *column[2:])
            for column in base
        )


class _BlobTypedConnection(ListParamConnection):
    def cursor(self):
        return _BlobTypedCursor(self._connection)


class _BlobTypedOps(RealContractOps):
    def _connection(self, _db_path):
        return _BlobTypedConnection(self._connection_ref)


def _conditions_db(columns, *extra):
    return _contract_db(
        "CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)",
        "INSERT INTO Bids VALUES (1, 0)",
        "INSERT INTO Bids VALUES (2, 1)",
        f"CREATE TABLE BidConditions ({columns})",
        *extra,
    )


class ConditionGuardMessageTests(unittest.TestCase):
    """Each public operation checks its own required columns first; the strict policy
    shows which check fired because the guard names the column (a raw sqlite error
    would mean the operation ran past a missing column)."""

    def _strict_message(self, call, columns, *extra):
        conn = _conditions_db(columns, *extra)
        with self.assertRaises(Exception) as caught:
            call(_StrictRealOps(conn))
        self.assertNotIsInstance(caught.exception, sqlite3.Error)
        return str(caught.exception)

    def test_each_operation_names_the_identity_column_it_cannot_find(self):
        calls = {
            "insert": lambda ops: ops.insert_condition(
                "x.mdb", "1", CreateConditionSpec()
            ),
            "duplicate": lambda ops: ops.duplicate_conditions("x.mdb", "1", ["10"]),
            "duplicate_to_bid": lambda ops: ops.duplicate_conditions_to_bid(
                "x.mdb", "1", "2", ["10"]
            ),
            "delete": lambda ops: ops.delete_conditions("x.mdb", "1", ["10"]),
        }
        for name, call in calls.items():
            for dropped, columns in (
                ("UID", "BidUID INTEGER, Name TEXT, Type INTEGER"),
                ("BidUID", "UID INTEGER, Name TEXT, Type INTEGER"),
            ):
                with self.subTest(operation=name, dropped=dropped):
                    self.assertEqual(
                        self._strict_message(call, columns),
                        f"Missing BidConditions.{dropped}",
                    )

    def test_the_reference_number_column_is_required_for_renumbering_and_for_ref_updates(
        self,
    ):
        columns = "UID INTEGER, BidUID INTEGER"
        seed = ("INSERT INTO BidConditions VALUES (10, 1)",)
        update = UpdateConditionDto()
        update.set("ref_no", 2)
        self.assertEqual(
            self._strict_message(
                lambda ops: ops.renumber_conditions("x.mdb", "1", ["10"]),
                columns,
                *seed,
            ),
            "Missing BidConditions.RefNo",
        )
        self.assertEqual(
            self._strict_message(
                lambda ops: ops.update_condition("x.mdb", "1", "10", update),
                columns,
                *seed,
            ),
            "Missing BidConditions.RefNo",
        )

    def test_takeoffs_that_cannot_be_matched_to_conditions_stop_the_delete_by_name(
        self,
    ):
        message = self._strict_message(
            lambda ops: ops.delete_conditions("x.mdb", "1", ["10"]),
            "UID INTEGER, BidUID INTEGER",
            "INSERT INTO BidConditions VALUES (10, 1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER)",
        )
        self.assertEqual(message, "Missing BidTakeoffs.BidConditionUID")


class ConditionEdgeContractTests(unittest.TestCase):
    def _allow_copied_text(self):
        global _ALLOW_COPIED_TEXT
        _ALLOW_COPIED_TEXT = True
        self.addCleanup(globals().__setitem__, "_ALLOW_COPIED_TEXT", False)

    def test_an_insert_for_a_bid_that_does_not_exist_is_refused_with_the_owner_named(
        self,
    ):
        conn = _full_db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                RealContractOps(conn).insert_condition(
                    "x.mdb", "99", CreateConditionSpec()
                )
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertIn("Bids has no row for UID 99", str(logs.records[0].exc_info[1]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone(), (0,)
        )

    def test_a_condition_of_another_bid_is_refused_as_an_ownership_error_by_the_cross_bid_copy(
        self,
    ):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (20, 2, 1, 'f', 0)"
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                RealContractOps(conn).duplicate_conditions_to_bid(
                    "x.mdb", "1", "2", ["20"]
                ),
                {},
            )
        self.assertIs(logs.records[0].exc_info[0], MissingBidOwnedUidError)
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "BidConditions.UID=20 does not belong to Bids.UID=1.",
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone(), (1,)
        )

    def test_missing_codes_copy_as_each_and_a_count_quantity_forces_each_units(self):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type, UOM1, Quantity1, UOM2, Quantity2, UOM3, Quantity3) "
            "VALUES (10, 1, 1, 'Wall', 1, NULL, NULL, ?, ?, ?, NULL)",
            (UOM_LINEAR_FEET, CALC_COUNT, UOM_SQUARE_FEET),
        )
        ops = RealContractOps(conn)
        self.assertEqual(
            ops.duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"]), {"10": "11"}
        )
        self.assertEqual(
            conn.execute(
                "SELECT UOM1, UOM2, UOM3 FROM BidConditions WHERE UID = 11"
            ).fetchone(),
            (UOM_EACH, UOM_EACH, UOM_M2),
        )

    def test_driver_text_for_codes_and_units_is_read_as_numbers_when_no_calculation_applies(
        self,
    ):
        self._allow_copied_text()
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type, UOM1, Quantity1, UOM2, Quantity2, UOM3, Quantity3) "
            "VALUES (10, 1, 1, 'Wall', 1, ?, 0, ?, 0, ?, 0)",
            (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET),
        )
        result = _TextRowsOps(conn).duplicate_conditions_to_bid(
            "x.mdb", "1", "2", ["10"]
        )
        self.assertEqual(result, {"10": "11"})
        self.assertEqual(
            conn.execute(
                "SELECT UOM1, UOM2, UOM3, typeof(UOM1) FROM BidConditions WHERE UID = 11"
            ).fetchone(),
            (UOM_M, UOM_M2, UOM_M3, "integer"),
        )

    def test_a_driver_that_returns_uids_as_text_still_maps_the_copy_to_its_source_uid(
        self,
    ):
        self._allow_copied_text()
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'Wall', 1)"
        )
        self.assertEqual(
            _TextRowsOps(conn).duplicate_conditions_to_bid("x.mdb", "1", "2", ["10"]),
            {"10": "11"},
        )

    def test_a_binary_column_reported_by_the_driver_is_stored_as_bytes_and_null_stays_null(
        self,
    ):
        for call in (
            lambda ops: ops.duplicate_conditions("x.mdb", "1", ["10", "11"]),
            lambda ops: list(
                ops.duplicate_conditions_to_bid(
                    "x.mdb", "1", "2", ["10", "11"]
                ).values()
            ),
        ):
            conn = _full_db()
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type, Notes) VALUES (10, 1, 1, 'A', 1, 'memo')"
            )
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type, Notes) VALUES (11, 1, 2, 'B', 1, NULL)"
            )
            with self.subTest(call=call):
                new_uids = call(_BlobTypedOps(conn))
                self.assertEqual(len(new_uids), 2)
                self.assertEqual(
                    conn.execute(
                        "SELECT typeof(Notes), Notes FROM BidConditions WHERE UID > 11 ORDER BY UID"
                    ).fetchall(),
                    [("blob", b"memo"), ("null", None)],
                )

    def test_the_source_rows_are_read_with_a_bracketed_column_list(self):
        conn = _full_db()
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'A', 1)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        RealContractOps(conn).duplicate_conditions("x.mdb", "1", ["10"])
        loads = [
            sql
            for sql in statements
            if "[GUID]" in sql and sql.lstrip().startswith("SELECT")
        ]
        self.assertEqual(len(loads), 1)
        self.assertRegex(
            loads[0],
            r"^SELECT (\[\w+\], )+\[\w+\] FROM \[BidConditions\] WHERE \[BidUID\] = 1 AND \[UID\]=10$",
        )

    def _duplicate_numbers(self):
        conn = _full_db()
        for uid, ref in ((12, 3), (13, 3), (14, 4)):
            conn.execute(
                "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (?, 1, ?, 'c', 0)",
                (uid, ref),
            )
        return conn

    def test_keeping_a_number_that_another_condition_also_holds_shifts_nothing(self):
        conn = self._duplicate_numbers()
        dto = UpdateConditionDto()
        dto.set("ref_no", 3)
        self.assertIs(
            RealContractOps(conn).update_condition("x.mdb", "1", "12", dto), True
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(12, 3), (13, 3), (14, 4)],
        )

    def test_driver_text_for_reference_numbers_does_not_change_which_updates_shift_peers(
        self,
    ):
        conn = self._duplicate_numbers()
        dto = UpdateConditionDto()
        dto.set("ref_no", 3)
        self.assertIs(
            _TextRowsOps(conn).update_condition("x.mdb", "1", "12", dto), True
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [(12, 3), (13, 3), (14, 4)],
        )

    def test_renumbering_stays_clear_of_numbers_held_by_conditions_that_are_not_listed(
        self,
    ):
        for ops_class in (RealContractOps, _TextRowsOps):
            with self.subTest(ops=ops_class.__name__):
                conn = _full_db()
                for uid, ref in ((10, 1), (11, 2), (12, 5)):
                    conn.execute(
                        "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (?, 1, ?, 'c', 0)",
                        (uid, ref),
                    )
                conn.execute(
                    "CREATE TRIGGER no_clash BEFORE UPDATE OF RefNo ON BidConditions WHEN "
                    "(SELECT COUNT(*) FROM BidConditions WHERE BidUID = NEW.BidUID AND RefNo = NEW.RefNo "
                    "AND UID <> NEW.UID) > 0 BEGIN SELECT RAISE(ABORT, 'ref clash'); END"
                )
                self.assertIs(
                    ops_class(conn).renumber_conditions("x.mdb", "1", ["11", "10"]),
                    True,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, RefNo FROM BidConditions ORDER BY UID"
                    ).fetchall(),
                    [(10, 2), (11, 1), (12, 5)],
                )

    def test_a_list_of_conditions_is_deleted_together_with_their_dependents(self):
        conn = ConditionDeleteCascadeContractTests()._db()
        self.assertIs(
            RealContractOps(conn).delete_conditions("x.mdb", "1", ["10", "11"]), True
        )
        for table, expected in (
            ("BidConditions", [20]),
            ("BidTakeoffs", [300]),
            ("BidLaborActivity", [3]),
            ("BidTypGroupViews", [2]),
            ("BidTakeoffTotals", [2]),
            ("BidConditionUser", []),
            ("ConditionSetStyles", []),
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    [
                        row[0]
                        for row in conn.execute(f"SELECT UID FROM {table} ORDER BY UID")
                    ],
                    expected,
                )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDimensions").fetchone(), (0,)
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPercents").fetchone(), (0,)
        )

    def test_driver_text_for_takeoff_uids_does_not_change_the_takeoff_cleanup(self):
        conn = ConditionDeleteCascadeContractTests()._db()
        self.assertIs(_TextRowsOps(conn).delete_conditions("x.mdb", "1", ["10"]), True)
        self.assertEqual(
            conn.execute(
                "SELECT ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, TypGroupMarkerUID "
                "FROM BidTakeoffs WHERE UID = 101"
            ).fetchone(),
            (None, None, None, None),
        )

    def test_unmatched_dependent_tables_are_skipped_without_any_warning(self):
        for table in (
            "ConditionSetStyles",
            "BidConditionUser",
            "BidLaborActivity",
            "BidTypGroupViews",
        ):
            with self.subTest(table=table):
                conn = _full_db(
                    f"CREATE TABLE {table} (UID INTEGER)",
                    f"INSERT INTO {table} VALUES (1)",
                )
                conn.execute(
                    "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'c', 0)"
                )
                with self.assertNoLogs("test", level="WARNING"):
                    self.assertIs(
                        RealContractOps(conn).delete_conditions("x.mdb", "1", ["10"]),
                        True,
                    )

    def test_a_takeoff_uid_that_exists_twice_stops_the_condition_delete_before_anything_is_removed(
        self,
    ):
        conn = _full_db(
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidConditionUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (70, 1, 10)",
            "INSERT INTO BidTakeoffs VALUES (70, 1, 10)",
        )
        conn.execute(
            "INSERT INTO BidConditions (UID, BidUID, RefNo, Name, Type) VALUES (10, 1, 1, 'c', 0)"
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                RealContractOps(conn).delete_conditions("x.mdb", "1", ["10"]), False
            )
        self.assertIs(logs.records[0].exc_info[0], DuplicateBidOwnedUidError)
        self.assertIn(
            "BidTakeoffs contains duplicate UID 70", str(logs.records[0].exc_info[1])
        )
        with self.assertRaises(DuplicateBidOwnedUidError):
            _StrictRealOps(conn).delete_conditions("x.mdb", "1", ["10"])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone(), (1,)
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone(), (2,)
        )
