import logging
import sqlite3
import unittest
from contextlib import contextmanager
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.application.dtos.paste_ref_remap_dto import PasteRefRemap
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
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
    _ParameterLimitedSqliteConnectionWrapper,
    _ParameterLimitedSqliteCursorWrapper,
    _ParameterLimitedSqliteOps,
    _SqliteAnnotationOps,
    _SqliteConnectionWrapper,
    _SqliteCursorWrapper,
    _SqliteDuplicateOps,
    _SqliteMdbOps,
    _SqliteRow,
    _SqliteSchema,
)
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.infrastructure.mdb.components.serialization import (
    encode_position,
    parse_position_storage,
    serialize_position_for_table,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _DimensionWriteOps as _dimension_support__DimensionWriteOps,
    _Logger as _dimension_support__Logger,
    _Schema as _dimension_support__Schema,
    _SqliteConnectionWrapper as _dimension_support__SqliteConnectionWrapper,
    _SqliteCursorWrapper as _dimension_support__SqliteCursorWrapper,
)


class AnnotationOperationsPersistenceTests(unittest.TestCase):
    def test_large_annotation_delete_uses_bounded_statements(self):
        class LimitedAnnotationOps(
            AnnotationOperationsMixin, _ParameterLimitedSqliteOps
        ):
            pass

        row_count = 256
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidAnnotationRects (UID INTEGER, BidUID INTEGER)")
        conn.executemany(
            "INSERT INTO BidAnnotationRects VALUES (?, 1)",
            ((uid,) for uid in range(1, row_count + 1)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertTrue(
            LimitedAnnotationOps(conn).delete_annotations(
                "large.mdb",
                [(str(uid), "rect") for uid in range(1, row_count + 1)],
            )
        )
        self.assertEqual(
            sum(
                sql.lstrip().upper().startswith("DELETE FROM [BIDANNOTATIONRECTS]")
                for sql in statements
            ),
            6,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Bids").fetchone()[0], 1)

    def test_annotation_delete_chunk_boundaries_remove_exactly_the_requested_rows(
        self,
    ):
        class LimitedAnnotationOps(
            AnnotationOperationsMixin, _ParameterLimitedSqliteOps
        ):
            pass

        for row_count, expected_delete_statements in (
            (1, 1),
            (50, 1),
            (51, 2),
            (100, 2),
        ):
            with self.subTest(row_count=row_count):
                conn = sqlite3.connect(":memory:")
                conn.execute("CREATE TABLE Bids (UID INTEGER)")
                conn.execute("INSERT INTO Bids VALUES (1)")
                conn.execute(
                    "CREATE TABLE BidAnnotationRects (UID INTEGER, BidUID INTEGER)"
                )
                conn.executemany(
                    "INSERT INTO BidAnnotationRects VALUES (?, 1)",
                    ((uid,) for uid in range(1, 201)),
                )
                statements = []
                conn.set_trace_callback(statements.append)
                self.assertTrue(
                    LimitedAnnotationOps(conn).delete_annotations(
                        "large.mdb",
                        [(str(uid), "rect") for uid in range(1, row_count + 1)],
                    )
                )
                self.assertEqual(
                    sum(
                        sql.lstrip()
                        .upper()
                        .startswith("DELETE FROM [BIDANNOTATIONRECTS]")
                        for sql in statements
                    ),
                    expected_delete_statements,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT MIN(UID), COUNT(*) FROM BidAnnotationRects"
                    ).fetchone(),
                    (row_count + 1, 200 - row_count),
                )

    def test_bulk_annotation_insert_scans_each_table_uid_space_once(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Position BLOB, "
            "Color INTEGER, Width INTEGER)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        result = _SqliteAnnotationOps(conn).insert_annotations(
            "large.mdb",
            "1",
            [
                InsertAnnotationSpec(
                    page_uid="3",
                    annotation_type="rect",
                    position=[0.0, 0.0, 1.0, 1.0],
                    color="#000000",
                    width=1.0,
                )
                for _index in range(100)
            ],
        )
        max_uid_queries = [
            sql for sql in statements if sql.lstrip().upper().startswith("SELECT MAX")
        ]
        self.assertEqual(result, [str(uid) for uid in range(1, 101)])
        self.assertEqual(len(max_uid_queries), 1)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT UID), MIN(UID), MAX(UID) "
                "FROM BidAnnotationRects"
            ).fetchone(),
            (100, 100, 1, 100),
        )

    def test_annotation_insert_rejects_orphan_bid_before_identity_allocation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (20, 99)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Position BLOB, "
            "Color INTEGER, Width INTEGER)"
        )
        statements = []
        conn.set_trace_callback(statements.append)
        with self.assertLogs("test", level="ERROR") as logs:
            result = _SqliteAnnotationOps(conn).insert_annotations(
                "malformed.mdb",
                "99",
                [
                    InsertAnnotationSpec(
                        page_uid="20",
                        annotation_type="rect",
                        position=[0.0, 0.0, 1.0, 1.0],
                        color="#000000",
                        width=1.0,
                    )
                ],
            )
        self.assertEqual(result, [])
        self.assertIn("Bids has no row for UID 99", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )
        self.assertEqual(
            [
                sql
                for sql in statements
                if sql.lstrip().upper().startswith(("SELECT MAX", "INSERT"))
            ],
            [],
        )

    def test_named_view_rename_writes_bid_named_views_name_only(self):
        class FakeSchema:
            def optional_table_missing(self, _table):
                return False

            def column_exists(self, _table, column):
                return column in {"UID", "BidUID", "Name"}

        class FakeCursor:
            def __init__(self):
                self.calls = []
                self.validation_rows = []

            def execute(self, sql, *params):
                if sql.startswith("SELECT [UID], [BidUID] FROM ["):
                    self.validation_rows = [(param, 1) for param in params]
                    return
                if sql.startswith("SELECT [UID] FROM ["):
                    self.validation_rows = [(param,) for param in params]
                    return
                self.calls.append((sql, params))

            def fetchall(self):
                return list(self.validation_rows)

        class FakeConnection:
            def __init__(self):
                self.cursor_instance = FakeCursor()

            def cursor(self):
                return self.cursor_instance

        class FakeWriter(AnnotationOperationsMixin):
            def __init__(self):
                self.connection = FakeConnection()
                self.required_columns = []
                self.logger = logging.getLogger("test")

            @contextmanager
            def _connection(self, _db_path):
                yield self.connection

            def _schema(self, _conn):
                return FakeSchema()

            def _require_write_columns(self, _schema, table, columns):
                self.required_columns.append((table, columns))

            @staticmethod
            def _record_caught_mutation_error(_exc):
                return False

        writer = FakeWriter()
        self.assertTrue(
            writer.save_annotation_text_properties(
                "job.mdb",
                [("42", "namedview", {"Text": "New View", "FontName": "Calibri"})],
            )
        )
        self.assertEqual(
            writer.required_columns,
            [
                ("BidNamedViews", ("UID", "BidUID")),
                ("BidNamedViews", ("UID", "Name")),
            ],
        )
        self.assertEqual(len(writer.connection.cursor_instance.calls), 1)
        sql, params = writer.connection.cursor_instance.calls[0]
        self.assertEqual(sql, "UPDATE [BidNamedViews] SET [Name]=? WHERE [UID]=?")
        self.assertEqual(params, ("New View", 42))


