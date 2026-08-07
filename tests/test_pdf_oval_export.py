import math
import os
import re
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QGraphicsPathItem
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.components.plan_view.components.selection_manager import (
    SelectionManagerMixin,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_item_renderer import (
    AnnotationItemRenderer,
)


class _ColorService:
    @staticmethod
    def hex_to_rgb_int(color):
        color = color.lstrip("#")
        return [int(color[index : index + 2], 16) for index in (0, 2, 4)]


def _page_info(**overrides):
    result = {
        "scale_factor1": 1.0,
        "scale_factor2": 72.0,
        "rotation": 0,
        "flip_x": False,
        "flip_y": False,
        "width": 500.0,
        "height": 400.0,
        "view_scale": 1.0,
        "coord_offset_x": 0.0,
        "coord_offset_y": 0.0,
    }
    result.update(overrides)
    return result


def _rotated_oval_position(cx, cy, width, height, rotation_deg):
    rotation = math.radians(rotation_deg)
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    position = []
    for dx, dy in ((-width / 2.0, -height / 2.0), (width / 2.0, height / 2.0)):
        position.extend([cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r])
    position.append(rotation)
    return position


def _oval_axis_points(annotation):
    geometry = annotation.get_oval_geometry_ost()
    if geometry is None:
        raise AssertionError("Expected valid oval geometry")
    center_x, center_y, radius_x, radius_y, rotation = geometry
    cos_r = math.cos(rotation)
    sin_r = math.sin(rotation)
    return [
        center_x,
        center_y,
        center_x + radius_x * cos_r,
        center_y + radius_x * sin_r,
        center_x - radius_y * sin_r,
        center_y + radius_y * cos_r,
    ]


class PdfOvalCollectionTests(unittest.TestCase):
    GEOMETRY_FIELDS = (
        "center_x",
        "center_y",
        "x_axis_dx",
        "x_axis_dy",
        "y_axis_dx",
        "y_axis_dy",
    )

    def setUp(self):
        self.exporter = PDFExporter.__new__(PDFExporter)
        self.exporter._coord_system = OSTCoordinateSystem()
        self.exporter._color_service = _ColorService()

    @staticmethod
    def _annotation(position, *, width=2.0, annotation_type="oval"):
        return BidAnnotation(
            uid="annotation",
            annotation_type=annotation_type,
            page_uid="page",
            position=position,
            color="#123456",
            width=width,
        )

    def _collect(self, position, page_info=None, *, width=2.0):
        result = self.exporter._collect_ovals(
            "page", [self._annotation(position, width=width)], page_info or _page_info()
        )
        self.assertEqual(len(result), 1)
        return result[0]

    def assertOvalGeometry(self, oval, *, center, x_axis, y_axis, stroke_width=2.0):
        self.assertAlmostEqual(oval.center_x, center[0])
        self.assertAlmostEqual(oval.center_y, center[1])
        self.assertAlmostEqual(oval.x_axis_dx, x_axis[0])
        self.assertAlmostEqual(oval.x_axis_dy, x_axis[1])
        self.assertAlmostEqual(oval.y_axis_dx, y_axis[0])
        self.assertAlmostEqual(oval.y_axis_dy, y_axis[1])
        self.assertAlmostEqual(oval.width, stroke_width)

    def assertSameGeometry(self, first, second):
        for field in self.GEOMETRY_FIELDS:
            self.assertAlmostEqual(getattr(first, field), getattr(second, field))

    def test_circle_wide_tall_small_and_large_ovals_preserve_independent_radii(self):
        cases = (
            ("circle", [10.0, 20.0, 70.0, 80.0], (30.0, 30.0)),
            ("wide", [10.0, 20.0, 130.0, 60.0], (60.0, 20.0)),
            ("tall", [10.0, 20.0, 50.0, 140.0], (20.0, 60.0)),
            ("small", [10.0, 20.0, 18.0, 26.0], (4.0, 3.0)),
            ("large", [10.0, 20.0, 450.0, 320.0], (220.0, 150.0)),
            ("reversed", [130.0, 60.0, 10.0, 20.0], (60.0, 20.0)),
        )
        for name, position, (radius_x, radius_y) in cases:
            with self.subTest(name=name):
                oval = self._collect(position)
                self.assertOvalGeometry(
                    oval,
                    center=(
                        (position[0] + position[2]) / 2.0,
                        400.0 - (position[1] + position[3]) / 2.0,
                    ),
                    x_axis=(radius_x, 0.0),
                    y_axis=(0.0, -radius_y),
                )

    def test_rotated_oval_matches_canonical_plan_view_dimensions(self):
        position = _rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        screen = calculate_annotation_geometry(
            self._annotation(position), lambda values: values
        )["oval"]
        oval = self._collect(position)
        self.assertAlmostEqual(screen["w"], 120.0)
        self.assertAlmostEqual(screen["h"], 40.0)
        self.assertAlmostEqual(screen["rotation_deg"], 30.0)
        self.assertOvalGeometry(
            oval,
            center=(200.0, 250.0),
            x_axis=(60.0 * math.cos(math.radians(30.0)), -30.0),
            y_axis=(-10.0, -20.0 * math.cos(math.radians(30.0))),
        )

    def test_stroke_width_changes_only_stroke_not_ellipse_geometry(self):
        position = _rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        thin = self._collect(position, width=0.25)
        thick = self._collect(position, width=12.0)
        self.assertSameGeometry(thin, thick)
        self.assertAlmostEqual(thin.width, 0.25)
        self.assertAlmostEqual(thick.width, 12.0)

    def test_export_geometry_is_independent_of_gui_zoom(self):
        position = _rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        low_zoom = self._collect(position, _page_info(view_scale=0.125))
        high_zoom = self._collect(position, _page_info(view_scale=8.0))
        self.assertSameGeometry(low_zoom, high_zoom)

    def test_degenerate_nonfinite_and_invalid_stroke_ovals_are_not_collected(self):
        cases = (
            ("zero width", [10.0, 20.0, 10.0, 80.0], 2.0),
            ("zero height", [10.0, 20.0, 70.0, 20.0], 2.0),
            ("nonfinite coordinate", [10.0, 20.0, math.inf, 80.0], 2.0),
            ("nonfinite rotation", [10.0, 20.0, 70.0, 80.0, math.nan], 2.0),
            ("negative stroke", [10.0, 20.0, 70.0, 80.0], -1.0),
            ("nonfinite stroke", [10.0, 20.0, 70.0, 80.0], math.nan),
        )
        for name, position, stroke_width in cases:
            with self.subTest(name=name):
                result = self.exporter._collect_ovals(
                    "page",
                    [self._annotation(position, width=stroke_width)],
                    _page_info(),
                )
                self.assertEqual(result, [])
        self.assertAlmostEqual(
            self._collect([10.0, 20.0, 70.0, 80.0], width=0).width, 0
        )

    def test_plan_scale_is_applied_exactly_once(self):
        position = [20.0, 40.0, 140.0, 80.0]
        oval = self._collect(
            position, _page_info(scale_factor1=1.0, scale_factor2=144.0)
        )
        self.assertOvalGeometry(
            oval,
            center=(40.0, 370.0),
            x_axis=(30.0, 0.0),
            y_axis=(0.0, -10.0),
        )

    def test_crop_offset_translates_geometry_without_rescaling_it(self):
        oval = self._collect(
            _rotated_oval_position(100.0, 120.0, 80.0, 20.0, 30.0),
            _page_info(
                coord_offset_x=17.0,
                coord_offset_y=23.0,
            ),
        )
        self.assertOvalGeometry(
            oval,
            center=(117.0, 303.0),
            x_axis=(40.0 * math.cos(math.radians(30.0)), -20.0),
            y_axis=(-5.0, -10.0 * math.cos(math.radians(30.0))),
        )

    def test_page_rotations_preserve_transformed_center_and_radius_vectors(self):
        position = _rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        ost_points = _oval_axis_points(self._annotation(position))
        for page_rotation in (0, 90, 180, 270, -90, 360, 450):
            with self.subTest(page_rotation=page_rotation):
                page_info = _page_info(rotation=page_rotation)
                expected = OSTCoordinateSystem.ost_to_pdf_coordinates(
                    ost_points, page_info
                )
                oval = self._collect(position, page_info)
                self.assertOvalGeometry(
                    oval,
                    center=expected[0],
                    x_axis=(
                        expected[1][0] - expected[0][0],
                        expected[1][1] - expected[0][1],
                    ),
                    y_axis=(
                        expected[2][0] - expected[0][0],
                        expected[2][1] - expected[0][1],
                    ),
                )

    def test_page_flips_preserve_affine_radius_vectors(self):
        position = _rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        ost_points = _oval_axis_points(self._annotation(position))
        for flip_x, flip_y in ((True, False), (False, True), (True, True)):
            with self.subTest(flip_x=flip_x, flip_y=flip_y):
                page_info = _page_info(flip_x=flip_x, flip_y=flip_y)
                expected = OSTCoordinateSystem.ost_to_pdf_coordinates(
                    ost_points, page_info
                )
                oval = self._collect(position, page_info)
                self.assertOvalGeometry(
                    oval,
                    center=expected[0],
                    x_axis=(
                        expected[1][0] - expected[0][0],
                        expected[1][1] - expected[0][1],
                    ),
                    y_axis=(
                        expected[2][0] - expected[0][0],
                        expected[2][1] - expected[0][1],
                    ),
                )

    def test_rectangle_and_line_collection_remain_unchanged(self):
        rectangle = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="rect")
        line = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="line")
        rects = self.exporter._collect_rects("page", [rectangle], _page_info())
        lines = self.exporter._collect_lines("page", [line], _page_info())
        self.assertEqual(len(rects), 1)
        self.assertEqual(
            [rects[0].min_x, rects[0].min_y, rects[0].max_x, rects[0].max_y],
            [10.0, 340.0, 130.0, 380.0],
        )
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            [lines[0].x1, lines[0].y1, lines[0].x2, lines[0].y2],
            [10.0, 380.0, 130.0, 340.0],
        )


class PlanViewOvalRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_rotated_plan_view_oval_uses_canonical_width_height_and_rotation(self):
        annotation = BidAnnotation(
            uid="oval",
            annotation_type="oval",
            page_uid="page",
            position=_rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0),
            width=2.0,
        )
        renderer = AnnotationItemRenderer(OSTCoordinateSystem())
        results, _items_by_uid = renderer.create_all_annotation_items(
            [(annotation.uid, annotation)], _page_info(), annotation.page_uid
        )
        self.assertEqual(len(results), 1)
        item = results[0][0]
        self.assertIsInstance(item, QGraphicsPathItem)
        bounds = item.path().boundingRect()
        self.assertAlmostEqual(bounds.center().x(), 200.0)
        self.assertAlmostEqual(bounds.center().y(), 150.0)
        self.assertAlmostEqual(bounds.width(), 120.0)
        self.assertAlmostEqual(bounds.height(), 40.0)
        self.assertAlmostEqual(item.rotation(), 30.0)

    def test_selection_handles_use_the_same_canonical_rotated_geometry(self):
        annotation = BidAnnotation(
            uid="oval",
            annotation_type="oval",
            position=_rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0),
        )
        actual = SelectionManagerMixin._get_ann_corners_ost(annotation)
        angle = math.radians(30.0)
        expected = []
        for dx, dy in ((-60.0, -20.0), (60.0, -20.0), (60.0, 20.0), (-60.0, 20.0)):
            expected.extend(
                [
                    200.0 + dx * math.cos(angle) - dy * math.sin(angle),
                    150.0 + dx * math.sin(angle) + dy * math.cos(angle),
                ]
            )
        for actual_value, expected_value in zip(actual, expected):
            self.assertAlmostEqual(actual_value, expected_value)


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
        self.assertTrue(
            all(math.isfinite(value) for value in self._array(large_annotation, "Rect"))
        )
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


if __name__ == "__main__":
    unittest.main()
