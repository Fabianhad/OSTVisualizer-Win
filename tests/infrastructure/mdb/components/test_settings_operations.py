from tests.helpers.mdb.operations import (
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
import logging
import pyodbc
from tests.helpers.mdb.real_write_contract import RealContractOps, contract_db
from ost_visualizer.infrastructure.mdb.components.serialization import encode_text_blob
import unittest
import sqlite3
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
from ost_visualizer.domain.entities.area import BidArea, BidAreaChangeset
from types import MappingProxyType, SimpleNamespace
from ost_visualizer.infrastructure.mdb.components.constants import (
    PAGE_DELETE_CHILD_TABLES,
    TAKEOFF_REFERENCE_TABLES,
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
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 2)")
        operations = _SqliteMdbOps(conn)
        with self.assertNoLogs("test", level="ERROR"):
            self.assertFalse(operations.save_bid_selected_page("bid.mdb", "2", "10"))
        self.assertIsNone(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0]
        )
        # Control: a page owned by the requested bid is accepted.
        self.assertTrue(operations.save_bid_selected_page("bid.mdb", "2", "11"))
        self.assertEqual(
            conn.execute(
                "SELECT BidPageSelectedUID FROM BidSettings WHERE UID = 20"
            ).fetchone()[0],
            11,
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
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertFalse(
                _SqliteMdbOps(conn).save_bid_selected_page("bid.mdb", "1", "11")
            )
        self.assertIn("BidSettings has multiple rows for Bids.UID=1", logs.output[0])
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

    def test_save_bid_selected_page_updates_and_clears_only_requested_bid_row(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidSettings ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageSelectedUID INTEGER)"
        )
        conn.executemany("INSERT INTO Bids (UID) VALUES (?)", ((1,), (2,)))
        conn.executemany(
            "INSERT INTO BidPages (UID, BidUID) VALUES (?, ?)",
            ((10, 1), (11, 1), (20, 2)),
        )
        conn.executemany(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) VALUES (?, ?, ?)",
            ((30, 1, 10), (31, 2, 20)),
        )
        operations = _SqliteMdbOps(conn)
        self.assertTrue(operations.save_bid_selected_page("bid.mdb", "1", "11"))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageSelectedUID FROM BidSettings ORDER BY UID"
            ).fetchall(),
            [(30, 1, 11), (31, 2, 20)],
        )
        self.assertTrue(operations.save_bid_selected_page("bid.mdb", "1", ""))
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, BidPageSelectedUID FROM BidSettings ORDER BY UID"
            ).fetchall(),
            [(30, 1, None), (31, 2, 20)],
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
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 1)")
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (2, 1, 10)"
        )
        conn.execute(
            "INSERT INTO BidSettings (UID, BidUID, BidPageSelectedUID) "
            "VALUES (3, 1, 11)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(conn.execute("SELECT UID FROM BidPages").fetchall(), [(11,)])
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageSelectedUID FROM BidSettings ORDER BY UID"
            ).fetchall(),
            [(2, None), (3, 11)],
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
        conn.executemany(
            "INSERT INTO BidPages (UID, BidUID) VALUES (?, 1)", ((10,), (11,))
        )
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
        conn.execute(
            "INSERT INTO Bids "
            "(UID, CoverSheetSelItemType, CoverSheetSelItemUID) "
            "VALUES (3, 1, 11)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        rows = conn.execute(
            "SELECT UID, CoverSheetSelItemType, CoverSheetSelItemUID "
            "FROM Bids ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(1, 1, None), (2, 2, 10), (3, 1, 11)])

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
        conn.executemany(
            "INSERT INTO BidPages (UID, BidUID) VALUES (?, 1)", ((10,), (11,))
        )
        conn.executemany(
            "INSERT INTO BidAnnotationRects (UID, BidPageUID, BidLayerUID) "
            "VALUES (?, ?, 30)",
            ((20, 10), (21, 11)),
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(
            conn.execute("SELECT UID, BidPageUID FROM BidAnnotationRects").fetchall(),
            [(21, 11)],
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidPages").fetchall(), [(11,)])

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
        conn.execute("INSERT INTO BidPages (UID, BidUID) VALUES (11, 1)")
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
            conn.executemany(
                f"INSERT INTO {table} (UID, BidPageUID) VALUES (?, ?)",
                ((100 + len(table), 10), (200 + len(table), 11)),
            )
        conn.execute("INSERT INTO BidTypGroupViews (UID, BidPageUID) VALUES (20, 10)")
        conn.execute("INSERT INTO BidTypGroupViews (UID, BidPageUID) VALUES (21, 11)")
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (30, 20)"
        )
        conn.execute(
            "INSERT INTO AffectDPCTypGroupViews "
            "(UID, BidTypGroupViewUID) VALUES (31, 21)"
        )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        self.assertEqual(
            conn.execute("SELECT UID FROM AffectDPCTypGroupViews").fetchall(),
            [(31,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID, BidPageUID FROM BidTypGroupViews").fetchall(),
            [(21, 11)],
        )
        for table in (
            "BidPercents",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "Boost",
            "DPCCalcFilter",
        ):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT BidPageUID FROM {table}").fetchall(),
                    [(11,)],
                )
        self.assertEqual(conn.execute("SELECT UID FROM BidPages").fetchall(), [(11,)])

    def test_page_delete_removes_only_target_page_rows_from_every_child_table(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER PRIMARY KEY, BidUID INTEGER)")
        conn.executemany("INSERT INTO BidPages VALUES (?, 1)", ((10,), (11,)))
        child_tables = (*PAGE_DELETE_CHILD_TABLES, "BidTakeoffs")
        for table in child_tables:
            conn.execute(f"CREATE TABLE [{table}] (UID INTEGER, BidPageUID INTEGER)")
            conn.executemany(f"INSERT INTO [{table}] VALUES (?, ?)", ((1, 10), (2, 11)))
        conn.execute("CREATE TABLE BidNamedViews (UID INTEGER, BidPageUID INTEGER)")
        conn.executemany("INSERT INTO BidNamedViews VALUES (?, ?)", ((1, 10), (2, 11)))
        conn.execute(
            "CREATE TABLE BidHotLinks ("
            "UID INTEGER, BidPageUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidHotLinks VALUES (?, ?, ?)",
            ((1, 10, 2), (2, 11, 1), (3, 11, 2), (4, 11, None)),
        )
        with self.assertNoLogs("test", level="WARNING"):
            self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["10"]))
        for table in child_tables:
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT UID, BidPageUID FROM [{table}]").fetchall(),
                    [(2, 11)],
                )
        self.assertEqual(
            conn.execute("SELECT UID, BidPageUID FROM BidNamedViews").fetchall(),
            [(2, 11)],
        )
        # Hot links on a surviving page are removed when they target a Named View
        # of the deleted page; links to surviving or absent views remain.
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageUID, BidPageViewUID FROM BidHotLinks ORDER BY UID"
            ).fetchall(),
            [(3, 11, 2), (4, 11, None)],
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidPages").fetchall(), [(11,)])

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

    def test_page_delete_removes_annotations_linked_by_either_takeoff_endpoint(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidTakeoffs ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidPages VALUES (?, 1)", ((7,), (8,)))
        conn.executemany(
            "INSERT INTO BidTakeoffs VALUES (?, 1, ?)", ((70, 7), (80, 8), (81, 8))
        )
        for index, table in enumerate(TAKEOFF_REFERENCE_TABLES, start=1):
            conn.execute(
                f"CREATE TABLE [{table}] ("
                "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
                "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER)"
            )
            conn.executemany(
                f"INSERT INTO [{table}] VALUES (?, 1, 8, ?, ?)",
                (
                    (index * 10 + 1, 80, 70),
                    (index * 10 + 2, 70, 80),
                    (index * 10 + 3, 80, 81),
                ),
            )
        self.assertTrue(_SqliteMdbOps(conn).delete_pages("bid.mdb", ["7"]))
        for index, table in enumerate(TAKEOFF_REFERENCE_TABLES, start=1):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidTakeoffFromUID, BidTakeoffToUID "
                        f"FROM [{table}]"
                    ).fetchall(),
                    [(index * 10 + 3, 80, 81)],
                )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidTakeoffs ORDER BY UID").fetchall(),
            [(80,), (81,)],
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
        # 100 pages span two 50-UID chunks. Schema probes do not scale with rows.
        row_selects = [sql for sql in selects if "sqlite_master" not in sql]
        self.assertEqual(len(row_selects), 3)
        self.assertEqual(len(updates), 2)
        self.assertEqual(len(deletes), 2)


