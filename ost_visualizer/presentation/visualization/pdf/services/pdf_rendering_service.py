import logging
import queue
import threading
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Tuple
from PySide6.QtCore import QObject, Signal
from .....application.dtos.render_result_dto import RenderResult
from .....domain.entities.identity_refs import BidRef
from .....domain.entities.page import Page
from ...utils.image_effects import apply_page_image_effects, tint_image
from ..page_cache import PageCache
from .composite_renderer import CompositeRenderer

logger = logging.getLogger(__name__)


def _snapshot_page_for_render(page: Page) -> Page:
    return replace(
        page,
        takeoffs=list(page.takeoffs),
        overlay_rect=tuple(page.overlay_rect),
    )


@dataclass
class RenderRequest:
    request_id: str
    request_type: str
    file_path: str
    page_index: int
    scale: float
    rotation: int
    tint_rgb: Optional[Tuple[int, int, int]]
    invert: bool
    bitonal: bool
    priority: int
    page_entity: Optional[Page]
    bid_ref: Optional[BidRef]
    view_scale: Optional[float]
    show_mode: Optional[int]
    cancelled: threading.Event
    callback: Callable[[RenderResult], None]
    use_cache: bool = True
    tile_x: int = 0
    tile_y: int = 0
    tile_w: int = 0
    tile_h: int = 0


class RenderBridge(QObject):
    result_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self._callbacks: Dict[str, Callable] = {}
        self.result_ready.connect(self._dispatch_result)

    def request_callback(
        self, request_id: str, callback: Callable, result: RenderResult
    ):
        self._callbacks[request_id] = callback
        self.result_ready.emit(result)

    def _dispatch_result(self, result: RenderResult):
        callback = self._callbacks.pop(result.request_id, None)
        if callback:
            try:
                callback(result)
            except Exception as exc:
                logger.exception(f"Callback error: {exc}")


