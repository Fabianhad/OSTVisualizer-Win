from PySide6.QtGui import QColor, QImage, QPainter
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.utils.image_effects import tint_image
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from unittest.mock import patch
from collections import OrderedDict
import unittest
import threading
import os
import math
from pathlib import Path
from typing import Optional
from ost_visualizer.application.render_quality import INTERACTIVE_PDF_RENDER_SCALE
from ost_visualizer.domain.entities.page import Page, build_pages_from_bid_data
from PySide6 import QtCore, QtGui, QtWidgets
from tests.presentation.components.plan_view.frame_cache_support import (
    FakeCompositeFramePageCache as _preferences_support_FakeCompositeFramePageCache,
    FakeDenseMarkerOverlayMovementPageCache as _preferences_support_FakeDenseMarkerOverlayMovementPageCache,
    FakeFrameCacheAdapter as _preferences_support_FakeFrameCacheAdapter,
    FakeOverlayMovementPageCache as _preferences_support_FakeOverlayMovementPageCache,
    FakeShiftedSourceMarkerTifPageCache as _preferences_support_FakeShiftedSourceMarkerTifPageCache,
)
from tests.presentation.dialogs.options.preference_support import (
    _app as _preferences_support__app,
)
from tests.presentation.components.plan_view.visible_frame_support import (
    _first_blue_column as _preferences_support__first_blue_column,
)
from PySide6.QtCore import QPointF
from tests.integration.geometry.overlay_calibration_support import (
    CALIBRATED_64_RECT as _overlay_calibration_support_CALIBRATED_64_RECT,
    _page as _overlay_calibration_support__page,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


class _RasterOverlayPageCache(_SignaturePageCache):
    def __init__(self):
        super().__init__()
        self.signatures["overlay.tif"] = (1, 300)

    def get_page(self, *_args, **_kwargs):
        return _image(200, 200)


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

    def test_composite_key_separates_bid_source_identity_and_base_signature(self):
        from dataclasses import replace

        cache = _SignaturePageCache()
        # The replacement paths carry the same signatures as the originals so
        # only the path text can separate their keys, not the signature.
        cache.signatures["other-base.pdf"] = cache.signatures["base.pdf"]
        cache.signatures["other.pdf"] = cache.signatures["overlay.pdf"]
        renderer = CompositeRenderer(cache)
        page = _page()
        bid = BidRef("bid.mdb", "bid-1")
        image = renderer.render_composite(page, bid, 1.0, 0)
        self.assertIsNotNone(image)
        self.assertIs(renderer.render_composite(page, bid, 1.0, 0), image)
        for name, other_page, other_bid in (
            ("bid file", page, BidRef("other.mdb", "bid-1")),
            ("bid uid", page, BidRef("bid.mdb", "bid-2")),
            ("no bid", page, None),
            ("page uid", replace(page, uid="page-2"), bid),
            ("page index", replace(page, page_index=1), bid),
            ("base path", replace(page, image_path="other-base.pdf"), bid),
            ("overlay path", replace(page, overlay_image_path="other.pdf"), bid),
        ):
            with self.subTest(name):
                other = renderer.render_composite(other_page, other_bid, 1.0, 0)
                self.assertIsNotNone(other)
                self.assertIsNot(other, image)
        cache.signatures["overlay.pdf"] = (1, 201)
        self.assertIsNot(renderer.render_composite(page, bid, 1.0, 0), image)
        cache.signatures["overlay.pdf"] = (1, 200)
        self.assertIs(renderer.render_composite(page, bid, 1.0, 0), image)
        cache.signatures["base.pdf"] = (2, 100)
        self.assertIsNot(renderer.render_composite(page, bid, 1.0, 0), image)

    def test_every_cancellation_checkpoint_discards_the_result_uncached(self):
        def tif_page():
            return _page(overlay_image_path="overlay.tif")

        # (name, cache, render, cancellation checks, rendering work, direct):
        # direct scenarios call the source renderer that get_composite wraps,
        # so its own last checkpoint is observable without the cache's check.
        scenarios = (
            (
                "composite",
                _SignaturePageCache,
                lambda renderer, cancelled: renderer.render_composite(
                    _page(), None, 1.0, 0, cancelled_check=cancelled
                ),
                6,
                ["tinted", "tinted", "composite"],
                False,
            ),
            (
                "composite sources",
                _SignaturePageCache,
                lambda renderer, cancelled: renderer._render_composite_sources(
                    _page(), 1.0, 0, cancelled, True
                ),
                4,
                ["tinted", "tinted", "composite"],
                True,
            ),
            (
                "pdf frame",
                _SignaturePageCache,
                lambda renderer, cancelled: renderer.render_composite_frame(
                    _page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0, cancelled_check=cancelled
                ),
                5,
                ["frame", "tint", "pdf overlay", "frame", "tint"],
                False,
            ),
            (
                "pdf frame sources",
                _SignaturePageCache,
                lambda renderer, cancelled: renderer._render_composite_frame_sources(
                    _page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0, cancelled, True
                ),
                3,
                ["frame", "tint", "pdf overlay", "frame", "tint"],
                True,
            ),
            (
                "raster frame",
                _RasterOverlayPageCache,
                lambda renderer, cancelled: renderer.render_composite_frame(
                    tif_page(),
                    1.0,
                    0.0,
                    0.0,
                    100.0,
                    100.0,
                    0,
                    cancelled_check=cancelled,
                ),
                5,
                ["frame", "tint", "raster overlay", "page", "tint"],
                False,
            ),
            (
                "raster frame sources",
                _RasterOverlayPageCache,
                lambda renderer, cancelled: renderer._render_composite_frame_sources(
                    tif_page(), 1.0, 0.0, 0.0, 100.0, 100.0, 0, cancelled, True
                ),
                4,
                ["frame", "tint", "raster overlay", "page", "tint"],
                True,
            ),
        )
        module = (
            "ost_visualizer.presentation.visualization.pdf.services.composite_renderer"
        )
        for name, make_cache, render, minimum_checks, full_work, direct in scenarios:

            def run(fire_at):
                events = []

                class LoggingCache(make_cache):
                    def get_tinted_page(self, *args, **kwargs):
                        events.append("tinted")
                        return super().get_tinted_page(*args, **kwargs)

                    def get_frame(self, *args, **kwargs):
                        events.append("frame")
                        return super().get_frame(*args, **kwargs)

                    def get_page(self, *args, **kwargs):
                        events.append("page")
                        return super().get_page(*args, **kwargs)

                def logged(label, original):
                    def wrapper(*args, **kwargs):
                        events.append(label)
                        return original(*args, **kwargs)

                    return wrapper

                cache = LoggingCache()
                checks = [0]

                def cancelled():
                    checks[0] += 1
                    if checks[0] == fire_at:
                        events.append("CANCELLED")
                    return fire_at is not None and checks[0] >= fire_at

                with patch.object(
                    CompositeRenderer,
                    "_composite_images",
                    logged("composite", CompositeRenderer._composite_images),
                ), patch.object(
                    CompositeRenderer,
                    "_draw_overlay_pdf_frame",
                    logged("pdf overlay", CompositeRenderer._draw_overlay_pdf_frame),
                ), patch.object(
                    CompositeRenderer,
                    "_draw_overlay_raster_frame",
                    logged(
                        "raster overlay", CompositeRenderer._draw_overlay_raster_frame
                    ),
                ), patch(
                    f"{module}.tint_image",
                    logged("tint", tint_image),
                ):
                    result = render(CompositeRenderer(cache), cancelled)
                return result, checks[0], cache, events

            result, total_checks, _cache, events = run(None)
            image = result[0] if direct else result
            self.assertIsNotNone(image, name)
            if direct:
                self.assertTrue(result[1], name)
            self.assertGreaterEqual(total_checks, minimum_checks, name)
            self.assertEqual(events, full_work, name)
            for fire_at in range(1, total_checks + 1):
                with self.subTest(scenario=name, cancelled_at_check=fire_at):
                    result, _checks, cache, events = run(fire_at)
                    if direct:
                        self.assertEqual(result, (None, False))
                    else:
                        self.assertIsNone(result)
                    self.assertEqual(len(cache._composite_cache), 0)
                    # A fired checkpoint must stop all further rendering work,
                    # not merely leave the final cache check to drop the result.
                    fired_at = events.index("CANCELLED")
                    self.assertEqual(events[fired_at + 1 :], [])
                    self.assertEqual(
                        events[:fired_at], full_work[: len(events[:fired_at])]
                    )

    def test_frame_requests_are_clipped_to_the_page_before_rendering_sources(self):
        for frame, expected in (
            ((-10.0, -10.0, 60.0, 60.0), (0.0, 0.0, 50.0, 50.0)),
            ((80.0, 80.0, 50.0, 50.0), (80.0, 80.0, 20.0, 20.0)),
        ):
            with self.subTest(frame=frame):
                cache = _preferences_support_FakeCompositeFramePageCache()
                image = CompositeRenderer(cache).render_composite_frame(
                    _page(), 2.0, *frame, 0
                )
                self.assertEqual(cache.calls[0], ("base.pdf", 0, 2.0, *expected))
                self.assertEqual(
                    (image.width(), image.height()),
                    (int(expected[2] * 2), int(expected[3] * 2)),
                )
        cache = _preferences_support_FakeCompositeFramePageCache()
        renderer = CompositeRenderer(cache)
        self.assertIsNone(
            renderer.render_composite_frame(_page(), 2.0, 200.0, 200.0, 10.0, 10.0, 0)
        )
        self.assertIsNone(
            renderer.render_composite_frame(
                _page(image_path="base.tif"), 2.0, 0.0, 0.0, 0.0, 10.0, 0
            )
        )
        self.assertEqual(cache.calls, [])

    def test_equivalent_clipped_pdf_frames_share_one_cached_composite(self):
        renderer = CompositeRenderer(_SignaturePageCache())
        page = _page()
        clipped = renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 50.0, 50.0, 0)
        self.assertIsNotNone(clipped)
        # Requests that clip to the same page rectangle must hit one cache entry.
        self.assertIs(
            renderer.render_composite_frame(page, 1.0, -10.0, -10.0, 60.0, 60.0, 0),
            clipped,
        )
        self.assertIsNot(
            renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 51.0, 50.0, 0),
            clipped,
        )
        self.assertIsNone(
            renderer.render_composite_frame(page, 1.0, 200.0, 200.0, 10.0, 10.0, 0)
        )


class CompositeRendererPreferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _preferences_support__app()
        font_directory = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"):
            QtGui.QFontDatabase.addApplicationFont(str(font_directory / filename))

    def tearDown(self):
        self.app.processEvents()

    def test_composite_base_pdf_overlay_uses_stable_overlay_scale(self):
        class FakePageCache(PageCache):
            def __init__(self):
                super().__init__()
                self.calls = []

            def file_signature(self, _file_path):
                return None

            def get_tinted_page(
                self,
                file_path,
                page_index,
                scale,
                rotation,
                tint_rgb,
                wait_for_in_flight=True,
            ):
                del wait_for_in_flight
                self.calls.append((file_path, page_index, scale, rotation, tint_rgb))
                return QtGui.QImage(300, 300, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )
        renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=3.0,
            raster_rotation=0,
        )
        self.assertEqual(page_cache.calls[0][2], 3.0)
        self.assertEqual(
            page_cache.calls[1][2],
            INTERACTIVE_PDF_RENDER_SCALE,
        )

    def test_composite_cache_key_uses_quantized_render_scale(self):
        class FakePageCache(PageCache):
            def __init__(self):
                super().__init__()
                self.calls = []

            def file_signature(self, _file_path):
                return None

            def get_tinted_page(
                self,
                file_path,
                page_index,
                scale,
                rotation,
                tint_rgb,
                wait_for_in_flight=True,
            ):
                del wait_for_in_flight
                self.calls.append((file_path, page_index, scale, rotation, tint_rgb))
                return QtGui.QImage(20, 20, QtGui.QImage.Format.Format_ARGB32)

        page_cache = FakePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
        )
        first = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.2341,
            raster_rotation=0,
        )
        second = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.2342,
            raster_rotation=0,
        )
        self.assertIs(first, second)
        self.assertEqual(len(page_cache.calls), 2)

    def test_composite_visible_frame_renders_base_and_overlay_frames(self):
        page_cache = _preferences_support_FakeCompositeFramePageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(0.0, 0.0, 100.0 / 72.0 * 64.0, 100.0 / 72.0 * 64.0),
        )
        image = renderer.render_composite_frame(
            page,
            scale=4.0,
            frame_x_pts=10.0,
            frame_y_pts=20.0,
            frame_w_pts=30.0,
            frame_h_pts=40.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(
            page_cache.calls[0],
            ("base.pdf", 0, 4.0, 10.0, 20.0, 30.0, 40.0),
        )
        self.assertEqual(
            page_cache.calls[1],
            ("overlay.pdf", 0, 4.0, 10.0, 20.0, 30.0, 40.0),
        )

    def test_composite_visible_frame_scales_overlay_rect_translation(self):
        renderer = CompositeRenderer(
            _preferences_support_FakeOverlayMovementPageCache()
        )
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_preferences_support__first_blue_column(image), 20)

    def test_composite_visible_frame_uses_renderer_rounded_page_origin(self):
        renderer = CompositeRenderer(
            _preferences_support_FakeOverlayMovementPageCache()
        )
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.pdf",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                20.5 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=10.25,
            frame_y_pts=0.0,
            frame_w_pts=40.0,
            frame_h_pts=40.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_preferences_support__first_blue_column(image), 20)

    def test_composite_visible_frame_uses_raster_overlay_frame_mapping(self):
        renderer = CompositeRenderer(
            _preferences_support_FakeOverlayMovementPageCache()
        )
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_preferences_support__first_blue_column(image), 20)

    def test_composite_visible_frame_uses_raster_overlay_rotated_rect_mapping(self):
        renderer = CompositeRenderer(
            _preferences_support_FakeDenseMarkerOverlayMovementPageCache()
        )
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                0.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            overlay_rotation=0.2,
            image_show_mode=2,
        )
        image = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=0.0,
            frame_y_pts=0.0,
            frame_w_pts=100.0,
            frame_h_pts=100.0,
            rotation=0,
        )
        self.assertIsNotNone(image)
        self.assertEqual(_preferences_support__first_blue_column(image), 0)

    def test_composite_visible_frame_tif_overlay_uses_source_mapping_when_frame_is_shifted(
        self,
    ):
        page_cache = _preferences_support_FakeShiftedSourceMarkerTifPageCache()
        renderer = CompositeRenderer(page_cache)
        page = Page(
            uid="page-1",
            name="Page 1",
            image_path="base.pdf",
            overlay_image_path="overlay.tif",
            page_index=0,
            width_pts=100.0,
            height_pts=100.0,
            scale_factor1=0.1875,
            scale_factor2=12.0,
            overlay_rect=(
                10.0 / 72.0 * 64.0,
                0.0,
                100.0 / 72.0 * 64.0,
                100.0 / 72.0 * 64.0,
            ),
            image_show_mode=2,
            overlay_rotation=0.0,
        )
        first_frame = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=20.0,
            frame_y_pts=5.0,
            frame_w_pts=80.0,
            frame_h_pts=80.0,
            rotation=0,
        )
        second_frame = renderer.render_composite_frame(
            page,
            scale=2.0,
            frame_x_pts=40.0,
            frame_y_pts=5.0,
            frame_w_pts=80.0,
            frame_h_pts=80.0,
            rotation=0,
        )
        self.assertIsNotNone(first_frame)
        self.assertIsNotNone(second_frame)
        first_col = _preferences_support__first_blue_column(first_frame)
        second_col = _preferences_support__first_blue_column(second_frame)
        self.assertIsNotNone(first_col)
        self.assertIsNotNone(second_col)
        self.assertLess(second_col, first_col)
        self.assertGreaterEqual(first_col - second_col, 35)
        self.assertLessEqual(first_col - second_col, 45)
        self.assertEqual(page_cache.page_scales, [1.0, 1.0])


