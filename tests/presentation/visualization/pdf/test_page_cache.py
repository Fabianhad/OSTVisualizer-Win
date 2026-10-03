from PySide6.QtGui import QImage
from ost_visualizer.presentation.visualization.pdf.page_cache import (
    PageCache,
    scoped_pdf_render_cancellation_token,
)
from ost_visualizer.application.render_quality import (
    CONSTRAINED_RENDER_SCALE_FLOOR,
    INTERACTIVE_PDF_RENDER_SCALE,
)
import unittest
import threading
import tempfile
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui
from ost_visualizer.presentation.visualization.utils.source_signature import (
    invalidate_source_files,
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
        self.page_count_calls = []

    def get_page_count(self, file_path):
        self.page_count_calls.append(file_path)
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
        # The 20M-pixel base raster cap binds before the byte cap:
        # floor(sqrt(20_000_000 / (3024 * 2160)) * 1000) / 1000.
        self.assertEqual(scale, 1.749)

    def test_cacheable_render_scale_without_pixel_cap_is_limited_by_image_bytes(self):
        # sqrt(96 MiB * 0.95 / (3024 * 2160 * 4)) floored to 3 decimals.
        self.assertEqual(
            PageCache.cacheable_render_scale(3024.0, 2160.0, 3.0),
            1.913,
        )
        self.assertEqual(
            PageCache.cacheable_render_scale(3024.0, 2160.0, 3.0, tinted=True),
            1.913,
        )
        self.assertEqual(
            PageCache.cacheable_render_scale(3024.0, 2160.0, 1.5),
            1.5,
        )

    def test_cacheable_render_scale_passes_through_degenerate_inputs(self):
        for width, height, scale in (
            (0.0, 792.0, 3.0),
            (612.0, 0.0, 3.0),
            (-612.0, 792.0, 3.0),
            (612.0, 792.0, 0.0),
            (612.0, 792.0, -1.0),
        ):
            with self.subTest(width=width, height=height, scale=scale):
                self.assertEqual(
                    PageCache.cacheable_render_scale(width, height, scale),
                    scale,
                )

    def test_estimated_render_bytes_rounds_pixel_extent_up(self):
        self.assertEqual(
            PageCache.estimated_render_bytes(612.0, 792.0, 2.0),
            1224 * 1584 * 4,
        )
        self.assertEqual(PageCache.estimated_render_bytes(10.2, 10.0, 1.0), 11 * 10 * 4)
        self.assertEqual(PageCache.estimated_render_bytes(0.0, 792.0, 2.0), 0)
        self.assertEqual(PageCache.estimated_render_bytes(612.0, 792.0, 0.0), 0)

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
        self.assertEqual(scale, 0.1)
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
        cache.get_page_size("b.pdf", 0)
        self.assertEqual(
            renderer.page_size_calls,
            [("a.pdf", 0), ("b.pdf", 0), ("c.pdf", 0), ("b.pdf", 0)],
        )

    def test_metadata_lookups_return_cached_values_and_isolate_text_runs(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        self.assertEqual(
            cache.get_page_info("a.pdf", 0), {"file_path": "a.pdf", "page_index": 0}
        )
        self.assertEqual(cache.get_page_info("a.pdf", 0), cache.get_page_info("a.pdf"))
        self.assertEqual(cache.get_page_size("a.pdf", 0), (0, 1))
        self.assertEqual(cache.get_page_size("a.pdf", 0), (0, 1))
        first_runs = cache.get_text_runs("a.pdf", 0)
        self.assertEqual(first_runs, [{"file_path": "a.pdf", "page_index": 0}])
        first_runs.append("mutation of the miss result")
        cached_runs = cache.get_text_runs("a.pdf", 0)
        self.assertEqual(cached_runs, [{"file_path": "a.pdf", "page_index": 0}])
        cached_runs.append("mutation of the hit result")
        self.assertEqual(
            cache.get_text_runs("a.pdf", 0),
            [{"file_path": "a.pdf", "page_index": 0}],
        )
        self.assertEqual(renderer.page_info_calls, [("a.pdf", 0)])
        self.assertEqual(renderer.page_size_calls, [("a.pdf", 0)])
        self.assertEqual(renderer.text_run_calls, [("a.pdf", 0)])

    def test_metadata_cache_keys_include_source_signature_and_clear_drops_them(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        signatures = [(1, 10, 1)]
        cache._get_renderer = lambda: renderer
        cache._file_signature = lambda _path: signatures[0]
        cache.get_page_info("a.pdf", 0)
        cache.get_page_size("a.pdf", 0)
        cache.get_text_runs("a.pdf", 0)
        signatures[0] = (1, 10, 2)
        cache.get_page_info("a.pdf", 0)
        cache.get_page_size("a.pdf", 0)
        cache.get_text_runs("a.pdf", 0)
        self.assertEqual(len(renderer.page_info_calls), 2)
        self.assertEqual(len(renderer.page_size_calls), 2)
        self.assertEqual(len(renderer.text_run_calls), 2)
        cache.clear()
        self.assertEqual(
            (
                len(cache._page_info_cache),
                len(cache._page_size_cache),
                len(cache._text_runs_cache),
            ),
            (0, 0, 0),
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
        retained = {key.file_path for key in cache._cache}
        self.assertNotIn("page-0.pdf", retained)
        self.assertIn("page-1.pdf", retained)
        self.assertIn("page-overflow.pdf", retained)

    def test_prefetch_pressure_accounts_for_every_shared_image_cache(self):
        shared_budget = 1600 * 1024 * 1024
        estimate = PageCache.estimated_render_bytes(612.0, 792.0, 1.0)
        self.assertEqual(estimate, 612 * 792 * 4)
        cache = PageCache()
        cache._image_size_bytes = lambda value: int(value)
        self.assertTrue(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))
        for attribute in (
            "_cache",
            "_frame_cache",
            "_tinted_cache",
            "_composite_cache",
        ):
            with self.subTest(cache=attribute):
                cache = PageCache()
                cache._image_size_bytes = lambda value: int(value)
                target = getattr(cache, attribute)
                target["held"] = shared_budget - estimate
                self.assertTrue(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))
                target["held"] = shared_budget - estimate + 1
                self.assertFalse(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))
        cache = PageCache()
        cache._image_size_bytes = lambda value: int(value)
        cache._frame_cache["frame"] = 10**12
        cache._tinted_cache["tinted"] = 10**12
        self.assertFalse(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))

    def test_prefetch_admission_rejects_oversized_image_and_full_entry_table(self):
        cache = PageCache()
        cache._image_size_bytes = lambda value: int(value)
        self.assertFalse(cache.can_accept_prefetch_render(10000.0, 10000.0, 1.0))
        self.assertFalse(
            cache.can_accept_prefetch_render(10000.0, 10000.0, 1.0, tinted=True)
        )
        self.assertTrue(cache.can_accept_prefetch_render(5000.0, 5000.0, 1.0))
        for index in range(PageCache.MAX_ENTRIES - 1):
            cache._cache[f"entry-{index}"] = 0
        self.assertTrue(cache.can_accept_prefetch_render(612.0, 792.0, 1.0))
        cache._cache["last-entry"] = 0
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
        self.assertEqual(renderer.page_count_calls, [pdf_file.name])

    def test_page_index_normalization_handles_non_pdf_empty_and_unreadable_sources(
        self,
    ):
        renderer = _RecordingPageRenderer(page_count=3)
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        with tempfile.TemporaryDirectory() as temp_dir:
            tif_path = Path(temp_dir) / "scan.tif"
            tif_path.write_bytes(b"tif")
            pdf_path = Path(temp_dir) / "plan.pdf"
            pdf_path.write_bytes(b"pdf")
            cache.get_page(str(tif_path), 7, 1.0, 0)
            self.assertEqual(renderer.render_calls[-1][1], 0)
            self.assertEqual(renderer.page_count_calls, [])
            renderer.page_count = 0
            cache.get_page(str(pdf_path), 5, 1.0, 0)
            self.assertEqual(renderer.render_calls[-1][1], 0)
        # A missing source has no signature, so the requested index is kept
        # instead of asking the native layer for a page count.
        renderer.page_count_calls.clear()
        cache.get_page(str(Path(temp_dir) / "missing.pdf"), 5, 1.0, 0)
        self.assertEqual(renderer.render_calls[-1][1], 5)
        self.assertEqual(renderer.page_count_calls, [])

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
        self.assertEqual(len(cache._frame_cache), 0)

    def test_oversized_image_is_rejected_without_evicting_cached_pages(self):
        class SizedRenderer:
            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                side = 64 if "huge" in file_path else 16
                return QImage(side, side, QImage.Format.Format_ARGB32)

        cache = PageCache()
        cache._get_renderer = lambda: SizedRenderer()
        cache._image_size_bytes = lambda image: (
            10**12 if image.width() > 16 else image.width() * image.height() * 4
        )
        small = cache.get_page("small.pdf", 0, 1.0, 0)
        huge = cache.get_page("huge.pdf", 0, 1.0, 0)
        self.assertFalse(huge.isNull())
        self.assertEqual({key.file_path for key in cache._cache}, {"small.pdf"})
        self.assertIs(cache.get_page("small.pdf", 0, 1.0, 0), small)

    def test_visible_frame_coordinates_are_quantized_before_render_and_keying(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        first = cache.get_frame("page.pdf", 0, 2.0, 10.0004, 20.0, 30.0, 40.0, 0)
        second = cache.get_frame("page.pdf", 0, 2.0, 10.0, 20.0004, 30.0004, 40.0, 0)
        third = cache.get_frame("page.pdf", 0, 2.0, 10.002, 20.0, 30.0, 40.0, 0)
        self.assertIs(first, second)
        self.assertIsNot(first, third)
        self.assertEqual(
            [call[:8] for call in renderer.frame_calls],
            [
                ("page.pdf", 0, 2.0, 10.0, 20.0, 30.0, 40.0, 0),
                ("page.pdf", 0, 2.0, 10.002, 20.0, 30.0, 40.0, 0),
            ],
        )

    def test_frame_lookup_rejects_empty_path_and_non_positive_frame_size(self):
        renderer = _FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        self.assertIsNone(cache.get_frame("", 0, 2.0, 0.0, 0.0, 30.0, 40.0, 0))
        self.assertIsNone(cache.get_frame("page.pdf", 0, 2.0, 0.0, 0.0, 0.0, 40.0, 0))
        self.assertIsNone(cache.get_frame("page.pdf", 0, 2.0, 0.0, 0.0, 30.0, -1.0, 0))
        self.assertEqual(renderer.frame_calls, [])
        self.assertIsNotNone(
            cache.get_frame("page.pdf", 0, 2.0, 0.0, 0.0, 30.0, 40.0, 0)
        )
        self.assertEqual(len(renderer.frame_calls), 1)

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
        # The bypassing request must not release the prefetch's in-flight claim.
        self.assertEqual(len(cache._in_flight), 1)
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
        # The waiting lookup shares the first render instead of repeating it.
        self.assertEqual(len(renderer.calls), 1)
        self.assertIs(first_results[0], second_results[0])

    def test_failed_render_releases_waiters_and_is_not_cached(self):
        class FailingThenSucceedingRenderer:
            def __init__(self):
                self.calls = 0

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("native render failed")
                return QImage(16, 16, QImage.Format.Format_ARGB32)

        renderer = FailingThenSucceedingRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        with self.assertRaisesRegex(RuntimeError, "native render failed"):
            cache.get_page("page.pdf", 0, 1.0, 0)
        self.assertEqual(cache._in_flight, set())
        self.assertEqual(len(cache._cache), 0)
        retried = cache.get_page("page.pdf", 0, 1.0, 0)
        self.assertFalse(retried.isNull())
        self.assertEqual(renderer.calls, 2)
        self.assertEqual(len(cache._cache), 1)

    def test_scoped_cancellation_token_restores_previous_scope(self):
        renderer = _TokenAwareRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        outer = _RecordingCancelToken()
        inner = _RecordingCancelToken()
        other_thread_tokens = []

        def render_on_other_thread():
            other_renderer = _TokenAwareRenderer()
            other_cache = PageCache()
            other_cache._get_renderer = lambda: other_renderer
            other_cache.get_page("other.pdf", 0, 1.0, 0)
            other_thread_tokens.extend(other_renderer.page_tokens)

        with scoped_pdf_render_cancellation_token(outer):
            with scoped_pdf_render_cancellation_token(inner):
                cache.get_page("inner.pdf", 0, 1.0, 0)
                worker = threading.Thread(target=render_on_other_thread)
                worker.start()
                worker.join(timeout=2.0)
            cache.get_page("outer.pdf", 0, 1.0, 0)
            with self.assertRaisesRegex(RuntimeError, "scope failure"):
                with scoped_pdf_render_cancellation_token(inner):
                    raise RuntimeError("scope failure")
            cache.get_page("after-error.pdf", 0, 1.0, 0)
        cache.get_page("unscoped.pdf", 0, 1.0, 0)
        self.assertEqual(
            renderer.page_tokens,
            [inner, outer, outer, None],
        )
        self.assertEqual(other_thread_tokens, [None])

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
        self.assertEqual(cache._in_flight, set())
        self.assertEqual(cache._frame_in_flight, set())
        self.assertEqual(renderer.page_tokens, [token])
        self.assertEqual(renderer.frame_tokens, [token])
        # Positive control: the same keys render and cache once the scope ends.
        live_page = cache.get_page("page.pdf", 0, 1.0, 0)
        live_frame = cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0)
        self.assertFalse(live_page.isNull())
        self.assertFalse(live_frame.isNull())
        self.assertIs(cache.get_page("page.pdf", 0, 1.0, 0), live_page)
        self.assertIs(
            cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0), live_frame
        )
        self.assertEqual(renderer.page_tokens, [token, None])
        self.assertEqual(renderer.frame_tokens, [token, None])

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

    def test_clear_drops_every_cached_image_and_forces_a_new_render(self):
        renderer = _TokenAwareRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        page = cache.get_page("page.pdf", 0, 1.0, 0)
        tinted = cache.get_tinted_page("page.pdf", 0, 1.0, 0, (10, 20, 30))
        frame = cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0)
        composite_image = QImage(4, 4, QImage.Format.Format_ARGB32)
        composite = cache.get_composite(
            ("composite", 1),
            lambda: (composite_image, True),
            is_current=lambda: True,
        )
        self.assertIs(composite, composite_image)
        self.assertEqual(
            (
                len(cache._cache),
                len(cache._tinted_cache),
                len(cache._frame_cache),
                len(cache._composite_cache),
            ),
            (1, 1, 1, 1),
        )
        cache.clear()
        self.assertEqual(
            (
                len(cache._cache),
                len(cache._tinted_cache),
                len(cache._frame_cache),
                len(cache._composite_cache),
            ),
            (0, 0, 0, 0),
        )
        self.assertIsNot(cache.get_page("page.pdf", 0, 1.0, 0), page)
        self.assertIsNot(
            cache.get_tinted_page("page.pdf", 0, 1.0, 0, (10, 20, 30)), tinted
        )
        self.assertIsNot(
            cache.get_frame("page.pdf", 0, 1.0, 0.0, 0.0, 10.0, 10.0, 0), frame
        )
        self.assertEqual(len(renderer.page_tokens), 2)
        self.assertEqual(len(renderer.frame_tokens), 2)

    def test_tinted_page_is_cached_per_tint_and_reuses_one_base_render(self):
        renderer = _RecordingPageRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        first = cache.get_tinted_page("page.pdf", 0, 1.0, 0, (10, 20, 30))
        again = cache.get_tinted_page("page.pdf", 0, 1.0, 0, (10, 20, 30))
        self.assertIs(first, again)
        self.assertEqual((first.width(), first.height()), (16, 16))
        # Each colour channel is part of the key on its own.
        variants = [
            cache.get_tinted_page("page.pdf", 0, 1.0, 0, tint)
            for tint in ((11, 20, 30), (10, 21, 30), (10, 20, 31))
        ]
        for variant in variants:
            self.assertIsNot(variant, first)
        self.assertEqual(len({id(image) for image in variants}), 3)
        self.assertEqual(len(renderer.render_calls), 1)
        self.assertEqual(len(cache._tinted_cache), 4)
        self.assertIsNone(cache.get_tinted_page("", 0, 1.0, 0))

    def test_tinted_page_is_not_cached_when_base_render_fails(self):
        class NullRenderer:
            def __init__(self):
                self.calls = 0

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls += 1
                return None

        renderer = NullRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        self.assertIsNone(cache.get_tinted_page("page.pdf", 0, 1.0, 0))
        self.assertIsNone(cache.get_tinted_page("page.pdf", 0, 1.0, 0))
        self.assertEqual(renderer.calls, 2)
        self.assertEqual(len(cache._tinted_cache), 0)
        self.assertEqual(len(cache._cache), 0)


