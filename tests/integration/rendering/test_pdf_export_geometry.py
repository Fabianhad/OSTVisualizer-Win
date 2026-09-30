import math
import re
import tempfile
import unittest
import zlib
from itertools import product
from pathlib import Path
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.domain.entities.annotation import BidAnnotation
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.utils.page_info_builder import build_page_info
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
    canonical_highlight_quads,
)
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QTransform
from tests.integration.rendering.pdf_geometry_support import (
    _ColorService as _pdf_geometry_support__ColorService,
    _TakeoffService as _pdf_geometry_support__TakeoffService,
    _UomService as _pdf_geometry_support__UomService,
    _annotation_blocks as _pdf_geometry_support__annotation_blocks,
    _appearance_block as _pdf_geometry_support__appearance_block,
    _appearance_stream as _pdf_geometry_support__appearance_stream,
    _array_values as _pdf_geometry_support__array_values,
    _object_blocks as _pdf_geometry_support__object_blocks,
    _write_pdf as _pdf_geometry_support__write_pdf,
)


class NativePdfExportGeometryTests(unittest.TestCase):
    @staticmethod
    def _exporter():
        return PDFExporter(
            OSTCoordinateSystem(),
            _pdf_geometry_support__ColorService(),
            _pdf_geometry_support__TakeoffService(),
            _pdf_geometry_support__UomService(),
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

    def test_mismatched_metadata_uses_native_geometry_for_every_export_overlay(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "native-36x24.pdf"
            output_path = Path(temp_dir) / "export.pdf"
            _pdf_geometry_support__write_pdf(source_path, 36.0 * 72.0, 24.0 * 72.0)
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
            square = _pdf_geometry_support__annotation_blocks(pdf_text, "Square")[0]
            self.assertEqual(
                _pdf_geometry_support__array_values(square, "Rect"),
                [360.0, 1248.0, 720.0, 1488.0],
            )
            polygon = _pdf_geometry_support__annotation_blocks(pdf_text, "Polygon")[0]
            self.assertEqual(
                _pdf_geometry_support__array_values(polygon, "Vertices"),
                [360.0, 1488.0, 720.0, 1488.0, 720.0, 1248.0, 360.0, 1248.0],
            )
            highlight_block = _pdf_geometry_support__annotation_blocks(
                pdf_text, "Highlight"
            )[0]
            self.assertEqual(
                _pdf_geometry_support__array_values(highlight_block, "QuadPoints"),
                [360.0, 1128.0, 720.0, 1128.0, 360.0, 1068.0, 720.0, 1068.0],
            )
            old_scaled_x = 360.0 * (36.0 / 42.0)
            old_scaled_y = (2160.0 - 600.0) * (24.0 / 30.0)
            self.assertNotIn(
                old_scaled_x,
                _pdf_geometry_support__array_values(highlight_block, "QuadPoints"),
            )
            self.assertNotIn(
                old_scaled_y,
                _pdf_geometry_support__array_values(highlight_block, "QuadPoints"),
            )
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
            _pdf_geometry_support__write_pdf(normal_path, 2592.0, 1728.0)
            _pdf_geometry_support__write_pdf(
                crop_path,
                2612.0,
                1748.0,
                origin=(10.0, 20.0),
                crop_box=(20.0, 30.0, 2612.0, 1758.0),
            )
            _pdf_geometry_support__write_pdf(rotated_path, 800.0, 600.0, rotation=90)
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
                _pdf_geometry_support__write_pdf(
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
                source_line = _pdf_geometry_support__annotation_blocks(pdf_text, "Line")
                self.assertEqual(len(source_line), 1)
                self.assertEqual(
                    _pdf_geometry_support__array_values(source_line[0], "L"),
                    expected_line,
                )
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
            _pdf_geometry_support__write_pdf(
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
            source_line = _pdf_geometry_support__annotation_blocks(pdf_text, "Line")
            self.assertEqual(len(source_line), 1)
            self.assertEqual(
                _pdf_geometry_support__array_values(source_line[0], "L"),
                [100.0, 640.0, 280.0, 340.0],
            )
            self.assertEqual(
                _pdf_geometry_support__array_values(source_line[0], "Border"),
                [0.0, 0.0, 16.0],
            )

    def test_rotated_and_multi_quad_highlights_have_native_pdf_appearances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.pdf"
            output_path = Path(temp_dir) / "export.pdf"
            _pdf_geometry_support__write_pdf(source_path, 600.0, 800.0)
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
        blocks = _pdf_geometry_support__annotation_blocks(pdf_text, "Highlight")
        self.assertEqual(len(blocks), 2)
        quad_lengths = sorted(
            len(_pdf_geometry_support__array_values(block, "QuadPoints"))
            for block in blocks
        )
        self.assertEqual(quad_lengths, [8, 16])
        for block in blocks:
            self.assertIn("/BM /Multiply", block)
            self.assertIn("/CA 1", block)
            self.assertNotIn("/InkList", block)
            self.assertNotIn("/BS <<", block)
            appearance = _pdf_geometry_support__appearance_block(pdf_text, block)
            self.assertEqual(
                _pdf_geometry_support__array_values(block, "Rect"),
                _pdf_geometry_support__array_values(appearance, "BBox"),
            )
            stream = _pdf_geometry_support__appearance_stream(appearance)
            quad_count = (
                len(_pdf_geometry_support__array_values(block, "QuadPoints")) // 8
            )
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
                _pdf_geometry_support__write_pdf(
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
                # Ink coordinates are already Page-space x/y pairs. An odd
                # position has one leading annotation-rotation metadata value.
                ink_positions = [
                    [0.0, *takeoff.position],
                    [math.pi / 2, *takeoff.position],
                    list(takeoff.position),
                    [0.0, 50.0, 140.0, 50.0, 140.0, 120.0],
                ]
                inks = [
                    BidAnnotation(
                        uid=f"matrix-ink-{index}",
                        annotation_type="ink",
                        page_uid=page.uid,
                        position=list(position),
                        color="#884422",
                        width=2.0,
                    )
                    for index, position in enumerate(ink_positions)
                ]
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
                    bid_annotations=[line, *inks],
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
                polygon = _pdf_geometry_support__annotation_blocks(pdf_text, "Polygon")[
                    0
                ]
                actual_vertices = _pdf_geometry_support__array_values(
                    polygon, "Vertices"
                )
                expected_vertices = self._canonical_pdf_points(
                    takeoff.position,
                    page_info["width"],
                    page_info["height"],
                    user_rotation,
                    flip_x,
                    flip_y,
                )
                self.assertEqual(actual_vertices, expected_vertices)
                ink_blocks = _pdf_geometry_support__annotation_blocks(pdf_text, "Ink")
                self.assertEqual(len(ink_blocks), len(inks))
                for ink, block, original in zip(inks, ink_blocks, ink_positions):
                    coordinates = original[1:] if len(original) % 2 else original
                    expected_ink = self._canonical_pdf_points(
                        coordinates,
                        page_info["width"],
                        page_info["height"],
                        user_rotation,
                        flip_x,
                        flip_y,
                    )
                    stroke = re.search(r"/InkList\s*\[\s*\[([^\]]*)\]", block)
                    self.assertIsNotNone(stroke)
                    self.assertEqual(
                        [float(value) for value in stroke.group(1).split()],
                        expected_ink,
                    )
                    appearance = _pdf_geometry_support__appearance_stream(
                        _pdf_geometry_support__appearance_block(pdf_text, block)
                    )
                    drawn_points = re.findall(
                        r"([-\d.]+)\s+([-\d.]+)\s+[ml]\b", appearance
                    )
                    self.assertEqual(
                        [float(value) for point in drawn_points for value in point],
                        expected_ink,
                    )
                    self.assertIn("2 w", appearance)
                    self.assertEqual(
                        _pdf_geometry_support__array_values(block, "C"),
                        [0.533333, 0.266667, 0.133333],
                    )
                    self.assertEqual(ink.position, original)
                line_block = _pdf_geometry_support__annotation_blocks(pdf_text, "Line")[
                    0
                ]
                self.assertEqual(
                    _pdf_geometry_support__array_values(line_block, "L"),
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
            _pdf_geometry_support__write_pdf(
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