class SettingsOperationsSaveCoverSheetTests(_SettingsOperationsPersistenceFixture):
    """SettingsOperationsMixin: lifecycle and combined contracts."""

    def test_measurement_system_save_normalizes_uoms_by_quantity_dimension(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE Bids ("
            "UID INTEGER PRIMARY KEY, JobName TEXT, MeasureBase INTEGER)"
        )
        conn.executemany("INSERT INTO Bids VALUES (?, 'Bid', 0)", ((1,), (2,)))
        conn.execute(
            "CREATE TABLE BidConditions ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT, "
            "Quantity1 INTEGER, UOM1 INTEGER)"
        )
        elevation_name = "Wall @B 8' 0\""
        conn.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, ?, ?)",
            (
                (10, 1, "Count", CALC_COUNT, UOM_LINEAR_FEET),
                (11, 1, "Length", CALC_LINEAR_LENGTH, UOM_LINEAR_FEET),
                (12, 1, elevation_name, CALC_LINEAR_LENGTH, UOM_LINEAR_FEET),
                (20, 2, elevation_name, CALC_LINEAR_LENGTH, UOM_LINEAR_FEET),
            ),
        )
        operations = _SqliteDuplicateOps(conn)
        metric_rows = [
            (10, "Count", UOM_EACH),
            (11, "Length", UOM_M),
            (12, "Wall @B 243.84 cm", UOM_M),
            (20, elevation_name, UOM_LINEAR_FEET),
        ]
        for _attempt in range(2):
            self.assertTrue(
                operations.save_cover_sheet(
                    "bid.mdb", "1", {"job_name": "Bid", "measure_base": 1}
                )
            )
            self.assertEqual(
                conn.execute(
                    "SELECT UID, Name, UOM1 FROM BidConditions ORDER BY UID"
                ).fetchall(),
                metric_rows,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT UID, MeasureBase FROM Bids ORDER BY UID"
                ).fetchall(),
                [(1, 1), (2, 0)],
            )
        self.assertTrue(
            operations.save_cover_sheet(
                "bid.mdb", "1", {"job_name": "Bid", "measure_base": 0}
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, UOM1 FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [
                (10, "Count", UOM_EACH),
                (11, "Length", UOM_LINEAR_FEET),
                (12, elevation_name, UOM_LINEAR_FEET),
                (20, elevation_name, UOM_LINEAR_FEET),
            ],
        )
        self.assertEqual(
            conn.execute("SELECT UID, MeasureBase FROM Bids ORDER BY UID").fetchall(),
            [(1, 0), (2, 0)],
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn(
            "This OST database does not support page-folder persistence", logs.output[0]
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn(
            "This OST database does not support page-folder hierarchy persistence",
            logs.output[0],
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
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Name FROM BidPages WHERE UID=9"
            ).fetchall(),
            [(9, 1, "New")],
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn(
            "BidPageFolders.UID=7 participates in a ParentUID cycle", logs.output[0]
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn("participates in a ParentUID cycle", logs.output[0])
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
                with self.assertLogs("test", level="ERROR") as logs:
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
                self.assertIn(
                    "BidPageFolders.UID=99 does not belong to Bids.UID=1",
                    logs.output[0],
                )
                self.assertEqual(
                    conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
                    "Original",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, ParentUID FROM BidPageFolders WHERE UID=7"
                    ).fetchall(),
                    [(7, None)],
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
        self.assertEqual(
            conn.execute("SELECT JobName FROM Bids WHERE UID=1").fetchone()[0],
            "Changed",
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn(
            "BidPageFolders.UID=7 does not belong to Bids.UID=1", logs.output[0]
        )
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn("BidPages.UID=20 does not belong to Bids.UID=1", logs.output[0])
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
        # Each 100-row delete spans two 50-UID chunks: Page Master clearing,
        # Page folder detachment and Folder parent clearing are 6 UPDATEs; Page
        # and Folder deletion are 4 DELETEs.
        self.assertEqual(len(updates), 6)
        self.assertEqual(len(deletes), 4)

    def test_cover_sheet_folder_delete_detaches_surviving_pages_and_child_folders(self):
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
            "INSERT INTO BidPageFolders VALUES (?, 1, ?, ?)",
            ((1, None, "Parent"), (2, 1, "Child"), (3, None, "Other")),
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, 1, ?, NULL)",
            ((101, 1), (102, 2), (103, 3)),
        )
        with self.assertNoLogs("test", level="ERROR"):
            self.assertTrue(
                _SqliteDuplicateOps(conn).save_cover_sheet(
                    "bid.mdb", "1", {"measure_base": 0, "deleted_folder_uids": ["1"]}
                )
            )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name FROM BidPageFolders ORDER BY UID"
            ).fetchall(),
            [(2, None, "Child"), (3, None, "Other")],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageFolderUID FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(101, None), (102, 2), (103, 3)],
        )

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
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, Width, Height FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(uid, 1, 42.0, 30.0) for uid in range(1, 101)],
        )

    def test_cover_sheet_new_page_in_new_folder_persists_assigned_identities(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobName TEXT)")
        conn.execute("INSERT INTO Bids VALUES (1, 'Bid')")
        conn.execute(
            "CREATE TABLE BidPageFolders ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, BidPageFolderUID INTEGER, SheetNo TEXT, "
            "Name TEXT, Width REAL, Height REAL, ScaleFactor1 REAL, "
            "ScaleFactor2 REAL, Show INTEGER, GUID TEXT, Index1 INTEGER, "
            "Sequence INTEGER, MultiPageCount INTEGER, ImagePath TEXT)"
        )
        conn.execute("INSERT INTO BidPageFolders VALUES (4, 1, NULL, 'Existing')")
        self.assertTrue(
            _SqliteDuplicateOps(conn).save_cover_sheet(
                "bid.mdb",
                "1",
                {
                    "job_name": "Bid",
                    "measure_base": 0,
                    "new_folders": [
                        {
                            "local_uid": "new_folder",
                            "name": "Level 1",
                            "parent_uid": "4",
                        }
                    ],
                    "pages": [
                        {
                            "uid": None,
                            "folder_uid": "new_folder",
                            "name": "Plan",
                            "sheet_no": "A-1",
                            "width": 42.0,
                            "height": 30.0,
                            "scale_factor1": 0.125,
                            "scale_factor2": 12.0,
                            "show_mode": 0,
                            "image_path": "C:/Plans/A-1.pdf",
                        }
                    ],
                },
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidUID, ParentUID, Name FROM BidPageFolders "
                "ORDER BY UID"
            ).fetchall(),
            [(4, 1, None, "Existing"), (5, 1, 4, "Level 1")],
        )
        page = conn.execute(
            "SELECT UID, BidUID, BidPageFolderUID, SheetNo, Name, Width, Height, "
            "ScaleFactor1, ScaleFactor2, Show, Index1, Sequence, MultiPageCount, "
            "ImagePath FROM BidPages"
        ).fetchall()
        self.assertEqual(
            page,
            [
                (
                    1,
                    1,
                    5,
                    "A-1",
                    "Plan",
                    42.0,
                    30.0,
                    0.125,
                    12.0,
                    0,
                    1,
                    1,
                    0,
                    "C:\\Plans\\A-1.pdf",
                )
            ],
        )
        guid = conn.execute("SELECT GUID FROM BidPages").fetchone()[0]
        self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")

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
        conn.executemany(
            "INSERT INTO BidAreas (UID, BidUID) VALUES (?, 1)", ((10,), (11,))
        )
        delete_tables = (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "BidTimeCards",
            "BidTypAreaCounts",
        )
        for table in delete_tables:
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidAreaUID INTEGER REFERENCES BidAreas(UID))"
            )
            conn.executemany(
                f"INSERT INTO {table} (UID, BidAreaUID) VALUES (?, ?)",
                ((1, 10), (2, 11)),
            )
        for table in ("BidPageSettings", "BidTakeoffs"):
            conn.execute(
                f"CREATE TABLE {table} (UID INTEGER PRIMARY KEY, "
                "BidAreaUID INTEGER REFERENCES BidAreas(UID))"
            )
            conn.executemany(
                f"INSERT INTO {table} (UID, BidAreaUID) VALUES (?, ?)",
                ((1, 10), (2, 11)),
            )
        conn.executemany(
            "INSERT INTO BidAreaTranslations "
            "(UID, MasterAreaUID, TranslateAreaUID) VALUES (?, ?, ?)",
            ((20, 10, 10), (21, 10, 11), (22, 11, 10), (23, 11, 11)),
        )
        with self.assertNoLogs("test", level="ERROR"):
            result = _SqliteMdbOps(conn).save_bid_areas(
                "bid.mdb",
                "1",
                BidAreaChangeset(new=[], updated=[], deleted_uids=["10"]),
            )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, MasterAreaUID, TranslateAreaUID "
                "FROM BidAreaTranslations"
            ).fetchall(),
            [(23, 11, 11)],
        )
        for table in delete_tables:
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(f"SELECT UID, BidAreaUID FROM {table}").fetchall(),
                    [(2, 11)],
                )
        for table in ("BidPageSettings", "BidTakeoffs"):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidAreaUID FROM {table} ORDER BY UID"
                    ).fetchall(),
                    [(1, None), (2, 11)],
                )
        self.assertEqual(conn.execute("SELECT UID FROM BidAreas").fetchall(), [(11,)])

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
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(
                    new=[],
                    updated=[BidArea("7", "1", "8", "Changed", 0)],
                    deleted_uids=[],
                ),
            )
        self.assertIn(
            "BidAreas.UID=7 participates in a ParentUID cycle", logs.output[0]
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
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(
                    new=[],
                    updated=[BidArea("7", "1", "8", "Changed", 0)],
                    deleted_uids=[],
                ),
            )
        self.assertIn(
            "BidAreas.UID=7 references missing BidAreas.UID=8 through ParentUID",
            logs.output[0],
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
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "malformed.mdb",
                "1",
                BidAreaChangeset(new=[], updated=[], deleted_uids=["7"]),
            )
        self.assertIn(
            "BidAreas.UID=8 references missing BidAreas.UID=7 through ParentUID",
            logs.output[0],
        )
        self.assertEqual(result, {})
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidAreas").fetchone()[0], 2)

    def test_area_save_allows_deleting_parent_when_children_are_reparented_or_deleted(
        self,
    ):
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
            ((7, None, "Parent"), (8, 7, "Kept child"), (9, 7, "Deleted child")),
        )
        with self.assertNoLogs("test", level="ERROR"):
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "bid.mdb",
                "1",
                BidAreaChangeset(
                    new=[],
                    updated=[BidArea("8", "1", "", "Kept child", 0)],
                    deleted_uids=["7", "9"],
                ),
            )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT UID, ParentUID, Name FROM BidAreas").fetchall(),
            [(8, None, "Kept child")],
        )

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
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteDuplicateOps(conn).save_bid_areas(
                "legacy.mdb",
                "1",
                BidAreaChangeset(
                    new=[],
                    updated=[BidArea("8", "1", "7", "Changed", 0)],
                    deleted_uids=[],
                ),
            )
        self.assertIn(
            "This OST database does not support Bid Area hierarchy persistence",
            logs.output[0],
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn(
            "New BidAreas correlation UID new_same must be present and unique",
            logs.output[0],
        )
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn("BidAreas contains duplicate pending identity 7", logs.output[0])
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
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(DISTINCT UID), COUNT(*) FROM BidAreas"
            ).fetchone(),
            (100, 100),
        )
        self.assertEqual(
            sorted(int(uid) for uid in uid_map.values()), list(range(1, 101))
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
        with self.assertLogs("test", level="ERROR") as logs:
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
        self.assertIn("forced second area insert failure", logs.output[0])

    def test_bid_area_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAreas ("
            "UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
            "Sequence INTEGER, GUID TEXT)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
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
        self.assertEqual([sql for sql in statements if "MAX(" in sql.upper()], [])


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
        with self.assertLogs("test", level="WARNING") as logs:
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1"]}
            )
        self.assertIsNone(result)
        self.assertIn("Refusing to delete condition types in use", logs.output[0])
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

    def test_save_condition_types_inserts_new_and_renames_updated_types(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER PRIMARY KEY, Name TEXT)")
        conn.execute("CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)")
        conn.executemany(
            "INSERT INTO CdnTypes (UID, Name) VALUES (?, ?)",
            ((1, "Old"), (2, "Untouched")),
        )
        result = _SqliteDuplicateOps(conn).save_condition_types(
            "bid.mdb",
            {
                "new": [{"uid": "new_0", "name": "Fresh"}],
                "updated": [{"uid": "1", "name": "Renamed"}],
                "deleted_uids": [],
            },
        )
        self.assertEqual(result, {"new_0": "3"})
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM CdnTypes ORDER BY UID").fetchall(),
            [(1, "Renamed"), (2, "Untouched"), (3, "Fresh")],
        )

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
        with self.assertLogs("test", level="WARNING") as logs:
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"deleted_uids": ["1", "2"]}
            )
        self.assertIsNone(result)
        self.assertIn("Refusing to delete condition types in use", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT UID FROM CdnTypes ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_save_condition_types_reports_schema_failure(self):
        conn = sqlite3.connect(":memory:")
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteMdbOps(conn).save_condition_types(
                "bid.mdb", {"new": [{"uid": "new_0", "name": "Concrete"}]}
            )
        self.assertIsNone(result)
        self.assertIn(
            "This OST database does not support condition types", logs.output[0]
        )

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
        with self.assertLogs("test", level="WARNING") as logs:
            result = _SqliteDuplicateOps(conn).save_condition_types(
                "large.mdb",
                {"deleted_uids": [str(uid) for uid in range(1, row_count + 1)]},
            )
        self.assertIsNone(result)
        self.assertIn("Refusing to delete condition types in use", logs.output[0])
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
        self.assertEqual(
            conn.execute("SELECT PayClassUID FROM Employees WHERE UID=8").fetchone()[0],
            None,
        )
        self.assertEqual(
            conn.execute(
                "SELECT EmployeeNo, FirstName FROM Employees WHERE UID=7"
            ).fetchone(),
            ("E1", "Ava"),
        )

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
        # Control: the same batch with a resolvable Pay Class is applied.
        result = _SqliteDuplicateOps(conn).save_employees(
            "malformed.mdb",
            {
                "updated": [employee("7", "E1", "Changed", "1")],
                "new": [employee("new_0", "E2", "New", "1")],
            },
        )
        self.assertEqual(result, {"new_0": "8"})
        self.assertEqual(
            conn.execute(
                "SELECT UID, EmployeeNo, FirstName, PayClassUID "
                "FROM Employees ORDER BY UID"
            ).fetchall(),
            [(7, "E1", "Changed", 1), (8, "E2", "New", 1)],
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
        conn.executemany("INSERT INTO Employees VALUES (?)", ((7,), (8,)))
        conn.executemany(
            "INSERT INTO Bids VALUES (?, ?, ?, ?)",
            ((1, 7, 7, 7), (2, 8, 7, 8), (3, 8, 8, 8)),
        )
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, EstimatorUID, PrManagerUID, JobSiteManagerUID "
                "FROM Bids ORDER BY UID"
            ).fetchall(),
            [(1, None, None, None), (2, 8, None, 8), (3, 8, 8, 8)],
        )
        self.assertEqual(conn.execute("SELECT UID FROM Employees").fetchall(), [(8,)])

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
        conn.executemany("INSERT INTO Employees VALUES (?)", ((7,), (8,)))
        conn.executemany("INSERT INTO BidEmployees VALUES (?, ?)", ((70, 7), (71, 8)))
        conn.executemany(
            "INSERT INTO BidDPCSubscribers VALUES (?, ?)", ((700, 7), (703, 8))
        )
        conn.executemany(
            "INSERT INTO BidTimeCards VALUES (?, ?)", ((701, 70), (704, 71))
        )
        conn.executemany(
            "INSERT INTO ConditionSets VALUES (?, ?)", ((702, 7), (705, 8))
        )
        result = _SqliteMdbOps(conn).save_employees(
            "bid.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidEmployeeUID FROM BidDPCSubscribers"
            ).fetchall(),
            [(703, 8)],
        )
        self.assertEqual(
            conn.execute("SELECT UID, EmployeeUID FROM BidEmployees").fetchall(),
            [(71, 8)],
        )
        self.assertEqual(
            conn.execute("SELECT UID, BidEmployeeUID FROM BidTimeCards").fetchall(),
            [(704, 71)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, EmployeeUID FROM ConditionSets ORDER BY UID"
            ).fetchall(),
            [(702, None), (705, 8)],
        )
        self.assertEqual(conn.execute("SELECT UID FROM Employees").fetchall(), [(8,)])

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
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIsNone(save(_SqliteDuplicateOps(conn)))
                self.assertIn(
                    f"New {table} correlation UID new_same must be present and unique",
                    logs.output[0],
                )
                self.assertEqual(
                    conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0],
                    0,
                )

    def test_master_data_updates_write_changed_fields_only_to_requested_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE JobStatuses ("
            "UID INTEGER, Name TEXT, Locked INTEGER, Sequence INTEGER)"
        )
        conn.executemany(
            "INSERT INTO JobStatuses VALUES (?, ?, ?, ?)",
            ((1, "Open", 0, 1), (2, "Closed", 0, 2)),
        )
        conn.execute("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO PayClasses VALUES (?, ?)",
            ((3, "Journeyman"), (4, "Apprentice")),
        )
        conn.execute(
            "CREATE TABLE Employees ("
            "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, "
            "Address1 TEXT, Address2 TEXT, City TEXT, State TEXT, Zip TEXT, "
            "HomePhone TEXT, MobilePhone TEXT, EMail TEXT, PayClassUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO Employees (UID, EmployeeNo, FirstName, PayClassUID) "
            "VALUES (?, ?, ?, ?)",
            ((7, "E7", "Ada", None), (8, "E8", "Bob", 4)),
        )
        conn.execute("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        conn.executemany(
            "INSERT INTO CdnTypes VALUES (?, ?)", ((1, "Slab"), (2, "Wall"))
        )
        operations = _SqliteDuplicateOps(conn)
        self.assertEqual(
            operations.save_job_statuses(
                "bid.mdb",
                {
                    "updated": [
                        {"uid": "1", "name": "Active", "locked": True, "sequence": 5}
                    ]
                },
            ),
            {},
        )
        self.assertEqual(
            operations.save_pay_classes(
                "bid.mdb", {"updated": [{"uid": "4", "name": "Foreman"}]}
            ),
            {},
        )
        self.assertEqual(
            operations.save_condition_types(
                "bid.mdb", {"updated": [{"uid": "2", "name": "Footing"}]}
            ),
            {},
        )
        employee = SimpleNamespace(
            uid="7",
            employee_no="E7-NEW",
            first_name="Ada",
            last_name="Lovelace",
            address1="1 Main",
            address2="Suite 2",
            city="Raleigh",
            state="NC",
            zip="27601",
            home_phone="111",
            mobile_phone="222",
            email="ada@example.com",
            pay_class_uid="3",
        )
        self.assertEqual(
            operations.save_employees("bid.mdb", {"updated": [employee]}), {}
        )
        self.assertEqual(
            conn.execute("SELECT * FROM JobStatuses ORDER BY UID").fetchall(),
            [(1, "Active", -1, 5), (2, "Closed", 0, 2)],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM PayClasses ORDER BY UID").fetchall(),
            [(3, "Journeyman"), (4, "Foreman")],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM CdnTypes ORDER BY UID").fetchall(),
            [(1, "Slab"), (2, "Footing")],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM Employees ORDER BY UID").fetchall(),
            [
                (
                    7,
                    "E7-NEW",
                    "Ada",
                    "Lovelace",
                    "1 Main",
                    "Suite 2",
                    "Raleigh",
                    "NC",
                    "27601",
                    "111",
                    "222",
                    "ada@example.com",
                    3,
                ),
                (
                    8,
                    "E8",
                    "Bob",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    4,
                ),
            ],
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

    def test_bid_status_update_sets_and_clears_only_the_requested_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?, ?)", ((7, None), (8, 5)))
        conn.execute("CREATE TABLE JobStatuses (UID INTEGER)")
        conn.executemany("INSERT INTO JobStatuses VALUES (?)", ((5,), (9,)))
        operations = _SqliteDuplicateOps(conn)
        self.assertTrue(operations.update_bid_job_status("bid.mdb", "7", "9"))
        self.assertEqual(
            conn.execute("SELECT UID, JobStatusUID FROM Bids ORDER BY UID").fetchall(),
            [(7, 9), (8, 5)],
        )
        self.assertTrue(operations.update_bid_job_status("bid.mdb", "7", None))
        self.assertEqual(
            conn.execute("SELECT UID, JobStatusUID FROM Bids ORDER BY UID").fetchall(),
            [(7, None), (8, 5)],
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
        conn.executemany("INSERT INTO PayClasses VALUES (?)", ((7,), (8,)))
        conn.executemany("INSERT INTO Employees VALUES (?, ?)", ((70, 7), (71, 8)))
        conn.executemany("INSERT INTO BidEmployees VALUES (?, ?)", ((700, 7), (701, 8)))
        result = _SqliteMdbOps(conn).save_pay_classes(
            "test.mdb", {"new": [], "updated": [], "deleted_uids": ["7"]}
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute(
                "SELECT UID, PayClassUID FROM Employees ORDER BY UID"
            ).fetchall(),
            [(70, None), (71, 8)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, PayClassUID FROM BidEmployees ORDER BY UID"
            ).fetchall(),
            [(700, None), (701, 8)],
        )
        self.assertEqual(conn.execute("SELECT UID FROM PayClasses").fetchall(), [(8,)])


class SettingsOperationsGuardTests(unittest.TestCase):
    class StrictOps(_SqliteDuplicateOps):
        logger = logging.getLogger("settings-ops-guard")

        def _require_write_columns(self, schema, table, columns):
            for column in columns:
                schema.require_column(table, column)

    def ops(self, script):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript(script)
        return self.StrictOps(connection), connection

    def logged_failure(self, call, expected_result):
        with self.assertLogs("settings-ops-guard", level="ERROR") as logs:
            self.assertEqual(call(), expected_result)
        self.assertEqual(len(logs.records), 1)
        return str(logs.records[0].exc_info[1])

    def test_master_data_saves_need_a_uid_column_in_their_table(self):
        cases = (
            ("JobStatuses", lambda ops: ops.save_job_statuses("x.mdb", {})),
            ("Employees", lambda ops: ops.save_employees("x.mdb", {})),
            ("PayClasses", lambda ops: ops.save_pay_classes("x.mdb", {})),
            ("CdnTypes", lambda ops: ops.save_condition_types("x.mdb", {})),
        )
        for table, call in cases:
            with self.subTest(table=table):
                ops, _connection = self.ops(f"CREATE TABLE {table} (Name TEXT);")
                message = self.logged_failure(lambda: call(ops), None)
                self.assertRegex(message, f"Missing {table}.UID")

    def test_master_data_rows_with_a_duplicated_uid_are_never_deleted(self):
        cases = (
            (
                "JobStatuses",
                "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER);"
                "INSERT INTO Bids VALUES (1, 5);",
                "SELECT JobStatusUID FROM Bids",
                [(5,)],
                lambda ops: ops.save_job_statuses("x.mdb", {"deleted_uids": ["5"]}),
            ),
            (
                "PayClasses",
                "CREATE TABLE Employees (UID INTEGER, PayClassUID INTEGER);"
                "INSERT INTO Employees VALUES (1, 5);",
                "SELECT PayClassUID FROM Employees",
                [(5,)],
                lambda ops: ops.save_pay_classes("x.mdb", {"deleted_uids": ["5"]}),
            ),
            (
                "CdnTypes",
                "",
                "SELECT 1",
                [(1,)],
                lambda ops: ops.save_condition_types("x.mdb", {"deleted_uids": ["5"]}),
            ),
        )
        for table, extra, probe, probe_rows, call in cases:
            with self.subTest(table=table):
                ops, connection = self.ops(
                    f"CREATE TABLE {table} (UID INTEGER, Name TEXT);"
                    f"INSERT INTO {table} VALUES (5, 'a'), (5, 'b'), (6, 'c');" + extra
                )
                message = self.logged_failure(lambda: call(ops), None)
                self.assertRegex(message, "duplicate")
                self.assertEqual(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone(), (3,)
                )
                self.assertEqual(connection.execute(probe).fetchall(), probe_rows)

    def test_master_data_rows_with_a_duplicated_uid_are_never_renamed(self):
        cases = (
            (
                "JobStatuses",
                lambda ops: ops.save_job_statuses(
                    "x.mdb", {"updated": [{"uid": "5", "name": "renamed"}]}
                ),
            ),
            (
                "PayClasses",
                lambda ops: ops.save_pay_classes(
                    "x.mdb", {"updated": [{"uid": "5", "name": "renamed"}]}
                ),
            ),
            (
                "CdnTypes",
                lambda ops: ops.save_condition_types(
                    "x.mdb", {"updated": [{"uid": "5", "name": "renamed"}]}
                ),
            ),
        )
        for table, call in cases:
            with self.subTest(table=table):
                ops, connection = self.ops(
                    f"CREATE TABLE {table} (UID INTEGER, Name TEXT, Locked INTEGER, Sequence INTEGER);"
                    f"INSERT INTO {table} VALUES (5, 'a', 0, 0), (5, 'b', 0, 0);"
                )
                call(ops)
                self.assertEqual(
                    connection.execute(
                        f"SELECT Name FROM {table} ORDER BY Name"
                    ).fetchall(),
                    [("a",), ("b",)],
                )

    def test_a_bid_status_change_needs_an_existing_unambiguous_status(self):
        script = (
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER);"
            "INSERT INTO Bids VALUES (1, 2);"
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT);"
            "INSERT INTO JobStatuses VALUES (2, 'Open'), (7, 'Won'), (7, 'Dup');"
        )
        ops, connection = self.ops(script)
        self.assertTrue(ops.update_bid_job_status("x.mdb", "1", "2"))
        self.assertTrue(ops.update_bid_job_status("x.mdb", "1", None))
        self.assertEqual(
            connection.execute("SELECT JobStatusUID FROM Bids").fetchall(), [(None,)]
        )
        message = self.logged_failure(
            lambda: ops.update_bid_job_status("x.mdb", "1", "7"), False
        )
        self.assertRegex(message, "duplicate")
        message = self.logged_failure(
            lambda: ops.update_bid_job_status("x.mdb", "1", "99"), False
        )
        self.assertRegex(message, "99")
        self.assertEqual(
            connection.execute("SELECT JobStatusUID FROM Bids").fetchall(), [(None,)]
        )

    def test_selecting_a_page_needs_the_selection_and_page_columns(self):
        ops, connection = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidSettings (BidUID INTEGER);"
            "INSERT INTO BidSettings VALUES (1);"
        )
        message = self.logged_failure(
            lambda: ops.save_bid_selected_page("x.mdb", "1", "5"), False
        )
        self.assertRegex(message, "Missing BidSettings.BidPageSelectedUID")
        ops, connection = self.ops(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidSettings (BidUID INTEGER, BidPageSelectedUID INTEGER);"
            "INSERT INTO BidSettings VALUES (1, NULL);"
            "CREATE TABLE BidPages (UID INTEGER);"
            "INSERT INTO BidPages VALUES (5);"
        )
        message = self.logged_failure(
            lambda: ops.save_bid_selected_page("x.mdb", "1", "5"), False
        )
        self.assertRegex(message, "Missing BidPages.BidUID")
        self.assertEqual(
            connection.execute("SELECT BidPageSelectedUID FROM BidSettings").fetchall(),
            [(None,)],
        )

    def test_the_cover_sheet_needs_a_bid_uid_column_and_a_folder_uid_column_to_delete_folders(
        self,
    ):
        ops, _connection = self.ops("CREATE TABLE Bids (JobName TEXT);")
        message = self.logged_failure(
            lambda: ops.save_cover_sheet("x.mdb", "1", {"job_name": "x"}), False
        )
        self.assertRegex(message, "Missing Bids.UID")
        ops, connection = self.ops(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT); INSERT INTO Bids VALUES (1, 'x');"
            "CREATE TABLE BidPageFolders (BidUID INTEGER, Name TEXT, ParentUID INTEGER);"
            "INSERT INTO BidPageFolders VALUES (1, 'f', NULL);"
        )
        self.logged_failure(
            lambda: ops.save_cover_sheet(
                "x.mdb", "1", {"job_name": "x", "deleted_folder_uids": ["5"]}
            ),
            False,
        )
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidPageFolders").fetchone(), (1,)
        )

    def test_deleting_pages_needs_a_page_uid_column(self):
        ops, connection = self.ops(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT); INSERT INTO Bids VALUES (1, 'x');"
            "CREATE TABLE BidPages (BidUID INTEGER, Name TEXT);"
            "INSERT INTO BidPages VALUES (1, 'p');"
        )
        self.logged_failure(lambda: ops.delete_pages("x.mdb", ["5"]), False)
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidPages").fetchone(), (1,)
        )

    def test_every_unit_of_measure_column_is_normalised_on_its_own(self):
        ops, connection = self.ops(
            "CREATE TABLE Bids (UID INTEGER PRIMARY KEY, JobName TEXT, MeasureBase INTEGER);"
            "INSERT INTO Bids VALUES (1, 'Bid', 0);"
            "CREATE TABLE BidConditions (UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT,"
            " Quantity1 INTEGER, Quantity2 INTEGER, Quantity3 INTEGER,"
            " UOM1 INTEGER, UOM2 INTEGER, UOM3 INTEGER);"
        )
        rows = (
            (
                10,
                1,
                "Only second",
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_LENGTH,
                CALC_COUNT,
                UOM_M,
                UOM_LINEAR_FEET,
                UOM_EACH,
            ),
            (
                11,
                1,
                "Only third",
                CALC_LINEAR_LENGTH,
                CALC_COUNT,
                CALC_LINEAR_LENGTH,
                UOM_M,
                UOM_EACH,
                UOM_LINEAR_FEET,
            ),
            (
                12,
                1,
                "All three",
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_LENGTH,
                UOM_LINEAR_FEET,
                UOM_LINEAR_FEET,
                UOM_LINEAR_FEET,
            ),
            (
                13,
                1,
                None,
                CALC_COUNT,
                CALC_COUNT,
                CALC_COUNT,
                UOM_EACH,
                UOM_EACH,
                UOM_EACH,
            ),
            (
                14,
                1,
                "",
                CALC_LINEAR_LENGTH,
                CALC_COUNT,
                CALC_COUNT,
                UOM_LINEAR_FEET,
                UOM_EACH,
                UOM_EACH,
            ),
        )
        connection.executemany(
            "INSERT INTO BidConditions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
        self.assertTrue(
            ops.save_cover_sheet("x.mdb", "1", {"job_name": "Bid", "measure_base": 1})
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, Name, UOM1, UOM2, UOM3 FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [
                (10, "Only second", UOM_M, UOM_M, UOM_EACH),
                (11, "Only third", UOM_M, UOM_EACH, UOM_M),
                (12, "All three", UOM_M, UOM_M, UOM_M),
                (13, None, UOM_EACH, UOM_EACH, UOM_EACH),
                (14, "", UOM_M, UOM_EACH, UOM_EACH),
            ],
        )


class SettingsOperationsSparseSchemaTests(unittest.TestCase):
    """Dependent tables that exist without the referencing column are left alone."""

    def database(self, script, bare_tables=()):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript(script)
        for table in bare_tables:
            connection.execute(f"CREATE TABLE IF NOT EXISTS [{table}] (UID INTEGER)")
            connection.execute(f"INSERT INTO [{table}] VALUES (1)")
        return connection

    def assert_bare_tables_untouched(self, connection, tables):
        for table in tables:
            with self.subTest(table=table):
                self.assertEqual(
                    connection.execute(f"SELECT UID FROM [{table}]").fetchall(), [(1,)]
                )

    def test_deleting_pages_skips_dependents_that_lack_the_referencing_columns(self):
        from ost_visualizer.infrastructure.mdb.components.constants import (
            PAGE_DELETE_CHILD_TABLES,
            TAKEOFF_REFERENCE_TABLES,
        )

        bare = sorted(
            {
                *PAGE_DELETE_CHILD_TABLES,
                *TAKEOFF_REFERENCE_TABLES,
                "BidComments",
                "BidTakeoffs",
                "BidPercents",
                "AffectDPCTypGroupViews",
                "BidTypGroupViews",
                "BidHotLinks",
                "BidNamedViews",
                "BidSettings",
            }
        )
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (11, 1), (21, 1);",
            bare,
        )
        self.assertTrue(_SqliteDuplicateOps(connection).delete_pages("x.mdb", ["11"]))
        self.assertEqual(
            connection.execute("SELECT UID FROM BidPages").fetchall(), [(21,)]
        )
        self.assert_bare_tables_untouched(connection, bare)

    def test_deleting_pages_removes_the_percentages_of_the_pages_takeoffs_only(self):
        connection = self.database(
            """
            CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);
            CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);
            INSERT INTO BidPages VALUES (11, 1), (21, 1);
            CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER);
            INSERT INTO BidTakeoffs VALUES (101, 1, 11), (201, 1, 21);
            CREATE TABLE BidPercents (UID INTEGER, BidTakeoffUID INTEGER);
            INSERT INTO BidPercents VALUES (1, 101), (2, 201);
            """
        )
        self.assertTrue(_SqliteDuplicateOps(connection).delete_pages("x.mdb", ["11"]))
        self.assertEqual(
            connection.execute("SELECT UID FROM BidPercents").fetchall(), [(2,)]
        )
        self.assertEqual(
            connection.execute("SELECT UID FROM BidTakeoffs").fetchall(), [(201,)]
        )

    def test_deleting_areas_skips_dependents_that_lack_the_area_column(self):
        from ost_visualizer.domain.entities.area import BidAreaChangeset

        bare = [
            "BidPageSettings",
            "BidTakeoffs",
            "BidTimeCards",
            "BidTypAreaCounts",
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "BidAreaTranslations",
        ]
        connection = self.database(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);"
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER,"
            " Name TEXT, Sequence INTEGER);"
            "INSERT INTO BidAreas VALUES (5, 1, NULL, 'a', 1), (6, 1, NULL, 'b', 2);",
            bare,
        )
        result = _SqliteDuplicateOps(connection).save_bid_areas(
            "x.mdb", "1", BidAreaChangeset(new=[], updated=[], deleted_uids=["5"])
        )
        self.assertEqual(result, {})
        self.assertEqual(
            connection.execute("SELECT UID FROM BidAreas").fetchall(), [(6,)]
        )
        self.assert_bare_tables_untouched(connection, bare)

    def test_deleting_master_data_skips_dependents_that_lack_the_reference_column(self):
        cases = (
            (
                "JobStatuses",
                ["Bids"],
                lambda ops: ops.save_job_statuses("x.mdb", {"deleted_uids": ["5"]}),
            ),
            (
                "PayClasses",
                ["Employees", "BidEmployees"],
                lambda ops: ops.save_pay_classes("x.mdb", {"deleted_uids": ["5"]}),
            ),
            (
                "Employees",
                [
                    "Bids",
                    "BidDPCSubscribers",
                    "BidTimeCards",
                    "BidEmployees",
                    "ConditionSets",
                ],
                lambda ops: ops.save_employees("x.mdb", {"deleted_uids": ["5"]}),
            ),
            (
                "CdnTypes",
                ["BidConditions"],
                lambda ops: ops.save_condition_types("x.mdb", {"deleted_uids": ["5"]}),
            ),
        )
        for table, bare, call in cases:
            with self.subTest(table=table):
                connection = self.database(
                    f"CREATE TABLE [{table}] (UID INTEGER, Name TEXT);"
                    f"INSERT INTO [{table}] VALUES (5, 'a'), (6, 'b');",
                    [name for name in bare if name != table],
                )
                result = call(_SqliteDuplicateOps(connection))
                self.assertIsNotNone(result)
                self.assertEqual(
                    connection.execute(f"SELECT UID FROM [{table}]").fetchall(), [(6,)]
                )
                self.assert_bare_tables_untouched(
                    connection, [name for name in bare if name != table]
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
        self.assertEqual(operations.updates, [])
        self.assertEqual(operations.inserts, [])
        self.assertEqual(operations.conn.enter_count, 1)
        self.assertEqual(operations.conn.exit_count, 1)

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
        self.assertEqual(
            bid_values,
            {
                "JobName": "Bid",
                "Notes": b"",
                "BidDate": None,
                "BidNo": 42,
                "JobID": "",
                "MeasureBase": 0,
                "TakeoffIncrements": 1.0,
                "ScaleStyle": 1,
                "ScaleFactor1": 0.25,
                "ScaleFactor2": 12.0,
                "PageWidth": 42.0,
                "PageHeight": 30.0,
                "JobStatusUID": None,
                "EstimatorUID": None,
            },
        )

    def test_cover_sheet_rejects_silent_noninteger_identifier_coercion(self):
        for key in ("job_status_uid", "estimator_uid", "bid_no"):
            for invalid_value in (True, 7.5, "7.5", "abc", [7]):
                with self.subTest(key=key, value=invalid_value):
                    operations = _path_support__CoverSheetSettingsOps()
                    self.assertFalse(
                        operations.save_cover_sheet(
                            "test.mdb",
                            "7",
                            {
                                key: invalid_value,
                                "job_name": "Bid",
                                "measure_base": 0,
                            },
                        )
                    )
                    self.assertEqual(operations.updates, [])
                    self.assertEqual(operations.inserts, [])

    def test_job_status_update_uses_none_instead_of_textual_null_sentinel(self):
        operations = _path_support__CoverSheetSettingsOps()
        self.assertTrue(operations.update_bid_job_status("test.mdb", "7", None))
        self.assertIsNone(operations.updates[-1]["values"]["JobStatusUID"])
        operations = _path_support__CoverSheetSettingsOps()
        self.assertFalse(operations.update_bid_job_status("test.mdb", "7", "NULL"))
        self.assertEqual(operations.updates, [])
        operations = _path_support__CoverSheetSettingsOps()
        self.assertTrue(operations.update_bid_job_status("test.mdb", "7", "8"))
        self.assertEqual(operations.updates[-1]["values"], {"JobStatusUID": 8})

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
        self.assertEqual(
            [(insert["table"], insert["values"]) for insert in operations.inserts],
            [
                (
                    "JobStatuses",
                    {"UID": 99, "Name": "Open", "Locked": 0, "Sequence": 0},
                ),
                ("PayClasses", {"UID": 99, "Name": "Field"}),
            ],
        )

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
        area_insert = next(
            insert for insert in operations.inserts if insert["table"] == "BidAreas"
        )
        self.assertEqual(area_insert["values"]["UID"], 99)
        self.assertEqual(area_insert["values"]["BidUID"], 7)
        self.assertIsNone(area_insert["values"]["ParentUID"])
        self.assertEqual(area_insert["values"]["Name"], "New Parent")
        self.assertEqual(area_update["values"]["Name"], "Existing Child")

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

    def test_cover_sheet_second_scale_factor_change_rescales_existing_page_positions(
        self,
    ):
        ops = _path_support__ScaleCoverSheetOps(old_sf1=0.125, old_sf2=12.0)
        success = ops.save_cover_sheet(
            "bid.mdb",
            "7",
            {
                "measure_base": 0,
                "pages": [_path_support__cover_sheet_page_update(scale_factor2=24.0)],
            },
        )
        self.assertTrue(success)
        self.assertEqual(ops.rescale_calls, [(11, 2.0)])
        self.assertEqual(ops.overlay_rescale_calls, [(11, 2.0)])

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
        # Page content still follows the scale change exactly once: 64 -> 96 units
        # per sheet inch.
        self.assertEqual(ops.rescale_calls, [(11, 1.5)])

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
        page_insert = ops.inserts[0]["values"]
        self.assertEqual(page_insert["UID"], 99)
        self.assertEqual(page_insert["BidUID"], 7)
        self.assertEqual(page_insert["ScaleFactor1"], 0.25)
        self.assertEqual(page_insert["ScaleFactor2"], 12.0)
        self.assertEqual(page_insert["SheetNo"], "S-101")
        self.assertEqual(page_insert["Name"], "Level 2")
        self.assertEqual(ops.updates[-1]["table"], "Bids")

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
        folder_insert = next(
            insert for insert in ops.inserts if insert["table"] == "BidPageFolders"
        )
        self.assertEqual(folder_insert["values"]["UID"], 99)
        self.assertEqual(folder_insert["values"]["Name"], "New Parent")
        self.assertIsNone(folder_insert["values"]["ParentUID"])
        self.assertEqual(folder_update["values"]["Name"], "Existing Child")

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
        page_delete_calls = [
            (query, args)
            for query, args in ops.conn.cursor_obj.calls
            if query.startswith("DELETE FROM [BidPages] WHERE")
        ]
        self.assertEqual(len(page_delete_calls), chunk_count)
        self.assertEqual(
            [uid for _query, args in page_delete_calls for uid in args],
            list(range(1, page_count + 1)),
        )
        # No statement binds more than one 50-UID chunk plus its owning Bid.
        self.assertTrue(
            all(len(args) <= 51 for _query, args in ops.conn.cursor_obj.calls)
        )


_RealContractOps = RealContractOps
_contract_db = contract_db


def _rows(conn, sql):
    return conn.execute(sql).fetchall()


class MasterDataWriteContractTests(unittest.TestCase):
    def test_new_job_status_writes_every_column_with_documented_defaults(self):
        conn = _contract_db(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked INTEGER, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (4, 'Existing', 0, 1)",
        )
        ops = _RealContractOps(conn)
        result = ops.save_job_statuses(
            "x.mdb",
            {
                "new": [
                    {"uid": "t1", "name": "Won", "locked": True, "sequence": 7},
                    {"uid": "t2"},
                ]
            },
        )
        self.assertEqual(result, {"t1": "5", "t2": "6"})
        self.assertEqual(
            conn.execute("SELECT * FROM JobStatuses ORDER BY UID").fetchall(),
            [(4, "Existing", 0, 1), (5, "Won", -1, 7), (6, "New Status", 0, 0)],
        )
        self.assertEqual(ops.skips, [])

    def test_updated_job_status_writes_every_column_with_documented_defaults(self):
        conn = _contract_db(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked INTEGER, Sequence INTEGER)",
            "INSERT INTO JobStatuses VALUES (4, 'A', 0, 1)",
            "INSERT INTO JobStatuses VALUES (5, 'B', -1, 2)",
            "INSERT INTO JobStatuses VALUES (6, 'C', -1, 3)",
        )
        ops = _RealContractOps(conn)
        result = ops.save_job_statuses(
            "x.mdb",
            {
                "updated": [
                    {"uid": 4, "name": "Renamed", "locked": True, "sequence": 9},
                    {"uid": "5"},
                    {"name": "No uid is ignored"},
                ]
            },
        )
        self.assertEqual(result, {})
        self.assertEqual(
            conn.execute("SELECT * FROM JobStatuses ORDER BY UID").fetchall(),
            [(4, "Renamed", -1, 9), (5, "", 0, 0), (6, "C", -1, 3)],
        )

    def test_job_status_inserts_report_each_skipped_optional_column_by_label(self):
        conn = _contract_db("CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)")
        ops = _RealContractOps(conn)
        ops.save_job_statuses("x.mdb", {"new": [{"uid": "t", "name": "N"}]})
        self.assertEqual(
            ops.skips,
            [
                ("JobStatuses", "Locked", "save_job_status_new"),
                ("JobStatuses", "Sequence", "save_job_status_new"),
            ],
        )
        conn.execute("INSERT INTO JobStatuses VALUES (9, 'Old')")
        ops = _RealContractOps(conn)
        ops.save_job_statuses("x.mdb", {"updated": [{"uid": 9, "name": "N"}]})
        self.assertEqual(
            ops.skips,
            [
                ("JobStatuses", "Locked", "save_job_status"),
                ("JobStatuses", "Sequence", "save_job_status"),
            ],
        )

    def test_job_status_saves_need_their_name_column(self):
        conn = _contract_db("CREATE TABLE JobStatuses (UID INTEGER)")
        conn.execute("INSERT INTO JobStatuses VALUES (1)")
        ops = _RealContractOps(conn)
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                ops.save_job_statuses("x.mdb", {"updated": [{"uid": 1, "name": "N"}]})
            )
        self.assertIn("Failed to save job statuses", logs.records[0].getMessage())
        self.assertIn("Missing JobStatuses.Name", str(logs.records[0].exc_info[1]))
        with self.assertLogs("test", "ERROR"):
            self.assertIsNone(
                ops.save_job_statuses("x.mdb", {"new": [{"uid": "t", "name": "N"}]})
            )
        self.assertEqual(conn.execute("SELECT UID FROM JobStatuses").fetchall(), [(1,)])

    def test_pay_class_saves_write_names_with_documented_defaults(self):
        conn = _contract_db(
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (3, 'A')",
            "INSERT INTO PayClasses VALUES (4, 'B')",
        )
        ops = _RealContractOps(conn)
        result = ops.save_pay_classes(
            "x.mdb",
            {
                "updated": [{"uid": 3, "name": "Renamed"}, {"uid": 4}],
                "new": [{"uid": "n1", "name": "Fresh"}, {"uid": "n2"}],
            },
        )
        self.assertEqual(result, {"n1": "5", "n2": "6"})
        self.assertEqual(
            conn.execute("SELECT * FROM PayClasses ORDER BY UID").fetchall(),
            [(3, "Renamed"), (4, ""), (5, "Fresh"), (6, "New Pay Class")],
        )
        self.assertEqual(ops.skips, [])

    def test_pay_class_saves_need_their_name_column(self):
        conn = _contract_db("CREATE TABLE PayClasses (UID INTEGER)")
        conn.execute("INSERT INTO PayClasses VALUES (1)")
        for changes in (
            {"updated": [{"uid": 1, "name": "N"}]},
            {"new": [{"uid": "t"}]},
        ):
            with self.subTest(changes=changes):
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(
                        _RealContractOps(conn).save_pay_classes("x.mdb", changes)
                    )
                self.assertIn(
                    "Failed to save pay classes", logs.records[0].getMessage()
                )
        self.assertEqual(conn.execute("SELECT UID FROM PayClasses").fetchall(), [(1,)])

    def test_condition_type_saves_write_names_with_documented_defaults(self):
        conn = _contract_db(
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
            "INSERT INTO CdnTypes VALUES (3, 'A')",
            "INSERT INTO CdnTypes VALUES (4, 'B')",
        )
        ops = _RealContractOps(conn)
        result = ops.save_condition_types(
            "x.mdb",
            {
                "updated": [{"uid": 3, "name": "Renamed"}, {"uid": 4}],
                "new": [{"uid": "n1", "name": "Fresh"}, {"uid": "n2"}],
            },
        )
        self.assertEqual(result, {"n1": "5", "n2": "6"})
        self.assertEqual(
            conn.execute("SELECT * FROM CdnTypes ORDER BY UID").fetchall(),
            [(3, "Renamed"), (4, ""), (5, "Fresh"), (6, "New Condition Type")],
        )
        self.assertEqual(ops.skips, [])

    def test_condition_type_saves_need_their_name_column(self):
        conn = _contract_db("CREATE TABLE CdnTypes (UID INTEGER)")
        conn.execute("INSERT INTO CdnTypes VALUES (1)")
        for changes in (
            {"updated": [{"uid": 1, "name": "N"}]},
            {"new": [{"uid": "t"}]},
        ):
            with self.subTest(changes=changes):
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(
                        _RealContractOps(conn).save_condition_types("x.mdb", changes)
                    )
                self.assertIn(
                    "Failed to save condition types", logs.records[0].getMessage()
                )
        self.assertEqual(conn.execute("SELECT UID FROM CdnTypes").fetchall(), [(1,)])

    def test_bid_job_status_update_needs_its_status_column(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO JobStatuses VALUES (5, 'Open')",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).update_bid_job_status("x.mdb", "1", "5"), False
            )
        self.assertIn("Missing Bids.JobStatusUID", str(logs.records[0].exc_info[1]))

    def test_bid_job_status_update_writes_and_clears_the_status(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobStatusUID INTEGER)",
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "INSERT INTO Bids VALUES (1, NULL)",
            "INSERT INTO Bids VALUES (2, 5)",
            "INSERT INTO JobStatuses VALUES (5, 'Open')",
        )
        ops = _RealContractOps(conn)
        self.assertIs(ops.update_bid_job_status("x.mdb", "1", "5"), True)
        self.assertIs(ops.update_bid_job_status("x.mdb", "2", None), True)
        self.assertEqual(
            conn.execute("SELECT * FROM Bids ORDER BY UID").fetchall(),
            [(1, 5), (2, None)],
        )


