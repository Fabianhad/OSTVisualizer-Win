import tempfile
import threading
import unittest
from PySide6.QtGui import QImage
from ost_visualizer.application.render_quality import (
    CONSTRAINED_RENDER_SCALE_FLOOR,
    INTERACTIVE_PDF_RENDER_SCALE,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import (
    PageCache,
    scoped_pdf_render_cancellation_token,
)


class _FakeRenderer:
    def __init__(self):
        self.page_info_calls = []
        self.page_count_calls = []
        self.page_size_calls = []
        self.text_run_calls = []
        self.frame_calls = []

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

    def render_frame(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
        native_cancel_token=None,
    ):
        self.frame_calls.append(
            (
                file_path,
                page_index,
                scale,
                frame_x_pts,
                frame_y_pts,
                frame_w_pts,
                frame_h_pts,
                rotation,
                native_cancel_token,
            )
        )
        return QImage(16, 16, QImage.Format.Format_ARGB32)


class _BlockingPageRenderer:
    def __init__(self):
        self.calls = []
        self.first_render_started = threading.Event()
        self.release_first_render = threading.Event()

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.calls.append((file_path, page_index, scale, rotation, native_cancel_token))
        if len(self.calls) == 1:
            self.first_render_started.set()
            self.release_first_render.wait(timeout=2.0)
        return QImage(16, 16, QImage.Format.Format_ARGB32)


class _RecordingPageRenderer:
    def __init__(self, page_count=3):
        self.page_count = page_count
        self.render_calls = []

    def get_page_count(self, file_path):
        return self.page_count

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.render_calls.append((file_path, page_index, scale, rotation))
        return QImage(16, 16, QImage.Format.Format_ARGB32)


class _RecordingCancelToken:
    def __init__(self, cancelled=False):
        self._cancelled = cancelled

    def is_cancelled(self):
        return self._cancelled


class _TokenAwareRenderer:
    def __init__(self):
        self.page_tokens = []
        self.frame_tokens = []

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.page_tokens.append(native_cancel_token)
        if native_cancel_token and native_cancel_token.is_cancelled():
            return None
        return QImage(16, 16, QImage.Format.Format_ARGB32)

    def render_frame(
        self,
        file_path,
        page_index,
        scale,
        frame_x_pts,
        frame_y_pts,
        frame_w_pts,
        frame_h_pts,
        rotation,
        native_cancel_token=None,
    ):
        self.frame_tokens.append(native_cancel_token)
        if native_cancel_token and native_cancel_token.is_cancelled():
            return None
        return QImage(16, 16, QImage.Format.Format_ARGB32)


class _ClosableRenderer:
    def __init__(self, error=None):
        self.error = error
        self.closed = False

    def close(self):
        self.closed = True
        if self.error is not None:
            raise self.error


class PageCacheLifecycleTests(unittest.TestCase):
    def test_cacheable_base_scale_keeps_heavy_pdf_under_cache_budget(self):
        scale = PageCache.cacheable_base_render_scale(
            3024.0,
            2160.0,
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertLess(scale, INTERACTIVE_PDF_RENDER_SCALE)
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
            PageCache.cacheable_base_render_scale(
                612.0,
                792.0,
                INTERACTIVE_PDF_RENDER_SCALE,
            ),
            INTERACTIVE_PDF_RENDER_SCALE,
        )

    def test_cache_constraints_can_reach_floor_without_changing_baseline(self):
        scale = PageCache.cacheable_base_render_scale(
            1_000_000.0,
            1_000_000.0,
            INTERACTIVE_PDF_RENDER_SCALE,
        )
        self.assertEqual(scale, CONSTRAINED_RENDER_SCALE_FLOOR)
        self.assertEqual(INTERACTIVE_PDF_RENDER_SCALE, 3.0)

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
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("b.pdf", 0)
        cache.get_page_size("a.pdf", 0)
        cache.get_page_size("c.pdf", 0)
        self.assertEqual(
            list(cache._page_size_cache.keys()),
            [("a.pdf", None, 0), ("c.pdf", None, 0)],
        )

    def test_large_plan_sheet_cache_retains_target_entry_count(self):
        renderer = _RecordingPageRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        cache._image_size_bytes = (
            lambda _image: PageCache.REPRESENTATIVE_PLAN_SHEET_BYTES
        )
        for index in range(PageCache.MAX_ENTRIES):
            cache.get_page(f"page-{index}.pdf", 0, 2.0, 0)
        self.assertEqual(len(cache._cache), PageCache.MAX_ENTRIES)
        self.assertEqual(
            cache._cache_size_bytes(cache._cache),
            PageCache.MAX_ENTRIES * PageCache.REPRESENTATIVE_PLAN_SHEET_BYTES,
        )
        cache.get_page("page-overflow.pdf", 0, 2.0, 0)
        self.assertEqual(len(cache._cache), PageCache.MAX_ENTRIES)
        self.assertNotIn("page-0.pdf", {key.file_path for key in cache._cache})

    def test_prefetch_pressure_accounts_for_frame_and_tinted_caches(self):
        cache = PageCache()
        cache._image_size_bytes = lambda value: int(value)
        cache._frame_cache["frame"] = 10**12
        cache._tinted_cache["tinted"] = 10**12
        self.assertFalse(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))

    def test_invalid_pdf_page_index_is_normalized_before_cache_key(self):
        renderer = _RecordingPageRenderer(page_count=3)
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf_file:
            first = cache.get_page(pdf_file.name, 99, 1.0, 0)
            second = cache.get_page(pdf_file.name, 2, 1.0, 0)
            third = cache.get_page(pdf_file.name, -5, 1.0, 0)
            fourth = cache.get_page(pdf_file.name, 0, 1.0, 0)
        self.assertIs(first, second)
        self.assertIs(third, fourth)
        self.assertEqual(
            renderer.render_calls,
            [
                (pdf_file.name, 2, 1.0, 0),
                (pdf_file.name, 0, 1.0, 0),
            ],
        )
        self.assertEqual({key.page_index for key in cache._cache}, {0, 2})

    def test_visible_frame_render_is_cached_by_frame_key(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        first = cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        second = cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        self.assertIs(first, second)
        self.assertEqual(len(renderer.frame_calls), 1)

    def test_visible_frame_cache_separates_scale_rotation_rect_and_signature(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        signatures = [None]
        cache._get_renderer = lambda: renderer
        cache._file_signature = lambda _path: signatures[0]
        cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        cache.get_frame("page.pdf", 0, 3.0, 10.0, 20.0, 30.0, 40.0, 0)
        cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 90)
        cache.get_frame("page.pdf", 0, 2.0, 11.0, 20.0, 30.0, 40.0, 0)
        signatures[0] = (123, 456)
        cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        self.assertEqual(len(renderer.frame_calls), 5)

    def test_visible_frame_cache_rejects_images_over_single_image_budget(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        cache._image_size_bytes = lambda _image: 10**12
        cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0)
        self.assertEqual(len(renderer.frame_calls), 2)

    def test_required_page_render_can_bypass_in_flight_prefetch_key(self):
        renderer = _BlockingPageRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        results = []
        prefetch_thread = threading.Thread(
            target=lambda: results.append(cache.get_page("page.pdf", 0, 1.75, 0)),
            daemon=True,
        )
        prefetch_thread.start()
        self.assertTrue(renderer.first_render_started.wait(timeout=1.0))
        current_image = cache.get_page(
            "page.pdf",
            0,
            1.75,
            0,
            wait_for_in_flight=False,
        )
        self.assertIsNotNone(current_image)
        self.assertEqual(
            renderer.calls,
            [
                ("page.pdf", 0, 1.75, 0, None),
                ("page.pdf", 0, 1.75, 0, None),
            ],
        )
        renderer.release_first_render.set()
        prefetch_thread.join(timeout=1.0)
        self.assertEqual(len(results), 1)

    def test_prefetch_cache_lookup_waits_for_same_in_flight_key(self):
        renderer = _BlockingPageRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        first_results = []
        second_results = []
        first_thread = threading.Thread(
            target=lambda: first_results.append(cache.get_page("page.pdf", 0, 1.75, 0)),
            daemon=True,
        )
        second_thread = threading.Thread(
            target=lambda: second_results.append(
                cache.get_page("page.pdf", 0, 1.75, 0)
            ),
            daemon=True,
        )
        first_thread.start()
        self.assertTrue(renderer.first_render_started.wait(timeout=1.0))
        second_thread.start()
        second_thread.join(timeout=0.05)
        self.assertEqual(len(second_results), 0)
        self.assertEqual(renderer.calls, [("page.pdf", 0, 1.75, 0, None)])
        renderer.release_first_render.set()
        first_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)
        self.assertEqual(len(first_results), 1)
        self.assertEqual(len(second_results), 1)

    def test_render_cancellation_token_reaches_page_and_frame_renderer(self):
        renderer = _TokenAwareRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        token = _RecordingCancelToken()
        with scoped_pdf_render_cancellation_token(token):
            cache.get_page("page.pdf", 0, 1.0, 0)
            cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0)
        self.assertEqual(renderer.page_tokens, [token])
        self.assertEqual(renderer.frame_tokens, [token])

    def test_cancelled_page_and_frame_renders_are_not_cached(self):
        renderer = _TokenAwareRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        token = _RecordingCancelToken(cancelled=True)
        with scoped_pdf_render_cancellation_token(token):
            page = cache.get_page("page.pdf", 0, 1.0, 0)
            frame = cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0)
        self.assertIsNone(page)
        self.assertIsNone(frame)
        self.assertEqual(cache._cache, {})
        self.assertEqual(cache._frame_cache, {})

    def test_clear_releases_every_renderer_when_one_close_fails(self):
        expected_error = RuntimeError("native close failed")
        failing_renderer = _ClosableRenderer(expected_error)
        remaining_renderer = _ClosableRenderer()
        cache = PageCache()
        original_local = cache._local
        cache._renderers.extend((failing_renderer, remaining_renderer))
        with self.assertRaisesRegex(RuntimeError, "native close failed") as raised:
            cache.clear()
        self.assertIs(raised.exception, expected_error)
        self.assertTrue(failing_renderer.closed)
        self.assertTrue(remaining_renderer.closed)
        self.assertEqual(cache._renderers, [])
        self.assertIsNot(cache._local, original_local)


if __name__ == "__main__":
    unittest.main()
