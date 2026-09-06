import os
import threading
import unittest
from collections import OrderedDict
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QColor, QImage, QPainter
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)


def _image(width=20, height=20):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    return image


def _page(**overrides):
    values = dict(
        uid="page-1",
        name="Page 1",
        image_path="base.pdf",
        overlay_image_path="overlay.pdf",
        width_pts=100.0,
        height_pts=100.0,
        scale_factor1=0.1875,
        scale_factor2=12.0,
        overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
    )
    values.update(overrides)
    return Page(**values)


class _FramePageCache(PageCache):
    def file_signature(self, _file_path):
        return None

    def get_tinted_page(self, *_args, **_kwargs):
        return _image()

    def get_frame(self, *_args, **_kwargs):
        return _image()

    def get_page_size(self, _file_path, _page_index):
        return 100.0, 100.0


class _SignaturePageCache(_FramePageCache):
    def __init__(self):
        super().__init__()
        self.signatures = {
            "base.pdf": (1, 100),
            "overlay.pdf": (1, 200),
        }
        self.tinted_calls = 0

    def file_signature(self, file_path):
        return self.signatures.get(file_path)

    def get_tinted_page(self, *_args, **_kwargs):
        self.tinted_calls += 1
        return _image()


class _BlockingContainsDict(OrderedDict):
    def __init__(self, entered, release):
        super().__init__()
        self._entered = entered
        self._release = release

    def __contains__(self, key):
        present = super().__contains__(key)
        self._entered.set()
        self._release.wait(timeout=2.0)
        return present


class _ExplodingPainter:
    RenderHint = QPainter.RenderHint
    last_instance = None

    def __init__(self, _target):
        self.ended = False
        type(self).last_instance = self

    def setRenderHint(self, *_args):
        pass

    def drawImage(self, *_args):
        raise RuntimeError("draw failed")

    def end(self):
        self.ended = True


