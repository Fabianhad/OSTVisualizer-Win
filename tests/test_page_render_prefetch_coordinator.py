import unittest
from PySide6.QtGui import QImage
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
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.render_priority import RenderPriority


class FakePageSizeProvider:
    def __init__(self, sizes=None):
        self.sizes = sizes or {}

    def get_page_size(self, _file_path, _page_index):
        return self.sizes.get(_file_path, (612.0, 792.0))


class FakeRenderingService:
    def __init__(self):
        self.calls = []
        self.cancelled = []
        self.callbacks = {}
        self._counter = 0

    def _record(self, request_type, kwargs):
        self._counter += 1
        request_id = f"{request_type}-{self._counter}"
        self.calls.append((request_type, request_id, kwargs))
        self.callbacks[request_id] = kwargs["callback"]
        return request_id

    def render_page_async(self, **kwargs):
        return self._record("page", kwargs)

    def render_overlay_async(self, **kwargs):
        return self._record("overlay", kwargs)

    def render_composite_async(self, **kwargs):
        return self._record("composite", kwargs)

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

    def render(self, file_path, page_index, scale, rotation):
        self.calls.append((file_path, page_index, scale, rotation))
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

    def _page(self, uid, **kwargs):
        values = {
            "uid": uid,
            "name": uid,
            "width_pts": 612.0,
            "height_pts": 792.0,
        }
        values.update(kwargs)
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
        coordinator = self._coordinator(
            rendering,
            cache,
            FakePageSizeProvider({"heavy.pdf": (3024.0, 2160.0)}),
        )
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="heavy.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(len(rendering.calls), 1)
        scale = rendering.calls[0][2]["scale"]
        self.assertLess(scale, 2.0)
        self.assertEqual(cache.render_checks, [(3024.0, 2160.0, scale)])

    def test_uncacheable_prefetch_estimate_skips_render(self):
        rendering = FakeRenderingService()
        cache = FakeCache(can_accept_render=False)
        coordinator = self._coordinator(
            rendering,
            cache,
            FakePageSizeProvider({"heavy.pdf": (3024.0, 2160.0)}),
        )
        pages = [
            self._page("p1", image_path="p1.pdf"),
            self._page("p2", image_path="heavy.pdf"),
        ]
        coordinator.prefetch_nearby_pages(pages[0], pages, None)
        self.assertEqual(rendering.calls, [])
        self.assertEqual(len(cache.render_checks), 1)

    def test_prefetch_warms_same_page_cache_used_by_normal_rendering(self):
        cache = PageCache()
        renderer = FakeImageRenderer()
        cache._get_renderer = lambda: renderer

        class CacheWarmingRenderingService(FakeRenderingService):
            def render_page_async(self, **kwargs):
                cache.get_page(
                    kwargs["file_path"],
                    kwargs["page_index"],
                    kwargs["scale"],
                    kwargs["rotation"],
                )
                return super().render_page_async(**kwargs)

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
        self.assertEqual(renderer.calls, [("p2.pdf", 0, 2.0, 0)])

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
                ("p1.pdf", 0, 2.0, 0),
                ("p1.pdf", 0, 3.0, 0),
                ("p1.pdf", 0, 2.0, 90),
            ],
        )


class ViewerSyncPrefetchIntegrationTests(unittest.TestCase):
    def test_current_page_load_is_queued_before_nearby_prefetch(self):
        calls = []
        page = Page(uid="p2", name="P2")

        class FakePlanView:
            current_page_uid = "p1"

            def refresh_current_page_overlays(self, **_kwargs):
                calls.append("refresh")
                return False

            def load_page(self, **_kwargs):
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
                "State", (), {"color_mode": "condition", "grayscale_enabled": False}
            )()
            place_condition_uid = None

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
            None,
        )
        coordinator.plan_view = FakePlanView()
        coordinator.update_plan_view("p2")
        self.assertEqual(calls, ["load", "snap", "prefetch"])


if __name__ == "__main__":
    unittest.main()
