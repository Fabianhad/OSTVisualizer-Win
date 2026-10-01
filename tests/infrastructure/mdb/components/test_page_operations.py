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
        self.assertTrue(
            _ParameterLimitedSqliteOps(conn).save_page_image_adjustments(
                "large.mdb",
                [str(uid) for uid in range(1, row_count + 1)],
                90,
                True,
                False,
                True,
                False,
            )
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
        self.assertTrue(
            ops.save_page_image_adjustments(
                "bid.mdb", ["1", "2"], 450, False, True, False, True
            )
        )
        self.assertTrue(
            ops.save_page_image_adjustments(
                "bid.mdb", ["4"], 45, False, False, False, False
            )
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
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0))
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
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
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
                self.assertFalse(
                    ops.save_page_scale(
                        "bid.mdb",
                        "11",
                        scale_factor1,
                        scale_factor2,
                    )
                )
                self.assertEqual(ops.rescale_calls, [])
                self.assertFalse(
                    any(
                        query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
                        for query, _args in ops.conn.cursor_obj.calls
                    )
                )
                self.assertIs(ops.conn.exit_args[-1][0], ValueError)

    def test_page_scale_change_rescales_overlay_rect_and_offsets(self):
        ops = _path_support__OverlayScaleOps()
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
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
        self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
        self.assertEqual(ops.position_rescales, [(11, 1.5)])
        self.assertEqual(ops.updates, [])

    def test_page_scale_change_leaves_absent_or_zero_size_overlay_rect_untouched(self):
        for overlay_rect in (None, "", "0.0,0.0,0.0,0.0", "5,5,0,100", "5,5,100,0"):
            with self.subTest(overlay_rect=overlay_rect):
                ops = _path_support__OverlayScaleOps(overlay_rect=overlay_rect)
                self.assertTrue(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
                self.assertEqual(ops.position_rescales, [(11, 1.5)])
                self.assertEqual(ops.updates, [])

    def test_page_scale_change_rejects_malformed_overlay_rect_before_any_write(self):
        for overlay_rect in ("0,0,2688", "0,0,abc,1920", "0,0,-1,1920"):
            with self.subTest(overlay_rect=overlay_rect):
                ops = _path_support__OverlayScaleOps(overlay_rect=overlay_rect)
                self.assertFalse(ops.save_page_scale("bid.mdb", "11", 0.125, 12.0))
                self.assertEqual(ops.position_rescales, [])
                self.assertEqual(ops.updates, [])
                self.assertFalse(
                    any(
                        query.startswith("UPDATE [BidPages] SET [ScaleFactor1]")
                        for query, _args in ops.conn.cursor_obj.calls
                    )
                )
                self.assertIs(ops.conn.exit_args[-1][0], ValueError)

    def test_page_scale_position_failure_aborts_scale_update(self):
        ops = _path_support__FailingPositionScaleOps(old_sf1=0.125, old_sf2=12.0)
        self.assertFalse(ops.save_page_scale("bid.mdb", "11", 0.25, 12.0))
        self.assertFalse(
            any(
                "UPDATE [BidPages] SET [ScaleFactor1]" in query
                for query, _args in ops.conn.cursor_obj.calls
            )
        )
        self.assertIs(ops.conn.exit_args[-1][0], pyodbc.Error)

    def test_saving_page_overlay_image_generates_full_page_overlay_rect(self):
        ops = _path_support__PageOverlayOps()
        success = ops.save_page_overlay_image(
            "bid.mdb",
            "11",
            r"C:\OCS Documents\OST\overlay.pdf",
        )
        self.assertTrue(success)
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
        self.assertTrue(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            )
        )
        self.assertEqual(ops.updates[0]["values"]["Show"], 1)

    def test_removing_page_overlay_image_clears_all_overlay_owned_storage(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"C:\Plans\overlay.pdf"
        )
        self.assertTrue(ops.save_page_overlay_image("bid.mdb", "11", ""))
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
        self.assertTrue(ops.save_page_overlay_image("bid.mdb", "11", path))
        self.assertEqual(ops.updates, [])

    def test_saving_same_overlay_image_with_other_separators_preserves_rectangle(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path="C:/OCS Documents/OST/overlay.pdf"
        )
        self.assertTrue(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            )
        )
        self.assertEqual(ops.updates, [])

    def test_saving_same_overlay_image_with_other_case_preserves_rectangle(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"c:\ocs documents\ost\OVERLAY.PDF"
        )
        self.assertTrue(
            ops.save_page_overlay_image(
                "bid.mdb",
                "11",
                r"C:\OCS Documents\OST\overlay.pdf",
            )
        )
        self.assertEqual(ops.updates, [])

    def test_replacing_overlay_with_different_image_resets_overlay_owned_state(self):
        ops = _path_support__PageOverlayOps(
            current_overlay_path=r"C:\Plans\old_overlay.pdf"
        )
        self.assertTrue(
            ops.save_page_overlay_image("bid.mdb", "11", r"C:\Plans\replacement.pdf")
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
        self.assertTrue(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (-1.103146, -2.5, 2686.161423, 1919.474692),
            )
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
                self.assertFalse(
                    ops.save_page_overlay_rect(
                        "bid.mdb",
                        "11",
                        (0.0, 0.0, 100.0, 100.0),
                    )
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
                self.assertFalse(
                    ops.save_page_overlay_rect("bid.mdb", "11", overlay_rect)
                )
                self.assertEqual(ops.updates, [])
                self.assertEqual(ops.conn.enter_count, 0)

    def test_saving_overlay_rect_rejects_missing_page(self):
        ops = _path_support__PageOverlayOps(page_exists=False)
        self.assertFalse(
            ops.save_page_overlay_rect(
                "bid.mdb",
                "11",
                (0.0, 0.0, 100.0, 100.0),
            )
        )
        self.assertEqual(ops.updates, [])
        self.assertIs(ops.conn.exit_args[-1][0], ValueError)


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
        self.assertTrue(writer.save_page_area("target.mdb", "20", "11"))
        self.assertEqual(self._page_settings(connection), [(31, 11, 2), (32, 10, 0)])

    def test_page_area_save_prefers_exact_selection_value_over_other_selected_rows(
        self,
    ):
        connection = self._page_area_connection(((40, 10, 1), (41, 12, 2)))
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertTrue(writer.save_page_area("target.mdb", "20", "11"))
        self.assertEqual(self._page_settings(connection), [(41, 11, 2)])

    def test_page_area_save_unassigned_replaces_selection_with_null_area_marker(self):
        connection = self._page_area_connection(((50, 10, 2), (51, 12, 1), (52, 10, 0)))
        writer = _import_export_support__SqliteMdbWriter(connection)
        self.assertTrue(writer.save_page_area("target.mdb", "20", "0"))
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
        self.assertTrue(writer.save_page_area("target.mdb", "20", "11"))
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
            self.assertFalse(
                _import_export_support__SqliteMdbWriter(connection).save_page_area(
                    "target.mdb", "20", "10"
                )
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
        self.assertTrue(
            _import_export_support__SqliteMdbWriter(connection).save_page_area(
                "target.mdb", "20", "11"
            )
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
        self.assertTrue(
            _import_export_support__SqliteMdbWriter(connection).save_page_area(
                "target.mdb", "20", ""
            )
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