class OverlayCoordinateContractTests(unittest.TestCase):
    def test_missing_and_zero_size_rectangles_produce_no_geometry(self):
        missing = _overlay_calibration_support__page(())
        zero_width = _overlay_calibration_support__page((0.0, 0.0, 0.0, 1920.0))
        zero_height = _overlay_calibration_support__page((0.0, 0.0, 2688.0, 0.0))
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        self.assertEqual(missing.overlay_rect_page_points(), (0.0, 0.0, 0.0, 0.0))
        self.assertIsNone(
            renderer._build_overlay_frame_context(
                zero_width, 100.0, 100.0, 1.0, 0.0, 0.0, 100.0, 100.0
            )
        )
        self.assertIsNone(
            renderer._build_overlay_frame_context(
                zero_height, 100.0, 100.0, 1.0, 0.0, 0.0, 100.0, 100.0
            )
        )

    def test_transform_is_forward_translate_rotate_then_scale(self):
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        transform = renderer._build_transform(
            10.0,
            -5.0,
            math.pi / 2.0,
            2.0,
            3.0,
        )
        mapped_origin = transform.map(QPointF(0.0, 0.0))
        mapped_x = transform.map(QPointF(1.0, 0.0))
        mapped_y = transform.map(QPointF(0.0, 1.0))
        self.assertAlmostEqual(mapped_origin.x(), 10.0)
        self.assertAlmostEqual(mapped_origin.y(), -5.0)
        self.assertAlmostEqual(mapped_x.x(), 10.0)
        self.assertAlmostEqual(mapped_x.y(), -3.0)
        self.assertAlmostEqual(mapped_y.x(), 7.0)
        self.assertAlmostEqual(mapped_y.y(), -5.0)

    def test_rotation_and_deskew_are_combined_once(self):
        page = _overlay_calibration_support__page(
            (64.0, 32.0, 640.0, 320.0),
            overlay_rotation=math.pi / 4.0,
            deskew_rotation_overlay=math.pi / 4.0,
        )
        renderer = CompositeRenderer.__new__(CompositeRenderer)
        context = renderer._build_overlay_frame_context(
            page,
            640.0,
            320.0,
            1.0,
            0.0,
            0.0,
            3024.0,
            2160.0,
        )
        self.assertIsNotNone(context)
        mapped = context["transform"].map(QPointF(1.0, 0.0))
        origin = context["transform"].map(QPointF(0.0, 0.0))
        self.assertAlmostEqual(mapped.x(), origin.x())
        self.assertGreater(mapped.y(), origin.y())

    def test_cached_and_uncached_paths_share_one_transform_identity(self):
        renderer = CompositeRenderer(PageCache())
        page_at_64_units = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_64_RECT
        )
        page_at_96_units = _overlay_calibration_support__page(
            _overlay_calibration_support_CALIBRATED_64_RECT,
            scale_factor1=0.125,
            scale_factor2=12.0,
        )
        key = renderer._build_cache_key(page_at_64_units, None, 1.0, 0)
        self.assertEqual(
            key,
            renderer._build_cache_key(page_at_64_units, None, 1.0, 0),
        )
        self.assertNotEqual(
            key,
            renderer._build_cache_key(page_at_96_units, None, 1.0, 0),
        )


from ost_visualizer.presentation.visualization.pdf.services import (
    composite_renderer as composite_module,
)


