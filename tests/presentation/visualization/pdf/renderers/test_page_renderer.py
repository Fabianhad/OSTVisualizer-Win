from PySide6.QtGui import QColor, QImage
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from unittest.mock import patch
import unittest
import tempfile
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from tests.presentation.components.plan_view.visible_frame_support import (
    _write_colored_corner_pdf as _preferences_support__write_colored_corner_pdf,
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
            self.assertIsNone(renderer._current_pdf_signature)
            self.assertIsNotNone(renderer._ensure_pdf_open_locked("first.pdf"))
            self.assertEqual(renderer._current_pdf_path, "first.pdf")
        self.assertEqual(
            _FakePdfRenderer.open_calls,
            ["first.pdf", "broken.pdf", "first.pdf"],
        )
        # The stale document is closed before each open attempt.
        self.assertEqual(_FakePdfRenderer.close_calls, 3)

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
        self.assertEqual(
            (upsampled.width(), upsampled.height()),
            (
                int(3 * INTERACTIVE_PDF_RENDER_SCALE),
                int(2 * INTERACTIVE_PDF_RENDER_SCALE),
            ),
        )
        for index, color in enumerate(colors):
            self.assertEqual(native.pixelColor(index % 3, index // 3), color)


class PageRendererPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_page_renderer_reopens_same_path_pdf_when_file_signature_changes(self):
        events = []

        class FakePdfRenderer:
            def open(self, file_path):
                events.append(("open", file_path))
                return True

            def close(self):
                events.append(("close", None))

            def get_last_error(self):
                return "fake"

        fake_pdf = FakePdfRenderer()
        renderer = PageRenderer()
        renderer._get_pdf_renderer = lambda: fake_pdf
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ostv_renderer_signature.pdf"
            path.write_bytes(b"first")
            try:
                self.assertIs(renderer._ensure_pdf_open_locked(str(path)), fake_pdf)
                self.assertIs(renderer._ensure_pdf_open_locked(str(path)), fake_pdf)
                self.assertEqual(
                    [event for event in events if event[0] == "open"],
                    [("open", str(path))],
                )
                path.write_bytes(b"second-version")
                self.assertIs(renderer._ensure_pdf_open_locked(str(path)), fake_pdf)
            finally:
                renderer.close()
        # Unchanged file: cached. Changed file: closed then reopened.
        self.assertEqual(
            events,
            [
                ("close", None),
                ("open", str(path)),
                ("close", None),
                ("open", str(path)),
            ],
        )

    def test_pdf_frame_render_matches_full_page_orientation(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        pdf_path = Path(temp_dir.name) / "ostv_frame_orientation.pdf"
        _preferences_support__write_colored_corner_pdf(pdf_path)
        renderer = PageRenderer()
        self.addCleanup(renderer.close)
        red, green, blue, yellow = (
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (255, 255, 0),
        )
        # (frame size, corners top-left, top-right, bottom-left, bottom-right)
        expected = {
            0: ((200, 100), [red, green, blue, yellow]),
            90: ((100, 200), [blue, red, yellow, green]),
            180: ((200, 100), [yellow, blue, green, red]),
            270: ((100, 200), [green, yellow, red, blue]),
        }

        def sample_corners(image):
            points = [
                (10, 10),
                (image.width() - 10, 10),
                (10, image.height() - 10),
                (image.width() - 10, image.height() - 10),
            ]
            return [
                (
                    image.pixelColor(x, y).red(),
                    image.pixelColor(x, y).green(),
                    image.pixelColor(x, y).blue(),
                )
                for x, y in points
            ]

        for rotation, ((frame_w, frame_h), corners) in expected.items():
            with self.subTest(rotation=rotation):
                full = renderer.render(str(pdf_path), 0, 1.0, rotation)
                frame = renderer.render_frame(
                    str(pdf_path),
                    0,
                    1.0,
                    0.0,
                    0.0,
                    frame_w,
                    frame_h,
                    rotation,
                )
                self.assertEqual((full.width(), full.height()), (frame_w, frame_h))
                self.assertEqual((frame.width(), frame.height()), (frame_w, frame_h))
                self.assertEqual(sample_corners(full), corners)
                self.assertEqual(sample_corners(frame), corners)

    def test_pdf_subframe_render_matches_full_page_crop(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        pdf_path = Path(temp_dir.name) / "ostv_frame_crop.pdf"
        _preferences_support__write_colored_corner_pdf(pdf_path)
        renderer = PageRenderer()
        self.addCleanup(renderer.close)
        scale = 2.0
        full = renderer.render(str(pdf_path), 0, scale, 0)
        # (x, y, w, h, expected size, probe pixel, expected colour at the probe)
        frames = [
            (0.0, 0.0, 80.0, 40.0, (160, 80), (4, 4), QColor(255, 0, 0)),
            (70.0, 30.0, 60.0, 40.0, (120, 80), (60, 40), QColor(255, 255, 255)),
            (150.0, 60.0, 50.0, 40.0, (100, 80), (80, 60), QColor(255, 255, 0)),
        ]
        for frame_x, frame_y, frame_w, frame_h, size, probe, colour in frames:
            with self.subTest(frame=(frame_x, frame_y, frame_w, frame_h)):
                frame = renderer.render_frame(
                    str(pdf_path),
                    0,
                    scale,
                    frame_x,
                    frame_y,
                    frame_w,
                    frame_h,
                    0,
                )
                self.assertEqual((frame.width(), frame.height()), size)
                self.assertEqual(frame.pixelColor(*probe), colour)
                crop = full.copy(
                    QtCore.QRect(
                        int(frame_x * scale + 0.5),
                        int(frame_y * scale + 0.5),
                        frame.width(),
                        frame.height(),
                    )
                )
                self.assertEqual(frame.size(), crop.size())
                for y in range(frame.height()):
                    for x in range(frame.width()):
                        self.assertEqual(
                            frame.pixel(x, y),
                            crop.pixel(x, y),
                            f"pixel mismatch at {x},{y}",
                        )
