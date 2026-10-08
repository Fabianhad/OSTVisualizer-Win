import logging
import os
import tempfile
import unittest
from types import SimpleNamespace
from ost_visualizer.infrastructure.pdf_metadata_provider import (
    NativePdfMetadataProvider,
)


class FailingRenderer:
    def open(self, file_path):
        raise RuntimeError(f"{file_path} failed")

    def close(self):
        raise AssertionError("close should not be called when open fails")


class RecordingRenderer:
    page_info_calls = []
    text_run_calls = []
    vector_calls = []

    def open(self, _file_path):
        return True

    def close(self):
        pass

    def page_count(self):
        return 3

    def page_info(self, page_index):
        self.page_info_calls.append(page_index)
        return SimpleNamespace(
            effective_width_pts=100.0 + len(self.page_info_calls),
            effective_height_pts=200.0,
            media_width_pts=100.0,
            media_height_pts=200.0,
            crop_width_pts=100.0,
            crop_height_pts=200.0,
            intrinsic_rotation=0,
        )

    def extract_text_runs(self, page_index):
        self.text_run_calls.append(page_index)
        return []

    def extract_path_segments(self, page_index):
        self.vector_calls.append(page_index)
        return []


class PdfMetadataProviderTests(unittest.TestCase):
    def setUp(self):
        RecordingRenderer.page_info_calls = []
        RecordingRenderer.text_run_calls = []
        RecordingRenderer.vector_calls = []

    def test_pdf_failure_logs_do_not_include_source_path(self):
        logger = logging.getLogger("tests.pdf_metadata_provider")
        provider = NativePdfMetadataProvider(
            logger=logger,
            renderer_factory=FailingRenderer,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            readers = (
                ("page info", provider.get_page_info),
                ("text runs", provider.get_text_runs),
                ("vector segments", provider.get_vector_segments),
            )
            for label, read in readers:
                with self.subTest(read=label):
                    with self.assertLogs(logger, level="WARNING") as captured:
                        result = read(pdf_file.name, 0)
                    if label == "page info":
                        self.assertEqual(result.status, "unavailable")
                    else:
                        self.assertEqual(result, [])
                    self.assertEqual(len(captured.records), 1)
                    output = "\n".join(captured.output)
                    self.assertIn("RuntimeError", output)
                    self.assertNotIn(pdf_file.name, output)
                    self.assertNotIn(os.path.basename(pdf_file.name), output)
                    self.assertNotIn("failed", captured.records[0].getMessage())

    def test_pdf_metadata_cache_key_includes_file_signature(self):
        provider = NativePdfMetadataProvider(renderer_factory=RecordingRenderer)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
            pdf_file.write(b"first")
            path = pdf_file.name
        try:
            first = provider.get_page_info(path, 0)
            first_again = provider.get_page_info(path, 0)
            negative_index = provider.get_page_info(path, -1)
            with open(path, "wb") as handle:
                handle.write(b"second-version")
            os.utime(path, None)
            second = provider.get_page_info(path, 0)
        finally:
            os.unlink(path)
        self.assertIs(first, first_again)
        self.assertIs(first, negative_index)
        self.assertNotEqual(first.effective_width_pts, second.effective_width_pts)
        self.assertEqual(RecordingRenderer.page_info_calls, [0, 0])

    def test_pdf_metadata_cache_key_includes_modification_time(self):
        provider = NativePdfMetadataProvider(renderer_factory=RecordingRenderer)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
            pdf_file.write(b"same-size")
            path = pdf_file.name
        try:
            first = provider.get_page_info(path, 0)
            original_mtime_ns = os.stat(path).st_mtime_ns
            os.utime(path, ns=(original_mtime_ns, original_mtime_ns + 2_000_000_000))
            second = provider.get_page_info(path, 0)
        finally:
            os.unlink(path)
        self.assertIsNot(first, second)
        self.assertEqual(first.effective_width_pts, 101.0)
        self.assertEqual(second.effective_width_pts, 102.0)
        self.assertEqual(RecordingRenderer.page_info_calls, [0, 0])

    def test_pdf_metadata_caches_are_bounded_lru(self):
        provider = NativePdfMetadataProvider(renderer_factory=RecordingRenderer)
        provider.MAX_CACHE_ENTRIES = 2
        provider.get_page_info("a.pdf", 0)
        provider.get_page_info("b.pdf", 0)
        provider.get_page_info("a.pdf", 0)
        provider.get_page_info("c.pdf", 0)
        self.assertEqual(
            [key[0] for key in provider._page_info_cache.keys()],
            ["a.pdf", "c.pdf"],
        )
        provider.get_text_runs("a.pdf", 0)
        provider.get_text_runs("b.pdf", 0)
        provider.get_text_runs("a.pdf", 0)
        provider.get_text_runs("c.pdf", 0)
        self.assertEqual(
            [key[0] for key in provider._text_runs_cache.keys()],
            ["a.pdf", "c.pdf"],
        )
        provider.get_vector_segments("a.pdf", 0)
        provider.get_vector_segments("b.pdf", 0)
        provider.get_vector_segments("a.pdf", 0)
        provider.get_vector_segments("c.pdf", 0)
        self.assertEqual(
            [key[0] for key in provider._segments_cache.keys()],
            ["a.pdf", "c.pdf"],
        )

    def test_pdf_metadata_lru_evicts_least_recently_used_file_and_rereads_it(self):
        provider = NativePdfMetadataProvider(renderer_factory=RecordingRenderer)
        provider.MAX_CACHE_ENTRIES = 2
        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for name in ("a.pdf", "b.pdf", "c.pdf"):
                path = os.path.join(directory, name)
                with open(path, "wb") as handle:
                    handle.write(name.encode())
                paths.append(path)
            path_a, path_b, path_c = paths
            info_a = provider.get_page_info(path_a, 0)
            provider.get_page_info(path_b, 0)
            self.assertIs(provider.get_page_info(path_a, 0), info_a)
            provider.get_page_info(path_c, 0)
            self.assertEqual(len(RecordingRenderer.page_info_calls), 3)
            self.assertIs(provider.get_page_info(path_a, 0), info_a)
            self.assertEqual(len(RecordingRenderer.page_info_calls), 3)
            provider.get_page_info(path_b, 0)
            self.assertEqual(len(RecordingRenderer.page_info_calls), 4)
            self.assertEqual(
                [key[0] for key in provider._page_info_cache.keys()],
                [path_a, path_b],
            )


class PdfMetadataVisibleBoxOriginTests(unittest.TestCase):
    CASES = {
        "crop box offset": (
            "/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
            (100, 200, 300, 200),
            (412.0, 592.0),
        ),
        "media box origin": (
            "/MediaBox [50 50 662 842]",
            (150, 250, 350, 250),
            (612.0, 792.0),
        ),
        "asymmetric crop box": (
            "/MediaBox [0 0 612 792] /CropBox [120 40 520 640]",
            (80, 260, 280, 260),
            (400.0, 600.0),
        ),
        "rotated crop box": (
            "/MediaBox [0 0 612 792] /CropBox [100 100 512 692] /Rotate 90",
            (100, 200, 300, 200),
            (412.0, 592.0),
        ),
    }

    def test_text_and_segments_are_relative_to_the_visible_box_origin(self):
        from pathlib import Path
        from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

        with tempfile.TemporaryDirectory() as directory:
            for label, (boxes, expected_segment, crop_size) in self.CASES.items():
                with self.subTest(label=label):
                    pdf = write_takeoff_pdf(
                        Path(directory) / f"{label}.pdf",
                        lines=[(200, 300, 400, 300)],
                        texts=[(150, 500, 12, "GRID")],
                        page_boxes=boxes,
                    )
                    provider = NativePdfMetadataProvider()
                    info = provider.get_page_info(str(pdf), 0)
                    self.assertEqual(
                        (info.crop_width_pts, info.crop_height_pts), crop_size
                    )
                    segments = provider.get_vector_segments(str(pdf), 0)
                    self.assertEqual(
                        [
                            tuple(round(v) for v in (s.x1, s.y1, s.x2, s.y2))
                            for s in segments
                        ],
                        [expected_segment],
                    )
                    run = provider.get_text_runs(str(pdf), 0)[0]
                    self.assertAlmostEqual(
                        run.left, expected_segment[0] - 50.0, delta=2.0
                    )
                    self.assertAlmostEqual(
                        run.bottom, expected_segment[1] + 200.0, delta=4.0
                    )
                    self.assertTrue(0.0 <= run.left < run.right <= crop_size[0])
                    self.assertTrue(0.0 <= run.bottom < run.top <= crop_size[1])
                    self.assertTrue(run.top - run.bottom < 20.0)
                    self.assertTrue(run.right - run.left < 60.0)


class UnreadableGeometryReader:
    def get_page_geometries(self, file_path):
        raise OSError(f"{file_path} could not be parsed")


class EmptyGeometryReader:
    def get_page_geometries(self, _file_path):
        return []


class PdfMetadataUnknownOriginTests(unittest.TestCase):
    def write_cropped_pdf(self, directory):
        from pathlib import Path
        from tests.presentation.services.ai_takeoff_pdf_support import write_takeoff_pdf

        return str(
            write_takeoff_pdf(
                Path(directory) / "cropped.pdf",
                lines=[(200, 300, 400, 300)],
                texts=[(150, 500, 12, "GRID")],
                page_boxes="/MediaBox [0 0 612 792] /CropBox [100 100 512 692]",
            )
        )

    def assert_page_coordinates_are_unshifted(self, provider, pdf):
        segments = provider.get_vector_segments(pdf, 0)
        self.assertEqual(
            [tuple(round(v) for v in (s.x1, s.y1, s.x2, s.y2)) for s in segments],
            [(200, 300, 400, 300)],
        )
        (run,) = provider.get_text_runs(pdf, 0)
        self.assertAlmostEqual(run.left, 150.0, delta=2.0)
        self.assertAlmostEqual(run.bottom, 500.0, delta=4.0)

    def test_an_unreadable_page_geometry_is_logged_without_the_path(self):
        logger = logging.getLogger("tests.pdf_metadata_provider.geometry")
        provider = NativePdfMetadataProvider(
            logger=logger, geometry_reader_factory=UnreadableGeometryReader
        )
        with tempfile.TemporaryDirectory() as directory:
            pdf = self.write_cropped_pdf(directory)
            with self.assertLogs(logger, level="WARNING") as captured:
                self.assert_page_coordinates_are_unshifted(provider, pdf)
        self.assertEqual(
            [record.getMessage() for record in captured.records],
            ["Failed to read PDF page geometry: OSError"] * 2,
        )

    def test_a_page_missing_from_the_geometry_keeps_page_coordinates(self):
        logger = logging.getLogger("tests.pdf_metadata_provider.geometry")
        provider = NativePdfMetadataProvider(
            logger=logger, geometry_reader_factory=EmptyGeometryReader
        )
        with tempfile.TemporaryDirectory() as directory:
            pdf = self.write_cropped_pdf(directory)
            with self.assertNoLogs(logger, level="WARNING"):
                self.assert_page_coordinates_are_unshifted(provider, pdf)


if __name__ == "__main__":
    unittest.main()