class PDFRenderingService:
    def __init__(self, page_cache: PageCache, num_workers: int = 2):
        self._page_cache = page_cache
        self._render_bridge = RenderBridge()
        self._composite_renderer = CompositeRenderer(page_cache)
        self._request_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._active_requests: Dict[str, RenderRequest] = {}
        self._worker_threads: List[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._request_counter = 0
        self._start_workers(num_workers)

    def _enqueue_request(self, request: RenderRequest) -> str:
        with self._lock:
            self._active_requests[request.request_id] = request
            counter = self._request_counter
            self._request_counter += 1
        self._request_queue.put((request.priority, counter, request))
        return request.request_id

    def render_page_async(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
        use_cache: bool = True,
        invert: bool = False,
        bitonal: bool = False,
        tint_rgb: Optional[tuple[int, int, int]] = None,
    ) -> str:
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="tinted_page" if tint_rgb else "page",
            file_path=file_path,
            page_index=page_index,
            scale=scale,
            rotation=rotation,
            tint_rgb=tint_rgb,
            invert=invert,
            bitonal=bitonal,
            priority=priority,
            page_entity=None,
            bid_ref=None,
            view_scale=None,
            show_mode=None,
            cancelled=threading.Event(),
            callback=callback,
            use_cache=use_cache,
        )
        return self._enqueue_request(request)

    def render_region_async(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        tile_x: int,
        tile_y: int,
        tile_w: int,
        tile_h: int,
        callback: Callable[[RenderResult], None],
        priority: int = 1,
        invert: bool = False,
        bitonal: bool = False,
        tint_rgb: Optional[tuple[int, int, int]] = None,
    ) -> str:
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="region",
            file_path=file_path,
            page_index=page_index,
            scale=scale,
            rotation=rotation,
            tint_rgb=tint_rgb,
            invert=invert,
            bitonal=bitonal,
            priority=priority,
            page_entity=None,
            bid_ref=None,
            view_scale=None,
            show_mode=None,
            cancelled=threading.Event(),
            callback=callback,
            tile_x=tile_x,
            tile_y=tile_y,
            tile_w=tile_w,
            tile_h=tile_h,
        )
        return self._enqueue_request(request)

    def render_composite_async(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        render_scale: float,
        rotation: int,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
    ) -> str:
        page_snapshot = _snapshot_page_for_render(page)
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="composite",
            file_path=page_snapshot.image_path,
            page_index=page_snapshot.page_index,
            scale=render_scale,
            rotation=rotation,
            tint_rgb=None,
            invert=page_snapshot.invert,
            bitonal=page_snapshot.bitonal,
            priority=priority,
            page_entity=page_snapshot,
            bid_ref=bid_ref,
            view_scale=None,
            show_mode=None,
            cancelled=threading.Event(),
            callback=callback,
        )
        return self._enqueue_request(request)

    def render_overlay_async(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        view_scale: float,
        show_mode: int,
        rotation: int,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
        render_scale: Optional[float] = None,
    ) -> str:
        scale = render_scale
        if scale is None:
            scale = 2.0 if page.overlay_image_path.lower().endswith(".pdf") else 1.0
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="overlay",
            file_path=page.overlay_image_path,
            page_index=0,
            scale=scale,
            rotation=rotation,
            tint_rgb=(80, 80, 255) if show_mode == 2 else None,
            invert=page.invert,
            bitonal=page.bitonal,
            priority=priority,
            page_entity=page,
            bid_ref=bid_ref,
            view_scale=view_scale,
            show_mode=show_mode,
            cancelled=threading.Event(),
            callback=callback,
        )
        return self._enqueue_request(request)

    def render_composite_region_async(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        scale: float,
        rotation: int,
        tile_x: int,
        tile_y: int,
        tile_w: int,
        tile_h: int,
        callback: Callable[[RenderResult], None],
        priority: int = 1,
    ) -> str:
        page_snapshot = _snapshot_page_for_render(page)
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="composite_region",
            file_path=page_snapshot.image_path,
            page_index=page_snapshot.page_index,
            scale=scale,
            rotation=rotation,
            tint_rgb=None,
            invert=page_snapshot.invert,
            bitonal=page_snapshot.bitonal,
            priority=priority,
            page_entity=page_snapshot,
            bid_ref=bid_ref,
            view_scale=None,
            show_mode=None,
            cancelled=threading.Event(),
            callback=callback,
            tile_x=tile_x,
            tile_y=tile_y,
            tile_w=tile_w,
            tile_h=tile_h,
        )
        return self._enqueue_request(request)

    def extract_pdf_text_async(
        self,
        file_path: str,
        page_index: int,
        callback: Callable[[RenderResult], None],
        priority: int = 2,
    ) -> str:
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="pdf_text",
            file_path=file_path,
            page_index=page_index,
            scale=1.0,
            rotation=0,
            tint_rgb=None,
            invert=False,
            bitonal=False,
            priority=priority,
            page_entity=None,
            bid_ref=None,
            view_scale=None,
            show_mode=None,
            cancelled=threading.Event(),
            callback=callback,
        )
        return self._enqueue_request(request)

    def cancel_request(self, request_id: str) -> None:
        with self._lock:
            request = self._active_requests.get(request_id)
            if request:
                request.cancelled.set()

    def _start_workers(self, num_workers: int):
        for i in range(num_workers):
            thread = threading.Thread(
                target=self._worker_loop, daemon=True, name=f"PDFRenderWorker-{i}"
            )
            self._worker_threads.append(thread)
            thread.start()

    def _worker_loop(self):
        while not self._shutdown_event.is_set():
            try:
                priority, counter, request = self._request_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if request is None:
                break
            if request.cancelled.is_set():
                self._cleanup_request(request.request_id)
                continue
            result = self._execute_render(request)
            if not request.cancelled.is_set():
                self._render_bridge.request_callback(
                    request.request_id, request.callback, result
                )
            self._cleanup_request(request.request_id)

    def _execute_render(self, request: RenderRequest) -> RenderResult:
        try:
            if request.request_type == "page":
                return self._execute_page_render(request)
            elif request.request_type == "tinted_page":
                return self._execute_tinted_render(request)
            elif request.request_type == "composite":
                return self._execute_composite(request)
            elif request.request_type == "overlay":
                return self._execute_overlay(request)
            elif request.request_type == "region":
                return self._execute_region_render(request)
            elif request.request_type == "composite_region":
                return self._execute_composite_region(request)
            elif request.request_type == "pdf_text":
                return self._execute_pdf_text(request)
            else:
                return RenderResult(
                    request.request_id,
                    False,
                    None,
                    f"Unknown request type: {request.request_type}",
                )
        except Exception as exc:
            logger.exception(f"Render error: {exc}")
            return RenderResult(request.request_id, False, None, str(exc))

    def _execute_page_render(self, request: RenderRequest) -> RenderResult:
        if request.use_cache:
            image = self._page_cache.get_page(
                request.file_path, request.page_index, request.scale, request.rotation
            )
        else:
            image = self._page_cache.render_uncached(
                request.file_path, request.page_index, request.scale, request.rotation
            )
        if request.cancelled.is_set():
            return RenderResult(request.request_id, False, None, "Cancelled")
        if not image:
            return RenderResult(
                request.request_id, False, None, "Failed to render page"
            )
        return RenderResult(
            request.request_id, True, self._apply_image_effects(request, image), None
        )

    def _execute_tinted_render(self, request: RenderRequest) -> RenderResult:
        tinted = self._page_cache.get_tinted_page(
            request.file_path,
            request.page_index,
            request.scale,
            request.rotation,
            tint_rgb=request.tint_rgb,
        )
        if request.cancelled.is_set() or not tinted:
            return RenderResult(request.request_id, False, None, "Cancelled or failed")
        return RenderResult(
            request.request_id, True, self._apply_image_effects(request, tinted), None
        )

    def _execute_composite(self, request: RenderRequest) -> RenderResult:
        page = request.page_entity
        composited = self._composite_renderer.render_composite(
            page,
            request.bid_ref,
            request.scale,
            request.rotation,
            cancelled_check=lambda: request.cancelled.is_set(),
        )
        if not composited:
            return RenderResult(
                request.request_id, False, None, "Failed to render composite"
            )
        return RenderResult(
            request.request_id,
            True,
            self._apply_image_effects(request, composited),
            None,
        )

    def _execute_pdf_text(self, request: RenderRequest) -> RenderResult:
        text_runs = self._page_cache.get_text_runs(
            request.file_path, request.page_index
        )
        page_info = self._page_cache.get_page_info(
            request.file_path, request.page_index
        )
        if request.cancelled.is_set():
            return RenderResult(request.request_id, False, None, "Cancelled")
        return RenderResult(
            request.request_id,
            True,
            {"text_runs": text_runs, "page_info": page_info},
            None,
        )

    def _execute_region_render(self, request: RenderRequest) -> RenderResult:
        image = self._page_cache.render_region_uncached(
            request.file_path,
            request.page_index,
            request.scale,
            request.tile_x,
            request.tile_y,
            request.tile_w,
            request.tile_h,
            request.rotation,
        )
        if request.cancelled.is_set() or not image:
            return RenderResult(request.request_id, False, None, "Cancelled or failed")
        if request.tint_rgb:
            image = tint_image(image, *request.tint_rgb)
        return RenderResult(
            request.request_id, True, self._apply_image_effects(request, image), None
        )

    def _execute_composite_region(self, request: RenderRequest) -> RenderResult:
        page = request.page_entity
        if not page:
            return RenderResult(request.request_id, False, None, "No page entity")
        composited = self._composite_renderer.render_composite_region(
            page,
            request.scale,
            request.tile_x,
            request.tile_y,
            request.tile_w,
            request.tile_h,
            request.rotation,
            cancelled_check=lambda: request.cancelled.is_set(),
        )
        if not composited:
            return RenderResult(
                request.request_id,
                False,
                None,
                "Failed to render composite region",
            )
        return RenderResult(
            request.request_id,
            True,
            self._apply_image_effects(request, composited),
            None,
        )

    def _execute_overlay(self, request: RenderRequest) -> RenderResult:
        if request.tint_rgb:
            overlay_image = self._page_cache.get_tinted_page(
                request.file_path,
                request.page_index,
                request.scale,
                request.rotation,
                tint_rgb=request.tint_rgb,
            )
        else:
            overlay_image = self._page_cache.get_page(
                request.file_path, request.page_index, request.scale, request.rotation
            )
        if request.cancelled.is_set() or not overlay_image:
            return RenderResult(request.request_id, False, None, "Cancelled or failed")
        return RenderResult(
            request.request_id,
            True,
            self._apply_image_effects(request, overlay_image),
            None,
        )

    def _apply_image_effects(self, request: RenderRequest, image):
        return apply_page_image_effects(
            image,
            bitonal=request.bitonal,
            invert=request.invert,
        )

    def _cleanup_request(self, request_id: str):
        with self._lock:
            self._active_requests.pop(request_id, None)

    def shutdown(self):
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        with self._lock:
            for request in self._active_requests.values():
                request.cancelled.set()
        for _ in range(len(self._worker_threads)):
            try:
                self._request_queue.put_nowait((0, 0, None))
            except queue.Full:
                break
        for thread in self._worker_threads:
            thread.join(timeout=3.0)
        self._worker_threads.clear()
        with self._lock:
            self._active_requests.clear()
        while not self._request_queue.empty():
            try:
                self._request_queue.get_nowait()
            except queue.Empty:
                break
        self._render_bridge._callbacks.clear()
        self._composite_renderer.clear_cache()
        self._page_cache.clear()
        self._render_bridge = None
        self._composite_renderer = None
        self._page_cache = None
