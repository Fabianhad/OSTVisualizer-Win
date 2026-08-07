import os
import re
import tempfile
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.page_export_data_dto import (
    PageExportData as PageExportDto,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter

_DISABLED_CAPTION_SETTINGS = AnnotationCaptionSettingsDto(False, ())


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
    def get_color_mapping(self, _conditions, _takeoffs, _display_mode, _grayscale):
        return {}, {}

    def hex_to_rgb_int(self, color):
        text = color.lstrip("#")
        return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]

    def get_2d_color_for_takeoff(
        self,
        takeoff,
        condition,
        color_map,
        page_area_selections=None,
        *,
        inactive_object_color,
    ):
        _ = (takeoff, page_area_selections, inactive_object_color)
        return color_map[condition.uid]

    def get_condition_color(self, _condition):
        return [0, 0, 0]


class _TakeoffService:
    def group_area_takeoffs_with_holes(self, _takeoffs, _conditions):
        return [], {}


class _Clearable:
    def __init__(self):
        self.clear_calls = 0

    def clear(self):
        self.clear_calls += 1

    def clear_cache(self):
        self.clear_calls += 1


class _FailingClearable(_Clearable):
    def clear(self):
        super().clear()
        raise RuntimeError("clear failed")

    def clear_cache(self):
        super().clear_cache()
        raise RuntimeError("clear failed")


class _ImageCache(_Clearable):
    def __init__(self, image):
        super().__init__()
        self.image = image

    def get_page(self, *_args):
        return self.image


class _ExplodingPainter:
    last_instance = None

    def __init__(self, _target):
        self.active = True
        self.ended = False
        type(self).last_instance = self

    def isActive(self):
        return self.active

    def drawImage(self, *_args):
        raise RuntimeError("draw failed")

    def end(self):
        self.active = False
        self.ended = True


class _CoordinateSystem:
    @staticmethod
    def parse_position(_position):
        return []

    @staticmethod
    def ost_to_pdf_coordinates(_position, _page_info):
        return []


def _make_exporter(writer):
    exporter = PDFExporter.__new__(PDFExporter)
    exporter._writer = writer
    exporter._color_service = _ColorService()
    exporter._takeoff_service = _TakeoffService()
    exporter._coord_system = _CoordinateSystem()
    exporter._uom_service = SimpleNamespace()
    exporter._export_page_cache = _Clearable()
    exporter._export_composite_renderer = _Clearable()
    return exporter


def _export_single_page(exporter, page):
    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = os.path.join(temp_dir, "out.pdf")
        return exporter.export(
            [PageExportDto(page=page)],
            output_path,
            display_mode="color",
            grayscale_enabled=False,
            caption_settings=_DISABLED_CAPTION_SETTINGS,
            elevation_callouts_enabled=False,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )


