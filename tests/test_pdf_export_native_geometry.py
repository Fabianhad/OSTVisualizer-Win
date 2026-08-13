import math
import re
import tempfile
import unittest
import zlib
from itertools import product
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QTransform
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
    canonical_highlight_quads,
)
from ost_visualizer.presentation.utils.page_info_builder import build_page_info


def _write_pdf(
    path: Path,
    width: float,
    height: float,
    *,
    origin=(0.0, 0.0),
    crop_box=None,
    rotation=0,
    user_unit=1.0,
    inherited=False,
    content=b"",
    source_line_annotation=False,
) -> None:
    min_x, min_y = origin
    max_x = min_x + width
    max_y = min_y + height
    crop = ""
    if crop_box is not None:
        crop = "/CropBox [" + " ".join(str(value) for value in crop_box) + "] "
    rotate = f"/Rotate {rotation} " if rotation else ""
    unit = f"/UserUnit {user_unit} " if user_unit != 1.0 else ""
    inherited_geometry = ""
    page_geometry = (
        f"/MediaBox [{min_x} {min_y} {max_x} {max_y}] " f"{crop}{rotate}{unit}"
    )
    if inherited:
        inherited_geometry = page_geometry
        page_geometry = ""
    annots = "/Annots [5 0 R] " if source_line_annotation else ""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        (
            "2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 "
            f"{inherited_geometry}>>\nendobj\n"
        ).encode("ascii"),
        (
            "3 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"{page_geometry}{annots}/Resources << >> /Contents 4 0 R >>\nendobj\n"
        ).encode("ascii"),
        (
            f"4 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"\nendstream\nendobj\n"
        ),
    ]
    if source_line_annotation:
        appearance = b"q\n1 0 1 RG 8 w 70 80 m 220 170 l S\nQ"
        objects.extend(
            (
                b"5 0 obj\n<< /Type /Annot /Subtype /Line /P 3 0 R "
                b"/Rect [64 74 226 176] /L [70 80 220 170] /C [1 0 1] "
                b"/Border [0 0 8] /AP << /N 6 0 R >> >>\nendobj\n",
                (
                    b"6 0 obj\n<< /Type /XObject /Subtype /Form "
                    b"/BBox [64 74 226 176] /Matrix [1 0 0 1 -64 -74] "
                    b"/Resources << >> /Length "
                    + str(len(appearance)).encode("ascii")
                    + b" >>\nstream\n"
                    + appearance
                    + b"\nendstream\nendobj\n"
                ),
            )
        )
    content = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(content))
        content += obj
    xref_offset = len(content)
    content += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    content += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        content += f"{offset:010d} 00000 n \n".encode("ascii")
    content += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(content)


