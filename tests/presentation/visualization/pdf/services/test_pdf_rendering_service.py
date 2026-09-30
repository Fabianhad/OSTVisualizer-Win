import threading
import unittest
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
)
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


class FakePageSizeProvider:
    def __init__(self, sizes=None):
        self.sizes = sizes or {}
        self.calls = []

    def get_page_size(self, file_path, page_index):
        self.calls.append((file_path, page_index))
        return self.sizes.get(file_path, (612.0, 792.0))


class FakeRenderingService:
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self.callbacks = {}
        self._counter = 0

    def _record(self, request_type, render_options):
        self._counter += 1
        request_id = f"{request_type}-{self._counter}"
        self.calls.append((request_type, request_id, render_options))
        self.callbacks[request_id] = render_options["callback"]
        return request_id

    def render_page_async(
        self,
        file_path,
        page_index,
        scale,
        rotation,
        callback,
        priority=0,
        invert=False,
        bitonal=False,
        tint_rgb=None,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        render_options = {
            "file_path": file_path,
            "page_index": page_index,
            "scale": scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "invert": invert,
            "bitonal": bitonal,
            "tint_rgb": tint_rgb,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        return self._record("page", render_options)

    def render_overlay_async(
        self,
        page,
        show_mode,
        rotation,
        render_scale,
        callback,
        priority=0,
        apply_invert_effect=True,
        apply_bitonal_effect=True,
    ):
        render_options = {
            "page": page,
            "show_mode": show_mode,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
            "render_scale": render_scale,
            "apply_invert_effect": apply_invert_effect,
            "apply_bitonal_effect": apply_bitonal_effect,
        }
        return self._record("overlay", render_options)

    def render_composite_async(
        self,
        page,
        bid_ref,
        render_scale,
        rotation,
        callback,
        priority=0,
    ):
        render_options = {
            "page": page,
            "bid_ref": bid_ref,
            "render_scale": render_scale,
            "rotation": rotation,
            "callback": callback,
            "priority": priority,
        }
        return self._record("composite", render_options)

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)

    def complete(self, request_id, success=True):
        callback = self.callbacks[request_id]
        callback(RenderResult(request_id, success, object(), None))


class FakeCache:
    def __init__(self, can_accept=True, can_accept_render=True, sizes=None):
        self.can_accept = can_accept
        self.can_accept_render = can_accept_render
        self.sizes = sizes or {}
        self.checks = 0
        self.render_checks = []

    def can_accept_prefetch(self):
        self.checks += 1
        return self.can_accept

    def can_accept_prefetch_render(self, width_pts, height_pts, scale):
        self.render_checks.append((width_pts, height_pts, scale))
        return self.can_accept_prefetch() and self.can_accept_render

    def get_page_size(self, file_path, page_index):
        return self.sizes.get((file_path, page_index), (612.0, 792.0))


class FakeImageRenderer:
    def __init__(self):
        self.calls = []

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.calls.append((file_path, page_index, scale, rotation, native_cancel_token))
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(0)
        return image


class PdfRenderingRequestLifecycleTests(unittest.TestCase):
    def _coordinator(self, rendering_service=None, cache=None, size_provider=None):
        rendering_service = rendering_service or FakeRenderingService()
        cache = cache or FakeCache()
        size_provider = size_provider or FakePageSizeProvider()
        return PageRenderPrefetchCoordinator(
            rendering_service,
            PageLoadStrategyService(size_provider),
            cache,
        )

    def _page(self, uid, **overrides):
        values = {
            "uid": uid,
            "name": uid,
            "width_pts": 612.0,
            "height_pts": 792.0,
        }
        values.update(overrides)
        return Page(**values)

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
        service = PDFRenderingService(PageCache(), num_workers=0)
        try:
            required_id = service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.75,
                rotation=0,
                callback=lambda _result: None,
                priority=RenderPriority.REQUIRED_PAGE,
            )
            visible_frame_id = service.render_frame_async(
                file_path="page.pdf",
                page_index=0,
                scale=2.0,
                rotation=0,
                frame_x_pts=0.0,
                frame_y_pts=0.0,
                frame_w_pts=100.0,
                frame_h_pts=100.0,
                callback=lambda _result: None,
                priority=RenderPriority.VISIBLE_FRAME,
            )
            prefetch_id = service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.75,
                rotation=0,
                callback=lambda _result: None,
                priority=RenderPriority.NEARBY_PREFETCH,
            )
            self.assertTrue(service._active_requests[required_id].wait_for_in_flight)
            self.assertTrue(
                service._active_requests[visible_frame_id].wait_for_in_flight
            )
            self.assertTrue(service._active_requests[prefetch_id].wait_for_in_flight)
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
        finally:
            service.shutdown()

    def test_shutdown_uses_unique_priority_queue_sentinel_counters(self):
        class JoinedWorker:
            def join(self, timeout=None):
                del timeout

            def is_alive(self):
                return False

        service = PDFRenderingService(PageCache(), num_workers=0)
        service.render_page_async(
            file_path="page.pdf",
            page_index=0,
            scale=1.0,
            rotation=0,
            callback=lambda _result: None,
            priority=0,
        )
        service._worker_threads = [JoinedWorker()]
        service.shutdown()
        self.assertIsNone(service._page_cache)

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
        service.shutdown()
        self.assertIsNotNone(service._page_cache)
        worker.alive = False
        service.shutdown()
        self.assertIsNone(service._page_cache)

    def test_requests_after_shutdown_fail_explicitly(self):
        service = PDFRenderingService(PageCache(), num_workers=0)
        service.shutdown()
        with self.assertRaisesRegex(RuntimeError, "shut down"):
            service.render_page_async(
                file_path="page.pdf",
                page_index=0,
                scale=1.0,
                rotation=0,
                callback=lambda _result: None,
            )
