from tests.helpers.mdb.operations import (
    _ParameterLimitedSqliteConnectionWrapper,
    _ParameterLimitedSqliteCursorWrapper,
    _ParameterLimitedSqliteOps,
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
from ost_visualizer.infrastructure.mdb.mdb_reader import MdbReader
from ost_visualizer.infrastructure.mdb.components.takeoff_operations import (
    TakeoffOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.settings_operations import (
    SettingsOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.project_operations import (
    ProjectOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.page_operations import (
    PageOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.layer_operations import (
    LayerOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_operations import (
    ConditionOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.condition_folder_operations import (
    ConditionFolderOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.bulk_write_helpers import (
    AccessBulkWriteMixin,
)
from ost_visualizer.infrastructure.mdb.components.bid_operations import (
    BidOperationsMixin,
)
import unittest
import sqlite3
import logging
import os
from types import SimpleNamespace
import pyodbc
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.cover_sheet.path_support import (
    _FailingPositionScaleOps as _path_support__FailingPositionScaleOps,
    _FakeConnection as _path_support__FakeConnection,
    _FakeCursor as _path_support__FakeCursor,
    _FakeLogger as _path_support__FakeLogger,
    _FakeSchema as _path_support__FakeSchema,
    _OverlayRectConnection as _path_support__OverlayRectConnection,
    _OverlayRectCursor as _path_support__OverlayRectCursor,
    _OverlayScaleOps as _path_support__OverlayScaleOps,
    _OverlayScaleSchema as _path_support__OverlayScaleSchema,
    _PageOverlayOps as _path_support__PageOverlayOps,
    _PageScaleOps as _path_support__PageScaleOps,
    _ScaleConnection as _path_support__ScaleConnection,
    _ScaleCursor as _path_support__ScaleCursor,
)
from collections import namedtuple
from contextlib import contextmanager
from tests.helpers.mdb.real_write_contract import (
    ListParamConnection,
    RealContractOps,
    contract_db,
)
from ost_visualizer.infrastructure.database.bid_owned_identity import (
    IncoherentBidOwnedScopeError,
    MalformedBidOwnedUidError,
    MissingBidOwnedUidError,
)
from ost_visualizer.infrastructure.mdb.components.import_operations import (
    ImportOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.schema_compatibility import (
    UnsupportedMdbSchemaError,
)
from tests.helpers.mdb.import_export_support import (
    _Rows as _import_export_support__Rows,
    _SqliteConnection as _import_export_support__SqliteConnection,
    _SqliteCursor as _import_export_support__SqliteCursor,
    _SqliteMdbWriter as _import_export_support__SqliteMdbWriter,
    _SqliteSchema as _import_export_support__SqliteSchema,
    _create_import_schema as _import_export_support__create_import_schema,
    _named_row as _import_export_support__named_row,
)
from ost_visualizer.infrastructure.mdb.components.serialization import (
    TEXT_POSITION_TABLES,
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
from tests.infrastructure.mdb.components.scale_position_support import (
    _Cursor as _scale_position_support__Cursor,
    _Logger as _scale_position_support__Logger,
    _PageOps as _scale_position_support__PageOps,
    _Schema as _scale_position_support__Schema,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PageOperationsPersistenceTests(unittest.TestCase):
    def test_large_page_image_adjustment_uses_bounded_updates(self):
        row_count = 256
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Rotation INTEGER, FlipX INTEGER, "
            "FlipY INTEGER, Invert INTEGER, Bitonal INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, 1, 0, 0, 0, 0, 0)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertIs(
            _ParameterLimitedSqliteOps(conn).save_page_image_adjustments(
                "large.mdb",
                [str(uid) for uid in range(1, row_count + 1)],
                90,
                True,
                False,
                True,
                False,
            ),
            True,
        )
        self.assertEqual(
            sum(
                sql.lstrip().upper().startswith("UPDATE [BIDPAGES]")
                for sql in statements
            ),
            6,
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidPages "
                "WHERE Rotation=90 AND FlipX=-1 AND FlipY=0 AND Invert=-1 "
                "AND Bitonal=0"
            ).fetchone()[0],
            row_count,
        )

    def test_page_image_adjustment_normalizes_rotation_and_leaves_other_pages_untouched(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidPages ("
            "UID INTEGER, BidUID INTEGER, Rotation INTEGER, FlipX INTEGER, "
            "FlipY INTEGER, Invert INTEGER, Bitonal INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidPages VALUES (?, 1, ?, ?, 0, 0, 0)",
            ((1, 0, 0), (2, 0, 0), (3, 180, -1), (4, 270, -1)),
        )
        ops = _SqliteMdbOps(conn)
        self.assertIs(
            ops.save_page_image_adjustments(
                "bid.mdb", ["1", "2"], 450, False, True, False, True
            ),
            True,
        )
        self.assertIs(
            ops.save_page_image_adjustments(
                "bid.mdb", ["4"], 45, False, False, False, False
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Rotation, FlipX, FlipY, Invert, Bitonal "
                "FROM BidPages ORDER BY UID"
            ).fetchall(),
            [
                (1, 90, 0, -1, 0, -1),
                (2, 90, 0, -1, 0, -1),
                (3, 180, -1, 0, 0, 0),
                (4, 0, 0, 0, 0, 0),
            ],
        )


class PageOperationsCoverSheetPathTests(unittest.TestCase):
    def test_page_scale_save_uses_shared_content_rescale(self):
        ops = _path_support__PageScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0), True)
        self.assertEqual(ops.rescale_calls, [(11, 0.5)])
        self.assertEqual(
            [
                args
                for query, args in ops.conn.cursor_obj.calls
                if query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
            ],
            [(0.25, 12.0, 11)],
        )
        self.assertIsNone(ops.conn.exit_args[-1][0])

    def test_page_scale_save_with_unchanged_calibration_skips_content_rescale(self):
        ops = _path_support__PageScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0), True)
        self.assertEqual(ops.rescale_calls, [])
        self.assertEqual(
            [
                args
                for query, args in ops.conn.cursor_obj.calls
                if query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
            ],
            [(0.125, 12.0, 11)],
        )

    def test_page_scale_save_rejects_invalid_overlay_calibration(self):
        cases = (
            (_path_support__PageScaleOps(old_sf1=0.0, old_sf2=12.0), 0.125, 12.0),
            (_path_support__PageScaleOps(old_sf1=0.125, old_sf2=12.0), 0.0, 12.0),
        )
        for ops, scale_factor1, scale_factor2 in cases:
            with self.subTest(
                old_scale=(
                    ops.conn.cursor_obj.old_sf1,
                    ops.conn.cursor_obj.old_sf2,
                ),
                new_scale=(scale_factor1, scale_factor2),
            ):
                self.assertIs(
                    ops.save_page_scale(
                        "bid.mdb",
                        "11",
                        scale_factor1,
                        scale_factor2,
                    ),
                    False,
                )
                self.assertEqual(ops.rescale_calls, [])
                self.assertIs(
                    any(
                        query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
                        for query, _args in ops.conn.cursor_obj.calls
                    ),
                    False,
                )
                self.assertIs(ops.conn.exit_args[-1][0], ValueError)

    def test_page_scale_change_rescales_overlay_rect_and_offsets(self):
        ops = _path_support__OverlayScaleOps()
        self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0), True)
        self.assertEqual(ops.position_rescales, [(11, 1.5)])
        self.assertEqual(
            ops.updates,
            [
                (
                    "BidPages",
                    {
                        "OverlayRect": ("-1.654719,0.000000,4029.242135,2879.212038"),
                        "OverlayOffsetX": -1.654719,
                        "OverlayOffsetY": 0.0,
                    },
                    "rescale_page_overlay_rect",
                )
            ],
        )
        self.assertEqual(
            [
                args
                for query, args in ops.conn.cursor_obj.calls
                if query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
            ],
            [(0.125, 12.0, 11)],
        )

    def test_page_scale_change_preserves_native_empty_overlay_marker(self):
        ops = _path_support__OverlayScaleOps(overlay_rect="*")
        self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0), True)
        self.assertEqual(ops.position_rescales, [(11, 1.5)])
        self.assertEqual(ops.updates, [])

    def test_page_scale_change_leaves_absent_or_zero_size_overlay_rect_untouched(self):
        for overlay_rect in (None, "", "0.0,0.0,0.0,0.0", "5,5,0,100", "5,5,100,0"):
            with self.subTest(overlay_rect=overlay_rect):
                ops = _path_support__OverlayScaleOps(overlay_rect=overlay_rect)
                self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0), True)
                self.assertEqual(ops.position_rescales, [(11, 1.5)])
                self.assertEqual(ops.updates, [])

    def test_page_scale_change_rejects_malformed_overlay_rect_before_any_write(self):
        for overlay_rect in ("0,0,2688", "0,0,abc,1920", "0,0,-1,1920"):
            with self.subTest(overlay_rect=overlay_rect):
                ops = _path_support__OverlayScaleOps(overlay_rect=overlay_rect)
                self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0), False)
                self.assertEqual(ops.position_rescales, [])
                self.assertEqual(ops.updates, [])
                self.assertIs(
                    any(
                        query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
                        for query, _args in ops.conn.cursor_obj.calls
                    ),
                    False,
                )
                self.assertIs(ops.conn.exit_args[-1][0], ValueError)

    def test_page_scale_position_failure_aborts_scale_update(self):
        ops = _path_support__FailingPositionScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertIs(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0), False)
        self.assertIs(
            any(
                "UPDATE [BidPages] SET [ScaleFactor1]" in query
                for query, _args in ops.conn.cursor_obj.calls
            ),
            False,
        )
        self.assertIs(ops.conn.exit_args[-1][0], pyodbc.Error)

    def test_saving_page_overlay_image_generates_full_page_overlay_rect(self):
        ops = _path_support__PageOverlayOps()
        success = ops.save_page_overlay_image(
            "bid.mdb",
            "11",
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertIs(success, True)
        self.assertEqual(len(ops.updates), 1)
        self.assertEqual(ops.updates[0]["table"], "BidPages")
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayImagePath": r"C:\OCS Documents\OST\overlay.pdf",
                "OverlayRect": "0.000000,0.000000,4032.000000,2880.000000",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_adding_overlay_without_original_selects_the_only_available_source(self):
        ops = _path_support__PageOverlayOps(original_image_path="")
        self.assertIs(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            ),
            True,
        )
        self.assertEqual(ops.updates[0]["values"]["Show"], 1)

    def test_removing_page_overlay_image_clears_all_overlay_owned_storage(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"C:\Plans\overlay.pdf"
        )
        self.assertIs(ops.save_page_overlay_image("bid.mdb", "11", ""), True)
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayImagePath": "",
                "OverlayRect": "",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
                "Show": 0,
            },
        )

    def test_saving_same_overlay_image_preserves_existing_rectangle(self):
        path = r"C:\OCS Documents\OST\overlay.pdf"
        ops = _path_support__PageOverlayOps(current_overlay_path=path)
        self.assertIs(ops.save_page_overlay_image("bid.mdb", "11", path), True)
        self.assertEqual(ops.updates, [])

    def test_saving_same_overlay_image_with_other_separators_preserves_rectangle(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path="C:/OCS Documents/OST/overlay.pdf"
        )
        self.assertIs(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            ),
            True,
        )
        self.assertEqual(ops.updates, [])

    def test_saving_same_overlay_image_with_other_case_preserves_rectangle(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"c:\ocs documents\ost\OVERLAY.PDF"
        )
        self.assertIs(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            ),
            True,
        )
        self.assertEqual(ops.updates, [])

    def test_replacing_overlay_with_different_image_resets_overlay_owned_state(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"C:\Plans\old_overlay.pdf"
        )
        self.assertIs(
            ops.save_page_overlay_image("bid.mdb", "11", r"C:\Plans\replacement.pdf"),
            True,
        )
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayImagePath": r"C:\Plans\replacement.pdf",
                "OverlayRect": "0.000000,0.000000,4032.000000,2880.000000",
                "OverlayOffsetX": 0.0,
                "OverlayOffsetY": 0.0,
                "OverlayRotation": 0.0,
                "OverlayResized": 0,
                "DeskewRotationOverlay": 0.0,
            },
        )

    def test_saving_overlay_rect_mirrors_native_translation_fields(self):
        ops = _path_support__PageOverlayOps()
        self.assertIs(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (-1.103146, -2.5, 2686.161423, 1919.474692),
            ),
            True,
        )
        self.assertEqual(
            ops.updates[0]["values"],
            {
                "OverlayRect": "-1.103146,-2.500000,2686.161423,1919.474692",
                "OverlayOffsetX": -1.103146,
                "OverlayOffsetY": -2.5,
            },
        )

    def test_saving_overlay_rect_rejects_invalid_page_calibration(self):
        cases = (
            {"scale_factor1": 0.0},
            {"scale_factor1": -0.125},
            {"scale_factor2": float("nan")},
        )
        for cursor_options in cases:
            with self.subTest(cursor_options=cursor_options):
                ops = _path_support__PageOverlayOps(**cursor_options)
                self.assertIs(
                    ops.save_page_overlay_rect(
                        "bid.mdb",
                        "11",
                        (0.0, 0.0, 100.0, 100.0),
                    ),
                    False,
                )
                self.assertEqual(ops.updates, [])
                self.assertIs(ops.conn.exit_args[-1][0], ValueError)

    def test_saving_overlay_rect_rejects_invalid_rectangle_before_opening_database(
        self,
    ):
        for overlay_rect in (
            (0.0, 0.0, -1.0, 100.0),
            (0.0, 0.0, 100.0, -1.0),
            (0.0, 0.0, float("nan"), 100.0),
            (0.0, 0.0, 100.0),
        ):
            with self.subTest(overlay_rect=overlay_rect):
                ops = _path_support__PageOverlayOps()
                self.assertIs(
                    ops.save_page_overlay_rect("bid.mdb", "11", overlay_rect), False
                )
                self.assertEqual(ops.updates, [])
                self.assertEqual(ops.conn.enter_count, 0)

    def test_saving_overlay_rect_rejects_missing_page(self):
        ops = _path_support__PageOverlayOps(page_exists=False)
        self.assertIs(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (0.0, 0.0, 100.0, 100.0),
            ),
            False,
        )
        self.assertEqual(ops.updates, [])
        self.assertIs(ops.conn.exit_args[-1][0], ValueError)


