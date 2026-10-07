import os
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.domain.entities.takeoff import Takeoff
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority
from ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
    RenderRequest,
)
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

_SERVICE_LOGGER = (
    "ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service"
)


def _solid_image(color, size=10):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    return image


class FakeImageRenderer:
    def __init__(self):
        self.calls = []

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.calls.append((file_path, page_index, scale, rotation, native_cancel_token))
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(0)
        return image


class SolidRenderer:
    """Native renderer fake: records calls and returns opaque red images."""

    def __init__(self, fail=False, error=None):
        self.fail = fail
        self.error = error
        self.page_calls = []
        self.frame_calls = []

    def _result(self):
        if self.error is not None:
            raise self.error
        return None if self.fail else _solid_image("red")

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.page_calls.append((file_path, page_index, scale, rotation))
        return self._result()

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
            (file_path, page_index, scale, frame_x_pts, frame_y_pts, frame_w_pts)
        )
        return self._result()

    def get_page_info(self, file_path, page_index):
        return {"width": 612.0, "path": file_path, "index": page_index}

    def extract_text_runs(self, file_path, page_index):
        return [{"text": "run", "path": file_path}]


class BlockingRenderer(SolidRenderer):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.page_calls.append((file_path, page_index, scale, rotation))
        self.started.set()
        self.release.wait(timeout=3.0)
        return _solid_image("red")

    def render_frame(self, *args, native_cancel_token=None):
        self.frame_calls.append(args[:6])
        self.started.set()
        self.release.wait(timeout=3.0)
        return _solid_image("red")