def _quadrants(width, height):
    """Top-left red, top-right green, bottom-left blue, bottom-right yellow."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    for x in range(width):
        for y in range(height):
            top, left = y < height // 2, x < width // 2
            colour = (
                ((255, 0, 0) if left else (0, 255, 0))
                if top
                else ((0, 0, 255) if left else (255, 255, 0))
            )
            image.setPixelColor(x, y, QColor(*colour))
    return image


def _solid(width, height, colour):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(*colour))
    return image


def _rgb(image, x, y):
    colour = image.pixelColor(x, y)
    return colour.red(), colour.green(), colour.blue()


class _PixelCache(PageCache):
    """Page cache whose sources are fixed images; every request is recorded."""

    def __init__(self, images=None, sizes=None, frames=None):
        super().__init__()
        self.images = images or {}
        self.sizes = sizes or {}
        self.frames = frames or {}
        self.calls = []

    def file_signature(self, _file_path):
        return None

    def get_page(self, path, index, scale, rotation, wait_for_in_flight=True):
        self.calls.append(("page", path, index, scale, rotation, wait_for_in_flight))
        image = self.images.get(path)
        return None if image is None else QImage(image)

    def get_tinted_page(
        self, path, index, scale, rotation, tint_rgb=(255, 80, 80), wait_for_in_flight=True
    ):
        self.calls.append(
            ("tinted", path, index, scale, rotation, tuple(tint_rgb), wait_for_in_flight)
        )
        image = self.images.get(path)
        return None if image is None else QImage(image)

    def get_page_size(self, path, _index):
        return self.sizes.get(path, (0.0, 0.0))

    def get_frame(
        self, path, index, scale, fx, fy, fw, fh, rotation, wait_for_in_flight=True
    ):
        self.calls.append(
            ("frame", path, index, scale, fx, fy, fw, fh, rotation, wait_for_in_flight)
        )
        image = self.frames.get(path)
        return None if image is None else QImage(image)


def _sheet(**overrides):
    """72 pt square sheet calibrated at 64 overlay units per sheet inch."""
    values = dict(
        uid="p",
        name="P",
        image_path="base.pdf",
        overlay_image_path="overlay.pdf",
        width_pts=72.0,
        height_pts=72.0,
        scale_factor1=0.1875,
        scale_factor2=12.0,
        overlay_rect=(16.0, 16.0, 32.0, 16.0),
    )
    values.update(overrides)
    return Page(**values)


class CompositePixelTests(unittest.TestCase):
    """Pixels of the composited canvas and overlay-only canvas (page cache faked)."""

    def renderer(self, **kwargs):
        self.cache = _PixelCache(**kwargs)
        return CompositeRenderer(self.cache)

    def assertColours(self, image, expected):
        for (x, y), colour in expected.items():
            self.assertEqual(_rgb(image, x, y), colour, (x, y))

    def test_composite_requests_the_base_in_red_and_the_overlay_in_blue(self):
        for overlay, expected_scale in (
            ("overlay.pdf", INTERACTIVE_PDF_RENDER_SCALE),
            ("overlay.tif", RASTER_NATIVE_RENDER_SCALE),
        ):
            with self.subTest(overlay=overlay):
                renderer = self.renderer(
                    images={
                        "base.pdf": _solid(216, 216, (0, 200, 0)),
                        overlay: _quadrants(20, 10),
                    }
                )
                renderer.render_composite(
                    _sheet(overlay_image_path=overlay, page_index=3),
                    None,
                    3.0,
                    90,
                    wait_for_in_flight=False,
                )
                self.assertEqual(
                    self.cache.calls,
                    [
                        ("tinted", "base.pdf", 3, 3.0, 90, (255, 80, 80), False),
                        ("tinted", overlay, 0, expected_scale, 90, (80, 80, 255), False),
                    ],
                )

    def test_composite_draws_the_overlay_over_the_base_inside_its_rect_only(self):
        renderer = self.renderer(
            images={
                "base.pdf": _solid(216, 216, (0, 200, 0)),
                "overlay.pdf": _quadrants(20, 10),
            }
        )
        image = renderer.render_composite(_sheet(), None, 3.0, 0)
        self.assertEqual((image.width(), image.height()), (216, 216))
        self.assertColours(
            image,
            {
                (5, 5): (0, 200, 0),
                (200, 200): (0, 200, 0),
                (53, 56): (0, 200, 0),
                (163, 56): (0, 200, 0),
                (56, 109): (0, 200, 0),
                (56, 56): (255, 0, 0),
                (98, 56): (255, 0, 0),
                (118, 56): (0, 255, 0),
                (160, 56): (0, 255, 0),
                (56, 106): (0, 0, 255),
                (118, 106): (255, 255, 0),
                (56, 72): (255, 0, 0),
                (56, 90): (0, 0, 255),
            },
        )

    def test_composite_without_a_base_or_overlay_image_is_not_composed(self):
        renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
        self.assertIsNone(renderer.render_composite(_sheet(), None, 3.0, 0))
        renderer = self.renderer(images={"base.pdf": _solid(216, 216, (0, 200, 0))})
        base_only = renderer.render_composite(_sheet(), None, 3.0, 0)
        self.assertEqual(_rgb(base_only, 100, 100), (0, 200, 0))
        before = len(self.cache.calls)
        renderer.render_composite(_sheet(), None, 3.0, 0)
        # An incomplete composite (no overlay) is never cached.
        self.assertEqual(len(self.cache.calls), 2 * before)

    def test_overlay_only_canvas_is_paper_with_the_overlay_stretched_into_its_rect(self):
        renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
        image = renderer.render_overlay_only(_sheet(), 3.0)
        self.assertEqual((image.width(), image.height()), (216, 216))
        self.assertEqual(image.pixelColor(5, 5).alpha(), 255)
        self.assertColours(
            image,
            {
                (5, 5): (255, 255, 255),
                (53, 56): (255, 255, 255),
                (56, 109): (255, 255, 255),
                (56, 56): (255, 0, 0),
                (160, 56): (0, 255, 0),
                (56, 106): (0, 0, 255),
                (160, 106): (255, 255, 0),
                (56, 72): (255, 0, 0),
                (56, 90): (0, 0, 255),
            },
        )

    def test_overlay_only_requests_the_overlay_tinted_only_when_asked(self):
        renderer = self.renderer(images={"overlay.tif": _quadrants(20, 10)})
        renderer.render_overlay_only(_sheet(overlay_image_path="overlay.tif"), 3.0)
        renderer.render_overlay_only(
            _sheet(overlay_image_path="overlay.tif", uid="q"), 3.0, tint_rgb=[80, 80, 255]
        )
        self.assertEqual(
            self.cache.calls,
            [
                ("page", "overlay.tif", 0, RASTER_NATIVE_RENDER_SCALE, 0, True),
                ("tinted", "overlay.tif", 0, RASTER_NATIVE_RENDER_SCALE, 0, (80, 80, 255), True),
            ],
        )

    def test_overlay_only_canvas_size_rounds_the_scaled_page_and_never_drops_below_a_pixel(
        self,
    ):
        for width, height, scale, expected in (
            (72.4, 10.0, 3.0, (217, 30)),
            (72.6, 10.0, 3.0, (218, 30)),
            (0.1, 0.1, 1.0, (1, 1)),
            (100.0, 40.0, 2.5, (250, 100)),
        ):
            with self.subTest(width=width, height=height, scale=scale):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(4, 4)})
                image = renderer.render_overlay_only(
                    _sheet(width_pts=width, height_pts=height), scale
                )
                self.assertEqual((image.width(), image.height()), expected)

    def test_overlay_only_is_none_without_an_overlay_image(self):
        renderer = self.renderer(images={})
        self.assertIsNone(renderer.render_overlay_only(_sheet(), 3.0))

    def test_overlay_rotates_about_its_rect_origin_and_deskew_adds_to_it(self):
        base = dict(overlay_rect=(40.0, 16.0, 32.0, 16.0))
        expectations = {
            (130, 60): (255, 0, 0),
            (130, 150): (0, 255, 0),
            (90, 60): (0, 0, 255),
            (90, 150): (255, 255, 0),
            (140, 100): (255, 255, 255),
        }
        for label, rotation, deskew in (
            ("overlay rotation", math.pi / 2, 0.0),
            ("deskew", 0.0, math.pi / 2),
            ("split", math.pi / 4, math.pi / 4),
        ):
            with self.subTest(label):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
                image = renderer.render_overlay_only(
                    _sheet(
                        overlay_rotation=rotation,
                        deskew_rotation_overlay=deskew,
                        **base,
                    ),
                    3.0,
                )
                self.assertColours(image, expectations)
        renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
        image = renderer.render_overlay_only(
            _sheet(
                overlay_rect=(48.0, 32.0, 32.0, 16.0),
                overlay_rotation=math.pi / 2,
                deskew_rotation_overlay=math.pi / 2,
            ),
            3.0,
        )
        self.assertColours(image, {(160, 106): (255, 0, 0), (56, 56): (255, 255, 0)})

    def test_a_rotation_of_exactly_one_radian_is_applied(self):
        for rotation, deskew in ((1.0, 0.0), (0.0, 1.0), (0.5, 0.5)):
            with self.subTest(rotation=rotation, deskew=deskew):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
                image = renderer.render_overlay_only(
                    _sheet(overlay_rotation=rotation, deskew_rotation_overlay=deskew),
                    3.0,
                )
                self.assertEqual(_rgb(image, 57, 84), (255, 0, 0))

    def test_overlay_pixels_are_smoothly_interpolated_when_enlarged(self):
        overlay = QImage(2, 1, QImage.Format.Format_ARGB32)
        overlay.setPixelColor(0, 0, QColor(255, 0, 0))
        overlay.setPixelColor(1, 0, QColor(0, 0, 255))
        renderer = self.renderer(images={"overlay.pdf": overlay, "base.pdf": _solid(216, 216, (0, 200, 0))})
        for image in (
            renderer.render_overlay_only(_sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0)), 3.0),
            renderer.render_composite(
                _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0), uid="c"), None, 3.0, 0
            ),
        ):
            row = [_rgb(image, x, 100) for x in range(60, 160)]
            blended = [px for px in row if 0 < px[0] < 255 and 0 < px[2] < 255]
            self.assertGreater(len(blended), 20)

    def test_a_degenerate_rect_leaves_the_canvas_without_an_overlay(self):
        for rect in ((0.0, 0.0, 0.0, 0.0), (16.0, 16.0, 0.0, 16.0), (16.0, 16.0, 16.0, 0.0)):
            with self.subTest(rect=rect):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(20, 10)})
                image = renderer.render_overlay_only(_sheet(overlay_rect=rect), 3.0)
                white = QImage(216, 216, QImage.Format.Format_ARGB32)
                white.fill(QColor(255, 255, 255))
                self.assertEqual(image, white)

    def test_drawing_an_overlay_restores_the_painter_state(self):
        renderer = CompositeRenderer(_PixelCache())
        canvas = QImage(216, 216, QImage.Format.Format_ARGB32)
        canvas.fill(QColor(255, 255, 255))
        painter = QPainter(canvas)
        try:
            renderer._draw_overlay_image(painter, _quadrants(20, 10), _sheet(), 216, 216)
            self.assertTrue(painter.transform().isIdentity())
            renderer._draw_overlay_image(
                painter, QImage(), _sheet(), 216, 216
            )
            self.assertTrue(painter.transform().isIdentity())
        finally:
            painter.end()
        self.assertEqual(_rgb(canvas, 56, 56), (255, 0, 0))
        self.assertEqual(_rgb(canvas, 5, 5), (255, 255, 255))


class CompositeFramePixelTests(unittest.TestCase):
    """Composite frames: what is asked of the cache and what lands where."""

    def setUp(self):
        self.tints = []
        original = composite_module.tint_image

        def recording_tint(image, red, green, blue):
            self.tints.append((red, green, blue))
            return QImage(image)

        patcher = patch.object(composite_module, "tint_image", recording_tint)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.original_tint = original

    def renderer(self, **kwargs):
        self.cache = _PixelCache(**kwargs)
        return CompositeRenderer(self.cache)

    def test_a_pdf_overlay_frame_is_requested_in_the_source_and_drawn_at_its_place(self):
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={
                "base.pdf": _solid(60, 60, (0, 0, 200)),
                "overlay.pdf": _solid(30, 30, (255, 255, 0)),
            },
        )
        page = _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0))
        image = renderer.render_composite_frame(
            page, 2.0, 10.0, 20.0, 30.0, 30.0, 90, wait_for_in_flight=False
        )
        self.assertEqual(
            self.cache.calls,
            [
                ("frame", "base.pdf", 0, 2.0, 10.0, 20.0, 30.0, 30.0, 90, False),
                ("frame", "overlay.pdf", 0, 2.0, 10.0, 20.0, 30.0, 30.0, 90, False),
            ],
        )
        self.assertEqual(self.tints, [(255, 80, 80), (80, 80, 255)])
        self.assertEqual((image.width(), image.height()), (60, 60))
        # The 30 px overlay frame covers the top-left quarter; the base shows elsewhere.
        self.assertEqual(_rgb(image, 5, 5), (255, 255, 0))
        self.assertEqual(_rgb(image, 25, 25), (255, 255, 0))
        self.assertEqual(_rgb(image, 35, 35), (0, 0, 200))
        self.assertEqual(_rgb(image, 55, 5), (0, 0, 200))
        # A complete composite is cached: the same viewport asks nothing new.
        calls = len(self.cache.calls)
        again = renderer.render_composite_frame(
            page, 2.0, 10.0, 20.0, 30.0, 30.0, 90, wait_for_in_flight=False
        )
        self.assertEqual(len(self.cache.calls), calls)
        self.assertEqual(again, image)

    def test_frames_are_clipped_to_the_page_before_anything_is_requested(self):
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={
                "base.pdf": _solid(80, 80, (0, 0, 200)),
                "overlay.pdf": _solid(80, 80, (255, 255, 0)),
            },
        )
        renderer.render_composite_frame(
            _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0)), 2.0, -10.0, -10.0, 50.0, 50.0, 0
        )
        self.assertEqual(
            self.cache.calls[0], ("frame", "base.pdf", 0, 2.0, 0.0, 0.0, 40.0, 40.0, 0, True)
        )
        self.assertEqual(
            self.cache.calls[1], ("frame", "overlay.pdf", 0, 2.0, 0.0, 0.0, 40.0, 40.0, 0, True)
        )

    def test_frames_outside_or_without_area_produce_nothing(self):
        for pdf_base in (True, False):
            for frame in (
                (100.0, 0.0, 10.0, 10.0),
                (0.0, 100.0, 10.0, 10.0),
                (-20.0, 0.0, 10.0, 10.0),
                (0.0, -20.0, 10.0, 10.0),
                (72.0, 0.0, 10.0, 10.0),
                (0.0, 0.0, 0.0, 10.0),
                (0.0, 0.0, 10.0, 0.0),
                (0.0, 0.0, -5.0, 10.0),
            ):
                with self.subTest(pdf_base=pdf_base, frame=frame):
                    renderer = self.renderer(
                        sizes={"overlay.pdf": (72.0, 72.0)},
                        frames={
                            "base.pdf": _solid(20, 20, (0, 0, 200)),
                            "base.tif": _solid(20, 20, (0, 0, 200)),
                            "overlay.pdf": _solid(20, 20, (255, 255, 0)),
                        },
                    )
                    page = _sheet(
                        image_path="base.pdf" if pdf_base else "base.tif",
                        overlay_rect=(0.0, 0.0, 64.0, 64.0),
                    )
                    self.assertIsNone(renderer.render_composite_frame(page, 1.0, *frame, 0))
                    self.assertEqual(self.cache.calls, [])

    def test_a_missing_base_frame_gives_nothing_and_a_missing_overlay_gives_the_base_only(
        self,
    ):
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={"overlay.pdf": _solid(30, 30, (255, 255, 0))},
        )
        page = _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0))
        self.assertIsNone(renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0))
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={"base.pdf": _solid(30, 30, (0, 0, 200))},
        )
        base_only = renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
        self.assertEqual(_rgb(base_only, 15, 15), (0, 0, 200))
        before = len(self.cache.calls)
        renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
        # The overlay-less composite is incomplete and therefore not cached.
        self.assertEqual(len(self.cache.calls), 2 * before)
        self.assertEqual(self.tints.count((80, 80, 255)), 0)

    def test_a_raster_overlay_frame_is_cropped_from_the_source_and_placed_in_its_rect(self):
        renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_image_path="overlay.tif"), 3.0, 0.0, 0.0, 72.0, 72.0, 0
        )
        self.assertEqual(
            self.cache.calls,
            [
                ("frame", "base.pdf", 0, 3.0, 0.0, 0.0, 72.0, 72.0, 0, True),
                ("page", "overlay.tif", 0, RASTER_NATIVE_RENDER_SCALE, 0, True),
            ],
        )
        self.assertEqual(self.tints, [(255, 80, 80), (80, 80, 255)])
        expected = {
            (5, 5): (0, 200, 0),
            (56, 56): (255, 0, 0),
            (160, 56): (0, 255, 0),
            (56, 106): (0, 0, 255),
            (160, 106): (255, 255, 0),
            (53, 56): (0, 200, 0),
            (56, 109): (0, 200, 0),
        }
        for (x, y), colour in expected.items():
            self.assertEqual(_rgb(image, x, y), colour, (x, y))

    def test_a_raster_overlay_without_a_known_size_falls_back_to_the_whole_overlay(self):
        renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (0.0, 0.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        page = _sheet(overlay_image_path="overlay.tif")
        image = renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 90)
        self.assertEqual(
            self.cache.calls[1:],
            [("tinted", "overlay.tif", 0, RASTER_NATIVE_RENDER_SCALE, 90, (80, 80, 255), True)],
        )
        for (x, y), colour in {
            (5, 5): (0, 200, 0),
            (56, 56): (255, 0, 0),
            (160, 106): (255, 255, 0),
        }.items():
            self.assertEqual(_rgb(image, x, y), colour, (x, y))
        # The fallback is not a faithful composite, so it is never cached.
        before = len(self.cache.calls)
        renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 90)
        self.assertEqual(len(self.cache.calls), 2 * before)

    def test_a_fallback_without_the_overlay_image_keeps_the_base(self):
        renderer = self.renderer(
            sizes={"overlay.tif": (0.0, 0.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_image_path="overlay.tif"), 3.0, 0.0, 0.0, 72.0, 72.0, 0
        )
        self.assertEqual(_rgb(image, 100, 100), (0, 200, 0))

    def test_a_shifted_frame_moves_the_fallback_overlay_by_the_frame_origin(self):
        renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (0.0, 0.0)},
            frames={"base.pdf": _solid(108, 108, (0, 200, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_image_path="overlay.tif"), 3.0, 18.0, 18.0, 36.0, 36.0, 0
        )
        # Frame origin (18, 18) pt is the rect's top-left: the red quadrant starts at 0.
        self.assertEqual(_rgb(image, 5, 5), (255, 0, 0))
        self.assertEqual(_rgb(image, 100, 5), (0, 255, 0))
        self.assertEqual(_rgb(image, 5, 100), (0, 200, 0))


def _split_base(width, height, hole=None):
    """Four distinct quadrants; optional fully transparent block (x0, y0, x1, y1)."""
    colours = {
        (True, True): (0, 200, 0),
        (False, True): (0, 0, 200),
        (True, False): (200, 0, 200),
        (False, False): (0, 200, 200),
    }
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    for x in range(width):
        for y in range(height):
            image.setPixelColor(
                x, y, QColor(*colours[(x < width // 2, y < height // 2)])
            )
    if hole is not None:
        x0, y0, x1, y1 = hole
        for x in range(x0, x1):
            for y in range(y0, y1):
                image.setPixelColor(x, y, QColor(0, 0, 0, 0))
    return image


class CompositeEdgeAndCachingTests(unittest.TestCase):
    def setUp(self):
        self.tints = []
        patcher = patch.object(
            composite_module,
            "tint_image",
            lambda image, r, g, b: self.tints.append((r, g, b)) or QImage(image),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def renderer(self, **kwargs):
        self.cache = _PixelCache(**kwargs)
        return CompositeRenderer(self.cache)

    def test_the_base_is_drawn_unshifted_over_a_white_paper_canvas(self):
        base = _split_base(216, 216, hole=(0, 0, 40, 40))
        renderer = self.renderer(
            images={"base.pdf": base, "overlay.pdf": _quadrants(20, 10)}
        )
        image = renderer.render_composite(_sheet(), None, 3.0, 0)
        # Exact seams of the base at x = 108 and y = 108 (outside the overlay rect).
        self.assertEqual(_rgb(image, 107, 200), (200, 0, 200))
        self.assertEqual(_rgb(image, 108, 200), (0, 200, 200))
        self.assertEqual(_rgb(image, 200, 107), (0, 0, 200))
        self.assertEqual(_rgb(image, 200, 108), (0, 200, 200))
        self.assertEqual(_rgb(image, 0, 108), (200, 0, 200))
        self.assertEqual(_rgb(image, 107, 215), (200, 0, 200))
        self.assertEqual(_rgb(image, 215, 215), (0, 200, 200))
        self.assertEqual(_rgb(image, 40, 40), (0, 200, 0))
        self.assertEqual(_rgb(image, 215, 0), (0, 0, 200))
        for point in ((0, 0), (20, 20), (39, 39), (0, 39), (39, 0)):
            colour = image.pixelColor(*point)
            self.assertEqual(
                (colour.red(), colour.green(), colour.blue(), colour.alpha()),
                (255, 255, 255, 255),
                point,
            )

    def test_frames_draw_the_base_unshifted_over_white_paper(self):
        base = _split_base(60, 60, hole=(50, 50, 60, 60))
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={"base.pdf": base, "overlay.pdf": _solid(30, 30, (255, 255, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0)), 2.0, 10.0, 20.0, 30.0, 30.0, 0
        )
        # The overlay frame covers the top-left 30 px square exactly.
        for point in ((0, 0), (29, 29), (29, 0), (0, 29)):
            self.assertEqual(_rgb(image, *point), (255, 255, 0), point)
        for point in ((30, 30), (30, 0), (0, 30), (59, 59)):
            self.assertNotEqual(_rgb(image, *point), (255, 255, 0), point)
        self.assertEqual(_rgb(image, 29, 45), (200, 0, 200))
        self.assertEqual(_rgb(image, 30, 45), (0, 200, 200))
        self.assertEqual(_rgb(image, 45, 29), (0, 0, 200))
        self.assertEqual(_rgb(image, 45, 30), (0, 200, 200))
        self.assertEqual(_rgb(image, 49, 49), (0, 200, 200))
        for point in ((50, 50), (55, 55), (59, 59), (50, 59), (59, 50)):
            colour = image.pixelColor(*point)
            self.assertEqual(
                (colour.red(), colour.green(), colour.blue(), colour.alpha()),
                (255, 255, 255, 255),
                point,
            )
        no_overlay = self.renderer(
            frames={"base.pdf": base}, sizes={"overlay.pdf": (0.0, 0.0)}
        )
        plain = no_overlay.render_composite_frame(
            _sheet(image_path="base.pdf", overlay_image_path=""), 2.0, 10.0, 20.0, 30.0, 30.0, 0
        )
        self.assertEqual(_rgb(plain, 29, 5), (0, 200, 0))
        self.assertEqual(_rgb(plain, 30, 5), (0, 0, 200))
        self.assertEqual(_rgb(plain, 5, 29), (0, 200, 0))
        self.assertEqual(_rgb(plain, 5, 30), (200, 0, 200))
        self.assertEqual(_rgb(plain, 49, 49), (0, 200, 200))
        self.assertEqual(_rgb(plain, 50, 50), (255, 255, 255))

    def test_a_frame_with_an_overlay_path_but_no_overlay_is_not_cached_as_complete(self):
        renderer = self.renderer(frames={"base.pdf": _solid(30, 30, (0, 0, 200))})
        page = _sheet(overlay_image_path="")
        renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
        # Raster-or-PDF base without any overlay path: nothing to compose, so
        # the frame is incomplete and not cached.
        before = len(self.cache.calls)
        renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
        self.assertEqual(len(self.cache.calls), 2 * before)

    def test_frames_over_a_raster_base_are_composed_directly_and_never_cached(self):
        for overlay in ("overlay.pdf", "overlay.tif"):
            with self.subTest(overlay=overlay):
                renderer = self.renderer(
                    sizes={overlay: (72.0, 72.0)},
                    images={overlay: _solid(72, 72, (255, 255, 0))},
                    frames={
                        "base.tif": _solid(30, 30, (0, 0, 200)),
                        overlay: _solid(30, 30, (255, 255, 0)),
                    },
                )
                page = _sheet(
                    image_path="base.tif",
                    overlay_image_path=overlay,
                    overlay_rect=(0.0, 0.0, 64.0, 64.0),
                )
                image = renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
                self.assertIsNotNone(image)
                before = len(self.cache.calls)
                renderer.render_composite_frame(page, 1.0, 0.0, 0.0, 30.0, 30.0, 0)
                self.assertEqual(len(self.cache.calls), 2 * before)

    def test_overlay_only_canvases_of_nearby_scales_are_cached_separately(self):
        # Each page has one dimension that stays one pixel at both scales, so the
        # other dimension alone must tell the two canvases apart in the cache.
        for width, height, expected in (
            (10.0, 0.01, [(100, 1), (104, 1)]),
            (0.01, 10.0, [(1, 100), (1, 104)]),
        ):
            with self.subTest(width=width, height=height):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(4, 4)})
                page = _sheet(
                    width_pts=width, height_pts=height, overlay_rect=(0.0, 0.0, 8.0, 8.0)
                )
                sizes = []
                for scale in (10.0, 10.4):
                    image = renderer.render_overlay_only(page, scale)
                    sizes.append((image.width(), image.height()))
                self.assertEqual(sizes, expected)

    def test_frames_touching_the_page_edge_have_no_area(self):
        renderer = self.renderer(
            sizes={"overlay.pdf": (72.0, 72.0)},
            frames={"base.pdf": _solid(20, 20, (0, 0, 200)), "overlay.pdf": _solid(20, 20, (255, 255, 0))},
        )
        page = _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0))
        for frame in (
            (-10.0, 0.0, 10.0, 10.0),
            (0.0, -10.0, 10.0, 10.0),
            (72.0, 0.0, 10.0, 10.0),
            (0.0, 72.0, 10.0, 10.0),
        ):
            with self.subTest(frame=frame):
                self.assertIsNone(renderer.render_composite_frame(page, 1.0, *frame, 0))
        self.assertEqual(self.cache.calls, [])

    def test_overlay_frames_outside_the_overlay_rect_are_not_requested(self):
        page = _sheet(overlay_rect=(0.0, 0.0, 16.0, 16.0))
        # (frame, description): beyond the rect in x only, in y only, or in both.
        for frame in (
            (40.0, 40.0, 20.0, 20.0),
            (30.0, 5.0, 10.0, 8.0),
            (5.0, 30.0, 8.0, 10.0),
        ):
            with self.subTest(frame=frame):
                renderer = self.renderer(
                    sizes={"overlay.pdf": (72.0, 72.0)},
                    frames={
                        "base.pdf": _solid(20, 20, (0, 0, 200)),
                        "overlay.pdf": _solid(20, 20, (255, 255, 0)),
                    },
                )
                image = renderer.render_composite_frame(page, 1.0, *frame, 0)
                self.assertEqual([call[1] for call in self.cache.calls], ["base.pdf"])
                self.assertEqual(_rgb(image, 3, 3), (0, 0, 200))
                # No overlay was drawn, so the frame is incomplete and not cached.
                renderer.render_composite_frame(page, 1.0, *frame, 0)
                self.assertEqual(len(self.cache.calls), 2)

    def test_overlay_frames_scale_with_the_overlay_to_page_ratio(self):
        # A 144 pt source squeezed into the 72 pt rect: half size, so a 2x frame
        # needs the overlay rendered at 1x, over a source window of 2x the frame.
        renderer = self.renderer(
            sizes={"overlay.pdf": (144.0, 144.0)},
            frames={"base.pdf": _solid(60, 60, (0, 0, 200)), "overlay.pdf": _solid(60, 60, (255, 255, 0))},
        )
        page = _sheet(overlay_rect=(0.0, 0.0, 64.0, 64.0))
        renderer.render_composite_frame(page, 2.0, 10.0, 20.0, 30.0, 30.0, 0)
        self.assertEqual(
            self.cache.calls[1],
            ("frame", "overlay.pdf", 0, 1.0, 20.0, 40.0, 60.0, 60.0, 0, True),
        )

    def test_degenerate_overlay_sizes_fall_back_instead_of_dividing_by_zero(self):
        for size in ((0.0, 200.0), (200.0, 0.0), (-1.0, 200.0), (200.0, -1.0)):
            with self.subTest(size=size):
                renderer = self.renderer(
                    images={"overlay.tif": _quadrants(200, 200)},
                    sizes={"overlay.tif": size},
                    frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
                )
                image = renderer.render_composite_frame(
                    _sheet(overlay_image_path="overlay.tif"), 3.0, 0.0, 0.0, 72.0, 72.0, 0
                )
                self.assertEqual(_rgb(image, 56, 56), (255, 0, 0))
        for rect in ((16.0, 16.0, 0.0, 16.0), (16.0, 16.0, 16.0, 0.0)):
            with self.subTest(rect=rect):
                renderer = self.renderer(
                    images={"overlay.tif": _quadrants(200, 200)},
                    sizes={"overlay.tif": (200.0, 200.0)},
                    frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
                )
                image = renderer.render_composite_frame(
                    _sheet(overlay_image_path="overlay.tif", overlay_rect=rect),
                    3.0, 0.0, 0.0, 72.0, 72.0, 0,
                )
                self.assertEqual(_rgb(image, 100, 100), (0, 200, 0))

    def test_a_raster_sub_frame_matches_the_same_region_of_the_full_page(self):
        def frames():
            return {"base.pdf": _solid(216, 216, (0, 200, 0))}

        full_renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames=frames(),
        )
        page = _sheet(overlay_image_path="overlay.tif")
        full = full_renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 0)
        sub_renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(108, 108, (0, 200, 0))},
        )
        sub = sub_renderer.render_composite_frame(page, 3.0, 18.0, 18.0, 36.0, 36.0, 0)
        # Sub-frame origin is (54, 54) px of the full page; the seams of the
        # overlay quadrants lie at x = 108 and y = 81 there.
        for x, y in ((2, 2), (50, 2), (58, 2), (100, 2), (2, 24), (2, 30), (50, 40), (58, 40), (100, 50)):
            self.assertEqual(_rgb(sub, x, y), _rgb(full, x + 54, y + 54), (x, y))
        self.assertEqual(_rgb(sub, 50, 20), (255, 0, 0))
        self.assertEqual(_rgb(sub, 58, 20), (0, 255, 0))
        self.assertEqual(_rgb(sub, 50, 40), (0, 0, 255))
        self.assertEqual(_rgb(sub, 58, 40), (255, 255, 0))

    def test_a_raster_overlay_frame_equals_the_overlay_only_canvas_inside_the_rect(self):
        overlay = _quadrants(200, 200)
        page = _sheet(overlay_image_path="overlay.tif")
        frame_renderer = self.renderer(
            images={"overlay.tif": overlay},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        frame = frame_renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 0)
        canvas_renderer = self.renderer(images={"overlay.tif": overlay})
        canvas = canvas_renderer.render_overlay_only(page, 3.0)
        # Rect = canvas px x 54..162, y 54..108. Inside it (one pixel in from the
        # rect's own antialiased edge) the two canvases must agree pixel for pixel;
        # just outside it the frame shows the base and the canvas shows paper.
        for x in range(55, 161):
            for y in range(55, 107):
                self.assertEqual(_rgb(frame, x, y), _rgb(canvas, x, y), (x, y))
        self.assertEqual(_rgb(frame, 52, 80), (0, 200, 0))
        self.assertEqual(_rgb(canvas, 52, 80), (255, 255, 255))

    def test_a_raster_overlay_that_cannot_be_loaded_leaves_an_incomplete_frame(self):
        renderer = self.renderer(
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        page = _sheet(overlay_image_path="overlay.tif")
        image = renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 0)
        self.assertEqual(_rgb(image, 100, 80), (0, 200, 0))
        before = len(self.cache.calls)
        renderer.render_composite_frame(page, 3.0, 0.0, 0.0, 72.0, 72.0, 0)
        self.assertEqual(len(self.cache.calls), 2 * before)

    def test_overlay_page_sizes_are_looked_up_for_page_zero(self):
        sizes = []
        for overlay in ("overlay.pdf", "overlay.tif"):
            renderer = self.renderer(
                images={overlay: _quadrants(200, 200)},
                sizes={overlay: (72.0, 72.0)},
                frames={"base.pdf": _solid(60, 60, (0, 0, 200)), overlay: _solid(60, 60, (255, 255, 0))},
            )
            original = self.cache.get_page_size
            self.cache.get_page_size = lambda path, index, original=original: (
                sizes.append((path, index)) or original(path, index)
            )
            renderer.render_composite_frame(
                _sheet(overlay_image_path=overlay, overlay_rect=(0.0, 0.0, 64.0, 64.0)),
                1.0, 0.0, 0.0, 30.0, 30.0, 0,
            )
        self.assertEqual(sizes, [("overlay.pdf", 0), ("overlay.tif", 0)])

    def test_a_rotated_overlay_has_antialiased_edges_over_the_base(self):
        renderer = self.renderer(
            images={
                "base.pdf": _solid(216, 216, (0, 200, 0)),
                "overlay.pdf": _solid(20, 20, (255, 0, 0)),
            }
        )
        image = renderer.render_composite(_sheet(overlay_rotation=0.5), None, 3.0, 0)
        blended = {
            _rgb(image, x, y)
            for x in range(216)
            for y in range(216)
            if _rgb(image, x, y) not in ((0, 200, 0), (255, 0, 0))
        }
        self.assertGreater(len(blended), 20)

    def test_a_raster_overlay_frame_crops_exactly_the_visible_source_window(self):
        recorded = []
        real_copy_region = composite_module.copy_region

        def recording_copy(image, left, top, width, height):
            recorded.append((left, top, width, height))
            return real_copy_region(image, left, top, width, height)

        # Rect = page pt x 18..54, y 18..36 over a 200 x 200 px source.
        for frame, expected in (
            ((0.0, 0.0, 72.0, 72.0), (0, 0, 200, 200)),
            ((18.0, 18.0, 36.0, 36.0), (0, 0, 200, 200)),
            ((36.0, 18.0, 18.0, 18.0), (100, 0, 100, 200)),
            ((18.0, 27.0, 36.0, 9.0), (0, 100, 200, 100)),
            ((27.0, 27.0, 9.0, 9.0), (50, 100, 50, 100)),
        ):
            with self.subTest(frame=frame):
                recorded.clear()
                renderer = self.renderer(
                    images={"overlay.tif": _quadrants(200, 200)},
                    sizes={"overlay.tif": (200.0, 200.0)},
                    frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
                )
                with patch.object(composite_module, "copy_region", recording_copy):
                    renderer.render_composite_frame(
                        _sheet(overlay_image_path="overlay.tif"), 3.0, *frame, 0
                    )
                self.assertEqual(recorded, [expected])

    def test_an_enlarged_raster_overlay_frame_is_smoothly_interpolated(self):
        overlay = QImage(2, 1, QImage.Format.Format_ARGB32)
        overlay.setPixelColor(0, 0, QColor(255, 0, 0))
        overlay.setPixelColor(1, 0, QColor(0, 0, 255))
        renderer = self.renderer(
            images={"overlay.tif": overlay},
            sizes={"overlay.tif": (2.0, 1.0)},
            frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_image_path="overlay.tif", overlay_rect=(0.0, 0.0, 64.0, 64.0)),
            3.0, 0.0, 0.0, 72.0, 72.0, 0,
        )
        row = [_rgb(image, x, 100) for x in range(60, 160)]
        self.assertGreater(len([px for px in row if 0 < px[0] < 255 and 0 < px[2] < 255]), 20)

    def test_one_pixel_wide_or_tall_overlays_are_drawn_by_the_canvas_and_the_composite(
        self,
    ):
        tall = QImage(1, 2, QImage.Format.Format_ARGB32)
        tall.setPixelColor(0, 0, QColor(255, 0, 0))
        tall.setPixelColor(0, 1, QColor(0, 0, 255))
        wide = QImage(2, 1, QImage.Format.Format_ARGB32)
        wide.setPixelColor(0, 0, QColor(255, 0, 0))
        wide.setPixelColor(1, 0, QColor(0, 0, 255))
        for label, overlay, probes in (
            ("1x2", tall, {(100, 60): (255, 0, 0), (100, 100): (0, 0, 255)}),
            ("2x1", wide, {(60, 80): (255, 0, 0), (160, 80): (0, 0, 255)}),
        ):
            with self.subTest(label):
                renderer = self.renderer(
                    images={"overlay.pdf": overlay, "base.pdf": _solid(216, 216, (0, 200, 0))}
                )
                canvas = renderer.render_overlay_only(_sheet(), 3.0)
                composite = renderer.render_composite(_sheet(uid="c"), None, 3.0, 0)
                for image in (canvas, composite):
                    for point, colour in probes.items():
                        self.assertEqual(_rgb(image, *point), colour, (label, point))

    def test_overlay_only_canvases_of_one_and_two_pixels_do_not_share_a_cache_entry(self):
        for width, height, expected in (
            (1.0, 0.01, [(1, 1), (2, 1)]),
            (0.01, 1.0, [(1, 1), (1, 2)]),
        ):
            with self.subTest(width=width, height=height):
                renderer = self.renderer(images={"overlay.pdf": _quadrants(4, 4)})
                page = _sheet(
                    width_pts=width, height_pts=height, overlay_rect=(0.0, 0.0, 8.0, 8.0)
                )
                sizes = []
                for scale in (1.0, 2.0):
                    image = renderer.render_overlay_only(page, scale)
                    sizes.append((image.width(), image.height()))
                self.assertEqual(sizes, expected)

    def test_a_one_pixel_wide_visible_source_window_is_still_drawn(self):
        # Frame x 27.018..27.118 pt is source x 50.1..50.66 px of the 200 px source:
        # a single source column, in the red (upper-left) quadrant at rows 22..
        renderer = self.renderer(
            images={"overlay.tif": _quadrants(200, 200)},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(1, 6, (0, 200, 0))},
        )
        image = renderer.render_composite_frame(
            _sheet(overlay_image_path="overlay.tif"), 3.0, 27.018, 20.0, 0.1, 2.0, 0
        )
        colours = {_rgb(image, 0, y) for y in range(image.height())}
        self.assertIn((255, 0, 0), colours)
        self.assertNotIn((0, 200, 0), colours)

    def test_a_source_window_beyond_the_decoded_image_leaves_an_incomplete_frame(self):
        # The size lookup says 200x200 but only 100x100 pixels were decoded, so
        # the right half of the rect has no pixels to crop.
        renderer = self.renderer(
            images={"overlay.tif": _quadrants(100, 100)},
            sizes={"overlay.tif": (200.0, 200.0)},
            frames={"base.pdf": _solid(30, 30, (0, 200, 0))},
        )
        page = _sheet(overlay_image_path="overlay.tif")
        image = renderer.render_composite_frame(page, 3.0, 40.0, 20.0, 10.0, 10.0, 0)
        self.assertEqual(_rgb(image, 15, 15), (0, 200, 0))
        before = len(self.cache.calls)
        renderer.render_composite_frame(page, 3.0, 40.0, 20.0, 10.0, 10.0, 0)
        self.assertEqual(len(self.cache.calls), 2 * before)

    def test_the_raster_crop_scales_the_source_window_by_the_native_render_scale(self):
        recorded = []
        real_copy_region = composite_module.copy_region

        def recording_copy(image, left, top, width, height):
            recorded.append((left, top, width, height))
            return real_copy_region(image, left, top, width, height)

        with patch.object(composite_module, "RASTER_NATIVE_RENDER_SCALE", 2.0):
            for frame, expected in (
                ((36.0, 18.0, 18.0, 18.0), (200, 0, 200, 400)),
                ((18.0, 27.0, 36.0, 9.0), (0, 200, 400, 200)),
                ((27.0, 27.0, 9.0, 9.0), (100, 200, 100, 200)),
            ):
                with self.subTest(frame=frame):
                    recorded.clear()
                    renderer = self.renderer(
                        images={"overlay.tif": _quadrants(400, 400)},
                        sizes={"overlay.tif": (200.0, 200.0)},
                        frames={"base.pdf": _solid(216, 216, (0, 200, 0))},
                    )
                    with patch.object(composite_module, "copy_region", recording_copy):
                        renderer.render_composite_frame(
                            _sheet(overlay_image_path="overlay.tif"), 3.0, *frame, 0
                        )
                    self.assertEqual(recorded, [expected])
                    self.assertIn(
                        ("page", "overlay.tif", 0, 2.0, 0, True), self.cache.calls
                    )