def _page(**overrides):
    data = {
        "uid": "page-1",
        "name": "Page 1",
        "image_path": "main.pdf",
        "overlay_image_path": "",
        "width_pts": 612.0,
        "height_pts": 792.0,
        "scale_factor1": 0.1875,
        "scale_factor2": 12.0,
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

    def test_overlay_only_export_with_invalid_calibration_uses_blank_background(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        result = _export_single_page(
            exporter,
            _page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                scale_factor1=0.0,
                overlay_rect=(0.0, 0.0, 2688.0, 1920.0),
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertTrue(exported_page.is_blank)
        self.assertEqual(exported_page.source_pdf, "")

    def test_overlay_only_pdf_export_uses_overlay_source_for_nearly_full_page_rect(
        self,
    ):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        exporter._create_overlay_rect_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "near full-page overlay-only export should not rasterize"
            )
        )
        result = _export_single_page(
            exporter,
            _page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                width_pts=42.0 * 72.0,
                height_pts=30.0 * 72.0,
                overlay_rect=(-1.103146, 0.0, 2686.161423, 1919.474692),
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "overlay.pdf")
        self.assertEqual(exported_page.page_index, 0)

    def test_overlay_only_pdf_export_rasterizes_moved_overlay_rect(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        calls = []
        exporter._create_overlay_rect_background_pdf = (
            lambda page, _page_info, temp_dir: calls.append(page.overlay_rect)
            or os.path.join(temp_dir, "moved-overlay.pdf")
        )
        result = _export_single_page(
            exporter,
            _page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                overlay_rect=(64.0, 0.0, 544.0, 704.0),
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [(64.0, 0.0, 544.0, 704.0)])
        self.assertTrue(exported_page.source_pdf.endswith("moved-overlay.pdf"))
        self.assertEqual(exported_page.page_index, 0)

    def test_overlay_only_pdf_export_rasterizes_rotated_overlay_rect(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        calls = []
        exporter._create_overlay_rect_background_pdf = (
            lambda page, _page_info, temp_dir: calls.append(page.overlay_rotation)
            or os.path.join(temp_dir, "rotated-overlay.pdf")
        )
        result = _export_single_page(
            exporter,
            _page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                overlay_rotation=0.01,
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [0.01])
        self.assertTrue(exported_page.source_pdf.endswith("rotated-overlay.pdf"))
        self.assertEqual(exported_page.page_index, 0)

    def test_positioned_overlay_export_clips_to_page_size(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        overlay = QImage(10, 10, QImage.Format.Format_ARGB32)
        overlay.fill(QColor(80, 80, 255).rgba())
        exporter._export_page_cache = _ImageCache(overlay)
        image = exporter._render_positioned_overlay_background(
            _page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                width_pts=72.0,
                height_pts=72.0,
                overlay_rect=(-32.0, -32.0, 64.0, 64.0),
            )
        )
        self.assertIsNotNone(image)
        self.assertEqual((image.width(), image.height()), (144, 144))

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

    def test_raster_background_pdf_ends_painter_when_drawing_fails(self):
        exporter = _make_exporter(_FakeWriter())
        rendered_image = QImage(10, 10, QImage.Format.Format_ARGB32)
        rendered_image.fill(QColor(255, 0, 0))
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "ost_visualizer.presentation.visualization.exporters.pdf_exporter.QPainter",
                _ExplodingPainter,
            ):
                with self.assertRaisesRegex(RuntimeError, "draw failed"):
                    exporter._write_raster_background_pdf(
                        rendered_image,
                        {"width": 612.0, "height": 792.0},
                        temp_dir,
                        "composite",
                    )
        self.assertIsNotNone(_ExplodingPainter.last_instance)
        self.assertTrue(_ExplodingPainter.last_instance.ended)

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
                display_mode="color",
                grayscale_enabled=False,
                caption_settings=_DISABLED_CAPTION_SETTINGS,
                elevation_callouts_enabled=False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                on_progress=lambda current, total, name: progress_calls.append(
                    (current, total, name)
                ),
            )
        self.assertTrue(result.success)
        self.assertEqual(writer.merge_calls, 1)
        self.assertEqual(progress_calls, [(1, 1, "Page 1")])

    def test_export_clears_background_render_resources_after_run(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        page_cache = _Clearable()
        composite_renderer = _Clearable()
        exporter._export_page_cache = page_cache
        exporter._export_composite_renderer = composite_renderer
        result = _export_single_page(exporter, _page())
        self.assertTrue(result.success)
        self.assertEqual(page_cache.clear_calls, 1)
        self.assertEqual(composite_renderer.clear_calls, 1)

    def test_cleanup_failure_preserves_result_and_clears_remaining_resources(self):
        writer = _FakeWriter()
        exporter = _make_exporter(writer)
        page_cache = _Clearable()
        composite_renderer = _FailingClearable()
        exporter._export_page_cache = page_cache
        exporter._export_composite_renderer = composite_renderer
        with self.assertLogs(
            "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
            level="ERROR",
        ) as captured:
            result = _export_single_page(exporter, _page())
        self.assertTrue(result.success)
        self.assertEqual(composite_renderer.clear_calls, 1)
        self.assertEqual(page_cache.clear_calls, 1)
        self.assertTrue(
            any(
                "Failed to clear PDF export composite renderer cache" in message
                for message in captured.output
            )
        )


if __name__ == "__main__":
    unittest.main()
