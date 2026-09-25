import os
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.renderers.page_renderer import (
    PageRenderer,
)
from ost_visualizer.presentation.visualization.pdf.services.composite_renderer import (
    CompositeRenderer,
)
from ost_visualizer.presentation.visualization.utils.source_signature import (
    invalidate_source_files,
)
from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter


class RasterViewportCompositionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.original_path = str(Path(self.directory.name) / "original.pdf")
        self.overlay_path = str(Path(self.directory.name) / "overlay.tif")
        writer = QPdfWriter(self.original_path)
        writer.setResolution(72)
        writer.setPageSize(QPageSize(QSizeF(100, 100), QPageSize.Unit.Point))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        painter = QPainter(writer)
        painter.fillRect(QRectF(0, 0, 100, 100), QColor("red"))
        painter.end()
        del writer
        self.write_image(self.overlay_path, "blue")
        self.cache = PageCache()
        self.addCleanup(self.cache.clear)
        self.page = Page(
            uid="page",
            name="Sheet",
            image_path=self.original_path,
            overlay_image_path=self.overlay_path,
            width_pts=100,
            height_pts=100,
            scale_factor1=1,
            scale_factor2=72,
            overlay_rect=(0, 0, 100, 100),
            image_show_mode=2,
        )
        self.first = CompositeRenderer(self.cache)
        self.second = CompositeRenderer(self.cache)

    def write_image(self, path, color):
        image = QImage(100, 100, QImage.Format.Format_RGB32)
        image.fill(QColor(color))
        image.setDotsPerMeterX(2835)
        image.setDotsPerMeterY(2835)
        self.assertTrue(image.save(path))

    def render(
        self,
        renderer=None,
        page=None,
        *,
        scale=1.0,
        x=0.0,
        width=100.0,
        cancelled=None,
        rotation=0
    ):
        return (renderer or self.first).render_composite_frame(
            page or self.page,
            scale,
            x,
            0.0,
            width,
            100.0,
            rotation,
            cancelled_check=cancelled,
        )

    def test_matching_consumers_reuse_raster_composition_and_source_loads(self):
        with patch.object(
            CompositeRenderer,
            "_draw_overlay_raster_frame",
            autospec=True,
            side_effect=CompositeRenderer._draw_overlay_raster_frame,
        ) as compose, patch.object(
            PageRenderer,
            "_render_image",
            autospec=True,
            side_effect=PageRenderer._render_image,
        ) as load:
            first = self.render()
            self.assertIsNotNone(first)
            loads = load.call_count
            second = self.render(self.second)
            self.assertEqual(first, second)
            self.assertEqual(load.call_count, loads)
            self.assertEqual(compose.call_count, 1)
            self.assertIs(self.render(CompositeRenderer(self.cache)), first)

    def test_revision_replacement_preserves_metadata_but_changes_pixels(self):
        before = self.render()
        stat = os.stat(self.overlay_path)
        self.write_image(self.overlay_path, "green")
        self.assertEqual(os.stat(self.overlay_path).st_size, stat.st_size)
        os.utime(self.overlay_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        invalidate_source_files([self.overlay_path])
        after = self.render(self.second)
        self.assertNotEqual(before, after)
        self.assertIs(self.render(), after)

    def test_frame_inputs_invalidate_but_downstream_effects_do_not(self):
        for changes in (
            {"overlay_rect": (20, 20, 60, 60)},
            {"overlay_rotation": 0.2},
            {"deskew_rotation_overlay": 0.2},
            {"scale_factor2": 144},
            {"width_pts": 200},
            {"height_pts": 200},
            {"layer_visible": False},
        ):
            with self.subTest(changes=changes):
                before = self.render()
                after = self.render(page=replace(self.page, **changes))
                self.assertIsNot(before, after)
        before = self.render()
        self.assertIs(
            self.render(page=replace(self.page, invert=True, bitonal=True)), before
        )
        self.assertIsNot(self.render(scale=2.0), before)
        self.assertIsNot(self.render(rotation=90), before)
        self.assertIsNot(self.render(x=10, width=50), before)
        self.cache.clear_composites()
        self.assertIsNot(self.render(), before)

    def test_missing_overlay_and_metadata_fallback_are_not_cached(self):
        with patch.object(self.cache, "get_page", return_value=None):
            fallback = self.render()
        self.assertIsNotNone(fallback)
        self.assertEqual(len(self.cache._composite_cache), 0)
        recovered = self.render()
        self.assertNotEqual(fallback, recovered)
        self.cache.clear_composites()
        with patch.object(self.cache, "get_page_size", return_value=(0, 0)):
            self.assertIsNotNone(self.render())
        self.assertEqual(len(self.cache._composite_cache), 0)
        unknown = replace(
            self.page, overlay_image_path=str(Path(self.directory.name) / "missing.xyz")
        )
        self.assertIsNotNone(self.render(page=unknown))
        self.assertEqual(len(self.cache._composite_cache), 0)

    def test_concurrent_raster_consumers_share_work_and_cancel_independently(self):
        for cancel_owner in (False, True):
            with self.subTest(cancel_owner=cancel_owner):
                self.cache.clear_composites()
                entered, waiting, release, cancelled = [
                    threading.Event() for _ in range(4)
                ]
                results = {}
                draw = self.first._draw_overlay_raster_frame
                wait = self.cache._in_flight_condition.wait

                def blocked(*args):
                    entered.set()
                    if not release.wait(2):
                        raise AssertionError("Raster composition was not released")
                    return draw(*args)

                def observe_wait(*args, **kwargs):
                    waiting.set()
                    return wait(*args, **kwargs)

                def first():
                    results["first"] = self.render(
                        self.first, cancelled=cancelled.is_set
                    )

                def second():
                    results["second"] = self.render(self.second)

                with patch.object(
                    self.first, "_draw_overlay_raster_frame", side_effect=blocked
                ), patch.object(
                    self.second,
                    "_draw_overlay_raster_frame",
                    wraps=self.second._draw_overlay_raster_frame,
                ) as other_draw, patch.object(
                    self.cache._in_flight_condition, "wait", side_effect=observe_wait
                ):
                    threads = [
                        threading.Thread(target=first),
                        threading.Thread(target=second),
                    ]
                    threads[0].start()
                    try:
                        self.assertTrue(entered.wait(1))
                        threads[1].start()
                        self.assertTrue(waiting.wait(1))
                        if cancel_owner:
                            cancelled.set()
                    finally:
                        release.set()
                        for thread in threads:
                            if thread.ident is not None:
                                thread.join(2)
                    self.assertEqual(other_draw.call_count, int(cancel_owner))
                self.assertIsNotNone(results["second"])
                if cancel_owner:
                    self.assertIsNone(results["first"])
                else:
                    self.assertIs(results["first"], results["second"])

    def test_old_raster_completion_cannot_replace_new_source(self):
        entered, release = threading.Event(), threading.Event()
        results = []
        draw = self.first._draw_overlay_raster_frame

        def blocked(*args):
            entered.set()
            if not release.wait(2):
                raise AssertionError("Raster composition was not released")
            return draw(*args)

        with patch.object(
            self.first, "_draw_overlay_raster_frame", side_effect=blocked
        ):
            thread = threading.Thread(target=lambda: results.append(self.render()))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.write_image(self.overlay_path, "green")
                invalidate_source_files([self.overlay_path])
                accepted = self.render(self.second)
            finally:
                release.set()
                thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [None])
        self.assertIs(self.render(CompositeRenderer(self.cache)), accepted)

    def test_partial_and_unknown_sources_retry_without_compositing(self):
        for suffix in ("tif", "xyz"):
            with self.subTest(suffix=suffix):
                self.cache.clear()
                missing = str(Path(self.directory.name) / ("missing." + suffix))
                if suffix == "xyz":
                    Path(missing).write_bytes(Path(self.overlay_path).read_bytes())
                page = replace(self.page, overlay_image_path=missing)
                with patch.object(
                    CompositeRenderer,
                    "_composite_images",
                    autospec=True,
                    side_effect=CompositeRenderer._composite_images,
                ) as compose, patch.object(
                    PageRenderer,
                    "_render_pdf",
                    autospec=True,
                    side_effect=PageRenderer._render_pdf,
                ) as raster, patch.object(
                    PageRenderer,
                    "_render_image",
                    autospec=True,
                    side_effect=PageRenderer._render_image,
                ) as decode:
                    first = self.first.render_composite(page, None, 1.0, 0)
                    second = self.second.render_composite(page, None, 1.0, 0)
                    self.assertIsNotNone(first)
                    self.assertEqual(first, second)
                    self.assertEqual(compose.call_count, 0)
                    self.assertEqual(raster.call_count, 1)
                    self.assertEqual(decode.call_count, 0)
                    self.assertEqual(len(self.cache._composite_cache), 0)
                if suffix == "tif":
                    self.write_image(missing, "green")
                    recovered = self.second.render_composite(page, None, 1.0, 0)
                    self.assertNotEqual(first, recovered)

    def test_raster_metadata_fallback_reuses_decoded_overlay(self):
        with patch.object(
            self.cache, "get_page_size", return_value=(0, 0)
        ), patch.object(
            CompositeRenderer,
            "_draw_overlay_raster_fallback",
            autospec=True,
            side_effect=CompositeRenderer._draw_overlay_raster_fallback,
        ) as fallback, patch.object(
            PageRenderer,
            "_render_image",
            autospec=True,
            side_effect=PageRenderer._render_image,
        ) as decode, patch.object(
            PageRenderer,
            "render_frame",
            autospec=True,
            side_effect=PageRenderer.render_frame,
        ) as raster:
            first = self.render()
            second = self.render(self.second)
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertEqual(fallback.call_count, 2)
            self.assertEqual(decode.call_count, 1)
            self.assertEqual(raster.call_count, 1)
            self.assertEqual(len(self.cache._composite_cache), 0)
        self.assertIsNotNone(self.render())
        self.assertEqual(len(self.cache._composite_cache), 1)

    def test_overlay_only_missing_source_retries_before_allocating_canvas(self):
        missing = str(Path(self.directory.name) / "later.tif")
        page = replace(self.page, overlay_image_path=missing)
        with patch.object(
            CompositeRenderer,
            "_draw_overlay_image",
            autospec=True,
            side_effect=CompositeRenderer._draw_overlay_image,
        ) as draw:
            self.assertIsNone(self.first.render_overlay_only(page, 1.0))
            self.assertIsNone(self.second.render_overlay_only(page, 1.0))
            self.assertEqual(draw.call_count, 0)
            self.assertEqual(len(self.cache._composite_cache), 0)
            self.write_image(missing, "green")
            recovered = self.first.render_overlay_only(page, 1.0)
            self.assertIsNotNone(recovered)
            self.assertIs(self.second.render_overlay_only(page, 1.0), recovered)
            self.assertEqual(draw.call_count, 1)

    def test_same_page_uid_in_other_database_does_not_reuse_wrong_pixels(self):
        from ost_visualizer.domain.entities.identity_refs import BidRef

        first_ref = BidRef("first.mdb", "bid")
        second_ref = BidRef("second.mdb", "bid")
        first = self.first.render_composite(self.page, first_ref, 1.0, 0)
        other_path = str(Path(self.directory.name) / "other.tif")
        self.write_image(other_path, "green")
        other_page = replace(self.page, overlay_image_path=other_path)
        other = self.second.render_composite(other_page, second_ref, 1.0, 0)
        self.assertNotEqual(first, other)
        self.assertIs(self.first.render_composite(self.page, first_ref, 1.0, 0), first)
        self.assertNotEqual(self.render(), self.render(page=other_page))
        self.assertNotEqual(
            self.first.render_overlay_only(self.page, 1.0),
            self.second.render_overlay_only(other_page, 1.0),
        )