class PageOperationsGuardTests(unittest.TestCase):
    class StrictOps(_SqliteDuplicateOps):
        logger = logging.getLogger("page-ops-guard")

        def _require_write_columns(self, schema, table, columns):
            for column in columns:
                schema.require_column(table, column)

    def ops(self, script):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.executescript(
            "CREATE TABLE Bids (UID INTEGER); INSERT INTO Bids VALUES (1);" + script
        )
        return self.StrictOps(connection), connection

    def failure_of(self, call):
        with self.assertLogs("page-ops-guard", level="ERROR") as logs:
            self.assertIs(call(), False)
        self.assertEqual(len(logs.records), 1)
        return logs.records[0]

    def test_a_page_scale_save_needs_the_scale_columns_and_exactly_one_page_row(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL);"
            "INSERT INTO BidPages VALUES (20, 1, 0.125);"
        )
        record = self.failure_of(lambda: ops.save_page_scale("t.mdb", "20", 0.25, 12.0))
        self.assertEqual(
            record.getMessage(), "Failed to save page scale for page 20 in t.mdb"
        )
        self.assertRegex(str(record.exc_info[1]), "Missing BidPages.ScaleFactor2")
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL,"
            " ScaleFactor2 REAL);"
            "INSERT INTO BidPages VALUES (20, 1, 0.125, 12.0), (20, 1, 0.125, 12.0);"
        )
        record = self.failure_of(lambda: ops.save_page_scale("t.mdb", "20", 0.25, 12.0))
        self.assertIn("duplicate", str(record.exc_info[1]).lower())
        self.assertEqual(
            connection.execute("SELECT ScaleFactor1 FROM BidPages").fetchall(),
            [(0.125,), (0.125,)],
        )

    def test_overlay_saves_refuse_an_ambiguous_page_and_change_nothing(self):
        script = (
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, Height REAL,"
            " ScaleFactor1 REAL, ScaleFactor2 REAL, OverlayImagePath TEXT, ImagePath TEXT,"
            " OverlayRect TEXT);"
            "INSERT INTO BidPages VALUES (20, 1, 10.0, 8.0, 0.125, 12.0, 'old.png', 'm.pdf',"
            " '0,0,1,1'), (20, 1, 10.0, 8.0, 0.125, 12.0, 'old.png', 'm.pdf', '0,0,1,1');"
        )
        for label, call in (
            (
                "image",
                lambda ops: ops.save_page_overlay_image("t.mdb", "20", "new.png"),
            ),
            (
                "rect",
                lambda ops: ops.save_page_overlay_rect(
                    "t.mdb", "20", (0.0, 0.0, 5.0, 5.0)
                ),
            ),
        ):
            with self.subTest(save=label):
                ops, connection = self.ops(script)
                record = self.failure_of(lambda: call(ops))
                self.assertIn("duplicate", str(record.exc_info[1]).lower())
                self.assertEqual(
                    connection.execute(
                        "SELECT DISTINCT OverlayImagePath, OverlayRect FROM BidPages"
                    ).fetchall(),
                    [("old.png", "0,0,1,1")],
                )
                self.assertRegex(
                    record.getMessage(),
                    r"^Failed to save page overlay (image|rect) for page 20 in t.mdb",
                )

    def test_a_page_scale_save_rescales_only_the_content_of_that_page(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL,"
            " ScaleFactor2 REAL);"
            "INSERT INTO BidPages VALUES (20, 1, 0.125, 12.0), (21, 1, 0.125, 12.0);"
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,"
            " Position BLOB);"
            "INSERT INTO BidTakeoffs VALUES (1, 1, 20, '1;2;3;4'), (2, 1, 20, ''),"
            " (3, 1, 21, '1;2;3;4');"
            "CREATE TABLE BidLegends (UID INTEGER, BidPageUID INTEGER);"
            "INSERT INTO BidLegends VALUES (9, 20);"
        )
        self.assertIs(ops.save_page_scale("t.mdb", "20", 0.25, 12.0), True)
        rows = connection.execute(
            "SELECT UID, Position FROM BidTakeoffs ORDER BY UID"
        ).fetchall()
        self.assertEqual(
            [(uid, parse_position_storage(position)) for uid, position in rows],
            [(1, [0.5, 1.0, 1.5, 2.0]), (2, []), (3, [1.0, 2.0, 3.0, 4.0])],
        )
        self.assertEqual(
            connection.execute(
                "SELECT UID, ScaleFactor1, ScaleFactor2 FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(20, 0.25, 12.0), (21, 0.125, 12.0)],
        )

    def test_a_scale_change_that_keeps_the_ratio_leaves_page_content_untouched(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL,"
            " ScaleFactor2 REAL);"
            "INSERT INTO BidPages VALUES (20, 1, 0.125, 12.0);"
            "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER,"
            " Position BLOB);"
            "INSERT INTO BidTakeoffs VALUES (1, 1, 20, '1;2;3;4');"
        )
        self.assertIs(ops.save_page_scale("t.mdb", "20", 0.25, 24.0), True)
        self.assertEqual(
            connection.execute("SELECT Position FROM BidTakeoffs").fetchall(),
            [("1;2;3;4",)],
        )

    def test_overlay_rectangles_of_any_positive_size_follow_a_scale_change(self):
        from ost_visualizer.infrastructure.mdb.components.overlay_rect import (
            parse_overlay_rect_storage,
            serialize_overlay_rect_storage,
        )

        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL,"
            " ScaleFactor2 REAL, OverlayRect TEXT, OverlayOffsetX REAL,"
            " OverlayOffsetY REAL);"
            "INSERT INTO BidPages VALUES (20, 1, 0.125, 12.0, '"
            + serialize_overlay_rect_storage((0.5, 0.5, 0.5, 0.5))
            + "', 0.5, 0.5);"
        )
        self.assertIs(ops.save_page_scale("t.mdb", "20", 0.25, 12.0), True)
        rect, x, y = connection.execute(
            "SELECT OverlayRect, OverlayOffsetX, OverlayOffsetY FROM BidPages"
        ).fetchone()
        for found, expected in zip(parse_overlay_rect_storage(rect), (0.25,) * 4):
            self.assertAlmostEqual(found, expected)
        self.assertEqual((x, y), (0.25, 0.25))

    def test_image_adjustments_need_every_adjustment_column_and_one_row_per_page(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Rotation INTEGER,"
            " FlipX INTEGER, FlipY INTEGER, Invert INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1, 0, 0, 0, 0);"
        )
        record = self.failure_of(
            lambda: ops.save_page_image_adjustments(
                "t.mdb", ["20"], 90, True, False, True, False
            )
        )
        self.assertRegex(str(record.exc_info[1]), "Missing BidPages.Bitonal")
        self.assertEqual(
            connection.execute("SELECT Rotation FROM BidPages").fetchall(), [(0,)]
        )
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Rotation INTEGER,"
            " FlipX INTEGER, FlipY INTEGER, Invert INTEGER, Bitonal INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1, 0, 0, 0, 0, 0), (20, 1, 0, 0, 0, 0, 0);"
        )
        self.failure_of(
            lambda: ops.save_page_image_adjustments(
                "t.mdb", ["20"], 90, True, False, True, False
            )
        )
        self.assertEqual(
            connection.execute("SELECT Rotation FROM BidPages").fetchall(),
            [(0,), (0,)],
        )

    def test_image_rotations_that_are_not_quarter_turns_are_stored_as_zero(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Rotation INTEGER,"
            " FlipX INTEGER, FlipY INTEGER, Invert INTEGER, Bitonal INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1, 9, 0, 0, 0, 0);"
        )
        for rotation, expected in (
            (0, 0),
            (90, 90),
            (180, 180),
            (270, 270),
            (-90, 270),
            (450, 90),
            (None, 0),
            (45, 0),
            (1, 0),
            (361, 0),
            (-1, 0),
        ):
            with self.subTest(rotation=rotation):
                self.assertIs(
                    ops.save_page_image_adjustments(
                        "t.mdb", ["20"], rotation, False, False, False, False
                    ),
                    True,
                )
                self.assertEqual(
                    connection.execute("SELECT Rotation FROM BidPages").fetchone(),
                    (expected,),
                )

    def test_page_area_settings_are_required_and_the_page_must_be_unambiguous(self):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1);"
        )
        record = self.failure_of(lambda: ops.save_page_area("t.mdb", "20", "10"))
        self.assertEqual(
            str(record.exc_info[1]),
            "This OST database does not support page area settings.",
        )
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1), (20, 1);"
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidAreas VALUES (10, 1);"
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER,"
            " BidAreaUID INTEGER, BidAreaSelected INTEGER);"
        )
        self.failure_of(lambda: ops.save_page_area("t.mdb", "20", "10"))
        self.assertEqual(
            connection.execute("SELECT COUNT(*) FROM BidPageSettings").fetchone(),
            (0,),
        )
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1);"
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER,"
            " BidAreaUID INTEGER);"
        )
        record = self.failure_of(lambda: ops.save_page_area("t.mdb", "20", ""))
        self.assertRegex(
            str(record.exc_info[1]), "Missing BidPageSettings.BidAreaSelected"
        )

    def test_selecting_an_area_without_a_settings_uid_column_replaces_the_selection(
        self,
    ):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1);"
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidAreas VALUES (10, 1), (11, 1);"
            "CREATE TABLE BidPageSettings (BidPageUID INTEGER, BidAreaUID INTEGER,"
            " BidAreaSelected INTEGER);"
            "INSERT INTO BidPageSettings VALUES (20, 10, 2), (20, 99, 0);"
        )
        self.assertIs(ops.save_page_area("t.mdb", "20", "11"), True)
        self.assertEqual(
            connection.execute(
                "SELECT BidAreaUID, BidAreaSelected FROM BidPageSettings ORDER BY 1"
            ).fetchall(),
            [(11, 2), (99, 0)],
        )

    def test_an_area_update_reuses_the_first_selected_row_when_none_has_the_requested_mode(
        self,
    ):
        ops, connection = self.ops(
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidPages VALUES (20, 1);"
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER);"
            "INSERT INTO BidAreas VALUES (10, 1), (11, 1);"
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER,"
            " BidAreaUID INTEGER, BidAreaSelected INTEGER);"
            "INSERT INTO BidPageSettings VALUES (7, 20, 10, 3), (8, 20, 10, NULL),"
            " (9, 21, 10, 2);"
        )
        self.assertIs(ops.save_page_area("t.mdb", "20", "11"), True)
        self.assertEqual(
            connection.execute(
                "SELECT UID, BidPageUID, BidAreaUID, BidAreaSelected "
                "FROM BidPageSettings ORDER BY UID"
            ).fetchall(),
            [(7, 20, 11, 2), (8, 20, 10, None), (9, 21, 10, 2)],
        )


