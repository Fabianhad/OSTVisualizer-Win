import unittest
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache


class _FakeRenderer:
    def __init__(self):
        self.page_info_calls = []
        self.page_count_calls = []
        self.page_size_calls = []
        self.text_run_calls = []

    def get_page_info(self, file_path, page_index):
        self.page_info_calls.append((file_path, page_index))
        return {"file_path": file_path, "page_index": page_index}

    def get_page_count(self, file_path):
        self.page_count_calls.append(file_path)
        return len(self.page_count_calls)

    def get_page_size(self, file_path, page_index):
        self.page_size_calls.append((file_path, page_index))
        return (page_index, page_index + 1)

    def extract_text_runs(self, file_path, page_index):
        self.text_run_calls.append((file_path, page_index))
        return [{"file_path": file_path, "page_index": page_index}]


class PageCacheLifecycleTests(unittest.TestCase):
    def test_pdf_metadata_caches_are_bounded_lru(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache.MAX_METADATA_ENTRIES = 2
        cache._get_renderer = lambda: renderer
        cache.get_page_info("a.pdf", 0)
        cache.get_page_info("b.pdf", 0)
        cache.get_page_info("a.pdf", 0)
        cache.get_page_info("c.pdf", 0)
        self.assertEqual(list(cache._page_info_cache.keys()), ["a.pdf:0", "c.pdf:0"])
        cache.get_page_info("b.pdf", 0)
        self.assertEqual(
            renderer.page_info_calls,
            [("a.pdf", 0), ("b.pdf", 0), ("c.pdf", 0), ("b.pdf", 0)],
        )
        cache.get_text_runs("a.pdf", 0)
        cache.get_text_runs("b.pdf", 0)
        cache.get_text_runs("a.pdf", 0)
        cache.get_text_runs("c.pdf", 0)
        self.assertEqual(list(cache._text_runs_cache.keys()), ["a.pdf:0", "c.pdf:0"])
        cache.get_text_runs("b.pdf", 0)
        self.assertEqual(
            renderer.text_run_calls,
            [("a.pdf", 0), ("b.pdf", 0), ("c.pdf", 0), ("b.pdf", 0)],
        )
        cache.get_page_count("a.pdf")
        cache.get_page_count("b.pdf")
        cache.get_page_count("a.pdf")
        cache.get_page_count("c.pdf")
        self.assertEqual(list(cache._page_count_cache.keys()), ["a.pdf", "c.pdf"])
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("b.pdf", 0)
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("c.pdf", 0)
        self.assertEqual(list(cache._page_size_cache.keys()), ["a.pdf:0", "c.pdf:0"])


if __name__ == "__main__":
    unittest.main()
