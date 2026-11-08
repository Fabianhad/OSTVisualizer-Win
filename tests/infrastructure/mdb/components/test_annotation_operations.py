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
from tests.helpers.mdb.annotation_write_support import (
    ReraisingRealContractAnnotationOps,
    RealContractAnnotationOps,
    RollbackListParamConnection,
    annotation_database,
)
from tests.helpers.mdb.real_write_contract import ListParamCursor
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


def _typed_columns(columns):
    return ", ".join(
        f"{column} INTEGER" if column.endswith("UID") else column for column in columns
    )


def _annotation_table_ddl(table, columns):
    return f"CREATE TABLE {table} ({_typed_columns(columns)})"


_COMMON_REQUIRED = ("UID", "BidUID", "BidPageUID", "Position")
# annotation type -> (table, required columns, operation label, optional columns)
_INSERT_CONTRACT = {
    "line": (
        "BidALines",
        _COMMON_REQUIRED,
        "insert_line_annotation",
        ("BidTakeoffFromUID", "BidTakeoffToUID", "Color", "Width"),
    ),
    "arrow": (
        "BidArrows",
        _COMMON_REQUIRED,
        "insert_arrow_annotation",
        ("BidTakeoffFromUID", "BidTakeoffToUID", "Color", "Width"),
    ),
    "dimension": (
        "BidDimensions",
        _COMMON_REQUIRED,
        "insert_dimension_annotation",
        (
            "BidTakeoffFromUID",
            "BidTakeoffToUID",
            "FontName",
            "FontColor",
            "FontSize",
            "FontBold",
            "FontItalic",
            "FontUnderline",
        ),
    ),
    "text": (
        "BidTexts",
        _COMMON_REQUIRED,
        "insert_text_annotation",
        (
            "BidLayerUID",
            "Name",
            "FontName",
            "FontColor",
            "FontSize",
            "FontBold",
            "FontItalic",
            "FontUnderline",
            "TextAlign",
        ),
    ),
    "callout": (
        "BidCallOuts",
        _COMMON_REQUIRED,
        "insert_callout_annotation",
        (
            "BidLayerUID",
            "Name",
            "FontName",
            "FontColor",
            "FontSize",
            "FontBold",
            "FontItalic",
            "FontUnderline",
            "TextAlign",
            "Color",
            "Width",
        ),
    ),
    "highlight": (
        "BidHighlights",
        _COMMON_REQUIRED,
        "insert_highlight_annotation",
        ("BidLayerUID", "Color"),
    ),
    "hotlink": (
        "BidHotLinks",
        _COMMON_REQUIRED + ("BidPageViewUID",),
        "insert_hotlink_annotation",
        ("BidLayerUID", "Color"),
    ),
    "namedview": (
        "BidNamedViews",
        _COMMON_REQUIRED + ("Name",),
        "insert_namedview_annotation",
        ("Color", "Origin"),
    ),
    "ink": (
        "BidAnnoInk",
        _COMMON_REQUIRED,
        "insert_ink_annotation",
        ("Color", "Width"),
    ),
    "rect": (
        "BidAnnotationRects",
        _COMMON_REQUIRED,
        "insert_rect_annotation",
        ("BidLayerUID", "Color", "Width"),
    ),
    "oval": (
        "BidAnnotationOvals",
        _COMMON_REQUIRED,
        "insert_oval_annotation",
        ("BidLayerUID", "Color", "Width"),
    ),
    "polygon": (
        "BidAnnotationPolygons",
        _COMMON_REQUIRED,
        "insert_polygon_annotation",
        ("BidLayerUID", "Color", "Width"),
    ),
    "cloud": (
        "BidAnnotationClouds",
        _COMMON_REQUIRED,
        "insert_cloud_annotation",
        ("BidLayerUID", "Color", "Width"),
    ),
}


def _insert_spec(annotation_type):
    properties = {}
    if annotation_type == "namedview":
        properties = {"Text": "View"}
    return InsertAnnotationSpec(
        page_uid="3",
        annotation_type=annotation_type,
        position=[1.0, 2.0, 13.0, 14.0],
        color="#ff0000",
        width=2.0,
        properties=properties,
    )


def _insert_database(annotation_type, columns):
    table = _INSERT_CONTRACT[annotation_type][0]
    return annotation_database(
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (3, 1)",
        _annotation_table_ddl(table, columns),
    )