class CompositeRendererTests(unittest.TestCase):
    def test_matching_pdf_frames_reuse_composition_after_consumer_reopen(self):
        cache = _SignaturePageCache()
        first, second = CompositeRenderer(cache), CompositeRenderer(cache)
        args = (_page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0)
        with patch.object(
            CompositeRenderer,
            "_draw_overlay_pdf_frame",
            autospec=True,
            side_effect=CompositeRenderer._draw_overlay_pdf_frame,
        ) as draw:
            image = first.render_composite_frame(*args)
            self.assertIsNotNone(image)
            self.assertEqual(second.render_composite_frame(*args), image)
            self.assertIs(CompositeRenderer(cache).render_composite_frame(*args), image)
            self.assertEqual(draw.call_count, 1)

    def test_pdf_frame_key_separates_viewport_resolution_and_composition_inputs(self):
        from dataclasses import replace

        cache = _SignaturePageCache()
        renderer = CompositeRenderer(cache)
        page = _page()

        def render(
            page=page, scale=1.0, x=0.0, y=0.0, width=100.0, height=100.0, rotation=0
        ):
            return renderer.render_composite_frame(
                page, scale, x, y, width, height, rotation
            )

        image = render()
        self.assertIsNotNone(image)
        for arguments in (
            {"scale": 2.0},
            {"x": 10.0},
            {"y": 10.0},
            {"width": 50.0},
            {"height": 50.0},
            {"rotation": 90},
        ):
            with self.subTest(arguments=arguments):
                self.assertIsNot(render(**arguments), image)
        for changes in (
            {"overlay_rect": (10.0, 10.0, 30.0, 30.0)},
            {"overlay_rotation": 0.2},
            {"deskew_rotation_overlay": 0.2},
            {"scale_factor2": 24.0},
            {"width_pts": 200.0},
            {"height_pts": 200.0},
        ):
            with self.subTest(changes=changes):
                self.assertIsNot(render(page=replace(page, **changes)), image)
        # Reopen onto a cached current state; downstream effects do not own the base frame.
        image = render()
        self.assertIs(
            render(page=replace(page, invert=True, bitonal=True, name="Renamed")), image
        )
        cache.clear_composites()
        self.assertIsNot(render(), image)

    def test_pdf_frame_cache_rejects_obsolete_source_and_incomplete_overlay(self):
        cache = _SignaturePageCache()
        first, second = CompositeRenderer(cache), CompositeRenderer(cache)
        args = (_page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0)
        entered, release = threading.Event(), threading.Event()
        results = []
        original = first._draw_overlay_pdf_frame

        def blocked(*values):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Frame composition was not released")
            return original(*values)

        with patch.object(first, "_draw_overlay_pdf_frame", side_effect=blocked):
            thread = threading.Thread(
                target=lambda: results.append(first.render_composite_frame(*args))
            )
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                cache.signatures["overlay.pdf"] = (2, 200)
                accepted = second.render_composite_frame(*args)
            finally:
                release.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.assertIs(second.render_composite_frame(*args), accepted)
        cache.clear_composites()
        original_get = cache.get_frame
        with patch.object(
            cache,
            "get_frame",
            side_effect=lambda path, *values, **kwargs: (
                None if path == "overlay.pdf" else original_get(path, *values, **kwargs)
            ),
        ):
            fallback = first.render_composite_frame(*args)
        self.assertIsNotNone(fallback)
        self.assertEqual(len(cache._composite_cache), 0)
        with patch.object(
            second, "_draw_overlay_pdf_frame", wraps=second._draw_overlay_pdf_frame
        ) as draw:
            recovered = second.render_composite_frame(*args)
            self.assertIsNotNone(recovered)
            self.assertEqual(draw.call_count, 1)

    def test_pdf_frame_matching_concurrent_consumers_share_work(self):
        cache = _SignaturePageCache()
        first, second = CompositeRenderer(cache), CompositeRenderer(cache)
        args = (_page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0)
        entered, waiting, release = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        results = []
        original = CompositeRenderer._draw_overlay_pdf_frame
        original_wait = cache._in_flight_condition.wait

        def blocked(*values):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Frame composition was not released")
            return original(*values)

        def wait(*values, **kwargs):
            waiting.set()
            return original_wait(*values, **kwargs)

        with patch.object(
            CompositeRenderer,
            "_draw_overlay_pdf_frame",
            autospec=True,
            side_effect=blocked,
        ) as draw, patch.object(cache._in_flight_condition, "wait", side_effect=wait):
            threads = [
                threading.Thread(
                    target=lambda renderer=renderer: results.append(
                        renderer.render_composite_frame(*args)
                    )
                )
                for renderer in (first, second)
            ]
            threads[0].start()
            try:
                self.assertTrue(entered.wait(1))
                threads[1].start()
                self.assertTrue(waiting.wait(1))
            finally:
                release.set()
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(2)
            self.assertEqual(draw.call_count, 1)
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])

    def test_overlay_canvas_key_covers_placement_resolution_and_tint(self):
        from dataclasses import replace

        renderer = CompositeRenderer(_SignaturePageCache())
        page = _page()
        tint = (80, 80, 255)
        image = renderer.render_overlay_only(page, 1.0, tint_rgb=tint)
        self.assertIsNotNone(image)
        for changes in (
            {"name": "Renamed"},
            {"invert": True},
            {"bitonal": True},
            {"image_path": "unrelated-original.pdf"},
        ):
            self.assertIs(
                renderer.render_overlay_only(
                    replace(page, **changes), 1.0, tint_rgb=tint
                ),
                image,
            )
        for changes in (
            {"width_pts": 200.0},
            {"height_pts": 200.0},
            {"overlay_rotation": 0.2},
            {"deskew_rotation_overlay": 0.3},
            {"overlay_rect": (1, 2, 20, 30)},
            {"scale_factor2": 24.0},
        ):
            with self.subTest(changes=changes):
                self.assertIsNot(
                    renderer.render_overlay_only(
                        replace(page, **changes), 1.0, tint_rgb=tint
                    ),
                    image,
                )
        self.assertIsNot(renderer.render_overlay_only(page, 2.0, tint_rgb=tint), image)
        self.assertIsNot(
            renderer.render_overlay_only(page, 1.0, tint_rgb=(255, 80, 80)), image
        )

    def test_overlay_canvas_pending_source_revision_cannot_repopulate_cache(self):
        cache = _SignaturePageCache()
        old, current = CompositeRenderer(cache), CompositeRenderer(cache)
        entered, release = threading.Event(), threading.Event()
        results = []
        original = old._draw_overlay_image

        def blocked(*args):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Composition was not released")
            return original(*args)

        with patch.object(old, "_draw_overlay_image", side_effect=blocked):
            thread = threading.Thread(
                target=lambda: results.append(
                    old.render_overlay_only(_page(), 1.0, tint_rgb=(80, 80, 255))
                )
            )
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                cache.signatures["overlay.pdf"] = (2, 200)
                accepted = current.render_overlay_only(
                    _page(), 1.0, tint_rgb=(80, 80, 255)
                )
            finally:
                release.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.assertIs(
            current.render_overlay_only(_page(), 1.0, tint_rgb=(80, 80, 255)), accepted
        )
        self.assertEqual(len(cache._composite_cache), 1)

    def test_matching_renderers_share_one_in_flight_composition(self):
        self._assert_in_flight_composition(cancel_owner=False)

    def test_cancelled_producer_does_not_cancel_other_consumers(self):
        self._assert_in_flight_composition(cancel_owner=True)

    def test_cache_clear_does_not_cancel_a_waiting_consumer(self):
        self._assert_in_flight_composition(cancel_owner=False, clear_cache=True)

    def _assert_in_flight_composition(self, *, cancel_owner, clear_cache=False):
        cache = _SignaturePageCache()
        first, second = CompositeRenderer(cache), CompositeRenderer(cache)
        entered, release, waiting = (threading.Event() for _ in range(3))
        results = []
        cancelled = threading.Event()
        original = CompositeRenderer._composite_images
        wait = cache._in_flight_condition.wait

        def compose(*args):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Composition was not released")
            return original(*args)

        def wait_for_owner(*args, **kwargs):
            waiting.set()
            return wait(*args, **kwargs)

        with patch.object(
            CompositeRenderer, "_composite_images", autospec=True, side_effect=compose
        ) as calls, patch.object(
            cache._in_flight_condition, "wait", side_effect=wait_for_owner
        ):
            threads = [
                threading.Thread(
                    target=lambda renderer=renderer: results.append(
                        renderer.render_composite(
                            _page(),
                            None,
                            1.0,
                            0,
                            cancelled_check=(
                                cancelled.is_set if renderer is first else None
                            ),
                        )
                    )
                )
                for renderer in (first, second)
            ]
            threads[0].start()
            self.assertTrue(entered.wait(1))
            threads[1].start()
            try:
                self.assertTrue(waiting.wait(1))
                if cancel_owner:
                    cancelled.set()
                if clear_cache:
                    cache.clear_composites()
            finally:
                release.set()
                for thread in threads:
                    thread.join(2)
            self.assertEqual(calls.call_count, 2 if cancel_owner or clear_cache else 1)
        self.assertEqual(len(results), 2)
        if cancel_owner:
            self.assertEqual(sum(image is None for image in results), 1)
            self.assertEqual(len(cache._composite_cache), 1)
        else:
            self.assertIsNotNone(results[0])
            if clear_cache:
                self.assertEqual(results[0], results[1])
                self.assertEqual(len(cache._composite_cache), 1)
            else:
                self.assertIs(results[0], results[1])

    def test_old_composition_cannot_repopulate_after_clear_or_source_replacement(self):
        for transition in ("clear", "source"):
            with self.subTest(transition=transition):
                cache = _SignaturePageCache()
                old, new = CompositeRenderer(cache), CompositeRenderer(cache)
                entered, release = threading.Event(), threading.Event()
                old_results = []
                original = old._composite_images

                def blocked(*args):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("Composition was not released")
                    return original(*args)

                with patch.object(old, "_composite_images", side_effect=blocked):
                    thread = threading.Thread(
                        target=lambda: old_results.append(
                            old.render_composite(_page(), None, 1.0, 0)
                        )
                    )
                    thread.start()
                    self.assertTrue(entered.wait(1))
                    try:
                        if transition == "clear":
                            cache.clear_composites()
                        else:
                            cache.signatures["overlay.pdf"] = (2, 200)
                        accepted = new.render_composite(_page(), None, 1.0, 0)
                    finally:
                        release.set()
                        thread.join(2)
                if transition == "source":
                    self.assertEqual(old_results, [None])
                else:
                    self.assertEqual(len(old_results), 1)
                    self.assertIsNotNone(old_results[0])
                    self.assertIsNot(old_results[0], accepted)
                self.assertIsNotNone(accepted)
                self.assertIs(new.render_composite(_page(), None, 1.0, 0), accepted)
                self.assertEqual(len(cache._composite_cache), 1)

    def test_composite_key_covers_geometry_but_not_post_composite_effects(self):
        from dataclasses import replace

        cache = _SignaturePageCache()
        renderer = CompositeRenderer(cache)
        page = _page()
        image = renderer.render_composite(page, None, 1.0, 0)
        for changes in ({"invert": True}, {"bitonal": True}, {"name": "Renamed"}):
            self.assertIs(
                CompositeRenderer(cache).render_composite(
                    replace(page, **changes), None, 1.0, 0
                ),
                image,
            )
        for changes in (
            {"width_pts": 200.0},
            {"height_pts": 200.0},
            {"overlay_rotation": 0.25},
            {"deskew_rotation_overlay": 0.1},
            {"overlay_rect": (1.0, 1.0, 20.0, 20.0)},
            {"scale_factor2": 24.0},
            {"rotation": 90, "width_pts": 200.0},
            {"image_show_mode": 2},
        ):
            with self.subTest(changes=changes):
                self.assertIsNot(
                    CompositeRenderer(cache).render_composite(
                        replace(page, **changes), None, 1.0, 0
                    ),
                    image,
                )
        self.assertIsNot(renderer.render_composite(page, None, 2.0, 0), image)
        self.assertIsNot(renderer.render_composite(page, None, 1.0, 90), image)

    def test_shared_composites_obey_entry_and_byte_budgets(self):
        cache = _SignaturePageCache()
        renderer = CompositeRenderer(cache)
        for uid in range(15):
            self.assertIsNotNone(
                renderer.render_composite(_page(uid=str(uid)), None, 1.0, 0)
            )
        self.assertEqual(len(cache._composite_cache), 10)
        cache.clear_composites()
        with patch(
            "ost_visualizer.presentation.visualization.pdf.page_cache._COMPOSITE_CACHE_MAX_BYTES",
            1600,
        ):
            for uid in range(3):
                renderer.render_composite(_page(uid=str(uid)), None, 1.0, 0)
        self.assertEqual(len(cache._composite_cache), 1)
        cache.clear_composites()
        with patch.object(cache, "PAGE_CACHE_MAX_SINGLE_IMAGE_BYTES", 1):
            self.assertIsNotNone(renderer.render_composite(_page(), None, 1.0, 0))
        self.assertFalse(cache._composite_cache)

    def test_page_dimension_change_moves_overlay_instead_of_reusing_old_pixels(self):
        from dataclasses import replace

        class ColoredCache(_FramePageCache):
            def get_tinted_page(self, file_path, *_args, **_kwargs):
                image = _image()
                image.fill(QColor("red" if file_path == "base.pdf" else "blue"))
                return image

        cache = ColoredCache()
        page = _page(overlay_rect=(0.0, 0.0, 50.0 / 72.0 * 64.0, 50.0 / 72.0 * 64.0))
        first = CompositeRenderer(cache).render_composite(page, None, 1.0, 0)
        second = CompositeRenderer(cache).render_composite(
            replace(page, width_pts=200.0), None, 1.0, 0
        )
        self.assertEqual(first.pixelColor(7, 7), QColor("blue"))
        self.assertEqual(second.pixelColor(7, 7), QColor("red"))

    def test_raster_base_composite_keeps_native_canvas_and_pdf_overlay_baseline(self):
        class SourceAwareCache(_FramePageCache):
            def __init__(self):
                super().__init__()
                self.calls = []

            def get_tinted_page(
                self,
                file_path,
                _page_index,
                scale,
                _rotation,
                *,
                tint_rgb,
                wait_for_in_flight,
            ):
                self.calls.append((file_path, scale, tint_rgb, wait_for_in_flight))
                if file_path == "base.tif":
                    return _image(13, 11)
                return _image(200, 200)

        cache = SourceAwareCache()
        result = CompositeRenderer(cache).render_composite(
            _page(image_path="base.tif"),
            bid_ref=None,
            render_scale=RASTER_NATIVE_RENDER_SCALE,
            raster_rotation=0,
        )
        self.assertIsNotNone(result)
        self.assertEqual((result.width(), result.height()), (13, 11))
        self.assertEqual(
            [(path, scale) for path, scale, _tint, _wait in cache.calls],
            [
                ("base.tif", RASTER_NATIVE_RENDER_SCALE),
                ("overlay.pdf", INTERACTIVE_PDF_RENDER_SCALE),
            ],
        )

    def test_composite_cache_invalidates_when_a_source_file_changes(self):
        page_cache = _SignaturePageCache()
        renderer = CompositeRenderer(page_cache)
        page = _page()
        first = renderer.render_composite(page, None, 1.0, 0)
        cached = renderer.render_composite(page, None, 1.0, 0)
        self.assertIs(first, cached)
        self.assertEqual(page_cache.tinted_calls, 2)
        page_cache.signatures["overlay.pdf"] = (2, 250)
        refreshed = renderer.render_composite(page, None, 1.0, 0)
        self.assertIsNot(refreshed, cached)
        self.assertEqual(page_cache.tinted_calls, 4)

    def test_cache_clear_cannot_interleave_with_cache_hit(self):
        renderer = CompositeRenderer(_FramePageCache())
        page = _page()
        cache_key = renderer._build_cache_key(page, None, 1.0, 0)
        entered = threading.Event()
        release = threading.Event()
        cache = _BlockingContainsDict(entered, release)
        cached_image = _image()
        cache[cache_key] = cached_image
        renderer._page_cache._composite_cache = cache
        render_result = []
        render_errors = []
        clear_done = threading.Event()

        def render():
            try:
                render_result.append(renderer.render_composite(page, None, 1.0, 0))
            except Exception as exc:
                render_errors.append(exc)

        render_thread = threading.Thread(target=render)
        clear_thread = threading.Thread(
            target=lambda: (renderer.clear_cache(), clear_done.set())
        )
        render_thread.start()
        self.assertTrue(entered.wait(timeout=1.0))
        clear_thread.start()
        self.assertFalse(clear_done.wait(timeout=0.05))
        release.set()
        render_thread.join(timeout=1.0)
        clear_thread.join(timeout=1.0)
        self.assertFalse(render_thread.is_alive())
        self.assertFalse(clear_thread.is_alive())
        self.assertEqual(render_errors, [])
        self.assertEqual(render_result, [cached_image])
        self.assertTrue(clear_done.is_set())

    def test_cancellation_during_overlay_discards_partial_frame(self):
        renderer = CompositeRenderer(_FramePageCache())
        cancellation_checks = 0

        def cancelled():
            nonlocal cancellation_checks
            cancellation_checks += 1
            return cancellation_checks >= 2

        result = renderer.render_composite_frame(
            _page(),
            scale=1.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
            cancelled_check=cancelled,
        )
        self.assertIsNone(result)
        self.assertGreaterEqual(cancellation_checks, 3)

    def test_cancelled_cached_composite_is_not_returned(self):
        renderer = CompositeRenderer(_FramePageCache())
        page = _page()
        cache_key = renderer._build_cache_key(page, None, 1.0, 0)
        renderer._page_cache._composite_cache[cache_key] = _image()
        result = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.0,
            raster_rotation=0,
            cancelled_check=lambda: True,
        )
        self.assertIsNone(result)

    def test_cancellation_after_compositing_discards_and_does_not_cache_result(self):
        renderer = CompositeRenderer(_FramePageCache())
        page = _page()
        cancelled = threading.Event()
        original = renderer._composite_images

        def compose(*args):
            result = original(*args)
            cancelled.set()
            return result

        with patch.object(
            renderer, "_composite_images", side_effect=compose
        ) as composition:
            result = renderer.render_composite(
                page, None, 1.0, 0, cancelled_check=cancelled.is_set
            )
        cache_key = renderer._build_cache_key(page, None, 1.0, 0)
        self.assertIsNone(result)
        self.assertNotIn(cache_key, renderer._page_cache._composite_cache)
        self.assertEqual(composition.call_count, 1)

    def test_full_composite_ends_painter_when_drawing_fails(self):
        renderer = CompositeRenderer(_FramePageCache())
        with patch(
            "ost_visualizer.presentation.visualization.pdf.services."
            "composite_renderer.QPainter",
            _ExplodingPainter,
        ):
            with self.assertRaisesRegex(RuntimeError, "draw failed"):
                renderer._composite_images(_image(), _image(), _page())
        self.assertTrue(_ExplodingPainter.last_instance.ended)

    def test_composite_frame_ends_painter_when_drawing_fails(self):
        renderer = CompositeRenderer(_FramePageCache())
        with patch(
            "ost_visualizer.presentation.visualization.pdf.services."
            "composite_renderer.QPainter",
            _ExplodingPainter,
        ):
            with self.assertRaisesRegex(RuntimeError, "draw failed"):
                renderer.render_composite_frame(
                    _page(),
                    scale=1.0,
                    frame_x_pts=0.0,
                    frame_y_pts=0.0,
                    frame_w_pts=100.0,
                    frame_h_pts=100.0,
                    rotation=0,
                )
        self.assertTrue(_ExplodingPainter.last_instance.ended)


if __name__ == "__main__":
    unittest.main()