def _pump_until(app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    return predicate()


class PdfRenderingRequestLifecycleTests(unittest.TestCase):
    def test_scale_and_rotation_use_distinct_cache_entries(self):
        cache = PageCache()
        renderer = FakeImageRenderer()
        cache._get_renderer = lambda: renderer
        cache.get_page("p1.pdf", 0, 2.0, 0)
        cache.get_page("p1.pdf", 0, 3.0, 0)
        cache.get_page("p1.pdf", 0, 2.0, 90)
        cache.get_page("p1.pdf", 0, 2.0, 0)
        self.assertEqual(
            renderer.calls,
            [
                ("p1.pdf", 0, 2.0, 0, None),
                ("p1.pdf", 0, 3.0, 0, None),
                ("p1.pdf", 0, 2.0, 90, None),
            ],
        )

    def test_required_and_visible_frame_renders_reuse_matching_in_flight_cache_keys(
        self,
    ):
        app = QApplication.instance() or QApplication([])
        renderer = BlockingRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        service = PDFRenderingService(cache, num_workers=2)
        results = {}

        def collector(name):
            return lambda result: results.__setitem__(name, result)

        try:
            service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.75,
                rotation=0,
                callback=collector("prefetch"),
                priority=RenderPriority.NEARBY_PREFETCH,
            )
            self.assertTrue(renderer.started.wait(timeout=2.0))
            service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.75,
                rotation=0,
                callback=collector("required"),
                priority=RenderPriority.REQUIRED_PAGE,
            )
            renderer.release.set()
            self.assertTrue(
                _pump_until(app, lambda: {"prefetch", "required"} <= set(results))
            )
            self.assertTrue(results["prefetch"].success)
            self.assertTrue(results["required"].success)
            self.assertEqual(renderer.page_calls, [("page.pdf", 0, 1.75, 0)])
            renderer.release.clear()
            renderer.started.clear()
            frame_args = dict(
                file_path="page.pdf",
                page_index=0,
                scale=2.0,
                rotation=0,
                frame_x_pts=0.0,
                frame_y_pts=0.0,
                frame_w_pts=100.0,
                frame_h_pts=100.0,
            )
            service.render_frame_async(
                callback=collector("frame-a"),
                priority=RenderPriority.VISIBLE_FRAME,
                **frame_args,
            )
            self.assertTrue(renderer.started.wait(timeout=2.0))
            service.render_frame_async(
                callback=collector("frame-b"),
                priority=RenderPriority.VISIBLE_FRAME,
                **frame_args,
            )
            renderer.release.set()
            self.assertTrue(
                _pump_until(app, lambda: {"frame-a", "frame-b"} <= set(results))
            )
            self.assertTrue(results["frame-a"].success)
            self.assertTrue(results["frame-b"].success)
            self.assertEqual(len(renderer.frame_calls), 1)
        finally:
            renderer.release.set()
            service.shutdown()

    def test_requests_wait_for_matching_in_flight_work_by_default(self):
        service = PDFRenderingService(PageCache(), num_workers=0)
        try:
            ids = [
                service.render_page_async(
                    "page.pdf",
                    0,
                    1.75,
                    0,
                    lambda _r: None,
                    RenderPriority.REQUIRED_PAGE,
                ),
                service.render_frame_async(
                    "page.pdf",
                    0,
                    2.0,
                    0,
                    0.0,
                    0.0,
                    100.0,
                    100.0,
                    lambda _r: None,
                    RenderPriority.VISIBLE_FRAME,
                ),
            ]
            for request_id in ids:
                self.assertTrue(service._active_requests[request_id].wait_for_in_flight)
        finally:
            service.shutdown()

    def test_cancel_request_signals_native_render_token(self):
        service = PDFRenderingService(PageCache(), num_workers=0)
        try:
            request_id = service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.75,
                rotation=0,
                callback=lambda _result: None,
                priority=RenderPriority.REQUIRED_PAGE,
            )
            request = service._active_requests[request_id]
            self.assertFalse(request.cancelled.is_set())
            self.assertFalse(request.native_cancel_token.is_cancelled())
            service.cancel_request("no-such-request")
            self.assertFalse(request.cancelled.is_set())
            service.cancel_request(request_id)
            service.cancel_request(request_id)
            self.assertTrue(request.cancelled.is_set())
            self.assertTrue(request.native_cancel_token.is_cancelled())
        finally:
            service.shutdown()

    def test_cancel_after_worker_posts_result_suppresses_gui_callback(self):
        app = QApplication.instance() or QApplication([])
        cache = PageCache()
        cache._get_renderer = lambda: FakeImageRenderer()
        service = PDFRenderingService(cache, num_workers=1)
        posted = threading.Event()
        callbacks = []
        original_post = service._render_bridge.request_callback

        def post_result(request, result):
            original_post(request, result)
            posted.set()

        service._render_bridge.request_callback = post_result
        try:
            request_id = service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.0,
                rotation=0,
                callback=callbacks.append,
            )
            self.assertTrue(posted.wait(timeout=1.0))
            service.cancel_request(request_id)
            app.processEvents()
            self.assertEqual(callbacks, [])
            self.assertNotIn(request_id, service._active_requests)
            # Positive control: an uncancelled request on the same service
            # still reaches its callback through the same bridge.
            posted.clear()
            live_request_id = service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=2.0,
                rotation=0,
                callback=callbacks.append,
            )
            self.assertTrue(posted.wait(timeout=1.0))
            self.assertTrue(_pump_until(app, lambda: len(callbacks) == 1))
            self.assertEqual(callbacks[0].request_id, live_request_id)
            self.assertTrue(callbacks[0].success)
            self.assertNotIn(live_request_id, service._active_requests)
        finally:
            service.shutdown()

    def test_cancel_during_render_never_posts_result_and_clears_request(self):
        app = QApplication.instance() or QApplication([])
        renderer = BlockingRenderer()
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        service = PDFRenderingService(cache, num_workers=1)
        posted = []
        callbacks = []
        original_post = service._render_bridge.request_callback
        service._render_bridge.request_callback = lambda request, result: (
            posted.append(request.request_id),
            original_post(request, result),
        )
        try:
            request_id = service.render_page_async(
                "page.pdf", 0, 1.0, 0, callbacks.append
            )
            self.assertTrue(renderer.started.wait(timeout=2.0))
            service.cancel_request(request_id)
            renderer.release.set()
            self.assertTrue(
                _pump_until(app, lambda: request_id not in service._active_requests)
            )
            self.assertEqual(posted, [])
            self.assertEqual(callbacks, [])
        finally:
            renderer.release.set()
            service.shutdown()

    def test_shutdown_cancels_active_requests_and_uses_unique_queue_sentinel_counters(
        self,
    ):
        class JoinedWorker:
            def join(self, timeout=None):
                del timeout

            def is_alive(self):
                return False

        service = PDFRenderingService(PageCache(), num_workers=0)
        request_id = service.render_page_async(
            file_path="page.pdf",
            page_index=0,
            scale=1.0,
            rotation=0,
            callback=lambda _result: None,
            priority=0,
        )
        request = service._active_requests[request_id]
        puts = []
        real_put = service._request_queue.put_nowait
        service._request_queue.put_nowait = lambda item: (
            puts.append(item),
            real_put(item),
        )[1]
        service._worker_threads = [JoinedWorker(), JoinedWorker()]
        service.shutdown()
        self.assertIsNone(service._page_cache)
        self.assertTrue(request.cancelled.is_set())
        self.assertTrue(request.native_cancel_token.is_cancelled())
        self.assertEqual(
            [(priority, item) for priority, _counter, item in puts],
            [(0, None), (0, None)],
        )
        # The queued request used counter 0; every sentinel needs its own
        # counter so equal-priority entries never compare their payloads.
        self.assertEqual([counter for _priority, counter, _item in puts], [1, 2])
        self.assertTrue(service._request_queue.empty())
        self.assertEqual(service._active_requests, {})

    def test_shutdown_retains_dependencies_until_workers_stop(self):
        class DelayedWorker:
            alive = True

            def join(self, timeout=None):
                del timeout

            def is_alive(self):
                return self.alive

        worker = DelayedWorker()
        service = PDFRenderingService(PageCache(), num_workers=0)
        service._worker_threads = [worker]
        with self.assertLogs(_SERVICE_LOGGER, level="ERROR") as captured:
            service.shutdown()
        self.assertIn("retained resources for 1 live worker", captured.output[0])
        self.assertIsNotNone(service._page_cache)
        self.assertEqual(service._worker_threads, [worker])
        worker.alive = False
        service.shutdown()
        self.assertIsNone(service._page_cache)
        self.assertEqual(service._worker_threads, [])

    def test_every_request_entry_point_fails_explicitly_after_shutdown(self):
        service = PDFRenderingService(PageCache(), num_workers=0)
        service.shutdown()
        page = Page(
            uid="p1", name="P1", image_path="page.pdf", overlay_image_path="o.pdf"
        )
        noop = lambda _result: None
        entry_points = {
            "page": lambda: service.render_page_async("page.pdf", 0, 1.0, 0, noop),
            "frame": lambda: service.render_frame_async(
                "page.pdf", 0, 1.0, 0, 0.0, 0.0, 10.0, 10.0, noop
            ),
            "composite": lambda: service.render_composite_async(
                page, None, 1.0, 0, noop
            ),
            "overlay": lambda: service.render_overlay_async(page, 1, 0, 1.0, noop),
            "composite_frame": lambda: service.render_composite_frame_async(
                page, None, 1.0, 0, 0.0, 0.0, 10.0, 10.0, noop
            ),
            "pdf_text": lambda: service.extract_pdf_text_async("page.pdf", 0, noop),
        }
        for name, submit in entry_points.items():
            with self.subTest(entry_point=name):
                with self.assertRaisesRegex(RuntimeError, "shut down"):
                    submit()
        self.assertEqual(service._active_requests, {})


class PdfRenderingRequestExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _service(self, renderer, num_workers=1):
        cache = PageCache()
        cache._get_renderer = lambda: renderer
        service = PDFRenderingService(cache, num_workers=num_workers)
        self.addCleanup(service.shutdown)
        return service

    def _run(self, submit):
        results = []
        request_id = submit(results.append)
        self.assertTrue(_pump_until(self.app, lambda: len(results) == 1))
        self.assertEqual(results[0].request_id, request_id)
        return results[0]

    def test_page_request_applies_effects_only_when_requested_downstream(self):
        renderer = SolidRenderer()
        service = self._service(renderer)
        cases = (
            ("plain", dict(), "#ff0000"),
            ("inverted", dict(invert=True), "#00ffff"),
            (
                "inversion deferred downstream",
                dict(invert=True, apply_invert_effect=False),
                "#ff0000",
            ),
        )
        for index, (name, effects, expected) in enumerate(cases):
            with self.subTest(case=name):
                result = self._run(
                    lambda callback: service.render_page_async(
                        f"page-{index}.pdf", 0, 1.0, 0, callback, **effects
                    )
                )
                self.assertTrue(result.success)
                self.assertIsNone(result.error)
                self.assertEqual(result.image.pixelColor(0, 0).name(), expected)
        self.assertEqual(len(renderer.page_calls), 3)

    def test_page_request_reports_native_render_failure(self):
        service = self._service(SolidRenderer(fail=True))
        result = self._run(
            lambda callback: service.render_page_async("page.pdf", 0, 1.0, 0, callback)
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.image)
        self.assertEqual(result.error, "Failed to render page")

    def test_render_exception_becomes_failed_result_and_clears_request(self):
        service = self._service(SolidRenderer(error=RuntimeError("native boom")))
        with self.assertLogs(_SERVICE_LOGGER, level="ERROR"):
            result = self._run(
                lambda callback: service.render_page_async(
                    "page.pdf", 0, 1.0, 0, callback
                )
            )
        self.assertFalse(result.success)
        self.assertIsNone(result.image)
        self.assertEqual(result.error, "native boom")
        self.assertTrue(_pump_until(self.app, lambda: not service._active_requests))

    def test_frame_request_renders_requested_frame_and_tints_on_demand(self):
        renderer = SolidRenderer()
        service = self._service(renderer)
        plain = self._run(
            lambda callback: service.render_frame_async(
                "page.pdf", 0, 2.0, 0, 5.0, 6.0, 7.0, 8.0, callback
            )
        )
        tinted = self._run(
            lambda callback: service.render_frame_async(
                "page.pdf",
                0,
                2.0,
                0,
                5.0,
                6.0,
                7.0,
                8.0,
                callback,
                tint_rgb=(80, 80, 255),
            )
        )
        self.assertTrue(plain.success)
        self.assertEqual(plain.image.pixelColor(0, 0).name(), "#ff0000")
        self.assertTrue(tinted.success)
        self.assertEqual(
            (tinted.image.width(), tinted.image.height()),
            (plain.image.width(), plain.image.height()),
        )
        self.assertNotEqual(tinted.image.pixelColor(0, 0).name(), "#ff0000")
        # Both requests share one cached frame render.
        self.assertEqual(renderer.frame_calls, [("page.pdf", 0, 2.0, 5.0, 6.0, 7.0)])

    def test_tinted_page_request_uses_tinted_cache_entry(self):
        renderer = SolidRenderer()
        service = self._service(renderer)
        result = self._run(
            lambda callback: service.render_page_async(
                "page.pdf", 0, 1.0, 0, callback, tint_rgb=(80, 80, 255)
            )
        )
        self.assertTrue(result.success)
        self.assertNotEqual(result.image.pixelColor(0, 0).name(), "#ff0000")
        self.assertEqual(len(renderer.page_calls), 1)

    def test_pdf_text_request_returns_text_runs_and_page_info(self):
        service = self._service(SolidRenderer())
        result = self._run(
            lambda callback: service.extract_pdf_text_async("doc.pdf", 0, callback)
        )
        self.assertTrue(result.success)
        self.assertEqual(
            result.image,
            {
                "text_runs": [{"text": "run", "path": "doc.pdf"}],
                "page_info": {"width": 612.0, "path": "doc.pdf", "index": 0},
                "visible_origin": (0.0, 0.0),
            },
        )

    def test_cancelled_request_is_dropped_before_render_and_others_still_run(self):
        renderer = SolidRenderer()
        service = self._service(renderer, num_workers=0)
        callbacks = []
        cancelled_id = service.render_page_async(
            "cancelled.pdf", 0, 1.0, 0, callbacks.append
        )
        live_id = service.render_page_async("live.pdf", 0, 1.0, 0, callbacks.append)
        service.cancel_request(cancelled_id)
        service._start_workers(1)
        self.assertTrue(_pump_until(self.app, lambda: len(callbacks) == 1))
        self.assertTrue(_pump_until(self.app, lambda: not service._active_requests))
        self.assertEqual([call[0] for call in renderer.page_calls], ["live.pdf"])
        self.assertEqual([result.request_id for result in callbacks], [live_id])

    def test_callback_exception_is_logged_and_request_is_still_cleared(self):
        service = self._service(SolidRenderer())

        def failing_callback(_result):
            raise ValueError("callback failed")

        with self.assertLogs(_SERVICE_LOGGER, level="ERROR") as captured:
            request_id = service.render_page_async(
                "page.pdf", 0, 1.0, 0, failing_callback
            )
            self.assertTrue(
                _pump_until(
                    self.app, lambda: request_id not in service._active_requests
                )
            )
        self.assertTrue(any("callback failed" in line for line in captured.output))

    def _bare_request(self, request_type, **overrides):
        values = dict(
            request_id="r1",
            request_type=request_type,
            file_path="page.pdf",
            page_index=0,
            scale=1.0,
            rotation=0,
            tint_rgb=None,
            invert=False,
            bitonal=False,
            priority=0,
            page_entity=None,
            bid_ref=None,
            callback=lambda _result: None,
        )
        values.update(overrides)
        return RenderRequest(**values)

    def test_unknown_request_type_fails_explicitly(self):
        service = self._service(SolidRenderer(), num_workers=0)
        result = service._execute_render(self._bare_request("bogus"))
        self.assertEqual(
            result, RenderResult("r1", False, None, "Unknown request type: bogus")
        )

    def test_composite_frame_request_without_page_entity_fails_explicitly(self):
        service = self._service(SolidRenderer(), num_workers=0)
        result = service._execute_render(self._bare_request("composite_frame"))
        self.assertEqual(result, RenderResult("r1", False, None, "No page entity"))


class PdfRenderingRequestSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.service = PDFRenderingService(PageCache(), num_workers=0)
        self.addCleanup(self.service.shutdown)

    def _page(self, **overrides):
        values = {
            "uid": "p1",
            "name": "P1",
            "image_path": "base.pdf",
            "overlay_image_path": "overlay.pdf",
            "page_index": 3,
            "takeoffs": [Takeoff(uid="t1", condition_uid="c1")],
            "overlay_rect": (1.0, 2.0, 3.0, 4.0),
            "invert": True,
            "bitonal": False,
        }
        values.update(overrides)
        return Page(**values)

    def test_entry_points_build_requests_with_documented_type_and_priority(self):
        service = self.service
        noop = lambda _result: None
        page = self._page()
        submitted = {
            "page": service.render_page_async("a.pdf", 1, 2.0, 90, noop),
            "tinted": service.render_page_async(
                "a.pdf", 1, 2.0, 90, noop, tint_rgb=(1, 2, 3)
            ),
            "frame": service.render_frame_async(
                "a.pdf", 1, 2.0, 90, 1.0, 2.0, 3.0, 4.0, noop
            ),
            "composite": service.render_composite_async(page, None, 2.0, 0, noop),
            "composite_frame": service.render_composite_frame_async(
                page, None, 2.0, 0, 1.0, 2.0, 3.0, 4.0, noop
            ),
            "overlay": service.render_overlay_async(page, 1, 0, 2.0, noop),
        }
        expected = {
            "page": ("page", RenderPriority.REQUIRED_PAGE),
            "tinted": ("tinted_page", RenderPriority.REQUIRED_PAGE),
            "frame": ("frame", RenderPriority.VISIBLE_FRAME),
            "composite": ("composite", RenderPriority.REQUIRED_PAGE),
            "composite_frame": ("composite_frame", RenderPriority.VISIBLE_FRAME),
            "overlay": ("overlay", RenderPriority.REQUIRED_PAGE),
        }
        for name, request_id in submitted.items():
            with self.subTest(entry_point=name):
                request = service._active_requests[request_id]
                self.assertEqual(
                    (request.request_type, request.priority), expected[name]
                )
        text_id = service.extract_pdf_text_async("a.pdf", 4, noop)
        text_request = service._active_requests[text_id]
        self.assertEqual(
            (text_request.file_path, text_request.page_index), ("a.pdf", 4)
        )
        self.assertEqual(text_request.priority, RenderPriority.PDF_TEXT)
        frame_request = service._active_requests[submitted["frame"]]
        self.assertEqual(
            (
                frame_request.frame_x_pts,
                frame_request.frame_y_pts,
                frame_request.frame_w_pts,
                frame_request.frame_h_pts,
            ),
            (1.0, 2.0, 3.0, 4.0),
        )

    def test_overlay_request_is_blue_tinted_only_in_comparison_mode(self):
        noop = lambda _result: None
        page = self._page()
        comparison = self.service._active_requests[
            self.service.render_overlay_async(page, 2, 0, 1.0, noop)
        ]
        overlay_only = self.service._active_requests[
            self.service.render_overlay_async(page, 1, 0, 1.0, noop)
        ]
        self.assertEqual(comparison.tint_rgb, (80, 80, 255))
        self.assertIsNone(overlay_only.tint_rgb)
        for request in (comparison, overlay_only):
            self.assertEqual(request.file_path, "overlay.pdf")
            self.assertEqual(request.page_index, 0)
            self.assertTrue(request.invert)

    def test_composite_requests_snapshot_the_page_at_submission_time(self):
        page = self._page()
        noop = lambda _result: None
        composite = self.service._active_requests[
            self.service.render_composite_async(page, None, 2.0, 0, noop)
        ]
        frame = self.service._active_requests[
            self.service.render_composite_frame_async(
                page, None, 2.0, 0, 0.0, 0.0, 5.0, 5.0, noop
            )
        ]
        page.takeoffs.append(Takeoff(uid="t2", condition_uid="c1"))
        page.invert = False
        for request in (composite, frame):
            snapshot = request.page_entity
            self.assertIsNot(snapshot, page)
            self.assertEqual([t.uid for t in snapshot.takeoffs], ["t1"])
            self.assertTrue(snapshot.invert)
            self.assertTrue(request.invert)
            self.assertEqual(request.file_path, "base.pdf")
            self.assertEqual(request.page_index, 3)

    def test_queue_orders_by_priority_then_submission_order(self):
        service = self.service
        noop = lambda _result: None
        prefetch = service.render_page_async(
            "a.pdf", 0, 1.0, 0, noop, RenderPriority.NEARBY_PREFETCH
        )
        required_first = service.render_page_async(
            "b.pdf", 0, 1.0, 0, noop, RenderPriority.REQUIRED_PAGE
        )
        visible = service.render_page_async(
            "c.pdf", 0, 1.0, 0, noop, RenderPriority.VISIBLE_FRAME
        )
        required_second = service.render_page_async(
            "d.pdf", 0, 1.0, 0, noop, RenderPriority.REQUIRED_PAGE
        )
        order = []
        while not service._request_queue.empty():
            _priority, _counter, request = service._request_queue.get_nowait()
            order.append(request.request_id)
        self.assertEqual(order, [required_first, required_second, visible, prefetch])
