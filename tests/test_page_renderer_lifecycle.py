import os
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtGui import QColor, QImage
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)


class _FakePdfRenderer:
    open_results = {}
    open_calls = []
    close_calls = 0

    def open(self, file_path):
        self.open_calls.append(file_path)
        return self.open_results.get(file_path, True)

    def close(self):
        type(self).close_calls += 1

    def get_last_error(self):
        return "open failed"


class PageRendererLifecycleTests(unittest.TestCase):
    def setUp(self):
        _FakePdfRenderer.open_results = {}
        _FakePdfRenderer.open_calls = []
        _FakePdfRenderer.close_calls = 0

    def test_failed_pdf_open_clears_cached_path_before_reopen(self):
        _FakePdfRenderer.open_results = {
            "first.pdf": True,
            "broken.pdf": False,
        }
        renderer = PageRenderer()
        with patch(
            "ost_visualizer.presentation.visualization.pdf.renderers.page_renderer."
            "ost_pdf.PDFRenderer",
            _FakePdfRenderer,
        ):
            self.assertIsNotNone(renderer._ensure_pdf_open_locked("first.pdf"))
            self.assertEqual(renderer._current_pdf_path, "first.pdf")
            self.assertIsNone(renderer._ensure_pdf_open_locked("broken.pdf"))
            self.assertIsNone(renderer._current_pdf_path)
            self.assertIsNotNone(renderer._ensure_pdf_open_locked("first.pdf"))
        self.assertEqual(
            _FakePdfRenderer.open_calls,
            ["first.pdf", "broken.pdf", "first.pdf"],
        )

    def test_raster_native_scale_preserves_source_pixels_without_upsampling(self):
        source = QImage(3, 2, QImage.Format.Format_ARGB32)
        colors = (
            QColor(255, 0, 0),
            QColor(0, 255, 0),
            QColor(0, 0, 255),
            QColor(255, 255, 0),
            QColor(0, 255, 255),
            QColor(255, 0, 255),
        )
        for index, color in enumerate(colors):
            source.setPixelColor(index % 3, index // 3, color)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "source.tif")
            self.assertTrue(source.save(path))
            renderer = PageRenderer()
            native = renderer.render(path, 0, RASTER_NATIVE_RENDER_SCALE, 0)
            upsampled = renderer.render(path, 0, INTERACTIVE_PDF_RENDER_SCALE, 0)
        self.assertIsNotNone(native)
        self.assertIsNotNone(upsampled)
        self.assertEqual((native.width(), native.height()), (3, 2))
        self.assertEqual((upsampled.width(), upsampled.height()), (6, 4))
        for index, color in enumerate(colors):
            self.assertEqual(native.pixelColor(index % 3, index // 3), color)


if __name__ == "__main__":
    unittest.main()
