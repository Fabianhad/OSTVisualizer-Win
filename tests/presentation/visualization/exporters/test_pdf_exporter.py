import os
import re
import tempfile
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch
from ost_visualizer.application.dtos.annotation_caption_dto import (
    AnnotationCaptionSettingsDto,
)
from ost_visualizer.application.dtos.page_export_data_dto import (
    PageExportData as PageExportDto,
)
from ost_visualizer.application.dtos.export_dto import ExportErrorCode
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.domain.entities.config import Config
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.utils.image_show_mode import (
    SHOW_BOTH,
    SHOW_ORIGINAL,
    SHOW_OVERLAY,
)
from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer
from ost_visualizer.presentation.visualization.exporters.pdf_exporter import PDFExporter
from PySide6.QtGui import QColor, QImage
from tests.presentation.visualization.exporters.overlay_export_support import (
    _Clearable as _overlay_export_support__Clearable,
    _ColorService as _overlay_export_support__ColorService,
    _CoordinateSystem as _overlay_export_support__CoordinateSystem,
    _DISABLED_CAPTION_SETTINGS as _overlay_export_support__DISABLED_CAPTION_SETTINGS,
    _ExplodingPainter as _overlay_export_support__ExplodingPainter,
    _FailingClearable as _overlay_export_support__FailingClearable,
    _FakeWriter as _overlay_export_support__FakeWriter,
    _geometry as _overlay_export_support__geometry,
    _ImageCache as _overlay_export_support__ImageCache,
    _RecordingImageCache as _overlay_export_support__RecordingImageCache,
    _TakeoffService as _overlay_export_support__TakeoffService,
    _export_single_page as _overlay_export_support__export_single_page,
    _make_exporter as _overlay_export_support__make_exporter,
    _page as _overlay_export_support__page,
    _read_pdf_stream_text as _overlay_export_support__read_pdf_stream_text,
    _read_pdf_text as _overlay_export_support__read_pdf_text,
)
import math
from ost_visualizer.domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_INK,
    ANNOTATION_TYPE_LINE,
    ANNOTATION_TYPE_OVAL,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
    BidAnnotation,
)
from ost_visualizer.domain.services.coordinate_transformation_service import (
    OSTCoordinateSystem,
)
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
)
from tests.presentation.visualization.exporters.oval_support import (
    _ColorService as _oval_support__ColorService,
    _oval_axis_points as _oval_support__oval_axis_points,
    _page_info as _oval_support__page_info,
    _rotated_oval_position as _oval_support__rotated_oval_position,
)
from ost_visualizer.application.dtos.color_dtos import ColorWithOpacity
from ost_visualizer.domain.entities import shape as shapes
from ost_visualizer.domain.entities.condition import Condition
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.pdf.renderers.annotation_renderer import (
    calculate_annotation_geometry,
    canonical_highlight_quads,
)
from tests.integration.rendering.pdf_geometry_support import (
    _ColorService as _pdf_geometry_support__ColorService,
    _TakeoffService as _pdf_geometry_support__TakeoffService,
    _UomService as _pdf_geometry_support__UomService,
)
from unittest import mock
from ost_visualizer.application.dtos.page_export_data_dto import PageExportData
from ost_visualizer.application.services.annotation_caption_resolver import (
    AnnotationCaptionResolver,
)
from ost_visualizer.domain.entities.elevation_callout import (
    ElevationCallout,
    ElevationCalloutSettings,
)
from ost_visualizer.domain.services.takeoff_service_impl import TakeoffDomainService
from ost_visualizer.domain.services.uom_service_impl import UOMDomainService
from ost_visualizer.presentation.visualization.services.color_service import (
    ColorService,
)
from tests.domain.services.elevation_support import (
    _CapturingPdfWriter as _elevation_support__CapturingPdfWriter,
    _EXPECTED_PDF_CALLOUT_LINES as _elevation_support__EXPECTED_PDF_CALLOUT_LINES,
    _area_condition as _elevation_support__area_condition,
    _area_takeoff as _elevation_support__area_takeoff,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.domain.entities.annotation_caption import AnnotationCaptionId
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsTextItem,
)
from tests.integration.annotations.dimension_support import (
    _ColorService as _dimension_support__ColorService,
    _page_info as _dimension_support__page_info,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class PDFOverlayExportTests(unittest.TestCase):
    def test_pdf_export_rejects_missing_native_geometry_instead_of_using_stored_size(
        self,
    ):
        writer = _overlay_export_support__FakeWriter()
        writer.get_page_geometries = lambda _path: []
        exporter = _overlay_export_support__make_exporter(writer)
        with self.assertLogs(
            "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
            level="ERROR",
        ):
            result = _overlay_export_support__export_single_page(
                exporter, _overlay_export_support__page()
            )
        self.assertFalse(result.success)
        self.assertIn("Native PDF page geometry is unavailable", result.error_message)
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(writer.merge_calls, 0)

    def test_main_only_export_uses_main_pdf_source(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        result = _overlay_export_support__export_single_page(
            exporter, _overlay_export_support__page()
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "main.pdf")
        self.assertEqual(exported_page.page_index, 2)
        self.assertFalse(exported_page.is_blank)
        self.assertEqual(
            (exported_page.page_width, exported_page.page_height), (612.0, 792.0)
        )
        self.assertEqual(
            (exported_page.source_width, exported_page.source_height), (612.0, 792.0)
        )
        self.assertEqual(exported_page.rotation, 0)
        self.assertFalse(exported_page.flip_x)
        self.assertFalse(exported_page.flip_y)

    def test_overlay_only_pdf_export_uses_overlay_source_directly(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "overlay-only export should not use comparison rendering"
            )
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf", image_show_mode=SHOW_OVERLAY
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "overlay.pdf")
        self.assertEqual(exported_page.page_index, 0)
        self.assertFalse(exported_page.is_blank)

    def test_overlay_only_export_with_invalid_calibration_uses_blank_background(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
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
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_overlay_rect_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "near full-page overlay-only export should not rasterize"
            )
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
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
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        calls = []
        exporter._create_overlay_rect_background_pdf = (
            lambda page, _page_info, temp_dir: calls.append(page.overlay_rect)
            or os.path.join(temp_dir, "moved-overlay.pdf")
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
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
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        calls = []
        exporter._create_overlay_rect_background_pdf = (
            lambda page, _page_info, temp_dir: calls.append(page.overlay_rotation)
            or os.path.join(temp_dir, "rotated-overlay.pdf")
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
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
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        overlay = QImage(10, 10, QImage.Format.Format_ARGB32)
        overlay.fill(QColor(80, 80, 255).rgba())
        exporter._export_page_cache = _overlay_export_support__ImageCache(overlay)
        image = exporter._render_positioned_overlay_background(
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_OVERLAY,
                width_pts=72.0,
                height_pts=72.0,
                overlay_rect=(-32.0, -32.0, 64.0, 64.0),
            ),
            {"width": 72.0, "height": 72.0},
        )
        self.assertIsNotNone(image)
        expected_size = round(72 * INTERACTIVE_PDF_RENDER_SCALE)
        self.assertEqual(
            (image.width(), image.height()), (expected_size, expected_size)
        )
        # The overlay rectangle spans -36..36 pt on a 72 pt page, so it covers
        # exactly the top-left quadrant of the canvas; the rest stays white paper.
        half = expected_size // 2
        blue = QColor(80, 80, 255).name()
        white = QColor(255, 255, 255).name()
        for x, y in ((10, 10), (half - 10, half - 10), (10, half - 10)):
            self.assertEqual(image.pixelColor(x, y).name(), blue, (x, y))
        for x, y in (
            (half + 10, half + 10),
            (expected_size - 10, 10),
            (10, expected_size - 10),
            (expected_size - 10, expected_size - 10),
        ):
            self.assertEqual(image.pixelColor(x, y).name(), white, (x, y))

    def test_positioned_overlay_without_calibration_or_image_is_not_rendered(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        overlay = QImage(10, 10, QImage.Format.Format_ARGB32)
        overlay.fill(QColor(80, 80, 255).rgba())
        cache = _overlay_export_support__RecordingImageCache(overlay)
        exporter._export_page_cache = cache
        page_info = {"width": 72.0, "height": 72.0}
        self.assertIsNone(
            exporter._render_positioned_overlay_background(
                _overlay_export_support__page(
                    overlay_image_path="", overlay_rect=(0.0, 0.0, 64.0, 64.0)
                ),
                page_info,
            )
        )
        self.assertIsNone(
            exporter._render_positioned_overlay_background(
                _overlay_export_support__page(
                    overlay_image_path="overlay.pdf",
                    scale_factor1=0.0,
                    overlay_rect=(0.0, 0.0, 64.0, 64.0),
                ),
                page_info,
            )
        )
        self.assertEqual(cache.requests, [])
        cache.image = None
        self.assertIsNone(
            exporter._render_positioned_overlay_background(
                _overlay_export_support__page(
                    overlay_image_path="overlay.pdf",
                    width_pts=72.0,
                    height_pts=72.0,
                    overlay_rect=(0.0, 0.0, 64.0, 64.0),
                ),
                page_info,
            )
        )
        self.assertEqual(len(cache.requests), 1)

    def test_positioned_raster_overlay_loads_native_pixels(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        cache = _overlay_export_support__RecordingImageCache(
            QImage(10, 10, QImage.Format.Format_ARGB32)
        )
        exporter._export_page_cache = cache
        image = exporter._render_positioned_overlay_background(
            _overlay_export_support__page(
                overlay_image_path="overlay.tif",
                image_show_mode=SHOW_OVERLAY,
                width_pts=72.0,
                height_pts=72.0,
                overlay_rect=(0.0, 0.0, 64.0, 64.0),
            ),
            {"width": 72.0, "height": 72.0},
        )
        self.assertIsNotNone(image)
        self.assertEqual(
            cache.requests, [("overlay.tif", 0, RASTER_NATIVE_RENDER_SCALE, 0)]
        )
        expected_size = round(72 * INTERACTIVE_PDF_RENDER_SCALE)
        self.assertEqual(
            (image.width(), image.height()), (expected_size, expected_size)
        )

    def test_raster_source_background_loads_native_pixels(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        source = QImage(10, 7, QImage.Format.Format_ARGB32)
        cache = _overlay_export_support__RecordingImageCache(source)
        exporter._export_page_cache = cache
        written_images = []
        forwarded = []
        exporter._write_raster_background_pdf = (
            lambda image, *args: written_images.append(image)
            or forwarded.append(args)
            or "image.pdf"
        )
        result = exporter._create_image_source_background_pdf(
            "main.tif",
            0,
            {"width": 72.0, "height": 72.0},
            "unused",
            "image",
        )
        self.assertEqual(result, "image.pdf")
        self.assertEqual(
            cache.requests, [("main.tif", 0, RASTER_NATIVE_RENDER_SCALE, 0)]
        )
        self.assertEqual(len(written_images), 1)
        self.assertIs(written_images[0], source)
        self.assertEqual(
            forwarded, [({"width": 72.0, "height": 72.0}, "unused", "image")]
        )
        self.assertEqual(
            (written_images[0].width(), written_images[0].height()), (10, 7)
        )

    def test_raster_background_pixel_density_does_not_change_pdf_page_geometry(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        page_info = {"width": 72.0, "height": 36.0}
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = []
            for width, height, prefix in ((16, 8, "native"), (32, 16, "upsampled")):
                image = QImage(width, height, QImage.Format.Format_ARGB32)
                image.fill(QColor(255, 0, 0))
                paths.append(
                    exporter._write_raster_background_pdf(
                        image, page_info, temp_dir, prefix
                    )
                )
            pdf_texts = [_overlay_export_support__read_pdf_text(path) for path in paths]
        for pdf_text in pdf_texts:
            self.assertIn("/MediaBox [0 0 72.000000 36.000000]", pdf_text)

    def test_composite_export_selects_scale_from_base_source_type(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        calls = []
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        exporter._export_composite_renderer = SimpleNamespace(
            render_composite=lambda _page, **kwargs: calls.append(kwargs) or image
        )
        exporter._write_raster_background_pdf = lambda *_args: "composite.pdf"
        for path, expected in (
            ("main.pdf", INTERACTIVE_PDF_RENDER_SCALE),
            ("main.tif", RASTER_NATIVE_RENDER_SCALE),
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    exporter._create_composite_background_pdf(
                        _overlay_export_support__page(image_path=path),
                        {"width": 72.0, "height": 72.0},
                        "unused",
                    ),
                    "composite.pdf",
                )
                self.assertEqual(calls[-1]["render_scale"], expected)
                self.assertIsNone(calls[-1]["bid_ref"])
                self.assertEqual(calls[-1]["raster_rotation"], 0)

    def test_composite_export_renders_an_unrotated_unflipped_page(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        captured_pages = []
        exporter._export_composite_renderer = SimpleNamespace(
            render_composite=lambda page, **_kwargs: captured_pages.append(page)
            or QImage(10, 10, QImage.Format.Format_ARGB32)
        )
        exporter._write_raster_background_pdf = lambda *_args: "composite.pdf"
        page = _overlay_export_support__page(rotation=90, flip_x=True, flip_y=True)
        exporter._create_composite_background_pdf(
            page, {"width": 612.0, "height": 792.0}, "unused"
        )
        self.assertEqual(len(captured_pages), 1)
        rendered = captured_pages[0]
        self.assertEqual(
            (rendered.rotation, rendered.flip_x, rendered.flip_y), (0, False, False)
        )
        # User rotation and flips are applied once, by the native writer.
        self.assertEqual((page.rotation, page.flip_x, page.flip_y), (90, True, True))

    def test_composite_export_uses_native_page_geometry_not_stored_dimensions(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        image = QImage(20, 10, QImage.Format.Format_ARGB32)
        captured_pages = []
        exporter._export_composite_renderer = SimpleNamespace(
            render_composite=lambda page, **_kwargs: captured_pages.append(page)
            or image
        )
        exporter._write_raster_background_pdf = (
            lambda rendered, _page_info, _temp_dir, _prefix: (
                "composite.pdf" if rendered is image else None
            )
        )
        page = _overlay_export_support__page(
            width_pts=42.0 * 72.0, height_pts=30.0 * 72.0
        )
        result = exporter._create_composite_background_pdf(
            page,
            {"width": 36.0 * 72.0, "height": 24.0 * 72.0},
            "unused",
        )
        self.assertEqual(result, "composite.pdf")
        self.assertEqual(len(captured_pages), 1)
        self.assertEqual(captured_pages[0].width_pts, 36.0 * 72.0)
        self.assertEqual(captured_pages[0].height_pts, 24.0 * 72.0)
        self.assertEqual(page.width_pts, 42.0 * 72.0)
        self.assertEqual(page.height_pts, 30.0 * 72.0)

    def test_overlay_only_raster_export_uses_single_image_source_path(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        calls = []
        exporter._create_image_source_background_pdf = (
            lambda source_path, page_index, _page_info, temp_dir, prefix: calls.append(
                (source_path, page_index, prefix)
            )
            or os.path.join(temp_dir, "overlay-image.pdf")
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.tif", image_show_mode=SHOW_OVERLAY
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [("overlay.tif", 0, "overlay")])
        self.assertTrue(exported_page.source_pdf.endswith("overlay-image.pdf"))
        self.assertEqual(exported_page.page_index, 0)

    def test_overlay_only_raster_export_does_not_use_comparison_rendering(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "overlay-only raster export should not use comparison rendering"
            )
        )
        exporter._create_image_source_background_pdf = lambda _source_path, _page_index, _page_info, temp_dir, _prefix: os.path.join(
            temp_dir, "overlay-image.pdf"
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.tif", image_show_mode=SHOW_OVERLAY
            ),
        )
        self.assertTrue(result.success)

    def test_main_and_overlay_export_uses_flattened_composite_background(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        calls = []
        exporter._create_composite_background_pdf = (
            lambda page, page_info, temp_dir: calls.append(
                (page.image_path, page.overlay_image_path)
            )
            or os.path.join(temp_dir, "composite.pdf")
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(calls, [("main.pdf", "overlay.pdf")])
        self.assertTrue(exported_page.source_pdf.endswith("composite.pdf"))
        self.assertEqual(exported_page.page_index, 0)
        self.assertFalse(exported_page.is_blank)

    def test_main_and_overlay_falls_back_to_main_when_composite_render_fails(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: None
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "main.pdf")
        self.assertEqual(exported_page.page_index, 2)

    def test_missing_main_with_overlay_enabled_exports_overlay(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "a missing main source should not trigger comparison rendering"
            )
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                image_path="",
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_BOTH,
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(writer.pages[0].source_pdf, "overlay.pdf")

    def test_hidden_main_with_overlay_enabled_exports_overlay_directly(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, _temp_dir: self.fail(
                "hidden main layer should not trigger comparison rendering"
            )
        )
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                layer_visible=False,
                overlay_image_path="overlay.pdf",
                image_show_mode=SHOW_BOTH,
            ),
        )
        self.assertTrue(result.success)
        self.assertEqual(writer.pages[0].source_pdf, "overlay.pdf")

    def test_blank_page_export_remains_blank(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                image_path="", overlay_image_path="", image_show_mode=SHOW_ORIGINAL
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertTrue(exported_page.is_blank)
        self.assertEqual(exported_page.source_pdf, "")
        self.assertEqual(exported_page.page_width, 612.0)
        self.assertEqual(exported_page.page_height, 792.0)
        self.assertEqual(writer.merge_calls, 1)

    def test_annotations_are_exported_over_composite_background(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        dimension = ost_pdf_writer.DimensionAnnotationData()
        dimension.content = "10' - 0\""
        exporter._create_composite_background_pdf = (
            lambda _page, _page_info, temp_dir: os.path.join(temp_dir, "composite.pdf")
        )
        exporter._collect_dimensions = lambda _uid, _annotations, _page_info: [
            dimension
        ]
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf", image_show_mode=SHOW_BOTH
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertTrue(exported_page.source_pdf.endswith("composite.pdf"))
        self.assertEqual(exported_page.dimensions[0].content, "10' - 0\"")

    def test_raster_background_pdf_draws_scaled_image_to_full_page_points(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
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
            pdf_text = _overlay_export_support__read_pdf_text(output_path)
            stream_text = _overlay_export_support__read_pdf_stream_text(output_path)
        self.assertIn("/MediaBox [0 0 612.000000 792.000000]", pdf_text)
        self.assertIn("1 0 0 -1 0 792 cm", stream_text)
        self.assertIn("0.500000000 0 0 0.500000000 0 0 cm", stream_text)
        self.assertNotIn("0.060000000 0 0 -0.060000000", stream_text)

    def test_raster_background_pdf_ends_painter_when_drawing_fails(self):
        exporter = _overlay_export_support__make_exporter(
            _overlay_export_support__FakeWriter()
        )
        rendered_image = QImage(10, 10, QImage.Format.Format_ARGB32)
        rendered_image.fill(QColor(255, 0, 0))
        _overlay_export_support__ExplodingPainter.last_instance = None
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch(
                "ost_visualizer.presentation.visualization.exporters.pdf_exporter.QPainter",
                _overlay_export_support__ExplodingPainter,
            ):
                with self.assertRaisesRegex(RuntimeError, "draw failed"):
                    exporter._write_raster_background_pdf(
                        rendered_image,
                        {"width": 612.0, "height": 792.0},
                        temp_dir,
                        "composite",
                    )
        self.assertIsNotNone(_overlay_export_support__ExplodingPainter.last_instance)
        self.assertTrue(_overlay_export_support__ExplodingPainter.last_instance.ended)

    def test_annotations_are_exported_over_overlay_only_source(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        dimension = ost_pdf_writer.DimensionAnnotationData()
        dimension.content = "6' - 0\""
        exporter._collect_dimensions = lambda _uid, _annotations, _page_info: [
            dimension
        ]
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                overlay_image_path="overlay.pdf", image_show_mode=SHOW_OVERLAY
            ),
        )
        self.assertTrue(result.success)
        exported_page = writer.pages[0]
        self.assertEqual(exported_page.source_pdf, "overlay.pdf")
        self.assertEqual(exported_page.dimensions[0].content, "6' - 0\"")

    def test_single_page_export_merges_once(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        progress_calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "out.pdf")
            result = exporter.export(
                [PageExportDto(page=_overlay_export_support__page())],
                output_path,
                display_mode="color",
                grayscale_enabled=False,
                caption_settings=_overlay_export_support__DISABLED_CAPTION_SETTINGS,
                elevation_callouts_enabled=False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                on_progress=lambda current, total, name: progress_calls.append(
                    (current, total, name)
                ),
            )
        self.assertTrue(result.success)
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.format_name, "PDF")
        self.assertEqual(writer.merge_calls, 1)
        self.assertEqual(writer.output_paths, [output_path])
        self.assertEqual(progress_calls, [(1, 1, "Page 1")])

    def test_multi_page_export_keeps_page_order_and_reports_progress(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        progress_calls = []
        pages = [
            _overlay_export_support__page(
                uid="a", name="First", image_path="a.pdf", page_index=0
            ),
            _overlay_export_support__page(
                uid="b", name="", image_path="b.pdf", page_index=1
            ),
            _overlay_export_support__page(
                uid="c", name="Third", image_path="c.pdf", page_index=2
            ),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            result = exporter.export(
                [PageExportDto(page=page) for page in pages],
                os.path.join(temp_dir, "out.pdf"),
                display_mode="color",
                grayscale_enabled=False,
                caption_settings=_overlay_export_support__DISABLED_CAPTION_SETTINGS,
                elevation_callouts_enabled=False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                on_progress=lambda current, total, name: progress_calls.append(
                    (current, total, name)
                ),
            )
        self.assertTrue(result.success)
        self.assertEqual(result.page_count, 3)
        self.assertEqual(writer.merge_calls, 1)
        self.assertEqual(
            [(page.source_pdf, page.page_index) for page in writer.pages],
            [("a.pdf", 0), ("b.pdf", 1), ("c.pdf", 2)],
        )
        self.assertEqual(
            progress_calls,
            [(1, 3, "First"), (2, 3, "Page 2"), (3, 3, "Third")],
        )

    def test_export_without_pages_reports_no_data_and_does_not_write(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        page_cache = _overlay_export_support__Clearable()
        exporter._export_page_cache = page_cache
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertLogs(
                "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
                level="ERROR",
            ):
                result = exporter.export(
                    [],
                    os.path.join(temp_dir, "out.pdf"),
                    display_mode="color",
                    grayscale_enabled=False,
                    caption_settings=_overlay_export_support__DISABLED_CAPTION_SETTINGS,
                    elevation_callouts_enabled=False,
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, ExportErrorCode.NO_DATA)
        self.assertEqual(result.error_message, "No valid pages to export.")
        self.assertEqual(writer.merge_calls, 0)
        self.assertEqual(page_cache.clear_calls, 1)

    def test_native_merge_failure_is_reported_with_the_writer_error(self):
        for last_error, expected in (
            ("disk full", "disk full"),
            ("", "Failed to write PDF."),
        ):
            with self.subTest(last_error=last_error):
                writer = _overlay_export_support__FakeWriter()
                writer.merge_result = False
                writer.last_error = last_error
                exporter = _overlay_export_support__make_exporter(writer)
                page_cache = _overlay_export_support__Clearable()
                exporter._export_page_cache = page_cache
                with self.assertLogs(
                    "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
                    level="ERROR",
                ):
                    result = _overlay_export_support__export_single_page(
                        exporter, _overlay_export_support__page()
                    )
                self.assertFalse(result.success)
                self.assertEqual(result.error_code, ExportErrorCode.WRITE_FAILED)
                self.assertEqual(result.error_message, expected)
                self.assertEqual(writer.merge_calls, 1)
                self.assertEqual(page_cache.clear_calls, 1)

    def test_unexpected_exception_is_reported_and_resources_are_still_cleared(self):
        writer = _overlay_export_support__FakeWriter()

        def exploding_merge(_pages, _output_path):
            raise OSError("writer exploded")

        writer.merge_pages_with_annotations = exploding_merge
        exporter = _overlay_export_support__make_exporter(writer)
        page_cache = _overlay_export_support__Clearable()
        composite_renderer = _overlay_export_support__Clearable()
        exporter._export_page_cache = page_cache
        exporter._export_composite_renderer = composite_renderer
        with self.assertLogs(
            "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
            level="ERROR",
        ):
            result = _overlay_export_support__export_single_page(
                exporter, _overlay_export_support__page()
            )
        self.assertFalse(result.success)
        self.assertEqual(result.error_code, ExportErrorCode.UNEXPECTED)
        self.assertEqual(result.error_message, "writer exploded")
        self.assertEqual(page_cache.clear_calls, 1)
        self.assertEqual(composite_renderer.clear_calls, 1)

    def test_export_geometry_follows_native_unit_rotation_and_user_rotation(self):
        # Visible box is 300 x 400 native units at UserUnit 2: 600 x 800 pt.
        box = (10.0, 20.0, 310.0, 420.0)
        cases = (
            # native rotation, user rotation, (source w, h), (export w, h), stored rotation
            (0, 0, (600.0, 800.0), (600.0, 800.0), 0),
            (90, 0, (800.0, 600.0), (800.0, 600.0), 0),
            (270, 0, (800.0, 600.0), (800.0, 600.0), 0),
            (0, 90, (600.0, 800.0), (800.0, 600.0), 90),
            (90, 90, (800.0, 600.0), (600.0, 800.0), 90),
            (0, 180, (600.0, 800.0), (600.0, 800.0), 180),
            (0, -90, (600.0, 800.0), (800.0, 600.0), 270),
            (0, 450, (600.0, 800.0), (800.0, 600.0), 90),
        )
        for native, user, source, export, stored in cases:
            with self.subTest(native_rotation=native, user_rotation=user):
                writer = _overlay_export_support__FakeWriter()
                geometry = _overlay_export_support__geometry(box, 2.0, native)
                writer.get_page_geometries = lambda _path, g=geometry: [g, g, g]
                exporter = _overlay_export_support__make_exporter(writer)
                result = _overlay_export_support__export_single_page(
                    exporter,
                    _overlay_export_support__page(
                        rotation=user, flip_x=user == 0 and native == 0
                    ),
                )
                self.assertTrue(result.success, result.error_message)
                exported = writer.pages[0]
                self.assertEqual(
                    (exported.source_width, exported.source_height), source
                )
                self.assertEqual((exported.page_width, exported.page_height), export)
                self.assertEqual(exported.rotation, stored)
                self.assertEqual(exported.flip_x, user == 0 and native == 0)
                self.assertFalse(exported.flip_y)

    def test_blank_page_export_rotates_stored_dimensions_once(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        result = _overlay_export_support__export_single_page(
            exporter,
            _overlay_export_support__page(
                image_path="",
                image_show_mode=SHOW_ORIGINAL,
                rotation=90,
                flip_y=True,
            ),
        )
        self.assertTrue(result.success)
        exported = writer.pages[0]
        self.assertTrue(exported.is_blank)
        self.assertEqual(
            (exported.source_width, exported.source_height), (612.0, 792.0)
        )
        self.assertEqual((exported.page_width, exported.page_height), (792.0, 612.0))
        self.assertEqual(exported.rotation, 90)
        self.assertTrue(exported.flip_y)

    def test_invalid_native_page_geometry_fails_the_export_without_writing(self):
        cases = {
            "page index beyond the native pages": (
                [_overlay_export_support__geometry()],
                "Native PDF page geometry is unavailable for page 2",
            ),
            "empty visible box": (
                [_overlay_export_support__geometry((5.0, 5.0, 5.0, 100.0))] * 3,
                "Native PDF page geometry is invalid for page 2",
            ),
        }
        for name, (geometries, message) in cases.items():
            with self.subTest(case=name):
                writer = _overlay_export_support__FakeWriter()
                writer.get_page_geometries = lambda _path, g=geometries: list(g)
                exporter = _overlay_export_support__make_exporter(writer)
                with self.assertLogs(
                    "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
                    level="ERROR",
                ):
                    result = _overlay_export_support__export_single_page(
                        exporter, _overlay_export_support__page()
                    )
                self.assertFalse(result.success)
                self.assertEqual(result.error_message, message)
                self.assertEqual(writer.merge_calls, 0)

    def test_export_clears_background_render_resources_after_run(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        page_cache = _overlay_export_support__Clearable()
        composite_renderer = _overlay_export_support__Clearable()
        exporter._export_page_cache = page_cache
        exporter._export_composite_renderer = composite_renderer
        result = _overlay_export_support__export_single_page(
            exporter, _overlay_export_support__page()
        )
        self.assertTrue(result.success)
        self.assertEqual(page_cache.clear_calls, 1)
        self.assertEqual(composite_renderer.clear_calls, 1)

    def test_cleanup_failure_preserves_result_and_clears_remaining_resources(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        page_cache = _overlay_export_support__Clearable()
        composite_renderer = _overlay_export_support__FailingClearable()
        exporter._export_page_cache = page_cache
        exporter._export_composite_renderer = composite_renderer
        with self.assertLogs(
            "ost_visualizer.presentation.visualization.exporters.pdf_exporter",
            level="ERROR",
        ) as captured:
            result = _overlay_export_support__export_single_page(
                exporter, _overlay_export_support__page()
            )
        self.assertTrue(result.success)
        self.assertEqual(composite_renderer.clear_calls, 1)
        self.assertEqual(page_cache.clear_calls, 1)
        self.assertTrue(
            any(
                "Failed to clear PDF export composite renderer cache" in message
                for message in captured.output
            )
        )


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
        self.exporter._color_service = _oval_support__ColorService()

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
            "page",
            [self._annotation(position, width=width)],
            page_info or _oval_support__page_info(),
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
        position = _oval_support__rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
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
        position = _oval_support__rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        thin = self._collect(position, width=0.25)
        thick = self._collect(position, width=12.0)
        self.assertSameGeometry(thin, thick)
        self.assertAlmostEqual(thin.width, 0.25)
        self.assertAlmostEqual(thick.width, 12.0)

    def test_export_geometry_is_independent_of_gui_zoom(self):
        position = _oval_support__rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        low_zoom = self._collect(position, _oval_support__page_info(view_scale=0.125))
        high_zoom = self._collect(position, _oval_support__page_info(view_scale=8.0))
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
                    _oval_support__page_info(),
                )
                self.assertEqual(result, [])
        self.assertAlmostEqual(
            self._collect([10.0, 20.0, 70.0, 80.0], width=0).width, 0
        )

    def test_plan_scale_is_applied_exactly_once(self):
        position = [20.0, 40.0, 140.0, 80.0]
        oval = self._collect(
            position, _oval_support__page_info(scale_factor1=1.0, scale_factor2=144.0)
        )
        self.assertOvalGeometry(
            oval,
            center=(40.0, 370.0),
            x_axis=(30.0, 0.0),
            y_axis=(0.0, -10.0),
        )

    def test_page_rotations_preserve_transformed_center_and_radius_vectors(self):
        position = _oval_support__rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        ost_points = _oval_support__oval_axis_points(self._annotation(position))
        for page_rotation in (0, 90, 180, 270, -90, 360, 450):
            with self.subTest(page_rotation=page_rotation):
                page_info = _oval_support__page_info(rotation=page_rotation)
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
        position = _oval_support__rotated_oval_position(200.0, 150.0, 120.0, 40.0, 30.0)
        ost_points = _oval_support__oval_axis_points(self._annotation(position))
        for flip_x, flip_y in ((True, False), (False, True), (True, True)):
            with self.subTest(flip_x=flip_x, flip_y=flip_y):
                page_info = _oval_support__page_info(flip_x=flip_x, flip_y=flip_y)
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

    def test_axis_aligned_oval_vectors_mirror_with_flips_and_half_turn(self):
        # Circle of radius 30 centred at OST (40, 50) on a 500 x 400 page.
        position = [10.0, 20.0, 70.0, 80.0]
        cases = (
            ("identity", {}, (40.0, 350.0), (30.0, 0.0), (0.0, -30.0)),
            ("flip_x", {"flip_x": True}, (460.0, 350.0), (-30.0, 0.0), (0.0, -30.0)),
            ("flip_y", {"flip_y": True}, (40.0, 50.0), (30.0, 0.0), (0.0, 30.0)),
            ("half turn", {"rotation": 180}, (460.0, 50.0), (-30.0, 0.0), (0.0, 30.0)),
        )
        for name, overrides, center, x_axis, y_axis in cases:
            with self.subTest(case=name):
                oval = self._collect(position, _oval_support__page_info(**overrides))
                self.assertOvalGeometry(
                    oval, center=center, x_axis=x_axis, y_axis=y_axis
                )

    def test_oval_collection_ignores_other_pages_hidden_and_other_annotation_types(
        self,
    ):
        position = [10.0, 20.0, 70.0, 80.0]
        valid = self._annotation(position)
        other_page = self._annotation(position)
        other_page.page_uid = "elsewhere"
        hidden = self._annotation(position)
        hidden.visible = False
        rectangle = self._annotation(position, annotation_type="rect")
        result = self.exporter._collect_ovals(
            "page", [other_page, hidden, rectangle, valid], _oval_support__page_info()
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].color, [0x12, 0x34, 0x56])

    def test_rectangle_and_line_collection_remain_unchanged(self):
        rectangle = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="rect")
        line = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="line")
        rects = self.exporter._collect_rects(
            "page", [rectangle], _oval_support__page_info()
        )
        lines = self.exporter._collect_lines("page", [line], _oval_support__page_info())
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
        self.assertEqual(rects[0].color, [0x12, 0x34, 0x56])
        self.assertEqual((rects[0].width, lines[0].width), (2.0, 2.0))

    def test_rotated_rectangle_uses_the_extent_of_all_eight_coordinates(self):
        rectangle = self._annotation(
            [10.0, 20.0, 130.0, 20.0, 130.0, 60.0, 10.0, 60.0], annotation_type="rect"
        )
        short = self._annotation([10.0, 20.0, 130.0], annotation_type="rect")
        line = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="line")
        rects = self.exporter._collect_rects(
            "page", [short, line, rectangle], _oval_support__page_info()
        )
        self.assertEqual(len(rects), 1)
        self.assertEqual(
            [rects[0].min_x, rects[0].min_y, rects[0].max_x, rects[0].max_y],
            [10.0, 340.0, 130.0, 380.0],
        )

    def test_arrow_and_polygon_collection_convert_to_native_page_coordinates(self):
        arrow = self._annotation([10.0, 20.0, 130.0, 60.0], annotation_type="arrow")
        arrow.width = 3.0
        arrows = self.exporter._collect_arrows(
            "page", [arrow], _oval_support__page_info()
        )
        self.assertEqual(len(arrows), 1)
        self.assertEqual(
            [arrows[0].x1, arrows[0].y1, arrows[0].x2, arrows[0].y2],
            [10.0, 380.0, 130.0, 340.0],
        )
        self.assertEqual((arrows[0].color, arrows[0].width), ([0x12, 0x34, 0x56], 3.0))
        triangle = [0.0, 0.0, 100.0, 0.0, 100.0, 50.0]
        polygon = self._annotation(triangle, annotation_type="polygon")
        cloud = self._annotation(triangle, annotation_type="cloud")
        too_short = self._annotation(triangle[:4], annotation_type="polygon")
        polygons = self.exporter._collect_polygons(
            "page", [polygon, cloud, too_short], _oval_support__page_info()
        )
        self.assertEqual(len(polygons), 2)
        for exported in polygons:
            self.assertEqual(
                [tuple(vertex) for vertex in exported.vertices],
                [(0.0, 400.0), (100.0, 400.0), (100.0, 350.0)],
            )
        self.assertEqual([item.is_cloud for item in polygons], [False, True])


class PdfExportPhysicalGeometryTests(unittest.TestCase):
    @staticmethod
    def _exporter():
        return PDFExporter(
            OSTCoordinateSystem(),
            _pdf_geometry_support__ColorService(),
            _pdf_geometry_support__TakeoffService(),
            _pdf_geometry_support__UomService(),
            object(),
        )

    def test_ink_calibration_matches_plan_geometry_without_mutating_position(self):
        exporter = self._exporter()
        page_info = {
            "width": 400.0,
            "height": 300.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
            "scale_factor1": 1.0,
            "scale_factor2": 144.0,
        }
        for position in (
            [0.0, 20.0, 40.0, 80.0, 100.0],
            [math.pi / 2, 20.0, 40.0, 80.0, 100.0],
            [20.0, 40.0, 80.0, 100.0],
        ):
            with self.subTest(position=position):
                ink = BidAnnotation(
                    uid="ink",
                    annotation_type="ink",
                    page_uid="page",
                    position=list(position),
                    color="#112233",
                    width=3.0,
                )
                exported = exporter._collect_inks("page", [ink], page_info)
                self.assertEqual(len(exported), 1)
                self.assertEqual(exported[0].color, [0x11, 0x22, 0x33])
                self.assertEqual(exported[0].width, 3.0)
                self.assertEqual(
                    [tuple(point) for point in exported[0].strokes[0]],
                    [(10.0, 280.0), (40.0, 250.0)],
                )
                rendered = calculate_annotation_geometry(ink, lambda coords: coords)
                self.assertEqual(rendered["points"], [(20.0, 40.0), (80.0, 100.0)])
                self.assertEqual(ink.position, position)

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

    def test_parented_non_area_takeoffs_are_not_lost_from_pdf_export(self):
        for family, position in (
            (Condition.TYPE_COUNT, [100, 200]),
            (Condition.TYPE_LINEAR, [100, 200, 120, 200]),
        ):
            with self.subTest(family=family):
                takeoff = Takeoff(
                    uid="child",
                    condition_uid="condition",
                    page_uid="page",
                    parent_uid="parent",
                    position=position,
                )
                condition = Condition(
                    uid="condition", condition_type=family, width=5, depth=5
                )
                exporter = self._exporter()
                exporter._takeoff_service = TakeoffDomainService()
                polygons, _callouts = exporter._collect_takeoffs(
                    [takeoff],
                    {condition.uid: condition},
                    {
                        "scale_factor1": 1,
                        "scale_factor2": 72,
                        "rotation": 0,
                        "flip_x": False,
                        "flip_y": False,
                        "width": 612,
                        "height": 792,
                        "view_scale": 1,
                    },
                    inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                    caption_settings=AnnotationCaptionSettingsDto(False, ()),
                    elevation_callouts_enabled=False,
                )
                self.assertEqual(len(polygons), 1)


class PdfElevationCalloutTests(unittest.TestCase):
    def setUp(self):
        uom_service = UOMDomainService()
        self.exporter = PDFExporter(
            OSTCoordinateSystem(),
            ColorService(),
            TakeoffDomainService(),
            uom_service,
            AnnotationCaptionResolver(uom_service),
        )
        self.condition = _elevation_support__area_condition(layer_uid="layer-1")
        self.takeoff = _elevation_support__area_takeoff()
        self.page_info = {
            "scale_factor1": 1.0,
            "scale_factor2": 1.0,
            "rotation": 0,
            "flip_x": False,
            "flip_y": False,
            "width": 612.0,
            "height": 792.0,
            "view_scale": 2.0,
        }

    def test_disabled_pdf_callouts_add_no_text_and_skip_resolution(self):
        with mock.patch.object(
            self.exporter, "_build_elevation_callout_text", autospec=True
        ) as callout_adapter:
            polygons, callouts = self.exporter._collect_takeoffs(
                [self.takeoff],
                {self.condition.uid: self.condition},
                self.page_info,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                caption_settings=AnnotationCaptionSettingsDto(False, ()),
                elevation_callouts_enabled=False,
            )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(callouts, [])
        callout_adapter.assert_not_called()

    def test_enabled_pdf_callout_uses_existing_textbox_data_with_shared_lines(self):
        polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
            elevation_callout_color="#abcdef",
        )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(len(callouts), 1)
        callout = callouts[0]
        self.assertIsInstance(callout, ost_pdf_writer.TextAnnotationData)
        self.assertEqual(
            callout.content.splitlines(),
            _elevation_support__EXPECTED_PDF_CALLOUT_LINES,
        )
        self.assertEqual(callout.text_align, "center")
        self.assertEqual(callout.font_size, 10.0)
        self.assertEqual(callout.color, [171, 205, 239])
        vertices = polygons[0].vertices
        center_x = (
            min(point[0] for point in vertices) + max(point[0] for point in vertices)
        ) / 2.0
        center_y = (
            min(point[1] for point in vertices) + max(point[1] for point in vertices)
        ) / 2.0
        self.assertEqual((callout.min_x + callout.max_x) / 2.0, center_x)
        self.assertEqual((callout.min_y + callout.max_y) / 2.0, center_y)

    def test_export_adds_resolved_callout_to_existing_page_text_pipeline(self):
        writer = _elevation_support__CapturingPdfWriter()
        self.exporter._writer = writer
        page = Page(
            uid="page-1",
            name="Page 1",
            width_pts=612.0,
            height_pts=792.0,
        )
        result = self.exporter.export(
            [
                PageExportData(
                    page=page,
                    bid_takeoffs=[self.takeoff],
                    bid_conditions={self.condition.uid: self.condition},
                )
            ],
            "out.pdf",
            Config.DISPLAY_MODE_ORIGINAL,
            False,
            AnnotationCaptionSettingsDto(False, ()),
            True,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(writer.pages), 1)
        self.assertEqual(len(writer.pages[0].texts), 1)
        self.assertEqual(
            writer.pages[0].texts[0].content.splitlines(),
            _elevation_support__EXPECTED_PDF_CALLOUT_LINES,
        )

    def test_configured_pdf_callout_lines_only_create_selected_text(self):
        _polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
            elevation_callout_settings=ElevationCalloutSettings(
                include_condition=True,
                include_top=False,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )
        self.assertEqual(len(callouts), 1)
        self.assertEqual(callouts[0].content, "F9")

    def test_empty_pdf_callout_selection_creates_no_textbox(self):
        _polygons, callouts = self.exporter._collect_takeoffs(
            [self.takeoff],
            {self.condition.uid: self.condition},
            self.page_info,
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=True,
            elevation_callout_settings=ElevationCalloutSettings(
                include_condition=False,
                include_top=False,
                include_bottom=False,
                include_cubic_yards=False,
            ),
        )
        self.assertEqual(callouts, [])


class BidDimensionAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pdf_export_collects_dimensions_as_native_dimension_data(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        annotation = BidAnnotation(
            uid="d6",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
            properties={"FontName": "Arial", "FontSize": 10},
        )
        lines = exporter._collect_lines(
            "p1", [annotation], _dimension_support__page_info()
        )
        dimensions = exporter._collect_dimensions(
            "p1", [annotation], _dimension_support__page_info()
        )
        texts = exporter._collect_texts(
            "p1", [annotation], _dimension_support__page_info()
        )
        expected_coords = OSTCoordinateSystem.ost_to_pdf_coordinates(
            [0.0, 0.0, 255.0, 0.0], _dimension_support__page_info()
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
        self.assertEqual(dimensions[0].color, [255, 0, 0])
        self.assertEqual(dimensions[0].font_size, 10.0)
        self.assertEqual(
            (dimensions[0].scale_factor1, dimensions[0].scale_factor2), (1.0, 72.0)
        )

    def test_pdf_export_skips_zero_length_dimensions(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        degenerate = BidAnnotation(
            uid="d0",
            annotation_type="dimension",
            page_uid="p1",
            position=[5.0, 5.0, 5.0, 5.0],
            color="#ff0000",
        )
        valid = BidAnnotation(
            uid="d1",
            annotation_type="dimension",
            page_uid="p1",
            position=[0.0, 0.0, 255.0, 0.0],
            color="#ff0000",
        )
        dimensions = exporter._collect_dimensions(
            "p1", [degenerate, valid], _dimension_support__page_info()
        )
        self.assertEqual([dimension.content for dimension in dimensions], ["21' - 3\""])

    def test_text_alignment_values_map_to_native_alignment(self):
        cases = (
            (0, "left"),
            (1, "center"),
            (2, "right"),
            (5, "left"),
            (1.0, "center"),
            (None, "left"),
            ("center", "center"),
            (" Right ", "right"),
            ("1", "center"),
            ("2", "right"),
            ("0", "left"),
            ("left", "left"),
            ("justified", "left"),
            ("", "left"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(PDFExporter._text_align_to_pdf_value(raw), expected)

    def test_pdf_export_collects_text_alignment_from_ost_numeric_values(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()

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
            _dimension_support__page_info(),
        )
        self.assertEqual(
            [text.text_align for text in texts], ["left", "center", "right"]
        )

    def test_pdf_export_skips_invisible_text_annotations(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        hidden = BidAnnotation(
            uid="hidden",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#000000",
            properties={"Text": "Hidden"},
            visible=False,
        )
        shown = BidAnnotation(
            uid="shown",
            annotation_type="text",
            page_uid="p1",
            position=[60.0, 80.0, 40.0, 20.0],
            color="#000000",
            properties={"Text": "Shown"},
        )
        self.assertEqual(
            exporter._collect_texts("p1", [hidden], _dimension_support__page_info()), []
        )
        texts = exporter._collect_texts(
            "p1", [hidden, shown], _dimension_support__page_info()
        )
        self.assertEqual([text.content for text in texts], ["Shown"])
        self.assertEqual(texts[0].font_size, 12.0)

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
        takeoffs, callouts = exporter._collect_takeoffs(
            [takeoff],
            {"c1": condition},
            _dimension_support__page_info(),
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=False,
        )
        self.assertEqual(takeoffs, [])
        self.assertEqual(callouts, [])
        exporter._color_service = _dimension_support__ColorService()
        exporter._color_service.get_condition_color = lambda _condition: [255, 0, 0]
        condition.layer_visible = True
        takeoffs, callouts = exporter._collect_takeoffs(
            [takeoff],
            {"c1": condition},
            _dimension_support__page_info(),
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(False, ()),
            elevation_callouts_enabled=False,
        )
        self.assertEqual(len(takeoffs), 1)
        self.assertEqual(takeoffs[0].color, [255, 0, 0])
        self.assertEqual(callouts, [])

    def test_pdf_export_passes_structured_resolved_caption_to_native_boundary(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        exporter._color_service.get_condition_color = lambda _condition: [255, 0, 0]
        exporter._takeoff_service = SimpleNamespace(
            group_area_takeoffs_with_holes=lambda takeoffs, _conditions: (takeoffs, {})
        )
        exporter._uom_service = UOMDomainService()
        exporter._annotation_caption_resolver = AnnotationCaptionResolver(
            exporter._uom_service
        )
        takeoff = Takeoff(
            uid="t-caption",
            condition_uid="c-caption",
            page_uid="p1",
            position=[0.0, 0.0, 144.0, 0.0, 144.0, 144.0, 0.0, 144.0],
        )
        condition = Condition(
            uid="c-caption",
            name="Slab",
            condition_type=Condition.TYPE_AREA,
            thickness=12.0,
        )
        polygons, callouts = exporter._collect_takeoffs(
            [takeoff],
            {condition.uid: condition},
            _dimension_support__page_info(),
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(
                enabled=True,
                selected_ids=(AnnotationCaptionId.AREA, AnnotationCaptionId.VOLUME),
            ),
            elevation_callouts_enabled=False,
        )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(callouts, [])
        self.assertEqual(polygons[0].color, [255, 0, 0])
        self.assertEqual(polygons[0].fill_opacity, 0.5)
        self.assertEqual(
            polygons[0].caption.lines,
            ["A = 144.00 sf", "V = 5.33 cu yd"],
        )
        self.assertEqual(polygons[0].caption.measurement_types, 5)
        self.assertEqual(
            polygons[0].vertices,
            OSTCoordinateSystem.ost_to_pdf_coordinates(
                takeoff.position, _dimension_support__page_info()
            ),
        )

    def test_disabled_caption_settings_leave_the_native_caption_empty(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        exporter._color_service.get_condition_color = lambda _condition: [255, 0, 0]
        exporter._takeoff_service = SimpleNamespace(
            group_area_takeoffs_with_holes=lambda takeoffs, _conditions: (takeoffs, {})
        )
        exporter._uom_service = UOMDomainService()
        resolved_calls = []
        exporter._annotation_caption_resolver = SimpleNamespace(
            resolve=lambda *args: resolved_calls.append(args)
        )
        takeoff = Takeoff(
            uid="t-caption",
            condition_uid="c-caption",
            page_uid="p1",
            position=[0.0, 0.0, 144.0, 0.0, 144.0, 144.0, 0.0, 144.0],
        )
        condition = Condition(
            uid="c-caption", name="Slab", condition_type=Condition.TYPE_AREA
        )
        polygons, _callouts = exporter._collect_takeoffs(
            [takeoff],
            {condition.uid: condition},
            _dimension_support__page_info(),
            inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
            caption_settings=AnnotationCaptionSettingsDto(
                enabled=False, selected_ids=(AnnotationCaptionId.AREA,)
            ),
            elevation_callouts_enabled=False,
        )
        self.assertEqual(len(polygons), 1)
        self.assertEqual(resolved_calls, [])
        self.assertEqual(list(polygons[0].caption.lines), [])
        self.assertEqual(polygons[0].caption.measurement_types, 0)

    def test_pdf_export_collects_highlights_as_native_highlight_data(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        annotation = BidAnnotation(
            uid="h1",
            annotation_type="highlight",
            page_uid="p1",
            position=[10.0, 20.0, 110.0, 60.0],
            color="#ffff00",
        )
        highlights = exporter._collect_highlights(
            "p1", [annotation], _dimension_support__page_info()
        )
        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            [highlights[0].paths[0][index] for index in (0, 1, 5, 4)],
            [[10.0, 772.0], [110.0, 772.0], [10.0, 732.0], [110.0, 732.0]],
        )
        self.assertEqual(len(highlights[0].paths[0]), 8)
        self.assertEqual(highlights[0].color, [255, 255, 0])
        self.assertAlmostEqual(highlights[0].opacity, 1.0)

    def test_pdf_export_collects_rotated_highlight_corners_in_pdf_quad_order(self):
        exporter = PDFExporter.__new__(PDFExporter)
        exporter._coord_system = OSTCoordinateSystem()
        exporter._color_service = _dimension_support__ColorService()
        annotation = BidAnnotation(
            uid="h2",
            annotation_type="highlight",
            page_uid="p1",
            position=[110.0, 60.0, 10.0, 20.0, 110.0, 20.0, 10.0, 60.0],
            color="#00ff00",
        )
        highlights = exporter._collect_highlights(
            "p1", [annotation], _dimension_support__page_info()
        )
        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            [highlights[0].paths[0][index] for index in (0, 1, 5, 4)],
            [[10.0, 772.0], [110.0, 772.0], [10.0, 732.0], [110.0, 732.0]],
        )


class PdfExportAnnotationRoutingTests(unittest.TestCase):
    def test_export_routes_each_annotation_family_to_its_native_field(self):
        writer = _overlay_export_support__FakeWriter()
        exporter = _overlay_export_support__make_exporter(writer)
        exporter._coord_system = OSTCoordinateSystem()
        families = (
            (ANNOTATION_TYPE_ARROW, 1, [10.0, 20.0, 130.0, 60.0], {}),
            (ANNOTATION_TYPE_RECT, 2, [10.0, 20.0, 130.0, 60.0], {}),
            (ANNOTATION_TYPE_LINE, 3, [10.0, 20.0, 130.0, 60.0], {}),
            (ANNOTATION_TYPE_DIMENSION, 4, [0.0, 0.0, 255.0, 0.0], {}),
            (ANNOTATION_TYPE_OVAL, 5, [10.0, 20.0, 70.0, 80.0], {}),
            (ANNOTATION_TYPE_POLYGON, 6, [0.0, 0.0, 100.0, 0.0, 100.0, 50.0], {}),
            (ANNOTATION_TYPE_INK, 7, [20.0, 40.0, 80.0, 100.0], {}),
            (ANNOTATION_TYPE_TEXT, 8, [60.0, 80.0, 40.0, 20.0], {"Text": "note"}),
            (ANNOTATION_TYPE_HIGHLIGHT, 9, [10.0, 20.0, 110.0, 60.0], {}),
        )
        annotations = []
        for annotation_type, count, position, properties in families:
            for index in range(count):
                annotations.append(
                    BidAnnotation(
                        uid=f"{annotation_type}-{index}",
                        annotation_type=annotation_type,
                        page_uid="page-1",
                        position=list(position),
                        color="#102030",
                        width=2.0,
                        properties=dict(properties),
                    )
                )
            for distractor in ("other-page", "hidden"):
                annotations.append(
                    BidAnnotation(
                        uid=f"{annotation_type}-{distractor}",
                        annotation_type=annotation_type,
                        page_uid=(
                            "elsewhere" if distractor == "other-page" else "page-1"
                        ),
                        position=list(position),
                        color="#102030",
                        width=2.0,
                        properties=dict(properties),
                        visible=distractor != "hidden",
                    )
                )
        annotations.append(
            BidAnnotation(
                uid="cloud",
                annotation_type=ANNOTATION_TYPE_CLOUD,
                page_uid="page-1",
                position=[0.0, 0.0, 100.0, 0.0, 100.0, 50.0],
                color="#102030",
                width=2.0,
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = exporter.export(
                [PageExportDto(page=_overlay_export_support__page())],
                os.path.join(temp_dir, "out.pdf"),
                display_mode="color",
                grayscale_enabled=False,
                caption_settings=_overlay_export_support__DISABLED_CAPTION_SETTINGS,
                elevation_callouts_enabled=False,
                inactive_object_color=Config.DEFAULT_INACTIVE_OBJECT_COLOR,
                bid_annotations=annotations,
            )
        self.assertTrue(result.success, result.error_message)
        exported = writer.pages[0]
        self.assertEqual(
            {
                "arrows": len(exported.arrows),
                "rects": len(exported.rects),
                "lines": len(exported.lines),
                "dimensions": len(exported.dimensions),
                "ovals": len(exported.ovals),
                "polygons": len(exported.polygons),
                "inks": len(exported.inks),
                "texts": len(exported.texts),
                "highlights": len(exported.highlights),
                "takeoffs": len(exported.takeoffs),
            },
            {
                "arrows": 1,
                "rects": 2,
                "lines": 3,
                "dimensions": 4,
                "ovals": 5,
                "polygons": 7,
                "inks": 7,
                "texts": 8,
                "highlights": 9,
                "takeoffs": 0,
            },
        )
        self.assertEqual(
            [polygon.is_cloud for polygon in exported.polygons],
            [False] * 6 + [True],
        )
        self.assertEqual(exported.texts[0].content, "note")