def _object_blocks(pdf_text: str) -> list[str]:
    return re.findall(r"\d+ 0 obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL)


def _annotation_blocks(pdf_text: str, subtype: str) -> list[str]:
    marker = f"/Subtype /{subtype}"
    return [block for block in _object_blocks(pdf_text) if marker in block]


def _array_values(block: str, key: str) -> list[float]:
    match = re.search(rf"/{re.escape(key)}\s*\[\s*([^\]]+)\]", block)
    if match is None:
        raise AssertionError(f"/{key} not found in {block}")
    return [float(value) for value in match.group(1).split()]


def _appearance_block(pdf_text: str, annotation_block: str) -> str:
    match = re.search(r"/AP\s*<<\s*/N\s+(\d+)\s+0\s+R", annotation_block)
    if match is None:
        raise AssertionError("Normal appearance reference not found")
    object_number = match.group(1)
    object_match = re.search(
        rf"{object_number} 0 obj\s*(.*?)\s*endobj", pdf_text, re.DOTALL
    )
    if object_match is None:
        raise AssertionError("Normal appearance object not found")
    return object_match.group(1)


def _appearance_stream(appearance_block: str) -> str:
    stream_match = re.search(r"stream\r?\n(.*?)endstream", appearance_block, re.DOTALL)
    if stream_match is None:
        raise AssertionError("Appearance stream not found")
    payload = stream_match.group(1).encode("latin-1")
    if "/FlateDecode" in appearance_block:
        payload = zlib.decompress(payload)
    return payload.decode("latin-1")


class _ColorService:
    @staticmethod
    def get_color_mapping(_conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    @staticmethod
    def hex_to_rgb_int(color):
        color = color.lstrip("#")
        return [int(color[index : index + 2], 16) for index in (0, 2, 4)]

    @staticmethod
    def get_condition_color(_condition):
        return [255, 0, 0]

    @staticmethod
    def get_2d_color_for_takeoff(
        _takeoff,
        _condition,
        color_map,
        _page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = inactive_object_color
        return next(iter(color_map.values()), ColorWithOpacity("#ff0000", 0.5))


class _TakeoffService:
    @staticmethod
    def group_area_takeoffs_with_holes(takeoffs, _conditions):
        return list(takeoffs), {}


class _UomService:
    @staticmethod
    def calculate_net_area_sf(_position, _holes):
        return 1.0


class NativePdfExportGeometryTests(unittest.TestCase):
    @staticmethod
    def _exporter():
        return PDFExporter(
            OSTCoordinateSystem(),
            _ColorService(),
            _TakeoffService(),
            _UomService(),
            object(),
        )

    @staticmethod
    def _page(path: Path, *, stored_width=3024.0, stored_height=2160.0):
        return Page(
            uid="page",
            name="A1",
            image_path=str(path),
            width_pts=stored_width,
            height_pts=stored_height,
            scale_factor1=1.0,
            scale_factor2=72.0,
        )

    def test_rotated_ellipse_takeoff_exports_rotated_physical_footprint(self):
        exporter = self._exporter()
        takeoff = Takeoff(
            uid="ellipse",
            condition_uid="ellipse-condition",
            page_uid="page",
            position=[100.0, 200.0],
            rotation=math.pi / 2.0,
        )
        condition = Condition(
            uid="ellipse-condition",
            condition_type=Condition.TYPE_COUNT,
            shape=shapes.ELLIPSE,
            width=20.0,
            depth=2.0,
            display_size=100.0,
        )
        polygons, callouts = exporter._collect_takeoffs(
            [takeoff],
            {condition.uid: condition},
            {
                "scale_factor1": 1.0,
                "scale_factor2": 72.0,
                "rotation": 0,
                "flip_x": False,
                "flip_y": False,
                "width": 612.0,
                "height": 792.0,
                "view_scale": 1.0,
            },
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=False,
        )
        self.assertEqual(callouts, [])
        self.assertEqual(len(polygons), 1)
        vertices = polygons[0].vertices
        self.assertAlmostEqual(
            max(x for x, _y in vertices) - min(x for x, _y in vertices), 2.0
        )
        self.assertAlmostEqual(
            max(y for _x, y in vertices) - min(y for _x, y in vertices), 20.0
        )

    def test_mismatched_metadata_uses_native_geometry_for_every_export_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "native-36x24.pdf"
            output_path = Path(temp_dir) / "export.pdf"
            _write_pdf(source_path, 36.0 * 72.0, 24.0 * 72.0)
            page = self._page(source_path)
            takeoff = Takeoff(
                uid="1",
                condition_uid="condition",
                page_uid=page.uid,
                position=[360.0, 240.0, 720.0, 240.0, 720.0, 480.0, 360.0, 480.0],
            )
            condition = Condition(
                uid="condition", name="Area", condition_type=Condition.TYPE_AREA
            )
            rectangle = BidAnnotation(
                uid="rect",
                annotation_type="rect",
                page_uid=page.uid,
                position=[360.0, 240.0, 720.0, 480.0],
                color="#336699",
                width=2.0,
            )
            highlight = BidAnnotation(
                uid="highlight",
                annotation_type="highlight",
                page_uid=page.uid,
                position=[360.0, 600.0, 720.0, 660.0],
                color="#ffff00",
            )
            exporter = self._exporter()
            page_info = exporter._build_page_info(page)
            result = exporter.export(
                [PageExportData(page, [takeoff], {condition.uid: condition})],
                str(output_path),
                "condition",
                False,
                AnnotationCaptionSettingsDto(False, ()),
                False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                bid_annotations=[rectangle, highlight],
            )
            self.assertTrue(result.success, result.error_message)
            self.assertEqual(
                (page_info["width"], page_info["height"]), (2592.0, 1728.0)
            )
            plan_coordinates = OSTCoordinateSystem(
                build_page_info(page, 2592.0, 1728.0, 1.0, 0)
            )
            plan_points = calculate_annotation_geometry(
                highlight, plan_coordinates.transform_vertices_to_2d
            )["highlight"]["points"]
            plan_quad = canonical_highlight_quads(plan_points)[0]
            exported_path = exporter._collect_highlights(
                page.uid, [highlight], page_info
            )[0].paths[0]
            exported_quad = [exported_path[index] for index in (0, 1, 5, 4)]
            export_as_plan_points = [
                (point[0], page_info["height"] - point[1]) for point in exported_quad
            ]
            self.assertEqual(export_as_plan_points, list(plan_quad))
            pdf_text = output_path.read_bytes().decode("latin-1", errors="ignore")
            square = _annotation_blocks(pdf_text, "Square")[0]
            self.assertEqual(
                _array_values(square, "Rect"), [360.0, 1248.0, 720.0, 1488.0]
            )
            polygon = _annotation_blocks(pdf_text, "Polygon")[0]
            self.assertEqual(
                _array_values(polygon, "Vertices"),
                [360.0, 1488.0, 720.0, 1488.0, 720.0, 1248.0, 360.0, 1248.0],
            )
            highlight_block = _annotation_blocks(pdf_text, "Highlight")[0]
            self.assertEqual(
                _array_values(highlight_block, "QuadPoints"),
                [360.0, 1128.0, 720.0, 1128.0, 360.0, 1068.0, 720.0, 1068.0],
            )
            old_scaled_x = 360.0 * (36.0 / 42.0)
            old_scaled_y = (2160.0 - 600.0) * (24.0 / 30.0)
            self.assertNotIn(old_scaled_x, _array_values(highlight_block, "QuadPoints"))
            self.assertNotIn(old_scaled_y, _array_values(highlight_block, "QuadPoints"))
            output_geometry = ost_pdf_writer.PDFWriter().get_page_geometries(
                str(output_path)
            )[0]
            self.assertEqual(
                tuple(output_geometry.visible_box), (0.0, 0.0, 2592.0, 1728.0)
            )
            renderer = PageRenderer()
            try:
                rendered = renderer.render(str(output_path), 0, 0.25, 0)
            finally:
                renderer.close()
            self.assertIsNotNone(rendered)
            self.assertEqual((rendered.width(), rendered.height()), (648, 432))
            highlight_pixel = rendered.pixelColor(135, 157)
            self.assertGreaterEqual(highlight_pixel.red(), 240)
            self.assertGreaterEqual(highlight_pixel.green(), 240)
            self.assertLessEqual(highlight_pixel.blue(), 20)

    def test_native_geometry_projects_to_canonical_export_coordinates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            normal_path = Path(temp_dir) / "normal.pdf"
            crop_path = Path(temp_dir) / "crop.pdf"
            rotated_path = Path(temp_dir) / "rotated.pdf"
            _write_pdf(normal_path, 2592.0, 1728.0)
            _write_pdf(
                crop_path,
                2612.0,
                1748.0,
                origin=(10.0, 20.0),
                crop_box=(20.0, 30.0, 2612.0, 1758.0),
            )
            _write_pdf(rotated_path, 800.0, 600.0, rotation=90)
            exporter = self._exporter()
            normal = exporter._build_page_info(
                self._page(normal_path, stored_width=2592.0, stored_height=1728.0)
            )
            cropped = exporter._build_page_info(self._page(crop_path))
            rotated = exporter._build_page_info(
                self._page(rotated_path, stored_width=600.0, stored_height=800.0)
            )
        self.assertEqual((normal["width"], normal["height"]), (2592.0, 1728.0))
        self.assertEqual((cropped["width"], cropped["height"]), (2592.0, 1728.0))
        self.assertEqual(
            OSTCoordinateSystem.ost_to_pdf_coordinates([0.0, 0.0], cropped),
            [[0.0, 1728.0]],
        )
        self.assertEqual(
            (rotated["width"], rotated["height"], rotated["rotation"]),
            (600.0, 800.0, 0),
        )
        self.assertEqual(
            OSTCoordinateSystem.ost_to_pdf_coordinates([100.0, 200.0], rotated),
            [[100.0, 600.0]],
        )

    def test_canonical_coordinate_transform_rejects_invalid_page_contracts(self):
        valid = {
            "width": 600.0,
            "height": 800.0,
            "scale_factor1": 1.0,
            "scale_factor2": 72.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
        }
        for overrides in (
            {"width": 0.0},
            {"height": float("nan")},
            {"scale_factor1": 0.0},
            {"scale_factor2": float("inf")},
            {"rotation": 45},
        ):
            with self.subTest(overrides=overrides):
                page_info = {**valid, **overrides}
                with self.assertRaises(ValueError):
                    OSTCoordinateSystem.ost_to_pdf_coordinates(
                        [100.0, 200.0], page_info
                    )

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
                    _write_pdf(source_path, 600.0, 800.0, **options)
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
                    _write_pdf(source_path, 600.0, 800.0, **options)
                    writer = ost_pdf_writer.PDFWriter()
                    geometries = writer.get_page_geometries(str(source_path))
                    self.assertEqual(len(geometries), 1, writer.get_last_error())
                    self.assertEqual(geometries[0].rotation, rotation)
                    self.assertEqual(tuple(geometries[0].visible_box), visible_box)

    def test_source_annotation_appearance_stays_aligned_during_normalization(self):
        cases = (
            (0, 0, False, False, [50.0, 50.0, 200.0, 140.0]),
            (90, 0, False, False, [50.0, 320.0, 140.0, 170.0]),
            (180, 90, True, False, [50.0, 50.0, 140.0, 200.0]),
            (270, 270, True, True, [320.0, 230.0, 170.0, 140.0]),
        )
        for native_rotation, user_rotation, flip_x, flip_y, expected_line in cases:
            with self.subTest(
                native_rotation=native_rotation,
                user_rotation=user_rotation,
                flip_x=flip_x,
                flip_y=flip_y,
            ), tempfile.TemporaryDirectory() as temp_dir:
                source_path = Path(temp_dir) / "annotated-source.pdf"
                output_path = Path(temp_dir) / "annotated-export.pdf"
                _write_pdf(
                    source_path,
                    400.0,
                    300.0,
                    origin=(10.0, 20.0),
                    crop_box=(20.0, 30.0, 390.0, 310.0),
                    rotation=native_rotation,
                    inherited=True,
                    content=b"q\n0.85 0.85 0.85 rg 20 30 370 280 re f\nQ",
                    source_line_annotation=True,
                )
                page = self._page(source_path, stored_width=999.0, stored_height=888.0)
                page.rotation = user_rotation
                page.flip_x = flip_x
                page.flip_y = flip_y
                result = self._exporter().export(
                    [PageExportData(page)],
                    str(output_path),
                    "condition",
                    False,
                    AnnotationCaptionSettingsDto(False, ()),
                    False,
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                )
                self.assertTrue(result.success, result.error_message)
                pdf_text = output_path.read_bytes().decode("latin-1", errors="ignore")
                source_line = _annotation_blocks(pdf_text, "Line")
                self.assertEqual(len(source_line), 1)
                self.assertEqual(_array_values(source_line[0], "L"), expected_line)
                renderer = PageRenderer()
                try:
                    source_image = renderer.render(str(source_path), 0, 1.0, 0)
                    output_image = renderer.render(str(output_path), 0, 1.0, 0)
                finally:
                    renderer.close()
                transform = QTransform()
                transform.translate(source_image.width() / 2, source_image.height() / 2)
                transform.rotate(-user_rotation)
                transform.scale(-1 if flip_x else 1, -1 if flip_y else 1)
                transform.translate(
                    -source_image.width() / 2, -source_image.height() / 2
                )
                expected_image = source_image.transformed(
                    transform, Qt.TransformationMode.FastTransformation
                )
                self.assertEqual(
                    self._magenta_bounds(output_image),
                    self._magenta_bounds(expected_image),
                )

    def test_source_annotation_geometry_applies_user_unit_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "annotated-user-unit.pdf"
            output_path = Path(temp_dir) / "annotated-user-unit-export.pdf"
            _write_pdf(
                source_path,
                400.0,
                300.0,
                origin=(10.0, 20.0),
                crop_box=(20.0, 30.0, 390.0, 310.0),
                rotation=90,
                user_unit=2.0,
                inherited=True,
                source_line_annotation=True,
            )
            page = self._page(source_path, stored_width=999.0, stored_height=888.0)
            result = self._exporter().export(
                [PageExportData(page)],
                str(output_path),
                "condition",
                False,
                AnnotationCaptionSettingsDto(False, ()),
                False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
            self.assertTrue(result.success, result.error_message)
            pdf_text = output_path.read_bytes().decode("latin-1", errors="ignore")
            source_line = _annotation_blocks(pdf_text, "Line")
            self.assertEqual(len(source_line), 1)
            self.assertEqual(
                _array_values(source_line[0], "L"),
                [100.0, 640.0, 280.0, 340.0],
            )
            self.assertEqual(
                _array_values(source_line[0], "Border"),
                [0.0, 0.0, 16.0],
            )

    def test_rotated_and_multi_quad_highlights_have_native_pdf_appearances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.pdf"
            output_path = Path(temp_dir) / "export.pdf"
            _write_pdf(source_path, 600.0, 800.0)
            page = self._page(source_path, stored_width=600.0, stored_height=800.0)
            rotated = BidAnnotation(
                uid="rotated",
                annotation_type="highlight",
                page_uid=page.uid,
                position=[100.0, 100.0, 300.0, 140.0, 290.0, 190.0, 90.0, 150.0],
                color="#00ff00",
            )
            multiple = BidAnnotation(
                uid="multiple",
                annotation_type="highlight",
                page_uid=page.uid,
                position=[
                    50.0,
                    300.0,
                    250.0,
                    300.0,
                    250.0,
                    340.0,
                    50.0,
                    340.0,
                    300.0,
                    400.0,
                    550.0,
                    400.0,
                    550.0,
                    450.0,
                    300.0,
                    450.0,
                ],
                color="#ffff00",
            )
            exporter = self._exporter()
            result = exporter.export(
                [PageExportData(page)],
                str(output_path),
                "condition",
                False,
                AnnotationCaptionSettingsDto(False, ()),
                False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                bid_annotations=[rotated, multiple],
            )
            self.assertTrue(result.success, result.error_message)
            pdf_text = output_path.read_bytes().decode("latin-1", errors="ignore")
        blocks = _annotation_blocks(pdf_text, "Highlight")
        self.assertEqual(len(blocks), 2)
        quad_lengths = sorted(
            len(_array_values(block, "QuadPoints")) for block in blocks
        )
        self.assertEqual(quad_lengths, [8, 16])
        for block in blocks:
            self.assertIn("/BM /Multiply", block)
            self.assertIn("/CA 1", block)
            self.assertNotIn("/InkList", block)
            self.assertNotIn("/BS <<", block)
            appearance = _appearance_block(pdf_text, block)
            self.assertEqual(
                _array_values(block, "Rect"), _array_values(appearance, "BBox")
            )
            stream = _appearance_stream(appearance)
            quad_count = len(_array_values(block, "QuadPoints")) // 8
            self.assertEqual(stream.count(" c "), quad_count * 2)
            self.assertEqual(stream.count(" c f "), quad_count)
            self.assertNotIn(" S", stream)

    def test_vector_geometry_matrix_keeps_source_and_takeoffs_in_one_space(self):
        content = (
            b"q\n"
            b"1 0 0 rg 20 30 80 80 re f\n"
            b"0 1 0 rg 310 30 80 80 re f\n"
            b"0 0 1 rg 20 230 80 80 re f\n"
            b"0 0 0 rg 310 230 80 80 re f\n"
            b"Q"
        )
        cases = product(
            (0, 90, 180, 270),
            (0, 90, 180, 270),
            (False, True),
            (False, True),
        )
        for native_rotation, user_rotation, flip_x, flip_y in cases:
            with self.subTest(
                native_rotation=native_rotation,
                user_rotation=user_rotation,
                flip_x=flip_x,
                flip_y=flip_y,
            ), tempfile.TemporaryDirectory() as temp_dir:
                source_path = Path(temp_dir) / "geometry-source.pdf"
                output_path = Path(temp_dir) / "geometry-export.pdf"
                _write_pdf(
                    source_path,
                    400.0,
                    300.0,
                    origin=(10.0, 20.0),
                    crop_box=(20.0, 30.0, 390.0, 310.0),
                    rotation=native_rotation,
                    inherited=True,
                    content=content,
                )
                page = self._page(source_path, stored_width=999.0, stored_height=888.0)
                page.rotation = user_rotation
                page.flip_x = flip_x
                page.flip_y = flip_y
                takeoff = Takeoff(
                    uid="matrix-takeoff",
                    condition_uid="condition",
                    page_uid=page.uid,
                    position=[
                        40.0,
                        50.0,
                        140.0,
                        50.0,
                        140.0,
                        120.0,
                        40.0,
                        120.0,
                    ],
                )
                line = BidAnnotation(
                    uid="matrix-line",
                    annotation_type="line",
                    page_uid=page.uid,
                    position=[60.0, 70.0, 180.0, 130.0],
                    color="#884422",
                    width=2.0,
                )
                condition = Condition(
                    uid="condition",
                    name="Area",
                    condition_type=Condition.TYPE_AREA,
                )
                exporter = self._exporter()
                page_info = exporter._build_page_info(page)
                result = exporter.export(
                    [
                        PageExportData(
                            page,
                            [takeoff],
                            {condition.uid: condition},
                        )
                    ],
                    str(output_path),
                    "condition",
                    False,
                    AnnotationCaptionSettingsDto(False, ()),
                    False,
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                    bid_annotations=[line],
                )
                self.assertTrue(result.success, result.error_message)
                output_geometry = ost_pdf_writer.PDFWriter().get_page_geometries(
                    str(output_path)
                )[0]
                self.assertEqual(output_geometry.rotation, 0)
                self.assertEqual(output_geometry.user_unit, 1.0)
                self.assertEqual(
                    tuple(output_geometry.visible_box),
                    (
                        0.0,
                        0.0,
                        page_info["export_width"],
                        page_info["export_height"],
                    ),
                )
                pdf_text = output_path.read_bytes().decode("latin-1", errors="ignore")
                polygon = _annotation_blocks(pdf_text, "Polygon")[0]
                actual_vertices = _array_values(polygon, "Vertices")
                expected_vertices = self._canonical_pdf_points(
                    takeoff.position,
                    page_info["width"],
                    page_info["height"],
                    user_rotation,
                    flip_x,
                    flip_y,
                )
                self.assertEqual(actual_vertices, expected_vertices)
                line_block = _annotation_blocks(pdf_text, "Line")[0]
                self.assertEqual(
                    _array_values(line_block, "L"),
                    self._canonical_pdf_points(
                        line.position,
                        page_info["width"],
                        page_info["height"],
                        user_rotation,
                        flip_x,
                        flip_y,
                    ),
                )
                renderer = PageRenderer()
                try:
                    source_image = renderer.render(str(source_path), 0, 0.25, 0)
                    output_image = renderer.render(str(output_path), 0, 0.25, 0)
                finally:
                    renderer.close()
                self.assertIsNotNone(source_image)
                self.assertIsNotNone(output_image)
                transform = QTransform()
                transform.translate(source_image.width() / 2, source_image.height() / 2)
                transform.rotate(-user_rotation)
                transform.scale(-1 if flip_x else 1, -1 if flip_y else 1)
                transform.translate(
                    -source_image.width() / 2, -source_image.height() / 2
                )
                expected_image = source_image.transformed(
                    transform, Qt.TransformationMode.FastTransformation
                )
                self.assertEqual(
                    self._corner_colors(output_image),
                    self._corner_colors(expected_image),
                )

    def test_inherited_user_unit_scales_canonical_page_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "inherited-user-unit.pdf"
            output_path = Path(temp_dir) / "export.pdf"
            _write_pdf(
                source_path,
                400.0,
                300.0,
                origin=(10.0, 20.0),
                crop_box=(20.0, 30.0, 390.0, 310.0),
                rotation=90,
                user_unit=2.0,
                inherited=True,
                content=(
                    b"q\n"
                    b"1 0 0 rg 20 30 80 80 re f\n"
                    b"0 1 0 rg 310 30 80 80 re f\n"
                    b"0 0 1 rg 20 230 80 80 re f\n"
                    b"0 0 0 rg 310 230 80 80 re f\n"
                    b"Q"
                ),
            )
            page = self._page(source_path, stored_width=3024.0, stored_height=2160.0)
            page.rotation = 90
            exporter = self._exporter()
            page_info = exporter._build_page_info(page)
            result = exporter.export(
                [PageExportData(page)],
                str(output_path),
                "condition",
                False,
                AnnotationCaptionSettingsDto(False, ()),
                False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            )
            self.assertTrue(result.success, result.error_message)
            output_geometry = ost_pdf_writer.PDFWriter().get_page_geometries(
                str(output_path)
            )[0]
            renderer = PageRenderer()
            try:
                source_image = renderer.render(str(source_path), 0, 0.25, 0)
                output_image = renderer.render(str(output_path), 0, 0.25, 0)
            finally:
                renderer.close()
            transform = QTransform()
            transform.translate(source_image.width() / 2, source_image.height() / 2)
            transform.rotate(-90)
            transform.translate(-source_image.width() / 2, -source_image.height() / 2)
            expected_image = source_image.transformed(
                transform, Qt.TransformationMode.FastTransformation
            )
        self.assertEqual((page_info["width"], page_info["height"]), (560.0, 740.0))
        self.assertEqual(
            (page_info["export_width"], page_info["export_height"]),
            (740.0, 560.0),
        )
        self.assertEqual(tuple(output_geometry.visible_box), (0.0, 0.0, 740.0, 560.0))
        self.assertEqual(output_geometry.user_unit, 1.0)
        self.assertEqual(
            self._corner_colors(output_image), self._corner_colors(expected_image)
        )

    @staticmethod
    def _canonical_pdf_points(
        position, width, height, rotation, flip_x, flip_y
    ) -> list[float]:
        output_height = width if rotation in (90, 270) else height
        result = []
        for x, y in zip(position[::2], position[1::2]):
            if flip_x:
                x = width - x
            if flip_y:
                y = height - y
            if rotation == 90:
                x, y = y, width - x
            elif rotation == 180:
                x, y = width - x, height - y
            elif rotation == 270:
                x, y = height - y, x
            result.extend((x, output_height - y))
        return result

    @staticmethod
    def _corner_colors(image) -> list[tuple[int, int, int]]:
        colors = []
        for x_fraction, y_fraction in ((0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)):
            x = min(image.width() - 1, int(image.width() * x_fraction))
            y = min(image.height() - 1, int(image.height() * y_fraction))
            colors.append(image.pixelColor(x, y).getRgb()[:3])
        return colors

    @staticmethod
    def _magenta_bounds(image) -> tuple[int, int, int, int]:
        points = []
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.red() > 150 and color.blue() > 150 and color.green() < 100:
                    points.append((x, y))
        if not points:
            raise AssertionError("Expected a visible magenta source annotation")
        return (
            min(x for x, _y in points),
            min(y for _x, y in points),
            max(x for x, _y in points),
            max(y for _x, y in points),
        )


if __name__ == "__main__":
    unittest.main()
