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


class ScriptedRenderer:
    instances = []
    page_total = 3
    fail_in = None

    def __init__(self):
        self.closed = 0
        self.page_info_requests = []
        self.text_requests = []
        self.segment_requests = []
        ScriptedRenderer.instances.append(self)

    def open(self, _file_path):
        return True

    def close(self):
        self.closed += 1

    def page_count(self):
        return ScriptedRenderer.page_total

    def _maybe_fail(self, name):
        if ScriptedRenderer.fail_in == name:
            raise RuntimeError(name)

    def page_info(self, page_index):
        self.page_info_requests.append(page_index)
        self._maybe_fail("page_info")
        return SimpleNamespace(
            effective_width_pts=100.0 + page_index,
            effective_height_pts=200.0,
            media_width_pts=100.0,
            media_height_pts=200.0,
            crop_width_pts=100.0,
            crop_height_pts=200.0,
            intrinsic_rotation=0,
        )

    def extract_text_runs(self, page_index):
        self.text_requests.append(page_index)
        self._maybe_fail("text")
        return [
            SimpleNamespace(
                text=f"page {page_index}", left=1.0, top=2.0, right=3.0, bottom=4.0
            ),
            SimpleNamespace(text=None, left=5.0, top=6.0, right=7.0, bottom=8.0),
        ]

    def extract_path_segments(self, page_index):
        self.segment_requests.append(page_index)
        self._maybe_fail("segments")
        return [(1.0, 2.0, 3.0 + page_index, 4.0)]


class PdfMetadataProviderBehaviourTests(unittest.TestCase):
    def setUp(self):
        ScriptedRenderer.instances = []
        ScriptedRenderer.page_total = 3
        ScriptedRenderer.fail_in = None
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = directory.name
        self.pdf = os.path.join(self.directory, "plan.pdf")
        with open(self.pdf, "wb") as handle:
            handle.write(b"%PDF-1.4")
        self.provider = self.fresh_provider()

    @staticmethod
    def fresh_provider():
        ScriptedRenderer.instances = []
        return NativePdfMetadataProvider(
            logger=logging.getLogger("tests.pdf_metadata_behaviour"),
            renderer_factory=ScriptedRenderer,
            geometry_reader_factory=lambda: SimpleNamespace(
                get_page_geometries=lambda _path: []
            ),
        )

    @staticmethod
    def readers(provider):
        return {
            "page info": (provider.get_page_info, "page_info_requests"),
            "text runs": (provider.get_text_runs, "text_requests"),
            "vector segments": (provider.get_vector_segments, "segment_requests"),
        }

    def test_page_indexes_are_clamped_to_the_pages_the_document_has(self):
        cases = ((-5, 0), (0, 0), (2, 2), (3, 2), (99, 2), (None, 0))
        for label in self.readers(self.provider):
            for requested, expected in cases:
                with self.subTest(read=label, requested=requested):
                    provider = self.fresh_provider()
                    read, requests = self.readers(provider)[label]
                    read(self.pdf, requested)
                    self.assertEqual(
                        getattr(ScriptedRenderer.instances[-1], requests), [expected]
                    )

    def test_a_document_without_pages_is_read_at_index_zero(self):
        ScriptedRenderer.page_total = 0
        self.provider.get_page_info(self.pdf, 5)
        self.assertEqual(ScriptedRenderer.instances[-1].page_info_requests, [0])

    def test_different_pages_of_one_file_are_cached_separately(self):
        first = self.provider.get_page_info(self.pdf, 0)
        second = self.provider.get_page_info(self.pdf, 1)
        self.assertIsNot(first, second)
        self.assertEqual(
            (first.effective_width_pts, second.effective_width_pts), (100.0, 101.0)
        )
        self.assertIs(self.provider.get_page_info(self.pdf, 0), first)
        self.assertEqual(len(ScriptedRenderer.instances), 2)
        runs = [self.provider.get_text_runs(self.pdf, index) for index in (0, 1)]
        self.assertEqual([run[0].text for run in runs], ["page 0", "page 1"])
        segments = [
            self.provider.get_vector_segments(self.pdf, index) for index in (0, 1)
        ]
        self.assertEqual([item[0].x2 for item in segments], [3.0, 4.0])

    def test_cache_hits_return_independent_copies_of_runs_and_segments(self):
        for read in (self.provider.get_text_runs, self.provider.get_vector_segments):
            first = read(self.pdf, 0)
            expected = list(first)
            first.clear()
            again = read(self.pdf, 0)
            self.assertEqual(again, expected)
            self.assertIsNot(again, first)
        self.assertEqual(len(ScriptedRenderer.instances), 2)

    def test_text_runs_keep_their_text_and_a_missing_text_is_empty(self):
        runs = self.provider.get_text_runs(self.pdf, 0)
        self.assertEqual([run.text for run in runs], ["page 0", ""])
        self.assertEqual(
            (runs[0].left, runs[0].top, runs[0].right, runs[0].bottom),
            (1.0, 2.0, 3.0, 4.0),
        )

    def test_the_native_document_is_closed_after_every_read(self):
        for label in self.readers(self.provider):
            with self.subTest(read=label):
                provider = self.fresh_provider()
                self.readers(provider)[label][0](self.pdf, 0)
                self.assertEqual(
                    [item.closed for item in ScriptedRenderer.instances], [1]
                )

    def test_the_native_document_is_closed_when_a_read_fails(self):
        failing = {
            "page info": "page_info",
            "text runs": "text",
            "vector segments": "segments",
        }
        for label, name in failing.items():
            with self.subTest(read=label):
                provider = self.fresh_provider()
                ScriptedRenderer.fail_in = name
                with self.assertLogs("tests.pdf_metadata_behaviour", level="WARNING"):
                    self.readers(provider)[label][0](self.pdf, 0)
                self.assertEqual(
                    [item.closed for item in ScriptedRenderer.instances], [1]
                )

    def test_only_existing_pdf_files_open_the_renderer(self):
        notes = os.path.join(self.directory, "notes.txt")
        with open(notes, "wb") as handle:
            handle.write(b"text")
        folder = os.path.join(self.directory, "folder.pdf")
        os.mkdir(folder)
        cases = {
            "no path": ("", "not_configured"),
            "not a pdf": (notes, "not_pdf"),
            "directory named like a pdf": (folder, "missing"),
            "missing file": (os.path.join(self.directory, "gone.pdf"), "missing"),
        }
        for label, (path, status) in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self.provider.get_page_info(path, 0).status, status)
                self.assertEqual(self.provider.get_text_runs(path, 0), [])
                self.assertEqual(self.provider.get_vector_segments(path, 0), [])
        self.assertEqual(ScriptedRenderer.instances, [])


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