class BidDimensionAnnotationTests(unittest.TestCase):
    def test_annotation_position_save_rejects_duplicate_uid_before_mutation(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, Position BLOB)"
        )
        original_a = encode_position([0.0, 0.0, 1.0, 1.0])
        original_b = encode_position([2.0, 2.0, 3.0, 3.0])
        conn.executemany(
            "INSERT INTO BidNamedViews VALUES (7, 1, ?)",
            ((original_a,), (original_b,)),
        )
        conn.commit()
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertFalse(
            _dimension_support__DimensionWriteOps(conn).save_annotation_positions(
                "malformed.mdb",
                [("7", "namedview", [4.0, 4.0, 8.0, 8.0, 0.0])],
            )
        )
        self.assertEqual(
            [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")],
            [],
        )
        self.assertEqual(
            conn.execute(
                "SELECT Position FROM BidNamedViews ORDER BY rowid"
            ).fetchall(),
            [(original_a,), (original_b,)],
        )

    def test_annotation_position_save_rejects_cross_bid_batch_atomically(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, Position BLOB)"
        )
        original_a = encode_position([0.0, 0.0, 1.0, 1.0, 0.0])
        original_b = encode_position([2.0, 2.0, 3.0, 3.0, 0.0])
        conn.executemany(
            "INSERT INTO BidNamedViews VALUES (?, ?, ?)",
            ((7, 1, original_a), (8, 2, original_b)),
        )
        conn.commit()
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertFalse(
            _dimension_support__DimensionWriteOps(conn).save_annotation_positions(
                "malformed.mdb",
                [
                    ("7", "namedview", [4.0, 4.0, 8.0, 8.0, 0.0]),
                    ("8", "namedview", [9.0, 9.0, 12.0, 12.0, 0.0]),
                ],
            )
        )
        self.assertEqual(
            [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")],
            [],
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidNamedViews ORDER BY UID").fetchall(),
            [(original_a,), (original_b,)],
        )

    def test_annotation_position_save_rejects_cross_table_bid_batch_atomically(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, Position BLOB)"
        )
        conn.execute(
            "CREATE TABLE BidAnnotationRects "
            "(UID INTEGER, BidUID INTEGER, Position BLOB)"
        )
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        original_view = encode_position([0.0, 0.0, 1.0, 1.0, 0.0])
        original_rect = encode_position([2.0, 2.0, 3.0, 3.0])
        conn.execute("INSERT INTO BidNamedViews VALUES (7, 1, ?)", (original_view,))
        conn.execute(
            "INSERT INTO BidAnnotationRects VALUES (8, 2, ?)", (original_rect,)
        )
        conn.commit()
        statements = []
        conn.set_trace_callback(statements.append)
        self.assertFalse(
            _dimension_support__DimensionWriteOps(conn).save_annotation_positions(
                "malformed.mdb",
                [
                    ("7", "namedview", [4.0, 4.0, 8.0, 8.0, 0.0]),
                    ("8", "rect", [9.0, 9.0, 12.0, 12.0]),
                ],
            )
        )
        self.assertEqual(
            [sql for sql in statements if sql.lstrip().upper().startswith("UPDATE")],
            [],
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidNamedViews").fetchall(),
            [(original_view,)],
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchall(),
            [(original_rect,)],
        )

    def test_annotation_batch_with_unsupported_type_inserts_nothing(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            """
            CREATE TABLE BidAnnotationRects (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Position BLOB,
                Color INTEGER,
                Width INTEGER
            )
            """
        )
        conn.commit()
        specs = [
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="rect",
                position=[1.0, 2.0, 3.0, 4.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="unsupported",
                position=[5.0, 6.0],
                color="#00ff00",
                width=1.0,
            ),
        ]
        new_uids = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb", "1", specs
        )
        self.assertEqual(new_uids, [])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0],
            0,
        )

    def test_annotation_batch_failure_after_first_insert_rolls_back_every_row(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidLayerUID INTEGER, Position BLOB, Color INTEGER, Width INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidAnnotationOvals ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
            "BidLayerUID INTEGER, Position BLOB, Color INTEGER)"
        )
        conn.commit()
        statements = []
        conn.set_trace_callback(statements.append)
        specs = [
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type=annotation_type,
                position=[1.0, 2.0, 3.0, 4.0],
                color="#ff0000",
                width=2.0,
            )
            for annotation_type in ("rect", "oval")
        ]
        new_uids = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb", "1", specs
        )
        self.assertEqual(new_uids, [])
        self.assertTrue(
            any(
                sql.lstrip().upper().startswith("INSERT INTO [BIDANNOTATIONRECTS]")
                for sql in statements
            )
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationOvals").fetchone()[0], 0
        )

    def test_annotation_insert_returns_uids_in_spec_order_across_interleaved_tables(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidLayers VALUES (9, 1)")
        for table in ("BidAnnotationRects", "BidAnnotationOvals"):
            conn.execute(
                f"CREATE TABLE {table} ("
                "UID INTEGER PRIMARY KEY, BidUID INTEGER, BidPageUID INTEGER, "
                "BidLayerUID INTEGER, Position BLOB, Color INTEGER, Width INTEGER)"
            )
        conn.execute(
            "INSERT INTO BidAnnotationRects (UID, BidUID, BidPageUID) VALUES (5, 1, 3)"
        )
        positions = {
            "rect-a": [1.0, 1.0, 2.0, 2.0],
            "oval-b": [3.0, 3.0, 4.0, 4.0],
            "rect-c": [5.0, 5.0, 6.0, 6.0],
            "oval-d": [7.0, 7.0, 8.0, 8.0],
        }
        specs = [
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type=name.split("-")[0],
                position=position,
                color="#010203",
                width=3.0,
                layer_uid="9" if name == "oval-d" else "",
            )
            for name, position in positions.items()
        ]
        new_uids = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb", "1", specs
        )
        self.assertEqual(new_uids, ["6", "1", "7", "2"])
        for table, uid, name in (
            ("BidAnnotationRects", 6, "rect-a"),
            ("BidAnnotationOvals", 1, "oval-b"),
            ("BidAnnotationRects", 7, "rect-c"),
            ("BidAnnotationOvals", 2, "oval-d"),
        ):
            with self.subTest(table=table, uid=uid):
                row = conn.execute(
                    f"SELECT BidUID, BidPageUID, BidLayerUID, Color, Width, Position "
                    f"FROM {table} WHERE UID=?",
                    (uid,),
                ).fetchone()
                self.assertEqual(
                    row[:5],
                    (1, 3, 9 if name == "oval-d" else None, 0x030201, 3),
                )
                self.assertEqual(parse_position_storage(row[5]), positions[name])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 3
        )

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_dimension_label_style_persists_to_bid_dimensions_font_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO BidDimensions
                (UID, BidUID, FontName, FontColor, FontSize, FontBold, FontItalic, FontUnderline)
            VALUES (7, 1, 'Arial', 0, 10, 0, 0, 0)
            """
        )
        ops = _dimension_support__DimensionWriteOps(conn)
        self.assertTrue(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "7",
                        "dimension",
                        {
                            "FontName": "Calibri",
                            "FontColor": 0x332211,
                            "FontSize": 18,
                            "FontBold": True,
                            "FontItalic": True,
                            "FontUnderline": True,
                        },
                    )
                ],
            )
        )
        row = conn.execute(
            """
            SELECT FontName, FontColor, FontSize, FontBold, FontItalic, FontUnderline
              FROM BidDimensions
             WHERE UID=7
            """
        ).fetchone()
        self.assertEqual(row, ("Calibri", 0x332211, 18, 1, 1, 1))

    def test_dimension_text_property_defaults_and_hex_color_only_touch_target_row(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO BidDimensions VALUES (?, 1, 'Times', 5, 30, 1, 1, 1)",
            ((7,), (8,)),
        )
        self.assertTrue(
            _dimension_support__DimensionWriteOps(conn).save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "7",
                        "dimension",
                        {"FontName": "", "FontColor": "#112233", "FontSize": 0},
                    )
                ],
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, FontName, FontColor, FontSize, FontBold, FontItalic, "
                "FontUnderline FROM BidDimensions ORDER BY UID"
            ).fetchall(),
            [(7, "Arial", 0x332211, 10, 0, 0, 0), (8, "Times", 5, 30, 1, 1, 1)],
        )

    def test_text_and_callout_property_updates_write_encoded_name_and_font_columns(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        for table in ("BidTexts", "BidCallOuts"):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    UID INTEGER PRIMARY KEY,
                    BidUID INTEGER,
                    Name BLOB,
                    FontName TEXT,
                    FontColor INTEGER,
                    FontSize INTEGER,
                    FontBold INTEGER,
                    FontItalic INTEGER,
                    FontUnderline INTEGER,
                    TextAlign INTEGER
                )
                """
            )
            conn.executemany(
                f"INSERT INTO {table} VALUES (?, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
                ((1,), (2,)),
            )
        self.assertTrue(
            _dimension_support__DimensionWriteOps(conn).save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "1",
                        "text",
                        {
                            "Text": "H\u00e9llo",
                            "FontName": "Calibri",
                            "FontColor": "#112233",
                            "FontSize": 20,
                            "FontBold": True,
                            "TextAlign": 2,
                        },
                    ),
                    ("1", "callout", {"Text": "Note"}),
                    ("1", "bogus", {"Text": "ignored"}),
                ],
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, FontName, FontColor, FontSize, FontBold, "
                "FontItalic, FontUnderline, TextAlign FROM BidTexts ORDER BY UID"
            ).fetchall(),
            [
                (
                    1,
                    "H\u00e9llo".encode("latin-1"),
                    "Calibri",
                    0x332211,
                    20,
                    1,
                    0,
                    0,
                    2,
                ),
                (2, b"\x00", "Times", 5, 30, 1, 1, 1, 3),
            ],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, FontName, FontColor, FontSize, FontBold, "
                "FontItalic, FontUnderline, TextAlign FROM BidCallOuts ORDER BY UID"
            ).fetchall(),
            [
                (1, b"Note", "Arial", 0, 12, 0, 0, 0, 0),
                (2, b"\x00", "Times", 5, 30, 1, 1, 1, 3),
            ],
        )

    def test_placeable_annotation_shapes_insert_through_annotation_write_path(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            """
            CREATE TABLE BidALines (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                Color INTEGER,
                Width INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidArrows (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                Color INTEGER,
                Width INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAnnoInk (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                Color INTEGER,
                Position BLOB,
                Width INTEGER
            )
            """
        )
        for table in (
            "BidAnnotationRects",
            "BidAnnotationOvals",
            "BidAnnotationPolygons",
            "BidAnnotationClouds",
        ):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    UID INTEGER PRIMARY KEY,
                    BidUID INTEGER,
                    BidPageUID INTEGER,
                    BidLayerUID INTEGER,
                    Position BLOB,
                    Color INTEGER,
                    Width INTEGER
                )
                """
            )
        conn.execute(
            """
            CREATE TABLE BidHighlights (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Color INTEGER,
                Position BLOB
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidTexts (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Name BLOB,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER,
                TextAlign INTEGER,
                Position TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidNamedViews (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                Name TEXT,
                Position BLOB,
                Color INTEGER,
                Origin INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO BidNamedViews "
            "(UID, BidUID, BidPageUID, Name) VALUES (1, 1, 3, 'Existing')"
        )
        conn.execute(
            """
            CREATE TABLE BidHotLinks (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidPageViewUID INTEGER,
                BidLayerUID INTEGER,
                Color INTEGER,
                Position BLOB
            )
            """
        )
        specs = [
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="line",
                position=[0.0, 0.0, 10.0, 10.0],
                color="#ff0000",
                width=2.0,
                properties={"BidTakeoffFromUID": "", "BidTakeoffToUID": ""},
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="arrow",
                position=[1.0, 2.0, 13.0, 14.0],
                color="#ff0000",
                width=2.0,
                properties={"BidTakeoffFromUID": "", "BidTakeoffToUID": ""},
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="dimension",
                position=[1.0, 2.0, 13.0, 14.0],
                color="#ff0000",
                width=3.0,
                properties={
                    "BidTakeoffFromUID": "",
                    "BidTakeoffToUID": "",
                    "FontName": "Arial",
                    "FontColor": "#ff0000",
                    "FontSize": 48,
                    "FontBold": False,
                    "FontItalic": False,
                    "FontUnderline": False,
                },
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="rect",
                position=[1.0, 2.0, 13.0, 14.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="oval",
                position=[2.0, 3.0, 14.0, 15.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="polygon",
                position=[0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="cloud",
                position=[1.0, 1.0, 13.0, 1.0, 7.0, 9.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="ink",
                position=[0.0, 0.0, 5.0, 5.0, 10.0, 0.0],
                color="#ff0000",
                width=2.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="highlight",
                position=[3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0],
                color="#ffff00",
                width=9.0,
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="text",
                position=[7.0, 8.0, 12.0, 12.0],
                color="#336699",
                width=4.0,
                properties={
                    "Text": "",
                    "FontName": "Arial",
                    "FontColor": 0x996633,
                    "FontSize": 72,
                    "FontBold": False,
                    "FontItalic": False,
                    "FontUnderline": False,
                    "TextAlign": 0,
                },
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="namedview",
                position=[1.0, 2.0, 13.0, 2.0, 13.0, 14.0, 1.0, 14.0],
                color="#008000",
                width=2.0,
                properties={"Text": "Lobby"},
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="hotlink",
                position=[5.0, 6.0],
                color="#ff0000",
                width=2.0,
                properties={"BidPageViewUID": "1"},
            ),
        ]
        new_uids = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb", "1", specs
        )
        self.assertEqual(new_uids, ["1"] * 10 + ["2", "1"])
        expected_tables = {
            "BidALines": "line",
            "BidArrows": "arrow",
            "BidAnnoInk": "ink",
            "BidAnnotationRects": "rect",
            "BidAnnotationOvals": "oval",
            "BidAnnotationPolygons": "polygon",
            "BidAnnotationClouds": "cloud",
        }
        spec_positions = {spec.annotation_type: spec.position for spec in specs}
        for table, annotation_type in expected_tables.items():
            with self.subTest(annotation_type=annotation_type):
                rows = conn.execute(
                    f"SELECT BidUID, BidPageUID, Color, Width, Position FROM {table}"
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][:4], (1, 3, 255, 2))
                self.assertEqual(
                    rows[0][4],
                    serialize_position_for_table(
                        table, spec_positions[annotation_type]
                    ),
                )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchone()[0],
            b"1.0;2.0;13.0;14.0\n",
        )
        for table in ("BidALines", "BidArrows"):
            with self.subTest(takeoff_references=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT BidTakeoffFromUID, BidTakeoffToUID FROM {table}"
                    ).fetchall(),
                    [(None, None)],
                )
        highlight_row = conn.execute(
            "SELECT BidUID, BidPageUID, Color, Position FROM BidHighlights"
        ).fetchone()
        self.assertEqual(highlight_row[:3], (1, 3, 0x00FFFF))
        self.assertEqual(
            highlight_row[3],
            serialize_position_for_table(
                "BidHighlights", [3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0]
            ),
        )
        dimension_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, FontName, FontColor, FontSize
              FROM BidDimensions
            """
        ).fetchone()
        self.assertEqual(dimension_row, (1, 3, "Arial", 255, 48))
        self.assertEqual(
            conn.execute(
                "SELECT BidTakeoffFromUID, BidTakeoffToUID, FontBold, FontItalic, "
                "FontUnderline, Position FROM BidDimensions"
            ).fetchall(),
            [
                (
                    None,
                    None,
                    0,
                    0,
                    0,
                    serialize_position_for_table(
                        "BidDimensions", [1.0, 2.0, 13.0, 14.0]
                    ),
                )
            ],
        )
        text_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, FontName, FontColor, FontSize, TextAlign, Position
              FROM BidTexts
            """
        ).fetchone()
        self.assertEqual(text_row[:6], (1, 3, "Arial", 0x996633, 72, 0))
        self.assertIsInstance(text_row[6], str)
        self.assertEqual(
            text_row[6],
            serialize_position_for_table("BidTexts", [7.0, 8.0, 12.0, 12.0]),
        )
        named_view_row = conn.execute(
            "SELECT BidUID, BidPageUID, Name, Color, Origin, Position "
            "FROM BidNamedViews WHERE Name='Lobby'"
        ).fetchone()
        self.assertEqual(named_view_row[:5], (1, 3, "Lobby", 32768, 0))
        self.assertEqual(
            named_view_row[5],
            serialize_position_for_table(
                "BidNamedViews", [13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]
            ),
        )
        hotlink_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, BidPageViewUID, Color, Position
              FROM BidHotLinks
            """
        ).fetchone()
        self.assertEqual(hotlink_row[:4], (1, 3, 1, 255))
        self.assertEqual(
            hotlink_row[4], serialize_position_for_table("BidHotLinks", [5.0, 6.0])
        )

    def test_hotlink_numeric_zero_target_is_persisted_as_null(self):
        captured_values = {}
        operations = _dimension_support__DimensionWriteOps(None)
        operations._execute_insert_values = (
            lambda _cursor, _schema, _table, values, _required, _operation: (
                captured_values.update(values)
            )
        )
        for raw_target in (0, "0", "", None):
            with self.subTest(raw_target=raw_target):
                captured_values.clear()
                operations._execute_annotation_insert(
                    None,
                    _dimension_support__Schema(),
                    "BidHotLinks",
                    "hotlink",
                    1,
                    2,
                    3,
                    None,
                    b"position",
                    255,
                    0,
                    {"BidPageViewUID": raw_target},
                )
                self.assertEqual(
                    captured_values,
                    {
                        "UID": 1,
                        "BidUID": 2,
                        "BidPageUID": 3,
                        "BidPageViewUID": None,
                        "BidLayerUID": None,
                        "Position": b"position",
                        "Color": 255,
                    },
                )
        for properties, remap, expected_target in (
            ({"BidPageViewUID": "7"}, None, 7),
            ({"BidPageViewUID": "7"}, PasteRefRemap(namedview_uids={"7": "12"}), 12),
            ({"BidPageViewUID": "8"}, PasteRefRemap(namedview_uids={"7": "12"}), 8),
        ):
            with self.subTest(properties=properties, remap=remap):
                captured_values.clear()
                operations._execute_annotation_insert(
                    None,
                    _dimension_support__Schema(),
                    "BidHotLinks",
                    "hotlink",
                    1,
                    2,
                    3,
                    None,
                    b"position",
                    255,
                    0,
                    properties,
                    ref_remap=remap,
                )
                self.assertEqual(captured_values["BidPageViewUID"], expected_target)

    def test_paste_remap_translates_takeoff_and_named_view_references_before_validation(
        self,
    ):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            "CREATE TABLE BidNamedViews "
            "(UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.executemany("INSERT INTO BidNamedViews VALUES (?, ?, 3)", ((5, 2), (9, 1)))
        conn.execute(
            "CREATE TABLE BidHotLinks (UID INTEGER, BidUID INTEGER, "
            "BidPageUID INTEGER, BidPageViewUID INTEGER, BidLayerUID INTEGER, "
            "Color INTEGER, Position BLOB)"
        )
        conn.execute(
            "CREATE TABLE BidALines (UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidTakeoffFromUID INTEGER, BidTakeoffToUID INTEGER, Position BLOB, "
            "Color INTEGER, Width INTEGER)"
        )
        conn.commit()
        specs = [
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="line",
                position=[0.0, 0.0, 1.0, 1.0],
                color="#000000",
                width=1.0,
                properties={"BidTakeoffFromUID": "11", "BidTakeoffToUID": "12"},
            ),
            InsertAnnotationSpec(
                page_uid="3",
                annotation_type="hotlink",
                position=[5.0, 6.0],
                color="#000000",
                width=1.0,
                properties={"BidPageViewUID": "5"},
            ),
        ]
        operations = _dimension_support__DimensionWriteOps(conn)
        self.assertEqual(operations.insert_annotations("bid.mdb", "1", specs), [])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidALines").fetchone()[0], 0
        )
        self.assertEqual(
            operations.insert_annotations(
                "bid.mdb",
                "1",
                specs,
                ref_remap=PasteRefRemap(
                    takeoff_uids={"11": "21"}, namedview_uids={"5": "9"}
                ),
            ),
            ["1", "1"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT BidTakeoffFromUID, BidTakeoffToUID FROM BidALines"
            ).fetchall(),
            [(21, None)],
        )
        self.assertEqual(
            conn.execute("SELECT BidPageViewUID FROM BidHotLinks").fetchall(),
            [(9,)],
        )

    def test_hotlink_insert_rejects_named_view_from_another_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (10, 1)")
        conn.execute(
            "CREATE TABLE BidNamedViews ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidHotLinks ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidPageViewUID INTEGER, BidLayerUID INTEGER, Color INTEGER, "
            "Position BLOB)"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (7, 2, 20)")
        conn.commit()
        result = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb",
            "1",
            [
                InsertAnnotationSpec(
                    page_uid="10",
                    annotation_type="hotlink",
                    position=[1.0, 2.0],
                    color="#ff0000",
                    width=1.0,
                    properties={"BidPageViewUID": "7"},
                )
            ],
        )
        self.assertEqual(result, [])
        self.assertEqual(conn.execute("SELECT * FROM BidHotLinks").fetchall(), [])

    def test_annotation_insert_rejects_page_from_another_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidLayerUID INTEGER, Position BLOB, Color INTEGER, Width INTEGER)"
        )
        conn.execute("INSERT INTO BidPages VALUES (10, 2)")
        conn.commit()
        result = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb",
            "1",
            [
                InsertAnnotationSpec(
                    page_uid="10",
                    annotation_type="rect",
                    position=[1.0, 2.0, 3.0, 4.0],
                    color="#ff0000",
                    width=1.0,
                    properties={},
                )
            ],
        )
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute("SELECT * FROM BidAnnotationRects").fetchall(), []
        )

    def test_annotation_insert_rejects_layer_from_another_bid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidLayerUID INTEGER, Position BLOB, Color INTEGER, Width INTEGER)"
        )
        conn.execute("INSERT INTO BidPages VALUES (10, 1)")
        conn.execute("INSERT INTO BidLayers VALUES (7, 2)")
        conn.commit()
        result = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "bid.mdb",
            "1",
            [
                InsertAnnotationSpec(
                    page_uid="10",
                    annotation_type="rect",
                    position=[1.0, 2.0, 3.0, 4.0],
                    color="#ff0000",
                    width=1.0,
                    properties={},
                    layer_uid="7",
                )
            ],
        )
        self.assertEqual(result, [])
        self.assertEqual(
            conn.execute("SELECT * FROM BidAnnotationRects").fetchall(), []
        )

    def test_named_view_insert_does_not_claim_dangling_hotlink_target_uid(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            "CREATE TABLE BidNamedViews ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, Name TEXT, "
            "Position BLOB, Color INTEGER, Origin INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidHotLinks ("
            "UID INTEGER, BidUID INTEGER, BidPageUID INTEGER, "
            "BidPageViewUID INTEGER)"
        )
        conn.execute("INSERT INTO BidHotLinks VALUES (7, 1, 3, 1)")
        result = _dimension_support__DimensionWriteOps(conn).insert_annotations(
            "malformed.mdb",
            "1",
            [
                InsertAnnotationSpec(
                    page_uid="3",
                    annotation_type="namedview",
                    position=[0.0, 0.0, 10.0, 10.0],
                    color="#ff0000",
                    width=1.0,
                    properties={"Text": "New view"},
                )
            ],
        )
        self.assertEqual(result, ["2"])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidNamedViews").fetchall(),
            [(2,)],
        )
        self.assertEqual(
            conn.execute("SELECT BidPageViewUID FROM BidHotLinks").fetchall(),
            [(1,)],
        )
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM BidHotLinks AS link "
                "INNER JOIN BidNamedViews AS view "
                "ON link.BidPageViewUID=view.UID"
            ).fetchone()[0],
            0,
        )

    def test_text_annotation_position_updates_write_text_payload(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidTexts (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Name BLOB,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER,
                TextAlign INTEGER,
                Position TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO BidTexts
                (UID, BidUID, BidPageUID, BidLayerUID, Position)
            VALUES
                (1, 1, 3, 4, ?)
            """,
            (encode_position([0.0, 0.0, 1.0, 1.0]),),
        )
        self.assertTrue(
            _dimension_support__DimensionWriteOps(conn).save_annotation_positions(
                "bid.mdb", [("1", "text", [7.0, 8.0, 12.0, 12.0])]
            )
        )
        position_value = conn.execute(
            "SELECT Position FROM BidTexts WHERE UID=1"
        ).fetchone()[0]
        self.assertIsInstance(position_value, str)
        self.assertEqual(
            position_value,
            serialize_position_for_table("BidTexts", [7.0, 8.0, 12.0, 12.0]),
        )

    def test_polygon_control_point_positions_persist_for_polygon_and_cloud_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        for table in ("BidAnnotationPolygons", "BidAnnotationClouds"):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    UID INTEGER PRIMARY KEY,
                    BidUID INTEGER,
                    Position BLOB
                )
                """
            )
            conn.execute(
                f"INSERT INTO {table} (UID, BidUID, Position) VALUES (1, 1, ?)",
                (encode_position([0.0, 0.0, 10.0, 0.0, 0.0, 10.0]),),
            )
        positions = {
            "polygon": [0.0, 0.0, 5.0, 0.0, 10.0, 0.0, 0.0, 10.0],
            "cloud": [0.0, 0.0, 10.0, 0.0, 10.0, 10.0, 0.0, 10.0],
        }
        self.assertTrue(
            _dimension_support__DimensionWriteOps(conn).save_annotation_positions(
                "bid.mdb",
                [
                    ("1", annotation_type, position)
                    for annotation_type, position in positions.items()
                ],
            )
        )
        for annotation_type, table in (
            ("polygon", "BidAnnotationPolygons"),
            ("cloud", "BidAnnotationClouds"),
        ):
            with self.subTest(annotation_type=annotation_type):
                stored = conn.execute(
                    f"SELECT Position FROM {table} WHERE UID=1"
                ).fetchone()[0]
                self.assertEqual(
                    stored,
                    serialize_position_for_table(table, positions[annotation_type]),
                )
                self.assertEqual(
                    parse_position_storage(stored), positions[annotation_type]
                )

    def test_annotation_style_updates_are_per_annotation_and_per_type(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)")
        conn.execute("INSERT INTO BidPages VALUES (3, 1)")
        conn.execute(
            """
            CREATE TABLE BidALines (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                Color INTEGER,
                Width INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidArrows (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                Color INTEGER,
                Width INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidAnnoInk (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                Color INTEGER,
                Position BLOB,
                Width INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidTakeoffFromUID INTEGER,
                BidTakeoffToUID INTEGER,
                Position BLOB,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER
            )
            """
        )
        for table in (
            "BidAnnotationRects",
            "BidAnnotationOvals",
            "BidAnnotationPolygons",
            "BidAnnotationClouds",
        ):
            conn.execute(
                f"""
                CREATE TABLE {table} (
                    UID INTEGER PRIMARY KEY,
                    BidUID INTEGER,
                    BidPageUID INTEGER,
                    BidLayerUID INTEGER,
                    Position BLOB,
                    Color INTEGER,
                    Width INTEGER
                )
                """
            )
        conn.execute(
            """
            CREATE TABLE BidTexts (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Name BLOB,
                FontName TEXT,
                FontColor INTEGER,
                FontSize INTEGER,
                FontBold INTEGER,
                FontItalic INTEGER,
                FontUnderline INTEGER,
                TextAlign INTEGER,
                Position TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidHighlights (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageUID INTEGER,
                BidLayerUID INTEGER,
                Color INTEGER,
                Position BLOB
            )
            """
        )
        base_positions = {
            "line": [0.0, 0.0, 10.0, 10.0],
            "arrow": [1.0, 2.0, 13.0, 14.0],
            "dimension": [1.0, 2.0, 13.0, 14.0],
            "rect": [1.0, 2.0, 13.0, 14.0],
            "oval": [2.0, 3.0, 14.0, 15.0],
            "polygon": [0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
            "cloud": [1.0, 1.0, 13.0, 1.0, 7.0, 9.0],
            "ink": [0.0, 0.0, 5.0, 5.0, 10.0, 0.0],
            "highlight": [3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0],
            "text": [7.0, 8.0, 12.0, 12.0],
        }
        specs = []
        for annotation_type, position in base_positions.items():
            for color in ("#ff0000", "#0000ff"):
                properties = {}
                if annotation_type in ("line", "arrow", "dimension"):
                    properties.update({"BidTakeoffFromUID": "", "BidTakeoffToUID": ""})
                if annotation_type == "dimension":
                    properties.update(
                        {
                            "FontName": "Arial",
                            "FontColor": color,
                            "FontSize": 10,
                            "FontBold": False,
                            "FontItalic": False,
                            "FontUnderline": False,
                        }
                    )
                if annotation_type == "text":
                    color_text = color.lstrip("#")
                    color_int = (
                        int(color_text[0:2], 16)
                        | (int(color_text[2:4], 16) << 8)
                        | (int(color_text[4:6], 16) << 16)
                    )
                    properties.update(
                        {
                            "Text": "Text",
                            "FontName": "Arial",
                            "FontColor": color_int,
                            "FontSize": 12,
                            "FontBold": False,
                            "FontItalic": False,
                            "FontUnderline": False,
                            "TextAlign": 0,
                        }
                    )
                specs.append(
                    InsertAnnotationSpec(
                        page_uid="3",
                        annotation_type=annotation_type,
                        position=list(position),
                        color=color,
                        width=4.0,
                        properties=properties,
                    )
                )
        ops = _dimension_support__DimensionWriteOps(conn)
        ops.insert_annotations("bid.mdb", "1", specs)
        updates = [
            ("1", annotation_type, {"Color": "#00aa44", "Width": 6.0})
            for annotation_type in base_positions
        ]
        self.assertTrue(ops.save_annotation_styles("bid.mdb", updates))
        expected_shape_tables = {
            "line": "BidALines",
            "arrow": "BidArrows",
            "rect": "BidAnnotationRects",
            "oval": "BidAnnotationOvals",
            "polygon": "BidAnnotationPolygons",
            "cloud": "BidAnnotationClouds",
            "ink": "BidAnnoInk",
        }
        for annotation_type, table in expected_shape_tables.items():
            with self.subTest(annotation_type=annotation_type):
                rows = conn.execute(
                    f"SELECT UID, Color, Width FROM {table} ORDER BY UID"
                ).fetchall()
                self.assertEqual(rows, [(1, 0x44AA00, 6), (2, 0xFF0000, 4)])
        dimension_rows = conn.execute(
            "SELECT UID, FontColor FROM BidDimensions ORDER BY UID"
        ).fetchall()
        self.assertEqual(dimension_rows, [(1, 0x44AA00), (2, 0xFF0000)])
        text_rows = conn.execute(
            "SELECT UID, FontColor FROM BidTexts ORDER BY UID"
        ).fetchall()
        self.assertEqual(text_rows, [(1, 0x44AA00), (2, 0xFF0000)])
        highlight_rows = conn.execute(
            "SELECT UID, Color FROM BidHighlights ORDER BY UID"
        ).fetchall()
        self.assertEqual(highlight_rows, [(1, 0x44AA00), (2, 0xFF0000)])

    def test_annotation_style_update_variants_leave_unlisted_columns_untouched(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidAnnotationRects "
            "(UID INTEGER, BidUID INTEGER, Color INTEGER, Width INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, Color INTEGER)"
        )
        conn.execute(
            "CREATE TABLE BidHotLinks (UID INTEGER, BidUID INTEGER, Color INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidAnnotationRects VALUES (?, 1, 100, 4)", ((1,), (2,))
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (1, 1, 100)")
        conn.execute("INSERT INTO BidHotLinks VALUES (1, 1, 100)")
        ops = _dimension_support__DimensionWriteOps(conn)
        self.assertTrue(ops.save_annotation_styles("bid.mdb", []))
        self.assertTrue(
            ops.save_annotation_styles(
                "bid.mdb",
                [
                    ("1", "rect", {"Color": 0x112233}),
                    ("2", "rect", {"Width": "3.7"}),
                    ("1", "namedview", {"Color": "#00aa44", "Width": 9}),
                    ("1", "hotlink", {"Color": 5, "Width": 9}),
                    ("1", "bogus", {"Color": 7}),
                    ("2", "rect", {"Opacity": 1}),
                ],
            )
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Color, Width FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(1, 0x112233, 4), (2, 100, 3)],
        )
        self.assertEqual(
            conn.execute("SELECT Color FROM BidNamedViews").fetchall(), [(0x44AA00,)]
        )
        self.assertEqual(
            conn.execute("SELECT Color FROM BidHotLinks").fetchall(), [(5,)]
        )

    def test_delete_annotations_removes_hotlinks_before_named_views(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            """
            CREATE TABLE BidNamedViews (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                Name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidHotLinks (
                UID INTEGER PRIMARY KEY,
                BidUID INTEGER,
                BidPageViewUID INTEGER REFERENCES BidNamedViews(UID)
            )
            """
        )
        conn.execute(
            "INSERT INTO BidNamedViews (UID, BidUID, Name) VALUES (1, 1, 'Lobby')"
        )
        conn.execute(
            "INSERT INTO BidHotLinks (UID, BidUID, BidPageViewUID) VALUES (1, 1, 1)"
        )
        result = _dimension_support__DimensionWriteOps(conn).delete_annotations(
            "bid.mdb",
            [("1", "namedview"), ("1", "hotlink")],
        )
        self.assertTrue(result)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidHotLinks").fetchone()[0],
            0,
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidNamedViews").fetchone()[0],
            0,
        )

    def test_delete_named_view_rejects_unlisted_dependent_hotlinks(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute(
            "CREATE TABLE BidNamedViews ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, Name TEXT)"
        )
        conn.execute(
            "CREATE TABLE BidHotLinks ("
            "UID INTEGER PRIMARY KEY, BidUID INTEGER, "
            "BidPageViewUID INTEGER REFERENCES BidNamedViews(UID))"
        )
        conn.execute("INSERT INTO BidNamedViews VALUES (1, 1, 'Lobby')")
        conn.execute("INSERT INTO BidHotLinks VALUES (2, 1, 1)")
        conn.commit()
        result = _dimension_support__DimensionWriteOps(conn).delete_annotations(
            "bid.mdb", [("1", "namedview")]
        )
        self.assertFalse(result)
        self.assertEqual(
            conn.execute("SELECT * FROM BidHotLinks").fetchall(), [(2, 1, 1)]
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidNamedViews").fetchall(), [(1, 1, "Lobby")]
        )

    def test_delete_annotations_rejects_targets_from_different_bids(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.executemany("INSERT INTO Bids VALUES (?)", ((1,), (2,)))
        for table in ("BidAnnotationRects", "BidAnnotationOvals"):
            conn.execute(f"CREATE TABLE {table} (UID INTEGER, BidUID INTEGER)")
            conn.executemany(
                f"INSERT INTO {table} VALUES (?, ?)", ((1, 1), (2, 2), (3, 1))
            )
        conn.commit()
        ops = _dimension_support__DimensionWriteOps(conn)
        for annotations in (
            [("1", "rect"), ("2", "rect")],
            [("1", "rect"), ("2", "oval")],
        ):
            with self.subTest(annotations=annotations):
                self.assertFalse(ops.delete_annotations("bid.mdb", annotations))
                for table in ("BidAnnotationRects", "BidAnnotationOvals"):
                    self.assertEqual(
                        conn.execute(
                            f"SELECT UID FROM {table} ORDER BY UID"
                        ).fetchall(),
                        [(1,), (2,), (3,)],
                    )
        self.assertTrue(
            ops.delete_annotations("bid.mdb", [("1", "rect"), ("3", "oval")])
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects ORDER BY UID").fetchall(),
            [(2,), (3,)],
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationOvals ORDER BY UID").fetchall(),
            [(1,), (2,)],
        )

    def test_delete_annotations_rejects_unsupported_type(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidAnnotationRects (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO BidAnnotationRects (UID) VALUES (1)")
        result = _dimension_support__DimensionWriteOps(conn).delete_annotations(
            "bid.mdb",
            [("1", "rect"), ("2", "unsupported")],
        )
        self.assertFalse(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(),
            [(1,)],
        )

    def test_delete_annotations_rejects_invalid_uid_without_raising(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE BidAnnotationRects (UID INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO BidAnnotationRects (UID) VALUES (1)")
        result = _dimension_support__DimensionWriteOps(conn).delete_annotations(
            "bid.mdb",
            [("not-a-uid", "rect")],
        )
        self.assertFalse(result)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(),
            [(1,)],
        )
