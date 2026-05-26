import os
import re
import tempfile
import unittest
import zlib
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage
from ost_visualizer.application.dtos.page_export_data_dto import (
    PageExportData as PageExportDto,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.handlers.export_handler import _append_extension_once
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter


class _FakeWriter:
    def __init__(self):
        self.pages = []
        self.merge_calls = 0

    def get_page_sizes(self, _path):
        return [(612.0, 792.0, 0.0, 0.0)]

    def merge_pages_with_annotations(self, pages, _output_path):
        self.merge_calls += 1
        self.pages = list(pages)
        return True

    def get_last_error(self):
        return ""


class _ColorService:
    def get_color_mapping(self, _conditions, _takeoffs, _color_mode, _grayscale):
        return {}, {}

    def hex_to_rgb_int(self, color):
        text = color.lstrip("#")
        return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]

    def should_gray_out_takeoff(self, _takeoff, _page_area_selections):
        return False

    def get_condition_color(self, _condition):
        return [0, 0, 0]


class _TakeoffService:
    def group_area_takeoffs_with_holes(self, _takeoffs, _conditions):
        return [], {}


class _CoordinateSystem:
    def parse_position(self, _position):
        return []

    def ost_to_pdf_coordinates(self, _position, _page_info):
        return []


def _make_exporter(writer):
    exporter = PDFExporter.__new__(PDFExporter)
    exporter._writer = writer
    exporter._color_service = _ColorService()
    exporter._takeoff_service = _TakeoffService()
    exporter._coord_system = _CoordinateSystem()
    exporter._uom_service = SimpleNamespace()
    exporter._export_page_cache = SimpleNamespace()
    exporter._export_composite_renderer = SimpleNamespace()
    return exporter


def _export_single_page(exporter, page):
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = os.path.join(temp_dir, "out.pdf")
        return exporter.export(
            [PageExportDto(page=page)],
            output_path,
            color_mode="color",
            grayscale_enabled=False,
        )


def _page(**overrides):
    data = {
        "uid": "page-1",
        "name": "Page 1",
        "image_path": "main.pdf",
        "overlay_image_path": "",
        "width_pts": 612.0,
        "height_pts": 792.0,
        "page_index": 2,
        "layer_visible": True,
        "image_show_mode": SHOW_ORIGINAL,
    }
    data.update(overrides)
    return Page(**data)


def _read_pdf_text(path):
    with open(path, "rb") as handle:
        return handle.read().decode("latin-1", errors="ignore")


def _read_pdf_stream_text(path):
    with open(path, "rb") as handle:
        pdf_bytes = handle.read()
    parts = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        stream_data = match.group(1)
        try:
            stream_data = zlib.decompress(stream_data)
        except zlib.error:
            pass
        parts.append(stream_data.decode("latin-1", errors="ignore"))
    return "\n".join(parts)


