import threading
from typing import Iterable, Optional
from .....application.dtos.render_result_dto import RenderResult
from .....application.interfaces.i_page_load_strategy_service import (
    IPageLoadStrategyService,
)
from .....application.interfaces.i_page_rendering_service import IPageRenderingService
from .....domain.entities.identity_refs import BidRef
from .....domain.entities.page import Page
from ..page_cache import PageCache
from ..render_priority import RenderPriority


class PageRenderPrefetchCoordinator:
    def __init__(
        self,
        rendering_service: IPageRenderingService,
        load_coordinator: IPageLoadStrategyService,
        page_cache: PageCache,
    ) -> None:
        self._rendering_service = rendering_service
        self._load_coordinator = load_coordinator
        self._page_cache = page_cache
        self._lock = threading.Lock()
        self._generation = 0
        self._active_request_ids: set[str] = set()
        self._completed_request_ids: set[str] = set()

    def prefetch_nearby_pages(
        self,
        current_page: Optional[Page],
        ordered_pages: Iterable[Page],
        bid_ref: Optional[BidRef],
    ) -> None:
        self.cancel_pending()
        if current_page is None:
            return
        pages = [page for page in ordered_pages if page is not None]
        targets = self._nearby_pages(current_page, pages)
        if not targets:
            return
        with self._lock:
            generation = self._generation
        for page in targets:
            self._schedule_page(page, bid_ref, generation)

    def cancel_pending(self) -> None:
        with self._lock:
            request_ids = list(self._active_request_ids)
            self._active_request_ids.clear()
            self._completed_request_ids.clear()
            self._generation += 1
        for request_id in request_ids:
            self._rendering_service.cancel_request(request_id)

    def _nearby_pages(self, current_page: Page, pages: list[Page]) -> list[Page]:
        current_index = next(
            (index for index, page in enumerate(pages) if page.uid == current_page.uid),
            -1,
        )
        if current_index < 0:
            return []
        result: list[Page] = []
        scheduled_uids: set[str] = set()
        if current_index > 0:
            previous_page = pages[current_index - 1]
            result.append(previous_page)
            scheduled_uids.add(previous_page.uid)
        if current_index + 1 < len(pages):
            next_page = pages[current_index + 1]
            if next_page.uid not in scheduled_uids:
                result.append(next_page)
        return result

    def _schedule_page(
        self, page: Page, bid_ref: Optional[BidRef], generation: int
    ) -> None:
        strategy = self._load_coordinator.determine_load_strategy(page)
        if not strategy.needs_async_loading or not page.layer_visible:
            return
        request_id = ""

        def callback(result: RenderResult) -> None:
            self._on_prefetch_complete(result, generation)

        if strategy.load_composite:
            render_scale = self._cacheable_prefetch_scale(
                strategy.pdf_width_pts,
                strategy.pdf_height_pts,
                strategy.main_scale,
            )
            if render_scale is None:
                return
            request_id = self._rendering_service.render_composite_async(
                page=page,
                bid_ref=bid_ref,
                render_scale=render_scale,
                rotation=0,
                callback=callback,
                priority=RenderPriority.NEARBY_PREFETCH,
            )
        elif strategy.load_main:
            render_scale = self._cacheable_prefetch_scale(
                strategy.pdf_width_pts,
                strategy.pdf_height_pts,
                strategy.main_scale,
            )
            if render_scale is None:
                return
            request_id = self._rendering_service.render_page_async(
                file_path=page.image_path,
                page_index=page.page_index,
                scale=render_scale,
                rotation=0,
                callback=callback,
                priority=RenderPriority.NEARBY_PREFETCH,
                invert=page.invert,
                bitonal=page.bitonal,
            )
        elif strategy.load_overlay and page.overlay_image_path:
            render_scale = self._cacheable_prefetch_scale(
                strategy.pdf_width_pts,
                strategy.pdf_height_pts,
                strategy.view_scale,
            )
            if render_scale is None:
                return
            request_id = self._rendering_service.render_overlay_async(
                page=page,
                bid_ref=bid_ref,
                view_scale=strategy.view_scale,
                show_mode=page.image_show_mode,
                rotation=page.rotation,
                callback=callback,
                priority=RenderPriority.NEARBY_PREFETCH,
                render_scale=render_scale,
            )
        if not request_id:
            return
        with self._lock:
            if generation != self._generation:
                cancel_now = True
            elif request_id in self._completed_request_ids:
                self._completed_request_ids.remove(request_id)
                cancel_now = False
            else:
                self._active_request_ids.add(request_id)
                cancel_now = False
        if cancel_now:
            self._rendering_service.cancel_request(request_id)

    def _on_prefetch_complete(self, result: RenderResult, generation: int) -> None:
        with self._lock:
            stale = generation != self._generation
            if stale:
                self._active_request_ids.discard(result.request_id)
                return
            if result.request_id in self._active_request_ids:
                self._active_request_ids.remove(result.request_id)
            else:
                self._completed_request_ids.add(result.request_id)

    def _cacheable_prefetch_scale(
        self,
        pdf_width_pts: float,
        pdf_height_pts: float,
        desired_scale: float,
    ) -> Optional[float]:
        render_scale = PageCache.cacheable_base_render_scale(
            pdf_width_pts,
            pdf_height_pts,
            desired_scale,
        )
        if not self._page_cache.can_accept_prefetch_render(
            pdf_width_pts,
            pdf_height_pts,
            render_scale,
        ):
            return None
        return render_scale
