import os
import re
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    CLOUD_SCALLOP_SIZE_SCALE,
    calculate_annotation_geometry,
    calculate_cloud_scallop_radius,
    calculate_highlight_quad_path,
    create_cloud_path_points,
    format_dimension_distance,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        subjects_by_page = []
        for page_object, annot_objects in sorted(page_to_annots.items()):
            self.assertGreater(len(annot_objects), 0)
            subjects = []
            for annot_object in annot_objects:
                annot_block = self._object_block(pdf_text, annot_object)
                self.assertRegex(annot_block, rf"/P\s+{page_object}\s+0\s+R")
                subjects.append(re.search(r"/Subj \((.*?)\)", annot_block).group(1))
            subjects_by_page.append(sorted(subjects))
        # Each page owns exactly the annotations it was given, no more, no less.
        self.assertEqual(
            subjects_by_page,
            [
                ["Arrow", "Highlight", "Line", "Rectangle", "Text Box"],
                ["Ellipse", "Pen", "Polygon", "Text Box"],
            ],
        )

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

    def test_native_pdf_export_sf_only_caption_preserves_existing_text_and_style(self):
        takeoff = self._native_takeoff(
            1234.5,
            caption_lines=["1,234.50 sf"],
            measurement_types=1,
        )
        pdf_text = self._write_native_pdf(takeoffs=[takeoff])
        self.assertIn("/Contents (1,234.50 sf)", pdf_text)
        self.assertIn("/MeasurementTypes 1", pdf_text)
        self.assertIn(
            "font: Helvetica 12pt; text-align:center; line-height:13.8pt", pdf_text
        )
        self.assertNotIn("<p>cu yd", pdf_text)
        self.assertNotIn("<p>V = ", pdf_text)

    def test_native_pdf_export_disabled_caption_emits_no_caption_text(self):
        pdf_text = self._write_native_pdf(takeoffs=[self._native_takeoff(1234.5)])
        self.assertIn("/Cap false", pdf_text)
        self.assertIn("/Contents ()", pdf_text)
        self.assertIn("/Label ()", pdf_text)
        self.assertIn("/MeasurementTypes 0", pdf_text)
        self.assertNotIn("1,234.50 sf", pdf_text)
        self.assertNotIn("/RC (<?xml", pdf_text)

    def test_native_pdf_export_cy_only_caption_uses_resolved_text(self):
        takeoff = self._native_takeoff(
            1234.5,
            caption_lines=["V = 45.72 cu yd"],
            measurement_types=4,
        )
        pdf_text = self._write_native_pdf(takeoffs=[takeoff])
        self.assertIn("/Contents (V = 45.72 cu yd)", pdf_text)
        self.assertIn("/MeasurementTypes 4", pdf_text)
        self.assertIn("<p>V = 45.72 cu yd</p>", pdf_text)
        self.assertNotIn("1,234.50 sf", pdf_text)

    def test_native_pdf_export_multiple_captions_keep_resolved_order_and_geometry(self):
        takeoff = self._native_takeoff(
            1234.5,
            caption_lines=[
                "01 - Existing takeoff",
                "A = 1,234.50 sf",
                "V = 45.72 cu yd",
            ],
            measurement_types=133,
            caption_label="01 - Existing takeoff",
        )
        pdf_text = self._write_native_pdf(takeoffs=[takeoff])
        self.assertIn(
            "/Contents (01 - Existing takeoff\\rA = 1,234.50 sf\\rV = 45.72 cu yd)",
            pdf_text,
        )
        self.assertIn("/Label (01 - Existing takeoff)", pdf_text)
        self.assertLess(
            pdf_text.index("<p>01 - Existing takeoff</p>"),
            pdf_text.index("<p>A = 1,234.50 sf</p>"),
        )
        self.assertLess(
            pdf_text.index("<p>A = 1,234.50 sf</p>"),
            pdf_text.index("<p>V = 45.72 cu yd</p>"),
        )
        block = self._annot_block_by_subject(pdf_text, "Area Measurement")
        self.assertIn("/Vertices [ 30 30 130 30 130 100 30 100 ]", block)
        self.assertIn("/IC [ 1 0 0 ]", block)
        self.assertIn("/FillOpacity 0.5", block)

    def test_native_pdf_export_writes_cloud_appearance_as_curves(self):
        pdf_text = self._write_native_pdf(polygons=[self._native_cloud()])
        cloud_block = self._annot_block_by_subject(pdf_text, "Cloud")
        self.assertIn("/Subtype /Polygon", cloud_block)
        self.assertIn("/IT /PolygonCloud", cloud_block)
        self.assertRegex(cloud_block, r"/BE\s+<<[^>]*?/S\s+/C")
        self.assertRegex(cloud_block, r"/BE\s+<<[^>]*?/I\s+2")
        self.assertRegex(cloud_block, r"/BS\s+<<[^>]*?/W\s+2")
        rect = self._array_values(cloud_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, cloud_block)
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        stream_text = self._stream_text(ap_block)
        self.assertIn(" c ", stream_text)
        self.assertIn("1 j 1 J", stream_text)
        self.assertNotIn(" l ", stream_text)

    def test_native_pdf_export_keeps_regular_polygon_appearance_straight(self):
        pdf_text = self._write_native_pdf(polygons=[self._native_polygon()])
        polygon_block = self._annot_block_by_subject(pdf_text, "Polygon")
        self.assertIn("/Subtype /Polygon", polygon_block)
        self.assertNotIn("/IT /PolygonCloud", polygon_block)
        self.assertNotIn("/BE <<", polygon_block)
        ap_block = self._ap_block_for_annotation(pdf_text, polygon_block)
        stream_text = self._stream_text(ap_block)
        self.assertIn(" l ", stream_text)
        self.assertNotIn(" c ", stream_text)

    def test_native_pdf_export_writes_highlight_annotation_fields(self):
        pdf_text = self._write_native_pdf(highlights=[self._native_highlight()])
        highlight_block = self._annot_block_by_subject(pdf_text, "Highlight")
        self.assertIn("/Subtype /Highlight", highlight_block)
        self.assertIn("/BM /Multiply", highlight_block)
        self.assertIn("/QuadPoints [ 10 90 120 90 10 40 120 40 ]", highlight_block)
        self.assertIn("/C [ 1 1 0 ]", highlight_block)
        self.assertIn("/CA 1", highlight_block)
        self.assertIn("/NM (", highlight_block)
        self.assertIn("/AP <<", highlight_block)
        self.assertNotIn("/InkList", highlight_block)
        self.assertNotIn("/BS <<", highlight_block)
        rect = self._array_values(highlight_block, "Rect")
        ap_block = self._ap_block_for_annotation(pdf_text, highlight_block)
        bbox = self._array_values(ap_block, "BBox")
        self._assert_ap_rect_bbox_and_matrix_match(rect, bbox, ap_block)
        self.assertIn("/BM /Multiply", ap_block)
        self.assertIn("/CA 1", ap_block)
        self.assertIn("/ca 1", ap_block)
        stream_text = self._stream_text(ap_block)
        self.assertIn("/R0 gs", stream_text)
        self.assertIn("1 1 0 rg", stream_text)
        self.assertIn("10 90 m 120 90 l", stream_text)
        self.assertEqual(stream_text.count(" c "), 2)
        self.assertIn(" c f ", stream_text)
        self.assertNotIn(" S", stream_text)

    def test_native_pdf_export_highlights_on_multiple_pages_reference_their_pages(self):
        first = self._blank_page(400.0, 300.0)
        first.highlights = [self._native_highlight()]
        second = self._blank_page(500.0, 350.0)
        second_highlight = self._native_highlight()
        second_highlight.paths = [
            calculate_highlight_quad_path(
                ((20.0, 120.0), (140.0, 120.0), (20.0, 80.0), (140.0, 80.0))
            )
        ]
        second.highlights = [second_highlight]
        pdf_text = self._write_native_pdf_pages([first, second])
        page_to_annots = self._page_annotation_refs(pdf_text)
        self.assertEqual(len(page_to_annots), 2)
        for page_object, annot_objects in page_to_annots.items():
            self.assertEqual(len(annot_objects), 1)
            annot_block = self._object_block(pdf_text, annot_objects[0])
            self.assertIn("/Subtype /Highlight", annot_block)
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
        oval.center_x = 85.0
        oval.center_y = 70.0
        oval.x_axis_dx = 50.0
        oval.x_axis_dy = 0.0
        oval.y_axis_dx = 0.0
        oval.y_axis_dy = 30.0
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

    def _native_cloud(self):
        cloud = ost_pdf_writer.PolygonAnnotationAnnotData()
        cloud.vertices = [
            [30.0, 30.0],
            [130.0, 30.0],
            [130.0, 130.0],
            [30.0, 130.0],
        ]
        cloud.color = [128, 64, 255]
        cloud.width = 2.0
        cloud.is_cloud = True
        return cloud

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
        highlight.paths = [
            calculate_highlight_quad_path(
                ((10.0, 90.0), (120.0, 90.0), (10.0, 40.0), (120.0, 40.0))
            )
        ]
        highlight.color = [255, 255, 0]
        highlight.opacity = 1.0
        highlight.content = ""
        return highlight

    def _native_takeoff(
        self,
        area_sf,
        caption_lines=None,
        measurement_types=0,
        caption_label="",
    ):
        takeoff = ost_pdf_writer.PolygonAnnotationData()
        takeoff.vertices = [
            [30.0, 30.0],
            [130.0, 30.0],
            [130.0, 100.0],
            [30.0, 100.0],
        ]
        takeoff.holes = []
        takeoff.color = [255, 0, 0]
        takeoff.fill_opacity = 0.5
        takeoff.area_sf = area_sf
        takeoff.scale_factor1 = 1.0
        takeoff.scale_factor2 = 1.0
        takeoff.depth = 1.0
        caption = ost_pdf_writer.AnnotationCaptionData()
        caption.lines = [] if caption_lines is None else caption_lines
        caption.label = caption_label
        caption.measurement_types = measurement_types
        takeoff.caption = caption
        return takeoff

    def _write_native_pdf_with_dimension(self, dimension):
        return self._write_native_pdf(dimensions=[dimension])

    def _write_native_pdf(
        self,
        takeoffs=None,
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
            page.takeoffs = takeoffs or []
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