class RealContractAnnotationInsertTests(unittest.TestCase):
    """Insert paths against the production required-column and skip contract."""

    def test_each_type_inserts_with_only_its_required_columns_and_reports_the_skips(
        self,
    ):
        for annotation_type, contract in _INSERT_CONTRACT.items():
            table, required, label, optional = contract
            with self.subTest(annotation_type=annotation_type):
                conn = _insert_database(annotation_type, required)
                ops = RealContractAnnotationOps(conn)
                result = ops.insert_annotations(
                    "bid.mdb", "1", [_insert_spec(annotation_type)]
                )
                self.assertEqual(result, ["1"])
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidUID, BidPageUID FROM {table}"
                    ).fetchall(),
                    [(1, 1, 3)],
                )
                self.assertEqual(
                    sorted(ops.skips),
                    sorted((table, column, label) for column in optional),
                )

    def test_each_type_fails_atomically_when_a_required_column_is_missing(self):
        for annotation_type, contract in _INSERT_CONTRACT.items():
            table, required, _label, _optional = contract
            for missing in required:
                with self.subTest(annotation_type=annotation_type, missing=missing):
                    columns = [column for column in required if column != missing]
                    conn = _insert_database(annotation_type, columns)
                    ops = RealContractAnnotationOps(conn)
                    with self.assertLogs(
                        "test.annotation_write_support", level="ERROR"
                    ) as logs:
                        result = ops.insert_annotations(
                            "bid.mdb", "1", [_insert_spec(annotation_type)]
                        )
                    self.assertEqual(result, [])
                    self.assertIn("bid.mdb", logs.output[0])
                    failure = logs.records[0].exc_info[1]
                    if missing == "UID":
                        # identity allocation reads MAX(UID) before any insert
                        self.assertIsInstance(failure, sqlite3.OperationalError)
                    else:
                        self.assertIsInstance(failure, RuntimeError)
                        self.assertEqual(str(failure), f"Missing {table}.{missing}")
                    self.assertEqual(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                    )

    def test_failed_insert_rolls_back_earlier_rows_of_the_same_batch(self):
        conn = annotation_database(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (3, 1)",
            _annotation_table_ddl("BidAnnotationRects", _COMMON_REQUIRED),
            _annotation_table_ddl("BidAnnotationOvals", _COMMON_REQUIRED),
            "CREATE TRIGGER block_oval BEFORE INSERT ON BidAnnotationOvals "
            "BEGIN SELECT RAISE(ABORT, 'oval blocked'); END",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            result = ops.insert_annotations(
                "bid.mdb", "1", [_insert_spec("rect"), _insert_spec("oval")]
            )
        self.assertEqual(result, [])
        self.assertIn("oval blocked", repr(logs.records[0].exc_info[1]))
        self.assertFalse(conn.in_transaction)
        for table in ("BidAnnotationRects", "BidAnnotationOvals"):
            self.assertEqual(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
            )

    def test_layer_is_only_validated_and_stored_when_the_table_has_the_column(self):
        conn = annotation_database(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidPages VALUES (3, 1)",
            "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidLayers VALUES (9, 2)",
            _annotation_table_ddl("BidAnnoInk", _COMMON_REQUIRED),
            _annotation_table_ddl(
                "BidAnnotationRects", _COMMON_REQUIRED + ("BidLayerUID",)
            ),
        )
        ops = RealContractAnnotationOps(conn)
        ink = _insert_spec("ink")
        ink.layer_uid = "9"
        self.assertEqual(ops.insert_annotations("bid.mdb", "1", [ink]), ["1"])
        rect = _insert_spec("rect")
        rect.layer_uid = "9"
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertEqual(ops.insert_annotations("bid.mdb", "1", [rect]), [])
        self.assertIn("BidLayers", repr(logs.records[0].exc_info[1]))
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidAnnoInk").fetchall(), [(1,)])


def _database_with_bid(*ddl):
    return annotation_database(
        "CREATE TABLE Bids (UID INTEGER)", "INSERT INTO Bids VALUES (1)", *ddl
    )


class RealContractAnnotationUpdateDeleteTests(unittest.TestCase):
    """Update and delete paths with real schema presence checks and rollback."""

    def test_position_save_skips_missing_tables_but_requires_the_position_column(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID", "Position")),
            _annotation_table_ddl("BidHighlights", ("UID", "BidUID")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, X'00')",
            "INSERT INTO BidHighlights VALUES (1, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        # BidAnnotationOvals does not exist: that update is skipped, not failed.
        self.assertIs(
            ops.save_annotation_positions(
                "bid.mdb",
                [
                    ("1", "oval", [0.0, 0.0, 1.0, 1.0]),
                    ("1", "rect", [1.0, 2.0, 3.0, 4.0]),
                    ("1", "bogus", [9.0]),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchall(),
            [(b"1.0;2.0;3.0;4.0\n",)],
        )
        # BidHighlights exists but lacks Position: required column, whole save fails.
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.save_annotation_positions(
                    "bid.mdb",
                    [
                        ("1", "rect", [5.0, 6.0, 7.0, 8.0]),
                        ("1", "highlight", [0.0, 0.0, 1.0, 1.0]),
                    ],
                ),
                False,
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]), "Missing BidHighlights.Position"
        )
        self.assertIn("bid.mdb", logs.output[0])
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchall(),
            [(b"1.0;2.0;3.0;4.0\n",)],
        )
        self.assertFalse(conn.in_transaction)

    def test_position_save_failure_midway_rolls_back_earlier_updates(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID", "Position")),
            _annotation_table_ddl("BidAnnotationOvals", ("UID", "BidUID", "Position")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, X'00')",
            "INSERT INTO BidAnnotationOvals VALUES (1, 1, X'00')",
            "CREATE TRIGGER block_oval BEFORE UPDATE ON BidAnnotationOvals "
            "BEGIN SELECT RAISE(ABORT, 'oval blocked'); END",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR"):
            self.assertIs(
                ops.save_annotation_positions(
                    "bid.mdb",
                    [
                        ("1", "rect", [1.0, 2.0, 3.0, 4.0]),
                        ("1", "oval", [1.0, 2.0, 3.0, 4.0]),
                    ],
                ),
                False,
            )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchall(),
            [(b"\x00",)],
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationOvals").fetchall(),
            [(b"\x00",)],
        )

    def test_text_property_save_skips_missing_tables_and_requires_text_columns(self):
        font_columns = (
            "FontName",
            "FontColor",
            "FontSize",
            "FontBold",
            "FontItalic",
            "FontUnderline",
        )
        text_columns = ("UID", "BidUID", "Name") + font_columns + ("TextAlign",)
        conn = _database_with_bid(
            _annotation_table_ddl("BidCallOuts", text_columns),
            _annotation_table_ddl("BidTexts", ("UID", "BidUID", "Name")),
            "INSERT INTO BidCallOuts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
            "INSERT INTO BidTexts VALUES (1, 1, X'00')",
        )
        ops = RealContractAnnotationOps(conn)
        # namedview/dimension tables do not exist and are skipped; the callout applies.
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    ("1", "namedview", {"Text": "Renamed"}),
                    ("1", "dimension", {"FontName": "Calibri"}),
                    ("1", "callout", {"Text": "Note", "FontSize": 20}),
                    ("1", "rect", {"Text": "ignored"}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidCallOuts").fetchall(),
            [(1, 1, b"Note", "Arial", 0, 20, 0, 0, 0, 0)],
        )
        # BidTexts lacks the font columns: required, so nothing is written.
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.save_annotation_text_properties(
                    "bid.mdb",
                    [
                        ("1", "callout", {"Text": "Changed"}),
                        ("1", "text", {"Text": "Changed"}),
                    ],
                ),
                False,
            )
        self.assertEqual(str(logs.records[0].exc_info[1]), "Missing BidTexts.FontName")
        self.assertEqual(
            conn.execute("SELECT Name FROM BidCallOuts").fetchall(), [(b"Note",)]
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidTexts").fetchall(), [(b"\x00",)]
        )

    def test_named_view_and_dimension_text_updates_require_their_own_columns(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID")),
            _annotation_table_ddl(
                "BidDimensions",
                (
                    "UID",
                    "BidUID",
                    "FontName",
                    "FontColor",
                    "FontSize",
                    "FontBold",
                    "FontItalic",
                ),
            ),
            "INSERT INTO BidNamedViews VALUES (1, 1)",
            "INSERT INTO BidDimensions VALUES (1, 1, 'Times', 5, 30, 1, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        for update, missing in (
            (("1", "namedview", {"Text": "Renamed"}), "BidNamedViews.Name"),
            (
                ("1", "dimension", {"FontName": "Calibri"}),
                "BidDimensions.FontUnderline",
            ),
        ):
            with self.subTest(missing=missing):
                with self.assertLogs(
                    "test.annotation_write_support", level="ERROR"
                ) as logs:
                    self.assertIs(
                        ops.save_annotation_text_properties("bid.mdb", [update]),
                        False,
                    )
                self.assertEqual(str(logs.records[0].exc_info[1]), f"Missing {missing}")
        self.assertEqual(
            conn.execute("SELECT FontName FROM BidDimensions").fetchall(), [("Times",)]
        )

    def test_style_save_skips_missing_tables_and_requires_style_columns(self):
        conn = _database_with_bid(
            _annotation_table_ddl(
                "BidAnnotationRects", ("UID", "BidUID", "Color", "Width")
            ),
            _annotation_table_ddl("BidTexts", ("UID", "BidUID", "Color")),
            _annotation_table_ddl("BidAnnoInk", ("UID", "BidUID", "Width")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, 100, 4)",
            "INSERT INTO BidTexts VALUES (1, 1, 100)",
            "INSERT INTO BidAnnoInk VALUES (1, 1, 4)",
        )
        ops = RealContractAnnotationOps(conn)
        # BidArrows does not exist and is skipped.
        self.assertIs(
            ops.save_annotation_styles(
                "bid.mdb",
                [
                    ("1", "arrow", {"Color": 1}),
                    ("1", "rect", {"Color": "#112233", "Width": 7}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Color, Width FROM BidAnnotationRects").fetchall(),
            [(0x332211, 7)],
        )
        # Text colour is stored in FontColor, which BidTexts lacks: required.
        # Ink has no Color column: required for a colour change.
        for update, missing in (
            (("1", "text", {"Color": "#112233"}), "BidTexts.FontColor"),
            (("1", "ink", {"Color": "#112233"}), "BidAnnoInk.Color"),
            (("1", "rect", {"Width": 1}), None),
        ):
            with self.subTest(update=update):
                if missing is None:
                    self.assertIs(ops.save_annotation_styles("bid.mdb", [update]), True)
                    continue
                with self.assertLogs(
                    "test.annotation_write_support", level="ERROR"
                ) as logs:
                    self.assertIs(
                        ops.save_annotation_styles("bid.mdb", [update]), False
                    )
                self.assertEqual(str(logs.records[0].exc_info[1]), f"Missing {missing}")
        self.assertEqual(
            conn.execute("SELECT Color FROM BidTexts").fetchall(), [(100,)]
        )
        self.assertEqual(
            conn.execute("SELECT Width FROM BidAnnoInk").fetchall(), [(4,)]
        )

    def test_style_save_requires_width_column_for_width_changes(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidALines", ("UID", "BidUID", "Color")),
            "INSERT INTO BidALines VALUES (1, 1, 100)",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.save_annotation_styles(
                    "bid.mdb", [("1", "line", {"Color": 5, "Width": 3})]
                ),
                False,
            )
        self.assertEqual(str(logs.records[0].exc_info[1]), "Missing BidALines.Width")
        self.assertEqual(
            conn.execute("SELECT Color FROM BidALines").fetchall(), [(100,)]
        )

    def test_style_save_failure_midway_rolls_back_earlier_updates(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID", "Color")),
            _annotation_table_ddl("BidAnnotationOvals", ("UID", "BidUID", "Color")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, 100)",
            "INSERT INTO BidAnnotationOvals VALUES (1, 1, 100)",
            "CREATE TRIGGER block_oval BEFORE UPDATE ON BidAnnotationOvals "
            "BEGIN SELECT RAISE(ABORT, 'oval blocked'); END",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR"):
            self.assertIs(
                ops.save_annotation_styles(
                    "bid.mdb",
                    [("1", "rect", {"Color": 5}), ("1", "oval", {"Color": 5})],
                ),
                False,
            )
        for table in ("BidAnnotationRects", "BidAnnotationOvals"):
            self.assertEqual(
                conn.execute(f"SELECT Color FROM {table}").fetchall(), [(100,)]
            )

    def test_text_property_failure_midway_rolls_back_earlier_updates(self):
        text_columns = (
            "UID",
            "BidUID",
            "Name",
            "FontName",
            "FontColor",
            "FontSize",
            "FontBold",
            "FontItalic",
            "FontUnderline",
            "TextAlign",
        )
        conn = _database_with_bid(
            _annotation_table_ddl("BidTexts", text_columns),
            _annotation_table_ddl("BidCallOuts", text_columns),
            "INSERT INTO BidTexts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
            "INSERT INTO BidCallOuts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
            "CREATE TRIGGER block_callout BEFORE UPDATE ON BidCallOuts "
            "BEGIN SELECT RAISE(ABORT, 'callout blocked'); END",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR"):
            self.assertIs(
                ops.save_annotation_text_properties(
                    "bid.mdb",
                    [("1", "text", {"Text": "A"}), ("1", "callout", {"Text": "B"})],
                ),
                False,
            )
        self.assertEqual(
            conn.execute("SELECT Name, FontName FROM BidTexts").fetchall(),
            [(b"\x00", "Times")],
        )

    def test_delete_skips_missing_tables_and_requires_the_uid_column(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID")),
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1)",
            "INSERT INTO BidAnnotationRects VALUES (2, 1)",
            "INSERT INTO BidNamedViews VALUES (3, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        # BidAnnotationOvals and BidHotLinks do not exist: skipped, not failed.
        self.assertIs(
            ops.delete_annotations(
                "bid.mdb",
                [
                    ("1", "rect"),
                    ("1", "rect"),
                    ("9", "oval"),
                    ("3", "namedview"),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(), [(2,)]
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidNamedViews").fetchall(), [])

    def test_delete_failure_midway_rolls_back_earlier_table_deletes(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID")),
            _annotation_table_ddl("BidAnnotationOvals", ("UID", "BidUID")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1)",
            "INSERT INTO BidAnnotationOvals VALUES (1, 1)",
            "CREATE TRIGGER block_oval BEFORE DELETE ON BidAnnotationOvals "
            "BEGIN SELECT RAISE(ABORT, 'oval blocked'); END",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.delete_annotations("bid.mdb", [("1", "rect"), ("1", "oval")]),
                False,
            )
        self.assertIn("oval blocked", repr(logs.records[0].exc_info[1]))
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(), [(1,)]
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationOvals").fetchall(), [(1,)]
        )

    def test_named_view_delete_requires_hotlink_dependency_columns(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID")),
            _annotation_table_ddl("BidHotLinks", ("UID", "BidUID")),
            "INSERT INTO BidNamedViews VALUES (1, 1)",
            "INSERT INTO BidHotLinks VALUES (5, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.delete_annotations("bid.mdb", [("1", "namedview")]), False
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]), "Missing BidHotLinks.BidPageViewUID"
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidNamedViews").fetchall(), [(1,)]
        )

    def test_named_view_delete_must_list_every_dependent_hotlink_by_uid(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID")),
            _annotation_table_ddl("BidHotLinks", ("UID", "BidUID", "BidPageViewUID")),
            "INSERT INTO BidNamedViews VALUES (1, 1)",
            "INSERT INTO BidNamedViews VALUES (2, 1)",
            "INSERT INTO BidHotLinks VALUES (5, 1, 1)",
            "INSERT INTO BidHotLinks VALUES (6, 1, 1)",
            "INSERT INTO BidHotLinks VALUES (7, 1, 2)",
        )
        ops = RealContractAnnotationOps(conn)
        # Only one of the two hot links of view 1 is requested.
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.delete_annotations(
                    "bid.mdb", [("1", "namedview"), ("5", "hotlink")]
                ),
                False,
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "Named View deletion must include every dependent Hot Link.",
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidHotLinks").fetchone()[0], 3
        )
        # Listing both dependent links of view 1 (a link of view 2 stays) succeeds.
        self.assertIs(
            ops.delete_annotations(
                "bid.mdb", [("1", "namedview"), ("5", "hotlink"), ("6", "hotlink")]
            ),
            True,
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidHotLinks").fetchall(), [(7,)])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidNamedViews").fetchall(), [(2,)]
        )

    def test_mutation_errors_are_reraised_when_the_error_policy_requests_it(self):
        def rect_tables():
            return annotation_database(
                _annotation_table_ddl(
                    "BidAnnotationRects",
                    ("UID", "BidUID", "Position", "Color", "Width"),
                ),
                "INSERT INTO BidAnnotationRects VALUES (1, 1, X'00', 1, 1)",
                "INSERT INTO BidAnnotationRects VALUES (1, 2, X'00', 1, 1)",
                "CREATE TABLE Bids (UID INTEGER)",
            )

        for label, call, error_type, message, expected_outcome in (
            (
                "positions",
                lambda ops: ops.save_annotation_positions(
                    "bid.mdb", [("1", "rect", [1.0, 2.0, 3.0, 4.0])]
                ),
                RuntimeError,
                "BidAnnotationRects contains duplicate UID 1",
                False,
            ),
            (
                "text",
                lambda ops: ops.save_annotation_text_properties(
                    "bid.mdb", [("1", "rect", {})]
                ),
                RuntimeError,
                "BidAnnotationRects contains duplicate UID 1",
                False,
            ),
            (
                "styles",
                lambda ops: ops.save_annotation_styles(
                    "bid.mdb", [("1", "rect", {"Color": 1})]
                ),
                RuntimeError,
                "BidAnnotationRects contains duplicate UID 1",
                False,
            ),
            (
                "insert",
                lambda ops: ops.insert_annotations(
                    "bid.mdb", "1", [_insert_spec("rect")]
                ),
                RuntimeError,
                "Bids has no row for UID 1",
                [],
            ),
            (
                "delete",
                lambda ops: ops.delete_annotations("bid.mdb", [("1", "bogus")]),
                ValueError,
                "Unsupported annotation type: bogus",
                False,
            ),
        ):
            with self.subTest(label):
                conn = rect_tables()
                reraising = ReraisingRealContractAnnotationOps(conn)
                with self.assertRaisesRegex(error_type, message):
                    call(reraising)
                # The default error policy converts the same failure into False/[].
                swallowing = RealContractAnnotationOps(conn)
                with self.assertLogs("test.annotation_write_support", level="ERROR"):
                    outcome = call(swallowing)
                self.assertEqual(outcome, expected_outcome)
                self.assertIs(type(outcome), type(expected_outcome))


_FONT_COLUMNS = (
    "FontName",
    "FontColor",
    "FontSize",
    "FontBold",
    "FontItalic",
    "FontUnderline",
)
_TEXT_COLUMNS = (
    ("UID", "BidUID", "BidPageUID", "BidLayerUID", "Name")
    + _FONT_COLUMNS
    + ("TextAlign", "Position")
)
_CALLOUT_COLUMNS = _TEXT_COLUMNS + ("Color", "Width")
_DIMENSION_COLUMNS = (
    "UID",
    "BidUID",
    "BidPageUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "Position",
) + _FONT_COLUMNS
_LINE_COLUMNS = (
    "UID",
    "BidUID",
    "BidPageUID",
    "BidTakeoffFromUID",
    "BidTakeoffToUID",
    "Position",
    "Color",
    "Width",
)


def _insert_ready_database(*ddl):
    return annotation_database(
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (3, 1)",
        "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidLayers VALUES (9, 1)",
        *ddl,
    )


class RealContractAnnotationInsertValueTests(unittest.TestCase):
    """Values written by insert_annotations for the text-like and takeoff types."""

    def _insert(self, conn, specs, ref_remap=None):
        ops = RealContractAnnotationOps(conn)
        result = ops.insert_annotations("bid.mdb", "1", specs, ref_remap=ref_remap)
        self.assertEqual(ops.skips, [])
        return result

    def test_callout_insert_persists_explicit_and_default_properties(self):
        conn = _insert_ready_database(
            _annotation_table_ddl("BidCallOuts", _CALLOUT_COLUMNS)
        )
        explicit = InsertAnnotationSpec(
            page_uid="3",
            annotation_type="callout",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#00ff00",
            width=3.0,
            properties={
                "Text": "Hi",
                "FontName": "Cambria",
                "FontColor": 0x0000FF,
                "FontSize": 14,
                "FontBold": True,
                "FontItalic": True,
                "FontUnderline": True,
                "TextAlign": 2,
            },
            layer_uid="9",
        )
        defaults = InsertAnnotationSpec(
            page_uid="3",
            annotation_type="callout",
            position=[5.0, 6.0, 7.0, 8.0],
            color="#000000",
            width=0,
        )
        self.assertEqual(self._insert(conn, [explicit, defaults]), ["1", "2"])
        rows = conn.execute(
            "SELECT UID, BidUID, BidPageUID, BidLayerUID, Name, FontName, FontColor, "
            "FontSize, FontBold, FontItalic, FontUnderline, TextAlign, Color, Width, "
            "Position FROM BidCallOuts ORDER BY UID"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                (
                    1,
                    1,
                    3,
                    9,
                    b"Hi",
                    "Cambria",
                    0x0000FF,
                    14,
                    1,
                    1,
                    1,
                    2,
                    0x00FF00,
                    3,
                    "1.0;2.0;13.0;14.0\n",
                ),
                (
                    2,
                    1,
                    3,
                    None,
                    b"",
                    "Arial",
                    0,
                    12,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    "5.0;6.0;7.0;8.0\n",
                ),
            ],
        )

    def test_text_insert_persists_explicit_and_default_properties(self):
        conn = _insert_ready_database(_annotation_table_ddl("BidTexts", _TEXT_COLUMNS))
        explicit = InsertAnnotationSpec(
            page_uid="3",
            annotation_type="text",
            position=[7.0, 8.0, 12.0, 12.0],
            color="#336699",
            width=4.0,
            properties={
                "Text": "Note",
                "FontName": "Cambria",
                "FontColor": 0x996633,
                "FontSize": 20,
                "FontBold": True,
                "FontItalic": True,
                "FontUnderline": True,
                "TextAlign": 1,
            },
            layer_uid="9",
        )
        defaults = InsertAnnotationSpec(
            page_uid="3",
            annotation_type="text",
            position=[1.0, 1.0, 2.0, 2.0],
            color="#336699",
            width=4.0,
        )
        self.assertEqual(self._insert(conn, [explicit, defaults]), ["1", "2"])
        rows = conn.execute(
            "SELECT UID, BidLayerUID, Name, FontName, FontColor, FontSize, FontBold, "
            "FontItalic, FontUnderline, TextAlign FROM BidTexts ORDER BY UID"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                (1, 9, b"Note", "Cambria", 0x996633, 20, 1, 1, 1, 1),
                (2, None, b"", "Arial", 0, 12, 0, 0, 0, 0),
            ],
        )

    def test_dimension_insert_persists_font_defaults_and_colour_fallbacks(self):
        conn = _insert_ready_database(
            _annotation_table_ddl("BidDimensions", _DIMENSION_COLUMNS)
        )

        def spec(color, properties):
            return InsertAnnotationSpec(
                page_uid="3",
                annotation_type="dimension",
                position=[0.0, 0.0, 255.0, 0.0],
                color=color,
                width=1.0,
                properties=properties,
            )

        specs = [
            spec("#336699", {}),
            spec("#336699", {"FontColor": "#00ff00"}),
            spec("#336699", {"FontColor": None}),
            spec(
                "#336699",
                {
                    "FontName": "Cambria",
                    "FontColor": 0x0000FF,
                    "FontSize": 18,
                    "FontBold": True,
                    "FontItalic": True,
                    "FontUnderline": True,
                },
            ),
        ]
        self.assertEqual(self._insert(conn, specs), ["1", "2", "3", "4"])
        self.assertEqual(
            conn.execute(
                "SELECT UID, FontName, FontColor, FontSize, FontBold, FontItalic, "
                "FontUnderline FROM BidDimensions ORDER BY UID"
            ).fetchall(),
            [
                (1, "Arial", 0x996633, 10, 0, 0, 0),
                (2, "Arial", 0x00FF00, 10, 0, 0, 0),
                (3, "Arial", 0, 10, 0, 0, 0),
                (4, "Cambria", 0x0000FF, 18, 1, 1, 1),
            ],
        )

    def test_takeoff_references_are_remapped_and_unset_forms_are_stored_as_null(self):
        conn = _insert_ready_database(
            _annotation_table_ddl("BidALines", _LINE_COLUMNS),
            _annotation_table_ddl("BidArrows", _LINE_COLUMNS),
            _annotation_table_ddl("BidDimensions", _DIMENSION_COLUMNS),
        )

        def spec(annotation_type, properties):
            return InsertAnnotationSpec(
                page_uid="3",
                annotation_type=annotation_type,
                position=[0.0, 0.0, 10.0, 10.0],
                color="#ff0000",
                width=2.0,
                properties=properties,
            )

        remap = PasteRefRemap(
            takeoff_uids={"11": "21", "12": "22", "0": "99", "": "98"}
        )
        specs = []
        for annotation_type in ("line", "arrow", "dimension"):
            specs.append(
                spec(
                    annotation_type,
                    {"BidTakeoffFromUID": "11", "BidTakeoffToUID": "12"},
                )
            )
            specs.append(
                spec(
                    annotation_type,
                    {"BidTakeoffFromUID": "0", "BidTakeoffToUID": 0},
                )
            )
            specs.append(
                spec(
                    annotation_type, {"BidTakeoffFromUID": "", "BidTakeoffToUID": None}
                )
            )
            specs.append(
                spec(
                    annotation_type,
                    {"BidTakeoffFromUID": "13", "BidTakeoffToUID": "14"},
                )
            )
        # specs are line x4, arrow x4, dimension x4: every table numbers its rows 1..4
        self.assertEqual(self._insert(conn, specs, remap), ["1", "2", "3", "4"] * 3)
        for table in ("BidALines", "BidArrows", "BidDimensions"):
            with self.subTest(table=table):
                self.assertEqual(
                    conn.execute(
                        f"SELECT UID, BidTakeoffFromUID, BidTakeoffToUID FROM {table} "
                        "ORDER BY UID"
                    ).fetchall(),
                    [(1, 21, 22), (2, None, None), (3, None, None), (4, None, None)],
                )

    def test_resolve_takeoff_fk_maps_only_known_references(self):
        resolve = AnnotationOperationsMixin._resolve_takeoff_fk
        remap = {"0": "5", "": "6", "7": "70"}
        for raw, expected in (
            (None, None),
            ("", None),
            ("0", None),
            (0, None),
            ("7", 70),
            (7, 70),
            ("8", None),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(resolve(raw, remap), expected)
        self.assertEqual(resolve("7", {}), None)

    def test_hotlink_without_a_target_needs_no_named_view_table(self):
        for raw_target in (None, "", "0", 0):
            with self.subTest(raw_target=raw_target):
                conn = _insert_ready_database(
                    _annotation_table_ddl(
                        "BidHotLinks", _COMMON_REQUIRED + ("BidPageViewUID",)
                    )
                )
                spec = InsertAnnotationSpec(
                    page_uid="3",
                    annotation_type="hotlink",
                    position=[1.0, 2.0],
                    color="#ff0000",
                    width=2.0,
                    properties={"BidPageViewUID": raw_target},
                )
                ops = RealContractAnnotationOps(conn)
                self.assertEqual(ops.insert_annotations("bid.mdb", "1", [spec]), ["1"])
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, BidPageViewUID FROM BidHotLinks"
                    ).fetchall(),
                    [(1, None)],
                )

    def test_width_defaults_to_zero_and_is_truncated_to_an_integer(self):
        conn = _insert_ready_database(
            _annotation_table_ddl(
                "BidAnnotationRects", _COMMON_REQUIRED + ("Color", "Width")
            )
        )
        specs = []
        for width in (0, None, 0.0, 2.9, 5):
            spec = _insert_spec("rect")
            spec.width = width
            specs.append(spec)
        ops = RealContractAnnotationOps(conn)
        self.assertEqual(
            ops.insert_annotations("bid.mdb", "1", specs),
            ["1", "2", "3", "4", "5"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT Width FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(0,), (0,), (0,), (2,), (5,)],
        )

    def test_unknown_bid_is_reported_before_any_other_reference_check(self):
        conn = annotation_database(
            "CREATE TABLE Bids (UID INTEGER)",
            "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
            _annotation_table_ddl("BidAnnotationRects", _COMMON_REQUIRED),
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertEqual(
                ops.insert_annotations("bid.mdb", "1", [_insert_spec("rect")]), []
            )
        self.assertIn("Bids has no row for UID 1", str(logs.records[0].exc_info[1]))

    def test_empty_batches_succeed_without_touching_the_database(self):
        class NoConnectionOps(RealContractAnnotationOps):
            def _connection(self, _db_path):
                raise AssertionError("an empty batch must not open a connection")

        ops = NoConnectionOps(annotation_database())
        self.assertIs(ops.save_annotation_text_properties("bid.mdb", []), True)
        self.assertIs(ops.save_annotation_styles("bid.mdb", []), True)
        self.assertIs(ops.delete_annotations("bid.mdb", []), True)
        self.assertEqual(ops.insert_annotations("bid.mdb", "1", []), [])
        self.assertIs(
            RealContractAnnotationOps(annotation_database()).save_annotation_positions(
                "bid.mdb", []
            ),
            True,
        )


class RealContractAnnotationBatchSemanticsTests(unittest.TestCase):
    """Skip rules, scope checks and value coercions of the update/delete batches."""

    def test_unknown_types_and_missing_tables_do_not_stop_the_rest_of_a_batch(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID", "Position")),
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID", "Position")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, X'00')",
            "INSERT INTO BidAnnotationRects VALUES (2, 1, X'00')",
            "INSERT INTO BidNamedViews VALUES (3, 1, X'00')",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_positions(
                "bid.mdb",
                [
                    ("9", "bogus", [0.0]),
                    ("9", "oval", [0.0, 0.0, 1.0, 1.0]),
                    ("1", "rect", [1.0, 1.0, 2.0, 2.0]),
                    ("3", "namedview", [0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0]),
                    ("2", "rect", [3.0, 3.0, 4.0, 4.0]),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Position FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(1, b"1.0;1.0;2.0;2.0\n"), (2, b"3.0;3.0;4.0;4.0\n")],
        )
        self.assertNotEqual(
            conn.execute("SELECT Position FROM BidNamedViews").fetchone()[0], b"\x00"
        )

    def test_text_property_batch_updates_every_supported_kind_in_order(self):
        font = _FONT_COLUMNS
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID", "Name")),
            _annotation_table_ddl("BidDimensions", ("UID", "BidUID") + font),
            _annotation_table_ddl(
                "BidTexts", ("UID", "BidUID", "Name") + font + ("TextAlign",)
            ),
            _annotation_table_ddl(
                "BidCallOuts", ("UID", "BidUID", "Name") + font + ("TextAlign",)
            ),
            "INSERT INTO BidNamedViews VALUES (1, 1, 'Old')",
            "INSERT INTO BidDimensions VALUES (1, 1, 'Times', 5, 30, 1, 1, 1)",
            "INSERT INTO BidTexts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
            "INSERT INTO BidCallOuts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    ("1", "bogus", {"Text": "ignored"}),
                    ("1", "namedview", {"Text": "New"}),
                    ("1", "dimension", {"FontName": "Calibri", "FontSize": 11}),
                    ("1", "text", {"Text": "T", "FontColor": 7}),
                    ("1", "callout", {"Text": "C", "TextAlign": 2}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidNamedViews").fetchall(), [("New",)]
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidDimensions").fetchall(),
            [(1, 1, "Calibri", 0, 11, 0, 0, 0)],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidTexts").fetchall(),
            [(1, 1, b"T", "Arial", 7, 12, 0, 0, 0, 0)],
        )
        self.assertEqual(
            conn.execute("SELECT * FROM BidCallOuts").fetchall(),
            [(1, 1, b"C", "Arial", 0, 12, 0, 0, 0, 2)],
        )

    def test_text_property_batch_continues_after_a_missing_text_table(self):
        font = _FONT_COLUMNS
        conn = _database_with_bid(
            _annotation_table_ddl(
                "BidCallOuts", ("UID", "BidUID", "Name") + font + ("TextAlign",)
            ),
            "INSERT INTO BidCallOuts VALUES (1, 1, X'00', 'Times', 5, 30, 1, 1, 1, 3)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [("1", "text", {"Text": "gone"}), ("1", "callout", {"Text": "C"})],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Name FROM BidCallOuts").fetchall(), [(b"C",)]
        )

    def test_text_property_missing_text_and_none_values_use_empty_defaults(self):
        font = _FONT_COLUMNS
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID", "Name")),
            _annotation_table_ddl(
                "BidTexts", ("UID", "BidUID", "Name") + font + ("TextAlign",)
            ),
            "INSERT INTO BidNamedViews VALUES (1, 1, 'Old')",
            "INSERT INTO BidNamedViews VALUES (2, 1, 'Old')",
            "INSERT INTO BidTexts VALUES (1, 1, X'41', 'Times', 5, 30, 1, 1, 1, 3)",
            "INSERT INTO BidTexts VALUES (2, 1, X'41', 'Times', 5, 30, 1, 1, 1, 3)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    ("1", "namedview", {}),
                    ("2", "namedview", {"Text": None}),
                    ("1", "text", {}),
                    (
                        "2",
                        "text",
                        {"Text": None, "FontName": None, "FontSize": None},
                    ),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT UID, Name FROM BidNamedViews ORDER BY UID").fetchall(),
            [(1, ""), (2, "")],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Name, FontName, FontSize FROM BidTexts ORDER BY UID"
            ).fetchall(),
            [(1, b"", "Arial", 12), (2, None, "Arial", 12)],
        )

    def test_style_batch_skips_entries_without_work_and_keeps_going(self):
        conn = _database_with_bid(
            _annotation_table_ddl(
                "BidAnnotationRects", ("UID", "BidUID", "Color", "Width")
            ),
            _annotation_table_ddl("BidTexts", ("UID", "BidUID", "FontColor")),
            _annotation_table_ddl("BidDimensions", ("UID", "BidUID", "FontColor")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, 100, 4)",
            "INSERT INTO BidAnnotationRects VALUES (2, 1, 100, 4)",
            "INSERT INTO BidTexts VALUES (1, 1, 100)",
            "INSERT INTO BidDimensions VALUES (1, 1, 100)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_styles(
                "bid.mdb",
                [
                    ("1", "bogus", {"Color": 1}),
                    ("1", "arrow", {"Color": 1}),
                    ("1", "rect", {"Opacity": 1}),
                    ("1", "text", {"Color": "#112233", "Width": 9}),
                    ("1", "dimension", {"Color": 0x445566, "Width": 9}),
                    ("2", "rect", {"Color": None, "Width": None}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Color, Width FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(1, 100, 4), (2, 0, 0)],
        )
        self.assertEqual(
            conn.execute("SELECT FontColor FROM BidTexts").fetchall(), [(0x332211,)]
        )
        self.assertEqual(
            conn.execute("SELECT FontColor FROM BidDimensions").fetchall(),
            [(0x445566,)],
        )

    def test_style_width_is_truncated_and_missing_widths_become_zero(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidALines", ("UID", "BidUID", "Color", "Width")),
            *(
                f"INSERT INTO BidALines VALUES ({uid}, 1, 100, 4)"
                for uid in (1, 2, 3, 4)
            ),
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_styles(
                "bid.mdb",
                [
                    ("1", "line", {"Width": 3.7}),
                    ("2", "line", {"Width": "6.2"}),
                    ("3", "line", {"Width": 0}),
                    ("4", "line", {"Width": None, "Color": "#000001"}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Color, Width FROM BidALines ORDER BY UID"
            ).fetchall(),
            [(1, 100, 3), (2, 100, 6), (3, 100, 0), (4, 0x010000, 0)],
        )

    def test_cross_bid_targets_are_rejected_for_every_batch_kind(self):
        font = _FONT_COLUMNS
        message = "Annotation mutation targets do not belong to one authoritative Bid."

        def database():
            conn = annotation_database(
                "CREATE TABLE Bids (UID INTEGER)",
                "INSERT INTO Bids VALUES (1)",
                "INSERT INTO Bids VALUES (2)",
                _annotation_table_ddl(
                    "BidAnnotationRects",
                    ("UID", "BidUID", "Position", "Color", "Width"),
                ),
                _annotation_table_ddl(
                    "BidTexts", ("UID", "BidUID", "Name") + font + ("TextAlign",)
                ),
                "INSERT INTO BidAnnotationRects VALUES (1, 1, X'00', 100, 4)",
                "INSERT INTO BidAnnotationRects VALUES (2, 1, X'00', 100, 4)",
                "INSERT INTO BidTexts VALUES (3, 2, X'41', 'Times', 5, 30, 1, 1, 1, 3)",
            )
            return conn

        for label, call in (
            (
                "positions",
                lambda ops: ops.save_annotation_positions(
                    "bid.mdb",
                    [
                        ("9", "bogus", [0.0]),
                        ("1", "rect", [1.0, 1.0, 2.0, 2.0]),
                        ("3", "text", [1.0, 1.0, 2.0, 2.0]),
                    ],
                ),
            ),
            (
                "text",
                lambda ops: ops.save_annotation_text_properties(
                    "bid.mdb",
                    [
                        ("9", "bogus", {}),
                        ("3", "text", {"Text": "x"}),
                        ("1", "rect", {}),
                    ],
                ),
            ),
            (
                "styles",
                lambda ops: ops.save_annotation_styles(
                    "bid.mdb",
                    [
                        ("9", "bogus", {"Color": 1}),
                        ("1", "rect", {"Color": 5}),
                        ("3", "text", {"Color": 5}),
                    ],
                ),
            ),
            (
                "delete",
                lambda ops: ops.delete_annotations(
                    "bid.mdb", [("1", "rect"), ("3", "text")]
                ),
            ),
        ):
            with self.subTest(label):
                conn = database()
                ops = RealContractAnnotationOps(conn)
                before = {
                    table: conn.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("BidAnnotationRects", "BidTexts")
                }
                with self.assertLogs(
                    "test.annotation_write_support", level="ERROR"
                ) as logs:
                    outcome = call(ops)
                self.assertIs(outcome, False)
                self.assertEqual(str(logs.records[0].exc_info[1]), message)
                after = {
                    table: conn.execute(f"SELECT * FROM {table}").fetchall()
                    for table in ("BidAnnotationRects", "BidTexts")
                }
                self.assertEqual(after, before)

    def test_style_batch_rejects_two_bids_inside_one_table(self):
        conn = annotation_database(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "INSERT INTO Bids VALUES (2)",
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID", "Color")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1, 100)",
            "INSERT INTO BidAnnotationRects VALUES (2, 2, 100)",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.save_annotation_styles(
                    "bid.mdb",
                    [("1", "rect", {"Color": 5}), ("2", "rect", {"Color": 5})],
                ),
                False,
            )
        self.assertEqual(
            str(logs.records[0].exc_info[1]),
            "BidAnnotationRects mutation targets do not belong to one authoritative Bid.",
        )
        self.assertEqual(
            conn.execute("SELECT Color FROM BidAnnotationRects").fetchall(),
            [(100,), (100,)],
        )

    def test_delete_batches_duplicate_uids_collapse_to_one_statement(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1)",
            "INSERT INTO BidAnnotationRects VALUES (2, 1)",
        )
        statements = []
        conn.set_trace_callback(statements.append)
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.delete_annotations("bid.mdb", [("1", "rect")] * 120),
            True,
        )
        deletes = [
            sql for sql in statements if sql.lstrip().upper().startswith("DELETE")
        ]
        self.assertEqual(deletes, ["DELETE FROM [BidAnnotationRects] WHERE [UID]=1"])
        self.assertEqual(
            conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(), [(2,)]
        )

    def test_delete_without_named_views_ignores_the_hotlink_dependency_schema(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidAnnotationRects", ("UID", "BidUID")),
            _annotation_table_ddl("BidHotLinks", ("UID", "BidUID")),
            "INSERT INTO BidAnnotationRects VALUES (1, 1)",
            "INSERT INTO BidHotLinks VALUES (5, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(ops.delete_annotations("bid.mdb", [("1", "rect")]), True)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidAnnotationRects").fetchone()[0], 0
        )
        self.assertEqual(conn.execute("SELECT UID FROM BidHotLinks").fetchall(), [(5,)])

    def test_named_view_delete_without_dependent_hotlinks_succeeds(self):
        conn = _database_with_bid(
            _annotation_table_ddl("BidNamedViews", ("UID", "BidUID")),
            _annotation_table_ddl("BidHotLinks", ("UID", "BidUID", "BidPageViewUID")),
            "INSERT INTO BidNamedViews VALUES (1, 1)",
            "INSERT INTO BidNamedViews VALUES (2, 1)",
            "INSERT INTO BidHotLinks VALUES (5, 1, 2)",
            "INSERT INTO BidHotLinks VALUES (6, 1, NULL)",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(ops.delete_annotations("bid.mdb", [("1", "namedview")]), True)
        self.assertEqual(
            conn.execute("SELECT UID FROM BidNamedViews").fetchall(), [(2,)]
        )
        self.assertEqual(
            conn.execute("SELECT UID FROM BidHotLinks ORDER BY UID").fetchall(),
            [(5,), (6,)],
        )


class _NumericTextRejectingCursor(ListParamCursor):
    """Rejects numeric text bound as a parameter and records every statement.
    LIMITATION (read before trusting this guard): the premise that Microsoft
    Access rejects numeric *text* parameters against Long columns was taken from
    verifier V5's audit of layer_operations and could NOT be confirmed here,
    because no Access/ODBC driver is available in this environment (sqlite
    coerces numeric text to INTEGER by column affinity, which is exactly why the
    ``int()`` calls were invisible to every sqlite-backed test). What this cursor
    does pin is the module's own contract: every uid/bid/page/layer identifier
    and numeric property is converted to a Python ``int`` before it reaches the
    driver, so the behavior never depends on the driver's text coercion.
    """

    def __init__(self, connection, executed):
        super().__init__(connection)
        self._executed = executed

    def execute(self, query, *params):
        flat = (
            tuple(params[0])
            if len(params) == 1 and isinstance(params[0], (list, tuple))
            else params
        )
        self._executed.append((query, flat))
        for parameter in flat:
            if isinstance(parameter, str) and parameter.strip().lstrip("-").isdigit():
                raise AssertionError(f"numeric text parameter {parameter!r} in {query}")
        return super().execute(query, *params)


class _NumericTextRejectingConnection(RollbackListParamConnection):
    def __init__(self, connection, executed):
        super().__init__(connection)
        self._executed = executed

    def cursor(self):
        return _NumericTextRejectingCursor(self._connection, self._executed)


class _StrictParameterAnnotationOps(ReraisingRealContractAnnotationOps):
    """Real-contract annotation writes whose driver refuses numeric text.
    Errors are re-raised (nested-transaction policy) so a rejected parameter
    fails the test with the offending statement instead of being logged and
    turned into a ``False`` result.
    """

    def __init__(self, connection):
        super().__init__(connection)
        self.executed = []

    def _connection(self, _db_path):
        return _NumericTextRejectingConnection(self._connection_ref, self.executed)

    def statements(self, statement_prefix):
        """Parameters of every recorded statement starting with the prefix."""
        return [
            params
            for query, params in self.executed
            if " ".join(query.split()).startswith(statement_prefix)
        ]

    def bound(self, statement_prefix):
        """Parameters of the single recorded statement starting with the prefix."""
        matches = self.statements(statement_prefix)
        if len(matches) != 1:
            raise AssertionError(
                f"expected one statement starting with {statement_prefix!r}, "
                f"got {len(matches)}"
            )
        return matches[0]

    def insert_bound(self, table):
        """Column -> bound parameter of the single INSERT into ``table``."""
        prefix = f"INSERT INTO [{table}] ("
        query = next(q for q, _p in self.executed if q.startswith(prefix))
        columns = [
            column.strip(" []")
            for column in query[len(prefix) : query.index(") VALUES")].split(",")
        ]
        return dict(zip(columns, self.bound(prefix)))


def _strict_parameter_database():
    return annotation_database(
        "CREATE TABLE Bids (UID INTEGER)",
        "INSERT INTO Bids VALUES (1)",
        "CREATE TABLE BidPages (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidPages VALUES (3, 1)",
        "CREATE TABLE BidLayers (UID INTEGER, BidUID INTEGER)",
        "INSERT INTO BidLayers VALUES (9, 1)",
        "CREATE TABLE BidTakeoffs (UID INTEGER, BidUID INTEGER)",
        _annotation_table_ddl(
            "BidNamedViews",
            ("UID", "BidUID", "BidPageUID", "Name", "Position", "Color", "Origin"),
        ),
        "INSERT INTO BidNamedViews VALUES (5, 1, 3, 'one', 'p', 1, 0)",
        "INSERT INTO BidNamedViews VALUES (6, 1, 3, 'two', 'p', 1, 0)",
        _annotation_table_ddl(
            "BidHotLinks",
            (
                "UID",
                "BidUID",
                "BidPageUID",
                "BidPageViewUID",
                "BidLayerUID",
                "Position",
                "Color",
            ),
        ),
        "INSERT INTO BidHotLinks VALUES (30, 1, 3, 6, NULL, X'00', 1)",
        _annotation_table_ddl(
            "BidAnnotationRects",
            (
                "UID",
                "BidUID",
                "BidPageUID",
                "BidLayerUID",
                "Position",
                "Color",
                "Width",
            ),
        ),
        "INSERT INTO BidAnnotationRects VALUES (1, 1, 3, NULL, X'00', 1, 1)",
        "INSERT INTO BidAnnotationRects VALUES (2, 1, 3, NULL, X'00', 1, 1)",
        _annotation_table_ddl("BidTexts", _TEXT_COLUMNS),
        "INSERT INTO BidTexts VALUES "
        "(1, 1, 3, NULL, X'00', 'Old', 1, 12, 0, 0, 0, 0, 'x')",
        _annotation_table_ddl("BidCallOuts", _CALLOUT_COLUMNS),
        "INSERT INTO BidCallOuts VALUES "
        "(1, 1, 3, NULL, X'00', 'Old', 1, 12, 0, 0, 0, 0, 'x', 1, 1)",
        _annotation_table_ddl("BidDimensions", _DIMENSION_COLUMNS),
        "INSERT INTO BidDimensions VALUES "
        "(1, 1, 3, NULL, NULL, X'00', 'Old', 1, 10, 0, 0, 0)",
        _annotation_table_ddl(
            "BidHighlights",
            ("UID", "BidUID", "BidPageUID", "BidLayerUID", "Position", "Color"),
        ),
    )


def _strict_spec(annotation_type, **properties):
    return InsertAnnotationSpec(
        page_uid="3",
        annotation_type=annotation_type,
        position=[1.0, 2.0, 13.0, 14.0],
        color="#ff0000",
        width=2.0,
        properties=properties,
        layer_uid="9",
    )


class AnnotationParameterTypingTests(unittest.TestCase):
    """Identifiers and numeric properties arrive as text and must be bound as ints.
    The sqlite stand-ins coerce numeric text by column affinity, so dropping an
    ``int()`` conversion in the module is invisible to them. These tests run the
    production operations (real MdbWriter column contract, real schema checks)
    over a driver that rejects numeric text, and assert the stored rows too so
    that a test cannot pass by doing nothing. See the cursor docstring for the
    unconfirmed Access premise.
    """

    def setUp(self):
        self.conn = _strict_parameter_database()
        self.ops = _StrictParameterAnnotationOps(self.conn)

    def test_the_numeric_text_guard_rejects_numeric_text_and_accepts_the_rest(self):
        cursor = _NumericTextRejectingCursor(self.conn, [])
        for rejected in ("7", "-7", " 7 ", "007", "0"):
            with self.subTest(rejected=rejected):
                with self.assertRaisesRegex(AssertionError, "numeric text parameter"):
                    cursor.execute("SELECT ?", rejected)
        for accepted in (7, 0, 7.5, "", "abc", "7.5", "1e3", "-", None, b"7", True):
            with self.subTest(accepted=accepted):
                cursor.execute("SELECT ?", [accepted])
        with self.assertRaisesRegex(AssertionError, "numeric text parameter '1'"):
            cursor.execute("SELECT ?, ?", ["x", "1"])

    def test_position_saves_bind_each_uid_as_an_integer(self):
        self.assertIs(
            self.ops.save_annotation_positions(
                "bid.mdb",
                [
                    ("1", "rect", [1.0, 2.0, 3.0, 4.0]),
                    ("5", "namedview", [0.0, 0.0, 4.0, 0.0, 4.0, 4.0, 0.0, 4.0]),
                ],
            ),
            True,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT UID, Position FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(1, b"1.0;2.0;3.0;4.0\n"), (2, b"\x00")],
        )
        self.assertNotEqual(
            self.conn.execute(
                "SELECT Position FROM BidNamedViews WHERE UID=5"
            ).fetchone()[0],
            "p",
        )
        updates = self.ops.statements("UPDATE")
        self.assertEqual([params[-1] for params in updates], [1, 5])
        for params in updates:
            self.assertIs(type(params[-1]), int)

    def test_style_saves_bind_the_uid_color_and_width_as_integers(self):
        self.assertIs(
            self.ops.save_annotation_styles(
                "bid.mdb",
                [
                    ("1", "rect", {"Color": "#00ff00", "Width": "3"}),
                    ("1", "text", {"Color": "#0000ff"}),
                    ("1", "dimension", {"Color": 255}),
                ],
            ),
            True,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT UID, Color, Width FROM BidAnnotationRects WHERE UID=1"
            ).fetchall(),
            [(1, 0x00FF00, 3)],
        )
        self.assertEqual(
            self.conn.execute("SELECT FontColor FROM BidTexts").fetchall(),
            [(0xFF0000,)],
        )
        self.assertEqual(
            self.conn.execute("SELECT FontColor FROM BidDimensions").fetchall(),
            [(255,)],
        )
        updates = self.ops.statements("UPDATE")
        self.assertEqual(len(updates), 3)
        for params in updates:
            with self.subTest(params=params):
                self.assertEqual(
                    [type(parameter) for parameter in params], [int] * len(params)
                )

    def test_text_property_saves_store_text_and_numeric_properties_for_every_kind(self):
        self.assertIs(
            self.ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "1",
                        "text",
                        {
                            "Text": "New",
                            "FontName": "Courier",
                            "FontColor": "#00ff00",
                            "FontSize": "14",
                            "FontBold": 1,
                            "FontItalic": "yes",
                            "FontUnderline": 0,
                            "TextAlign": "2",
                        },
                    ),
                    (
                        "1",
                        "callout",
                        {"Text": "Call", "FontSize": "15", "TextAlign": "1"},
                    ),
                    ("1", "dimension", {"FontSize": "11", "FontBold": True}),
                    ("6", "namedview", {"Text": "renamed"}),
                ],
            ),
            True,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT Name, FontName, FontColor, FontSize, FontBold, FontItalic, "
                "FontUnderline, TextAlign FROM BidTexts"
            ).fetchall(),
            [(b"New", "Courier", 0x00FF00, 14, 1, 1, 0, 2)],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT Name, FontSize, TextAlign FROM BidCallOuts"
            ).fetchall(),
            [(b"Call", 15, 1)],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT FontName, FontSize, FontBold FROM BidDimensions"
            ).fetchall(),
            [("Arial", 11, 1)],
        )
        self.assertEqual(
            self.conn.execute("SELECT Name FROM BidNamedViews WHERE UID=6").fetchone(),
            ("renamed",),
        )

    def test_text_property_updates_hand_the_driver_python_typed_values(self):
        """Pins the Python types handed to the driver (BIT flags as bool, rest int)."""
        self.assertIs(
            self.ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "1",
                        "text",
                        {
                            "Text": "New",
                            "FontColor": "#00ff00",
                            "FontSize": "14",
                            "FontBold": 1,
                            "FontItalic": "yes",
                            "FontUnderline": 0,
                            "TextAlign": "2",
                        },
                    ),
                    (
                        "1",
                        "dimension",
                        {"FontColor": 7.0, "FontSize": "11", "FontBold": 1},
                    ),
                ],
            ),
            True,
        )
        self.assertEqual(
            [(type(value), value) for value in self.ops.bound("UPDATE [BidTexts]")],
            [
                (bytes, b"New"),
                (str, "Arial"),
                (int, 0x00FF00),
                (int, 14),
                (bool, True),
                (bool, True),
                (bool, False),
                (int, 2),
                (int, 1),
            ],
        )
        self.assertEqual(
            [
                (type(value), value)
                for value in self.ops.bound("UPDATE [BidDimensions]")
            ],
            [
                (str, "Arial"),
                (int, 7),
                (int, 11),
                (bool, True),
                (bool, False),
                (bool, False),
                (int, 1),
            ],
        )

    def test_inserts_bind_bid_page_layer_and_remapped_references_as_integers(self):
        remap = PasteRefRemap(takeoff_uids={"11": "21"}, namedview_uids={"4": "6"})
        new_uids = self.ops.insert_annotations(
            "bid.mdb",
            "1",
            [
                _strict_spec("rect"),
                _strict_spec("hotlink", BidPageViewUID="4"),
                _strict_spec("text", Text="hi", FontSize=14),
                _strict_spec("dimension", BidTakeoffFromUID="11", BidTakeoffToUID="0"),
                _strict_spec("highlight"),
            ],
            ref_remap=remap,
        )
        self.assertEqual(len(new_uids), 5)
        rect = self.ops.insert_bound("BidAnnotationRects")
        hotlink = self.ops.insert_bound("BidHotLinks")
        dimension = self.ops.insert_bound("BidDimensions")
        for label, bound, identifiers in (
            ("rect", rect, ("UID", "BidUID", "BidPageUID", "BidLayerUID", "Width")),
            (
                "hotlink",
                hotlink,
                ("UID", "BidUID", "BidPageUID", "BidLayerUID", "BidPageViewUID"),
            ),
            (
                "dimension",
                dimension,
                ("UID", "BidUID", "BidPageUID", "BidTakeoffFromUID"),
            ),
        ):
            for column in identifiers:
                with self.subTest(annotation=label, column=column):
                    self.assertIs(type(bound[column]), int)
        self.assertEqual(
            {
                key: rect[key]
                for key in ("BidUID", "BidPageUID", "BidLayerUID", "Width")
            },
            {"BidUID": 1, "BidPageUID": 3, "BidLayerUID": 9, "Width": 2},
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT BidPageViewUID, BidLayerUID FROM BidHotLinks WHERE UID<>30"
            ).fetchall(),
            [(6, 9)],
        )
        self.assertEqual(dimension["BidTakeoffFromUID"], 21)
        self.assertIsNone(dimension["BidTakeoffToUID"])

    def test_deletes_bind_every_uid_as_an_integer(self):
        self.assertIs(
            self.ops.delete_annotations(
                "bid.mdb", [("2", "rect"), ("6", "namedview"), ("30", "hotlink")]
            ),
            True,
        )
        self.assertEqual(
            self.conn.execute("SELECT UID FROM BidAnnotationRects").fetchall(), [(1,)]
        )
        self.assertEqual(
            self.conn.execute("SELECT UID FROM BidNamedViews").fetchall(), [(5,)]
        )
        self.assertEqual(
            self.conn.execute("SELECT UID FROM BidHotLinks").fetchall(), []
        )


