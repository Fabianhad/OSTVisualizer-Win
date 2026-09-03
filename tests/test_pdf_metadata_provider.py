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
            with self.assertLogs(logger, level="WARNING") as captured:
                result = provider.get_page_info(pdf_file.name, 0)
        self.assertEqual(result.status, "unavailable")
        output = "\n".join(captured.output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn(pdf_file.name, output)
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
if __name__ == "__main__":
    unittest.main()
