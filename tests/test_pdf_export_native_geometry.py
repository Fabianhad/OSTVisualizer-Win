import re
import tempfile
import unittest
import zlib
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
) -> None:
    min_x, min_y = origin
    max_x = min_x + width
    max_y = min_y + height
    crop = ""
    if crop_box is not None:
        crop = "/CropBox [" + " ".join(str(value) for value in crop_box) + "] "
    rotate = f"/Rotate {rotation} " if rotation else ""
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            "3 0 obj\n<< /Type /Page /Parent 2 0 R "
            f"/MediaBox [{min_x} {min_y} {max_x} {max_y}] "
            f"{crop}{rotate}/Resources << >> /Contents 4 0 R >>\nendobj\n"
        ).encode("ascii"),
        b"4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n",
    ]
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

    def test_matching_metadata_and_crop_origin_preserve_native_coordinates(self):
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
        self.assertEqual(
            (normal["coord_offset_x"], normal["coord_offset_y"]), (0.0, 0.0)
        )
        self.assertEqual((cropped["width"], cropped["height"]), (2592.0, 1728.0))
        self.assertEqual(
            (cropped["coord_offset_x"], cropped["coord_offset_y"]), (20.0, 30.0)
        )
        self.assertEqual(
            OSTCoordinateSystem.ost_to_pdf_coordinates([0.0, 0.0], cropped),
            [[20.0, 1758.0]],
        )
        self.assertEqual(
            (rotated["width"], rotated["height"], rotated["rotation"]),
            (800.0, 600.0, 90),
        )
        self.assertEqual(
            OSTCoordinateSystem.ost_to_pdf_coordinates([100.0, 200.0], rotated),
            [[600.0, 100.0]],
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


if __name__ == "__main__":
    unittest.main()