class PageCachePreferenceTests(unittest.TestCase):
    def test_page_cache_keeps_low_and_high_resolution_scales_separate(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append((file_path, page_index, scale, rotation))
                return QtGui.QImage(
                    int(scale * 10),
                    int(scale * 10),
                    QtGui.QImage.Format.Format_ARGB32,
                )

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        low = cache.get_page("page.pdf", 0, 1.0, 0)
        high = cache.get_page("page.pdf", 0, 2.0, 0)
        low_again = cache.get_page("page.pdf", 0, 1.0, 0)
        self.assertIs(low, low_again)
        self.assertIsNot(low, high)
        self.assertEqual(
            renderer.calls,
            [
                ("page.pdf", 0, 1.0, 0),
                ("page.pdf", 0, 2.0, 0),
            ],
        )

    def test_page_cache_key_changes_when_same_path_file_content_changes(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append((file_path, page_index, scale, rotation))
                return QtGui.QImage(
                    len(self.calls),
                    1,
                    QtGui.QImage.Format.Format_ARGB32,
                )

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "signature.pdf"
            path.write_bytes(b"first")
            first = cache.get_page(str(path), 0, 1.0, 0)
            first_again = cache.get_page(str(path), 0, 1.0, 0)
            path.write_bytes(b"second-version")
            second = cache.get_page(str(path), 0, 1.0, 0)
        self.assertIs(first, first_again)
        self.assertIsNot(first, second)
        self.assertEqual(len(renderer.calls), 2)

    def test_explicit_source_revision_invalidates_cache_for_unchanged_file_stat(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = 0

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls += 1
                return QtGui.QImage(2, 2, QtGui.QImage.Format.Format_ARGB32)

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "revision.pdf"
            path.write_bytes(b"same-size-bytes")
            stat_before = path.stat()
            signature_before = cache.file_signature(str(path))
            first = cache.get_page(str(path), 0, 1.0, 0)
            self.assertIs(cache.get_page(str(path), 0, 1.0, 0), first)
            invalidate_source_files([str(path)])
            stat_after = path.stat()
            signature_after = cache.file_signature(str(path))
            second = cache.get_page(str(path), 0, 1.0, 0)
            # Same mtime and size: only the explicit revision differs.
            self.assertEqual(
                (stat_before.st_mtime_ns, stat_before.st_size),
                (stat_after.st_mtime_ns, stat_after.st_size),
            )
            self.assertEqual(signature_before[:2], signature_after[:2])
            self.assertNotEqual(signature_before[2], signature_after[2])
            self.assertIsNot(first, second)
            self.assertIs(cache.get_page(str(path), 0, 1.0, 0), second)
        self.assertEqual(renderer.calls, 2)

    def test_page_cache_quantizes_scale_before_full_and_frame_renders(self):
        class FakeRenderer:
            def __init__(self):
                self.calls = []

            def render(
                self, file_path, page_index, scale, rotation, native_cancel_token=None
            ):
                self.calls.append(("page", scale))
                return QtGui.QImage(10, 10, QtGui.QImage.Format.Format_ARGB32)

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
                self.calls.append(
                    (
                        "frame",
                        scale,
                        frame_x_pts,
                        frame_y_pts,
                        frame_w_pts,
                        frame_h_pts,
                    )
                )
                return QtGui.QImage(3, 4, QtGui.QImage.Format.Format_ARGB32)

        renderer = FakeRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        cache.get_page("page.pdf", 0, 1.23456, 0)
        cache.get_frame("page.pdf", 0, 1.23456, 1.0, 2.0, 3.0, 4.0, 0)
        self.assertEqual(
            renderer.calls,
            [
                ("page", 1.235),
                ("frame", 1.235, 1.0, 2.0, 3.0, 4.0),
            ],
        )
