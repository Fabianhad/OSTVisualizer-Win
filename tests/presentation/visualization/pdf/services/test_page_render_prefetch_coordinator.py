import unittest
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
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
                del (
                    file_path,
                    page_index,
                    scale,
                    rotation,
                    priority,
                    invert,
                    bitonal,
                    tint_rgb,
                    apply_invert_effect,
                    apply_bitonal_effect,
                )
                self._counter += 1
                request_id = f"page-{self._counter}"
                callback(RenderResult(request_id, True, object(), None))
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
        size_provider = FakePageSizeProvider({"heavy.pdf": (3024.0, 2160.0)})
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

    def test_raster_overlay_prefetch_uses_native_pixel_scale(self):
        rendering = FakeRenderingService()
        size_provider = FakePageSizeProvider({"overlay.tif": (1224.0, 1584.0)})
        cache = FakeCache(sizes={("overlay.tif", 0): (1224.0, 1584.0)})
        coordinator = self._coordinator(rendering, cache, size_provider)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page(
                "p2",
                overlay_image_path="overlay.tif",
                image_show_mode=1,
            ),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(len(rendering.calls), 1)
        self.assertEqual(rendering.calls[0][0], "overlay")
        self.assertEqual(
            rendering.calls[0][2]["render_scale"],
            RASTER_NATIVE_RENDER_SCALE,
        )
        self.assertEqual(
            cache.render_checks,
            [(1224.0, 1584.0, RASTER_NATIVE_RENDER_SCALE)],
        )

    def test_uncacheable_raster_overlay_uses_native_dimensions_and_skips_render(self):
        rendering = FakeRenderingService()
        native_size = (12000.0, 12000.0)
        size_provider = FakePageSizeProvider({"overlay.tif": native_size})
        cache = FakeCache(
            can_accept_render=False,
            sizes={("overlay.tif", 0): native_size},
        )
        coordinator = self._coordinator(rendering, cache, size_provider)
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page(
                "p2",
                overlay_image_path="overlay.tif",
                image_show_mode=1,
            ),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(rendering.calls, [])
        self.assertEqual(
            cache.render_checks,
            [(12000.0, 12000.0, RASTER_NATIVE_RENDER_SCALE)],
        )

    def test_uncacheable_prefetch_estimate_skips_render(self):
        rendering = FakeRenderingService()
        cache = FakeCache(can_accept_render=False)
        size_provider = FakePageSizeProvider({"heavy.pdf": (3024.0, 2160.0)})
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