class PageOperationsRelationshipTests(unittest.TestCase):
    @staticmethod
    def _page_area_connection(settings_rows):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("INSERT INTO Bids (UID, JobName) VALUES (1, 'Bid')")
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.executemany(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (?, 1, ?)",
            ((10, "Area 1"), (11, "Area 2"), (12, "Area 3")),
        )
        connection.executemany(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (?, 20, ?, ?)",
            settings_rows,
        )
        return connection

    @staticmethod
    def _page_settings(connection):
        return connection.execute(
            "SELECT UID, BidAreaUID, BidAreaSelected FROM BidPageSettings "
            "WHERE BidPageUID=20 ORDER BY UID"
        ).fetchall()

    def test_page_area_save_retains_highest_uid_when_duplicates_tie(self):
        connection = self._page_area_connection(((30, 10, 2), (31, 12, 2), (32, 10, 0)))
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertIs(writer.save_page_area("target.mdb", "20", "11"), True)
        self.assertEqual(self._page_settings(connection), [(31, 11, 2), (32, 10, 0)])

    def test_page_area_save_prefers_exact_selection_value_over_other_selected_rows(
        self,
    ):
        connection = self._page_area_connection(((40, 10, 1), (41, 12, 2)))
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertIs(writer.save_page_area("target.mdb", "20", "11"), True)
        self.assertEqual(self._page_settings(connection), [(41, 11, 2)])

    def test_page_area_save_unassigned_replaces_selection_with_null_area_marker(self):
        connection = self._page_area_connection(((50, 10, 2), (51, 12, 1), (52, 10, 0)))
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertIs(writer.save_page_area("target.mdb", "20", "0"), True)
        self.assertEqual(self._page_settings(connection), [(51, None, 1), (52, 10, 0)])

    def test_save_page_area_replaces_selection_without_violating_unique_selected_index(
        self,
    ):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, unique_page_selected=True
        )
        connection.execute("INSERT INTO Bids (UID, JobName) VALUES (1, 'Bid')")
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (10, 1, 'Area 1')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (11, 1, 'Area 2')"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (1, 20, 10, 1)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (2, 20, 10, 2)"
        )
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertIs(writer.save_page_area("target.mdb", "20", "11"), True)
        rows = connection.execute(
            "SELECT UID, BidAreaUID, BidAreaSelected FROM BidPageSettings "
            "WHERE BidPageUID=20 ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(2, 11, 2)])

    def test_save_page_area_rejects_area_from_another_bid(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(
            connection, unique_page_selected=True
        )
        connection.executemany(
            "INSERT INTO Bids (UID, JobName) VALUES (?, ?)",
            ((1, "First"), (2, "Second")),
        )
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (10, 2, 'Other')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (11, 1, 'Own')"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (1, 20, 11, 2)"
        )
        connection.commit()
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                _import_export_support__SqliteMdbWriter(connection).save_page_area(
                    "target.mdb", "20", "10"
                ),
                False,
            )
        self.assertIn("BidAreas.UID=10 does not belong to Bids.UID=1", logs.output[0])
        self.assertEqual(
            connection.execute(
                "SELECT UID, BidPageUID, BidAreaUID, BidAreaSelected "
                "FROM BidPageSettings"
            ).fetchall(),
            [(1, 20, 11, 2)],
        )

    def test_save_page_area_normalizes_duplicate_physical_uids(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("DROP TABLE BidPageSettings")
        connection.execute(
            "CREATE TABLE BidPageSettings ("
            "UID INTEGER, BidPageUID INTEGER, BidAreaUID INTEGER, "
            "BidTypAreaUID INTEGER, BidAreaSelected INTEGER)"
        )
        connection.execute("INSERT INTO Bids (UID, JobName) VALUES (1, 'Bid')")
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (10, 1, 'Area 1')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (11, 1, 'Area 2')"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (5, 20, 10, 1)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidAreaSelected) VALUES (5, 20, 11, 2)"
        )
        self.assertIs(
            _import_export_support__SqliteMdbWriter(connection).save_page_area(
                "target.mdb", "20", "11"
            ),
            True,
        )
        rows = connection.execute(
            "SELECT UID, BidAreaUID, BidAreaSelected FROM BidPageSettings "
            "WHERE BidPageUID=20"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:], (11, 2))

    def test_clear_page_area_preserves_nonselected_page_settings_rows(self):
        connection = sqlite3.connect(":memory:")
        _import_export_support__create_import_schema(connection)
        connection.execute("INSERT INTO Bids (UID, JobName) VALUES (1, 'Bid')")
        connection.execute(
            "INSERT INTO BidPages (UID, BidUID, Name) VALUES (20, 1, 'Sheet')"
        )
        connection.execute(
            "INSERT INTO BidAreas (UID, BidUID, Name) VALUES (10, 1, 'Area')"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidTypAreaUID, BidAreaSelected) "
            "VALUES (1, 20, 10, 77, 0)"
        )
        connection.execute(
            "INSERT INTO BidPageSettings "
            "(UID, BidPageUID, BidAreaUID, BidTypAreaUID, BidAreaSelected) "
            "VALUES (2, 20, 10, NULL, 2)"
        )
        self.assertIs(
            _import_export_support__SqliteMdbWriter(connection).save_page_area(
                "target.mdb", "20", ""
            ),
            True,
        )
        rows = connection.execute(
            "SELECT UID, BidAreaUID, BidTypAreaUID, BidAreaSelected "
            "FROM BidPageSettings WHERE BidPageUID=20 ORDER BY UID"
        ).fetchall()
        self.assertEqual(rows, [(1, 10, 77, 0)])


