import unittest
import threading
from types import SimpleNamespace
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from ost_visualizer.presentation.visualization.pdf.services.pdf_rendering_service import (
    PDFRenderingService,
)


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

    def render_page_async(self, **render_options):
        return self._record("page", render_options)

    def render_overlay_async(self, **render_options):
        return self._record("overlay", render_options)

    def render_composite_async(self, **render_options):
        return self._record("composite", render_options)

    def cancel_request(self, request_id):
        self.cancelled.append(request_id)

    def complete(self, request_id, success=True):
        callback = self.callbacks[request_id]
        callback(RenderResult(request_id, success, object(), None))


class FakeCache:
    def __init__(self, can_accept=True, can_accept_render=True):
        self.can_accept = can_accept
        self.can_accept_render = can_accept_render
        self.checks = 0
        self.render_checks = []

    def can_accept_prefetch(self):
        self.checks += 1
        return self.can_accept

    def can_accept_prefetch_render(self, width_pts, height_pts, scale):
        self.render_checks.append((width_pts, height_pts, scale))
        return self.can_accept_prefetch() and self.can_accept_render


class FakeImageRenderer:
    def __init__(self):
        self.calls = []

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.calls.append((file_path, page_index, scale, rotation, native_cancel_token))
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(0)
        return image


class PageRenderPrefetchCoordinatorTests(unittest.TestCase):
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

    def test_pdf_load_strategy_uses_stored_dimensions_without_page_size_lookup(self):
        size_provider = FakePageSizeProvider({"slow.pdf": (3024.0, 2160.0)})
        strategy = PageLoadStrategyService(size_provider).determine_load_strategy(
            self._page(
                "p1",
                image_path="slow.pdf",
                width_pts=3024.0,
                height_pts=2160.0,
            )
        )
        self.assertEqual(strategy.pdf_width_pts, 3024.0)
        self.assertEqual(strategy.pdf_height_pts, 2160.0)
        self.assertEqual(size_provider.calls, [])

    def test_pdf_load_strategy_reads_page_size_when_stored_dimensions_missing(self):
        size_provider = FakePageSizeProvider({"slow.pdf": (3024.0, 2160.0)})
        strategy = PageLoadStrategyService(size_provider).determine_load_strategy(
            self._page(
                "p1",
                image_path="slow.pdf",
                width_pts=0.0,
                height_pts=0.0,
            )
        )
        self.assertEqual(strategy.pdf_width_pts, 3024.0)
        self.assertEqual(strategy.pdf_height_pts, 2160.0)
        self.assertEqual(size_provider.calls, [("slow.pdf", 0)])

    def test_overlay_only_raster_without_main_image_still_loads(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider({"overlay.tif": (1224.0, 1584.0)})
        ).determine_load_strategy(
            self._page(
                "p1",
                image_path=None,
                overlay_image_path="overlay.tif",
                image_show_mode=1,
            )
        )
        self.assertTrue(strategy.needs_async_loading)
        self.assertTrue(strategy.load_overlay)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_composite)

    def test_overlay_only_mode_without_overlay_does_not_load_hidden_main(self):
        strategy = PageLoadStrategyService(
            FakePageSizeProvider()
        ).determine_load_strategy(
            self._page(
                "p1",
                image_path="main.pdf",
                overlay_image_path=None,
                image_show_mode=1,
            )
        )
        self.assertFalse(strategy.needs_async_loading)
        self.assertFalse(strategy.load_overlay)
        self.assertFalse(strategy.load_main)
        self.assertFalse(strategy.load_composite)

    def test_only_previous_and_next_pages_are_prefetched_at_lower_priority(self):
        rendering = FakeRenderingService()
        coordinator = self._coordinator(rendering)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
            self._page("p3", image_path="p3.pdf"),
            self._page("p4", image_path="p4.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[1], pages, BidRef("bid.mdb", "bid"))
        self.assertEqual(
            [call[2]["file_path"] for call in rendering.calls],
            ["p1.pdf", "p3.pdf"],
        )
        self.assertTrue(
            all(
                call[2]["priority"] == RenderPriority.NEARBY_PREFETCH
                for call in rendering.calls
            )
        )
        self.assertGreater(RenderPriority.NEARBY_PREFETCH, RenderPriority.REQUIRED_PAGE)

    def test_duplicate_adjacent_page_uid_is_scheduled_once(self):
        rendering = FakeRenderingService()
        coordinator = self._coordinator(rendering)
        repeated = self._page("p1", image_path="p1.pdf")
        current = self._page("p2", image_path="p2.pdf")
        coordinator.prefetch_nearby_pages(current, [repeated, current, repeated], None)
        self.assertEqual([call[2]["file_path"] for call in rendering.calls], ["p1.pdf"])

    def test_render_selection_matches_page_load_strategy(self):
        rendering = FakeRenderingService()
        coordinator = self._coordinator(rendering)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page(
                "p2",
                image_path="base.pdf",
                overlay_image_path="overlay.pdf",
                image_show_mode=2,
            ),
            self._page("p3", overlay_image_path="overlay-only.pdf", image_show_mode=1),
        ]
        coordinator.prefetch_nearby_pages(pages[1], pages, None)
        self.assertEqual([call[0] for call in rendering.calls], ["page", "overlay"])
        coordinator.prefetch_nearby_pages(pages[2], pages, None)
        self.assertEqual(rendering.calls[-1][0], "composite")

    def test_switching_pages_cancels_and_invalidates_stale_prefetch(self):
        rendering = FakeRenderingService()
        coordinator = self._coordinator(rendering)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
            self._page("p3", image_path="p3.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[1], pages, None)
        old_ids = [call[1] for call in rendering.calls]
        coordinator.prefetch_nearby_pages(pages[2], pages, None)
        self.assertCountEqual(rendering.cancelled, old_ids)
        scheduled_after_switch = list(rendering.calls)
        rendering.complete(old_ids[0])
        self.assertEqual(rendering.calls, scheduled_after_switch)
        self.assertCountEqual(rendering.cancelled, old_ids)

    def test_synchronous_prefetch_completion_does_not_leave_orphaned_request(self):
        class SynchronousRenderingService(FakeRenderingService):
            def render_page_async(self, **render_options):
                self._counter += 1
                request_id = f"page-{self._counter}"
                render_options["callback"](
                    RenderResult(request_id, True, object(), None)
                )
                return request_id

        rendering = SynchronousRenderingService()
        coordinator = self._coordinator(rendering)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(coordinator._active_request_ids, set())
        coordinator.cancel_pending()
        self.assertEqual(rendering.cancelled, [])

    def test_duplicate_prefetch_completion_does_not_leave_a_pending_request(self):
        rendering = FakeRenderingService()
        coordinator = self._coordinator(rendering)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        request_id = rendering.calls[0][1]
        rendering.complete(request_id)
        rendering.complete(request_id)
        self.assertEqual(coordinator._active_request_ids, set())
        coordinator.cancel_pending()
        self.assertEqual(rendering.cancelled, [])

    def test_cache_pressure_skips_prefetch(self):
        rendering = FakeRenderingService()
        cache = FakeCache(can_accept=False)
        coordinator = self._coordinator(rendering, cache)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(rendering.calls, [])
        self.assertEqual(cache.checks, 1)

    def test_heavy_pdf_prefetch_uses_cache_aware_scale(self):
        rendering = FakeRenderingService()
        cache = FakeCache()
        size_provider = FakePageSizeProvider({"heavy.pdf": (100.0, 100.0)})
        coordinator = self._coordinator(rendering, cache, size_provider)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page(
                "p2",
                image_path="heavy.pdf",
                width_pts=3024.0,
                height_pts=2160.0,
            ),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(len(rendering.calls), 1)
        scale = rendering.calls[0][2]["scale"]
        self.assertLess(scale, 2.0)
        self.assertEqual(cache.render_checks, [(3024.0, 2160.0, scale)])
        self.assertEqual(size_provider.calls, [])

    def test_uncacheable_prefetch_estimate_skips_render(self):
        rendering = FakeRenderingService()
        cache = FakeCache(can_accept_render=False)
        size_provider = FakePageSizeProvider({"heavy.pdf": (100.0, 100.0)})
        coordinator = self._coordinator(rendering, cache, size_provider)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page(
                "p2",
                image_path="heavy.pdf",
                width_pts=3024.0,
                height_pts=2160.0,
            ),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(rendering.calls, [])
        self.assertEqual(len(cache.render_checks), 1)
        self.assertEqual(size_provider.calls, [])

    def test_prefetch_warms_same_page_cache_used_by_normal_rendering(self):
        cache = PageCache()
        renderer = FakeImageRenderer()
        cache._get_renderer = lambda: renderer

        class CacheWarmingRenderingService(FakeRenderingService):
            def render_page_async(self, **render_options):
                cache.get_page(
                    render_options["file_path"],
                    render_options["page_index"],
                    render_options["scale"],
                    render_options["rotation"],
                )
                return super().render_page_async(**render_options)

        rendering = CacheWarmingRenderingService()
        coordinator = PageRenderPrefetchCoordinator(
            rendering,
            PageLoadStrategyService(FakePageSizeProvider()),
            cache,
        )
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="p2.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        cache.get_page("p2.pdf", 0, 2.0, 0)
        self.assertEqual(renderer.calls, [("p2.pdf", 0, 2.0, 0, None)])

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


class ViewerSyncPrefetchIntegrationTests(unittest.TestCase):
    def test_current_page_load_is_queued_before_nearby_prefetch(self):
        calls = []
        page = Page(uid="p2", name="P2")

        class FakePlanView:
            current_page_uid = "p1"

            def refresh_current_page_overlays(self, **_call_options):
                calls.append("refresh")
                return False

            def load_page(self, **_call_options):
                calls.append("load")

            def prefetch_nearby_pages(self, *_args):
                calls.append("prefetch")

            def set_snap_settings(self, *_args):
                calls.append("snap")

        class FakeProjectData:
            def get_page(self, page_uid):
                return page if page_uid == "p2" else None

            def get_all_pages(self):
                return [Page(uid="p1", name="P1"), page, Page(uid="p3", name="P3")]

            def get_bid_conditions(self):
                return {}

            def get_page_takeoffs(self, _page_uid):
                return []

            def get_page_annotations(self, _page_uid):
                return []

            def get_page_area_selections(self):
                return {}

            def get_hidden_layer_uids(self):
                return set()

            def get_bid(self, _bid_ref):
                return Bid(uid="bid", name="Bid")

        class FakeUiState:
            state = type(
                "State",
                (),
                {
                    "display_mode_2d": "condition",
                    "display_mode_3d": "condition",
                    "display_modes_synced": True,
                    "grayscale_enabled": False,
                },
            )()
            place_condition_uid = None
            place_condition_uids = []

            def get_selected_bid_ref(self):
                return BidRef("bid.mdb", "bid")

        class FakeColorService:
            def get_color_mapping(self, *_args):
                return {}, {}

        coordinator = ViewerSyncCoordinator(
            FakeUiState(),
            None,
            FakeColorService(),
            FakeProjectData(),
            SimpleNamespace(dispatch=lambda callback, payload: callback(payload)),
        )
        coordinator.plan_view = FakePlanView()
        coordinator.update_plan_view("p2")
        self.assertEqual(calls, ["load", "snap", "prefetch"])


if __name__ == "__main__":
    unittest.main()