class _InterruptedAnnotationOps(RealContractAnnotationOps):
    def _schema(self, _connection):
        raise KeyboardInterrupt()


class _NeverMissingSchema:
    """Like the real schema for an unknown table name: it never reports it missing."""

    def __init__(self, inner):
        self._inner = inner

    def optional_table_missing(self, _table):
        return False

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _NeverMissingSchemaAnnotationOps(RealContractAnnotationOps):
    def _schema(self, connection):
        return _NeverMissingSchema(super()._schema(connection))


class _ConnectionCountingAnnotationOps(RealContractAnnotationOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.opened = []

    def _connection(self, db_path):
        self.opened.append(db_path)
        return super()._connection(db_path)


class _AllocationRecordingAnnotationOps(_StrictParameterAnnotationOps):
    def __init__(self, connection):
        super().__init__(connection)
        self.allocations = []

    def _next_uids_preserving_references(self, cursor, schema, table, count):
        self.allocations.append((table, count))
        return super()._next_uids_preserving_references(cursor, schema, table, count)


class AnnotationOperationsErrorPolicyTests(unittest.TestCase):
    """What the mutating operations log and propagate when something goes wrong."""

    def test_an_interrupt_propagates_from_every_mutating_operation_without_a_log(self):
        for label, call in (
            (
                "positions",
                lambda ops: ops.save_annotation_positions(
                    "bid.mdb", [("1", "rect", [0.0, 0.0, 1.0, 1.0])]
                ),
            ),
            (
                "text properties",
                lambda ops: ops.save_annotation_text_properties(
                    "bid.mdb", [("1", "text", {"Text": "x"})]
                ),
            ),
            (
                "styles",
                lambda ops: ops.save_annotation_styles(
                    "bid.mdb", [("1", "rect", {"Color": 1})]
                ),
            ),
            (
                "insert",
                lambda ops: ops.insert_annotations(
                    "bid.mdb", "1", [_strict_spec("rect")]
                ),
            ),
            (
                "delete",
                lambda ops: ops.delete_annotations("bid.mdb", [("1", "rect")]),
            ),
        ):
            with self.subTest(label):
                conn = _strict_parameter_database()
                ops = _InterruptedAnnotationOps(conn)
                with self.assertNoLogs("test.annotation_write_support", level="ERROR"):
                    with self.assertRaises(KeyboardInterrupt):
                        call(ops)
                self.assertIs(conn.in_transaction, False)
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position FROM BidAnnotationRects ORDER BY UID"
                    ).fetchall(),
                    [(1, b"\x00"), (2, b"\x00")],
                )

    def test_each_failed_operation_logs_one_message_naming_the_operation_and_file(
        self,
    ):
        broken_rects = (
            "CREATE TABLE BidAnnotationRects (Foo INTEGER)",
            "INSERT INTO BidAnnotationRects VALUES (1)",
        )
        for label, ddl, call, expected_outcome, expected_message in (
            (
                "positions",
                broken_rects,
                lambda ops: ops.save_annotation_positions(
                    "bid.mdb", [("1", "rect", [0.0, 0.0, 1.0, 1.0])]
                ),
                False,
                "Failed to bulk save annotation positions in bid.mdb",
            ),
            (
                "text properties",
                ("CREATE TABLE BidTexts (Foo INTEGER)",),
                lambda ops: ops.save_annotation_text_properties(
                    "bid.mdb", [("1", "text", {"Text": "x"})]
                ),
                False,
                "Failed to bulk save annotation text properties in bid.mdb",
            ),
            (
                "styles",
                broken_rects,
                lambda ops: ops.save_annotation_styles(
                    "bid.mdb", [("1", "rect", {"Color": 1})]
                ),
                False,
                "Failed to bulk save annotation styles in bid.mdb",
            ),
            (
                "insert",
                ("CREATE TABLE Bids (UID INTEGER)",),
                lambda ops: ops.insert_annotations(
                    "bid.mdb", "1", [_strict_spec("rect")]
                ),
                [],
                "Failed to bulk insert annotations in bid.mdb",
            ),
            (
                "delete",
                broken_rects,
                lambda ops: ops.delete_annotations("bid.mdb", [("1", "rect")]),
                False,
                "Failed to bulk delete annotations in bid.mdb",
            ),
        ):
            with self.subTest(label):
                ops = RealContractAnnotationOps(annotation_database(*ddl))
                with self.assertLogs(
                    "test.annotation_write_support", level="ERROR"
                ) as logs:
                    outcome = call(ops)
                self.assertEqual(outcome, expected_outcome)
                self.assertIs(type(outcome), type(expected_outcome))
                self.assertEqual(
                    [record.getMessage() for record in logs.records], [expected_message]
                )

    def test_unsupported_types_are_rejected_with_the_exact_message(self):
        ops = ReraisingRealContractAnnotationOps(_strict_parameter_database())
        for label, call in (
            (
                "insert",
                lambda: ops.insert_annotations("bid.mdb", "1", [_strict_spec("bogus")]),
            ),
            (
                "delete",
                lambda: ops.delete_annotations("bid.mdb", [("1", "bogus")]),
            ),
        ):
            with self.subTest(label):
                with self.assertRaises(ValueError) as caught:
                    call()
                self.assertEqual(
                    str(caught.exception), "Unsupported annotation type: bogus"
                )

    def test_an_empty_insert_batch_never_opens_a_connection_or_logs(self):
        ops = _ConnectionCountingAnnotationOps(_strict_parameter_database())
        with self.assertNoLogs("test.annotation_write_support", level="ERROR"):
            self.assertEqual(ops.insert_annotations("bid.mdb", "1", []), [])
        self.assertEqual(ops.opened, [])

    def test_a_position_for_an_unknown_type_is_skipped_even_if_no_table_is_reported_missing(
        self,
    ):
        ops = _NeverMissingSchemaAnnotationOps(annotation_database())
        self.assertIs(
            ops.save_annotation_positions("bid.mdb", [("1", "bogus", [0.0, 0.0])]),
            True,
        )


