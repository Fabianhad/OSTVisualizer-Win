import os
import re
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.application.dtos.insert_annotation_spec_dto import (
    InsertAnnotationSpec,
)
from ost_visualizer.infrastructure.mdb.components.annotation_operations import (
    AnnotationOperationsMixin,
)
from ost_visualizer.infrastructure.mdb.components.annotation_reader import (
    AnnotationReaderMixin,
)
from ost_visualizer.infrastructure.mdb.components.constants import encode_position
from ost_visualizer.presentation.components.plan_view.components.graphics_items import (
    DIMENSION_LABEL_ITEM_KIND,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
    format_dimension_distance,
)


class _FakeCursor:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.last_query = ""

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def execute(self, query, *_params):
        self.last_query = query

    def fetchall(self):
        for table, rows in self.rows_by_table.items():
            if table in self.last_query:
                return rows
        return []


class _FakeConnection:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table

    def cursor(self):
        return _FakeCursor(self.rows_by_table)


class _Reader(AnnotationReaderMixin):
    pass


class _Schema:
    def optional_table_missing(self, _table):
        return False

    def column_exists(self, _table, _column):
        return True


class _Logger:
    def exception(self, *_args, **_kwargs):
        pass


class _SqliteCursorWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, query, *params):
        if len(params) == 1 and isinstance(params[0], (list, tuple)):
            params = tuple(params[0])
        self._cursor = self._conn.execute(query, params)

    def fetchone(self):
        if self._cursor is None:
            return None
        return self._cursor.fetchone()


class _SqliteConnectionWrapper:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        if exc_type is None:
            self._conn.commit()
        return False

    def cursor(self):
        return _SqliteCursorWrapper(self._conn)


class _DimensionWriteOps(AnnotationOperationsMixin):
    logger = _Logger()

    def __init__(self, conn):
        self._conn = conn

    def _connection(self, _db_path):
        return _SqliteConnectionWrapper(self._conn)

    def _schema(self, _conn):
        return _Schema()

    def _require_write_columns(self, _schema, _table, _columns):
        pass

    def _execute_insert_values(
        self,
        cursor,
        _schema,
        table,
        values,
        required_columns,
        _operation,
    ):
        missing = [column for column in required_columns if column not in values]
        if missing:
            raise AssertionError(f"missing required columns: {missing}")
        col_list = ", ".join(f"[{column}]" for column in values)
        placeholders = ", ".join("?" for _ in values)
        cursor.execute(
            f"INSERT INTO [{table}] ({col_list}) VALUES ({placeholders})",
            list(values.values()),
        )


class _ColorService:
    def hex_to_rgb_int(self, color):
        text = color.lstrip("#")
        return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]


