import unittest
from ost_visualizer.application.dtos.render_result_dto import RenderResult
from ost_visualizer.application.render_quality import (
    INTERACTIVE_PDF_RENDER_SCALE,
    RASTER_NATIVE_RENDER_SCALE,
)
from ost_visualizer.application.services.page_load_strategy_service import (
    PageLoadStrategyService,
)
from ost_visualizer.domain.entities.page import Page
from ost_visualizer.presentation.visualization.pdf.page_cache import PageCache
from ost_visualizer.presentation.visualization.pdf.services.page_render_prefetch_coordinator import (
    PageRenderPrefetchCoordinator,
)
from PySide6.QtGui import QImage
from types import SimpleNamespace
from ost_visualizer.domain.entities.bid import Bid
from ost_visualizer.domain.entities.identity_refs import BidRef
from ost_visualizer.presentation.coordinators.viewer_sync_coordinator import (
    ViewerSyncCoordinator,
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


class FakeImageRenderer:
    def __init__(self):
        self.calls = []

    def render(self, file_path, page_index, scale, rotation, native_cancel_token=None):
        self.calls.append((file_path, page_index, scale, rotation, native_cancel_token))
        image = QImage(10, 10, QImage.Format.Format_ARGB32)
        image.fill(0)
        return image


class PrefetchCacheWorkflowTests(unittest.TestCase):
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

    def test_prefetch_warms_same_page_cache_used_by_normal_rendering(self):
        cache = PageCache()
        renderer = FakeImageRenderer()
        cache._get_renderer = lambda: renderer

        class CacheWarmingRenderingService(FakeRenderingService):
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
                cache.get_page(
                    file_path,
                    page_index,
                    scale,
                    rotation,
                )
                return super().render_page_async(
                    file_path,
                    page_index,
                    scale,
                    rotation,
                    callback,
                    priority,
                    invert,
                    bitonal,
                    tint_rgb,
                    apply_invert_effect,
                    apply_bitonal_effect,
                )

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
        cache.get_page("p2.pdf", 0, INTERACTIVE_PDF_RENDER_SCALE, 0)
        self.assertEqual(
            renderer.calls,
            [("p2.pdf", 0, INTERACTIVE_PDF_RENDER_SCALE, 0, None)],
        )


class ViewerSyncPrefetchIntegrationTests(unittest.TestCase):
    def test_current_page_load_is_queued_before_nearby_prefetch(self):
        calls = []
        page = Page(uid="p2", name="P2")

        class FakePlanView:
            current_page_uid = "p1"

            def refresh_current_page_overlays(
                self,
                page,
                takeoffs,
                conditions,
                color_map,
                bid_ref=None,
                annotations=None,
                page_area_selections=None,
                hidden_layer_uids=None,
                changed_takeoff_uids=None,
                changed_annotation_uids=None,
                changed_annotation_types=None,
            ):
                del (
                    page,
                    takeoffs,
                    conditions,
                    color_map,
                    bid_ref,
                    annotations,
                    page_area_selections,
                    hidden_layer_uids,
                    changed_takeoff_uids,
                    changed_annotation_uids,
                    changed_annotation_types,
                )
                calls.append("refresh")
                return False

            def load_page(
                self,
                page,
                takeoffs,
                conditions,
                color_map,
                bid_ref=None,
                annotations=None,
                page_area_selections=None,
                hidden_layer_uids=None,
            ):
                del (
                    page,
                    takeoffs,
                    conditions,
                    color_map,
                    bid_ref,
                    annotations,
                    page_area_selections,
                    hidden_layer_uids,
                )
                calls.append("load")

            def prefetch_nearby_pages(self, current_page, ordered_pages, bid_ref=None):
                del current_page, ordered_pages, bid_ref
                calls.append("prefetch")

            def set_snap_settings(self, takeoff_increments, measure_base):
                del takeoff_increments, measure_base
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
            def get_color_mapping(
                self,
                bid_conditions,
                bid_takeoffs,
                display_mode="solid",
                grayscale_enabled=True,
                extra_condition_uids=None,
            ):
                del (
                    bid_conditions,
                    bid_takeoffs,
                    display_mode,
                    grayscale_enabled,
                    extra_condition_uids,
                )
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
