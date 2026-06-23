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
    def test_cacheable_base_scale_keeps_heavy_pdf_under_cache_budget(self):
        scale = PageCache.cacheable_base_render_scale(3024.0, 2160.0, 2.0)
        self.assertLess(scale, 2.0)
        self.assertLessEqual(
            PageCache.estimated_render_bytes(3024.0, 2160.0, scale),
            PageCache.PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES,
        )
        self.assertLessEqual(
            int(3024.0 * scale + 0.999999) * int(2160.0 * scale + 0.999999),
            PageCache.BASE_RASTER_MAX_PIXELS,
        )

    def test_cacheable_base_scale_preserves_small_pdf_scale(self):
        self.assertEqual(
            PageCache.cacheable_base_render_scale(612.0, 792.0, 2.0),
            2.0,
        )

    def test_pdf_metadata_caches_are_bounded_lru(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache.MAX_METADATA_ENTRIES = 2
        cache._get_renderer = lambda: renderer
        cache.get_page_info("a.pdf", 0)
        cache.get_page_info("b.pdf", 0)
        cache.get_page_info("a.pdf", 0)
        cache.get_page_info("c.pdf", 0)
        self.assertEqual(
            list(cache._page_info_cache.keys()),
            [("a.pdf", None, 0), ("c.pdf", None, 0)],
        )
        cache.get_page_info("b.pdf", 0)
        self.assertEqual(
            renderer.page_info_calls,
            [("a.pdf", 0), ("b.pdf", 0), ("c.pdf", 0), ("b.pdf", 0)],
        )
        cache.get_text_runs("a.pdf", 0)
        cache.get_text_runs("b.pdf", 0)
        cache.get_text_runs("a.pdf", 0)
        cache.get_text_runs("c.pdf", 0)
        self.assertEqual(
            list(cache._text_runs_cache.keys()),
            [("a.pdf", None, 0), ("c.pdf", None, 0)],
        )
        cache.get_text_runs("b.pdf", 0)
        self.assertEqual(
            renderer.text_run_calls,
            [("a.pdf", 0), ("b.pdf", 0), ("c.pdf", 0), ("b.pdf", 0)],
        )
        cache.get_page_count("a.pdf")
        cache.get_page_count("b.pdf")
        cache.get_page_count("a.pdf")
        cache.get_page_count("c.pdf")
        self.assertEqual(
            list(cache._page_count_cache.keys()),
            [("a.pdf", None), ("c.pdf", None)],
        )
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("b.pdf", 0)
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("c.pdf", 0)
        self.assertEqual(
            list(cache._page_size_cache.keys()),
            [("a.pdf", None, 0), ("c.pdf", None, 0)],
        )


if __name__ == "__main__":
    unittest.main()