class AnnotationOperationsValueEdgeTests(unittest.TestCase):
    """Reference validation scope, UID allocation sizes and numeric coercions."""

    def test_only_hot_links_validate_a_named_view_reference(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        self.assertEqual(
            ops.insert_annotations(
                "bid.mdb", "1", [_strict_spec("rect", BidPageViewUID="999")]
            ),
            ["3"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageUID FROM BidAnnotationRects ORDER BY UID"
            ).fetchall(),
            [(1, 3), (2, 3), (3, 3)],
        )

    def test_each_table_reserves_exactly_as_many_uids_as_it_receives_specs(self):
        ops = _AllocationRecordingAnnotationOps(_strict_parameter_database())
        specs = [
            _strict_spec("rect"),
            _strict_spec("text", Text="a"),
            _strict_spec("rect"),
            _strict_spec("rect"),
            _strict_spec("text", Text="b"),
        ]
        self.assertEqual(
            ops.insert_annotations("bid.mdb", "1", specs),
            ["3", "2", "4", "5", "3"],
        )
        self.assertEqual(ops.allocations, [("BidAnnotationRects", 3), ("BidTexts", 2)])

    def test_numeric_colours_are_bound_as_integers(self):
        ops = _StrictParameterAnnotationOps(_strict_parameter_database())
        self.assertIs(
            ops.save_annotation_styles(
                "bid.mdb",
                [("1", "rect", {"Color": 255.0}), ("2", "rect", {"Color": None})],
            ),
            True,
        )
        updates = ops.statements("UPDATE [BidAnnotationRects]")
        self.assertEqual(updates, [(255, 1), (0, 2)])
        self.assertEqual(
            [[type(value) for value in params] for params in updates],
            [[int, int], [int, int]],
        )
        self.assertEqual(
            ops.insert_annotations(
                "bid.mdb", "1", [_strict_spec("dimension", FontColor=7.0)]
            ),
            ["2"],
        )
        font_color = ops.insert_bound("BidDimensions")["FontColor"]
        self.assertEqual(font_color, 7)
        self.assertIs(type(font_color), int)

    def test_none_valued_text_properties_fall_back_to_the_documented_defaults(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    (
                        "1",
                        "text",
                        {
                            "Text": "Hi",
                            "FontName": None,
                            "FontColor": None,
                            "FontSize": None,
                            "FontBold": None,
                            "TextAlign": None,
                        },
                    )
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT FontName, FontColor, FontSize, FontBold, FontItalic, "
                "FontUnderline, TextAlign FROM BidTexts"
            ).fetchall(),
            [("Arial", 0, 12, 0, 0, 0, 0)],
        )


