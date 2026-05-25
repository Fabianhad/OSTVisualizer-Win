import os
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QGraphicsPathItem, QGraphicsScene,
                               QGraphicsTextItem)

from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.layer import Layer
from ost_visualizer.domain.services.coordinate_transformation_service import \
    OSTCoordinateSystem
from ost_visualizer.infrastructure.mdb.components.annotation_operations import \
    AnnotationOperationsMixin
from ost_visualizer.infrastructure.mdb.components.annotation_reader import \
    AnnotationReaderMixin
from ost_visualizer.infrastructure.mdb.components.constants import \
    encode_position
from ost_visualizer.presentation.components.plan_view.components.graphics_items import \
    DIMENSION_LABEL_ITEM_KIND
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import \
    PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import \
    AnnotationItemRenderer
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry, format_dimension_distance)


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


class _Logger:
    def exception(self, *_args, **_kwargs):
        pass


class _SqliteCursorWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, query, *params):
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
        self.assertEqual(dimension.properties["BidTakeoffFromUID"], "11")
        self.assertEqual(dimension.properties["BidTakeoffToUID"], "12")

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

        self.assertEqual(rect, bbox)
        self.assertLessEqual(rect[0], 10.0)
        self.assertLessEqual(rect[1], -4.0)
        self.assertGreaterEqual(rect[2], 265.0)
        self.assertGreaterEqual(rect[3], 44.0)
        self.assertIn("/Matrix [ 1 0 0 1 ", ap_block)

    def test_native_pdf_export_dimension_ap_bounds_match_rect_and_ticks(self):
        dimension = self._native_dimension(10.0, 20.0, 265.0, 20.0, "21' - 3\"")
        dimension.width = 4.0
        dimension.font_size = 12.0
        pdf_text = self._write_native_pdf_with_dimension(dimension)

        dimension_block = self._annot_block_by_subject(pdf_text, "Length Measurement")
        rect = self._array_values(dimension_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, dimension_block)
        bbox = self._array_values(ap_block, "BBox")

        self.assertEqual(rect, bbox)
        self.assertLessEqual(rect[0], 10.0)
        self.assertLessEqual(rect[1], 15.0)
        self.assertGreaterEqual(rect[2], 265.0)
        self.assertGreaterEqual(rect[3], 25.0)
        self.assertIn("/Matrix [ 1 0 0 1 ", ap_block)

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

    def _array_values(self, object_block, key):
        match = re.search(rf"/{key}\s+\[\s*([^\]]+)\]", object_block)
        self.assertIsNotNone(match)
        return [float(value) for value in match.group(1).split()]

    def _annot_block_by_subject(self, pdf_text, subject):
        for annot_block in self._annotation_blocks(pdf_text):
            if f"/Subj ({subject})" in annot_block:
                return annot_block
        self.fail(f"Annotation with subject {subject!r} was not found")

    def _annotation_blocks(self, pdf_text):
        blocks = []
        for match in re.finditer(r"\d+\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL):
            object_body = match.group(1)
            if "/Type /Annot" in object_body:
                blocks.append(object_body)
        return blocks

    def _page_annotation_refs(self, pdf_text):
        page_to_annots = {}
        for match in re.finditer(r"(\d+)\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL):
            object_number = int(match.group(1))
            object_body = match.group(2)
            if "/Type /Page" not in object_body or "/Type /Pages" in object_body:
                continue
            annots_match = re.search(r"/Annots\s+\[\s*([^\]]*)\]", object_body)
            if annots_match is None:
                continue
            refs = [
                int(ref)
                for ref in re.findall(r"(\d+)\s+0\s+R", annots_match.group(1))
            ]
            page_to_annots[object_number] = refs
        return page_to_annots


if __name__ == "__main__":
    unittest.main()