class CoverSheetBidColumnContractTests(unittest.TestCase):
    _BIDS = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT, Notes BLOB, BidDate TEXT, "
        "BidNo INTEGER, JobID TEXT, MeasureBase INTEGER, TakeoffIncrements REAL, "
        "ScaleStyle INTEGER, ScaleFactor1 REAL, ScaleFactor2 REAL, PageWidth REAL, "
        "PageHeight REAL, JobStatusUID INTEGER, EstimatorUID INTEGER)"
    )
    _SELECT = (
        "SELECT JobName, Notes, BidDate, BidNo, JobID, MeasureBase, TakeoffIncrements, "
        "ScaleStyle, ScaleFactor1, ScaleFactor2, PageWidth, PageHeight, "
        "JobStatusUID, EstimatorUID FROM Bids WHERE UID = {uid}"
    )

    def _db(self):
        return _contract_db(
            self._BIDS,
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "CREATE TABLE Employees (UID INTEGER)",
            "INSERT INTO JobStatuses VALUES (5, 'Open')",
            "INSERT INTO Employees VALUES (8)",
            "INSERT INTO Bids VALUES (1, 'Old', NULL, '2020-01-01', 3, 'OLD', 0, "
            "9.0, 9, 9.0, 9.0, 9.0, 9.0, NULL, NULL)",
            "INSERT INTO Bids VALUES (2, 'Other', NULL, NULL, NULL, 'O', 0, "
            "9.0, 9, 9.0, 9.0, 9.0, 9.0, NULL, NULL)",
        )

    def test_every_bid_field_of_the_cover_sheet_reaches_its_own_column(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet(
                "x.mdb",
                "1",
                {
                    "job_name": "Job",
                    "notes": "memo",
                    "bid_date": "2026-01-02",
                    "bid_no": "12",
                    "job_id": "J-9",
                    "measure_base": 0,
                    "takeoff_increments": 2.5,
                    "scale_style": 3,
                    "scale_factor1": 0.5,
                    "scale_factor2": 24.0,
                    "page_width": 36.0,
                    "page_height": 24.0,
                    "job_status_uid": "5",
                    "estimator_uid": "8",
                },
            ),
            True,
        )
        row = conn.execute(self._SELECT.format(uid=1)).fetchone()
        self.assertEqual(
            (row[0], row[2], row[3], row[4], *row[5:]),
            ("Job", "2026-01-02", 12, "J-9", 0, 2.5, 3, 0.5, 24.0, 36.0, 24.0, 5, 8),
        )
        self.assertEqual(row[1], encode_text_blob("memo"))
        self.assertEqual(
            conn.execute(self._SELECT.format(uid=2)).fetchone()[0], "Other"
        )

    def test_a_bare_cover_sheet_update_writes_the_documented_defaults(self):
        conn = self._db()
        self.assertIs(_RealContractOps(conn).save_cover_sheet("x.mdb", "1", {}), True)
        row = conn.execute(self._SELECT.format(uid=1)).fetchone()
        self.assertEqual(
            (row[0], row[2], row[3], row[4], *row[5:]),
            ("", None, None, "", 0, 1.0, 1, 0.25, 12.0, 42.0, 30.0, None, None),
        )
        self.assertEqual(row[1], encode_text_blob(""))
        self.assertEqual(conn.execute(self._SELECT.format(uid=2)).fetchone()[4], "O")

    def test_an_empty_bid_date_clears_the_date_and_none_notes_clear_the_notes(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet("x.mdb", "1", {"bid_date": "", "notes": None}), True
        )
        row = conn.execute(self._SELECT.format(uid=1)).fetchone()
        self.assertIsNone(row[2])
        self.assertEqual(row[1], encode_text_blob(""))

    def test_the_cover_sheet_bid_update_needs_the_uid_and_job_name_columns(self):
        for dropped in ("UID", "JobName"):
            with self.subTest(missing=dropped):
                conn = _contract_db(
                    f"CREATE TABLE Bids ({'JobName TEXT' if dropped == 'UID' else 'UID INTEGER'})"
                )
                if dropped == "JobName":
                    conn.execute("INSERT INTO Bids VALUES (1)")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIs(
                        _RealContractOps(conn).save_cover_sheet("x.mdb", "1", {}), False
                    )
                self.assertIn(
                    f"Missing Bids.{dropped}", str(logs.records[0].exc_info[1])
                )

    def test_a_job_status_needs_the_status_table(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, JobStatusUID INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Old', NULL)",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb", "1", {"job_status_uid": "5"}
                ),
                False,
            )
        self.assertIn("JobStatuses is unavailable", str(logs.records[0].exc_info[1]))
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet("x.mdb", "1", {"job_name": "Kept"}),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT JobName, JobStatusUID FROM Bids").fetchall(),
            [("Kept", None)],
        )

    def test_an_estimator_needs_the_employee_table(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, EstimatorUID INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Old', NULL)",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb", "1", {"estimator_uid": "8"}
                ),
                False,
            )
        self.assertIn("Employees is unavailable", str(logs.records[0].exc_info[1]))


class _PyodbcTranslatingCursor(_SqliteCursorWrapper):
    """Access reports statement failures as pyodbc.Error, not sqlite3 errors."""

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        try:
            return super().execute(query, *params)
        except sqlite3.Error as exc:
            raise pyodbc.Error("23000", str(exc)) from exc


class _PyodbcTranslatingConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _PyodbcTranslatingCursor(self._connection)


class _TolerantPyodbcOps(RealContractOps):
    def _connection(self, _db_path):
        return _PyodbcTranslatingConnection(self._connection_ref)


