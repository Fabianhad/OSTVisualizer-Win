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
from ost_visualizer.presentation.visualization.utils.image_bands import BAND_PIXELS
from tests.presentation.visualization.utils.image_op_spy import (
    largest_operation,
    recorded_image_operations,
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

    def test_large_pdf_renders_convert_in_bands_without_changing_the_picture(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        pdf_path = Path(temp_dir.name) / "ostv_large_frame.pdf"
        _preferences_support__write_colored_corner_pdf(pdf_path)
        renderer = PageRenderer()
        self.addCleanup(renderer.close)
        red, yellow = (255, 0, 0), (255, 255, 0)
        for label, render in (
            ("page", lambda: renderer.render(str(pdf_path), 0, 8.0, 0)),
            (
                "frame",
                lambda: renderer.render_frame(
                    str(pdf_path), 0, 8.0, 0.0, 0.0, 200.0, 100.0, 0
                ),
            ),
        ):
            with self.subTest(render=label):
                with recorded_image_operations() as operations:
                    image = render()
                self.assertEqual((image.width(), image.height()), (1600, 800))
                self.assertGreater(image.width() * image.height(), 2 * BAND_PIXELS)
                self.assertEqual(
                    image.format(), QtGui.QImage.Format.Format_ARGB32_Premultiplied
                )
                top_left = image.pixelColor(10, 10)
                bottom_right = image.pixelColor(image.width() - 10, image.height() - 10)
                self.assertEqual(
                    (top_left.red(), top_left.green(), top_left.blue()), red
                )
                self.assertEqual(
                    (bottom_right.red(), bottom_right.green(), bottom_right.blue()),
                    yellow,
                )
                self.assertLessEqual(largest_operation(operations), BAND_PIXELS)

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


_RENDERER_LOGGER = (
    "ost_visualizer.presentation.visualization.pdf.renderers.page_renderer"
)


class PageRendererNativeDocumentTests(unittest.TestCase):
    """PageRenderer against real PDFium documents and real image files."""

    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()

    def setUp(self):
        from ost_visualizer.presentation.visualization.exporters import ost_pdf_writer

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        writer = ost_pdf_writer.PDFWriter()
        pages = []
        for width in (100.0, 200.0, 300.0):
            page = ost_pdf_writer.PageExportData()
            page.is_blank = True
            page.page_width = width
            page.page_height = 50.0
            pages.append(page)
        self.three_pages = str(self.dir / "three.pdf")
        self.assertTrue(writer.merge_pages_with_annotations(pages, self.three_pages))
        self.garbage_pdf = self.dir / "garbage.pdf"
        self.garbage_pdf.write_bytes(b"not a pdf")
        self.tiff = self.dir / "seven_by_five.tif"
        image = QImage(7, 5, QImage.Format.Format_ARGB32)
        image.fill(QColor(255, 0, 0))
        self.assertTrue(image.save(str(self.tiff)))
        self.garbage_tiff = self.dir / "garbage.tif"
        self.garbage_tiff.write_bytes(b"garbage")
        self.renderer = PageRenderer()
        self.addCleanup(self.renderer.close)

    def test_page_indexes_outside_the_document_render_the_nearest_page(self):
        widths = {
            index: self.renderer.render(self.three_pages, index, 1.0, 0).width()
            for index in (-3, -1, 0, 1, 2, 3, 99)
        }
        self.assertEqual(
            widths, {-3: 100, -1: 100, 0: 100, 1: 200, 2: 300, 3: 300, 99: 300}
        )

    def test_page_count_size_and_info_come_from_the_native_document(self):
        self.assertEqual(self.renderer.get_page_count(self.three_pages), 3)
        self.assertEqual(
            self.renderer.get_page_size(self.three_pages, 1), (200.0, 50.0)
        )
        self.assertEqual(self.renderer.get_page_size(self.three_pages), (100.0, 50.0))
        self.assertEqual(
            self.renderer.get_page_info(self.three_pages, 2),
            {
                "pdf_width": 300.0,
                "pdf_height": 50.0,
                "media_width_pts": 300.0,
                "media_height_pts": 50.0,
                "crop_width_pts": 300.0,
                "crop_height_pts": 50.0,
                "intrinsic_rotation": 0,
            },
        )
        self.assertEqual(
            self.renderer.get_page_info(self.three_pages)["pdf_width"], 100.0
        )

    def test_page_info_reports_the_rotated_effective_size_and_unrotated_crop(self):
        from tests.integration.rendering.pdf_geometry_support import _write_pdf

        path = self.dir / "boxes.pdf"
        _write_pdf(
            path, 300, 200, origin=(5.0, 6.0), crop_box=(20, 10, 220, 160), rotation=90
        )
        info = self.renderer.get_page_info(str(path), 0)
        self.assertEqual((info["pdf_width"], info["pdf_height"]), (150.0, 200.0))
        self.assertEqual(
            (info["crop_width_pts"], info["crop_height_pts"]), (200.0, 150.0)
        )
        self.assertEqual(info["intrinsic_rotation"], 90)
        self.assertEqual(self.renderer.get_page_size(str(path)), (150.0, 200.0))

    def test_a_page_the_native_renderer_has_no_info_for_reports_neutral_metadata(self):
        from ost_visualizer.presentation.visualization.pdf import ost_pdf

        # The real extension answers None for a page index outside the document.
        native = ost_pdf.PDFRenderer()
        self.assertTrue(native.open(self.three_pages))
        try:
            self.assertIsNone(native.page_info(99))
        finally:
            native.close()

        class NoInfoPdf:
            def open(self, _path):
                return True

            def close(self):
                pass

            def get_last_error(self):
                return ""

            def page_info(self, _index):
                return None

        renderer = PageRenderer()
        renderer._get_pdf_renderer = lambda: NoInfoPdf()
        info = renderer.get_page_info(self.three_pages, 99)
        self.assertEqual(
            info,
            {
                "pdf_width": 0.0,
                "pdf_height": 0.0,
                "media_width_pts": 0.0,
                "media_height_pts": 0.0,
                "crop_width_pts": 0.0,
                "crop_height_pts": 0.0,
                "intrinsic_rotation": 0,
            },
        )

    def test_text_runs_come_from_the_requested_page_of_a_real_pdf(self):
        from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

        path = write_takeoff_pdf(self.dir / "text.pdf", texts=[(150, 500, 12, "GRID")])
        runs = self.renderer.extract_text_runs(str(path))
        self.assertEqual([run.text for run in runs], ["GRID"])
        self.assertEqual(self.renderer.extract_text_runs(str(path), 1), [])
        self.assertTrue(150.0 < runs[0].left < runs[0].right < 190.0)
        self.assertEqual(self.renderer.extract_text_runs(self.three_pages, 1), [])

    def test_metadata_of_raster_images_uses_their_pixel_size(self):
        self.assertEqual(self.renderer.get_page_size(str(self.tiff)), (7.0, 5.0))
        info = self.renderer.get_page_info(str(self.tiff))
        self.assertEqual((info["pdf_width"], info["pdf_height"]), (7.0, 5.0))
        self.assertEqual(
            [info[key] for key in info if key not in ("pdf_width", "pdf_height")],
            [0.0, 0.0, 0.0, 0.0, 0],
        )
        with self.assertNoLogs(_RENDERER_LOGGER, "ERROR"):
            self.assertEqual(self.renderer.get_page_count(str(self.tiff)), 1)
            self.assertEqual(self.renderer.extract_text_runs(str(self.tiff)), [])
        self.assertEqual(
            self.renderer.get_page_size(str(self.garbage_tiff)), (0.0, 0.0)
        )

    def test_missing_files_report_neutral_metadata(self):
        missing = str(self.dir / "missing.pdf")
        empty_info = {
            "pdf_width": 0.0,
            "pdf_height": 0.0,
            "media_width_pts": 0.0,
            "media_height_pts": 0.0,
            "crop_width_pts": 0.0,
            "crop_height_pts": 0.0,
            "intrinsic_rotation": 0,
        }
        with self.assertLogs(_RENDERER_LOGGER, "WARNING") as captured:
            self.assertEqual(self.renderer.get_page_size(missing), (0.0, 0.0))
        self.assertEqual(
            captured.output,
            [f"WARNING:{_RENDERER_LOGGER}:get_page_size: File not found: {missing}"],
        )
        with self.assertNoLogs(_RENDERER_LOGGER, "ERROR"):
            self.assertEqual(self.renderer.get_page_info(missing), empty_info)
            self.assertEqual(self.renderer.get_page_count(missing), 1)
            self.assertEqual(self.renderer.extract_text_runs(missing), [])
        with self.assertLogs(_RENDERER_LOGGER, "WARNING") as captured:
            self.assertIsNone(self.renderer.render(missing, 0, 1.0, 0))
        self.assertEqual(
            captured.output,
            [f"WARNING:{_RENDERER_LOGGER}:File not found: {missing}"],
        )
        # Neither an absent path nor a non-PDF source may even try to open PDFium.
        with self.assertNoLogs(_RENDERER_LOGGER, "ERROR"):
            self.assertIsNone(self.renderer.render("", 0, 1.0, 0))
            self.assertIsNone(self.renderer.render_frame("", 0, 1.0, 0, 0, 10, 10, 0))
            self.assertIsNone(
                self.renderer.render_frame(missing, 0, 1.0, 0, 0, 10, 10, 0)
            )
            self.assertIsNone(
                self.renderer.render_frame(str(self.tiff), 0, 1.0, 0, 0, 10, 10, 0)
            )

    def test_an_unreadable_pdf_degrades_every_lookup_and_logs_why(self):
        path = str(self.garbage_pdf)
        empty_info = {
            "pdf_width": 0.0,
            "pdf_height": 0.0,
            "media_width_pts": 0.0,
            "media_height_pts": 0.0,
            "crop_width_pts": 0.0,
            "crop_height_pts": 0.0,
            "intrinsic_rotation": 0,
        }
        with self.assertLogs(_RENDERER_LOGGER, "ERROR") as captured:
            self.assertEqual(self.renderer.get_page_count(path), 1)
            self.assertEqual(self.renderer.get_page_size(path), (0.0, 0.0))
            self.assertEqual(self.renderer.get_page_info(path), empty_info)
            self.assertEqual(self.renderer.extract_text_runs(path), [])
            self.assertIsNone(self.renderer.render(path, 0, 1.0, 0))
            self.assertIsNone(self.renderer.render_frame(path, 0, 1.0, 0, 0, 10, 10, 0))
        self.assertEqual(len(captured.records), 6)
        for record in captured.records:
            self.assertRegex(
                record.getMessage(),
                r"^Failed to open PDF \(.*size=9\): .*garbage\.pdf$",
            )

    def test_open_failures_distinguish_missing_file_directory_and_bad_content(self):
        class RefusingPdf:
            def open(self, _path):
                return False

            def close(self):
                pass

            def get_last_error(self):
                return "pdfium says no"

        renderer = PageRenderer()
        renderer._get_pdf_renderer = lambda: RefusingPdf()
        folder = self.dir / "folder.pdf"
        folder.mkdir()
        cases = (
            (str(self.dir / "gone.pdf"), "Failed to open PDF (file not found): "),
            (str(folder), "Failed to open PDF (not a file): "),
            (
                str(self.garbage_pdf),
                "Failed to open PDF (pdfium says no, size=9): ",
            ),
        )
        for path, prefix in cases:
            with self.subTest(path=path):
                with self.assertLogs(_RENDERER_LOGGER, "ERROR") as captured:
                    self.assertIsNone(renderer._ensure_pdf_open_locked(path))
                self.assertEqual(
                    [r.getMessage() for r in captured.records], [prefix + path]
                )

    def test_rendering_without_a_native_renderer_is_reported_not_raised(self):
        renderer = PageRenderer()
        renderer._get_pdf_renderer = lambda: None
        with self.assertLogs(_RENDERER_LOGGER, "ERROR") as captured:
            self.assertIsNone(renderer._ensure_pdf_open_locked(self.three_pages))
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["PDF rendering not available"],
        )

    def test_a_cancelled_native_render_returns_nothing_without_an_error(self):
        from ost_visualizer.presentation.visualization.pdf import ost_pdf

        live = ost_pdf.RenderCancelToken()
        image = self.renderer.render(self.three_pages, 1, 1.0, 0, live)
        self.assertEqual((image.width(), image.height()), (200, 50))
        frame = self.renderer.render_frame(
            self.three_pages, 1, 1.0, 0.0, 0.0, 100.0, 50.0, 0, live
        )
        self.assertEqual((frame.width(), frame.height()), (100, 50))
        cancelled = ost_pdf.RenderCancelToken()
        cancelled.cancel()
        with self.assertNoLogs(_RENDERER_LOGGER, "ERROR"):
            self.assertIsNone(
                self.renderer.render(self.three_pages, 1, 1.0, 0, cancelled)
            )
            self.assertIsNone(
                self.renderer.render_frame(
                    self.three_pages, 1, 1.0, 0.0, 0.0, 100.0, 50.0, 0, cancelled
                )
            )

    def test_a_failed_native_render_without_cancellation_is_logged(self):
        from ost_visualizer.presentation.visualization.pdf import ost_pdf

        for token in (None, ost_pdf.RenderCancelToken()):
            with self.subTest(token=token):
                with self.assertLogs(_RENDERER_LOGGER, "ERROR") as captured:
                    self.assertIsNone(
                        self.renderer.render(self.three_pages, 1, 0.0, 0, token)
                    )
                self.assertEqual(
                    [record.getMessage() for record in captured.records],
                    ["Failed to render PDF page 1"],
                )

    def test_raster_loading_lifts_the_image_allocation_limit(self):
        from PySide6.QtGui import QImageReader

        previous_limit = QImageReader.allocationLimit()
        self.addCleanup(QImageReader.setAllocationLimit, previous_limit)
        QImageReader.setAllocationLimit(128)
        self.assertIsNotNone(self.renderer.render(str(self.tiff), 0, 1.0, 0))
        self.assertEqual(QImageReader.allocationLimit(), 0)

    def test_an_unreadable_raster_is_logged_and_not_rendered(self):
        with self.assertLogs(_RENDERER_LOGGER, "ERROR") as captured:
            self.assertIsNone(self.renderer.render(str(self.garbage_tiff), 0, 1.0, 0))
        self.assertRegex(
            captured.records[0].getMessage(),
            r"^Failed to load image: .*garbage\.tif - ",
        )

    def test_unsupported_file_types_are_refused_with_a_warning(self):
        path = self.dir / "notes.txt"
        path.write_text("x")
        with self.assertLogs(_RENDERER_LOGGER, "WARNING") as captured:
            self.assertIsNone(self.renderer.render(str(path), 0, 1.0, 0))
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Unsupported file type: .txt"],
        )

    def test_close_releases_the_native_document_and_forgets_it(self):
        events = []

        class FakePdf:
            def open(self, _path):
                return True

            def close(self):
                events.append("close")

            def get_last_error(self):
                return ""

        renderer = PageRenderer()
        renderer._pdf_renderer = FakePdf()
        renderer._current_pdf_path = "x.pdf"
        renderer._current_pdf_signature = (1, 2)
        renderer.close()
        self.assertEqual(events, ["close"])
        self.assertIsNone(renderer._pdf_renderer)
        self.assertIsNone(renderer._current_pdf_path)
        self.assertIsNone(renderer._current_pdf_signature)
        renderer.close()
        self.assertEqual(events, ["close"])
