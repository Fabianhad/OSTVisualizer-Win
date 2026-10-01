import logging
import sqlite3
import unittest
from ost_visualizer.application.dtos.create_condition_spec_dto import (
    CreateConditionSpec,
)
from ost_visualizer.application.dtos.update_condition_dto import UpdateConditionDto
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_LINEAR_LENGTH,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
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