class _StrictPyodbcOps(_TolerantPyodbcOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


_POISON_TRIGGER = (
    "CREATE TRIGGER poison BEFORE {event} ON {table} WHEN NEW.Name = 'poison' "
    "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
)


class MasterDataWriteFailurePolicyTests(unittest.TestCase):
    """A failing row write is skipped under the tolerant policy and raised under the strict one."""

    def _case(self, table, columns, rows, event="UPDATE"):
        conn = _contract_db(
            f"CREATE TABLE {table} ({columns})",
            *[f"INSERT INTO {table} VALUES {row}" for row in rows],
            _POISON_TRIGGER.format(event=event, table=table),
        )
        return conn

    def test_a_failing_job_status_update_is_skipped_but_later_updates_still_run(self):
        for ops_class, raises in (
            (_TolerantPyodbcOps, False),
            (_StrictPyodbcOps, True),
        ):
            with self.subTest(strict=raises):
                conn = self._case(
                    "JobStatuses", "UID INTEGER, Name TEXT", ["(1, 'a')", "(2, 'b')"]
                )
                changes = {
                    "updated": [
                        {"uid": 1, "name": "poison"},
                        {"uid": 2, "name": "fine"},
                    ]
                }
                if raises:
                    with self.assertRaises(pyodbc.Error):
                        ops_class(conn).save_job_statuses("x.mdb", changes)
                else:
                    self.assertEqual(
                        ops_class(conn).save_job_statuses("x.mdb", changes), {}
                    )
                    self.assertEqual(
                        _rows(conn, "SELECT UID, Name FROM JobStatuses ORDER BY UID"),
                        [(1, "a"), (2, "fine")],
                    )

    def test_a_failing_job_status_insert_is_skipped_and_left_out_of_the_uid_map(self):
        for ops_class, raises in (
            (_TolerantPyodbcOps, False),
            (_StrictPyodbcOps, True),
        ):
            with self.subTest(strict=raises):
                conn = self._case(
                    "JobStatuses", "UID INTEGER, Name TEXT", [], event="INSERT"
                )
                changes = {
                    "new": [
                        {"uid": "t1", "name": "poison"},
                        {"uid": "t2", "name": "fine"},
                    ]
                }
                if raises:
                    with self.assertRaises(pyodbc.Error):
                        ops_class(conn).save_job_statuses("x.mdb", changes)
                else:
                    self.assertEqual(
                        ops_class(conn).save_job_statuses("x.mdb", changes), {"t2": "2"}
                    )
                    self.assertEqual(
                        _rows(conn, "SELECT UID, Name FROM JobStatuses"), [(2, "fine")]
                    )

    def test_a_failing_pay_class_write_follows_the_same_policy(self):
        for event, key, changes in (
            (
                "UPDATE",
                "updated",
                {"updated": [{"uid": 1, "name": "poison"}, {"uid": 2, "name": "fine"}]},
            ),
            (
                "INSERT",
                "new",
                {
                    "new": [
                        {"uid": "t1", "name": "poison"},
                        {"uid": "t2", "name": "fine"},
                    ]
                },
            ),
        ):
            for ops_class, raises in (
                (_TolerantPyodbcOps, False),
                (_StrictPyodbcOps, True),
            ):
                with self.subTest(event=event, strict=raises):
                    rows = ["(1, 'a')", "(2, 'b')"] if event == "UPDATE" else []
                    conn = self._case(
                        "PayClasses", "UID INTEGER, Name TEXT", rows, event=event
                    )
                    if raises:
                        with self.assertRaises(pyodbc.Error):
                            ops_class(conn).save_pay_classes("x.mdb", changes)
                    else:
                        result = ops_class(conn).save_pay_classes("x.mdb", changes)
                        if key == "new":
                            self.assertEqual(result, {"t2": "2"})
                            self.assertEqual(
                                _rows(conn, "SELECT UID, Name FROM PayClasses"),
                                [(2, "fine")],
                            )
                        else:
                            self.assertEqual(result, {})
                            self.assertEqual(
                                _rows(
                                    conn,
                                    "SELECT UID, Name FROM PayClasses ORDER BY UID",
                                ),
                                [(1, "a"), (2, "fine")],
                            )

    def test_a_failing_condition_type_write_follows_the_same_policy(self):
        for event, key, changes in (
            (
                "UPDATE",
                "updated",
                {"updated": [{"uid": 1, "name": "poison"}, {"uid": 2, "name": "fine"}]},
            ),
            (
                "INSERT",
                "new",
                {
                    "new": [
                        {"uid": "t1", "name": "poison"},
                        {"uid": "t2", "name": "fine"},
                    ]
                },
            ),
        ):
            for ops_class, raises in (
                (_TolerantPyodbcOps, False),
                (_StrictPyodbcOps, True),
            ):
                with self.subTest(event=event, strict=raises):
                    rows = ["(1, 'a')", "(2, 'b')"] if event == "UPDATE" else []
                    conn = self._case(
                        "CdnTypes", "UID INTEGER, Name TEXT", rows, event=event
                    )
                    if raises:
                        with self.assertRaises(pyodbc.Error):
                            ops_class(conn).save_condition_types("x.mdb", changes)
                    else:
                        result = ops_class(conn).save_condition_types("x.mdb", changes)
                        if key == "new":
                            self.assertEqual(result, {"t2": "2"})
                        else:
                            self.assertEqual(result, {})
                            self.assertEqual(
                                _rows(
                                    conn, "SELECT UID, Name FROM CdnTypes ORDER BY UID"
                                ),
                                [(1, "a"), (2, "fine")],
                            )


class CoverSheetPageAndFolderContractTests(unittest.TestCase):
    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
        "INSERT INTO Bids VALUES (1, 'Job')",
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, SheetNo TEXT, Name TEXT, "
        "Width REAL, Height REAL, ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER, "
        "RasterDrawMethod INTEGER, ScaleStyle INTEGER, GUID TEXT, Index1 INTEGER, "
        "Sequence INTEGER, MultiPageCount INTEGER, ImagePath TEXT, OverlayImagePath TEXT, "
        "BidPageFolderUID INTEGER)",
    )
    _PAGE = (
        "SELECT SheetNo, Name, Width, Height, ScaleFactor1, ScaleFactor2, Show, "
        "RasterDrawMethod, ScaleStyle, Index1, Sequence, MultiPageCount, ImagePath, "
        "OverlayImagePath, BidPageFolderUID FROM BidPages WHERE {where}"
    )

    def _db(self):
        return _contract_db(*self._DDL)

    def test_a_new_cover_sheet_page_persists_every_field_and_normalizes_paths(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet(
                "x.mdb",
                "1",
                {
                    "new_folders": [{"local_uid": "f", "name": "Folder"}],
                    "pages": [
                        {
                            "width": 42.0,
                            "height": 30.0,
                            "scale_factor1": 0.25,
                            "scale_factor2": 12.0,
                            "show_mode": 2,
                            "sheet_no": "S-1",
                            "name": "Plan",
                            "index": 7,
                            "sequence": 9,
                            "multi_page_count": 5,
                            "image_path": "dir/a.pdf",
                            "overlay_path": "dir/o.pdf",
                            "folder_uid": "f",
                        }
                    ],
                },
            ),
            True,
        )
        folder_uid = conn.execute("SELECT UID FROM BidPageFolders").fetchone()[0]
        self.assertEqual(
            conn.execute(self._PAGE.format(where="BidUID = 1")).fetchone(),
            (
                "S-1",
                "Plan",
                42.0,
                30.0,
                0.25,
                12.0,
                2,
                1,
                1,
                7,
                9,
                5,
                "dir\\a.pdf",
                "dir\\o.pdf",
                folder_uid,
            ),
        )
        guid = conn.execute("SELECT GUID FROM BidPages").fetchone()[0]
        self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")

    def test_a_new_cover_sheet_page_uses_documented_defaults_for_blank_fields(self):
        conn = self._db()
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb",
            "1",
            {
                "pages": [
                    {
                        "width": 1.0,
                        "height": 2.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 4.0,
                        "show_mode": 0,
                        "sheet_no": None,
                        "name": None,
                        "index": 0,
                        "sequence": 0,
                        "multi_page_count": None,
                        "image_path": None,
                        "overlay_path": None,
                        "folder_uid": "",
                    }
                ]
            },
        )
        self.assertEqual(
            conn.execute(self._PAGE.format(where="BidUID = 1")).fetchone(),
            ("", "", 1.0, 2.0, 1.0, 4.0, 0, 1, 1, 1, 1, 0, "", "", None),
        )

    def test_pages_without_a_width_are_ignored(self):
        conn = self._db()
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb", "1", {"pages": [{"name": "No width", "height": 1.0}]}
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidPages"), [(0,)])

    def test_an_existing_cover_sheet_page_updates_every_field(self):
        conn = self._db()
        conn.execute(
            "INSERT INTO BidPages VALUES (20, 1, 'old', 'Old', 1.0, 1.0, 0.25, 12.0, 0, 1, 1, "
            "'{KEEP}', 1, 1, 0, 'old.pdf', 'old-overlay.pdf', NULL)"
        )
        conn.execute("INSERT INTO BidPageFolders VALUES (5, 1, 'F', NULL)")
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet(
                "x.mdb",
                "1",
                {
                    "pages": [
                        {
                            "uid": 20,
                            "width": 42.0,
                            "height": 30.0,
                            "scale_factor1": 0.25,
                            "scale_factor2": 12.0,
                            "show_mode": 2,
                            "sheet_no": "S-2",
                            "name": "Renamed",
                            "index": 4,
                            "sequence": 8,
                            "image_path": "n/img.pdf",
                            "overlay_path": "old-overlay.pdf",
                            "folder_uid": "5",
                        }
                    ]
                },
            ),
            True,
        )
        row = conn.execute(
            "SELECT SheetNo, Name, Width, Height, Show, Index1, Sequence, ImagePath, "
            "OverlayImagePath, BidPageFolderUID, GUID, BidUID, MultiPageCount "
            "FROM BidPages WHERE UID = 20"
        ).fetchone()
        self.assertEqual(
            row,
            (
                "S-2",
                "Renamed",
                42.0,
                30.0,
                2,
                4,
                8,
                "n\\img.pdf",
                "old-overlay.pdf",
                5,
                "{KEEP}",
                1,
                0,
            ),
        )

    def test_an_existing_cover_sheet_page_with_blank_fields_uses_the_defaults(self):
        conn = self._db()
        conn.execute(
            "INSERT INTO BidPages VALUES (20, 1, 'old', 'Old', 1.0, 1.0, 0.25, 12.0, 0, 1, 1, "
            "'{KEEP}', 5, 5, 0, 'old.pdf', NULL, 3)"
        )
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb",
            "1",
            {
                "pages": [
                    {
                        "uid": 20,
                        "width": 1.0,
                        "height": 1.0,
                        "scale_factor1": 0.25,
                        "scale_factor2": 12.0,
                        "show_mode": 0,
                        "sheet_no": None,
                        "name": None,
                        "index": None,
                        "sequence": None,
                        "image_path": None,
                        "overlay_path": None,
                        "folder_uid": None,
                    }
                ]
            },
        )
        self.assertEqual(
            conn.execute(
                "SELECT SheetNo, Name, Index1, Sequence, ImagePath, OverlayImagePath, "
                "BidPageFolderUID FROM BidPages WHERE UID = 20"
            ).fetchone(),
            ("", "", 1, 1, "", "", None),
        )

    def test_updating_a_page_of_another_bid_is_refused(self):
        conn = self._db()
        conn.execute(
            "INSERT INTO BidPages VALUES (20, 2, 'o', 'Other', 1.0, 1.0, 0.25, 12.0, 0, 1, 1, "
            "'{G}', 1, 1, 0, '', '', NULL)"
        )
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb",
                    "1",
                    {
                        "pages": [
                            {
                                "uid": 20,
                                "width": 9.0,
                                "height": 9.0,
                                "scale_factor1": 0.25,
                                "scale_factor2": 12.0,
                                "show_mode": 0,
                                "name": "Hijack",
                            }
                        ]
                    },
                ),
                False,
            )
        self.assertEqual(_rows(conn, "SELECT Name FROM BidPages"), [("Other",)])

    def test_new_folders_use_a_default_name_and_link_parents_by_new_uid(self):
        conn = self._db()
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb",
            "1",
            {
                "new_folders": [
                    {"local_uid": "child", "name": "Child", "parent_uid": "root"},
                    {"local_uid": "root", "name": ""},
                ]
            },
        )
        rows = {
            n: (u, p)
            for u, n, p in _rows(
                conn, "SELECT UID, Name, ParentUID FROM BidPageFolders"
            )
        }
        self.assertEqual(set(rows), {"Child", "New Folder"})
        self.assertIsNone(rows["New Folder"][1])
        self.assertEqual(rows["Child"][1], rows["New Folder"][0])

    def test_an_existing_folder_update_with_a_blank_name_is_skipped(self):
        conn = self._db()
        conn.execute("INSERT INTO BidPageFolders VALUES (5, 1, 'Keep', NULL)")
        conn.execute("INSERT INTO BidPageFolders VALUES (6, 1, 'Rename me', NULL)")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Parent', NULL)")
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb",
            "1",
            {
                "folders": [
                    {"uid": 5, "name": ""},
                    {"uid": 6, "name": "Renamed", "parent_uid": 7},
                ]
            },
        )
        self.assertEqual(
            _rows(conn, "SELECT UID, Name, ParentUID FROM BidPageFolders ORDER BY UID"),
            [(5, "Keep", None), (6, "Renamed", 7), (7, "Parent", None)],
        )

    def test_deleting_folders_unassigns_their_pages_and_children(self):
        conn = self._db()
        conn.execute("INSERT INTO BidPageFolders VALUES (5, 1, 'Gone', NULL)")
        conn.execute("INSERT INTO BidPageFolders VALUES (6, 1, 'Child', 5)")
        conn.execute("INSERT INTO BidPageFolders VALUES (7, 1, 'Stays', NULL)")
        conn.execute(
            "INSERT INTO BidPages VALUES (20, 1, '', 'A', 1.0, 1.0, 0.25, 12.0, 0, 1, 1, "
            "'{G}', 1, 1, 0, '', '', 5)"
        )
        conn.execute(
            "INSERT INTO BidPages VALUES (21, 1, '', 'B', 1.0, 1.0, 0.25, 12.0, 0, 1, 1, "
            "'{H}', 1, 2, 0, '', '', 7)"
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"deleted_folder_uids": ["5"]}
            ),
            True,
        )
        self.assertEqual(
            _rows(conn, "SELECT UID, ParentUID FROM BidPageFolders ORDER BY UID"),
            [(6, None), (7, None)],
        )
        self.assertEqual(
            _rows(conn, "SELECT UID, BidPageFolderUID FROM BidPages ORDER BY UID"),
            [(20, None), (21, 7)],
        )

    def test_deleting_a_folder_of_another_bid_is_refused(self):
        conn = self._db()
        conn.execute("INSERT INTO BidPageFolders VALUES (5, 2, 'Other', NULL)")
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb", "1", {"deleted_folder_uids": ["5"]}
                ),
                False,
            )
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPageFolders"), [(5,)])


class CoverSheetOperationLabelTests(unittest.TestCase):
    """A skipped optional column is reported with the operation that skipped it."""

    _PAGE_COLS = (
        "UID INTEGER, BidUID INTEGER, Width REAL, Height REAL, ScaleFactor1 REAL, "
        "ScaleFactor2 REAL, Show INTEGER, Name TEXT"
    )

    def _db(self, extra=""):
        return _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (1, 'Job')",
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
            f"CREATE TABLE BidPages ({self._PAGE_COLS})",
            *([extra] if extra else []),
        )

    def test_the_bid_update_reports_each_missing_optional_bid_column(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(ops.save_cover_sheet("x.mdb", "1", {"job_name": "N"}), True)
        self.assertIn(("Bids", "PageHeight", "save_cover_sheet_bid"), ops.skips)
        self.assertEqual({op for _t, _c, op in ops.skips}, {"save_cover_sheet_bid"})

    def test_a_new_folder_reports_the_missing_parent_column_with_its_label(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        ops.save_cover_sheet(
            "x.mdb", "1", {"new_folders": [{"local_uid": "a", "name": "A"}]}
        )
        self.assertIn(
            ("BidPageFolders", "ParentUID", "save_cover_sheet_new_folder"), ops.skips
        )

    def test_an_updated_folder_reports_the_missing_parent_column_with_its_label(self):
        conn = self._db("INSERT INTO BidPageFolders VALUES (5, 1, 'F')")
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet("x.mdb", "1", {"folders": [{"uid": 5, "name": "G"}]}),
            True,
        )
        self.assertIn(
            ("BidPageFolders", "ParentUID", "save_cover_sheet_folder"), ops.skips
        )
        self.assertEqual(_rows(conn, "SELECT Name FROM BidPageFolders"), [("G",)])

    def test_a_new_page_reports_missing_optional_page_columns_with_its_label(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        ops.save_cover_sheet(
            "x.mdb",
            "1",
            {
                "pages": [
                    {
                        "width": 1.0,
                        "height": 1.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 4.0,
                        "show_mode": 0,
                    }
                ]
            },
        )
        labels = {op for table, _c, op in ops.skips if table == "BidPages"}
        self.assertEqual(labels, {"save_cover_sheet_new_page"})

    def test_an_updated_page_reports_missing_optional_page_columns_with_its_label(self):
        conn = self._db()
        conn.execute("ALTER TABLE BidPages ADD COLUMN OverlayImagePath TEXT")
        conn.execute(
            "INSERT INTO BidPages (UID, BidUID, Width, Height, ScaleFactor1, ScaleFactor2, "
            "Show, Name, OverlayImagePath) VALUES (20, 1, 1.0, 1.0, 1.0, 4.0, 0, 'Old', '')"
        )
        ops = _RealContractOps(conn)
        ops.save_cover_sheet(
            "x.mdb",
            "1",
            {
                "pages": [
                    {
                        "uid": 20,
                        "width": 2.0,
                        "height": 2.0,
                        "scale_factor1": 1.0,
                        "scale_factor2": 4.0,
                        "show_mode": 1,
                        "name": "New",
                    }
                ]
            },
        )
        labels = {op for table, _c, op in ops.skips if table == "BidPages"}
        self.assertEqual(labels, {"save_cover_sheet_page"})
        self.assertIn(("BidPages", "SheetNo", "save_cover_sheet_page"), ops.skips)
        self.assertEqual(
            _rows(conn, "SELECT Name, Width, Show FROM BidPages"), [("New", 2.0, 1)]
        )

    def test_the_selected_page_save_needs_both_page_identity_columns(self):
        for dropped, remaining in (("UID", "BidUID"), ("BidUID", "UID")):
            with self.subTest(missing=dropped):
                conn = _contract_db(f"CREATE TABLE BidPages ({remaining} INTEGER)")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIs(
                        _RealContractOps(conn).save_bid_selected_page(
                            "x.mdb", "1", "2"
                        ),
                        False,
                    )
                self.assertIn(
                    "does not support selected page persistence",
                    str(logs.records[0].exc_info[1]),
                )


def _employee(uid, **overrides):
    values = dict(
        uid=uid,
        employee_no="E",
        first_name="First",
        last_name="Last",
        address1="A1",
        address2="A2",
        city="City",
        state="ST",
        zip="12345",
        home_phone="H",
        mobile_phone="M",
        email="e@x",
        pay_class_uid="",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


_EMP_COLUMNS = (
    "UID INTEGER, EmployeeNo TEXT, FirstName TEXT, LastName TEXT, Address1 TEXT, "
    "Address2 TEXT, City TEXT, State TEXT, Zip TEXT, HomePhone TEXT, MobilePhone TEXT, "
    "EMail TEXT, PayClassUID INTEGER"
)
_EMP_SELECT = (
    "SELECT UID, EmployeeNo, FirstName, LastName, Address1, Address2, City, State, Zip, "
    "HomePhone, MobilePhone, EMail, PayClassUID FROM Employees ORDER BY UID"
)


class EmployeeSaveContractTests(unittest.TestCase):
    def _db(self, *extra):
        return _contract_db(
            f"CREATE TABLE Employees ({_EMP_COLUMNS})",
            "INSERT INTO Employees VALUES (1, 'old', 'Old', 'Name', 'o1', 'o2', 'oc', 'os', "
            "'oz', 'oh', 'om', 'oe', NULL)",
            "INSERT INTO Employees VALUES (2, 'two', 'Two', 'Name', '', '', '', '', '', '', "
            "'', '', NULL)",
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (5, 'Hourly')",
            *extra,
        )

    def test_updated_and_new_employees_persist_every_field_and_pay_class(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        result = ops.save_employees(
            "x.mdb",
            {
                "updated": [
                    _employee(
                        1,
                        employee_no="E1",
                        first_name="Ann",
                        last_name="Lee",
                        address1="a1",
                        address2="a2",
                        city="c",
                        state="s",
                        zip="z",
                        home_phone="hp",
                        mobile_phone="mp",
                        email="mail",
                        pay_class_uid="5",
                    ),
                ],
                "new": [
                    _employee("tmp-a", first_name="Bob", pay_class_uid="5"),
                    _employee("tmp-b", first_name="Cy", pay_class_uid="new_pc"),
                    _employee("tmp-c", first_name="Di", pay_class_uid=""),
                ],
            },
        )
        self.assertEqual(result, {"tmp-a": "3", "tmp-b": "4", "tmp-c": "5"})
        self.assertEqual(ops.skips, [])
        rows = conn.execute(_EMP_SELECT).fetchall()
        self.assertEqual(
            rows[0],
            (1, "E1", "Ann", "Lee", "a1", "a2", "c", "s", "z", "hp", "mp", "mail", 5),
        )
        self.assertEqual(rows[1][:4], (2, "two", "Two", "Name"))
        self.assertEqual(
            rows[2],
            (
                3,
                "E",
                "Bob",
                "Last",
                "A1",
                "A2",
                "City",
                "ST",
                "12345",
                "H",
                "M",
                "e@x",
                5,
            ),
        )
        self.assertEqual((rows[3][2], rows[3][12]), ("Cy", None))
        self.assertEqual((rows[4][2], rows[4][12]), ("Di", None))

    def test_updated_employees_with_a_blank_uid_are_skipped(self):
        conn = self._db()
        self.assertEqual(
            _RealContractOps(conn).save_employees(
                "x.mdb", {"updated": [_employee(None, first_name="Ghost")]}
            ),
            {},
        )
        self.assertEqual(
            [
                r[0]
                for r in conn.execute("SELECT FirstName FROM Employees ORDER BY UID")
            ],
            ["Old", "Two"],
        )

    def test_an_unknown_pay_class_on_an_update_or_a_new_employee_rejects_the_whole_save(
        self,
    ):
        for changes in (
            {"updated": [_employee(1, first_name="X", pay_class_uid="99")]},
            {"new": [_employee("t", first_name="X", pay_class_uid="99")]},
        ):
            with self.subTest(changes=list(changes)):
                conn = self._db()
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(
                        _RealContractOps(conn).save_employees("x.mdb", changes)
                    )
                self.assertIn("PayClasses", str(logs.records[0].exc_info[1]))
                self.assertEqual(
                    conn.execute(
                        "SELECT FirstName FROM Employees WHERE UID = 1"
                    ).fetchone()[0],
                    "Old",
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM Employees").fetchone()[0], 2
                )

    def test_employee_saves_need_the_uid_column_and_report_optional_columns_by_label(
        self,
    ):
        conn = _contract_db("CREATE TABLE Employees (FirstName TEXT)")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                _RealContractOps(conn).save_employees("x.mdb", {"new": []})
            )
        self.assertIn("Missing Employees.UID", str(logs.records[0].exc_info[1]))
        conn = _contract_db(
            "CREATE TABLE Employees (UID INTEGER, FirstName TEXT)",
            "INSERT INTO Employees VALUES (1, 'x')",
        )
        ops = _RealContractOps(conn)
        self.assertEqual(
            ops.save_employees(
                "x.mdb", {"updated": [_employee(1)], "new": [_employee("t")]}
            ),
            {"t": "2"},
        )
        labels = {op for _t, _c, op in ops.skips}
        self.assertEqual(labels, {"save_employee", "save_employee_new"})
        self.assertIn(("Employees", "LastName", "save_employee"), ops.skips)
        self.assertIn(("Employees", "LastName", "save_employee_new"), ops.skips)
        self.assertNotIn(("Employees", "FirstName", "save_employee"), ops.skips)

    def test_an_invalid_deleted_uid_is_rejected_with_the_table_label(self):
        conn = self._db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIsNone(
                _RealContractOps(conn).save_employees(
                    "x.mdb", {"deleted_uids": ["abc"]}
                )
            )
        self.assertIn("Invalid Employees UID: 'abc'", str(logs.records[0].exc_info[1]))

    def test_deleting_employees_clears_every_dependent_table_and_keeps_the_rest(self):
        conn = self._db(
            "CREATE TABLE Bids (UID INTEGER, EstimatorUID INTEGER, PrManagerUID INTEGER, "
            "JobSiteManagerUID INTEGER)",
            "INSERT INTO Bids VALUES (10, 1, 2, 1)",
            "INSERT INTO Bids VALUES (11, 2, 1, 2)",
            "CREATE TABLE BidDPCSubscribers (UID INTEGER, BidEmployeeUID INTEGER)",
            "INSERT INTO BidDPCSubscribers VALUES (1, 1)",
            "INSERT INTO BidDPCSubscribers VALUES (2, 2)",
            "CREATE TABLE BidEmployees (UID INTEGER, EmployeeUID INTEGER)",
            "INSERT INTO BidEmployees VALUES (100, 1)",
            "INSERT INTO BidEmployees VALUES (200, 2)",
            "CREATE TABLE BidTimeCards (UID INTEGER, BidEmployeeUID INTEGER)",
            "INSERT INTO BidTimeCards VALUES (1, 100)",
            "INSERT INTO BidTimeCards VALUES (2, 200)",
            "CREATE TABLE ConditionSets (UID INTEGER, EmployeeUID INTEGER)",
            "INSERT INTO ConditionSets VALUES (1, 1)",
            "INSERT INTO ConditionSets VALUES (2, 2)",
        )
        self.assertEqual(
            _RealContractOps(conn).save_employees("x.mdb", {"deleted_uids": ["1"]}), {}
        )
        q = lambda sql: conn.execute(sql).fetchall()
        self.assertEqual(q("SELECT UID FROM Employees"), [(2,)])
        self.assertEqual(
            q(
                "SELECT UID, EstimatorUID, PrManagerUID, JobSiteManagerUID FROM Bids ORDER BY UID"
            ),
            [(10, None, 2, None), (11, 2, None, 2)],
        )
        self.assertEqual(q("SELECT UID FROM BidDPCSubscribers"), [(2,)])
        self.assertEqual(q("SELECT UID FROM BidEmployees"), [(200,)])
        self.assertEqual(q("SELECT UID FROM BidTimeCards"), [(2,)])
        self.assertEqual(
            q("SELECT UID, EmployeeUID FROM ConditionSets ORDER BY UID"),
            [(1, None), (2, 2)],
        )

    def test_a_failed_condition_set_clear_warns_and_still_deletes_unless_strict(self):
        for ops_class, strict in (
            (_TolerantPyodbcOps, False),
            (_StrictPyodbcOps, True),
        ):
            with self.subTest(strict=strict):
                conn = self._db(
                    "CREATE TABLE ConditionSets (UID INTEGER, EmployeeUID INTEGER)",
                    "INSERT INTO ConditionSets VALUES (1, 1)",
                    "CREATE TRIGGER block BEFORE UPDATE ON ConditionSets "
                    "BEGIN SELECT RAISE(ABORT, 'blocked'); END",
                )
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        ops_class(conn).save_employees("x.mdb", {"deleted_uids": ["1"]})
                    continue
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertEqual(
                        ops_class(conn).save_employees(
                            "x.mdb", {"deleted_uids": ["1"]}
                        ),
                        {},
                    )
                message = logs.records[0].getMessage()
                self.assertIn("Failed to clear ConditionSets.EmployeeUID", message)
                self.assertIn("[1]", message)
                self.assertEqual(
                    conn.execute("SELECT UID FROM Employees").fetchall(), [(2,)]
                )

    def test_a_failing_employee_row_write_is_skipped_unless_the_policy_is_strict(self):
        for event, key in (("UPDATE", "updated"), ("INSERT", "new")):
            for ops_class, strict in (
                (_TolerantPyodbcOps, False),
                (_StrictPyodbcOps, True),
            ):
                with self.subTest(event=event, strict=strict):
                    conn = self._db(
                        f"CREATE TRIGGER poison BEFORE {event} ON Employees "
                        "WHEN NEW.FirstName = 'poison' "
                        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
                    )
                    if key == "updated":
                        changes = {
                            "updated": [
                                _employee(1, first_name="poison"),
                                _employee(2, first_name="fine"),
                            ]
                        }
                    else:
                        changes = {
                            "new": [
                                _employee("a", first_name="poison"),
                                _employee("b", first_name="fine"),
                            ]
                        }
                    if strict:
                        with self.assertRaises(pyodbc.Error):
                            ops_class(conn).save_employees("x.mdb", changes)
                        continue
                    result = ops_class(conn).save_employees("x.mdb", changes)
                    names = [
                        r[0]
                        for r in conn.execute(
                            "SELECT FirstName FROM Employees ORDER BY UID"
                        )
                    ]
                    if key == "updated":
                        self.assertEqual(result, {})
                        self.assertEqual(names, ["Old", "fine"])
                    else:
                        self.assertEqual(result, {"b": "4"})
                        self.assertEqual(names, ["Old", "Two", "fine"])


class _AreaFixture:
    DDL = (
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "INSERT INTO Bids VALUES (2)",
        "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT, "
        "Sequence INTEGER, WasSent INTEGER, GUID TEXT)",
        "INSERT INTO BidAreas VALUES (10, 1, NULL, 'Root', 1, 1, '{R}')",
        "INSERT INTO BidAreas VALUES (11, 1, 10, 'Child', 2, 1, '{C}')",
        "INSERT INTO BidAreas VALUES (12, 1, NULL, 'Other', 3, 1, '{O}')",
        "INSERT INTO BidAreas VALUES (20, 2, NULL, 'Foreign', 1, 1, '{F}')",
    )

    @staticmethod
    def area(uid, name, parent="", sequence=0):
        return BidArea(
            uid=str(uid),
            bid_uid="1",
            parent_uid=str(parent),
            name=name,
            sequence=sequence,
        )

    @staticmethod
    def changes(new=(), updated=(), deleted=()):
        return BidAreaChangeset(
            new=list(new), updated=list(updated), deleted_uids=list(deleted)
        )

    def db(self, *extra):
        return _contract_db(*self.DDL, *extra)


class BidAreaSaveContractTests(unittest.TestCase, _AreaFixture):
    def test_new_areas_persist_every_column_with_a_fresh_guid_and_local_parent_links(
        self,
    ):
        conn = self.db()
        ops = _RealContractOps(conn)
        result = ops.save_bid_areas(
            "x.mdb",
            "1",
            self.changes(
                new=[
                    self.area("kid", "Kid", parent="mom", sequence=5),
                    self.area("mom", "Mom", sequence=4),
                    self.area("under", "Under root", parent=10, sequence=6),
                ]
            ),
        )
        self.assertEqual(set(result), {"kid", "mom", "under"})
        self.assertEqual(ops.skips, [])
        rows = {
            n: (u, p, s, w, g)
            for u, p, n, s, w, g in conn.execute(
                "SELECT UID, ParentUID, Name, Sequence, WasSent, GUID FROM BidAreas WHERE UID > 20"
            )
        }
        self.assertEqual(set(rows), {"Kid", "Mom", "Under root"})
        self.assertEqual(rows["Mom"][1], None)
        self.assertEqual(rows["Kid"][1], rows["Mom"][0])
        self.assertEqual(rows["Under root"][1], 10)
        self.assertEqual(
            (rows["Kid"][2], rows["Mom"][2], rows["Under root"][2]), (5, 4, 6)
        )
        for _uid, _parent, _seq, was_sent, guid in rows.values():
            self.assertEqual(was_sent, 0)
            self.assertRegex(guid, r"^\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}$")
        self.assertEqual({result[k] for k in result}, {str(rows[n][0]) for n in rows})
        self.assertEqual(
            conn.execute("SELECT BidUID FROM BidAreas WHERE UID > 20").fetchall(),
            [(1,)] * 3,
        )

    def test_updated_areas_rewrite_name_parent_and_sequence_only(self):
        conn = self.db()
        self.assertEqual(
            _RealContractOps(conn).save_bid_areas(
                "x.mdb",
                "1",
                self.changes(
                    updated=[
                        self.area(11, "Renamed", parent=12, sequence=9),
                        self.area(10, "Root again", sequence=1),
                    ]
                ),
            ),
            {},
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID, Name, Sequence, GUID, WasSent FROM BidAreas "
                "WHERE UID IN (10, 11, 12) ORDER BY UID"
            ).fetchall(),
            [
                (10, None, "Root again", 1, "{R}", 1),
                (11, 12, "Renamed", 9, "{C}", 1),
                (12, None, "Other", 3, "{O}", 1),
            ],
        )

    def test_deleting_an_area_removes_every_reference_to_it(self):
        conn = self.db(
            "CREATE TABLE BidPageSettings (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidPageSettings VALUES (1, 12)",
            "INSERT INTO BidPageSettings VALUES (2, 20)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (1, 12)",
            "INSERT INTO BidTakeoffs VALUES (2, 20)",
            "CREATE TABLE BidAreaTranslations (UID INTEGER, MasterAreaUID INTEGER, TranslateAreaUID INTEGER)",
            "INSERT INTO BidAreaTranslations VALUES (1, 12, 20)",
            "INSERT INTO BidAreaTranslations VALUES (2, 20, 12)",
            "INSERT INTO BidAreaTranslations VALUES (3, 20, 20)",
            "CREATE TABLE BidTakeoffTotals (UID INTEGER, BidAreaUID INTEGER)",
            "CREATE TABLE BidLaborCostCodeTotals (UID INTEGER, BidAreaUID INTEGER)",
            "CREATE TABLE BidTypicalGroupTotals (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidTakeoffTotals VALUES (1, 12)",
            "INSERT INTO BidTakeoffTotals VALUES (2, 20)",
            "INSERT INTO BidLaborCostCodeTotals VALUES (1, 12)",
            "INSERT INTO BidLaborCostCodeTotals VALUES (2, 20)",
            "INSERT INTO BidTypicalGroupTotals VALUES (1, 12)",
            "INSERT INTO BidTypicalGroupTotals VALUES (2, 20)",
            "CREATE TABLE BidTimeCards (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidTimeCards VALUES (1, 12)",
            "INSERT INTO BidTimeCards VALUES (2, 20)",
            "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)",
            "INSERT INTO BidTypAreaCounts VALUES (1, 12)",
            "INSERT INTO BidTypAreaCounts VALUES (2, 20)",
        )
        self.assertEqual(
            _RealContractOps(conn).save_bid_areas(
                "x.mdb", "1", self.changes(deleted=["12"])
            ),
            {},
        )
        q = lambda sql: conn.execute(sql).fetchall()
        self.assertEqual(q("SELECT UID FROM BidAreas WHERE UID = 12"), [])
        self.assertEqual(q("SELECT COUNT(*) FROM BidAreas"), [(3,)])
        self.assertEqual(
            q("SELECT UID, BidAreaUID FROM BidPageSettings ORDER BY UID"),
            [(1, None), (2, 20)],
        )
        self.assertEqual(
            q("SELECT UID, BidAreaUID FROM BidTakeoffs ORDER BY UID"),
            [(1, None), (2, 20)],
        )
        self.assertEqual(q("SELECT UID FROM BidAreaTranslations"), [(3,)])
        for table in (
            "BidTakeoffTotals",
            "BidLaborCostCodeTotals",
            "BidTypicalGroupTotals",
            "BidTimeCards",
            "BidTypAreaCounts",
        ):
            self.assertEqual(q(f"SELECT UID FROM {table}"), [(2,)], table)

    def test_area_changes_are_validated_with_exact_messages_before_any_write(self):
        cases = (
            (
                self.changes(updated=[self.area(10, "X")], deleted=["10"]),
                "BidAreas.UID=10 cannot be updated and deleted in one save.",
            ),
            (
                self.changes(updated=[self.area(20, "X")]),
                "BidAreas.UID=20 does not belong to Bids.UID=1.",
            ),
            (
                self.changes(deleted=["20"]),
                "BidAreas.UID=20 does not belong to Bids.UID=1.",
            ),
            (
                self.changes(new=[self.area("n", "A"), self.area("n", "B")]),
                "New BidAreas correlation UID n must be present and unique within one save.",
            ),
            (
                self.changes(new=[self.area("10", "Clash")]),
                "BidAreas contains duplicate pending identity 10.",
            ),
            (
                self.changes(new=[self.area("n", "A", parent=99)]),
                "BidAreas.UID=n references missing BidAreas.UID=99 through ParentUID.",
            ),
            (
                self.changes(new=[self.area("n", "A", parent="zz")]),
                "BidAreas.UID=n has a non-authoritative ParentUID zz",
            ),
            (
                self.changes(updated=[self.area(10, "Root", parent=11)]),
                "BidAreas.UID=10 participates in a ParentUID cycle.",
            ),
            (
                self.changes(
                    new=[
                        self.area("a", "A", parent="b"),
                        self.area("b", "B", parent="a"),
                    ]
                ),
                "participates in a ParentUID cycle",
            ),
            (
                self.changes(deleted=["10"]),
                "BidAreas.UID=11 references missing BidAreas.UID=10 through ParentUID.",
            ),
        )
        for changes, expected in cases:
            with self.subTest(expected=expected):
                conn = self.db()
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertEqual(
                        _RealContractOps(conn).save_bid_areas("x.mdb", "1", changes), {}
                    )
                self.assertIn(expected, str(logs.records[0].exc_info[1]))
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*), SUM(Sequence) FROM BidAreas"
                    ).fetchone(),
                    (4, 7),
                )

    def test_a_schema_without_a_parent_column_cannot_store_a_hierarchy(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                _RealContractOps(conn).save_bid_areas(
                    "x.mdb",
                    "1",
                    self.changes(
                        new=[self.area("a", "A"), self.area("b", "B", parent="a")]
                    ),
                ),
                {},
            )
        self.assertIn(
            "does not support Bid Area hierarchy persistence",
            str(logs.records[0].exc_info[1]),
        )
        flat = _RealContractOps(conn).save_bid_areas(
            "x.mdb", "1", self.changes(new=[self.area("a", "A")])
        )
        self.assertEqual(list(flat), ["a"])

    def test_an_unknown_bid_or_a_missing_table_is_rejected(self):
        conn = self.db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                _RealContractOps(conn).save_bid_areas("x.mdb", "9", self.changes()), {}
            )
        self.assertIn("Bids has no row for UID 9", str(logs.records[0].exc_info[1]))
        conn = _contract_db("CREATE TABLE Bids (UID INTEGER)")
        with self.assertLogs("test", "ERROR") as logs:
            _RealContractOps(conn).save_bid_areas("x.mdb", "1", self.changes())
        self.assertIn("does not support bid areas", str(logs.records[0].exc_info[1]))

    def test_area_saves_need_their_identity_columns_and_report_optional_ones_by_label(
        self,
    ):
        for dropped in ("UID", "BidUID"):
            with self.subTest(missing=dropped):
                conn = self.db()
                conn.execute(f"ALTER TABLE BidAreas DROP COLUMN {dropped}")
                with self.assertLogs("test", "ERROR") as logs:
                    _RealContractOps(conn).save_bid_areas("x.mdb", "1", self.changes())
                self.assertIn(
                    f"Missing BidAreas.{dropped}", str(logs.records[0].exc_info[1])
                )
        conn = self.db()
        conn.execute("ALTER TABLE BidAreas DROP COLUMN Name")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                _RealContractOps(conn).save_bid_areas(
                    "x.mdb", "1", self.changes(new=[self.area("n", "A")])
                ),
                {},
            )
        self.assertIn("Missing BidAreas.Name", str(logs.records[0].exc_info[1]))
        conn = self.db()
        for column in ("Sequence", "WasSent", "GUID"):
            conn.execute(f"ALTER TABLE BidAreas DROP COLUMN {column}")
        ops = _RealContractOps(conn)
        ops.save_bid_areas(
            "x.mdb",
            "1",
            self.changes(new=[self.area("n", "New")], updated=[self.area(10, "Upd")]),
        )
        self.assertIn(("BidAreas", "Sequence", "save_bid_area_new"), ops.skips)
        self.assertIn(("BidAreas", "WasSent", "save_bid_area_new"), ops.skips)
        self.assertIn(("BidAreas", "GUID", "save_bid_area_new"), ops.skips)
        self.assertIn(("BidAreas", "Sequence", "save_bid_area"), ops.skips)

    def test_a_failing_area_write_is_skipped_unless_the_policy_is_strict(self):
        scenarios = (
            ("INSERT", "new", "BidAreas"),
            ("UPDATE", "updated", "BidAreas"),
            ("DELETE", "deleted", "BidAreas"),
            ("DELETE", "deleted", "BidTimeCards"),
            ("DELETE", "deleted", "BidTypAreaCounts"),
        )
        for event, kind, table in scenarios:
            for ops_class, strict in (
                (_TolerantPyodbcOps, False),
                (_StrictPyodbcOps, True),
            ):
                with self.subTest(event=event, table=table, strict=strict):
                    extra = [
                        "CREATE TABLE BidTimeCards (UID INTEGER, BidAreaUID INTEGER)",
                        "CREATE TABLE BidTypAreaCounts (UID INTEGER, BidAreaUID INTEGER)",
                    ]
                    when = {
                        ("INSERT", "BidAreas"): "WHEN NEW.Name = 'poison'",
                        ("UPDATE", "BidAreas"): "WHEN NEW.Name = 'poison'",
                        ("DELETE", "BidAreas"): "WHEN OLD.UID = 12",
                        ("DELETE", "BidTimeCards"): "",
                        ("DELETE", "BidTypAreaCounts"): "",
                    }[(event, table)]
                    extra.append(
                        f"CREATE TRIGGER block BEFORE {event} ON {table} {when} "
                        "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
                    )
                    extra += [
                        "INSERT INTO BidTimeCards VALUES (1, 12)",
                        "INSERT INTO BidTypAreaCounts VALUES (1, 12)",
                    ]
                    conn = self.db(*extra)
                    if kind == "new":
                        changes = self.changes(
                            new=[self.area("a", "poison"), self.area("b", "fine")]
                        )
                    elif kind == "updated":
                        changes = self.changes(
                            updated=[self.area(10, "poison"), self.area(12, "fine")]
                        )
                    else:
                        changes = self.changes(deleted=["12"])
                    if strict:
                        with self.assertRaises(pyodbc.Error):
                            ops_class(conn).save_bid_areas("x.mdb", "1", changes)
                        continue
                    result = ops_class(conn).save_bid_areas("x.mdb", "1", changes)
                    names = [
                        r[0]
                        for r in conn.execute(
                            "SELECT Name FROM BidAreas WHERE BidUID = 1 ORDER BY UID"
                        )
                    ]
                    if kind == "new":
                        self.assertEqual(list(result), ["a", "b"])
                        self.assertIn("fine", names)
                        self.assertNotIn("poison", names)
                    elif kind == "updated":
                        self.assertEqual(result, {})
                        self.assertEqual(names, ["Root", "Child", "fine"])
                    elif table == "BidAreas":
                        self.assertIn("Other", names)
                    else:
                        self.assertNotIn("Other", names)