class PageScalePositionSerializationTests(unittest.TestCase):
    def test_page_scale_rescale_writes_text_payload_for_text_position_tables(self):
        ops = _scale_position_support__PageOps()
        cursor = _scale_position_support__Cursor(
            "BidTexts",
            [SimpleNamespace(UID=7, Position=encode_position([1.0, 2.0, 3.0, 4.0]))],
        )
        ops._rescale_page_positions(
            cursor, _scale_position_support__Schema("BidTexts"), page_uid=3, factor=0.5
        )
        self.assertEqual(cursor.updates, [("0.5;1.0;1.5;2.0\n", 7)])

    def test_page_scale_rescale_writes_binary_payload_for_binary_position_tables(self):
        ops = _scale_position_support__PageOps()
        cursor = _scale_position_support__Cursor(
            "BidTakeoffs",
            [SimpleNamespace(UID=7, Position=encode_position([1.0, 2.0, 3.0, 4.0]))],
        )
        ops._rescale_page_positions(
            cursor,
            _scale_position_support__Schema("BidTakeoffs"),
            page_uid=3,
            factor=0.5,
        )
        self.assertEqual(cursor.updates, [(b"0.5;1;1.5;2\n", 7)])

    def test_legend_xml_coordinates_rescale_without_changing_metadata(self):
        import xml.etree.ElementTree as ET

        payload = (
            b'<Legends dX="30.804" dY="1022.679" Visible="255">\n'
            b'<Legend ConditionUID="11334" dX="30.804" dY="30.804" '
            b'Visible="1" FontSize="12" FontName="Arial" FontColor="0" FontStyle="0"/>\n'
            b"</Legends>\n"
        )
        ops = _scale_position_support__PageOps()
        cursor = _scale_position_support__Cursor(
            "BidLegends", [SimpleNamespace(UID=11641, Position=payload)]
        )
        ops._rescale_page_positions(
            cursor, _scale_position_support__Schema("BidLegends"), 11376, 2.0
        )
        self.assertEqual(ops.logger.warnings, [])
        self.assertEqual(len(cursor.updates), 1)
        scaled, uid = cursor.updates[0]
        self.assertIsInstance(scaled, bytes)
        self.assertEqual(uid, 11641)
        before, after = ET.fromstring(payload), ET.fromstring(scaled)
        self.assertEqual(
            [element.tag for element in after.iter()],
            [element.tag for element in before.iter()],
        )
        for old, new in zip(before.iter(), after.iter()):
            self.assertEqual(set(new.attrib), set(old.attrib))
            for key, value in old.attrib.items():
                if key in ("dX", "dY"):
                    self.assertAlmostEqual(
                        float(new.attrib[key]) / 256, float(value) / 128
                    )
                else:
                    self.assertEqual(new.attrib[key], value)
        self.assertEqual(
            after.attrib, {"dX": "61.608", "dY": "2045.358", "Visible": "255"}
        )
        self.assertEqual(after.find("Legend").attrib["dX"], "61.608")
        self.assertEqual(after.find("Legend").attrib["dY"], "61.608")

    def test_invalid_legend_xml_rejects_scale_instead_of_partially_rewriting_it(self):
        from xml.etree.ElementTree import ParseError

        for payload in (b"<Legends", b'<Other dX="1"/>', b'<Legends dX="NaN"/>'):
            with self.subTest(payload=payload):
                ops = _scale_position_support__PageOps()
                cursor = _scale_position_support__Cursor(
                    "BidLegends", [SimpleNamespace(UID=11641, Position=payload)]
                )
                with self.assertRaises((ValueError, ParseError)):
                    ops._rescale_page_positions(
                        cursor,
                        _scale_position_support__Schema("BidLegends"),
                        11376,
                        2.0,
                    )
                self.assertEqual(cursor.updates, [])

    def test_scale_preserves_annotation_rotation(self):
        for table in ("BidTexts", "BidAnnotationRects", "BidAnnotationOvals"):
            with self.subTest(table=table):
                ops = _scale_position_support__PageOps()
                cursor = _scale_position_support__Cursor(
                    table,
                    [
                        SimpleNamespace(
                            UID=7,
                            Position=serialize_position_for_table(
                                table, [1, 2, 3, 4, 0.5]
                            ),
                        )
                    ],
                )
                ops._rescale_page_positions(
                    cursor, _scale_position_support__Schema(table), 3, 2.0
                )
                self.assertEqual(
                    parse_position_storage(cursor.updates[0][0]), [2, 4, 6, 8, 0.5]
                )

    def test_all_annotation_rotation_fields_survive_scale(self):
        from ost_visualizer.domain.entities.annotation import BidAnnotation
        from ost_visualizer.infrastructure.database.annotation_storage import (
            ANNOTATION_TYPE_BY_TABLE,
        )

        for table, kind in ANNOTATION_TYPE_BY_TABLE.items():
            with self.subTest(table=table):
                position = (
                    [0.123456789, 100, 200, 300, 400]
                    if kind == "ink"
                    else [100, 200, 300, 400, 0.123456789]
                )
                payload = (";".join(map(str, position)) + "\n").encode("latin-1")
                cursor = _scale_position_support__Cursor(
                    table, [SimpleNamespace(UID=7, Position=payload)]
                )
                _scale_position_support__PageOps()._rescale_page_positions(
                    cursor, _scale_position_support__Schema(table), 3, 2
                )
                scaled = parse_position_storage(cursor.updates[0][0])
                self.assertEqual(
                    BidAnnotation("7", kind, position=scaled).stored_rotation_rad,
                    BidAnnotation("7", kind, position=position).stored_rotation_rad,
                )
                rotation_index = 0 if kind == "ink" else 4
                self.assertEqual(
                    scaled,
                    [
                        value if index == rotation_index else value * 2
                        for index, value in enumerate(position)
                    ],
                )

    def test_large_coordinate_round_trip_retains_three_decimal_precision(self):
        payload = b"123456.789;987654.321\n"
        for _ in range(10):
            for factor in (2.0, 0.5):
                cursor = _scale_position_support__Cursor(
                    "BidTakeoffs", [SimpleNamespace(UID=7, Position=payload)]
                )
                _scale_position_support__PageOps()._rescale_page_positions(
                    cursor, _scale_position_support__Schema("BidTakeoffs"), 3, factor
                )
                payload = cursor.updates[0][0]
        self.assertEqual(parse_position_storage(payload), [123456.789, 987654.321])

    def test_curved_takeoff_offset_is_a_length_not_a_trailing_angle(self):
        cursor = _scale_position_support__Cursor(
            "BidTakeoffs", [SimpleNamespace(UID=7, Position=b"1;2;3;4;5;6;7\n")]
        )
        _scale_position_support__PageOps()._rescale_page_positions(
            cursor, _scale_position_support__Schema("BidTakeoffs"), 3, 2
        )
        self.assertEqual(
            parse_position_storage(cursor.updates[0][0]), [2, 4, 6, 8, 10, 12, 14]
        )

    def test_unverified_position_tables_leave_empty_payloads_untouched(self):
        for table in ("BidComments", "BidTypGroupViews"):
            for payload in (None, "", b""):
                with self.subTest(table=table, payload=payload):
                    ops = _scale_position_support__PageOps()
                    cursor = _scale_position_support__Cursor(
                        table, [SimpleNamespace(UID=7, Position=payload)]
                    )
                    ops._rescale_page_positions(
                        cursor, _scale_position_support__Schema(table), 3, 2.0
                    )
                    self.assertEqual(cursor.updates, [])
                    self.assertEqual(ops.logger.warnings, [])

    def test_unverified_position_tables_do_not_rewrite_unparseable_payloads(self):
        # This characterizes the existing parser, not a valid OST payload format.
        for table, payload in (
            ("BidComments", "not-a-numeric-position"),
            ("BidTypGroupViews", b"not-a-numeric-position"),
        ):
            with self.subTest(table=table):
                ops = _scale_position_support__PageOps()
                cursor = _scale_position_support__Cursor(
                    table, [SimpleNamespace(UID=7, Position=payload)]
                )
                ops._rescale_page_positions(
                    cursor, _scale_position_support__Schema(table), 3, 2.0
                )
                self.assertEqual(cursor.updates, [])
                self.assertEqual(
                    ops.logger.warnings,
                    [
                        f"Skipping page-scale rescale for {table} UID 7 "
                        "because Position is not numeric"
                    ],
                )
                self.assertEqual(cursor.rows[0].Position, payload)

    def test_page_scale_rescale_skips_unparseable_position_payload(self):
        ops = _scale_position_support__PageOps()
        cursor = _scale_position_support__Cursor(
            "BidTexts", [SimpleNamespace(UID=8, Position="\ua0e3\ue2b8\ub7b8")]
        )
        ops._rescale_page_positions(
            cursor, _scale_position_support__Schema("BidTexts"), page_uid=3, factor=0.5
        )
        self.assertEqual(cursor.updates, [])
        self.assertEqual(
            ops.logger.warnings,
            [
                "Skipping page-scale rescale for BidTexts UID 8 "
                "because Position is not numeric"
            ],
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


_PAGE_COLUMNS = (
    "UID INTEGER, BidUID INTEGER, Name TEXT, Width REAL, Height REAL, "
    "ScaleFactor1 REAL, ScaleFactor2 REAL, ImagePath TEXT, OverlayImagePath TEXT, "
    "OverlayRect TEXT, OverlayOffsetX REAL, OverlayOffsetY REAL, "
    "OverlayRotation REAL, OverlayResized INTEGER, DeskewRotationOverlay REAL, "
    "[Show] INTEGER, ZoomFac REAL, CurrentX REAL, CurrentY REAL, Rotation INTEGER, "
    "FlipX INTEGER, FlipY INTEGER, Invert INTEGER, Bitonal INTEGER"
)


def _page_row(uid, bid_uid, name):
    return (
        "INSERT INTO BidPages VALUES "
        f"({uid}, {bid_uid}, '{name}', 42.0, 30.0, 0.125, 12.0, 'plan.pdf', '', '', "
        "0.0, 0.0, 0.0, 0, 0.0, 0, 1.0, 5.0, 6.0, 0, 0, 0, 0, 0)"
    )


class PageOperationsRealContractTests(unittest.TestCase):
    """Page saves run against sqlite with the production column contract."""

    ops_class = RealContractOps

    def database(self, *extra):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            f"CREATE TABLE BidPages ({_PAGE_COLUMNS})",
            _page_row(20, 1, "Sheet A"),
            _page_row(21, 1, "Sheet B"),
            _page_row(30, 2, "Other bid"),
            "CREATE TABLE BidAreas (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidAreas VALUES (10, 1)",
            "CREATE TABLE BidPageSettings (UID INTEGER, BidPageUID INTEGER, "
            "BidAreaUID INTEGER, BidAreaSelected INTEGER)",
            *extra,
        )
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    @staticmethod
    def pages(conn, columns="*"):
        return conn.execute(f"SELECT {columns} FROM BidPages ORDER BY UID").fetchall()

    def test_page_name_is_saved_for_the_requested_page_only(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(ops.save_page_name("x.mdb", "20", "Renamed"), True)
        self.assertEqual(
            self.pages(conn, "UID, Name"),
            [(20, "Renamed"), (21, "Sheet B"), (30, "Other bid")],
        )

    def test_page_name_without_a_name_column_fails_and_is_logged(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (20, 1)",
        )
        self.addCleanup(conn.close)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(self.ops_class(conn).save_page_name("x.mdb", "20", "N"), False)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to save page name for page 20 in x.mdb",
        )
        self.assertRegex(str(logs.records[0].exc_info[1]), "Missing BidPages.Name")

    def test_page_view_state_is_saved_for_the_requested_page_only(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(ops.save_page_view_state("x.mdb", "20", 2.5, 10.0, -20.0), True)
        self.assertEqual(
            self.pages(conn, "UID, ZoomFac, CurrentX, CurrentY"),
            [(20, 2.5, 10.0, -20.0), (21, 1.0, 5.0, 6.0), (30, 1.0, 5.0, 6.0)],
        )
        self.assertEqual(ops.skips, [])

    def test_page_view_state_on_a_database_without_view_columns_is_a_reported_noop(
        self,
    ):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ZoomFac REAL)",
            "INSERT INTO BidPages VALUES (20, 1, 1.0)",
        )
        self.addCleanup(conn.close)
        ops = self.ops_class(conn)
        with self.assertNoLogs("test", level="WARNING"):
            self.assertIs(ops.save_page_view_state("x.mdb", "20", 3.0, 1.0, 2.0), True)
        self.assertEqual(
            conn.execute("SELECT ZoomFac FROM BidPages").fetchall(), [(3.0,)]
        )
        self.assertEqual(
            ops.skips,
            [
                ("BidPages", "CurrentX", "save_page_view_state"),
                ("BidPages", "CurrentY", "save_page_view_state"),
            ],
        )
        conn.execute("ALTER TABLE BidPages DROP COLUMN ZoomFac")
        ops = self.ops_class(conn)
        with self.assertNoLogs("test", level="WARNING"):
            self.assertIs(ops.save_page_view_state("x.mdb", "20", 3.0, 1.0, 2.0), True)
        self.assertEqual(
            ops.skips,
            [
                ("BidPages", "ZoomFac", "save_page_view_state"),
                ("BidPages", "CurrentX", "save_page_view_state"),
                ("BidPages", "CurrentY", "save_page_view_state"),
            ],
        )

    def test_page_show_mode_is_stored_as_an_integer_for_one_page(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(ops.save_page_show_mode("x.mdb", "20", "2"), True)
        self.assertEqual(
            self.pages(conn, "UID, [Show]"), [(20, 2), (21, 0), (30, 0)]
        )
        self.assertEqual(
            conn.execute("SELECT typeof([Show]) FROM BidPages WHERE UID=20").fetchone(),
            ("integer",),
        )

    def test_page_show_mode_without_a_show_column_fails_and_is_logged(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (20, 1)",
        )
        self.addCleanup(conn.close)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(self.ops_class(conn).save_page_show_mode("x.mdb", "20", 1), False)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to save page show mode for page 20 in x.mdb",
        )
        self.assertRegex(str(logs.records[0].exc_info[1]), "Missing BidPages.Show")

    def test_invert_and_bitonal_flags_use_access_boolean_values_independently(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(ops.save_page_invert("x.mdb", "20", True), True)
        self.assertEqual(
            self.pages(conn, "UID, Invert, Bitonal"),
            [(20, -1, 0), (21, 0, 0), (30, 0, 0)],
        )
        self.assertIs(ops.save_page_bitonal("x.mdb", "20", True), True)
        self.assertEqual(
            self.pages(conn, "UID, Invert, Bitonal"),
            [(20, -1, -1), (21, 0, 0), (30, 0, 0)],
        )
        self.assertIs(ops.save_page_invert("x.mdb", "20", False), True)
        self.assertIs(ops.save_page_bitonal("x.mdb", "20", 0), True)
        self.assertEqual(
            self.pages(conn, "UID, Invert, Bitonal"),
            [(20, 0, 0), (21, 0, 0), (30, 0, 0)],
        )

    def test_invert_and_bitonal_on_a_database_without_the_columns_report_false(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (20, 1)",
        )
        self.addCleanup(conn.close)
        ops = self.ops_class(conn)
        with self.assertNoLogs("test", level="WARNING"):
            self.assertIs(ops.save_page_invert("x.mdb", "20", True), False)
            self.assertIs(ops.save_page_bitonal("x.mdb", "20", True), False)
        self.assertEqual(
            ops.skips,
            [
                ("BidPages", "Invert", "save_page_invert"),
                ("BidPages", "Bitonal", "save_page_bitonal"),
            ],
        )

    def test_every_page_save_logs_its_own_failure_and_changes_nothing(self):
        conn = self.database()
        before = self.pages(conn)
        calls = (
            (
                "save_page_scale",
                lambda ops: ops.save_page_scale("x.mdb", "99", 0.25, 12.0),
                "Failed to save page scale for page 99 in x.mdb",
            ),
            (
                "save_page_name",
                lambda ops: ops.save_page_name("x.mdb", "99", "N"),
                "Failed to save page name for page 99 in x.mdb",
            ),
            (
                "save_page_view_state",
                lambda ops: ops.save_page_view_state("x.mdb", "99", 1.0, 2.0, 3.0),
                "Failed to save page view state for page 99 in x.mdb",
            ),
            (
                "save_page_show_mode",
                lambda ops: ops.save_page_show_mode("x.mdb", "99", 1),
                "Failed to save page show mode for page 99 in x.mdb",
            ),
            (
                "save_page_overlay_image",
                lambda ops: ops.save_page_overlay_image("x.mdb", "99", "o.pdf"),
                "Failed to save page overlay image for page 99 in x.mdb",
            ),
            (
                "save_page_overlay_rect",
                lambda ops: ops.save_page_overlay_rect(
                    "x.mdb", "99", (0.0, 0.0, 5.0, 5.0)
                ),
                "Failed to save page overlay rect for page 99 in x.mdb",
            ),
            (
                "save_page_invert",
                lambda ops: ops.save_page_invert("x.mdb", "99", True),
                "Failed to save page invert state for page 99 in x.mdb",
            ),
            (
                "save_page_bitonal",
                lambda ops: ops.save_page_bitonal("x.mdb", "99", True),
                "Failed to save page bitonal state for page 99 in x.mdb",
            ),
            (
                "save_page_image_adjustments",
                lambda ops: ops.save_page_image_adjustments(
                    "x.mdb", ["99"], 90, True, True, True, True
                ),
                "Failed to save page image adjustments in x.mdb",
            ),
            (
                "save_page_area",
                lambda ops: ops.save_page_area("x.mdb", "99", "10"),
                "Failed to save page area for page 99 in x.mdb",
            ),
        )
        for label, call, message in calls:
            with self.subTest(save=label):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(call(self.ops_class(conn)), False)
                self.assertEqual(len(logs.records), 1)
                self.assertEqual(logs.records[0].getMessage(), message)
                self.assertRegex(
                    str(logs.records[0].exc_info[1]),
                    r"BidPages has no row for UID 99",
                )
                self.assertEqual(self.pages(conn), before)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM BidPageSettings").fetchone(),
                    (0,),
                )

    def test_fatal_mutation_errors_propagate_instead_of_returning_false(self):
        conn = self.database()
        ops = _PropagatingContractOps(conn)
        calls = (
            lambda: ops.save_page_scale("x.mdb", "99", 0.25, 12.0),
            lambda: ops.save_page_name("x.mdb", "99", "N"),
            lambda: ops.save_page_view_state("x.mdb", "99", 1.0, 2.0, 3.0),
            lambda: ops.save_page_show_mode("x.mdb", "99", 1),
            lambda: ops.save_page_overlay_image("x.mdb", "99", "o.pdf"),
            lambda: ops.save_page_overlay_rect("x.mdb", "99", (0.0, 0.0, 5.0, 5.0)),
            lambda: ops.save_page_invert("x.mdb", "99", True),
            lambda: ops.save_page_bitonal("x.mdb", "99", True),
            lambda: ops.save_page_image_adjustments(
                "x.mdb", ["99"], 90, True, True, True, True
            ),
            lambda: ops.save_page_area("x.mdb", "99", "10"),
        )
        for index, call in enumerate(calls):
            with self.subTest(call=index):
                with self.assertRaisesRegex(
                    MissingBidOwnedUidError, "BidPages has no row for UID 99"
                ):
                    call()

    def test_page_saves_reject_malformed_page_uids_before_touching_rows(self):
        conn = self.database()
        before = self.pages(conn)
        for bad_uid in ("abc", "0", "-5", ""):
            with self.subTest(page_uid=bad_uid):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(
                        self.ops_class(conn).save_page_name("x.mdb", bad_uid, "N"),
                        False,
                    )
                self.assertIsInstance(logs.records[0].exc_info[1], MalformedBidOwnedUidError)
                self.assertEqual(self.pages(conn), before)

    def test_image_adjustments_refuse_pages_of_different_bids_and_empty_targets(self):
        conn = self.database()
        before = self.pages(conn)
        for page_uids, error in (
            (["20", "30"], IncoherentBidOwnedScopeError),
            ([], MissingBidOwnedUidError),
        ):
            with self.subTest(page_uids=page_uids):
                with self.assertLogs("test", level="ERROR") as logs:
                    self.assertIs(
                        self.ops_class(conn).save_page_image_adjustments(
                            "x.mdb", page_uids, 90, True, True, True, True
                        ),
                        False,
                    )
                self.assertIsInstance(logs.records[0].exc_info[1], error)
                self.assertEqual(self.pages(conn), before)

    def test_image_adjustments_store_access_booleans_for_each_flag(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(
            ops.save_page_image_adjustments(
                "x.mdb", ["20", "21"], 270, True, False, False, True
            ),
            True,
        )
        self.assertEqual(
            self.pages(conn, "UID, Rotation, FlipX, FlipY, Invert, Bitonal"),
            [(20, 270, -1, 0, 0, -1), (21, 270, -1, 0, 0, -1), (30, 0, 0, 0, 0, 0)],
        )
        self.assertIs(
            ops.save_page_image_adjustments(
                "x.mdb", ["20"], 0, False, True, True, False
            ),
            True,
        )
        self.assertEqual(
            self.pages(conn, "UID, Rotation, FlipX, FlipY, Invert, Bitonal"),
            [(20, 0, 0, -1, -1, 0), (21, 270, -1, 0, 0, -1), (30, 0, 0, 0, 0, 0)],
        )

    def test_overlay_image_replacement_persists_every_overlay_owned_column(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(
            ops.save_page_overlay_image("x.mdb", "20", r"C:\Plans\overlay.pdf"), True
        )
        self.assertEqual(
            self.pages(
                conn,
                "UID, OverlayImagePath, OverlayRect, OverlayOffsetX, OverlayOffsetY, "
                "OverlayRotation, OverlayResized, DeskewRotationOverlay, [Show]",
            ),
            [
                (
                    20,
                    r"C:\Plans\overlay.pdf",
                    "0.000000,0.000000,4032.000000,2880.000000",
                    0.0,
                    0.0,
                    0.0,
                    0,
                    0.0,
                    0,
                ),
                (21, "", "", 0.0, 0.0, 0.0, 0, 0.0, 0),
                (30, "", "", 0.0, 0.0, 0.0, 0, 0.0, 0),
            ],
        )
        conn.execute("UPDATE BidPages SET OverlayRect='1,2,3,4' WHERE UID=20")
        self.assertIs(
            ops.save_page_overlay_image("x.mdb", "20", "c:/plans/OVERLAY.pdf"), True
        )
        self.assertEqual(
            conn.execute("SELECT OverlayRect FROM BidPages WHERE UID=20").fetchone(),
            ("1,2,3,4",),
        )
        self.assertIs(ops.save_page_overlay_image("x.mdb", "20", ""), True)
        self.assertEqual(
            conn.execute(
                "SELECT OverlayImagePath, OverlayRect, [Show] FROM BidPages "
                "WHERE UID=20"
            ).fetchone(),
            ("", "", 0),
        )

    def test_overlay_image_on_a_page_without_dimensions_fails_without_writing(self):
        conn = self.database()
        conn.execute("UPDATE BidPages SET Width=0 WHERE UID=20")
        conn.commit()
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                self.ops_class(conn).save_page_overlay_image("x.mdb", "20", "o.pdf"),
                False,
            )
        self.assertRegex(
            str(logs.records[0].exc_info[1]), "Page dimensions must be positive"
        )
        self.assertEqual(
            conn.execute("SELECT OverlayImagePath FROM BidPages WHERE UID=20").fetchone(),
            ("",),
        )

    def test_overlay_rect_is_stored_with_translation_columns(self):
        conn = self.database()
        ops = self.ops_class(conn)
        self.assertIs(
            ops.save_page_overlay_rect("x.mdb", "20", (-1.5, 2.25, 100.0, 50.0)), True
        )
        self.assertEqual(
            self.pages(conn, "UID, OverlayRect, OverlayOffsetX, OverlayOffsetY"),
            [
                (20, "-1.500000,2.250000,100.000000,50.000000", -1.5, 2.25),
                (21, "", 0.0, 0.0),
                (30, "", 0.0, 0.0),
            ],
        )
        conn.execute("UPDATE BidPages SET ScaleFactor1=0 WHERE UID=21")
        conn.commit()
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                ops.save_page_overlay_rect("x.mdb", "21", (0.0, 0.0, 1.0, 1.0)), False
            )
        self.assertRegex(
            str(logs.records[0].exc_info[1]),
            "Page 21 requires finite positive scale factors",
        )

    def test_overlay_image_skips_overlay_columns_the_database_lacks(self):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, Width REAL, "
            "Height REAL, ScaleFactor1 REAL, ScaleFactor2 REAL, OverlayImagePath TEXT, "
            "ImagePath TEXT)",
            "INSERT INTO BidPages VALUES (20, 1, 42.0, 30.0, 0.125, 12.0, '', 'a.pdf')",
        )
        self.addCleanup(conn.close)
        ops = self.ops_class(conn)
        with self.assertNoLogs("test", level="WARNING"):
            self.assertIs(ops.save_page_overlay_image("x.mdb", "20", "o.pdf"), True)
        self.assertEqual(
            conn.execute("SELECT OverlayImagePath FROM BidPages").fetchall(),
            [("o.pdf",)],
        )
        self.assertEqual(
            ops.skips,
            [
                ("BidPages", column, "save_page_overlay_image")
                for column in (
                    "OverlayRect",
                    "OverlayOffsetX",
                    "OverlayOffsetY",
                    "OverlayRotation",
                    "OverlayResized",
                    "DeskewRotationOverlay",
                )
            ],
        )

    def test_image_adjustments_reject_a_bare_string_of_page_uids(self):
        conn = self.database(_page_row(1, 1, "One"), _page_row(2, 1, "Two"))
        before = self.pages(conn)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                self.ops_class(conn).save_page_image_adjustments(
                    "x.mdb", "12", 90, True, True, True, True
                ),
                False,
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]), "Invalid BidPages UID collection: '12'"
        )
        self.assertEqual(self.pages(conn), before)

    def test_page_area_selection_is_saved_through_the_production_contract(self):
        conn = self.database()
        ops = self.ops_class(conn)
        select = "SELECT UID, BidPageUID, BidAreaUID, BidAreaSelected FROM BidPageSettings"
        self.assertIs(ops.save_page_area("x.mdb", "20", "10"), True)
        self.assertEqual(conn.execute(select).fetchall(), [(1, 20, 10, 2)])
        self.assertIs(ops.save_page_area("x.mdb", "20", "0"), True)
        self.assertEqual(conn.execute(select).fetchall(), [(1, 20, None, 1)])
        self.assertIs(ops.save_page_area("x.mdb", "20", ""), True)
        self.assertEqual(conn.execute(select).fetchall(), [])
        conn.execute("INSERT INTO BidPageSettings VALUES (7, 20, 10, 0)")
        self.assertIs(ops.save_page_area("x.mdb", "20", "10"), True)
        self.assertEqual(
            conn.execute(select + " ORDER BY UID").fetchall(),
            [(7, 20, 10, 0), (8, 20, 10, 2)],
        )

    def overlay_rect_database(self, extra_columns=""):
        conn = contract_db(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL, "
            f"ScaleFactor2 REAL{extra_columns})",
            "INSERT INTO BidPages (UID, BidUID, ScaleFactor1, ScaleFactor2) "
            "VALUES (20, 1, 0.125, 12.0)",
        )
        self.addCleanup(conn.close)
        return conn

    def test_overlay_rect_without_any_overlay_columns_has_nothing_to_write(self):
        conn = self.overlay_rect_database()
        ops = self.ops_class(conn)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(
                ops.save_page_overlay_rect("x.mdb", "20", (0.0, 0.0, 5.0, 5.0)), False
            )
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to save page overlay rect for page 20 in x.mdb",
        )
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "This OST database has no writable columns for save_page_overlay_rect.",
        )

    def test_overlay_rect_reports_the_translation_columns_it_had_to_skip(self):
        conn = self.overlay_rect_database(", OverlayRect TEXT")
        ops = self.ops_class(conn)
        self.assertIs(
            ops.save_page_overlay_rect("x.mdb", "20", (1.0, 2.0, 5.0, 5.0)), True
        )
        self.assertEqual(
            conn.execute("SELECT OverlayRect FROM BidPages").fetchall(),
            [("1.000000,2.000000,5.000000,5.000000",)],
        )
        self.assertEqual(
            ops.skips,
            [
                ("BidPages", "OverlayOffsetX", "save_page_overlay_rect"),
                ("BidPages", "OverlayOffsetY", "save_page_overlay_rect"),
            ],
        )