class AnnotationOperationsRequiredColumnTests(unittest.TestCase):
    """Every column a text or dimension update writes is required, one at a time."""

    def _missing_column_message(self, table, columns, update):
        conn = _database_with_bid(
            _annotation_table_ddl(table, columns),
            f"INSERT INTO {table} (UID, BidUID) VALUES (1, 1)",
        )
        ops = RealContractAnnotationOps(conn)
        with self.assertLogs("test.annotation_write_support", level="ERROR") as logs:
            self.assertIs(
                ops.save_annotation_text_properties("bid.mdb", [update]), False
            )
        return str(logs.records[0].exc_info[1])

    def test_a_text_or_callout_update_needs_every_text_column(self):
        text_columns = ("UID", "BidUID", "Name") + _FONT_COLUMNS + ("TextAlign",)
        for annotation_type, table in (
            ("text", "BidTexts"),
            ("callout", "BidCallOuts"),
        ):
            for missing in text_columns[2:]:
                with self.subTest(table=table, missing=missing):
                    columns = tuple(c for c in text_columns if c != missing)
                    self.assertEqual(
                        self._missing_column_message(
                            table,
                            columns,
                            ("1", annotation_type, {"Text": "x"}),
                        ),
                        f"Missing {table}.{missing}",
                    )

    def test_a_dimension_update_needs_every_font_column(self):
        for missing in _FONT_COLUMNS:
            with self.subTest(missing=missing):
                columns = ("UID", "BidUID") + tuple(
                    c for c in _FONT_COLUMNS if c != missing
                )
                self.assertEqual(
                    self._missing_column_message(
                        "BidDimensions",
                        columns,
                        ("1", "dimension", {"FontName": "Calibri"}),
                    ),
                    f"Missing BidDimensions.{missing}",
                )