class SelectedPageSaveContractTests(unittest.TestCase):
    def _db(self, *extra):
        return _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "INSERT INTO BidPages VALUES (20, 2)",
            "CREATE TABLE BidSettings (UID INTEGER, BidUID INTEGER, BidPageSelectedUID INTEGER)",
            "INSERT INTO BidSettings VALUES (1, 1, NULL)",
            *extra,
        )

    def test_an_existing_settings_row_is_updated_and_cleared(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(ops.save_bid_selected_page("x.mdb", "1", "10"), True)
        self.assertEqual(
            conn.execute("SELECT BidPageSelectedUID FROM BidSettings").fetchall(),
            [(10,)],
        )
        for blank in ("", None):
            conn.execute("UPDATE BidSettings SET BidPageSelectedUID = 10")
            self.assertIs(ops.save_bid_selected_page("x.mdb", "1", blank), True)
            self.assertEqual(
                conn.execute("SELECT BidPageSelectedUID FROM BidSettings").fetchall(),
                [(None,)],
            )
        conn.execute("UPDATE BidSettings SET BidPageSelectedUID = 10")
        self.assertIs(ops.save_bid_selected_page("x.mdb", "1", "not-a-number"), True)
        self.assertEqual(
            conn.execute("SELECT BidPageSelectedUID FROM BidSettings").fetchall(),
            [(None,)],
        )

    def test_a_page_of_another_bid_or_a_missing_page_is_refused_with_false(self):
        conn = self._db()
        ops = _RealContractOps(conn)
        self.assertIs(ops.save_bid_selected_page("x.mdb", "1", "20"), False)
        self.assertIs(ops.save_bid_selected_page("x.mdb", "1", "99"), False)
        self.assertEqual(
            conn.execute("SELECT BidPageSelectedUID FROM BidSettings").fetchall(),
            [(None,)],
        )

    def test_a_bid_without_a_settings_row_gets_one_inserted(self):
        conn = self._db("DELETE FROM BidSettings")
        ops = _RealContractOps(conn)
        self.assertIs(ops.save_bid_selected_page("x.mdb", "2", "20"), True)
        self.assertEqual(
            conn.execute(
                "SELECT BidUID, BidPageSelectedUID FROM BidSettings"
            ).fetchall(),
            [(2, 20)],
        )
        self.assertEqual(ops.skips, [])

    def test_two_settings_rows_or_a_missing_bid_or_columns_fail_with_false(self):
        for extra, message in (
            (
                "INSERT INTO BidSettings VALUES (2, 1, NULL)",
                "BidSettings has multiple rows",
            ),
        ):
            conn = self._db(extra)
            with self.assertLogs("test", "ERROR") as logs:
                self.assertIs(
                    _RealContractOps(conn).save_bid_selected_page("x.mdb", "1", "10"),
                    False,
                )
            self.assertIn(message, str(logs.records[0].exc_info[1]))
        conn = self._db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_bid_selected_page("x.mdb", "9", "10"), False
            )
        self.assertIn("Bids has no row for UID 9", str(logs.records[0].exc_info[1]))
        for dropped in ("BidUID", "BidPageSelectedUID"):
            conn = self._db()
            conn.execute(f"ALTER TABLE BidSettings DROP COLUMN {dropped}")
            with self.assertLogs("test", "ERROR") as logs:
                self.assertIs(
                    _RealContractOps(conn).save_bid_selected_page("x.mdb", "1", "10"),
                    False,
                )
            self.assertIn(
                f"Missing BidSettings.{dropped}", str(logs.records[0].exc_info[1])
            )
        conn = self._db()
        conn.execute("ALTER TABLE BidPages DROP COLUMN BidUID")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_bid_selected_page("x.mdb", "1", "10"), False
            )
        self.assertIn("Missing BidPages.BidUID", str(logs.records[0].exc_info[1]))
        conn = self._db("DROP TABLE BidSettings")
        with self.assertLogs("test", "ERROR"):
            self.assertIs(
                _RealContractOps(conn).save_bid_selected_page("x.mdb", "1", "10"), False
            )


class MeasureBaseNormalizationTests(unittest.TestCase):
    """Switching a bid's measure system rewrites only the condition values that change."""

    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
        "INSERT INTO Bids VALUES (1, 'Job', 0)",
        "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1 INTEGER, "
        "UOM2 INTEGER, UOM3 INTEGER, Quantity1 INTEGER, Quantity2 INTEGER, Quantity3 INTEGER)",
        "CREATE TABLE WriteLog (Col TEXT, UID INTEGER)",
        "CREATE TRIGGER log_uom1 AFTER UPDATE OF UOM1 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM1', NEW.UID); END",
        "CREATE TRIGGER log_uom2 AFTER UPDATE OF UOM2 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM2', NEW.UID); END",
        "CREATE TRIGGER log_uom3 AFTER UPDATE OF UOM3 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM3', NEW.UID); END",
        "CREATE TRIGGER log_name AFTER UPDATE OF Name ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('Name', NEW.UID); END",
    )

    def _db(self, *rows):
        conn = _contract_db(*self._DDL)
        for row in rows:
            conn.execute(
                "INSERT INTO BidConditions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", row
            )
        return conn

    def _change(self, conn, measure_base):
        return _RealContractOps(conn).save_cover_sheet(
            "x.mdb", "1", {"job_name": "Job", "measure_base": measure_base}
        )

    def test_switching_to_metric_converts_units_and_elevation_names_of_the_bid_only(
        self,
    ):
        conn = self._db(
            (
                1,
                1,
                "Wall @T 9' 6\"",
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                UOM_CUBIC_FEET,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
            (2, 2, "Other @T 9' 6\"", UOM_LINEAR_FEET, 0, 0, CALC_LINEAR_LENGTH, 0, 0),
        )
        self.assertIs(self._change(conn, 1), True)
        self.assertEqual(
            conn.execute(
                "SELECT Name, UOM1, UOM2, UOM3 FROM BidConditions WHERE UID = 1"
            ).fetchone(),
            ("Wall @T 289.56 cm", UOM_M, UOM_M2, UOM_M3),
        )
        self.assertEqual(
            conn.execute(
                "SELECT Name, UOM1 FROM BidConditions WHERE UID = 2"
            ).fetchone(),
            ("Other @T 9' 6\"", UOM_LINEAR_FEET),
        )
        self.assertEqual(conn.execute("SELECT MeasureBase FROM Bids").fetchone(), (1,))

    def test_switching_back_to_imperial_converts_metric_values(self):
        conn = self._db(
            (1, 1, "Wall @T 285 cm", UOM_M, 0, 0, CALC_LINEAR_LENGTH, 0, 0),
        )
        conn.execute("UPDATE Bids SET MeasureBase = 1")
        self.assertIs(self._change(conn, 0), True)
        self.assertEqual(
            conn.execute("SELECT Name, UOM1 FROM BidConditions").fetchone(),
            ("Wall @T 9' 4 1/4\"", UOM_LINEAR_FEET),
        )

    def test_only_the_values_that_change_are_written(self):
        conn = self._db(
            (
                1,
                1,
                "Plain",
                UOM_M,
                UOM_SQUARE_FEET,
                UOM_M3,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
            (
                2,
                1,
                "Unchanged",
                UOM_M,
                UOM_M2,
                UOM_M3,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
            (
                3,
                1,
                "Name only @T 9' 6\"",
                UOM_M,
                UOM_M2,
                UOM_M3,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                CALC_VOLUME,
            ),
        )
        self.assertIs(self._change(conn, 1), True)
        self.assertEqual(
            sorted(conn.execute("SELECT Col, UID FROM WriteLog").fetchall()),
            [("Name", 3), ("UOM2", 1)],
        )

    def test_an_unreadable_elevation_name_is_reported_and_the_other_conditions_convert(
        self,
    ):
        conn = self._db(
            (
                1,
                1,
                'Broken @B 1/0"',
                UOM_LINEAR_FEET,
                UOM_SQUARE_FEET,
                0,
                CALC_LINEAR_LENGTH,
                CALC_LINEAR_BOTH_SIDES,
                0,
            ),
            (2, 1, "Wall @T 9' 6\"", UOM_LINEAR_FEET, 0, 0, CALC_LINEAR_LENGTH, 0, 0),
        )
        with self.assertLogs(level="WARNING") as logged:
            self.assertIs(self._change(conn, 1), True)
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, UOM1, UOM2 FROM BidConditions ORDER BY UID"
            ).fetchall(),
            [
                (1, 'Broken @B 1/0"', UOM_M, UOM_M2),
                (2, "Wall @T 289.56 cm", UOM_M, 0),
            ],
        )
        self.assertEqual(conn.execute("SELECT MeasureBase FROM Bids").fetchone(), (1,))
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(len(messages), 1)
        self.assertIn("1", messages[0])
        self.assertIn('Broken @B 1/0"', messages[0])

    def test_a_same_system_save_never_touches_conditions(self):
        conn = self._db(
            (1, 1, "Wall @T 9' 6\"", UOM_LINEAR_FEET, 0, 0, CALC_LINEAR_LENGTH, 0, 0),
        )
        self.assertIs(self._change(conn, 0), True)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM WriteLog").fetchone(), (0,))

    def test_conditions_without_quantity_columns_are_normalized_from_their_units(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Job', 0)",
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1 INTEGER)",
            "INSERT INTO BidConditions VALUES (1, 1, 'Plain', ?)".replace(
                "?", str(UOM_LINEAR_FEET)
            ),
        )
        self.assertIs(self._change(conn, 1), True)
        self.assertEqual(
            conn.execute("SELECT UOM1 FROM BidConditions").fetchone(), (UOM_M,)
        )

    def test_a_condition_table_without_the_identity_columns_is_left_alone(self):
        for dropped in ("UID", "BidUID", "Name"):
            with self.subTest(missing=dropped):
                columns = [
                    c
                    for c in ("UID INTEGER", "BidUID INTEGER", "Name TEXT")
                    if not c.startswith(dropped + " ")
                ]
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
                    "INSERT INTO Bids VALUES (1, 'Job', 0)",
                    f"CREATE TABLE BidConditions ({', '.join(columns)}, UOM1 INTEGER)",
                )
                self.assertIs(self._change(conn, 1), True)
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Job', 0)",
        )
        self.assertIs(self._change(conn, 1), True)


