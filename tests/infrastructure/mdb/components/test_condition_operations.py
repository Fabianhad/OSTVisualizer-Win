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
        conn.execute("INSERT INTO BidConditions (UID, BidUID) VALUES (10, 1)")
        for table in ("BidTakeoffTotals", "BidTypicalGroupTotals"):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, BidUID INTEGER, "
                "BidConditionUID INTEGER REFERENCES BidConditions(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidUID, BidConditionUID) "
                "VALUES (?, 1, 10)",
                (100 + len(table),),
            )
        conn.execute(
            "INSERT INTO BidLaborActivity "
            "(UID, BidUID, BidConditionUID) VALUES (20, 1, 10)"
        )
        conn.execute(
            "INSERT INTO BidPercents (UID, BidLaborActivityUID) VALUES (30, 20)"
        )
        conn.execute(
            "INSERT INTO BidTypGroupViews "
            "(UID, BidUID, BidConditionUID) VALUES (40, 1, 10)"
        )
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (50, 40)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        for table in (
            "BidPercents",
            "BidLaborActivity",
            "AffectDPCTypGroupViews",
            "BidTypGroupViews",
            "BidTakeoffTotals",
            "BidTypicalGroupTotals",
            "BidConditions",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
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
            ((70, 10, None, None, None, None), (80, 11, 70, 70, 70, 70)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(80, None, None, None, None)],
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
        conn.execute("INSERT INTO BidConditions VALUES (10, 1)")
        conn.execute("INSERT INTO BidConditionUser VALUES (20, 1, 10)")
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(conn.execute("SELECT * FROM BidConditionUser").fetchall(), [])
        self.assertEqual(conn.execute("SELECT * FROM BidConditions").fetchall(), [])

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
        conn.execute("INSERT INTO BidDimensions VALUES (90, 80, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_conditions("bid.mdb", "1", ["10"]))
        self.assertEqual(conn.execute("SELECT * FROM BidDimensions").fetchall(), [])
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
        result = _SqliteDuplicateOps(conn).duplicate_conditions(
            "malformed.mdb", "1", ["7", "8"]
        )
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
        result = _SqliteDuplicateOps(conn).delete_conditions(
            "malformed.mdb", "1", ["7", "8"]
        )
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
        result = _SqliteDuplicateOps(conn).duplicate_conditions_to_bid(
            "malformed.mdb", "1", "99", ["7"]
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, BidUID FROM BidConditions").fetchall(),
            [(7, 1)],
        )

    def test_condition_cross_bid_duplicate_normalizes_uom_for_destination_system(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, MeasureBase INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?, ?)", ((1, 0), (2, 1)))
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, Name TEXT, "
            "Quantity1 INTEGER, UOM1 INTEGER)"
        )
        conn.execute(
            "INSERT INTO BidConditions VALUES "
            "(7, 1, 'source-guid', 1, 'Source', ?, ?)",
            (CALC_LINEAR_LENGTH, UOM_LINEAR_FEET),
        )
        result = _SqliteDuplicateOps(conn).duplicate_conditions_to_bid(
            "mixed.mdb", "1", "2", ["7"]
        )
        self.assertEqual(len(result), 1)
        duplicated_uid = int(result["7"])
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, Quantity1, UOM1 FROM BidConditions WHERE UID=?",
                (duplicated_uid,),
            ).fetchone(),
            (2, CALC_LINEAR_LENGTH, UOM_M),
        )

    def test_condition_insert_rejects_cross_bid_relationship_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, GUID TEXT, RefNo INTEGER, "
            "Name TEXT, Type INTEGER, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.executemany("INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
        )
        result = _SqliteDuplicateOps(conn).insert_condition(
            "malformed.mdb",
            "1",
            CreateConditionSpec(
                name="Invalid",
                condition_type=1,
                layer_uid="8",
                folder_uid="9",
            ),
        )
        self.assertIsNone(result)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidConditions").fetchone()[0], 0
        )

    def test_condition_update_rejects_cross_bid_relationships_atomically(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, BidLayerUID INTEGER, "
            "BidConditionFolderUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidConditionFolders (UID INTEGER, BidUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        conn.execute("INSERT INTO BidConditions VALUES (50, 1, 'Original', 7, 9)")
        conn.executemany("INSERT INTO BidLayers VALUES (?, ?)", ((7, 1), (8, 2)))
        conn.executemany(
            "INSERT INTO BidConditionFolders VALUES (?, ?)", ((9, 1), (10, 2))
        )
        updates = UpdateConditionDto()
        updates.set("name", "Unexpected mutation")
        updates.set("layer_uid", "8")
        updates.set("folder_uid", "9")
        success = _SqliteDuplicateOps(conn).update_condition(
            "malformed.mdb", "1", "50", updates
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute(
                "SELECT Name, BidLayerUID, BidConditionFolderUID "
                "FROM BidConditions WHERE UID=50"
            ).fetchone(),
            ("Original", 7, 9),
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
        self.assertEqual(len(result), 100)
        self.assertEqual(len(max_queries), 2)
        self.assertLessEqual(len(source_queries), 2)

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