class AnnotationOperationsHotLinkRemapTests(unittest.TestCase):
    def _hotlink_spec(self, target):
        return _strict_spec("hotlink", BidPageViewUID=target)

    def test_a_numeric_hot_link_target_is_remapped_through_its_text_key(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        self.assertEqual(
            ops.insert_annotations(
                "bid.mdb",
                "1",
                [self._hotlink_spec(6)],
                ref_remap=PasteRefRemap(namedview_uids={"6": "5"}),
            ),
            ["31"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, BidPageViewUID FROM BidHotLinks ORDER BY UID"
            ).fetchall(),
            [(30, 6), (31, 5)],
        )

    def test_the_remapped_hot_link_target_is_the_one_that_gets_validated(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        with self.assertRaisesRegex(
            RuntimeError, "BidNamedViews has no row for UID 999"
        ):
            ops.insert_annotations(
                "bid.mdb",
                "1",
                [self._hotlink_spec(6)],
                ref_remap=PasteRefRemap(namedview_uids={"6": "999"}),
            )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidHotLinks").fetchone()[0], 1
        )


class AnnotationOperationsRound3Tests(unittest.TestCase):
    """Uid coercion, callout styles, named-view positions and dependency chunking."""

    def test_padded_and_float_uids_are_accepted_by_position_saves_characterisation(
        self,
    ):
        # Characterisation of the current lenient coercion: int() runs before the
        # uid is validated, so " 1" and 1.0 address row 1.
        for uid in (" 1", 1.0, "1"):
            with self.subTest(uid=uid):
                conn = _strict_parameter_database()
                ops = _StrictParameterAnnotationOps(conn)
                self.assertIs(
                    ops.save_annotation_positions(
                        "bid.mdb", [(uid, "rect", [1.0, 2.0, 3.0, 4.0])]
                    ),
                    True,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT UID, Position FROM BidAnnotationRects ORDER BY UID"
                    ).fetchall(),
                    [(1, b"1.0;2.0;3.0;4.0\n"), (2, b"\x00")],
                )

    def test_a_non_numeric_uid_in_a_delete_fails_with_the_int_conversion_text(self):
        # Characterisation: the text comes from int(), not from the helper that
        # normalises uid collections.
        ops = ReraisingRealContractAnnotationOps(_strict_parameter_database())
        with self.assertRaises(ValueError) as caught:
            ops.delete_annotations("bid.mdb", [("abc", "rect")])
        self.assertEqual(
            str(caught.exception), "invalid literal for int() with base 10: 'abc'"
        )

    def test_callout_style_updates_write_color_and_width_not_the_font_colour(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_styles(
                "bid.mdb", [("1", "callout", {"Color": "#00ff00", "Width": "9.7"})]
            ),
            True,
        )
        self.assertEqual(
            ops.statements("UPDATE [BidCallOuts]"),
            [(0x00FF00, 9, 1)],
        )
        self.assertEqual(
            [
                " ".join(query.split())
                for query, _params in ops.executed
                if query.lstrip().startswith("UPDATE [BidCallOuts]")
            ],
            ["UPDATE [BidCallOuts] SET [Color]=?, [Width]=? WHERE [UID]=?"],
        )
        self.assertEqual(
            conn.execute(
                "SELECT Color, Width, FontColor, FontSize FROM BidCallOuts"
            ).fetchall(),
            [(0x00FF00, 9, 1, 12)],
        )

    def test_a_callout_colour_alone_leaves_the_width_untouched(self):
        conn = _strict_parameter_database()
        ops = _StrictParameterAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_styles("bid.mdb", [("1", "callout", {"Color": 255})]),
            True,
        )
        self.assertEqual(
            conn.execute("SELECT Color, Width, FontColor FROM BidCallOuts").fetchall(),
            [(255, 1, 1)],
        )

    def test_named_view_positions_are_stored_normalised_and_other_types_raw(self):
        conn = annotation_database(
            "CREATE TABLE Bids (UID INTEGER)",
            "INSERT INTO Bids VALUES (1)",
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER, Position BLOB)",
            "INSERT INTO BidNamedViews VALUES (3, 1, X'00')",
            "INSERT INTO BidNamedViews VALUES (4, 1, X'00')",
            "CREATE TABLE BidAnnotationRects "
            "(UID INTEGER, BidUID INTEGER, Position BLOB)",
            "INSERT INTO BidAnnotationRects VALUES (5, 1, X'00')",
        )
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_positions(
                "bid.mdb",
                [
                    ("3", "namedview", [1.0, 2.0, 13.0, 14.0]),
                    ("4", "namedview", [5.0, 6.0, 1.0, 2.0]),
                    ("5", "rect", [1.0, 2.0, 13.0, 14.0]),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT UID, Position FROM BidNamedViews ORDER BY UID"
            ).fetchall(),
            [
                (3, b"13.0;14.0;1.0;2.0;13.0;2.0;1.0;14.0;0.0\n"),
                (4, b"5.0;6.0;1.0;2.0;5.0;2.0;1.0;6.0;0.0\n"),
            ],
        )
        self.assertEqual(
            conn.execute("SELECT Position FROM BidAnnotationRects").fetchall(),
            [(b"1.0;2.0;13.0;14.0\n",)],
        )

    def test_the_named_view_dependency_lookup_is_chunked_like_the_delete(self):
        class LimitedAnnotationOps(
            AnnotationOperationsMixin, _ParameterLimitedSqliteOps
        ):
            pass

        count = 120
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE Bids (UID INTEGER)")
        conn.execute("INSERT INTO Bids VALUES (1)")
        conn.execute("CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER)")
        conn.execute(
            "CREATE TABLE BidHotLinks "
            "(UID INTEGER, BidUID INTEGER, BidPageViewUID INTEGER)"
        )
        conn.executemany(
            "INSERT INTO BidNamedViews VALUES (?, 1)",
            ((uid,) for uid in range(1, count + 1)),
        )
        conn.executemany(
            "INSERT INTO BidHotLinks VALUES (?, 1, ?)",
            ((1000 + uid, uid) for uid in range(1, count + 1)),
        )
        statements = []
        conn.set_trace_callback(statements.append)
        annotations = [(str(uid), "namedview") for uid in range(1, count + 1)] + [
            (str(1000 + uid), "hotlink") for uid in range(1, count + 1)
        ]
        self.assertIs(
            LimitedAnnotationOps(conn).delete_annotations("bid.mdb", annotations), True
        )
        lookups = [
            sql
            for sql in statements
            if sql.lstrip().startswith("SELECT [UID] FROM [BidHotLinks]")
        ]
        self.assertEqual(len(lookups), 3)
        for lookup in lookups:
            self.assertLessEqual(lookup.count(",") + 1, 50)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidNamedViews").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidHotLinks").fetchone()[0], 0
        )