_SCALED_TABLES = (
    "BidTakeoffs",
    "BidDimensions",
    "BidArrows",
    "BidCallOuts",
    "BidAnnotationPolygons",
    "BidAnnotationClouds",
    "BidAnnotationRects",
    "BidAnnotationOvals",
    "BidAnnoInk",
    "BidTexts",
    "BidComments",
    "BidTypGroupViews",
)
# BidALines and BidHighlights are deliberately never created: absent tables are
# skipped without ending the scan of the tables that follow them.
_LEGEND_XML = (
    '<Legends dX="30.804" dY="1022.679" Visible="255">'
    '<Legend ConditionUID="11334" dX="30.804" dY="30.804" Visible="1"/></Legends>'
)


class PageScaleChangeContentTests(unittest.TestCase):
    """save_page_scale rewrites page content in one transaction (sqlite end state)."""

    def database(self, *, overlay_columns=True, broken_legend=False):
        ddl = [
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER, ScaleFactor1 REAL, "
            "ScaleFactor2 REAL"
            + (
                ", OverlayRect TEXT, OverlayOffsetX REAL, OverlayOffsetY REAL)"
                if overlay_columns
                else ")"
            ),
            "INSERT INTO BidPages VALUES (20, 1, 0.125, 12.0"
            + (", '10,20,30,40', 10.0, 20.0)" if overlay_columns else ")"),
            "INSERT INTO BidPages VALUES (21, 1, 0.125, 12.0"
            + (", '', 0.0, 0.0)" if overlay_columns else ")"),
        ]
        for table in _SCALED_TABLES:
            position = "5;6;7;8;0.5" if table == "BidTexts" else "10;20;30;40"
            ddl.append(
                f"CREATE TABLE [{table}] (UID INTEGER, BidPageUID INTEGER, Position BLOB)"
            )
            # Unusable rows come first so that skipping them must not end the table.
            ddl.append(f"INSERT INTO [{table}] VALUES (3, 20, NULL)")
            ddl.append(f"INSERT INTO [{table}] VALUES (4, 20, 'not-numeric')")
            ddl.append(f"INSERT INTO [{table}] VALUES (1, 20, '{position}')")
            ddl.append(f"INSERT INTO [{table}] VALUES (2, 21, '{position}')")
        ddl.append("INSERT INTO BidTexts VALUES (5, 20, '1;2;3;4;0.5;9;10')")
        ddl.append(
            "CREATE TABLE BidLegends (UID INTEGER, BidPageUID INTEGER, Position BLOB)"
        )
        ddl.append("INSERT INTO BidLegends VALUES (3, 20, NULL)")
        ddl.append(
            "INSERT INTO BidLegends VALUES (1, 20, "
            + ("X'3C4C6567656E6473'" if broken_legend else f"'{_LEGEND_XML}'")
            + ")"
        )
        ddl.append(f"INSERT INTO BidLegends VALUES (4, 20, '{_LEGEND_XML}')")
        ddl.append(f"INSERT INTO BidLegends VALUES (2, 21, '{_LEGEND_XML}')")
        # Tables that must be skipped: each lacks exactly one required column.
        ddl.append("CREATE TABLE BidHotLinks (UID INTEGER, Position BLOB)")
        ddl.append("INSERT INTO BidHotLinks VALUES (1, '1;2;3;4')")
        ddl.append("CREATE TABLE BidNamedViews (UID INTEGER, BidPageUID INTEGER)")
        ddl.append("INSERT INTO BidNamedViews VALUES (1, 20)")
        conn = contract_db(*ddl)
        conn.commit()
        self.addCleanup(conn.close)
        return conn

    def save_scale(self, ops, page_uid, sf1, sf2, *, rewrites=True):
        """Run save_page_scale; return (result, warning messages)."""
        if not rewrites:
            with self.assertNoLogs("test", level="WARNING"):
                return ops.save_page_scale("x.mdb", page_uid, sf1, sf2), []
        with self.assertLogs("test", level="WARNING") as logs:
            result = ops.save_page_scale("x.mdb", page_uid, sf1, sf2)
        return result, [
            record.getMessage()
            for record in logs.records
            if record.levelname == "WARNING"
        ]

    @staticmethod
    def positions(conn, table):
        return [
            (uid, page, parse_position_storage(position))
            for uid, page, position in conn.execute(
                f"SELECT UID, BidPageUID, Position FROM [{table}] ORDER BY UID"
            )
        ]

    def test_scale_change_rewrites_only_the_requested_pages_content_tables(self):
        conn = self.database()
        ops = _TransactionalContractOps(conn)
        result, warnings = self.save_scale(ops, "20", 0.0625, 12.0)
        self.assertIs(result, True)
        self.assertEqual(
            sorted(warnings),
            sorted(
                f"Skipping page-scale rescale for {table} UID 4 because Position "
                "is not numeric"
                for table in _SCALED_TABLES
            ),
        )
        for table in _SCALED_TABLES:
            with self.subTest(table=table):
                expected = (
                    [5.0 * 2, 6.0 * 2, 7.0 * 2, 8.0 * 2, 0.5]
                    if table == "BidTexts"
                    else [20.0, 40.0, 60.0, 80.0]
                )
                original = (
                    [5.0, 6.0, 7.0, 8.0, 0.5]
                    if table == "BidTexts"
                    else [10.0, 20.0, 30.0, 40.0]
                )
                rows = [
                    (1, 20, expected),
                    (2, 21, original),
                    (3, 20, []),
                    (4, 20, []),
                ]
                if table == "BidTexts":
                    rows.append((5, 20, [2.0, 4.0, 6.0, 8.0, 0.5, 9.0, 10.0]))
                self.assertEqual(self.positions(conn, table), rows)
                self.assertEqual(
                    conn.execute(
                        f"SELECT Position FROM [{table}] WHERE UID=4"
                    ).fetchone(),
                    ("not-numeric",),
                )
        self.assertEqual(
            conn.execute("SELECT UID, Position FROM BidHotLinks").fetchall(),
            [(1, "1;2;3;4")],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, ScaleFactor1, ScaleFactor2 FROM BidPages ORDER BY UID"
            ).fetchall(),
            [(20, 0.0625, 12.0), (21, 0.125, 12.0)],
        )
        legend = conn.execute(
            "SELECT UID, Position FROM BidLegends ORDER BY UID"
        ).fetchall()
        self.assertEqual([row[0] for row in legend], [1, 2, 3, 4])
        for scaled in (legend[0][1], legend[3][1]):
            self.assertIn(b'dX="61.608"', scaled)
            self.assertIn(b'dY="2045.358"', scaled)
        self.assertEqual(legend[1], (2, _LEGEND_XML))
        self.assertEqual(legend[2], (3, None))

    def test_scale_change_scales_the_overlay_rectangle_and_translation_together(self):
        conn = self.database()
        ops = _TransactionalContractOps(conn)
        self.assertIs(self.save_scale(ops, "20", 0.0625, 12.0)[0], True)
        self.assertEqual(
            conn.execute(
                "SELECT UID, OverlayRect, OverlayOffsetX, OverlayOffsetY FROM BidPages "
                "ORDER BY UID"
            ).fetchall(),
            [
                (20, "20.000000,40.000000,60.000000,80.000000", 20.0, 40.0),
                (21, "", 0.0, 0.0),
            ],
        )

    def test_scale_change_without_overlay_columns_still_rewrites_positions(self):
        conn = self.database(overlay_columns=False)
        ops = _TransactionalContractOps(conn)
        self.assertIs(self.save_scale(ops, "20", 0.25, 12.0)[0], True)
        self.assertEqual(
            self.positions(conn, "BidTakeoffs")[0], (1, 20, [5.0, 10.0, 15.0, 20.0])
        )
        self.assertEqual(ops.skips, [])

    def test_scale_change_below_the_epsilon_does_not_rewrite_content(self):
        conn = self.database()
        ops = _TransactionalContractOps(conn)
        result, _ = self.save_scale(
            ops, "20", 0.125, 12.0 * (1 + 1e-12), rewrites=False
        )
        self.assertIs(result, True)
        self.assertEqual(
            self.positions(conn, "BidTakeoffs")[0], (1, 20, [10.0, 20.0, 30.0, 40.0])
        )
        self.assertEqual(
            conn.execute("SELECT OverlayRect FROM BidPages WHERE UID=20").fetchone(),
            ("10,20,30,40",),
        )
        self.assertEqual(
            conn.execute("SELECT ScaleFactor2 FROM BidPages WHERE UID=20").fetchone(),
            (12.0 * (1 + 1e-12),),
        )

    def test_rescale_threshold_is_exclusive_at_the_epsilon_itself(self):
        from unittest import mock
        from ost_visualizer.infrastructure.mdb.components import page_operations

        # Ratios are 12/0.125 = 96 and 18/0.125 = 144, so the factor is exactly 1.5.
        for epsilon, rewritten in ((0.5, False), (0.4999, True)):
            with self.subTest(epsilon=epsilon):
                conn = self.database()
                with mock.patch.object(page_operations, "SCALE_EPSILON", epsilon):
                    result, _ = self.save_scale(
                        _TransactionalContractOps(conn),
                        "20",
                        0.125,
                        18.0,
                        rewrites=rewritten,
                    )
                self.assertIs(result, True)
                self.assertEqual(
                    self.positions(conn, "BidTakeoffs")[0][2],
                    [15.0, 30.0, 45.0, 60.0] if rewritten else [10.0, 20.0, 30.0, 40.0],
                )

    def test_failed_content_rewrite_rolls_back_every_earlier_write(self):
        conn = self.database(broken_legend=True)
        ops = _TransactionalContractOps(conn)
        with self.assertLogs("test", level="ERROR") as logs:
            self.assertIs(ops.save_page_scale("x.mdb", "20", 0.0625, 12.0), False)
        self.assertEqual(
            logs.records[0].getMessage(),
            "Failed to save page scale for page 20 in x.mdb",
        )
        for table in _SCALED_TABLES:
            with self.subTest(table=table):
                self.assertEqual(
                    [row[2] for row in self.positions(conn, table) if row[0] == 1],
                    [[5.0, 6.0, 7.0, 8.0, 0.5] if table == "BidTexts" else [10.0, 20.0, 30.0, 40.0]],
                )
        self.assertEqual(
            conn.execute(
                "SELECT ScaleFactor1, OverlayRect, OverlayOffsetX FROM BidPages "
                "WHERE UID=20"
            ).fetchone(),
            (0.125, "10,20,30,40", 10.0),
        )
