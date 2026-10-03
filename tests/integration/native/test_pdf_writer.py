import math
import os
import re
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from tests.paths import REPO_ROOT
from tests.integration.rendering.pdf_geometry_support import (
    _write_pdf as _pdf_geometry_support__write_pdf,
)


class NativePdfOvalAppearanceTests(unittest.TestCase):
    @staticmethod
    def _try_write_pdf(oval):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "oval.pdf"
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 500.0
            page.page_height = 400.0
            page.ovals = [oval]
            writer = ost_pdf_writer.PDFWriter()
            success = writer.merge_pages_with_annotations([page], str(output))
            pdf_text = (
                output.read_bytes().decode("latin-1", errors="ignore")
                if output.exists()
                else ""
            )
            return success, writer.get_last_error(), pdf_text

    def _write_pdf(self, oval):
        success, error, pdf_text = self._try_write_pdf(oval)
        self.assertTrue(success, error)
        return pdf_text

    @staticmethod
    def _object_block(pdf_text, object_number):
        match = re.search(
            rf"{object_number}\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
        )
        if match is None:
            raise AssertionError(f"PDF object {object_number} was not found")
        return match.group(1)

    def _annotation_and_appearance(self, pdf_text):
        annotation = next(
            match.group(1)
            for match in re.finditer(
                r"\d+\s+0\s+obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
            )
            if "/Subj (Ellipse)" in match.group(1)
        )
        ap_match = re.search(r"/AP\s+<<\s*/N\s+(\d+)\s+0\s+R", annotation)
        self.assertIsNotNone(ap_match)
        return annotation, self._object_block(pdf_text, int(ap_match.group(1)))

    def _array(self, block, key):
        match = re.search(rf"/{key}\s+\[\s*([^\]]+)\]", block)
        self.assertIsNotNone(match)
        return [float(value) for value in match.group(1).split()]

    def _border_width(self, annotation):
        match = re.search(r"/BS\s+<<.*?/W\s+(-?\d+(?:\.\d+)?)", annotation)
        self.assertIsNotNone(match)
        return float(match.group(1))

    def _stream(self, block):
        match = re.search(r"stream\r?\n(.*?)\r?\n?endstream", block, re.DOTALL)
        self.assertIsNotNone(match)
        data = match.group(1).encode("latin-1")
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        return data.decode("latin-1", errors="ignore")

    @staticmethod
    def _native_oval(*, stroke_width):
        angle = math.radians(30.0)
        oval = ost_pdf_writer.OvalAnnotationData()
        oval.center_x = 200.0
        oval.center_y = 250.0
        oval.x_axis_dx = 60.0 * math.cos(angle)
        oval.x_axis_dy = -60.0 * math.sin(angle)
        oval.y_axis_dx = -20.0 * math.sin(angle)
        oval.y_axis_dy = -20.0 * math.cos(angle)
        oval.color = [200, 50, 20]
        oval.width = stroke_width
        return oval

    def test_rotated_appearance_uses_transformed_radius_vectors(self):
        oval = self._native_oval(stroke_width=2.0)
        pdf_text = self._write_pdf(oval)
        _annotation, appearance = self._annotation_and_appearance(pdf_text)
        commands = self._stream(appearance)
        start_index = commands.index(" m ")
        start_prefix = commands[:start_index]
        start = [
            float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", start_prefix)[-2:]
        ]
        self.assertAlmostEqual(start[0], oval.center_x + oval.x_axis_dx, places=3)
        self.assertAlmostEqual(start[1], oval.center_y + oval.x_axis_dy, places=3)
        segments = [
            [float(value) for value in match]
            for match in re.findall(
                r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
                r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+"
                r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+c",
                commands,
            )
        ]
        self.assertEqual(len(segments), 4)
        expected_endpoints = (
            (oval.center_x + oval.y_axis_dx, oval.center_y + oval.y_axis_dy),
            (oval.center_x - oval.x_axis_dx, oval.center_y - oval.x_axis_dy),
            (oval.center_x - oval.y_axis_dx, oval.center_y - oval.y_axis_dy),
            (oval.center_x + oval.x_axis_dx, oval.center_y + oval.x_axis_dy),
        )
        for segment, endpoint in zip(segments, expected_endpoints):
            self.assertAlmostEqual(segment[4], endpoint[0], places=3)
            self.assertAlmostEqual(segment[5], endpoint[1], places=3)
        self.assertRegex(commands, r"c h S\s*$")

    def test_annotation_bounds_expand_by_half_stroke_without_changing_geometry(self):
        thin = self._native_oval(stroke_width=0.5)
        thick = self._native_oval(stroke_width=12.0)
        thin_text = self._write_pdf(thin)
        thick_text = self._write_pdf(thick)
        thin_annotation, thin_appearance = self._annotation_and_appearance(thin_text)
        thick_annotation, thick_appearance = self._annotation_and_appearance(thick_text)
        thin_rect = self._array(thin_annotation, "Rect")
        thick_rect = self._array(thick_annotation, "Rect")
        thin_bbox = self._array(thin_appearance, "BBox")
        thick_bbox = self._array(thick_appearance, "BBox")
        for rect_value, bbox_value in zip(thin_rect, thin_bbox):
            self.assertAlmostEqual(rect_value, bbox_value, places=3)
        for rect_value, bbox_value in zip(thick_rect, thick_bbox):
            self.assertAlmostEqual(rect_value, bbox_value, places=3)
        for low_index, high_index in ((0, 2), (1, 3)):
            self.assertAlmostEqual(
                thin_rect[low_index] - thick_rect[low_index], 5.75, places=4
            )
            self.assertAlmostEqual(
                thick_rect[high_index] - thin_rect[high_index], 5.75, places=4
            )
        x_extent = math.hypot(thick.x_axis_dx, thick.y_axis_dx)
        y_extent = math.hypot(thick.x_axis_dy, thick.y_axis_dy)
        expected_thick_rect = [
            thick.center_x - x_extent - 6.0,
            thick.center_y - y_extent - 6.0,
            thick.center_x + x_extent + 6.0,
            thick.center_y + y_extent + 6.0,
        ]
        for actual, expected in zip(thick_rect, expected_thick_rect):
            self.assertAlmostEqual(actual, expected, places=4)
        self.assertAlmostEqual(self._border_width(thick_annotation), 12.0)
        self.assertIn("/RD [ 6 6 6 6 ]", thick_annotation)
        thin_stream = self._stream(thin_appearance)
        thick_stream = self._stream(thick_appearance)
        self.assertEqual(
            re.sub(r"\b0\.5 w ", "WIDTH w ", thin_stream),
            re.sub(r"\b12 w ", "WIDTH w ", thick_stream),
        )

    def test_zero_and_very_small_strokes_remain_numeric_pdf_values(self):
        for stroke_width in (0.0, 1.0e-6):
            with self.subTest(stroke_width=stroke_width):
                pdf_text = self._write_pdf(self._native_oval(stroke_width=stroke_width))
                annotation, appearance = self._annotation_and_appearance(pdf_text)
                self.assertAlmostEqual(
                    self._border_width(annotation), stroke_width, places=12
                )
                for inset in self._array(annotation, "RD"):
                    self.assertAlmostEqual(inset, stroke_width / 2.0, places=12)
                stream = self._stream(appearance)
                self.assertNotRegex(stream.lower(), r"\d+e[+-]\d+")
                width_match = re.search(r"(-?\d+(?:\.\d+)?)\s+w\s", stream)
                self.assertIsNotNone(width_match)
                self.assertAlmostEqual(
                    float(width_match.group(1)), stroke_width, places=12
                )

    def test_large_coordinates_and_reversed_radius_vectors_are_supported(self):
        large = self._native_oval(stroke_width=2.0)
        large.center_x = 1_000_000.0
        large.center_y = -1_000_000.0
        large_text = self._write_pdf(large)
        large_annotation, _appearance = self._annotation_and_appearance(large_text)
        large_rect = self._array(large_annotation, "Rect")
        self.assertTrue(all(math.isfinite(value) for value in large_rect))
        # Independent bounds: centre -/+ the ellipse extents -/+ half the 2 pt stroke.
        large_x_extent = math.hypot(large.x_axis_dx, large.y_axis_dx)
        large_y_extent = math.hypot(large.x_axis_dy, large.y_axis_dy)
        for actual, expected in zip(
            large_rect,
            [
                1_000_000.0 - large_x_extent - 1.0,
                -1_000_000.0 - large_y_extent - 1.0,
                1_000_000.0 + large_x_extent + 1.0,
                -1_000_000.0 + large_y_extent + 1.0,
            ],
        ):
            self.assertAlmostEqual(actual, expected, places=2)
        normal = self._native_oval(stroke_width=2.0)
        reversed_x = self._native_oval(stroke_width=2.0)
        reversed_x.x_axis_dx *= -1.0
        reversed_x.x_axis_dy *= -1.0
        normal_annotation, _appearance = self._annotation_and_appearance(
            self._write_pdf(normal)
        )
        reversed_annotation, _appearance = self._annotation_and_appearance(
            self._write_pdf(reversed_x)
        )
        for normal_value, reversed_value in zip(
            self._array(normal_annotation, "Rect"),
            self._array(reversed_annotation, "Rect"),
        ):
            self.assertAlmostEqual(normal_value, reversed_value, places=4)

    def test_invalid_native_oval_data_fails_export(self):
        cases = (
            ("nonfinite center", "center_x", math.nan),
            ("nonfinite radius", "x_axis_dx", math.inf),
            ("zero radius", "x_axis_dx", 0.0),
            ("negative stroke", "width", -1.0),
            ("nonfinite stroke", "width", math.nan),
        )
        for name, field, value in cases:
            with self.subTest(name=name):
                oval = self._native_oval(stroke_width=2.0)
                setattr(oval, field, value)
                if name == "zero radius":
                    oval.x_axis_dy = 0.0
                success, error, _pdf_text = self._try_write_pdf(oval)
                self.assertFalse(success)
                self.assertIn("Oval", error)