class AnnotationOperationsTextValueTypeTests(unittest.TestCase):
    def test_numeric_text_properties_are_stored_as_text(self):
        conn = _strict_parameter_database()
        ops = RealContractAnnotationOps(conn)
        self.assertIs(
            ops.save_annotation_text_properties(
                "bid.mdb",
                [
                    ("5", "namedview", {"Text": 123}),
                    ("1", "text", {"Text": "t", "FontName": 77}),
                ],
            ),
            True,
        )
        self.assertEqual(
            conn.execute(
                "SELECT typeof(Name), Name FROM BidNamedViews WHERE UID=5"
            ).fetchall(),
            [("text", "123")],
        )
        self.assertEqual(
            conn.execute("SELECT typeof(FontName), FontName FROM BidTexts").fetchall(),
            [("text", "77")],
        )

    def test_a_named_view_delete_needs_the_hot_link_uid_column_itself(self):
        conn = _database_with_bid(
            "CREATE TABLE BidNamedViews (UID INTEGER, BidUID INTEGER)",
            "INSERT INTO BidNamedViews VALUES (1, 1)",
            "CREATE TABLE BidHotLinks (BidUID INTEGER, BidPageViewUID INTEGER)",
        )
        with self.assertRaises(RuntimeError) as caught:
            ReraisingRealContractAnnotationOps(conn).delete_annotations(
                "bid.mdb", [("1", "namedview")]
            )
        self.assertEqual(str(caught.exception), "Missing BidHotLinks.UID")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM BidNamedViews").fetchone()[0], 1
        )