class CoverSheetValidationMessageTests(unittest.TestCase):
    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)",
        "INSERT INTO Bids VALUES (1, 'Job', NULL, NULL)",
        "INSERT INTO Bids VALUES (2, 'Other', NULL, NULL)",
        "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
        "INSERT INTO JobStatuses VALUES (5, 'Open')",
        "CREATE TABLE Employees (UID INTEGER)",
        "INSERT INTO Employees VALUES (8)",
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT, ParentUID INTEGER)",
        "INSERT INTO BidPageFolders VALUES (5, 1, 'Root', NULL)",
        "INSERT INTO BidPageFolders VALUES (6, 1, 'Child', 5)",
        "INSERT INTO BidPageFolders VALUES (9, 2, 'Foreign', NULL)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, BidPageFolderUID INTEGER)",
        "INSERT INTO BidPages VALUES (10, 1, 'P', 6)",
        "INSERT INTO BidPages VALUES (20, 2, 'Foreign page', NULL)",
    )

    def _fail(self, updates, ddl=None, expected=""):
        conn = _contract_db(*(ddl or self._DDL))
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet("x.mdb", "1", updates), False
            )
        self.assertIn(expected, str(logs.records[0].exc_info[1]))
        return conn

    def test_unknown_master_references_are_rejected_by_table(self):
        self._fail({"job_status_uid": 99}, expected="JobStatuses")
        self._fail({"estimator_uid": 99}, expected="Employees")

    def test_known_master_references_are_stored(self):
        conn = _contract_db(*self._DDL)
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_status_uid": 5, "estimator_uid": 8}
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT JobStatusUID, EstimatorUID FROM Bids WHERE UID = 1"
            ).fetchone(),
            (5, 8),
        )

    def test_pages_and_folders_of_another_bid_are_rejected_with_the_table_label(self):
        self._fail(
            {"deleted_page_uids": [20]},
            expected="BidPages.UID=20 does not belong to Bids.UID=1",
        )
        self._fail(
            {"pages": [{"uid": 20, "width": 1.0, "height": 1.0}]},
            expected="BidPages.UID=20 does not belong to Bids.UID=1",
        )
        self._fail(
            {"deleted_folder_uids": [9]},
            expected="BidPageFolders.UID=9 does not belong to Bids.UID=1.",
        )
        self._fail(
            {"folders": [{"uid": 9, "name": "Hijack"}]},
            expected="BidPageFolders.UID=9 does not belong to Bids.UID=1.",
        )

    def test_invalid_deleted_identifiers_are_rejected_with_the_table_label(self):
        self._fail(
            {"deleted_page_uids": ["x"]}, expected="BidPages contains malformed UID x"
        )
        self._fail(
            {"deleted_folder_uids": ["y"]},
            expected="BidPageFolders contains malformed UID y",
        )

    def test_folder_hierarchy_edits_are_validated_against_the_resulting_graph(self):
        self._fail(
            {"folders": [{"uid": 5, "name": "Root", "parent_uid": 6}]},
            expected="BidPageFolders.UID=5 participates in a ParentUID cycle.",
        )
        self._fail(
            {"folders": [{"uid": 6, "name": "Child", "parent_uid": "zz"}]},
            expected="BidPageFolders parent zz is not authoritative.",
        )
        self._fail(
            {"folders": [{"uid": 6, "name": "Child", "parent_uid": 77}]},
            expected="BidPageFolders.UID=77 does not belong to Bids.UID=1.",
        )
        self._fail(
            {"new_folders": [{"local_uid": "5", "name": "Dup"}]},
            expected="BidPageFolders contains duplicate pending identity 5.",
        )
        self._fail(
            {
                "new_folders": [
                    {"local_uid": "a", "name": "A"},
                    {"local_uid": "a", "name": "B"},
                ]
            },
            expected="duplicate pending identity a",
        )
        self._fail(
            {"pages": [{"uid": 10, "width": 1.0, "height": 1.0, "folder_uid": 88}]},
            expected="BidPageFolders.UID=88 does not belong to Bids.UID=1.",
        )

    def test_a_deleted_parent_folder_orphans_its_children_instead_of_dangling(self):
        conn = _contract_db(*self._DDL)
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"deleted_folder_uids": [5]}
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ParentUID FROM BidPageFolders WHERE BidUID = 1"
            ).fetchall(),
            [(6, None)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT BidPageFolderUID FROM BidPages WHERE UID = 10"
            ).fetchone(),
            (6,),
        )

    def test_a_reparent_into_a_deleted_folder_is_rejected(self):
        self._fail(
            {
                "deleted_folder_uids": [5],
                "folders": [{"uid": 6, "name": "Child", "parent_uid": 5}],
            },
            expected="BidPageFolders.UID=5 does not belong to Bids.UID=1.",
        )

    def test_folder_edits_need_a_folder_table_and_hierarchy_support(self):
        no_table = tuple(
            s for s in self._DDL if "BidPageFolders" not in s and "BidPages" not in s
        )
        self._fail(
            {"new_folders": [{"local_uid": "a", "name": "A"}]},
            ddl=no_table,
            expected="does not support page-folder persistence",
        )
        flat = tuple(
            (
                s.replace(", ParentUID INTEGER)", ")")
                .replace(", 5)", ")")
                .replace(", NULL)", ")")
                if "BidPageFolders" in s
                else s
            )
            for s in self._DDL
        )
        flat = tuple(s for s in flat if not s.startswith("INSERT INTO BidPageFolders"))
        flat += (
            "INSERT INTO BidPageFolders VALUES (5, 1, 'Root')",
            "INSERT INTO BidPageFolders VALUES (6, 1, 'Child')",
        )
        self._fail(
            {"new_folders": [{"local_uid": "a", "name": "A", "parent_uid": 5}]},
            ddl=flat,
            expected="does not support page-folder hierarchy persistence",
        )
        conn = _contract_db(*flat)
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb",
                "1",
                {"new_folders": [{"local_uid": "a", "name": "A", "parent_uid": 0}]},
            ),
            True,
        )

    def test_a_failing_page_child_delete_warns_and_continues_unless_strict(self):
        for ops_class, strict in (
            (_TolerantPyodbcOps, False),
            (_StrictPyodbcOps, True),
        ):
            with self.subTest(strict=strict):
                conn = _contract_db(
                    *self._DDL,
                    "CREATE TABLE BidLegends (UID INTEGER, BidPageUID INTEGER)",
                    "INSERT INTO BidLegends VALUES (1, 10)",
                    "CREATE TRIGGER block BEFORE DELETE ON BidLegends "
                    "BEGIN SELECT RAISE(ABORT, 'blocked'); END",
                )
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        ops_class(conn).delete_pages("x.mdb", ["10"])
                    continue
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertIs(ops_class(conn).delete_pages("x.mdb", ["10"]), True)
                message = logs.records[0].getMessage()
                self.assertIn(
                    "Failed to delete from BidLegends for pages [10]", message
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM BidPages WHERE UID = 10"
                    ).fetchone(),
                    (0,),
                )


