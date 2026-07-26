import os
import threading
import unittest
from collections import OrderedDict
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter

from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)


def _image(width=20, height=20):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    return image


def _page():
    return Page(
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


class _FramePageCache:
    def get_tinted_page(self, *_args, **_kwargs):
        return _image()

    def get_frame(self, *_args, **_kwargs):
        return _image()

    def get_page_size(self, _file_path, _page_index):
        return 100.0, 100.0


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
        return None

    def drawImage(self, *_args):
        raise RuntimeError("draw failed")

    def end(self):
        self.ended = True


class CompositeRendererTests(unittest.TestCase):
    def test_cache_clear_cannot_interleave_with_cache_hit(self):
        renderer = CompositeRenderer(_FramePageCache())
        page = _page()
        cache_key = renderer._build_cache_key(page, None, 1.0, 0)
        entered = threading.Event()
        release = threading.Event()
        cache = _BlockingContainsDict(entered, release)
        cached_image = _image()
        cache[cache_key] = cached_image
        renderer._composite_cache = cache
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
        renderer._composite_cache[cache_key] = _image()

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
        cancellation_checks = 0

        def cancelled():
            nonlocal cancellation_checks
            cancellation_checks += 1
            return cancellation_checks >= 4

        result = renderer.render_composite(
            page,
            bid_ref=None,
            render_scale=1.0,
            raster_rotation=0,
            cancelled_check=cancelled,
        )

        cache_key = renderer._build_cache_key(page, None, 1.0, 0)
        self.assertIsNone(result)
        self.assertNotIn(cache_key, renderer._composite_cache)
        self.assertEqual(cancellation_checks, 4)

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