def _page_info():
    return {
        "scale_factor1": 1.0,
        "scale_factor2": 72.0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
        "width": 612.0,
        "height": 792.0,
        "view_scale": 1.0,
    }


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bid_dimensions_are_read_as_dimension_annotations(self):
        row = SimpleNamespace(
            UID=7,
            BidPageUID=3,
            BidTakeoffFromUID=11,
            BidTakeoffToUID=12,
            Position=encode_position([0.0, 0.0, 255.0, 0.0]),
            FontName="Arial",
            FontColor=255,
            FontSize=10,
            FontBold=False,
            FontItalic=False,
            FontUnderline=False,
        )
        annotations = _Reader()._parse_bid_annotations_for_bid(
            _FakeConnection({"BidDimensions": [row]}),
            "1",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
        )
        dimensions = [ann for ann in annotations if ann.is_dimension]
        self.assertEqual(len(dimensions), 1)
        dimension = dimensions[0]
        self.assertEqual(dimension.uid, "7")
        self.assertEqual(dimension.page_uid, "3")
        self.assertEqual(dimension.position, [0.0, 0.0, 255.0, 0.0])
        self.assertEqual(dimension.color, "#ff0000")
        self.assertEqual(dimension.width, 1.0)
        self.assertEqual(dimension.properties["BidTakeoffFromUID"], "11")
        self.assertEqual(dimension.properties["BidTakeoffToUID"], "12")

    def test_placeable_annotation_shapes_reload_from_existing_tables(self):
        rows_by_table = {
            "BidALines": [
                SimpleNamespace(
                    UID=11,
                    BidPageUID=3,
                    BidTakeoffFromUID=None,
                    BidTakeoffToUID=None,
                    Position=encode_position([0.0, 0.0, 10.0, 10.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidArrows": [
                SimpleNamespace(
                    UID=12,
                    BidPageUID=3,
                    BidTakeoffFromUID=None,
                    BidTakeoffToUID=None,
                    Position=encode_position([1.0, 2.0, 13.0, 14.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationRects": [
                SimpleNamespace(
                    UID=13,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([1.0, 2.0, 13.0, 14.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationOvals": [
                SimpleNamespace(
                    UID=14,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([2.0, 3.0, 14.0, 15.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationPolygons": [
                SimpleNamespace(
                    UID=15,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([0.0, 0.0, 12.0, 0.0, 6.0, 8.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnotationClouds": [
                SimpleNamespace(
                    UID=16,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position([1.0, 1.0, 13.0, 1.0, 7.0, 9.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidAnnoInk": [
                SimpleNamespace(
                    UID=18,
                    BidPageUID=3,
                    Position=encode_position([0.0, 0.0, 5.0, 5.0, 10.0, 0.0]),
                    Color=255,
                    Width=2,
                )
            ],
            "BidHighlights": [
                SimpleNamespace(
                    UID=17,
                    BidPageUID=3,
                    BidLayerUID=99,
                    Position=encode_position(
                        [3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0]
                    ),
                    Color=0x00FFFF,
                )
            ],
        }
        annotations = _Reader()._parse_bid_annotations_for_bid(
            _FakeConnection(rows_by_table),
            "1",
            {"99": Layer(uid="99", name="Annotation", visible=True)},
        )
        by_type = {ann.annotation_type: ann for ann in annotations}
        self.assertEqual(
            set(by_type),
            {
                "line",
                "arrow",
                "rect",
                "oval",
                "polygon",
                "cloud",
                "ink",
                "highlight",
            },
        )
        self.assertEqual(by_type["arrow"].position, [1.0, 2.0, 13.0, 14.0])
        self.assertEqual(by_type["highlight"].color, "#ffff00")
        self.assertEqual(by_type["highlight"].width, 0.0)
        self.assertEqual(
            by_type["polygon"].position,
            [0.0, 0.0, 12.0, 0.0, 6.0, 8.0],
        )
        self.assertEqual(by_type["ink"].position, [0.0, 0.0, 5.0, 5.0, 10.0, 0.0])
        self.assertFalse(by_type["line"].properties)

    def test_dimension_distance_uses_existing_feet_inches_rounding(self):
        self.assertEqual(format_dimension_distance(255.0), "21' - 3\"")
        self.assertEqual(format_dimension_distance(18.0), "1' - 6\"")
        self.assertEqual(format_dimension_distance(6.0), '6"')

    def test_horizontal_dimension_renders_line_ticks_and_centered_text(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("d1", annotation)], _page_info(), "p1"
        )
        items = [item for item, _link in results]
        self.assertEqual(len(items), 2)
        self.assertIsInstance(items[0], QGraphicsPathItem)
        self.assertIsInstance(items[1], QGraphicsTextItem)
        self.assertEqual(items[1].toPlainText(), "21' - 3\"")
        self.assertEqual(items[1].data(2), DIMENSION_LABEL_ITEM_KIND)
        self.assertEqual(items[0].path().elementCount(), 6)
        self.assertEqual(items[0].pen().widthF(), 1.0)
        self.assertEqual([item.data(0) for item in uid_to_items["d1"]], ["d1", "d1"])

    def test_vertical_dimension_renders_perpendicular_ticks(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d2",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 0.0, 120.0],
            color="#00aa00",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d2", annotation)], _page_info(), "p1"
        )
        path = results[0][0].path()
        tick_start = path.elementAt(2)
        tick_end = path.elementAt(3)
        self.assertAlmostEqual(tick_start.y, tick_end.y)
        self.assertNotAlmostEqual(tick_start.x, tick_end.x)
        self.assertEqual(results[1][0].toPlainText(), "10' - 0\"")

    def test_angled_dimension_renders_without_crashing(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d3",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 36.0, 48.0],
            color="#0000ff",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d3", annotation)], _page_info(), "p1"
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "5' - 0\"")

    def test_missing_scale_data_is_graceful(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d4",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 12.0, 0.0],
            color="#000000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d4", annotation)],
            {"scale_factor1": 0.0, "scale_factor2": 0.0, "view_scale": 0.0},
            "p1",
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][0].toPlainText(), "1' - 0\"")

    def test_bid_aline_rendering_remains_a_single_line_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="l1",
            annotation_type="line",
            page_uid="p1",
            position=[0.0, 0.0, 24.0, 0.0],
            color="#ff0000",
            width=2.0,
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("l1", annotation)], _page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsPathItem)
        self.assertEqual(results[0][0].path().elementCount(), 2)

    def test_dimension_text_and_ticks_are_selectable_scene_items(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="d5",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        results, _uid_to_items = renderer.create_all_annotation_items(
            [("d5", annotation)], _page_info(), "p1"
        )
        scene = QGraphicsScene()
        for item, _link in results:
            scene.addItem(item)
        text_item = results[1][0]
        hit_items = scene.items(text_item.mapToScene(text_item.boundingRect().center()))
        self.assertIn("d5", [item.data(0) for item in hit_items])

    def test_pdf_export_collects_dimensions_as_native_dimension_data(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _ColorService()
        annotation = BidAnnotation(
            uid="d6",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        lines = exporter._collect_lines("p1", [annotation], _page_info())
        dimensions = exporter._collect_dimensions("p1", [annotation], _page_info())
        texts = exporter._collect_texts("p1", [annotation], _page_info())
        expected_coords = OSTCoordinateSystem.ost_to_pdf_coordinates(
            [0.0, 0.0, 255.0, 0.0], _page_info()
        )
        self.assertEqual(len(lines), 0)
        self.assertEqual(len(texts), 0)
        self.assertEqual(len(dimensions), 1)
        self.assertEqual(dimensions[0].content, "21' - 3\"")
        actual_coords = [
            [dimensions[0].x1, dimensions[0].y1],
            [dimensions[0].x2, dimensions[0].y2],
        ]
        self.assertEqual(actual_coords, expected_coords)

    def test_pdf_export_collects_text_alignment_from_ost_numeric_values(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _ColorService()

        def annotation(uid, align):
            return BidAnnotation(
                uid=uid,
                annotation_type="text",
                page_uid="p1",
                position=[60.0, 80.0, 40.0, 20.0],
                color="#000000",
                properties={"Text": uid, "TextAlign": align},
            )

        texts = exporter._collect_texts(
            "p1",
            [
                annotation("left", 0),
                annotation("center", 1),
                annotation("right", 2),
            ],
            _page_info(),
        )
        self.assertEqual(
            [text.text_align for text in texts], ["left", "center", "right"]
        )

    def test_pdf_export_skips_invisible_text_annotations(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _ColorService()
        hidden = BidAnnotation(
            uid="hidden",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#000000",
            properties={"Text": "Hidden"},
            visible=False,
        )
        self.assertEqual(exporter._collect_texts("p1", [hidden], _page_info()), [])

    def test_pdf_export_skips_takeoffs_on_hidden_conditions(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._takeoff_service = SimpleNamespace(
            group_area_takeoffs_with_holes=lambda takeoffs, _conditions: (takeoffs, {})
        )
        takeoff = Takeoff(
            uid="t1",
            condition_uid="c1",
            page_uid="p1",
            position=[10.0, 20.0],
        )
        condition = Condition(
            uid="c1",
            condition_type=Condition.TYPE_COUNT,
            width=12.0,
            layer_visible=False,
        )
        takeoffs = exporter._collect_takeoffs(
            [takeoff],
            {"c1": condition},
            _page_info(),
        )
        self.assertEqual(takeoffs, [])

    def test_pdf_export_collects_highlights_as_native_highlight_data(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _ColorService()
        annotation = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 20.0, 110.0, 60.0],
            color="#ffff00",
        )
        highlights = exporter._collect_highlights("p1", [annotation], _page_info())
        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].strokes,
            [[[10.0, 752.0], [110.0, 752.0]]],
        )
        self.assertAlmostEqual(highlights[0].width, 40.0)
        self.assertEqual(highlights[0].color, [255, 255, 0])
        self.assertAlmostEqual(highlights[0].opacity, 1.0)

    def test_pdf_export_collects_rotated_highlight_corners_in_pdf_quad_order(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _ColorService()
        annotation = BidAnnotation(
            uid="h2",
            annotation_type="highlight",
            page_uid="p1",
            position=[110.0, 60.0, 10.0, 20.0, 110.0, 20.0, 10.0, 60.0],
            color="#00ff00",
        )
        highlights = exporter._collect_highlights("p1", [annotation], _page_info())
        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].strokes,
            [[[10.0, 752.0], [110.0, 752.0]]],
        )
        self.assertAlmostEqual(highlights[0].width, 40.0)

    def test_dimension_label_style_persists_to_bid_dimensions_font_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute(
            """
            CREATE TABLE BidDimensions (
                UID INTEGER PRIMARY KEY,
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
                (UID, FontName, FontColor, FontSize, FontBold, FontItalic, FontUnderline)
            VALUES (7, 'Arial', 0, 10, 0, 0, 0)
            """
        )
        ops = _DimensionWriteOps(conn)
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

    def test_placeable_annotation_shapes_insert_through_annotation_write_path(self):
        conn = sqlite3.connect(":memory:")
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
                Position BLOB
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
                    "FontSize": 12,
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
                    "FontSize": 12,
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
        new_uids = _DimensionWriteOps(conn).insert_annotations("bid.mdb", "1", specs)
        self.assertEqual(new_uids, ["1"] * 12)
        expected_tables = {
            "BidALines": "line",
            "BidArrows": "arrow",
            "BidAnnoInk": "ink",
            "BidAnnotationRects": "rect",
            "BidAnnotationOvals": "oval",
            "BidAnnotationPolygons": "polygon",
            "BidAnnotationClouds": "cloud",
        }
        for table, annotation_type in expected_tables.items():
            with self.subTest(annotation_type=annotation_type):
                row = conn.execute(
                    f"SELECT BidUID, BidPageUID, Color, Width FROM {table}"
                ).fetchone()
                self.assertEqual(row, (1, 3, 255, 2))
        highlight_row = conn.execute(
            "SELECT BidUID, BidPageUID, Color, Position FROM BidHighlights"
        ).fetchone()
        self.assertEqual(highlight_row[:3], (1, 3, 0x00FFFF))
        self.assertEqual(
            highlight_row[3],
            encode_position([3.0, 4.0, 15.0, 4.0, 15.0, 16.0, 3.0, 16.0]),
        )
        dimension_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, FontName, FontColor, FontSize
              FROM BidDimensions
            """
        ).fetchone()
        self.assertEqual(dimension_row, (1, 3, "Arial", 255, 12))
        text_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, FontName, FontColor, FontSize, TextAlign, Position
              FROM BidTexts
            """
        ).fetchone()
        self.assertEqual(text_row[:6], (1, 3, "Arial", 0x996633, 12, 0))
        self.assertEqual(
            text_row[6].encode("latin-1"),
            encode_position([7.0, 8.0, 12.0, 12.0]),
        )
        named_view_row = conn.execute(
            "SELECT BidUID, BidPageUID, Name, Color, Position FROM BidNamedViews"
        ).fetchone()
        self.assertEqual(named_view_row[:4], (1, 3, "Lobby", 32768))
        self.assertEqual(
            named_view_row[4],
            encode_position([13.0, 14.0, 1.0, 2.0, 13.0, 2.0, 1.0, 14.0, 0.0]),
        )
        hotlink_row = conn.execute(
            """
            SELECT BidUID, BidPageUID, BidPageViewUID, Color, Position
              FROM BidHotLinks
            """
        ).fetchone()
        self.assertEqual(hotlink_row[:4], (1, 3, 1, 255))
        self.assertEqual(hotlink_row[4], encode_position([5.0, 6.0]))

    def test_annotation_style_updates_are_per_annotation_and_per_type(self):
        conn = sqlite3.connect(":memory:")
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
                Position BLOB
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
        ops = _DimensionWriteOps(conn)
        ops.insert_annotations("bid.mdb", "1", specs)
        updates = [
            ("1", annotation_type, {"Color": "#00aa00", "Width": 6.0})
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
                self.assertEqual(rows, [(1, 0x00AA00, 6), (2, 0xFF0000, 4)])
        dimension_rows = conn.execute(
            "SELECT UID, FontColor FROM BidDimensions ORDER BY UID"
        ).fetchall()
        self.assertEqual(dimension_rows, [(1, 0x00AA00), (2, 0xFF0000)])
        text_rows = conn.execute(
            "SELECT UID, FontColor FROM BidTexts ORDER BY UID"
        ).fetchall()
        self.assertEqual(text_rows, [(1, 0x00AA00), (2, 0xFF0000)])
        highlight_rows = conn.execute(
            "SELECT UID, Color FROM BidHighlights ORDER BY UID"
        ).fetchall()
        self.assertEqual(highlight_rows, [(1, 0x00AA00), (2, 0xFF0000)])

    def test_delete_annotations_removes_hotlinks_before_named_views(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            CREATE TABLE BidNamedViews (
                UID INTEGER PRIMARY KEY,
                Name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE BidHotLinks (
                UID INTEGER PRIMARY KEY,
                BidPageViewUID INTEGER REFERENCES BidNamedViews(UID)
            )
            """
        )
        conn.execute("INSERT INTO BidNamedViews (UID, Name) VALUES (1, 'Lobby')")
        conn.execute("INSERT INTO BidHotLinks (UID, BidPageViewUID) VALUES (1, 1)")
        result = _DimensionWriteOps(conn).delete_annotations(
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

    def test_renderer_uses_annotation_color_not_global_default_style(self):
        from ost_visualizer.presentation.utils.annotation_defaults import (
            set_annotation_style_for_tool,
        )

        annotation = BidAnnotation(
            uid="a1",
            annotation_type="rect",
            position=[1.0, 2.0, 13.0, 14.0],
            color="#336699",
            width=4.0,
        )
        set_annotation_style_for_tool("rect", color="#ff0000", line_width=9.0)
        try:
            geometry = calculate_annotation_geometry(
                annotation,
                lambda position: list(position),
            )
            self.assertEqual(geometry["color"], "#336699")
            self.assertEqual(geometry["width"], 4.0)
        finally:
            set_annotation_style_for_tool("rect", color="#ff0000", line_width=4.0)

    def test_empty_text_annotation_renders_editable_text_item(self):
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        annotation = BidAnnotation(
            uid="text-1",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#336699",
            properties={"Text": "", "FontName": "Arial", "FontSize": 12},
        )
        results, uid_to_items = renderer.create_all_annotation_items(
            [("text-1", annotation)], _page_info(), "p1"
        )
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0][0], QGraphicsTextItem)
        self.assertEqual(results[0][0].toPlainText(), "")
        self.assertEqual(uid_to_items["text-1"], [results[0][0]])

    def test_native_pdf_export_writes_horizontal_line_dimension_annotation(self):
        pdf_text = self._write_native_pdf_with_dimension(
            self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        )
        self.assertIn("/Subtype /Line", pdf_text)
        self.assertIn("/IT /LineDimension", pdf_text)
        self.assertIn("/Subj (Length Measurement)", pdf_text)
        self.assertRegex(pdf_text, r"/L \[\s*10\s+20\s+265\s+20\s*\]")
        self.assertIn("/LE [ /ClosedArrow /ClosedArrow ]", pdf_text)
        self.assertIn("/LL 10", pdf_text)
        self.assertIn("/LLE 2", pdf_text)
        self.assertIn("/Cap true", pdf_text)
        self.assertIn("/MeasurementTypes 130", pdf_text)
        self.assertIn("/SlopeType 1", pdf_text)
        self.assertIn("/Label ()", pdf_text)
        self.assertIn("/DepthUnit [", pdf_text)
        self.assertIn("/U (mm)", pdf_text)
        self.assertIn("/C 0.3527778", pdf_text)
        self.assertIn("/Contents (21' - 3\")", pdf_text)
        self.assertIn("/RC (<?xml", pdf_text)
        self.assertIn("/AP <<", pdf_text)
        self.assertRegex(pdf_text, r"/Measure \d+ 0 R")
        self.assertIn("/VP [", pdf_text)
        self.assertIn("/Type /Viewport", pdf_text)

    def test_native_pdf_export_dimension_page_reference_matches_page_object(self):
        pdf_text = self._write_native_pdf_with_dimension(
            self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        )
        page_to_annots = self._page_annotation_refs(pdf_text)
        self.assertEqual(len(page_to_annots), 1)
        page_object, annot_objects = next(iter(page_to_annots.items()))
        self.assertEqual(len(annot_objects), 1)
        annot_block = self._object_block(pdf_text, annot_objects[0])
        self.assertIn("/IT /LineDimension", annot_block)
        self.assertRegex(annot_block, rf"/P\s+{page_object}\s+0\s+R")

    def test_native_pdf_export_dimensions_on_multiple_pages_reference_their_pages(self):
        first = self._blank_page(400.0, 300.0)
        first.dimensions = [
            self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        ]
        second = self._blank_page(500.0, 350.0)
        second.dimensions = [
            self._native_dimension(20.0, 30.0, 220.0, 30.0, "16' - 8\"")
        ]
        pdf_text = self._write_native_pdf_pages([first, second])
        page_to_annots = self._page_annotation_refs(pdf_text)
        self.assertEqual(len(page_to_annots), 2)
        for page_object, annot_objects in page_to_annots.items():
            self.assertEqual(len(annot_objects), 1)
            annot_block = self._object_block(pdf_text, annot_objects[0])
            self.assertIn("/IT /LineDimension", annot_block)
            self.assertRegex(annot_block, rf"/P\s+{page_object}\s+0\s+R")

    def test_native_pdf_export_supported_annotations_reference_their_pages(self):
        first = self._blank_page(400.0, 300.0)
        first.arrows = [self._native_arrow()]
        first.rects = [self._native_rect()]
        first.lines = [self._native_line()]
        first.texts = [self._native_text("First page", "center")]
        first.highlights = [self._native_highlight()]
        second = self._blank_page(500.0, 350.0)
        second.ovals = [self._native_oval()]
        second.polygons = [self._native_polygon()]
        second.inks = [self._native_ink()]
        second.texts = [self._native_text("Second page", "right")]
        pdf_text = self._write_native_pdf_pages([first, second])
        page_to_annots = self._page_annotation_refs(pdf_text)
        self.assertEqual(len(page_to_annots), 2)
        for page_object, annot_objects in page_to_annots.items():
            self.assertGreater(len(annot_objects), 0)
            for annot_object in annot_objects:
                annot_block = self._object_block(pdf_text, annot_object)
                self.assertRegex(annot_block, rf"/P\s+{page_object}\s+0\s+R")

    def test_native_pdf_export_writes_bluebeam_like_supported_annotation_fields(self):
        pdf_text = self._write_native_pdf(
            arrows=[self._native_arrow()],
            rects=[self._native_rect()],
            lines=[self._native_line()],
            ovals=[self._native_oval()],
            polygons=[self._native_polygon()],
            inks=[self._native_ink()],
            texts=[self._native_text("Centered note", "center")],
        )
        arrow_block = self._annot_block_by_subject(pdf_text, "Arrow")
        self.assertIn("/Subtype /Line", arrow_block)
        self.assertIn("/IT /LineArrow", arrow_block)
        self.assertIn("/LE [ /None /ClosedArrow ]", arrow_block)
        line_block = self._annot_block_by_subject(pdf_text, "Line")
        self.assertIn("/Subtype /Line", line_block)
        self.assertIn("/LE [ /None /None ]", line_block)
        self.assertNotIn("/IT /LineDimension", line_block)
        rect_block = self._annot_block_by_subject(pdf_text, "Rectangle")
        self.assertIn("/Subtype /Square", rect_block)
        self.assertIn("/RD [ 2 2 2 2 ]", rect_block)
        oval_block = self._annot_block_by_subject(pdf_text, "Ellipse")
        self.assertIn("/Subtype /Circle", oval_block)
        self.assertIn("/RD [ 0.5 0.5 0.5 0.5 ]", oval_block)
        polygon_block = self._annot_block_by_subject(pdf_text, "Polygon")
        self.assertIn("/Subtype /Polygon", polygon_block)
        self.assertIn("/Vertices [", polygon_block)
        ink_block = self._annot_block_by_subject(pdf_text, "Pen")
        self.assertIn("/Subtype /Ink", ink_block)
        self.assertIn("/InkList [", ink_block)
        text_block = self._annot_block_by_subject(pdf_text, "Text Box")
        self.assertIn("/Subtype /FreeText", text_block)
        self.assertIn("/Contents (Centered note)", text_block)
        self.assertIn("/RC (<?xml", text_block)
        self.assertIn("/Q 1", text_block)
        self.assertIn("text-align:center", text_block)
        self.assertGreaterEqual(pdf_text.count("/AP <<"), 7)

    def test_native_pdf_export_writes_highlight_annotation_fields(self):
        pdf_text = self._write_native_pdf(highlights=[self._native_highlight()])
        highlight_block = self._annot_block_by_subject(pdf_text, "Highlight")
        self.assertIn("/Subtype /Ink", highlight_block)
        self.assertIn("/BM /Multiply", highlight_block)
        self.assertIn("/InkList [ [ 10 65 120 65 ] ]", highlight_block)
        self.assertIn("/Rect [ -17 38 147 92 ]", highlight_block)
        self.assertIn("/C [ 1 1 0 ]", highlight_block)
        self.assertIn("/BS << /S /S /Type /Border /W 50 >>", highlight_block)
        self.assertIn("/NM (", highlight_block)
        self.assertIn("/AP <<", highlight_block)
        self.assertNotIn("/QuadPoints", highlight_block)
        ap_block = self._ap_block_for_annotation(pdf_text, highlight_block)
        self.assertIn("/BM /Multiply", ap_block)
        self.assertIn("/CA 1", ap_block)
        stream_text = self._stream_text(ap_block)
        self.assertIn("/R0 gs", stream_text)
        self.assertIn("1 1 0 RG", stream_text)
        self.assertIn("50 w 1 j 1 J", stream_text)
        self.assertIn("10 65 m 120 65 l S", stream_text)

    def test_native_pdf_export_highlights_on_multiple_pages_reference_their_pages(self):
        first = self._blank_page(400.0, 300.0)
        first.highlights = [self._native_highlight()]
        second = self._blank_page(500.0, 350.0)
        second_highlight = self._native_highlight()
        second_highlight.strokes = [[[20.0, 100.0], [140.0, 100.0]]]
        second_highlight.width = 40.0
        second.highlights = [second_highlight]
        pdf_text = self._write_native_pdf_pages([first, second])
        page_to_annots = self._page_annotation_refs(pdf_text)
        self.assertEqual(len(page_to_annots), 2)
        for page_object, annot_objects in page_to_annots.items():
            self.assertEqual(len(annot_objects), 1)
            annot_block = self._object_block(pdf_text, annot_objects[0])
            self.assertIn("/Subtype /Ink", annot_block)
            self.assertIn("/BM /Multiply", annot_block)
            self.assertRegex(annot_block, rf"/P\s+{page_object}\s+0\s+R")

    def test_native_pdf_export_arrow_ap_bounds_include_drawn_arrowhead(self):
        arrow = self._native_arrow()
        arrow.x1 = 10.0
        arrow.y1 = 20.0
        arrow.x2 = 265.0
        arrow.y2 = 20.0
        arrow.width = 4.0
        pdf_text = self._write_native_pdf(arrows=[arrow])
        arrow_block = self._annot_block_by_subject(pdf_text, "Arrow")
        rect = self._array_values(arrow_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, arrow_block)
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        self.assertLessEqual(rect[0], 10.0)
        self.assertLessEqual(rect[1], -4.0)
        self.assertGreaterEqual(rect[2], 265.0)
        self.assertGreaterEqual(rect[3], 44.0)

    def test_native_pdf_export_line_ap_bounds_match_rect_and_drawn_line(self):
        line = self._native_line()
        line.x1 = 10.0
        line.y1 = 20.0
        line.x2 = 265.0
        line.y2 = 20.0
        line.width = 4.0
        pdf_text = self._write_native_pdf(lines=[line])
        line_block = self._annot_block_by_subject(pdf_text, "Line")
        rect = self._array_values(line_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, line_block)
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        self.assertLessEqual(rect[0], 10.0)
        self.assertLessEqual(rect[1], 20.0)
        self.assertGreaterEqual(rect[2], 265.0)
        self.assertGreaterEqual(rect[3], 20.0)
        self.assertIn("/LE [ /None /None ]", line_block)

    def test_native_pdf_export_dimension_ap_bounds_match_rect_and_ticks(self):
        dimension = self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        dimension.width = 4.0
        dimension.font_size = 12.0
        pdf_text = self._write_native_pdf_with_dimension(dimension)
        dimension_block = self._annot_block_by_subject(pdf_text, "Length Measurement")
        rect = self._array_values(dimension_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, dimension_block)
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        self.assertLessEqual(rect[0], 10.0)
        self.assertLessEqual(rect[1], 15.0)
        self.assertGreaterEqual(rect[2], 265.0)
        self.assertGreaterEqual(rect[3], 25.0)

    def test_native_pdf_export_writes_bluebeam_style_dimension_measure_scale(self):
        dimension = self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        dimension.scale_factor1 = 0.09375
        dimension.scale_factor2 = 12.0
        pdf_text = self._write_native_pdf_with_dimension(dimension)
        self.assertIn("/R (0,09375 in = 1 ft' in\")", pdf_text)
        self.assertRegex(pdf_text, r"/X\s*\[\s*<<[^>]+/C\s+0\.148148")

    def test_native_pdf_export_omits_measure_when_scale_is_invalid(self):
        dimension = self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        dimension.scale_factor1 = 0.0
        dimension.scale_factor2 = 0.0
        pdf_text = self._write_native_pdf_with_dimension(dimension)
        self.assertIn("/IT /LineDimension", pdf_text)
        self.assertNotRegex(pdf_text, r"/Measure \d+ 0 R")
        self.assertNotIn("/VP [", pdf_text)

    def test_native_pdf_export_writes_vertical_line_dimension_annotation(self):
        pdf_text = self._write_native_pdf_with_dimension(
            self._native_dimension(100.0, 25.0, 100.0, 145.0, "10' - 0\"")
        )
        self.assertRegex(pdf_text, r"/L \[\s*100\s+25\s+100\s+145\s*\]")
        self.assertIn("/IT /LineDimension", pdf_text)
        self.assertIn("/Contents (10' - 0\")", pdf_text)

    def test_native_pdf_export_writes_angled_dimension_with_sane_rect(self):
        pdf_text = self._write_native_pdf_with_dimension(
            self._native_dimension(25.0, 50.0, 85.0, 130.0, "8' - 4\"")
        )
        self.assertIn("/IT /LineDimension", pdf_text)
        rect_values = self._first_rect(pdf_text)
        self.assertEqual(len(rect_values), 4)
        self.assertLess(rect_values[0], rect_values[2])
        self.assertLess(rect_values[1], rect_values[3])

    def test_native_pdf_export_leaves_bid_aline_as_plain_line_annotation(self):
        pdf_text = self._write_native_pdf(lines=[self._native_line()])
        self.assertIn("/Subtype /Line", pdf_text)
        self.assertIn("/Subj (Line)", pdf_text)
        self.assertIn("/LE [ /None /None ]", pdf_text)
        self.assertNotIn("/IT /LineDimension", pdf_text)

    def test_native_pdf_export_leaves_text_annotation_unchanged(self):
        pdf_text = self._write_native_pdf(texts=[self._native_text("Note", "left")])
        self.assertIn("/Subtype /FreeText", pdf_text)
        self.assertIn("/Subj (Text Box)", pdf_text)
        self.assertIn("/Q 0", pdf_text)
        self.assertNotIn("/IT /LineDimension", pdf_text)

    def test_native_pdf_export_text_appearance_wraps_inside_textbox(self):
        text = self._native_text(
            "Alpha beta gamma delta epsilon zeta eta theta iota", "left"
        )
        text.max_x = 90.0
        text.max_y = 110.0
        pdf_text = self._write_native_pdf(texts=[text])
        text_block = self._annot_block_by_subject(pdf_text, "Text Box")
        ap_block = self._ap_block_for_annotation(pdf_text, text_block)
        rect = self._array_values(text_block, "Rect")
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        stream_text = self._stream_text(ap_block)
        self.assertIn("10 20 80 90 re W n", stream_text)
        self.assertGreaterEqual(stream_text.count(") Tj"), 3)
        self.assertNotIn(
            "(Alpha beta gamma delta epsilon zeta eta theta iota) Tj",
            stream_text,
        )

    def test_dimension_geometry_is_ignored_when_position_is_invalid(self):
        geometry = calculate_annotation_geometry(
            BidAnnotation(uid="bad", annotation_type="dimension", position=[0.0, 0.0]),
            lambda values: values,
        )
        self.assertNotIn("dimension", geometry)

    def _native_dimension(self, x1, y1, x2, y2, content):
        dimension = ost_pdf_writer.DimensionAnnotationData()
        dimension.x1 = x1
        dimension.y1 = y1
        dimension.x2 = x2
        dimension.y2 = y2
        dimension.color = [255, 0, 0]
        dimension.width = 1.0
        dimension.content = content
        dimension.font_size = 10.0
        dimension.scale_factor1 = 1.0
        dimension.scale_factor2 = 72.0
        return dimension

    def _native_arrow(self):
        arrow = ost_pdf_writer.ArrowAnnotationData()
        arrow.x1 = 10.0
        arrow.y1 = 20.0
        arrow.x2 = 110.0
        arrow.y2 = 80.0
        arrow.color = [255, 0, 0]
        arrow.width = 1.5
        return arrow

    def _native_rect(self):
        rect = ost_pdf_writer.RectAnnotationData()
        rect.min_x = 25.0
        rect.min_y = 30.0
        rect.max_x = 125.0
        rect.max_y = 90.0
        rect.color = [0, 128, 255]
        rect.width = 2.0
        return rect

    def _native_line(self):
        line = ost_pdf_writer.LineAnnotationData()
        line.x1 = 10.0
        line.y1 = 20.0
        line.x2 = 265.0
        line.y2 = 20.0
        line.color = [255, 0, 0]
        line.width = 1.0
        return line

    def _native_oval(self):
        oval = ost_pdf_writer.OvalAnnotationData()
        oval.min_x = 35.0
        oval.min_y = 40.0
        oval.max_x = 135.0
        oval.max_y = 100.0
        oval.color = [0, 180, 90]
        oval.width = 1.0
        return oval

    def _native_polygon(self):
        polygon = ost_pdf_writer.PolygonAnnotationAnnotData()
        polygon.vertices = [[30.0, 30.0], [90.0, 35.0], [70.0, 95.0]]
        polygon.color = [128, 64, 255]
        polygon.width = 1.0
        polygon.is_cloud = False
        return polygon

    def _native_ink(self):
        ink = ost_pdf_writer.InkAnnotationData()
        ink.strokes = [[[20.0, 20.0], [40.0, 45.0], [70.0, 30.0]]]
        ink.color = [50, 50, 50]
        ink.width = 1.0
        return ink

    def _native_text(self, content, align):
        text = ost_pdf_writer.TextAnnotationData()
        text.min_x = 10.0
        text.min_y = 20.0
        text.max_x = 170.0
        text.max_y = 55.0
        text.content = content
        text.font_size = 12.0
        text.color = [0, 0, 0]
        text.text_align = align
        return text

    def _native_highlight(self):
        highlight = ost_pdf_writer.HighlightAnnotationData()
        highlight.strokes = [[[10.0, 65.0], [120.0, 65.0]]]
        highlight.color = [255, 255, 0]
        highlight.width = 50.0
        highlight.opacity = 1.0
        highlight.content = ""
        return highlight

    def _write_native_pdf_with_dimension(self, dimension):
        return self._write_native_pdf(dimensions=[dimension])

    def _write_native_pdf(
        self,
        dimensions=None,
        arrows=None,
        rects=None,
        lines=None,
        ovals=None,
        polygons=None,
        inks=None,
        texts=None,
        highlights=None,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "dimension_export.pdf"
            page = self._blank_page(400.0, 300.0)
            page.dimensions = dimensions or []
            page.arrows = arrows or []
            page.rects = rects or []
            page.lines = lines or []
            page.ovals = ovals or []
            page.polygons = polygons or []
            page.inks = inks or []
            page.texts = texts or []
            page.highlights = highlights or []
            writer = ost_pdf_writer.PDFWriter()
            self.assertTrue(
                writer.merge_pages_with_annotations([page], str(output_path)),
                writer.get_last_error(),
            )
            return output_path.read_bytes().decode("latin-1", errors="ignore")

    def _blank_page(self, width, height):
        page = ost_pdf_writer.PageExportData()
        page.is_blank = True
        page.page_width = width
        page.page_height = height
        return page

    def _write_native_pdf_pages(self, pages):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "dimension_export.pdf"
            writer = ost_pdf_writer.PDFWriter()
            self.assertTrue(
                writer.merge_pages_with_annotations(pages, str(output_path)),
                writer.get_last_error(),
            )
            return output_path.read_bytes().decode("latin-1", errors="ignore")

    def _first_rect(self, pdf_text):
        match = re.search(r"/Rect \[\s*([^\]]+)\]", pdf_text)
        self.assertIsNotNone(match)
        return [float(value) for value in match.group(1).split()]

    def _object_block(self, pdf_text, object_number):
        match = re.search(
            rf"{object_number}\s+0\s+obj\s*(.*?)\s*endobj",
            pdf_text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def _ap_block_for_annotation(self, pdf_text, annot_block):
        match = re.search(r"/AP\s+<<\s*/N\s+(\d+)\s+0\s+R\s*>>", annot_block)
        self.assertIsNotNone(match)
        return self._object_block(pdf_text, int(match.group(1)))

    def _stream_text(self, object_block):
        match = re.search(r"stream\r?\n(.*?)\r?\n?endstream", object_block, re.DOTALL)
        self.assertIsNotNone(match)
        stream_data = match.group(1).encode("latin-1")
        try:
            stream_data = zlib.decompress(stream_data)
        except zlib.error:
            pass
        return stream_data.decode("latin-1", errors="ignore")

    def _array_values(self, object_block, key):
        match = re.search(rf"/{key}\s+\[\s*([^\]]+)\]", object_block)
        self.assertIsNotNone(match)
        return [float(value) for value in match.group(1).split()]

    def _assert_ap_rect_bbox_and_matrix_match(self, rect, bbox, ap_block):
        self.assertEqual(rect, bbox)
        matrix = self._array_values(ap_block, "Matrix")
        self.assertEqual(matrix[:4], [1.0, 0.0, 0.0, 1.0])
        self.assertAlmostEqual(matrix[4], -rect[0])
        self.assertAlmostEqual(matrix[5], -rect[1])

    def _annot_block_by_subject(self, pdf_text, subject):
        for annot_block in self._annotation_blocks(pdf_text):
            if f"/Subj ({subject})" in annot_block:
                return annot_block
        self.fail(f"Annotation with subject {subject!r} was not found")

    def _annotation_blocks(self, pdf_text):
        blocks = []
        for match in re.finditer(
            r"\d+\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
        ):
            object_body = match.group(1)
            if "/Type /Annot" in object_body:
                blocks.append(object_body)
        return blocks

    def _page_annotation_refs(self, pdf_text):
        page_to_annots = {}
        for match in re.finditer(
            r"(\d+)\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
        ):
            object_number = int(match.group(1))
            object_body = match.group(2)
            if "/Type /Page" not in object_body or "/Type /Pages" in object_body:
                continue
            annots_match = re.search(r"/Annots\s+\[\s*([^\]]*)\]", object_body)
            if annots_match is None:
                continue
            refs = [
                int(ref) for ref in re.findall(r"(\d+)\s+0\s+R", annots_match.group(1))
            ]
            page_to_annots[object_number] = refs
        return page_to_annots


if __name__ == "__main__":
    unittest.main()