class _RecordingCursor(_SqliteCursorWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def execute(self, query, *params):
        self._queries.append(" ".join(query.split()))
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        return super().execute(query, *params)


class _RecordingConnection(_SqliteConnectionWrapper):
    def __init__(self, connection, queries):
        super().__init__(connection)
        self._queries = queries

    def cursor(self):
        return _RecordingCursor(self._connection, self._queries)


class _RecordingOps(RealContractOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.queries = []

    def _connection(self, _db_path):
        return _RecordingConnection(self._connection_ref, self.queries)


class _FailingSelectCursor(_PyodbcTranslatingCursor):
    def execute(self, query, *params):
        if query.lstrip().upper().startswith("SELECT") and "[BidConditions]" in query:
            raise pyodbc.Error("HY000", "usage lookup failed")
        return super().execute(query, *params)


class _FailingSelectConnection(_SqliteConnectionWrapper):
    def cursor(self):
        return _FailingSelectCursor(self._connection)


class _FailingUsageOps(RealContractOps):
    def _connection(self, _db_path):
        return _FailingSelectConnection(self._connection_ref)


class _StrictFailingUsageOps(_FailingUsageOps):
    @staticmethod
    def _record_caught_mutation_error(_exc):
        return True


class CoverSheetFolderEdgeContractTests(unittest.TestCase):
    _DDL = CoverSheetValidationMessageTests._DDL

    def _db(self, *extra, ddl=None):
        return _contract_db(*(ddl or self._DDL), *extra)

    def _save(self, conn, updates, ops=None):
        return (ops or _RealContractOps(conn)).save_cover_sheet("x.mdb", "1", updates)

    def test_a_folder_uid_that_exists_twice_in_the_table_cannot_be_updated(self):
        conn = self._db("INSERT INTO BidPageFolders VALUES (5, 2, 'Twin', NULL)")
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                self._save(conn, {"folders": [{"uid": 5, "name": "Renamed"}]}), False
            )
        self.assertIn(
            "BidPageFolders contains duplicate UID 5", str(logs.records[0].exc_info[1])
        )
        self.assertEqual(
            conn.execute(
                "SELECT Name FROM BidPageFolders WHERE UID = 5 AND BidUID = 1"
            ).fetchone(),
            ("Root",),
        )

    def test_deleting_a_folder_without_a_folder_table_is_refused_by_the_schema_check(
        self,
    ):
        no_folders = tuple(s for s in self._DDL if "BidPageFolders" not in s)
        no_folders = tuple(s for s in no_folders if "BidPages" not in s)
        conn = _contract_db(*no_folders)
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(self._save(conn, {"deleted_folder_uids": [5]}), False)
        self.assertIn(
            "does not support page-folder persistence", str(logs.records[0].exc_info[1])
        )

    def test_deleting_folders_works_when_pages_cannot_store_a_folder(self):
        conn = self._db(
            "DROP TABLE BidPages",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidPages VALUES (10, 1, 'P')",
        )
        self.assertIs(self._save(conn, {"deleted_folder_uids": [6]}), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPageFolders WHERE BidUID = 1").fetchall(),
            [(5,)],
        )

    def test_folder_tables_need_their_identity_columns_for_any_folder_edit(self):
        for dropped in ("UID", "BidUID"):
            with self.subTest(missing=dropped):
                conn = self._db(f"ALTER TABLE BidPageFolders DROP COLUMN {dropped}")
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIs(
                        self._save(
                            conn, {"new_folders": [{"local_uid": "a", "name": "A"}]}
                        ),
                        False,
                    )
                self.assertIn(
                    f"Missing BidPageFolders.{dropped}",
                    str(logs.records[0].exc_info[1]),
                )

    def test_blank_folder_spellings_never_require_a_folder_table(self):
        no_folders = tuple(
            s for s in self._DDL if "BidPageFolders" not in s and "BidPages" not in s
        ) + (
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Name TEXT, Width REAL, Height REAL, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER, OverlayImagePath TEXT)",
            "INSERT INTO BidPages VALUES (10, 1, 'P', 1.0, 1.0, 0.25, 12.0, 0, '')",
        )
        for blank in ("", 0, "0", None):
            with self.subTest(folder=blank):
                conn = _contract_db(*no_folders)
                page = {
                    "uid": 10,
                    "width": 1.0,
                    "height": 1.0,
                    "scale_factor1": 0.25,
                    "scale_factor2": 12.0,
                    "show_mode": 0,
                    "folder_uid": blank,
                }
                self.assertIs(self._save(conn, {"pages": [page]}), True)

    def test_blank_parent_spellings_never_require_hierarchy_support(self):
        flat = tuple(
            (
                s.replace(", ParentUID INTEGER)", ")")
                if "CREATE TABLE BidPageFolders" in s
                else s
            )
            for s in self._DDL
            if not s.startswith("INSERT INTO BidPageFolders")
        ) + (
            "INSERT INTO BidPageFolders VALUES (5, 1, 'Root')",
            "INSERT INTO BidPageFolders VALUES (6, 1, 'Child')",
        )
        flat = tuple(
            s.replace("BidPageFolderUID INTEGER)", "BidPageFolderUID INTEGER)")
            for s in flat
        )
        for blank in ("", 0, "0", None):
            with self.subTest(parent=blank):
                conn = _contract_db(*flat)
                folder = {"uid": 6, "name": "Child"}
                if blank is not None:
                    folder["parent_uid"] = blank
                self.assertIs(self._save(conn, {"folders": [folder]}), True)

    def test_a_folder_update_may_clear_its_parent_with_any_blank_spelling(self):
        for blank in ("", 0, "0", None):
            with self.subTest(parent=blank):
                conn = self._db()
                folder = {"uid": 6, "name": "Child"}
                if blank is not None:
                    folder["parent_uid"] = blank
                self.assertIs(self._save(conn, {"folders": [folder]}), True)
                self.assertEqual(
                    conn.execute(
                        "SELECT ParentUID FROM BidPageFolders WHERE UID = 6"
                    ).fetchone()[0]
                    in (None, 0),
                    True,
                )

    def test_a_stored_blank_parent_text_is_not_mistaken_for_a_deleted_folder(self):
        conn = self._db("UPDATE BidPageFolders SET ParentUID = '' WHERE UID = 6")
        self.assertIs(self._save(conn, {"deleted_folder_uids": [5]}), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidPageFolders WHERE BidUID = 1").fetchall(),
            [(6,)],
        )

    def test_a_page_update_without_an_original_image_shows_a_replacement_overlay_alone(
        self,
    ):
        columns = (
            "UID INTEGER, BidUID INTEGER, Name TEXT, Width REAL, Height REAL, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER, ImagePath TEXT, "
            "OverlayImagePath TEXT, OverlayRect TEXT, Sequence INTEGER"
        )
        for image, expected in ((None, 1), ("", 1), ("p.pdf", 0)):
            with self.subTest(image=image):
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
                    "INSERT INTO Bids VALUES (1, 'Job')",
                    f"CREATE TABLE BidPages ({columns})",
                    "INSERT INTO BidPages VALUES (10, 1, 'P', 4.0, 3.0, 0.25, 12.0, 0, '', '', '', 1)",
                )
                page = {
                    "uid": 10,
                    "width": 4.0,
                    "height": 3.0,
                    "scale_factor1": 0.25,
                    "scale_factor2": 12.0,
                    "show_mode": 0,
                    "overlay_path": "new/o.pdf",
                    "image_path": image,
                }
                self.assertIs(self._save(conn, {"pages": [page]}), True)
                row = conn.execute(
                    "SELECT Show, OverlayImagePath, OverlayRect FROM BidPages"
                ).fetchone()
                self.assertEqual(row[0], expected)
                self.assertEqual(row[1], "new\\o.pdf")
                self.assertNotEqual(row[2], "")

    def test_a_new_page_with_only_an_overlay_is_shown_alone(self):
        columns = (
            "UID INTEGER, BidUID INTEGER, Width REAL, Height REAL, ScaleFactor1 REAL, "
            "ScaleFactor2 REAL, Show INTEGER, ImagePath TEXT, OverlayImagePath TEXT, "
            "OverlayRect TEXT"
        )
        for image, expected in ((None, 1), ("p.pdf", 3)):
            with self.subTest(image=image):
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
                    "INSERT INTO Bids VALUES (1, 'Job')",
                    f"CREATE TABLE BidPages ({columns})",
                )
                page = {
                    "width": 4.0,
                    "height": 3.0,
                    "scale_factor1": 0.25,
                    "scale_factor2": 12.0,
                    "show_mode": 3,
                    "overlay_path": "o.pdf",
                    "image_path": image,
                }
                self.assertIs(self._save(conn, {"pages": [page]}), True)
                self.assertEqual(
                    conn.execute("SELECT Show FROM BidPages").fetchone(), (expected,)
                )

    def test_an_updated_page_rewrites_its_scale_factors_and_rescales_positions(self):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (1, 'Job')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, Height REAL, "
            "ScaleFactor1 REAL, ScaleFactor2 REAL, Show INTEGER, OverlayImagePath TEXT)",
            "INSERT INTO BidPages VALUES (10, 1, 4.0, 3.0, 0.25, 12.0, 0, '')",
        )
        page = {
            "uid": 10,
            "width": 4.0,
            "height": 3.0,
            "scale_factor1": 0.5,
            "scale_factor2": 24.0,
            "show_mode": 0,
        }
        self.assertIs(self._save(conn, {"pages": [page]}), True)
        self.assertEqual(
            conn.execute(
                "SELECT ScaleFactor1, ScaleFactor2, Width, Height FROM BidPages"
            ).fetchone(),
            (0.5, 24.0, 4.0, 3.0),
        )

    def test_page_delete_labels_invalid_identifiers_by_table(self):
        conn = self._db()
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(_RealContractOps(conn).delete_pages("x.mdb", ["x"]), False)
        self.assertIn("Invalid BidPages UID: 'x'", str(logs.records[0].exc_info[1]))

    def test_master_data_deletes_label_invalid_identifiers_by_table(self):
        conn = _contract_db(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT)",
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
        )
        for call, label in (
            (
                lambda o: o.save_job_statuses("x.mdb", {"deleted_uids": ["bad"]}),
                "JobStatuses",
            ),
            (
                lambda o: o.save_pay_classes("x.mdb", {"deleted_uids": ["bad"]}),
                "PayClasses",
            ),
            (
                lambda o: o.save_condition_types("x.mdb", {"deleted_uids": ["bad"]}),
                "CdnTypes",
            ),
        ):
            with self.subTest(label=label):
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertIsNone(call(_RealContractOps(conn)))
                self.assertIn(
                    f"Invalid {label} UID: 'bad'", str(logs.records[0].exc_info[1])
                )

    def test_page_cascade_rejects_duplicate_comment_and_takeoff_uids_with_table_labels(
        self,
    ):
        base = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
        )
        conn = _contract_db(
            *base,
            "CREATE TABLE BidComments (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, ParentCommentUID INTEGER)",
            "INSERT INTO BidComments VALUES (7, 1, 10, NULL)",
            "INSERT INTO BidComments VALUES (7, 1, 10, NULL)",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(_RealContractOps(conn).delete_pages("x.mdb", ["10"]), False)
        self.assertIn(
            "BidComments contains duplicate UID 7", str(logs.records[0].exc_info[1])
        )
        conn = _contract_db(
            *base,
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (8, 1, 10)",
            "INSERT INTO BidTakeoffs VALUES (8, 1, 10)",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(_RealContractOps(conn).delete_pages("x.mdb", ["10"]), False)
        self.assertIn(
            "BidTakeoffs contains duplicate UID 8", str(logs.records[0].exc_info[1])
        )

    def test_page_cascade_skips_percent_and_annotation_tables_that_lack_the_takeoff_columns(
        self,
    ):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (8, 1, 10)",
            "CREATE TABLE BidPercents (UID INTEGER)",
            "INSERT INTO BidPercents VALUES (1)",
            "CREATE TABLE BidDimensions (UID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidDimensions VALUES (1, 99)",
            "CREATE TABLE BidALines (UID INTEGER, BidTakeoffFromUID INTEGER)",
            "INSERT INTO BidALines VALUES (1, 8)",
        )
        with self.assertNoLogs("test", "ERROR"):
            self.assertIs(_RealContractOps(conn).delete_pages("x.mdb", ["10"]), True)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidPercents").fetchone(), (1,)
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidDimensions").fetchone(), (1,)
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidALines").fetchone(), (0,)
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM BidPages").fetchone(), (0,))


class MeasureBaseColumnSemanticsTests(unittest.TestCase):
    def _run(self, rows, metric_target=1, columns=None):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Job', %d)" % (1 - metric_target),
            "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1 INTEGER, "
            "UOM2 INTEGER, UOM3 INTEGER, Quantity1 INTEGER, Quantity2 INTEGER, Quantity3 INTEGER)",
            "CREATE TABLE WriteLog (Col TEXT, UID INTEGER)",
            *[
                f"CREATE TRIGGER log_{c} AFTER UPDATE OF {c} ON BidConditions "
                f"BEGIN INSERT INTO WriteLog VALUES ('{c}', NEW.UID); END"
                for c in ("UOM1", "UOM2", "UOM3", "Name")
            ],
        )
        for row in rows:
            conn.execute(
                "INSERT INTO BidConditions VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)", row
            )
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb", "1", {"job_name": "Job", "measure_base": metric_target}
        )
        return conn

    def test_each_quantity_column_drives_the_unit_of_its_own_slot(self):
        conn = self._run(
            [
                (1, "A", UOM_SQUARE_FEET, 0, 0, CALC_LINEAR_LENGTH, 0, 0),
                (2, "B", 0, UOM_LINEAR_FEET, 0, 0, CALC_LINEAR_BOTH_SIDES, 0),
                (3, "C", 0, 0, UOM_LINEAR_FEET, 0, 0, CALC_VOLUME),
            ]
        )
        rows = conn.execute(
            "SELECT UID, UOM1, UOM2, UOM3 FROM BidConditions ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows[0][1], UOM_M)
        self.assertEqual(rows[1][2], UOM_M2)
        self.assertEqual(rows[2][3], UOM_M3)

    def test_conditions_with_no_units_or_quantities_are_not_written(self):
        conn = self._run([(1, None, None, None, None, None, None, None)])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM WriteLog").fetchone(), (0,))
        conn = self._run([(1, "Plain", None, None, None, None, None, None)])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM WriteLog").fetchone(), (0,))


class MoreSettingsPolicyTests(unittest.TestCase):
    def test_updated_employees_and_master_rows_without_a_uid_are_skipped_not_fatal(
        self,
    ):
        conn = _contract_db(
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (1, 'A')",
            "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
            "INSERT INTO CdnTypes VALUES (1, 'A')",
        )
        ops = _RealContractOps(conn)
        self.assertEqual(
            ops.save_pay_classes(
                "x.mdb", {"updated": [{"name": "ghost"}, {"uid": 1, "name": "B"}]}
            ),
            {},
        )
        self.assertEqual(
            ops.save_condition_types(
                "x.mdb", {"updated": [{"name": "ghost"}, {"uid": 1, "name": "B"}]}
            ),
            {},
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM PayClasses").fetchall(), [("B",)]
        )
        self.assertEqual(conn.execute("SELECT Name FROM CdnTypes").fetchall(), [("B",)])

    def test_an_updated_employee_with_a_pending_pay_class_keeps_its_other_fields_and_no_pay_class(
        self,
    ):
        conn = _contract_db(
            f"CREATE TABLE Employees ({_EMP_COLUMNS})",
            "INSERT INTO Employees VALUES (1, 'old', 'Old', 'Name', '', '', '', '', '', '', '', '', 5)",
            "CREATE TABLE PayClasses (UID INTEGER, Name TEXT)",
            "INSERT INTO PayClasses VALUES (5, 'Hourly')",
        )
        self.assertEqual(
            _RealContractOps(conn).save_employees(
                "x.mdb",
                {
                    "updated": [
                        _employee(1, first_name="Renamed", pay_class_uid="new_pc")
                    ]
                },
            ),
            {},
        )
        self.assertEqual(
            conn.execute("SELECT FirstName, PayClassUID FROM Employees").fetchone(),
            ("Renamed", None),
        )

    def test_a_failing_condition_type_usage_lookup_refuses_the_delete_unless_strict(
        self,
    ):
        for ops_class, strict in (
            (_FailingUsageOps, False),
            (_StrictFailingUsageOps, True),
        ):
            with self.subTest(strict=strict):
                conn = _contract_db(
                    "CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)",
                    "INSERT INTO CdnTypes VALUES (1, 'A')",
                    "CREATE TABLE BidConditions (UID INTEGER, CdnTypeUID INTEGER)",
                )
                if strict:
                    with self.assertRaises(pyodbc.Error):
                        ops_class(conn).save_condition_types(
                            "x.mdb", {"deleted_uids": [1]}
                        )
                    continue
                with self.assertLogs("test", "WARNING") as logs:
                    self.assertIsNone(
                        ops_class(conn).save_condition_types(
                            "x.mdb", {"deleted_uids": [1]}
                        )
                    )
                self.assertIn(
                    "Failed to validate condition type usage for [1]",
                    logs.records[0].getMessage(),
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM CdnTypes").fetchone(), (1,)
                )

    def test_area_and_folder_sql_selects_the_parent_column_only_when_it_exists(self):
        for parent_column, expected in (
            (", ParentUID INTEGER", "[ParentUID]"),
            ("", "NULL AS [ParentUID]"),
        ):
            with self.subTest(table="BidAreas", parent=bool(parent_column)):
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER)",
                    "INSERT INTO Bids VALUES (1)",
                    f"CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT{parent_column})",
                )
                ops = _RecordingOps(conn)
                ops.save_bid_areas(
                    "x.mdb", "1", BidAreaChangeset(new=[], updated=[], deleted_uids=[])
                )
                self.assertIn(
                    f"SELECT [UID], {expected} FROM [BidAreas] WHERE [BidUID]=?",
                    ops.queries,
                )
        for parent_column, expected in (
            (", ParentUID INTEGER", "[ParentUID]"),
            ("", "NULL AS [ParentUID]"),
        ):
            with self.subTest(table="BidPageFolders", parent=bool(parent_column)):
                conn = _contract_db(
                    "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
                    "INSERT INTO Bids VALUES (1, 'J')",
                    "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
                    f"CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT{parent_column})",
                )
                ops = _RecordingOps(conn)
                ops.save_cover_sheet(
                    "x.mdb", "1", {"new_folders": [{"local_uid": "a", "name": "A"}]}
                )
                self.assertIn(
                    f"SELECT [UID], {expected} FROM [BidPageFolders] WHERE [BidUID]=?",
                    ops.queries,
                )

    def _areas_db(self, *extra):
        return _contract_db(*_AreaFixture.DDL, *extra)

    def test_area_rows_with_duplicate_uids_in_the_bid_block_every_area_save(self):
        conn = self._areas_db(
            "INSERT INTO BidAreas VALUES (12, 1, NULL, 'Dup', 9, 1, '{D}')"
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                _RealContractOps(conn).save_bid_areas(
                    "x.mdb",
                    "1",
                    BidAreaChangeset(
                        new=[],
                        updated=[
                            BidArea(
                                uid="10",
                                bid_uid="1",
                                parent_uid="",
                                name="X",
                                sequence=1,
                            )
                        ],
                        deleted_uids=[],
                    ),
                ),
                {},
            )
        self.assertIn(
            "BidAreas contains duplicate UID 12", str(logs.records[0].exc_info[1])
        )

    def test_malformed_area_identifiers_are_rejected_by_table(self):
        for changes, expected in (
            (
                BidAreaChangeset(new=[], updated=[], deleted_uids=["zz"]),
                "BidAreas contains malformed UID zz",
            ),
            (
                BidAreaChangeset(
                    new=[],
                    updated=[
                        BidArea(
                            uid="yy", bid_uid="1", parent_uid="", name="X", sequence=1
                        )
                    ],
                    deleted_uids=[],
                ),
                "BidAreas contains malformed UID yy",
            ),
        ):
            with self.subTest(expected=expected):
                conn = self._areas_db()
                with self.assertLogs("test", "ERROR") as logs:
                    self.assertEqual(
                        _RealContractOps(conn).save_bid_areas("x.mdb", "1", changes), {}
                    )
                self.assertIn(expected, str(logs.records[0].exc_info[1]))

    def test_an_updated_area_whose_uid_exists_in_another_bid_too_is_refused(self):
        conn = self._areas_db(
            "INSERT INTO BidAreas VALUES (10, 2, NULL, 'Twin', 1, 1, '{T}')"
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertEqual(
                _RealContractOps(conn).save_bid_areas(
                    "x.mdb",
                    "1",
                    BidAreaChangeset(
                        new=[],
                        updated=[
                            BidArea(
                                uid="10",
                                bid_uid="1",
                                parent_uid="",
                                name="X",
                                sequence=1,
                            )
                        ],
                        deleted_uids=[],
                    ),
                ),
                {},
            )
        self.assertIn(
            "BidAreas contains duplicate UID 10", str(logs.records[0].exc_info[1])
        )

    def test_new_and_updated_areas_treat_every_blank_parent_spelling_as_root(self):
        for blank in ("", 0, "0", None):
            with self.subTest(parent=blank):
                conn = self._areas_db()
                result = _RealContractOps(conn).save_bid_areas(
                    "x.mdb",
                    "1",
                    BidAreaChangeset(
                        new=[
                            BidArea(
                                uid="n",
                                bid_uid="1",
                                parent_uid=blank,
                                name="New",
                                sequence=7,
                            )
                        ],
                        updated=[
                            BidArea(
                                uid="11",
                                bid_uid="1",
                                parent_uid=blank,
                                name="Upd",
                                sequence=2,
                            )
                        ],
                        deleted_uids=[],
                    ),
                )
                self.assertEqual(list(result), ["n"])
                # The string "0" is truthy text, so it is stored as the integer 0; the other
                # spellings are stored as NULL. Every reader treats both as the root.
                expected = 0 if blank == "0" else None
                (stored,) = conn.execute(
                    "SELECT ParentUID FROM BidAreas WHERE UID = 11"
                ).fetchone()
                self.assertEqual(stored, expected)
                (stored_new,) = conn.execute(
                    "SELECT ParentUID FROM BidAreas WHERE UID = ?", (int(result["n"]),)
                ).fetchone()
                self.assertEqual(stored_new, expected)

    def test_stored_blank_area_parents_are_roots_when_other_areas_change(self):
        conn = self._areas_db("UPDATE BidAreas SET ParentUID = '' WHERE UID = 12")
        self.assertEqual(
            _RealContractOps(conn).save_bid_areas(
                "x.mdb",
                "1",
                BidAreaChangeset(new=[], updated=[], deleted_uids=["10", "11"]),
            ),
            {},
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAreas WHERE BidUID = 1").fetchall(),
            [(12,)],
        )


class SettingsFolderResolutionTests(unittest.TestCase):
    """_resolve_folder_uid turns whatever the page dialog sent into an Access Long."""

    resolve = staticmethod(_RealContractOps._resolve_folder_uid)

    def test_a_pending_folder_resolves_to_the_integer_it_was_assigned(self):
        for assigned in (7, "7"):
            with self.subTest(assigned=assigned):
                result = self.resolve(
                    "local", {"local": assigned}, invalid_as_none=False
                )
                self.assertEqual(result, 7)
                self.assertIs(type(result), int)

    def test_a_blank_reference_is_no_folder(self):
        for blank in (None, "", 0):
            self.assertIsNone(self.resolve(blank, {}, invalid_as_none=False))

    def test_an_unusable_reference_is_none_only_when_the_caller_allows_it(self):
        self.assertIsNone(self.resolve("abc", {}, invalid_as_none=True))
        with self.assertRaises(ValueError):
            self.resolve("abc", {}, invalid_as_none=False)
        self.assertEqual(self.resolve("12", {}, invalid_as_none=False), 12)


class CoverSheetInputShapeTests(unittest.TestCase):
    """The save reads the dialog's update dict without taking ownership of its lists."""

    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
        "INSERT INTO Bids VALUES (1, 'Job')",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (10, 1)",
        "INSERT INTO BidPages VALUES (11, 1)",
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)",
    )

    def test_the_callers_deleted_page_list_is_not_extended_by_the_save(self):
        conn = _contract_db(*self._DDL)
        deleted = [10]
        updates = {"deleted_page_uids": deleted, "pages": [{"uid": 11, "width": None}]}
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet("x.mdb", "1", updates), True
        )
        self.assertEqual(deleted, [10])
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPages"), [(11,)])

    def test_the_callers_deleted_folder_list_is_not_extended_by_the_save(self):
        conn = _contract_db(
            *self._DDL,
            "INSERT INTO BidPageFolders VALUES (5, 1, NULL, 'Gone')",
            "INSERT INTO BidPageFolders VALUES (6, 1, NULL, 'Kept')",
        )
        deleted = [5]
        updates = {
            "deleted_folder_uids": deleted,
            "folders": [{"uid": 6, "name": "Kept"}],
        }
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet("x.mdb", "1", updates), True
        )
        self.assertEqual(deleted, [5])
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPageFolders"), [(6,)])

    def test_tuples_are_accepted_for_the_deleted_page_uids(self):
        conn = _contract_db(*self._DDL)
        updates = {"deleted_page_uids": (10,), "pages": [{"uid": 11, "width": None}]}
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet("x.mdb", "1", updates), True
        )
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPages"), [(11,)])

    def test_a_page_without_a_width_is_ignored_even_when_it_names_an_existing_page(
        self,
    ):
        conn = _contract_db(*self._DDL, "ALTER TABLE BidPages ADD COLUMN Name TEXT")
        conn.execute("UPDATE BidPages SET Name = 'Old'")
        ops = _RealContractOps(conn)
        self.assertIs(
            ops.save_cover_sheet(
                "x.mdb", "1", {"pages": [{"uid": 10, "width": None, "name": "Changed"}]}
            ),
            True,
        )
        self.assertEqual(
            _rows(conn, "SELECT Name FROM BidPages ORDER BY UID"), [("Old",), ("Old",)]
        )

    def test_a_folder_table_without_a_uid_column_does_not_block_a_save_that_touches_no_folder(
        self,
    ):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (1, 'Job')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "CREATE TABLE BidPageFolders (BidUID INTEGER, Name TEXT)",
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Renamed"}
            ),
            True,
        )
        self.assertEqual(_rows(conn, "SELECT JobName FROM Bids"), [("Renamed",)])

    def test_new_folders_without_a_parent_are_inserted_in_the_order_given(self):
        conn = _contract_db(*self._DDL)
        new_folders = [
            {"local_uid": "f", "name": "First"},
            {"local_uid": "x", "name": "Second"},
            {"name": "Third"},
        ]
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"new_folders": new_folders}
            ),
            True,
        )
        self.assertEqual(
            _rows(conn, "SELECT Name FROM BidPageFolders ORDER BY rowid"),
            [("First",), ("Second",), ("Third",)],
        )

    def test_a_duplicated_folder_uid_in_the_table_blocks_any_folder_save_with_its_table_label(
        self,
    ):
        conn = _contract_db(
            *self._DDL,
            "INSERT INTO BidPageFolders VALUES (5, 1, NULL, 'A')",
            "INSERT INTO BidPageFolders VALUES (5, 1, NULL, 'B')",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb", "1", {"new_folders": [{"local_uid": "n", "name": "N"}]}
                ),
                False,
            )
        self.assertRegex(
            str(logs.records[0].exc_info[1]),
            r"^BidPageFolders contains duplicate UID 5;",
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidPageFolders"), [(2,)])

    def test_a_malformed_folder_uid_in_the_table_blocks_any_folder_save(self):
        conn = _contract_db(
            *self._DDL,
            "INSERT INTO BidPageFolders VALUES (0, 1, NULL, 'Zero')",
        )
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIs(
                _RealContractOps(conn).save_cover_sheet(
                    "x.mdb", "1", {"new_folders": [{"local_uid": "n", "name": "N"}]}
                ),
                False,
            )
        self.assertRegex(
            str(logs.records[0].exc_info[1]),
            r"^BidPageFolders contains malformed UID 0;",
        )


class _ValidatorHarness:
    """Run a static validator against a real sqlite table through the writer's cursor shape."""

    @staticmethod
    def call_validator(ddl, validator, *args):
        conn = _contract_db(*ddl)
        ops = _RealContractOps(conn)
        with ops._connection("x.mdb") as connection:
            return validator(connection.cursor(), ops._schema(connection), 1, *args)


class MasterDataIterableInputTests(unittest.TestCase):
    """The new-row collections of the settings dialogs may be any iterable, read once."""

    def test_new_job_statuses_may_be_a_generator(self):
        conn = _contract_db(
            "CREATE TABLE JobStatuses (UID INTEGER, Name TEXT, Locked INTEGER, Sequence INTEGER)"
        )
        rows = ({"uid": f"t{i}", "name": f"S{i}"} for i in range(2))
        self.assertEqual(
            _RealContractOps(conn).save_job_statuses("x.mdb", {"new": rows}),
            {"t0": "1", "t1": "2"},
        )
        self.assertEqual(
            _rows(conn, "SELECT Name FROM JobStatuses ORDER BY UID"), [("S0",), ("S1",)]
        )

    def test_new_pay_classes_may_be_a_generator(self):
        conn = _contract_db("CREATE TABLE PayClasses (UID INTEGER, Name TEXT)")
        rows = ({"uid": f"t{i}", "name": f"P{i}"} for i in range(2))
        self.assertEqual(
            _RealContractOps(conn).save_pay_classes("x.mdb", {"new": rows}),
            {"t0": "1", "t1": "2"},
        )
        self.assertEqual(
            _rows(conn, "SELECT Name FROM PayClasses ORDER BY UID"), [("P0",), ("P1",)]
        )

    def test_new_condition_types_may_be_a_generator(self):
        conn = _contract_db("CREATE TABLE CdnTypes (UID INTEGER, Name TEXT)")
        rows = ({"uid": f"t{i}", "name": f"C{i}"} for i in range(2))
        self.assertEqual(
            _RealContractOps(conn).save_condition_types("x.mdb", {"new": rows}),
            {"t0": "1", "t1": "2"},
        )
        self.assertEqual(
            _rows(conn, "SELECT Name FROM CdnTypes ORDER BY UID"), [("C0",), ("C1",)]
        )

    def test_new_employees_may_be_a_generator(self):
        conn = _contract_db(f"CREATE TABLE Employees ({_EMP_COLUMNS})")
        rows = (_employee(f"t{i}", first_name=f"F{i}") for i in range(2))
        self.assertEqual(
            _RealContractOps(conn).save_employees("x.mdb", {"new": rows}),
            {"t0": "1", "t1": "2"},
        )
        self.assertEqual(
            _rows(conn, "SELECT FirstName FROM Employees ORDER BY UID"),
            [("F0",), ("F1",)],
        )


class FolderValidatorCanonicalUidTests(unittest.TestCase, _ValidatorHarness):
    """Folder uids are compared by their integer value, however the cell or the dialog spells them."""

    validate = staticmethod(_RealContractOps._require_valid_cover_sheet_folder_updates)
    _TYPED = (
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, ParentUID INTEGER, Name TEXT)",
        "INSERT INTO BidPageFolders VALUES (11, 1, NULL, 'Mom')",
        "INSERT INTO BidPageFolders VALUES (12, 1, 11, 'Kid')",
    )
    _TEXT = (
        "CREATE TABLE BidPageFolders (UID, BidUID INTEGER, ParentUID, Name TEXT)",
        "INSERT INTO BidPageFolders VALUES ('011', 1, NULL, 'Mom')",
        "INSERT INTO BidPageFolders VALUES ('012', 1, '011', 'Kid')",
    )

    def test_a_deleted_uid_with_leading_zeros_names_the_same_folder(self):
        self.call_validator(
            self._TYPED, self.validate, {"deleted_folder_uids": ["011"]}
        )

    def test_a_folder_stored_with_a_text_uid_is_deleted_by_its_integer_value(self):
        self.call_validator(self._TEXT, self.validate, {"deleted_folder_uids": [11]})

    def test_an_updated_uid_with_leading_zeros_names_the_same_folder(self):
        self.call_validator(
            self._TYPED, self.validate, {"folders": [{"uid": "012", "name": "Kid"}]}
        )

    def test_an_unknown_folder_is_still_refused(self):
        from ost_visualizer.infrastructure.database.bid_owned_identity import (
            MissingBidOwnedUidError,
        )

        with self.assertRaises(MissingBidOwnedUidError):
            self.call_validator(
                self._TYPED, self.validate, {"folders": [{"uid": "13", "name": "Nope"}]}
            )
        with self.assertRaises(MissingBidOwnedUidError):
            self.call_validator(
                self._TYPED, self.validate, {"deleted_folder_uids": ["13"]}
            )


class AreaValidatorCanonicalUidTests(
    unittest.TestCase, _ValidatorHarness, _AreaFixture
):
    """Area uids are compared by integer value; a parent pointer is a reference, never a root marker."""

    validate = staticmethod(_RealContractOps._require_valid_bid_area_changes)

    def check(self, changes, extra=(), ddl=None):
        return self.call_validator(ddl or (*self.DDL, *extra), self.validate, changes)

    def test_a_deleted_uid_with_leading_zeros_names_the_same_area(self):
        self.check(self.changes(deleted=["012"]))

    def test_an_updated_uid_with_leading_zeros_names_the_same_area(self):
        self.check(self.changes(updated=[self.area("012", "Other again")]))

    def test_an_updated_area_with_leading_zeros_closes_a_parent_cycle_by_integer_value(
        self,
    ):
        from ost_visualizer.infrastructure.database.bid_owned_identity import (
            CyclicBidOwnedReferenceError,
        )

        with self.assertRaises(CyclicBidOwnedReferenceError):
            self.check(self.changes(updated=[self.area("010", "Root", parent=11)]))

    def test_an_area_stored_with_a_text_uid_is_updated_by_its_integer_value(self):
        ddl = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidAreas (UID, BidUID INTEGER, ParentUID, Name TEXT)",
            "INSERT INTO BidAreas VALUES ('011', 1, NULL, 'Root')",
        )
        self.check(self.changes(updated=[self.area("11", "Renamed")]), ddl=ddl)

    def test_a_parent_pointer_to_area_one_is_a_reference_that_can_dangle(self):
        from ost_visualizer.infrastructure.database.bid_owned_identity import (
            DanglingBidOwnedReferenceError,
        )

        with self.assertRaisesRegex(
            DanglingBidOwnedReferenceError,
            r"^BidAreas\.UID=13 references missing BidAreas\.UID=1 through ParentUID\.$",
        ):
            self.check(
                self.changes(),
                extra=("INSERT INTO BidAreas VALUES (13, 1, 1, 'Lost', 4, 1, '{L}')",),
            )

    def test_new_areas_that_form_a_parent_cycle_cannot_be_ordered_for_insert(self):
        areas = [self.area("a", "A", parent="b"), self.area("b", "B", parent="a")]
        with self.assertRaisesRegex(ValueError, "cycle"):
            _RealContractOps._order_new_bid_areas_for_insert(areas)

    def test_new_areas_are_ordered_parents_first_and_otherwise_as_given(self):
        areas = [
            self.area("kid", "K", parent="mom"),
            self.area("solo", "S"),
            self.area("mom", "M"),
        ]
        ordered = _RealContractOps._order_new_bid_areas_for_insert(areas)
        self.assertEqual([a.uid for a in ordered], ["mom", "kid", "solo"])


class MeasureBaseValueShapeTests(unittest.TestCase):
    """The measure system arrives as text from the dialog and may be stored as text by older files."""

    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase)",
        "INSERT INTO Bids VALUES (1, 'Job', 0)",
        "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1 INTEGER)",
    )

    def _db(self):
        conn = _contract_db(*self._DDL)
        conn.execute(
            "INSERT INTO BidConditions VALUES (1, 1, 'Wall', ?)", (UOM_LINEAR_FEET,)
        )
        return conn

    def test_a_textual_measure_base_switches_the_system_and_is_stored_as_a_number(self):
        conn = self._db()
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": "1"}
            ),
            True,
        )
        self.assertEqual(_rows(conn, "SELECT UOM1 FROM BidConditions"), [(UOM_M,)])
        self.assertEqual(
            _rows(conn, "SELECT MeasureBase, typeof(MeasureBase) FROM Bids"),
            [(1, "integer")],
        )

    def test_a_stored_text_measure_base_equal_to_the_requested_one_changes_nothing(
        self,
    ):
        conn = self._db()
        conn.execute("UPDATE Bids SET MeasureBase = '1'")
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
            ),
            True,
        )
        self.assertEqual(
            _rows(conn, "SELECT UOM1 FROM BidConditions"), [(UOM_LINEAR_FEET,)]
        )

    def test_a_null_stored_measure_base_counts_as_imperial(self):
        conn = self._db()
        conn.execute("UPDATE Bids SET MeasureBase = NULL")
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb", "1", {"job_name": "Job", "measure_base": 0}
        )
        self.assertEqual(
            _rows(conn, "SELECT UOM1 FROM BidConditions"), [(UOM_LINEAR_FEET,)]
        )
        _RealContractOps(conn).save_cover_sheet(
            "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
        )
        self.assertEqual(_rows(conn, "SELECT UOM1 FROM BidConditions"), [(UOM_M,)])


