from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
import unittest
import sqlite3
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.services.uom_service import (
    CALC_COUNT,
    CALC_LINEAR_LENGTH,
    UOM_EACH,
    UOM_LINEAR_FEET,
    UOM_M,
)
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from types import MappingProxyType, SimpleNamespace
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CHILD_TABLES,
)
from tests.presentation.dialogs.cover_sheet.path_support import (
    _AllDeleteColumnsSchema as _path_support__AllDeleteColumnsSchema,
    _BulkDeleteCoverSheetOps as _path_support__BulkDeleteCoverSheetOps,
    _CoverSheetSettingsOps as _path_support__CoverSheetSettingsOps,
    _FakeConnection as _path_support__FakeConnection,
    _FakeCursor as _path_support__FakeCursor,
    _FakeLogger as _path_support__FakeLogger,
    _FakeSchema as _path_support__FakeSchema,
    _ScaleConnection as _path_support__ScaleConnection,
    _ScaleCoverSheetOps as _path_support__ScaleCoverSheetOps,
    _ScaleCursor as _path_support__ScaleCursor,
    _app as _path_support__app,
    _cover_sheet_page_update as _path_support__cover_sheet_page_update,
)


class _SettingsOperationsPersistenceFixture(unittest.TestCase):
    pass


class SettingsOperationsSaveBidSelectedPageTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_save_bid_selected_page_rejects_page_from_another_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageSelectedUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO Bids (UID) VALUES (2)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 2, NULL)"
        )
        self.assertFalse(
            _SqliteMdbOps(conn).save_bid_selected_page("bid.mdb", "2", "10")
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0]
        )

    def test_save_bid_selected_page_rejects_multiple_settings_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageSelectedUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (20, 1, 10)"
        )
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (21, 1, 11)"
        )
        self.assertFalse(
            _SqliteMdbOps(conn).save_bid_selected_page("bid.mdb", "1", "11")
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageSelectedUID FROM BidSettings ORDER BY UID"
            ).fetchall(),
            [(20, 10), (21, 11)],
        )

    def test_save_bid_selected_page_creates_missing_legacy_settings_row(self):
        class Ops(_SqliteMdbOps):
            @staticmethod
            def _execute_insert_values(
                cursor,
                schema,
                table,
                values,
                required_columns,
                _operation,
            ):
                for column in required_columns:
                    if not schema.column_exists(table, column):
                        raise RuntimeError(f"Missing {table}.{column}")
                filtered = {
                    column: value
                    for column, value in values.items()
                    if schema.column_exists(table, column)
                }
                columns = tuple(filtered)
                cursor.execute(
                    f"INSERT INTO [{table}] "
                    f"({', '.join(f'[{column}]' for column in columns)}) "
                    f"VALUES ({', '.join('?' for _column in columns)})",
                    *(filtered[column] for column in columns),
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidSettings (" "BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        self.assertTrue(Ops(conn).save_bid_selected_page("bid.mdb", "1", "10"))
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, BidPageSelectedUID FROM BidSettings"
            ).fetchall(),
            [(1, 10)],
        )

    def test_selected_page_save_rejects_orphan_bid_companion_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidSettings (BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidSettings VALUES (99, NULL)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).save_bid_selected_page(
                    "malformed.mdb", "99", "20"
                )
            )
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE BidUID=99"
            ).fetchone()[0]
        )


class SettingsOperationsDeletePagesTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_delete_page_clears_bid_settings_selected_page_before_page_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute(
            """
            CREATE TABLE BidPages (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidSettings (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER REFERENCES Bids(UID),
                BidPageSelectedUID INTEGER REFERENCES BidPages(UID)
            )
            """
        )
        conn.execute("INSERT INTO Bids (UID) VALUES (1)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (2, 1, 10)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 2"
            ).fetchone()[0]
        )

    def test_delete_page_clears_only_page_typed_cover_sheet_selection(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, "
            "CoverSheetSelItemType INTEGER, "
            "CoverSheetSelItemUID INTEGER)"
        )
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO Bids "
            "(UID, CoverSheetSelItemType, CoverSheetSelItemUID) "
            "VALUES (1, 1, 10)"
        )
        conn.execute(
            "INSERT INTO Bids "
            "(UID, CoverSheetSelItemType, CoverSheetSelItemUID) "
            "VALUES (2, 2, 10)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        rows = conn.execute(
            "SELECT UID, CoverSheetSelItemUID FROM Bids ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(1, None), (2, 10)])

    def test_delete_pages_preserves_conditions_uoms_and_remaining_takeoffs(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, UOM1 INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER PRIMARY KEY, BidPageUID INTEGER, BidConditionUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages (UID, BidUID) VALUES (?, 1)",
            ((10,), (11,), (12,)),
        )
        conn.executemany(
            "INSERT INTO BidConditions (UID, BidUID, UOM1) VALUES (?, 1, ?)",
            ((20, 7), (21, 9)),
        )
        conn.executemany(
            "INSERT INTO BidTakeoffs (UID, BidPageUID, BidConditionUID) "
            "VALUES (?, ?, ?)",
            (
                (30, 10, 20),
                (31, 11, 20),
                (32, 12, 21),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10", "12"]))
        self.assertEqual(
            conn.execute("SELECT UID, UOM1 FROM BidConditions ORDER BY UID").fetchall(),
            [(20, 7), (21, 9)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageUID, BidConditionUID FROM BidTakeoffs"
            ).fetchall(),
            [(31, 11, 20)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages ORDER BY UID").fetchall(),
            [(11,)],
        )

    def test_delete_page_removes_indexed_annotation_shape_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidPageUID INTEGER,
                BidLayerUID INTEGER
            )
            """
        )
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        conn.execute(
            "INSERT INTO BidAnnotationRects (UID, BidPageUID, BidLayerUID) "
            "VALUES (20, 10, 30)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0],
            0,
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)

    def test_delete_page_removes_all_ancillary_page_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidPageUID INTEGER REFERENCES BidPages(UID))"
        )
        conn.execute(
            "CREATE TABLE AffectDPCTypGroupViews ("
            "UID INTEGER PRIMARY KEY, BidTypGroupViewUID INTEGER "
            "REFERENCES BidTypGroupViews(UID))"
        )
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (10, 1)")
        for table in (
            "BidPercents",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "Boost",
            "DPCCalcFilter",
        ):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidPageUID INTEGER REFERENCES BidPages(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidPageUID) VALUES (?, 10)",
                (100 + len(table),),
            )
        conn.execute("INSERT INTO BidTypGroupViews (UID, BidPageUID) VALUES (20, 10)")
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (30, 20)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        for table in (
            "AffectDPCTypGroupViews",
            "BidTypGroupViews",
            "BidPercents",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "Boost",
            "DPCCalcFilter",
            "BidPages",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_page_delete_clears_master_page_and_cross_page_comment_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, MasterPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidComments ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "ParentCommentUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, ?, ?)",
            ((7, 1, None), (8, 1, 7), (9, 2, 7)),
        )
        conn.executemany(
            "INSERT INTO BidComments VALUES (?, 1, ?, ?)",
            ((70, 7, None), (80, 8, 70)),
        )
        conn.execute("INSERT INTO BidComments VALUES (90, 2, 9, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, MasterPageUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(8, None), (9, 7)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentCommentUID FROM BidComments ORDER BY UID"
            ).fetchall(),
            [(80, None), (90, 70)],
        )

    def test_page_delete_clears_surviving_takeoff_self_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "ParentUID INTEGER, TypGroupTakeoffUID INTEGER, "
            "TypPageTakeoffUID INTEGER, TypGroupMarkerUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidPages VALUES (?, ?)", ((7, 1), (8, 1), (9, 2)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (70, 1, 7, None, None, None, None),
                (80, 1, 8, 70, 70, 70, 70),
                (90, 2, 9, 70, 70, 70, 70),
            ),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, TypGroupTakeoffUID, TypPageTakeoffUID, "
                "TypGroupMarkerUID FROM BidTakeoffs"
            ).fetchall(),
            [(80, None, None, None, None), (90, 70, 70, 70, 70)],
        )

    def test_page_delete_removes_annotations_linked_by_to_takeoff(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDimensions ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidPages VALUES (?, 1)", ((7,), (8,)))
        conn.executemany("INSERT INTO BidTakeoffs VALUES (?, 1, ?)", ((70, 7), (80, 8)))
        conn.execute("INSERT INTO BidDimensions VALUES (90, 1, 8, 80, 70)")
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        self.assertEqual(conn.execute("SELECT * FROM BidDimensions").fetchall(), [])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(80,)]
        )

    def test_page_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidPageUID INTEGER)")
        conn.executemany("INSERT INTO BidPages VALUES (7, ?)", ((1,), (2,)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(_SqliteMdbOps(conn).delete_pages("malformed.mdb", ["7"]))
        self.assertIn("BidPages contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 2)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTakeoffs").fetchone()[0], 1
        )

    def test_bulk_page_delete_batches_cascade_statements(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, MasterPageUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, 1, NULL)",
            ((uid,) for uid in range(1, 102)),
        )
        conn.execute("UPDATE BidPages SET MasterPageUID=100 WHERE UID=101")
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertTrue(
            _SqliteDuplicateOps(conn).delete_pages(
                "large.mdb", [str(uid) for uid in range(1, 101)]
            )
        )
        selects = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT")
        ]
        updates = [
            sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")
        ]
        deletes = [
            sql for sql in statements if sql.lstrip().upper().startswith("DELETE")
        ]
        self.assertEqual(
            conn.execute(
                "SELECT UID, MasterPageUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(101, None)],
        )
        self.assertLessEqual(len(selects), 50)
        self.assertLessEqual(len(updates), 2)
        self.assertLessEqual(len(deletes), 2)


class SettingsOperationsSaveCoverSheetTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_measurement_system_save_normalizes_uoms_by_quantity_dimension(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Bid', 0)")
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT, "
            "Quantity1 INTEGER, UOM1 INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, 1, ?, ?, ?)",
            (
                (10, "Count", CALC_COUNT, UOM_LINEAR_FEET),
                (11, "Length", CALC_LINEAR_LENGTH, UOM_LINEAR_FEET),
            ),
        )
        operations = _SqliteDuplicateOps(conn)
        self.assertTrue(
            operations.save_cover_sheet(
                "bid.mdb", "1", {"job_name": "Bid", "measure_base": 1}
            )
        )
        self.assertEqual(
            conn.execute("SELECT UID, UOM1 FROM BidConditions ORDER BY UID").fetchall(),
            [(10, UOM_EACH), (11, UOM_M)],
        )
        self.assertTrue(
            operations.save_cover_sheet(
                "bid.mdb", "1", {"job_name": "Bid", "measure_base": 1}
            )
        )
        self.assertEqual(
            conn.execute("SELECT UID, UOM1 FROM BidConditions ORDER BY UID").fetchall(),
            [(10, UOM_EACH), (11, UOM_M)],
        )

    def test_page_folder_insert_reserves_dangling_parent_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Orphan', 8)")
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "malformed.mdb",
                "1",
                {
                    "job_name": "Original",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_0",
                            "name": "Unrelated",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, 8), (9, None)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidPageFolders AS child "
                "INNER JOIN BidPageFolders AS parent "
                "ON child.ParentUID=parent.UID"
            ).fetchone()[0],
            0,
        )

    def test_cover_sheet_rejects_folder_write_before_bid_update_when_table_missing(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Before')")
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_0",
                            "name": "Folder",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Before",
        )

    def test_cover_sheet_rejects_nested_folder_when_schema_is_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Before')")
        conn.execute(
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)"
        )
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "parent",
                            "name": "Parent",
                            "parent_uid": None,
                        },
                        {
                            "local_uid": "child",
                            "name": "Child",
                            "parent_uid": "parent",
                        },
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Before",
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidPageFolders").fetchall(), [])
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "1",
                {
                    "job_name": "Flat",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "root",
                            "name": "Root",
                            "parent_uid": None,
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT BidUID, Name FROM BidPageFolders").fetchall(),
            [(1, "Root")],
        )

    def test_page_insert_reserves_dangling_ancillary_page_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)")
        conn.execute("CREATE TABLE BidMarkedPages (UID INTEGER, BidPageUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Bid')")
        conn.execute("INSERT INTO BidPages VALUES (7, 1, 'Existing')")
        conn.execute("INSERT INTO BidMarkedPages VALUES (1, 8)")
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "malformed.mdb",
            "1",
            {
                "measure_base": 0,
                "pages": [
                    {
                        "uid": None,
                        "name": "New",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPages ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidMarkedPages AS marked "
                "INNER JOIN BidPages AS page ON marked.BidPageUID=page.UID"
            ).fetchone()[0],
            0,
        )

    def test_cover_sheet_folder_save_rejects_cycle_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original', 0)")
        conn.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 1, ?, NULL)",
            ((7, "First"), (8, "Second")),
        )
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "malformed.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "folders": [
                        {"uid": "7", "name": "First", "parent_uid": "8"},
                        {"uid": "8", "name": "Second", "parent_uid": "7"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, None), (8, None)],
        )

    def test_cover_sheet_new_folders_reject_pending_cycle_before_insert(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        self.assertFalse(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "malformed.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "new_folders": [
                        {"local_uid": "new_a", "name": "A", "parent_uid": "new_b"},
                        {"local_uid": "new_b", "name": "B", "parent_uid": "new_a"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPageFolders").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )

    def test_cover_sheet_folder_save_rejects_missing_or_cross_bid_parent(self):
        for parent_rows in ((), ((99, 2, "Other", None),)):
            with self.subTest(parent_rows=parent_rows):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
                conn.execute(
                    "CREATE TABLE BidPages "
                    "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
                )
                conn.execute(
                    "CREATE TABLE BidPageFolders "
                    "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
                )
                conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
                conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Child', NULL)")
                conn.executemany(
                    "INSERT INTO BidPageFolders VALUES (?, ?, ?, ?)", parent_rows
                )
                self.assertFalse(
                    _SqliteDuplicateOps(conn).save_cover_sheet(
                        "malformed.mdb",
                        "1",
                        {
                            "job_name": "Changed",
                            "measure_base": 0,
                            "folders": [
                                {
                                    "uid": "7",
                                    "name": "Child",
                                    "parent_uid": "99",
                                }
                            ],
                        },
                    )
                )
                self.assertEqual(
                    conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
                    "Original",
                )

    def test_cover_sheet_folder_save_accepts_valid_multi_level_graph(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPages "
            "(UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPageFolders "
            "(UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 1, ?, ?)",
            ((7, "Root", None), (8, "Middle", 7), (9, "Leaf", 8)),
        )
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "valid.mdb",
                "1",
                {
                    "job_name": "Changed",
                    "measure_base": 0,
                    "folders": [
                        {"uid": "7", "name": "Root", "parent_uid": None},
                        {"uid": "8", "name": "Middle", "parent_uid": "7"},
                        {"uid": "9", "name": "Leaf", "parent_uid": "8"},
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(7, None), (8, 7), (9, 8)],
        )

    def test_cover_sheet_page_move_rejects_cross_bid_folder_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER, Name TEXT, "
            "OverlayImagePath TEXT, ScaleFactor1 REAL, ScaleFactor2 REAL)"
        )
        conn.execute("INSERT INTO Bids VALUES (1, 'Original')")
        conn.execute("INSERT INTO Bids VALUES (2, 'Other')")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 2, NULL, 'Other')")
        conn.execute(
            "INSERT INTO BidPages VALUES (10, 1, NULL, 'Page', '', 0.125, 12.0)"
        )
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "malformed.mdb",
            "1",
            {
                "measure_base": 0,
                "job_name": "Changed",
                "pages": [
                    {
                        "uid": "10",
                        "folder_uid": "7",
                        "name": "Page",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Original",
        )
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageFolderUID FROM BidPages WHERE UID=10"
            ).fetchone()[0]
        )

    def test_cover_sheet_save_rejects_cross_bid_page_before_bid_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, OverlayImagePath TEXT, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL)"
        )
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, 0)",
            ((1, "Expected bid"), (2, "Other bid")),
        )
        conn.execute("INSERT INTO BidPages VALUES (20, 2, 'Other page', '', 1, 1)")
        success = _SqliteDuplicateOps(conn).save_cover_sheet(
            "malformed.mdb",
            "1",
            {
                "job_name": "Unexpected mutation",
                "measure_base": 0,
                "pages": [
                    {
                        "uid": "20",
                        "name": "Unexpected page mutation",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 1.0,
                        "show_mode": 0,
                    }
                ],
            },
        )
        self.assertFalse(success)
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Expected bid",
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidPages WHERE UID=20").fetchone()[0],
            "Other page",
        )

    def test_cover_sheet_rejects_missing_optional_master_reference_before_bid_update(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, NULL)")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        conn.execute("INSERT INTO JobStatuses VALUES (8)")
        conn.execute("CREATE TABLE Employees (UID INTEGER)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).save_cover_sheet(
                    "malformed.mdb",
                    "7",
                    {
                        "job_name": "After",
                        "job_status_uid": "8",
                        "estimator_uid": "9",
                        "measure_base": 0,
                    },
                )
            )
        self.assertIn("Employees has no row for UID 9", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT JobName, JobStatusUID, EstimatorUID FROM Bids WHERE UID=7"
            ).fetchone(),
            ("Before", 8, None),
        )

    def test_cover_sheet_batches_page_and_folder_deletes(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER, "
            "MasterPageUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPageFolders VALUES (?, 1, NULL, ?)",
            ((uid, f"Folder {uid}") for uid in range(1, 101)),
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, 1, ?, NULL)",
            ((100 + uid, uid) for uid in range(1, 101)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "large.mdb",
                "1",
                {
                    "deleted_page_uids": [str(uid) for uid in range(101, 201)],
                    "deleted_folder_uids": [str(uid) for uid in range(1, 101)],
                },
            )
        )
        updates = [
            sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")
        ]
        deletes = [
            sql for sql in statements if sql.lstrip().upper().startswith("DELETE")
        ]
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone()[0], 0)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPageFolders").fetchone()[0], 0
        )
        self.assertLessEqual(len(updates), 7)
        self.assertLessEqual(len(deletes), 4)

    def test_cover_sheet_preserves_forward_new_folder_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER NOT NULL, Name TEXT, "
            "ParentUID INTEGER REFERENCES BidPageFolders(UID))"
        )
        conn.commit()
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "large.mdb",
                "1",
                {
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_child",
                            "name": "Child",
                            "parent_uid": "new_parent",
                        },
                        {
                            "local_uid": "new_parent",
                            "name": "Parent",
                            "parent_uid": None,
                        },
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(1, 2, "Child"), (2, None, "Parent")],
        )

    def test_cover_sheet_forward_folder_order_is_stable_at_batch_boundaries(self):
        for row_count in (49, 50, 51, 99, 100, 101, 249, 250, 251, 999, 1000):
            with self.subTest(row_count=row_count):
                conn = sqlite3.connect(":memory:")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute(
                    "CREATE TABLE BidPageFolders ("
                    "UID INTEGER PRIMARY KEY, BidUID INTEGER NOT NULL, Name TEXT, "
                    "ParentUID INTEGER REFERENCES BidPageFolders(UID))"
                )
                conn.commit()
                folders = [
                    {
                        "local_uid": f"new_{index}",
                        "name": f"Folder {index}",
                        "parent_uid": (
                            f"new_{index + 1}" if index + 1 < row_count else None
                        ),
                    }
                    for index in range(row_count)
                ]
                self.assertTrue(
                    _SqliteDuplicateOps(conn).save_cover_sheet(
                        "large.mdb",
                        "1",
                        {"measure_base": 0, "new_folders": folders},
                    )
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, ParentUID, Name "
                        "FROM BidPageFolders ORDER BY UID"
                    ).fetchall(),
                    [
                        (
                            uid,
                            uid + 1 if uid < row_count else None,
                            f"Folder {uid - 1}",
                        )
                        for uid in range(1, row_count + 1)
                    ],
                )

    def test_cover_sheet_batches_new_page_identity_scans(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Width REAL, Height REAL)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        result = _SqliteDuplicateOps(conn).save_cover_sheet(
            "large.mdb",
            "1",
            {
                "pages": [
                    {
                        "uid": None,
                        "name": f"Page {index}",
                        "width": 42.0,
                        "height": 30.0,
                        "scale_factor1": 0.125,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                    }
                    for index in range(100)
                ]
            },
        )
        max_uid_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        self.assertTrue(result)
        self.assertEqual(len(max_uid_queries), 1)

    def test_cover_sheet_omits_master_fields_when_legacy_tables_are_unavailable(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)"
        )
        conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, 9)")
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "legacy.mdb",
                "7",
                {"job_name": "After", "measure_base": 0},
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT JobName, JobStatusUID, EstimatorUID FROM Bids WHERE UID=7"
            ).fetchone(),
            ("After", 8, 9),
        )

    def test_cover_sheet_rejects_new_master_reference_when_table_is_unavailable(self):
        for update_key, expected_message in (
            ("job_status_uid", "JobStatuses is unavailable"),
            ("estimator_uid", "Employees is unavailable"),
        ):
            with self.subTest(update_key=update_key):
                conn = sqlite3.connect(":memory:")
                conn.execute(
                    "CREATE TABLE Bids ("
                    "UID INTEGER, JobName TEXT, JobStatusUID INTEGER, "
                    "EstimatorUID INTEGER)"
                )
                conn.execute("INSERT INTO Bids VALUES (7, 'Before', 8, 9)")
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertFalse(
                        _SqliteDuplicateOps(conn).save_cover_sheet(
                            "legacy.mdb",
                            "7",
                            {
                                "job_name": "After",
                                "measure_base": 0,
                                update_key: "10",
                            },
                        )
                    )
                self.assertIn(expected_message, logs.output[0])
                self.assertEqual(
                    conn.execute(
                        "SELECT JobName, JobStatusUID, EstimatorUID "
                        "FROM Bids WHERE UID=7"
                    ).fetchone(),
                    ("Before", 8, 9),
                )


class SettingsOperationsSaveBidAreasTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_delete_area_removes_all_ancillary_area_dependents(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAreaTranslations ("
            "UID INTEGER PRIMARY KEY, MasterAreaUID INTEGER REFERENCES BidAreas(UID), "
            "TranslateAreaUID INTEGER REFERENCES BidAreas(UID))"
        )
        conn.execute("INSERT INTO BidAreas (UID, BidUID) VALUES (10, 1)")
        for table in (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
        ):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidAreaUID INTEGER REFERENCES BidAreas(UID))"
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidAreaUID) VALUES (?, 10)",
                (100 + len(table),),
            )
        conn.execute(
            "INSERT INTO BidAreaTranslations "
            "(UID, MasterAreaUID, TranslateAreaUID) VALUES (20, 10, 10)"
        )
        result = _SqliteMdbOps(conn).save_bid_areas(
            "bid.mdb",
            "1",
            BidAreaChangeset(new=[], updated=[], deleted_uids=["10"]),
        )
        self.assertEqual(result, {})
        for table in (
            "BidAreaTranslations",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "BidAreas",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                )

    def test_area_save_rejects_parent_cycle_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?, 0, '')",
            ((7, None, "First"), (8, 7, "Second")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "8", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidAreas ORDER BY UID"
            ).fetchall(),
            [(7, None, "First"), (8, 7, "Second")],
        )

    def test_area_save_rejects_cross_bid_parent_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, ?, NULL, ?, 0, '')",
            ((7, 1, "Source"), (8, 2, "Other bid")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "8", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT ParentUID, Name FROM BidAreas WHERE UID=7").fetchone(),
            (None, "Source"),
        )

    def test_area_save_rejects_deleting_parent_with_surviving_child(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, ?, 0, '')",
            ((7, None, "Parent"), (8, 7, "Child")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(new=[], updated=[], deleted_uids=["7"]),
        )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 2)

    def test_legacy_area_save_rejects_unpersistable_hierarchy(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        conn.executemany(
            "INSERT INTO BidAreas VALUES (?, 1, ?, 0, '')",
            ((7, "First"), (8, "Second")),
        )
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "legacy.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("8", "1", "7", "Changed", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidAreas ORDER BY UID").fetchall(),
            [(7, "First"), (8, "Second")],
        )

    def test_legacy_area_save_accepts_flat_update_without_parent_column(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, Name TEXT, Sequence INTEGER, GUID TEXT)"
        )
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, 'Before', 0, '')")
        result = _SqliteDuplicateOps(conn).save_bid_areas(
            "legacy.mdb",
            "1",
            BidAreaChangeset(
                new=[],
                updated=[BidArea("7", "1", "", "After", 0)],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT Name FROM BidAreas WHERE UID=7").fetchone()[0],
            "After",
        )

    def test_area_insert_reserves_dangling_indirect_area_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.execute("CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)")
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, NULL, 'Existing', 1, '')")
        conn.execute("INSERT INTO BidTypAreaCounts VALUES (1, 8)")
        uid_map = _SqliteDuplicateOps(conn).save_bid_areas(
            "malformed.mdb",
            "1",
            BidAreaChangeset(
                new=[BidArea("new_0", "1", "", "New", 2)],
                updated=[],
                deleted_uids=[],
            ),
        )
        self.assertEqual(uid_map, {"new_0": "9"})
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAreas ORDER BY UID").fetchall(),
            [(7,), (9,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidTypAreaCounts AS counts "
                "INNER JOIN BidAreas AS area ON counts.BidAreaUID=area.UID"
            ).fetchone()[0],
            0,
        )

    def test_area_delete_rejects_duplicate_physical_uid_before_cascade(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidTakeoffs (UID INTEGER, BidAreaUID INTEGER)")
        conn.executemany("INSERT INTO BidAreas VALUES (?, ?)", ((7, 1), (7, 1)))
        conn.execute("INSERT INTO BidTakeoffs VALUES (70, 7)")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteMdbOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(new=[], updated=[], deleted_uids=["7"]),
            )
        self.assertEqual(result, {})
        self.assertIn("BidAreas contains duplicate UID 7", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 2)
        self.assertEqual(
            conn.execute("SELECT BidAreaUID FROM BidTakeoffs").fetchall(), [(7,)]
        )

    def test_bid_area_batch_rejects_duplicate_correlation_uids_atomically(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        with self.assertLogs("test", level="ERROR"):
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(
                    new=[
                        BidArea("new_same", "1", "", "First", 0),
                        BidArea("new_same", "1", "", "Second", 1),
                    ],
                    updated=[],
                    deleted_uids=[],
                ),
            )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 0)

    def test_bid_area_batch_rejects_correlation_uid_colliding_with_existing_area(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.execute("INSERT INTO BidAreas VALUES (7, 1, NULL, 'Existing', 0, '')")
        with self.assertLogs("test", level="ERROR"):
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(
                    new=[BidArea("7", "1", "", "New", 1)],
                    updated=[],
                    deleted_uids=[],
                ),
            )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidAreas ORDER BY UID").fetchall(),
            [(7, "Existing")],
        )

    def test_bid_area_batch_allocates_once_and_preserves_forward_parent(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        new_areas = [
            BidArea("new_0", "1", "new_99", "Forward child", 0),
            *(
                BidArea(f"new_{index}", "1", "", f"Area {index}", index)
                for index in range(1, 99)
            ),
            BidArea("new_99", "1", "", "Forward parent", 99),
        ]
        statements = []
        conn.set_trace_callback(statements.append)
        uid_map = _SqliteDuplicateOps(conn).save_bid_areas(
            "large.mdb",
            "1",
            BidAreaChangeset(new=new_areas, updated=[], deleted_uids=[]),
        )
        max_uid_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        self.assertEqual(len(uid_map), 100)
        self.assertEqual(len(max_uid_queries), 2)
        self.assertEqual(
            conn.execute(
                "SELECT ParentUID FROM BidAreas WHERE UID=?", uid_map["new_0"]
            ).fetchone()[0],
            int(uid_map["new_99"]),
        )

    def test_bid_area_batch_inserts_forward_parent_before_child_for_fk_backends(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER NOT NULL, "
            "ParentUID INTEGER REFERENCES BidAreas(UID), Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        conn.commit()
        uid_map = _SqliteDuplicateOps(conn).save_bid_areas(
            "large.mdb",
            "1",
            BidAreaChangeset(
                new=[
                    BidArea("new_child", "1", "new_parent", "Child", 1),
                    BidArea("new_parent", "1", "", "Parent", 0),
                ],
                updated=[],
                deleted_uids=[],
            ),
        )
        self.assertEqual(
            uid_map,
            {"new_child": "1", "new_parent": "2"},
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidAreas ORDER BY UID"
            ).fetchall(),
            [(1, 2, "Child"), (2, None, "Parent")],
        )

    def test_bid_area_forward_parent_order_is_stable_at_batch_boundaries(self):
        for row_count in (49, 50, 51, 99, 100, 101, 249, 250, 251, 999, 1000):
            with self.subTest(row_count=row_count):
                conn = sqlite3.connect(":memory:")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute(
                    "CREATE TABLE BidAreas ("
                    "UID INTEGER PRIMARY KEY, BidUID INTEGER NOT NULL, "
                    "ParentUID INTEGER REFERENCES BidAreas(UID), Name TEXT, "
                    "Sequence INTEGER, GUID TEXT)"
                )
                conn.commit()
                areas = [
                    BidArea(
                        f"new_{index}",
                        "1",
                        f"new_{index + 1}" if index + 1 < row_count else "",
                        f"Area {index}",
                        index,
                    )
                    for index in range(row_count)
                ]
                uid_map = _SqliteDuplicateOps(conn).save_bid_areas(
                    "large.mdb",
                    "1",
                    BidAreaChangeset(new=areas, updated=[], deleted_uids=[]),
                )
                self.assertEqual(len(uid_map), row_count)
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, ParentUID, Name, Sequence "
                        "FROM BidAreas ORDER BY UID"
                    ).fetchall(),
                    [
                        (
                            uid,
                            uid + 1 if uid < row_count else None,
                            f"Area {uid - 1}",
                            uid - 1,
                        )
                        for uid in range(1, row_count + 1)
                    ],
                )

    def test_bid_area_batch_failure_returns_no_allocated_identity_map(self):
        class FailingAreaOps(_SqliteDuplicateOps):
            def __init__(self, connection):
                super().__init__(connection)
                self.area_insert_count = 0

            def _execute_insert_values(
                self, cursor, schema, table, values, required, operation
            ):
                if table == "BidAreas":
                    self.area_insert_count += 1
                    if self.area_insert_count == 2:
                        raise RuntimeError("forced second area insert failure")
                return super()._execute_insert_values(
                    cursor, schema, table, values, required, operation
                )

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        result = FailingAreaOps(conn).save_bid_areas(
            "large.mdb",
            "1",
            BidAreaChangeset(
                new=[
                    BidArea("new_0", "1", "", "First", 0),
                    BidArea("new_1", "1", "", "Second", 1),
                ],
                updated=[],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {})

    def test_bid_area_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "99",
                BidAreaChangeset(
                    new=[BidArea("new_0", "99", "", "Area", 0)],
                    updated=[],
                    deleted_uids=[],
                ),
            )
        self.assertEqual(result, {})
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 0)


class SettingsOperationsSaveConditionTypesTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_save_condition_types_refuses_type_used_by_conditions(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Used')")
        conn.execute("INSERT INTO BidConditions (UID, CdnTypeUID) VALUES (10, 1)")
        with self.assertLogs("test", level="WARNING"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1"]}
            )
        self.assertIsNone(result)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 1)

    def test_save_condition_types_allows_unused_type_delete(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Unused')")
        result = _SqliteMdbOps(conn).save_condition_types(
            "bid.mdb", {"deleted_uids": ["1"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], 0)

    def test_save_condition_types_preflights_complete_delete_batch(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute(
            """
            CREATE TABLE BidConditions (
                UID INTEGER PRIMARY KEY,
                CdnTypeUID INTEGER REFERENCES CdnTypes(UID)
            )
            """
        )
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (1, 'Unused')")
        conn.execute("INSERT INTO CdnTypes (UID, Name) VALUES (2, 'Used')")
        conn.execute("INSERT INTO BidConditions (UID, CdnTypeUID) VALUES (10, 2)")
        with self.assertLogs("test", level="WARNING"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1", "2"]}
            )
        self.assertIsNone(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM CdnTypes ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_save_condition_types_reports_schema_failure(self):
        conn = sqlite3.connect(":memory:")
        with self.assertLogs("test", level="ERROR"):
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"new": [{"uid": "new_0", "name": "Concrete"}]}
            )
        self.assertIsNone(result)

    def test_condition_type_batch_checks_all_usage_chunks_before_delete(self):
        row_count = 51
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)")
        conn.executemany(
            "INSERT INTO CdnTypes VALUES (?, ?)",
            ((uid, f"Type {uid}") for uid in range(1, row_count + 1)),
        )
        conn.execute("INSERT INTO BidConditions VALUES (1000, 51)")
        statements = []
        conn.set_trace_callback(statements.append)
        with self.assertLogs("test", level="WARNING"):
            result = _SqliteDuplicateOps(conn).save_condition_types(
                "large.mdb",
                {"deleted_uids": [str(uid) for uid in range(1, row_count + 1)]},
            )
        self.assertIsNone(result)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone()[0], row_count
        )
        self.assertFalse(
            any(
                sql.lstrip().upper().startswith("DELETE FROM [CDNTYPES]")
                for sql in statements
            )
        )


class SettingsOperationsSaveEmployeesTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_save_employees_returns_uid_map_for_new_employee(self):
        class EmployeeOps(_SqliteMdbOps):
            def _next_uid(self, cursor, table):
                cursor.execute(f"SELECT MAX([UID]) FROM [{table}]")
                row = cursor.fetchone()
                return int(row[0]) + 1 if row and row[0] is not None else 1

            def _execute_insert_values(
                self, cursor, _schema, table, values, _required_columns, _operation
            ):
                columns = list(values)
                column_sql = ", ".join(f"[{column}]" for column in columns)
                placeholders = ", ".join("?" for _column in columns)
                cursor.execute(
                    f"INSERT INTO [{table}] ({column_sql}) VALUES ({placeholders})",
                    *[values[column] for column in columns],
                )

        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE Employees (
                UID INTEGER PRIMARY KEY,
                EmployeeNo TEXT,
                FirstName TEXT,
                LastName TEXT,
                Address1 TEXT,
                Address2 TEXT,
                City TEXT,
                State TEXT,
                Zip TEXT,
                HomePhone TEXT,
                MobilePhone TEXT,
                EMail TEXT,
                PayClassUID INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, LastName) "
            "VALUES (7, 'E1', 'Ava', 'Lee')"
        )
        employee = SimpleNamespace(
            uid="new_0",
            employee_no="E2",
            first_name="Mia",
            last_name="Ray",
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            home_phone="",
            mobile_phone="",
            email="",
            pay_class_uid="",
        )
        result = EmployeeOps(conn).save_employees(
            "bid.mdb", {"new": [employee], "updated": [], "deleted_uids": []}
        )
        self.assertEqual(result, {"new_0": "8"})
        inserted = conn.execute(
            "SELECT EmployeeNo, FirstName, LastName FROM Employees WHERE UID=8"
        ).fetchone()
        self.assertEqual(inserted, ("E2", "Mia", "Ray"))

    def test_employee_batch_rejects_missing_pay_class_before_first_write(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        conn.execute("INSERT INTO PayClasses VALUES (1, 'Existing')")
        conn.execute(
            "CREATE TABLE Employees ("
            "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, "
            "PayClassUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7, 'E1', 'Before', 'User', 1)")

        def employee(uid, employee_no, first_name, pay_class_uid):
            return SimpleNamespace(
                uid=uid,
                employee_no=employee_no,
                first_name=first_name,
                last_name="User",
                address1="",
                address2="",
                city="",
                state="",
                zip="",
                home_phone="",
                mobile_phone="",
                email="",
                pay_class_uid=pay_class_uid,
            )

        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_employees(
                "malformed.mdb",
                {
                    "updated": [employee("7", "E1", "Changed", "1")],
                    "new": [employee("new_0", "E2", "New", "99")],
                },
            )
        self.assertIsNone(result)
        self.assertIn("PayClasses has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT UID, EmployeeNo, FirstName, PayClassUID "
                "FROM Employees ORDER BY UID"
            ).fetchall(),
            [(7, "E1", "Before", 1)],
        )

    def test_employee_update_rejects_duplicate_physical_uid(self):
        class EmployeeOps(_SqliteMdbOps):
            @staticmethod
            def _execute_update_values(
                cursor,
                _schema,
                table,
                values,
                _required_columns,
                where_sql,
                where_params,
                _operation,
            ):
                columns = list(values)
                assignments = ", ".join(f"[{column}]=?" for column in columns)
                cursor.execute(
                    f"UPDATE [{table}] SET {assignments} WHERE {where_sql}",
                    *[values[column] for column in columns],
                    *where_params,
                )

        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Employees ("
            "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, "
            "Address1 TEXT, Address2 TEXT, City TEXT, State TEXT, Zip TEXT, "
            "HomePhone TEXT, MobilePhone TEXT, EMail TEXT, PayClassUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName) VALUES (7, ?, ?)",
            (("E1", "First"), ("E2", "Conflicting")),
        )
        employee = SimpleNamespace(
            uid="7",
            employee_no="UPDATED",
            first_name="Updated",
            last_name="",
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            home_phone="",
            mobile_phone="",
            email="",
            pay_class_uid="",
        )
        with self.assertLogs("test", level="ERROR") as logs:
            result = EmployeeOps(conn).save_employees(
                "malformed.mdb",
                {"new": [], "updated": [employee], "deleted_uids": []},
            )
        self.assertIsNone(result)
        self.assertIn("Employees contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute(
                "SELECT EmployeeNo, FirstName FROM Employees ORDER BY rowid"
            ).fetchall(),
            [("E1", "First"), ("E2", "Conflicting")],
        )

    def test_delete_employee_clears_all_direct_bid_roles(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, EstimatorUID INTEGER, "
            "PrManagerUID INTEGER, JobSiteManagerUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO Bids VALUES (1, 7, 7, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT EstimatorUID, PrManagerUID, JobSiteManagerUID FROM Bids"
            ).fetchone(),
            (None, None, None),
        )

    def test_delete_employee_removes_direct_dpc_subscriber_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidEmployees ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidTimeCards ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE ConditionSets ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO BidEmployees VALUES (70, 7)")
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 7)")
        conn.execute("INSERT INTO BidTimeCards VALUES (701, 70)")
        conn.execute("INSERT INTO ConditionSets VALUES (702, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDPCSubscribers").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidEmployees").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidTimeCards").fetchone()[0], 0
        )
        self.assertIsNone(
            conn.execute("SELECT EmployeeUID FROM ConditionSets").fetchone()[0]
        )

    def test_delete_employee_preserves_subscriber_for_colliding_bid_employee_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidEmployees ("
            "UID INTEGER PRIMARY KEY, EmployeeUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.executemany("INSERT INTO Employees VALUES (?)", [(7,), (70,)])
        conn.executemany("INSERT INTO BidEmployees VALUES (?, ?)", [(70, 7), (71, 70)])
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 70)")
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT BidEmployeeUID FROM BidDPCSubscribers").fetchall(),
            [(70,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID, EmployeeUID FROM BidEmployees").fetchall(),
            [(71, 70)],
        )

    def test_delete_employee_cleans_dpc_subscriber_without_bid_employees_table(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Employees (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE BidDPCSubscribers ("
            "UID INTEGER PRIMARY KEY, BidEmployeeUID INTEGER)"
        )
        conn.execute("INSERT INTO Employees VALUES (7)")
        conn.execute("INSERT INTO BidDPCSubscribers VALUES (700, 7)")
        result = _SqliteMdbOps(conn).save_employees(
            "test.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDPCSubscribers").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM Employees").fetchone()[0], 0
        )


class SettingsOperationsSaveJobStatusesTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_master_data_inserts_do_not_claim_dangling_reference_uids(self):
        employee = SimpleNamespace(
            uid="new_employee",
            employee_no="E2",
            first_name="Mia",
            last_name="Ray",
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            home_phone="",
            mobile_phone="",
            email="",
            pay_class_uid="",
        )
        fixtures = (
            (
                "JobStatuses",
                (
                    "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
                ),
                (
                    "INSERT INTO JobStatuses VALUES (1, 'Existing')",
                    "INSERT INTO Bids VALUES (10, 2)",
                ),
                lambda ops: ops.save_job_statuses(
                    "malformed.mdb",
                    {"new": [{"uid": "new_status", "name": "New"}]},
                ),
                {"new_status": "3"},
            ),
            (
                "Employees",
                (
                    "CREATE TABLE Employees ("
                    "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER)",
                ),
                (
                    "INSERT INTO Employees VALUES (1, 'E1', 'Ava', 'Lee')",
                    "INSERT INTO Bids VALUES (10, 2)",
                ),
                lambda ops: ops.save_employees("malformed.mdb", {"new": [employee]}),
                {"new_employee": "3"},
            ),
            (
                "PayClasses",
                (
                    "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)",
                ),
                (
                    "INSERT INTO PayClasses VALUES (1, 'Existing')",
                    "INSERT INTO Employees VALUES (10, 2)",
                ),
                lambda ops: ops.save_pay_classes(
                    "malformed.mdb",
                    {"new": [{"uid": "new_class", "name": "New"}]},
                ),
                {"new_class": "3"},
            ),
            (
                "CdnTypes",
                (
                    "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                    "CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)",
                ),
                (
                    "INSERT INTO CdnTypes VALUES (1, 'Existing')",
                    "INSERT INTO BidConditions VALUES (10, 2)",
                ),
                lambda ops: ops.save_condition_types(
                    "malformed.mdb",
                    {"new": [{"uid": "new_type", "name": "New"}]},
                ),
                {"new_type": "3"},
            ),
        )
        for table, ddl, inserts, save, expected in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                for statement in ddl:
                    conn.execute(statement)
                for statement in inserts:
                    conn.execute(statement)
                result = save(_SqliteDuplicateOps(conn))
                self.assertEqual(result, expected)
                self.assertEqual(
                    conn.execute(
                        f"SELECT [UID] FROM [{table}] ORDER BY [UID]"
                    ).fetchall(),
                    [(1,), (3,)],
                )

    def test_master_data_batch_creation_scans_each_uid_space_once(self):
        def employee(index):
            return SimpleNamespace(
                uid=f"new_employee_{index}",
                employee_no=f"E{index}",
                first_name="Employee",
                last_name=str(index),
                address1="",
                address2="",
                city="",
                state="",
                zip="",
                home_phone="",
                mobile_phone="",
                email="",
                pay_class_uid="",
            )

        fixtures = (
            (
                "JobStatuses",
                "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_job_statuses(
                    "large.mdb",
                    {
                        "new": [
                            {"uid": f"new_status_{index}", "name": f"Status {index}"}
                            for index in range(100)
                        ]
                    },
                ),
            ),
            (
                "Employees",
                "CREATE TABLE Employees ("
                "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT)",
                lambda ops: ops.save_employees(
                    "large.mdb", {"new": [employee(index) for index in range(100)]}
                ),
            ),
            (
                "PayClasses",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_pay_classes(
                    "large.mdb",
                    {
                        "new": [
                            {"uid": f"new_class_{index}", "name": f"Class {index}"}
                            for index in range(100)
                        ]
                    },
                ),
            ),
            (
                "CdnTypes",
                "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_condition_types(
                    "large.mdb",
                    {
                        "new": [
                            {"uid": f"new_type_{index}", "name": f"Type {index}"}
                            for index in range(100)
                        ]
                    },
                ),
            ),
        )
        for table, create_sql, save in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(create_sql)
                statements = []
                conn.set_trace_callback(statements.append)
                uid_map = save(_SqliteDuplicateOps(conn))
                max_uid_queries = [
                    sql
                    for sql in statements
                    if sql.lstrip().upper().startswith("SELECT MAX")
                ]
                self.assertEqual(len(uid_map), 100)
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    100,
                )
                self.assertEqual(len(max_uid_queries), 1)

    def test_master_data_batch_rejects_duplicate_correlation_uids_atomically(self):
        duplicate_employee = SimpleNamespace(
            uid="new_same",
            employee_no="E1",
            first_name="Employee",
            last_name="One",
            address1="",
            address2="",
            city="",
            state="",
            zip="",
            home_phone="",
            mobile_phone="",
            email="",
            pay_class_uid="",
        )
        second_employee = SimpleNamespace(
            **{**vars(duplicate_employee), "employee_no": "E2", "last_name": "Two"}
        )
        fixtures = (
            (
                "JobStatuses",
                "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_job_statuses(
                    "malformed.mdb",
                    {
                        "new": [
                            {"uid": "new_same", "name": "First"},
                            {"uid": "new_same", "name": "Second"},
                        ]
                    },
                ),
            ),
            (
                "Employees",
                "CREATE TABLE Employees ("
                "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT)",
                lambda ops: ops.save_employees(
                    "malformed.mdb",
                    {"new": [duplicate_employee, second_employee]},
                ),
            ),
            (
                "PayClasses",
                "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_pay_classes(
                    "malformed.mdb",
                    {
                        "new": [
                            {"uid": "new_same", "name": "First"},
                            {"uid": "new_same", "name": "Second"},
                        ]
                    },
                ),
            ),
            (
                "CdnTypes",
                "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                lambda ops: ops.save_condition_types(
                    "malformed.mdb",
                    {
                        "new": [
                            {"uid": "new_same", "name": "First"},
                            {"uid": "new_same", "name": "Second"},
                        ]
                    },
                ),
            ),
        )
        for table, create_sql, save in fixtures:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                conn.execute(create_sql)
                with self.assertLogs("test", level="ERROR"):
                    self.assertIsNone(save(_SqliteDuplicateOps(conn)))
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    0,
                )

    def test_master_data_batch_deletion_uses_bounded_statement_sets(self):
        row_count = 251
        deleted_uids = [str(uid) for uid in range(1, row_count + 1)]
        cases = (
            (
                "JobStatuses",
                (
                    "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
                ),
                (
                    (
                        "INSERT INTO JobStatuses VALUES (?, ?)",
                        [(uid, f"Status {uid}") for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO Bids VALUES (?, ?)",
                        [(1000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                ),
                lambda ops: ops.save_job_statuses(
                    "large.mdb", {"deleted_uids": deleted_uids}
                ),
                {"SELECT": 8, "UPDATE": 6, "DELETE": 6},
            ),
            (
                "Employees",
                (
                    "CREATE TABLE Employees (UID INTEGER)",
                    "CREATE TABLE Bids ("
                    "UID INTEGER, EstimatorUID INTEGER, PrManagerUID INTEGER, "
                    "JobSiteManagerUID INTEGER)",
                    "CREATE TABLE BidEmployees (UID INTEGER, EmployeeUID INTEGER)",
                    "CREATE TABLE BidDPCSubscribers ("
                    "UID INTEGER, BidEmployeeUID INTEGER)",
                    "CREATE TABLE BidTimeCards (UID INTEGER, BidEmployeeUID INTEGER)",
                    "CREATE TABLE ConditionSets (UID INTEGER, EmployeeUID INTEGER)",
                ),
                (
                    (
                        "INSERT INTO Employees VALUES (?)",
                        [(uid,) for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO Bids VALUES (?, ?, ?, ?)",
                        [
                            (1000 + uid, uid, uid, uid)
                            for uid in range(1, row_count + 1)
                        ],
                    ),
                    (
                        "INSERT INTO BidEmployees VALUES (?, ?)",
                        [(2000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO BidDPCSubscribers VALUES (?, ?)",
                        [(3000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO BidTimeCards VALUES (?, ?)",
                        [(4000 + uid, 2000 + uid) for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO ConditionSets VALUES (?, ?)",
                        [(5000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                ),
                lambda ops: ops.save_employees(
                    "large.mdb", {"deleted_uids": deleted_uids}
                ),
                {"SELECT": 13, "UPDATE": 24, "DELETE": 24},
            ),
            (
                "PayClasses",
                (
                    "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
                    "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER)",
                    "CREATE TABLE BidEmployees (UID INTEGER, PayClassUID INTEGER)",
                ),
                (
                    (
                        "INSERT INTO PayClasses VALUES (?, ?)",
                        [(uid, f"Class {uid}") for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO Employees VALUES (?, ?)",
                        [(1000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                    (
                        "INSERT INTO BidEmployees VALUES (?, ?)",
                        [(2000 + uid, uid) for uid in range(1, row_count + 1)],
                    ),
                ),
                lambda ops: ops.save_pay_classes(
                    "large.mdb", {"deleted_uids": deleted_uids}
                ),
                {"SELECT": 9, "UPDATE": 12, "DELETE": 6},
            ),
            (
                "CdnTypes",
                (
                    "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                    "CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)",
                ),
                (
                    (
                        "INSERT INTO CdnTypes VALUES (?, ?)",
                        [(uid, f"Type {uid}") for uid in range(1, row_count + 1)],
                    ),
                ),
                lambda ops: ops.save_condition_types(
                    "large.mdb", {"deleted_uids": deleted_uids}
                ),
                {"SELECT": 14, "UPDATE": 0, "DELETE": 6},
            ),
        )
        for table, ddl, inserts, save, expected_counts in cases:
            with self.subTest(table=table):
                conn = sqlite3.connect(":memory:")
                for statement in ddl:
                    conn.execute(statement)
                for statement, rows in inserts:
                    conn.executemany(statement, rows)
                statements = []
                conn.set_trace_callback(statements.append)
                self.assertEqual(save(_SqliteDuplicateOps(conn)), {})
                counts = {
                    operation: sum(
                        sql.lstrip().upper().startswith(operation) for sql in statements
                    )
                    for operation in ("SELECT", "UPDATE", "DELETE")
                }
                self.assertEqual(counts, expected_counts)
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    0,
                )


class SettingsOperationsUpdateBidJobStatusTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_bid_status_update_rejects_missing_master_reference(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (7, NULL)")
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteDuplicateOps(conn).update_bid_job_status(
                    "malformed.mdb", "7", "9"
                )
            )
        self.assertIn("JobStatuses has no row for UID 9", logs.output[0])
        self.assertIsNone(
            conn.execute("SELECT JobStatusUID FROM Bids WHERE UID=7").fetchone()[0]
        )

    def test_bid_status_update_rejects_duplicate_physical_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (7, ?)", ((10,), (20,)))
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).update_bid_job_status("malformed.mdb", "7", "30")
            )
        self.assertIn("Bids contains duplicate UID 7", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT JobStatusUID FROM Bids ORDER BY rowid").fetchall(),
            [(10,), (20,)],
        )


class SettingsOperationsSavePayClassesTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_delete_pay_class_clears_global_and_bid_employee_references(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE PayClasses (UID INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE Employees (UID INTEGER PRIMARY KEY, PayClassUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidEmployees (UID INTEGER PRIMARY KEY, PayClassUID INTEGER)"
        )
        conn.execute("INSERT INTO PayClasses VALUES (7)")
        conn.execute("INSERT INTO Employees VALUES (70, 7)")
        conn.execute("INSERT INTO BidEmployees VALUES (700, 7)")
        result = _SqliteMdbOps(conn).save_pay_classes(
            "test.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT PayClassUID FROM Employees").fetchall(), [(None,)]
        )
        self.assertEqual(
            conn.execute("SELECT PayClassUID FROM BidEmployees").fetchall(),
            [(None,)],
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM PayClasses").fetchone()[0], 0
        )


class SettingsOperationsCoverSheetPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _path_support__app()

    def tearDown(self):
        self.app.processEvents()

    def test_empty_pay_class_changes_report_success(self):
        operations = _path_support__CoverSheetSettingsOps()
        result = operations.save_pay_classes(
            "test.mdb",
            {"new": [], "updated": [], "deleted_uids": []},
        )
        self.assertEqual(result, {})

    def test_cover_sheet_normalizes_nullable_access_column_values(self):
        operations = _path_support__CoverSheetSettingsOps()
        self.assertTrue(
            operations.save_cover_sheet(
                "test.mdb",
                "7",
                {
                    "job_status_uid": "",
                    "job_name": "Bid",
                    "estimator_uid": None,
                    "bid_date": "",
                    "bid_no": "42",
                    "measure_base": 0,
                },
            )
        )
        bid_values = next(
            update["values"]
            for update in operations.updates
            if update["table"] == "Bids"
        )
        self.assertIsNone(bid_values["JobStatusUID"])
        self.assertIsNone(bid_values["EstimatorUID"])
        self.assertIsNone(bid_values["BidDate"])
        self.assertEqual(bid_values["BidNo"], 42)

    def test_cover_sheet_rejects_silent_noninteger_identifier_coercion(self):
        for invalid_value in (True, 7.5):
            with self.subTest(value=invalid_value):
                operations = _path_support__CoverSheetSettingsOps()
                self.assertFalse(
                    operations.save_cover_sheet(
                        "test.mdb",
                        "7",
                        {
                            "job_status_uid": invalid_value,
                            "job_name": "Bid",
                            "measure_base": 0,
                        },
                    )
                )
                self.assertEqual(operations.updates, [])

    def test_job_status_update_uses_none_instead_of_textual_null_sentinel(self):
        operations = _path_support__CoverSheetSettingsOps()
        self.assertTrue(operations.update_bid_job_status("test.mdb", "7", None))
        self.assertIsNone(operations.updates[-1]["values"]["JobStatusUID"])
        operations = _path_support__CoverSheetSettingsOps()
        self.assertFalse(operations.update_bid_job_status("test.mdb", "7", "NULL"))
        self.assertEqual(operations.updates, [])

    def test_new_master_data_returns_authoritative_uid_maps(self):
        operations = _path_support__CoverSheetSettingsOps()
        job_statuses = operations.save_job_statuses(
            "test.mdb",
            {
                "new": [{"uid": "new_status", "name": "Open"}],
                "updated": [],
                "deleted_uids": [],
            },
        )
        pay_classes = operations.save_pay_classes(
            "test.mdb",
            {
                "new": [{"uid": "new_pay", "name": "Field"}],
                "updated": [],
                "deleted_uids": [],
            },
        )
        self.assertEqual(job_statuses, {"new_status": "99"})
        self.assertEqual(pay_classes, {"new_pay": "99"})

    def test_existing_bid_area_can_move_under_new_area(self):
        operations = _path_support__CoverSheetSettingsOps()
        result = operations.save_bid_areas(
            "test.mdb",
            "7",
            BidAreaChangeset(
                new=[
                    BidArea(
                        uid="new_0",
                        bid_uid="7",
                        parent_uid="",
                        name="New Parent",
                        sequence=1,
                    )
                ],
                updated=[
                    BidArea(
                        uid="5",
                        bid_uid="7",
                        parent_uid="new_0",
                        name="Existing Child",
                        sequence=1,
                    )
                ],
                deleted_uids=[],
            ),
        )
        self.assertEqual(result, {"new_0": "99"})
        area_update = next(
            update for update in operations.updates if update["table"] == "BidAreas"
        )
        self.assertEqual(area_update["values"]["ParentUID"], 99)

    def test_cover_sheet_save_writes_page_image_paths_with_windows_separators(self):
        ops = _path_support__CoverSheetSettingsOps()
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _path_support__cover_sheet_page_update(
                        image_path=(
                            "C:/OCS Documents/OST/25-051 Marriott Element, "
                            "Capel Hill, NC/S-100.pdf"
                        ),
                        overlay_path="C:/OCS Documents/OST/overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(
            [update["table"] for update in ops.updates],
            ["Bids", "BidPages"],
        )
        bid_update = next(update for update in ops.updates if update["table"] == "Bids")
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertNotIn("ImageFolder", bid_update["values"])
        self.assertEqual(
            page_update["values"]["ImagePath"],
            (
                r"C:\OCS Documents\OST\25-051 Marriott Element, "
                r"Capel Hill, NC\S-100.pdf"
            ),
        )
        self.assertEqual(
            page_update["values"]["OverlayImagePath"],
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertEqual(
            page_update["values"]["OverlayRect"],
            "0.000000,0.000000,4032.000000,2880.000000",
        )
        self.assertEqual(page_update["values"]["OverlayOffsetX"], 0.0)
        self.assertEqual(page_update["values"]["OverlayOffsetY"], 0.0)
        self.assertEqual(page_update["values"]["OverlayRotation"], 0.0)
        self.assertEqual(page_update["values"]["OverlayResized"], 0)
        self.assertEqual(page_update["values"]["DeskewRotationOverlay"], 0.0)
        self.assertEqual(page_update["values"]["SheetNo"], "S-100")

    def test_cover_sheet_overlay_only_removal_restores_original_and_clears_metadata(
        self,
    ):
        ops = _path_support__CoverSheetSettingsOps()
        ops.conn.cursor_obj.current_overlay_path = r"C:\Plans\overlay.pdf"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    {
                        **_path_support__cover_sheet_page_update(
                            image_path=r"C:\Plans\original.pdf",
                            overlay_path="",
                        ),
                        "show_mode": 1,
                    }
                ],
            },
        )
        self.assertTrue(success)
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            {
                key: page_update["values"][key]
                for key in (
                    "OverlayImagePath",
                    "Show",
                    "OverlayRect",
                    "OverlayOffsetX",
                    "OverlayOffsetY",
                    "OverlayRotation",
                    "OverlayResized",
                    "DeskewRotationOverlay",
                )
            },
            {
                "OverlayImagePath": "",
                "Show": 0,
                "OverlayRect": "",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_cover_sheet_page_scale_change_rescales_existing_page_positions(self):
        ops = _path_support__ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [_path_support__cover_sheet_page_update(scale_factor1=0.25)],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [(11, 0.5)])
        self.assertEqual(ops.overlay_rescale_calls, [(11, 0.5)])

    def test_cover_sheet_unchanged_page_scale_does_not_rescale_positions(self):
        ops = _path_support__ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [_path_support__cover_sheet_page_update()],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [])
        self.assertEqual(ops.overlay_rescale_calls, [])

    def test_cover_sheet_overlay_replacement_uses_new_calibration_once(self):
        ops = _path_support__ScaleCoverSheetOps(old_sf1=0.1875, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _path_support__cover_sheet_page_update(
                        scale_factor1=0.125,
                        overlay_path=r"C:\Plans\overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.overlay_rescale_calls, [])
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            page_update["values"]["OverlayRect"],
            "0.000000,0.000000,4032.000000,2880.000000",
        )

    def test_cover_sheet_separator_only_overlay_path_change_preserves_rectangle(self):
        ops = _path_support__CoverSheetSettingsOps()
        ops.conn.cursor_obj.current_overlay_path = "C:/Plans/overlay.pdf"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _path_support__cover_sheet_page_update(
                        overlay_path=r"C:\Plans\overlay.pdf",
                    )
                ],
            },
        )
        self.assertTrue(success)
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(
            page_update["values"]["OverlayImagePath"],
            r"C:\Plans\overlay.pdf",
        )
        self.assertNotIn("OverlayRect", page_update["values"])
        self.assertNotIn("OverlayOffsetX", page_update["values"])
        self.assertNotIn("OverlayOffsetY", page_update["values"])

    def test_cover_sheet_new_page_scale_does_not_rescale_positions(self):
        ops = _path_support__ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [
                    _path_support__cover_sheet_page_update(
                        uid=None,
                        scale_factor1=0.25,
                        sheet_no="S-101",
                        name="Level 2",
                    )
                ],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [])
        self.assertEqual([insert["table"] for insert in ops.inserts], ["BidPages"])

    def test_cover_sheet_existing_page_can_move_into_new_folder(self):
        ops = _path_support__CoverSheetSettingsOps()
        page = _path_support__cover_sheet_page_update()
        page["folder_uid"] = "new_folder_0"
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "new_folders": [
                    {
                        "local_uid": "new_folder_0",
                        "name": "New Folder",
                        "parent_uid": None,
                    }
                ],
                "pages": [page],
            },
        )
        self.assertTrue(success)
        folder_insert = next(
            insert for insert in ops.inserts if insert["table"] == "BidPageFolders"
        )
        page_update = next(
            update for update in ops.updates if update["table"] == "BidPages"
        )
        self.assertEqual(folder_insert["values"]["UID"], 99)
        self.assertEqual(page_update["values"]["BidPageFolderUID"], 99)

    def test_cover_sheet_existing_folder_can_move_into_new_folder(self):
        ops = _path_support__CoverSheetSettingsOps()
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "new_folders": [
                    {
                        "local_uid": "new_folder_0",
                        "name": "New Parent",
                        "parent_uid": None,
                    }
                ],
                "folders": [
                    {
                        "uid": "5",
                        "name": "Existing Child",
                        "parent_uid": "new_folder_0",
                    }
                ],
                "pages": [],
            },
        )
        self.assertTrue(success)
        folder_update = next(
            update for update in ops.updates if update["table"] == "BidPageFolders"
        )
        self.assertEqual(folder_update["values"]["ParentUID"], 99)

    def test_cover_sheet_bulk_delete_uses_one_transaction_and_bounded_cascade(self):
        ops = _path_support__BulkDeleteCoverSheetOps()
        page_count = 225
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "deleted_page_uids": [str(index) for index in range(1, page_count + 1)],
                "pages": [],
            },
        )
        chunk_count = (page_count + 49) // 50
        per_chunk_statement_count = len(PAGE_DELETE_CHILD_TABLES) + 11
        self.assertTrue(success)
        self.assertEqual(ops.conn.enter_count, 1)
        self.assertEqual(ops.conn.exit_count, 1)
        self.assertEqual(
            len(ops.conn.cursor_obj.calls),
            3 + chunk_count * (per_chunk_statement_count + 1),
        )