class PdfWriterAnnotationValidationTests(unittest.TestCase):
    def setUp(self):
        source_root = REPO_ROOT / "cpp_extensions" / "src"
        source_paths = (
            source_root / "module_pdf_writer.cpp",
            source_root / "common" / "page_transform.hpp",
            source_root / "pdf" / "pdf_writer.cpp",
            source_root / "pdf" / "pdf_writer.hpp",
            source_root / "pdf" / "bluebeam_annotation.cpp",
            source_root / "pdf" / "bluebeam_annotation.hpp",
        )
        binary_path = Path(ost_pdf_writer.__file__)
        if any(
            path.stat().st_mtime > binary_path.stat().st_mtime for path in source_paths
        ):
            self.skipTest("ost_pdf_writer must be rebuilt for native source changes")

    def test_empty_polygon_returns_failure_instead_of_accessing_missing_vertex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "blank.pdf"
            writer = ost_pdf_writer.PDFWriter()
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 72.0
            page.page_height = 72.0
            polygon = ost_pdf_writer.PolygonAnnotationData()
            polygon.vertices = []
            page.takeoffs = [polygon]
            self.assertFalse(writer.merge_pages_with_annotations([page], str(pdf_path)))
            self.assertIn("must contain vertices", writer.get_last_error())

    def test_page_export_contract_rejects_incomplete_or_conflicting_geometry(self):
        cases = []
        unconfigured = ost_pdf_writer.PageExportData()
        unconfigured.is_blank = True
        cases.append((unconfigured, "canonical dimensions"))
        missing_source = ost_pdf_writer.PageExportData()
        missing_source.page_width = 72.0
        missing_source.page_height = 72.0
        missing_source.source_width = 72.0
        missing_source.source_height = 72.0
        cases.append((missing_source, "require a source PDF"))
        conflicting_blank = ost_pdf_writer.PageExportData()
        conflicting_blank.is_blank = True
        conflicting_blank.source_pdf = "not-a-blank-page.pdf"
        conflicting_blank.page_width = 72.0
        conflicting_blank.page_height = 72.0
        cases.append((conflicting_blank, "must not specify a source PDF"))
        mismatched_rotation = ost_pdf_writer.PageExportData()
        mismatched_rotation.source_pdf = "not-opened-before-validation.pdf"
        mismatched_rotation.source_width = 72.0
        mismatched_rotation.source_height = 144.0
        mismatched_rotation.page_width = 72.0
        mismatched_rotation.page_height = 144.0
        mismatched_rotation.rotation = 90
        cases.append((mismatched_rotation, "do not match source dimensions"))
        invalid_rotation = ost_pdf_writer.PageExportData()
        invalid_rotation.is_blank = True
        invalid_rotation.page_width = 72.0
        invalid_rotation.page_height = 72.0
        invalid_rotation.rotation = 45
        cases.append((invalid_rotation, "multiple of 90"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "invalid.pdf"
            for page, message in cases:
                with self.subTest(message=message):
                    writer = ost_pdf_writer.PDFWriter()
                    self.assertFalse(
                        writer.merge_pages_with_annotations([page], str(output_path))
                    )
                    self.assertIn(message, writer.get_last_error())

    def test_page_export_requires_at_least_one_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = ost_pdf_writer.PDFWriter()
            output_path = Path(temp_dir) / "empty.pdf"
            self.assertFalse(writer.merge_pages_with_annotations([], str(output_path)))
            self.assertIn("at least one page", writer.get_last_error())

    def test_empty_ink_strokes_return_failure_instead_of_accessing_missing_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "blank.pdf"
            writer = ost_pdf_writer.PDFWriter()
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = 72.0
            page.page_height = 72.0
            ink = ost_pdf_writer.InkAnnotationData()
            ink.strokes = [[]]
            page.inks = [ink]
            self.assertFalse(writer.merge_pages_with_annotations([page], str(pdf_path)))
            self.assertIn("must contain points", writer.get_last_error())

    def test_highlight_contract_rejects_empty_or_nonfinite_data(self):
        valid_path = [
            (0.0, 0.0),
            (0.0, 10.0),
            (0.0, 10.0),
            (10.0, 10.0),
            (10.0, 10.0),
            (10.0, 0.0),
            (10.0, 0.0),
            (0.0, 0.0),
        ]
        cases = []
        empty = ost_pdf_writer.HighlightAnnotationData()
        empty.paths = []
        cases.append((empty, "must contain paths"))
        nonfinite_coordinate = ost_pdf_writer.HighlightAnnotationData()
        nonfinite_coordinate.paths = [
            [
                (float("nan"), y) if index == 0 else (x, y)
                for index, (x, y) in enumerate(valid_path)
            ]
        ]
        cases.append((nonfinite_coordinate, "coordinates must be finite"))
        nonfinite_opacity = ost_pdf_writer.HighlightAnnotationData()
        nonfinite_opacity.paths = [valid_path]
        nonfinite_opacity.opacity = float("nan")
        cases.append((nonfinite_opacity, "opacity must be finite"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "invalid-highlight.pdf"
            for highlight, message in cases:
                with self.subTest(message=message):
                    writer = ost_pdf_writer.PDFWriter()
                    page = ost_pdf_writer.PageExportData()
                    page.is_blank = True
                    page.page_width = 72.0
                    page.page_height = 72.0
                    page.highlights = [highlight]
                    self.assertFalse(
                        writer.merge_pages_with_annotations([page], str(output_path))
                    )
                    self.assertIn(message, writer.get_last_error())


class NativePdfPageGeometryTests(unittest.TestCase):
    def test_native_geometry_rejects_invalid_rotation_and_user_unit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, options, message in (
                ("rotation", {"rotation": 45}, "multiple of 90"),
                ("user-unit", {"user_unit": 0.0}, "invalid /UserUnit"),
                (
                    "crop-box",
                    {"crop_box": (10.0, 10.0, 10.0, 20.0)},
                    "degenerate /CropBox",
                ),
            ):
                with self.subTest(name=name):
                    source_path = Path(temp_dir) / f"invalid-{name}.pdf"
                    _pdf_geometry_support__write_pdf(
                        source_path, 600.0, 800.0, **options
                    )
                    writer = ost_pdf_writer.PDFWriter()
                    self.assertEqual(writer.get_page_geometries(str(source_path)), [])
                    self.assertIn(message, writer.get_last_error())

    def test_native_geometry_accepts_valid_boundary_and_normalized_values(self):
        cases = (
            ("negative-rotation", {"rotation": -90}, 270, (0.0, 0.0, 600.0, 800.0)),
            ("large-rotation", {"rotation": 450}, 90, (0.0, 0.0, 600.0, 800.0)),
            (
                "user-unit-limit",
                {"user_unit": 75000.0},
                0,
                (0.0, 0.0, 600.0, 800.0),
            ),
            (
                "partly-outside-crop",
                {"crop_box": (-50.0, -60.0, 100.0, 120.0)},
                0,
                (0.0, 0.0, 100.0, 120.0),
            ),
            (
                "reversed-crop",
                {"crop_box": (500.0, 700.0, 100.0, 200.0)},
                0,
                (100.0, 200.0, 500.0, 700.0),
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for name, options, rotation, visible_box in cases:
                with self.subTest(name=name):
                    source_path = Path(temp_dir) / f"valid-{name}.pdf"
                    _pdf_geometry_support__write_pdf(
                        source_path, 600.0, 800.0, **options
                    )
                    writer = ost_pdf_writer.PDFWriter()
                    geometries = writer.get_page_geometries(str(source_path))
                    self.assertEqual(len(geometries), 1, writer.get_last_error())
                    self.assertEqual(geometries[0].rotation, rotation)
                    self.assertEqual(tuple(geometries[0].visible_box), visible_box)