class ConditionValueShapeTests(unittest.TestCase):
    """Unit and calculation codes read back from a loosely typed file are compared as integers."""

    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT, MeasureBase INTEGER)",
        "INSERT INTO Bids VALUES (1, 'Job', 0)",
        "CREATE TABLE BidConditions (UID INTEGER, BidUID INTEGER, Name TEXT, UOM1, UOM2, UOM3, "
        "Quantity1, Quantity2, Quantity3)",
        "CREATE TABLE WriteLog (Col TEXT, UID INTEGER)",
        "CREATE TRIGGER log_uom1 AFTER UPDATE OF UOM1 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM1', NEW.UID); END",
        "CREATE TRIGGER log_uom2 AFTER UPDATE OF UOM2 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM2', NEW.UID); END",
        "CREATE TRIGGER log_uom3 AFTER UPDATE OF UOM3 ON BidConditions "
        "BEGIN INSERT INTO WriteLog VALUES ('UOM3', NEW.UID); END",
    )

    def test_text_coded_conditions_are_converted_exactly_as_integer_coded_ones(self):
        conn = _contract_db(*self._DDL)
        conn.execute(
            "INSERT INTO BidConditions VALUES (1, 1, 'Plain', ?, ?, ?, ?, ?, ?)",
            tuple(
                str(value)
                for value in (
                    UOM_M,
                    UOM_SQUARE_FEET,
                    UOM_M3,
                    CALC_LINEAR_LENGTH,
                    CALC_LINEAR_BOTH_SIDES,
                    CALC_VOLUME,
                )
            ),
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
            ),
            True,
        )
        self.assertEqual(_rows(conn, "SELECT Col, UID FROM WriteLog"), [("UOM2", 1)])
        self.assertEqual(
            _rows(conn, "SELECT CAST(UOM2 AS INTEGER) FROM BidConditions"), [(UOM_M2,)]
        )

    def test_text_coded_imperial_conditions_convert_every_unit_and_leave_metric_ones_alone(
        self,
    ):
        conn = _contract_db(*self._DDL)
        for uid, units in (
            (1, (UOM_LINEAR_FEET, UOM_SQUARE_FEET, UOM_CUBIC_FEET)),
            (2, (UOM_M, UOM_M2, UOM_M3)),
        ):
            conn.execute(
                "INSERT INTO BidConditions VALUES (?, 1, 'Row', ?, ?, ?, ?, ?, ?)",
                (
                    uid,
                    *(str(u) for u in units),
                    *(
                        str(c)
                        for c in (
                            CALC_LINEAR_LENGTH,
                            CALC_LINEAR_BOTH_SIDES,
                            CALC_VOLUME,
                        )
                    ),
                ),
            )
        conn.execute(
            "INSERT INTO BidConditions VALUES (3, 1, 'Uncalculated', '0', '0', '0', '0', '0', '0')"
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
            ),
            True,
        )
        self.assertEqual(
            sorted(_rows(conn, "SELECT Col, UID FROM WriteLog")),
            [("UOM1", 1), ("UOM2", 1), ("UOM3", 1)],
        )
        self.assertEqual(
            _rows(
                conn,
                "SELECT CAST(UOM1 AS INTEGER), CAST(UOM2 AS INTEGER), CAST(UOM3 AS INTEGER) "
                "FROM BidConditions WHERE UID = 1",
            ),
            [(UOM_M, UOM_M2, UOM_M3)],
        )

    def test_blank_codes_are_zero(self):
        conn = _contract_db(*self._DDL)
        conn.execute(
            "INSERT INTO BidConditions VALUES (1, 1, 'Blank', NULL, '', NULL, NULL, '', NULL)"
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
            ),
            True,
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM WriteLog"), [(0,)])


class PageDeleteTextUidTests(unittest.TestCase):
    """Deleting a page re-points the comment and takeoff links of other pages by integer uid."""

    _DDL = (
        "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
        "INSERT INTO Bids VALUES (1, 'Job')",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (10, 1)",
        "INSERT INTO BidPages VALUES (11, 1)",
        "CREATE TABLE BidComments (UID, BidUID INTEGER, BidPageUID INTEGER, ParentCommentUID INTEGER)",
        "INSERT INTO BidComments VALUES ('31', 1, 10, NULL)",
        "INSERT INTO BidComments VALUES (32, 1, 11, 31)",
        "CREATE TABLE BidTakeoffs (UID, BidUID INTEGER, BidPageUID INTEGER, ParentUID INTEGER)",
        "INSERT INTO BidTakeoffs VALUES ('41', 1, 10, NULL)",
        "INSERT INTO BidTakeoffs VALUES (42, 1, 11, 41)",
    )

    def test_links_to_comments_and_takeoffs_of_the_deleted_page_are_cleared(self):
        conn = _contract_db(*self._DDL)
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "deleted_page_uids": [10]}
            ),
            True,
        )
        self.assertEqual(
            _rows(conn, "SELECT ParentCommentUID FROM BidComments WHERE UID = 32"),
            [(None,)],
        )
        self.assertEqual(
            _rows(conn, "SELECT ParentUID FROM BidTakeoffs WHERE UID = 42"), [(None,)]
        )
        self.assertEqual(_rows(conn, "SELECT UID FROM BidPages"), [(11,)])

    def test_a_takeoff_table_with_only_some_reference_columns_is_cleared_for_those_only(
        self,
    ):
        conn = _contract_db(
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT)",
            "INSERT INTO Bids VALUES (1, 'Job')",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (10, 1)",
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)",
            "INSERT INTO BidTakeoffs VALUES (41, 1, 10)",
        )
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "deleted_page_uids": [10]}
            ),
            True,
        )
        self.assertEqual(_rows(conn, "SELECT COUNT(*) FROM BidPages"), [(0,)])


# ---------------------------------------------------------------------------
# Second-pass additions (AB): exact error messages (the earlier tests matched
# substrings, so a changed tail such as the final full stop went unnoticed),
# iterable inputs of the folder validator and driver-typed identifier reads.
# ---------------------------------------------------------------------------
from ost_visualizer.infrastructure.database.bid_owned_identity import (  # noqa: E402
    CyclicBidOwnedReferenceError as _CyclicError,
    DanglingBidOwnedReferenceError,
    MissingBidOwnedUidError as _MissingUidError,
)
from tests.helpers.mdb.real_write_contract import (  # noqa: E402
    ListParamConnection as _ListParamConnection,
    ListParamCursor as _ListParamCursor,
)


class SettingsExactMessageTests(unittest.TestCase, _ValidatorHarness, _AreaFixture):
    folder_check = staticmethod(
        _RealContractOps._require_valid_cover_sheet_folder_updates
    )
    area_check = staticmethod(_RealContractOps._require_valid_bid_area_changes)
    _FOLDER_DDL = CoverSheetValidationMessageTests._DDL

    def raised(self, error_type, call):
        with self.assertRaises(error_type) as caught:
            call()
        return str(caught.exception)

    def folder_message(self, error_type, updates, ddl=None):
        return self.raised(
            error_type,
            lambda: self.call_validator(
                ddl or self._FOLDER_DDL, self.folder_check, updates
            ),
        )

    def area_message(self, error_type, changes, ddl=None):
        return self.raised(
            error_type,
            lambda: self.call_validator(ddl or self.DDL, self.area_check, changes),
        )

    def logged(self, call):
        with self.assertLogs("test", "ERROR") as logs:
            self.assertIn(call(), (None, False, {}))
        return str(logs.records[0].exc_info[1])

    # ---- page-folder validator
    def test_a_folder_that_belongs_to_another_bid_is_refused_with_the_full_sentence(
        self,
    ):
        expected = "BidPageFolders.UID=9 does not belong to Bids.UID=1."
        self.assertEqual(
            self.folder_message(_MissingUidError, {"deleted_folder_uids": [9]}),
            expected,
        )
        self.assertEqual(
            self.folder_message(
                _MissingUidError, {"folders": [{"uid": 9, "name": "Hijack"}]}
            ),
            expected,
        )
        self.assertEqual(
            self.folder_message(
                _MissingUidError,
                {"folders": [{"uid": 6, "name": "Child", "parent_uid": 9}]},
            ),
            expected,
        )

    def test_an_unknown_parent_is_named_in_the_full_sentence(self):
        self.assertEqual(
            self.folder_message(
                _MissingUidError,
                {"folders": [{"uid": 6, "name": "Child", "parent_uid": 77}]},
            ),
            "BidPageFolders.UID=77 does not belong to Bids.UID=1.",
        )

    def test_a_pending_folder_that_reuses_an_identity_is_named_in_the_full_sentence(
        self,
    ):
        self.assertEqual(
            self.folder_message(
                RuntimeError, {"new_folders": [{"local_uid": "5", "name": "Dup"}]}
            ),
            "BidPageFolders contains duplicate pending identity 5.",
        )
        self.assertEqual(
            self.folder_message(
                RuntimeError,
                {
                    "new_folders": [
                        {"local_uid": "a", "name": "A"},
                        {"local_uid": "a", "name": "B"},
                    ]
                },
            ),
            "BidPageFolders contains duplicate pending identity a.",
        )

    def test_a_parent_that_is_not_an_identifier_is_named_in_the_full_sentence(self):
        self.assertEqual(
            self.folder_message(
                _MissingUidError,
                {"folders": [{"uid": 6, "name": "Child", "parent_uid": "zz"}]},
            ),
            "BidPageFolders parent zz is not authoritative.",
        )

    def test_folder_edits_without_a_folder_table_or_hierarchy_column_say_so(self):
        no_table = tuple(
            s
            for s in self._FOLDER_DDL
            if "BidPageFolders" not in s and "BidPages" not in s
        )
        self.assertEqual(
            self.folder_message(
                RuntimeError,
                {"new_folders": [{"local_uid": "a", "name": "A"}]},
                ddl=no_table,
            ),
            "This OST database does not support page-folder persistence.",
        )
        flat = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidPageFolders VALUES (5, 1, 'Root')",
        )
        self.assertEqual(
            self.folder_message(
                RuntimeError,
                {"new_folders": [{"local_uid": "a", "name": "A", "parent_uid": 5}]},
                ddl=flat,
            ),
            "This OST database does not support page-folder hierarchy persistence.",
        )

    def test_a_new_folder_without_a_local_id_gets_a_predictable_pending_identity(self):
        updates = {
            "new_folders": [
                {"name": "A"},
                {"local_uid": "b", "name": "B", "parent_uid": "__new_folder_0"},
            ]
        }
        self.call_validator(self._FOLDER_DDL, self.folder_check, updates)
        conn = _contract_db(*self._FOLDER_DDL)
        self.assertIs(
            _RealContractOps(conn).save_cover_sheet("x.mdb", "1", dict(updates)), True
        )
        rows = dict(
            conn.execute(
                "SELECT Name, UID FROM BidPageFolders WHERE BidUID = 1"
            ).fetchall()
        )
        self.assertEqual(
            conn.execute(
                "SELECT ParentUID FROM BidPageFolders WHERE Name = 'B'"
            ).fetchone(),
            (rows["A"],),
        )

    # ---- cover sheet master references and integer helper
    def test_master_references_without_their_tables_are_refused_by_name(self):
        ddl = (
            "CREATE TABLE Bids (UID INTEGER, JobName TEXT, JobStatusUID INTEGER, EstimatorUID INTEGER)",
            "INSERT INTO Bids VALUES (1, 'Job', NULL, NULL)",
        )
        for field, expected in (
            (
                "job_status_uid",
                "This OST database does not support Job Status selection because "
                "JobStatuses is unavailable.",
            ),
            (
                "estimator_uid",
                "This OST database does not support Estimator selection because "
                "Employees is unavailable.",
            ),
        ):
            with self.subTest(field=field):
                conn = _contract_db(*ddl)
                self.assertEqual(
                    self.logged(
                        lambda: _RealContractOps(conn).save_cover_sheet(
                            "x.mdb", "1", {field: 5}
                        )
                    ),
                    expected,
                )

    def test_optional_integers_refuse_booleans_and_unsupported_types_by_name(self):
        convert = _RealContractOps._optional_integer
        self.assertEqual(
            self.raised(TypeError, lambda: convert(True)),
            "Boolean values are not valid Access integer identifiers",
        )
        self.assertEqual(
            self.raised(TypeError, lambda: convert(1.5)),
            "Unsupported Access integer value: float",
        )
        self.assertEqual(
            self.raised(TypeError, lambda: convert([1])),
            "Unsupported Access integer value: list",
        )
        self.assertEqual(
            (convert(None), convert(" 7 "), convert(" "), convert(8)),
            (None, 7, None, 8),
        )

    # ---- master data and selected page: the missing-table sentences
    def test_each_save_without_its_table_names_the_missing_feature(self):
        empty = lambda: _contract_db(
            "CREATE TABLE Bids (UID INTEGER)", "INSERT INTO Bids VALUES (1)"
        )
        cases = (
            (
                lambda ops: ops.save_job_statuses("x.mdb", {}),
                "This OST database does not support job statuses.",
            ),
            (
                lambda ops: ops.save_employees("x.mdb", {}),
                "This OST database does not support employees.",
            ),
            (
                lambda ops: ops.save_pay_classes("x.mdb", {}),
                "This OST database does not support pay classes.",
            ),
            (
                lambda ops: ops.save_condition_types("x.mdb", {}),
                "This OST database does not support condition types.",
            ),
            (
                lambda ops: ops.save_bid_areas("x.mdb", "1", self.changes()),
                "This OST database does not support bid areas.",
            ),
            (
                lambda ops: ops.save_bid_selected_page("x.mdb", "1", "5"),
                "This OST database does not support selected page persistence.",
            ),
        )
        for call, expected in cases:
            with self.subTest(expected=expected):
                conn = empty()
                self.assertEqual(
                    self.logged(lambda: call(_RealContractOps(conn))), expected
                )

    # ---- bid area validator
    def test_area_edits_are_refused_with_the_full_sentence(self):
        self.assertEqual(
            self.area_message(
                RuntimeError,
                self.changes(updated=[self.area(10, "Root")], deleted=[10]),
            ),
            "BidAreas.UID=10 cannot be updated and deleted in one save.",
        )
        self.assertEqual(
            self.area_message(_MissingUidError, self.changes(deleted=[20])),
            "BidAreas.UID=20 does not belong to Bids.UID=1.",
        )
        self.assertEqual(
            self.area_message(
                RuntimeError, self.changes(new=[self.area("", "Nameless")])
            ),
            "BidAreas contains duplicate pending identity <missing>.",
        )
        self.assertEqual(
            self.area_message(RuntimeError, self.changes(new=[self.area(10, "Clash")])),
            "BidAreas contains duplicate pending identity 10.",
        )
        self.assertEqual(
            self.area_message(
                _MissingUidError, self.changes(new=[self.area("n", "N", parent="zz")])
            ),
            "BidAreas.UID=n has a non-authoritative ParentUID zz.",
        )

    def test_an_area_hierarchy_needs_the_parent_column_and_says_so(self):
        flat = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER, Name TEXT)",
            "INSERT INTO BidAreas VALUES (10, 1, 'Root')",
        )
        self.assertEqual(
            self.area_message(
                RuntimeError,
                self.changes(new=[self.area("n", "N", parent=10)]),
                ddl=flat,
            ),
            "This OST database does not support Bid Area hierarchy persistence.",
        )

    def test_new_areas_that_form_a_cycle_are_refused_by_the_insert_ordering_with_the_full_sentence(
        self,
    ):
        areas = [self.area("a", "A", parent="b"), self.area("b", "B", parent="a")]
        self.assertEqual(
            self.raised(
                ValueError,
                lambda: _RealContractOps._order_new_bid_areas_for_insert(areas),
            ),
            "New Bid Area parent graph contains a cycle.",
        )

    def test_a_self_parented_area_cannot_be_ordered_for_insert(self):
        areas = [self.area("a", "A", parent="a")]
        self.assertEqual(
            self.raised(
                ValueError,
                lambda: _RealContractOps._order_new_bid_areas_for_insert(areas),
            ),
            "New Bid Area parent graph contains a cycle.",
        )

    # ---- the folder validator reads each collection once, whatever iterable it gets
    def test_generator_inputs_are_checked_like_lists(self):
        def gen(items):
            return (item for item in items)

        with self.assertRaises(_MissingUidError):
            self.call_validator(
                self._FOLDER_DDL,
                self.folder_check,
                {"folders": gen([{"uid": 9, "name": "Hijack"}])},
            )
        with self.assertRaises(RuntimeError):
            self.call_validator(
                self._FOLDER_DDL,
                self.folder_check,
                {
                    "new_folders": gen(
                        [
                            {"local_uid": "a", "name": "A"},
                            {"local_uid": "a", "name": "B"},
                        ]
                    )
                },
            )
        no_table = tuple(
            s
            for s in self._FOLDER_DDL
            if "BidPageFolders" not in s and "BidPages" not in s
        )
        self.call_validator(
            no_table, self.folder_check, {"deleted_folder_uids": gen([])}
        )
        with self.assertRaises(_MissingUidError):
            self.call_validator(
                self._FOLDER_DDL, self.folder_check, {"deleted_folder_uids": gen([9])}
            )

    def test_a_text_parent_of_a_deleted_folder_does_not_close_a_cycle_through_a_reused_identity(
        self,
    ):
        ddl = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPageFolders (UID, BidUID INTEGER, ParentUID, Name TEXT)",
            "INSERT INTO BidPageFolders VALUES (5, 1, NULL, 'Gone')",
            "INSERT INTO BidPageFolders VALUES (6, 1, '05', 'Kid')",
        )
        updates = {
            "deleted_folder_uids": [5],
            "new_folders": [{"local_uid": "05", "name": "Reused", "parent_uid": 6}],
        }
        self.call_validator(ddl, self.folder_check, updates)

    def test_a_pending_folder_that_closes_a_cycle_is_refused_with_the_cycle_error(self):
        updates = {"new_folders": [{"local_uid": "a", "name": "A", "parent_uid": "a"}]}
        self.assertEqual(
            self.folder_message(_CyclicError, updates),
            "BidPageFolders.UID=a participates in a ParentUID cycle.",
        )


class _TextUidCursor(_ListParamCursor):
    """Returns the UID column of the condition-normalisation select as zero-padded text."""

    def execute(self, query, *params):
        self._texted = "FROM [BidConditions] WHERE [BidUID]=?" in query
        return super().execute(query, *params)

    def fetchall(self):
        rows = super().fetchall()
        if not self._texted:
            return rows
        return [
            _SqliteRow(
                row._columns,
                [
                    f"{v:04d}" if n == "UID" else v
                    for n, v in zip(row._columns, row._values)
                ],
            )
            for row in rows
        ]


class _TextUidConnection(_ListParamConnection):
    def cursor(self):
        return _TextUidCursor(self._connection)


class _TextUidOps(RealContractOps):
    def _connection(self, _db_path):
        return _TextUidConnection(self._connection_ref)


class DriverTextIdentifierTests(unittest.TestCase):
    def test_a_condition_uid_read_back_as_text_is_still_bound_as_an_integer_when_the_measure_system_changes(
        self,
    ):
        conn = _contract_db(*MeasureBaseNormalizationTests._DDL)
        conn.execute(
            "INSERT INTO BidConditions VALUES (1, 1, 'Wall', ?, 0, 0, ?, 0, 0)",
            (UOM_LINEAR_FEET, CALC_LINEAR_LENGTH),
        )
        self.assertIs(
            _TextUidOps(conn).save_cover_sheet(
                "x.mdb", "1", {"job_name": "Job", "measure_base": 1}
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT UOM1 FROM BidConditions WHERE UID = 1").fetchone(),
            (UOM_M,),
        )


class SettingsValidatorEdgeContractTests(
    unittest.TestCase, _ValidatorHarness, _AreaFixture
):
    folder_check = staticmethod(
        _RealContractOps._require_valid_cover_sheet_folder_updates
    )
    area_check = staticmethod(_RealContractOps._require_valid_bid_area_changes)
    _FLAT = (
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "CREATE TABLE BidPageFolders (UID INTEGER, BidUID INTEGER, Name TEXT)",
        "INSERT INTO BidPageFolders VALUES (5, 1, 'Root')",
        "INSERT INTO BidPageFolders VALUES (9, 2, 'Foreign')",
    )

    def test_a_flat_folder_table_still_checks_generator_inputs_after_the_hierarchy_scan(
        self,
    ):
        # Without a parent column the validator first scans both collections for a parent;
        # the collections must survive that scan to be validated afterwards.
        with self.assertRaises(_MissingUidError):
            self.call_validator(
                self._FLAT,
                self.folder_check,
                {"folders": (item for item in [{"uid": 9, "name": "Hijack"}])},
            )
        with self.assertRaises(RuntimeError):
            self.call_validator(
                self._FLAT,
                self.folder_check,
                {
                    "new_folders": (
                        item
                        for item in [
                            {"local_uid": "a", "name": "A"},
                            {"local_uid": "a", "name": "B"},
                        ]
                    )
                },
            )

    def test_a_new_folder_that_names_its_own_generated_identity_as_parent_closes_a_cycle(
        self,
    ):
        updates = {"new_folders": [{"name": "A", "parent_uid": "__new_folder_0"}]}
        with self.assertRaises(_CyclicError) as caught:
            self.call_validator(
                CoverSheetValidationMessageTests._DDL, self.folder_check, updates
            )
        self.assertEqual(
            str(caught.exception),
            "BidPageFolders.UID=__new_folder_0 participates in a ParentUID cycle.",
        )

    def test_a_stored_text_parent_stays_a_reference_to_the_area_with_that_integer_value(
        self,
    ):
        ddl = (
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidAreas (UID, BidUID INTEGER, ParentUID, Name TEXT)",
            "INSERT INTO BidAreas VALUES (12, 1, '011', 'Orphan')",
        )
        with self.assertRaises(DanglingBidOwnedReferenceError) as caught:
            self.call_validator(
                ddl, self.area_check, self.changes(new=[self.area("011", "Pending")])
            )
        self.assertEqual(
            str(caught.exception),
            "BidAreas.UID=12 references missing BidAreas.UID=11 through ParentUID.",
        )


# ---------------------------------------------------------------------------
# Strict identifier binding for the whole module.
#
# Every UID / BidUID this mixin sends to the database is an integer: the Access
# columns are Long, and Access criteria on a Long column do not take numeric
# text.  sqlite's INTEGER affinity silently coerces '5' to 5, so without this
# patch a dropped int() on a bound identifier is invisible.  Parameters that go
# into the Employees Text columns (EmployeeNo, postal code, phone numbers...) are
# exempt because they legitimately hold digit strings; the identifier columns of
# the same statement (UID, PayClassUID) stay strict.
# ---------------------------------------------------------------------------
_ORIGINAL_CURSOR_EXECUTE = None
_EMPLOYEE_TEXT_COLUMNS = frozenset(
    {
        "EmployeeNo",
        "FirstName",
        "LastName",
        "Address1",
        "Address2",
        "City",
        "State",
        "Zip",
        "HomePhone",
        "MobilePhone",
        "EMail",
    }
)


def _bound_column_names(query):
    import re as _re

    if query.lstrip().upper().startswith("UPDATE"):
        return _re.findall(r"\[(\w+)\]\s*=\s*\?", query)
    match = _re.search(r"\(([^)]*)\)\s*VALUES", query, _re.IGNORECASE)
    return _re.findall(r"\[(\w+)\]", match.group(1)) if match else []


def _strict_identifier_execute(self, query, *params):
    flat = (
        params[0]
        if len(params) == 1 and isinstance(params[0], (list, tuple))
        else params
    )
    names = _bound_column_names(query) if "[Employees]" in query else []
    for index, parameter in enumerate(flat):
        if names and index < len(names) and names[index] in _EMPLOYEE_TEXT_COLUMNS:
            continue
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