class PDFOverlayExportTests(unittest.TestCase):
    def test_pdf_export_filename_keeps_existing_pdf_extension(self):
        filename = _append_extension_once(
            "25-051 Marriott Element, Capel Hill, NC - S-100.pdf", "pdf"
        )
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.pdf"
        )

    def test_pdf_export_filename_keeps_existing_pdf_extension_case_insensitive(self):
        filename = _append_extension_once(
            "25-051 Marriott Element, Capel Hill, NC - S-100.PDF", "pdf"
        )
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.PDF"
        )

    def test_pdf_export_filename_appends_pdf_when_missing(self):
        filename = _append_extension_once(
            "25-051 Marriott Element, Capel Hill, NC - S-100", "pdf"
        )
        self.assertEqual(
            filename, "25-051 Marriott Element, Capel Hill, NC - S-100.pdf"
        )

    def test_main_only_export_uses_main_pdf_source(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        result = _export_single_page(exporter, _page())
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "main.pdf")
        self.assertEqual(exported_page.page_index, 2)
        self.assertFalse(exported_page.is_blank)

    def test_overlay_only_pdf_export_uses_overlay_source_directly(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "overlay-only export should not use comparison rendering"
            )
        )
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.pdf", image_show_mode=SHOW_OVERLAY),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "overlay.pdf")
        self.assertEqual(exported_page.page_index, 0)
        self.assertFalse(exported_page.is_blank)

    def test_overlay_only_raster_export_uses_single_image_source_path(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        calls = []
        exporter._create_image_source_background_pdf = (
            lambda source_path, page_index, _page_info, temp_dir, prefix: calls.append(
                (source_path, page_index, prefix)
            )
            or os.path.join(temp_dir, "overlay-image.pdf")
        )
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.tif", image_show_mode=SHOW_OVERLAY),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [("overlay.tif", 0, "overlay")])
        self.assertTrue(exported_page.source_pdf.endswith("overlay-image.pdf"))
        self.assertEqual(exported_page.page_index, 0)

    def test_overlay_only_raster_export_does_not_use_comparison_rendering(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "overlay-only raster export should not use comparison rendering"
            )
        )
        exporter._create_image_source_background_pdf = lambda _source_path, _page_index, _page_info, temp_dir, _prefix: os.path.join(
            temp_dir, "overlay-image.pdf"
        )
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.tif", image_show_mode=SHOW_OVERLAY),
        )
        self.assertTrue(result.success)

    def test_main_and_overlay_export_uses_flattened_composite_background(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        calls = []
        exporter._create_composite_background_pdf = (
            lambda page, page_info, temp_dir: calls.append(
                (page.image_path, page.overlay_image_path)
            )
            or os.path.join(temp_dir, "composite.pdf")
        )
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [("main.pdf", "overlay.pdf")])
        self.assertTrue(exported_page.source_pdf.endswith("composite.pdf"))
        self.assertEqual(exported_page.page_index, 0)
        self.assertFalse(exported_page.is_blank)

    def test_main_and_overlay_falls_back_to_main_when_composite_render_fails(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: None
        )
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "main.pdf")
        self.assertEqual(exported_page.page_index, 2)

    def test_missing_main_with_overlay_enabled_exports_overlay(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: None
        )
        result = _export_single_page(
            exporter,
            _page(
                image_path="",
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_BOTH,
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(writer.pages[0].source_pdf, "overlay.pdf")

    def test_hidden_main_with_overlay_enabled_exports_overlay_directly(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "hidden main layer should not trigger comparison rendering"
            )
        )
        result = _export_single_page(
            exporter,
            _page(
                layer_visible=False,
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_BOTH,
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(writer.pages[0].source_pdf, "overlay.pdf")

    def test_blank_page_export_remains_blank(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        result = _export_single_page(
            exporter,
            _page(image_path="", overlay_image_path="", image_show_mode=SHOW_ORIGINAL),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertTrue(exported_page.is_blank)
        self.assertEqual(exported_page.page_width, 612.0)
        self.assertEqual(exported_page.page_height, 792.0)

    def test_annotations_are_exported_over_composite_background(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        dimension = ost_pdf_writer.DimensionAnnotationData()
        dimension.content = "10' - 0\""
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, temp_dir: os.path.join(temp_dir, "composite.pdf")
        )
        exporter._collect_dimensions = lambda _uid, _annotations, _page_info: [
            dimension
        ]
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertTrue(exported_page.source_pdf.endswith("composite.pdf"))
        self.assertEqual(exported_page.dimensions[0].content, "10' - 0\"")

    def test_raster_background_pdf_draws_scaled_image_to_full_page_points(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        rendered_image = QImage(1224, 1584, QImage.Format.Format_ARGB32)
        rendered_image.fill(QColor(255, 0, 0))
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = exporter._write_raster_background_pdf(
                rendered_image,
                {"width": 612.0, "height": 792.0},
                temp_dir,
                "composite",
            )
            self.assertIsNotNone(output_path)
            pdf_text = _read_pdf_text(output_path)
            stream_text = _read_pdf_stream_text(output_path)
        self.assertIn("/MediaBox [0 0 612.000000 792.000000]", pdf_text)
        self.assertIn("1 0 0 -1 0 792 cm", stream_text)
        self.assertIn("0.500000000 0 0 0.500000000 0 0 cm", stream_text)
        self.assertNotIn("0.060000000 0 0 -0.060000000", stream_text)

    def test_annotations_are_exported_over_overlay_only_source(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        dimension = ost_pdf_writer.DimensionAnnotationData()
        dimension.content = "6' - 0\""
        exporter._collect_dimensions = lambda _uid, _annotations, _page_info: [
            dimension
        ]
        result = _export_single_page(
            exporter,
            _page(overlay_image_path="overlay.pdf", image_show_mode=SHOW_OVERLAY),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "overlay.pdf")
        self.assertEqual(exported_page.dimensions[0].content, "6' - 0\"")

    def test_single_page_export_merges_once(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        progress_calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            result = exporter.export(
                [PageExportDto(page=_page())],
                os.path.join(temp_dir, "out.pdf"),
                color_mode="color",
                grayscale_enabled=False,
                on_progress=lambda current, total, name: progress_calls.append(
                    (current, total, name)
                ),
            )
        self.assertTrue(result.success)
        self.assertEqual(writer.merge_calls, 1)
        self.assertEqual(progress_calls, [(1, 1, "Page 1")])


if __name__ == "__main__":
    unittest.main()
