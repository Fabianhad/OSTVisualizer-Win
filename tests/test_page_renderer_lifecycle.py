import unittest
from unittest.mock import patch
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


if __name__ == "__main__":
    unittest.main()
