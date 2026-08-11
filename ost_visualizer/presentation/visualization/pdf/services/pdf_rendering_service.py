import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Tuple
from PySide6.QtCore import QObject, Signal
from .....application.dtos.render_result_dto import RenderResult
from .....domain.entities.identity_refs import BidRef
from .....domain.entities.page import Page
from ...utils.image_effects import apply_page_image_effects, tint_image
from .. import ost_pdf
from ..page_cache import PageCache, scoped_pdf_render_cancellation_token
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
    callback: Callable[[RenderResult], None]
    cancelled: threading.Event = field(default_factory=threading.Event)
    native_cancel_token: ost_pdf.RenderCancelToken = field(
        default_factory=ost_pdf.RenderCancelToken
    )
    apply_invert_effect: bool = True
    apply_bitonal_effect: bool = True
    frame_x_pts: float = 0.0
    frame_y_pts: float = 0.0
    frame_w_pts: float = 0.0
    frame_h_pts: float = 0.0
    wait_for_in_flight: bool = True


@dataclass
class PdfTextRequest:
    request_id: str
    file_path: str
    page_index: int
    priority: int
    callback: Callable[[RenderResult], None]
    cancelled: threading.Event = field(default_factory=threading.Event)
    native_cancel_token: ost_pdf.RenderCancelToken = field(
        default_factory=ost_pdf.RenderCancelToken
    )


_QueuedRequest = RenderRequest | PdfTextRequest


class RenderBridge(QObject):
    result_ready = Signal(object, object)

    def __init__(self, request_finished: Callable[[str], None]):
        super().__init__()
        self._request_finished = request_finished
        self._closed = threading.Event()
        self.result_ready.connect(self._dispatch_result)

    def request_callback(self, request: _QueuedRequest, result: RenderResult):
        if self._closed.is_set():
            self._finish_request(request.request_id)
            return
        self.result_ready.emit(request, result)

    def _dispatch_result(self, request: _QueuedRequest, result: RenderResult):
        try:
            if self._closed.is_set() or request.cancelled.is_set():
                return
            try:
                request.callback(result)
            except Exception as exc:
                logger.exception("Callback error: %s", exc)
        finally:
            self._finish_request(request.request_id)

    def _finish_request(self, request_id: str) -> None:
        callback = self._request_finished
        if callback is not None:
            callback(request_id)

    def cleanup(self) -> None:
        self._closed.set()
        self._request_finished = None
        try:
            self.result_ready.disconnect(self._dispatch_result)
        except (RuntimeError, TypeError):
            pass


class PDFRenderingService:
    def __init__(self, page_cache: PageCache, num_workers: int = 2):
        self._page_cache = page_cache
        self._composite_renderer = CompositeRenderer(page_cache)
        self._request_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._active_requests: Dict[str, _QueuedRequest] = {}
        self._worker_threads: List[threading.Thread] = []
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()
        self._request_counter = 0
        self._render_bridge = RenderBridge(self._cleanup_request)
        self._start_workers(num_workers)

    def _enqueue_request(self, request: _QueuedRequest) -> str:
        with self._lock:
            if self._shutdown_event.is_set():
                raise RuntimeError("PDF rendering service is shut down")
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
        invert: bool = False,
        bitonal: bool = False,
        tint_rgb: Optional[tuple[int, int, int]] = None,
        apply_invert_effect: bool = True,
        apply_bitonal_effect: bool = True,
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
            callback=callback,
            apply_invert_effect=apply_invert_effect,
            apply_bitonal_effect=apply_bitonal_effect,
        )
        return self._enqueue_request(request)

    def render_frame_async(
        self,
        file_path: str,
        page_index: int,
        scale: float,
        rotation: int,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        callback: Callable[[RenderResult], None],
        priority: int = 1,
        invert: bool = False,
        bitonal: bool = False,
        tint_rgb: Optional[tuple[int, int, int]] = None,
    ) -> str:
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="frame",
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
            callback=callback,
            frame_x_pts=frame_x_pts,
            frame_y_pts=frame_y_pts,
            frame_w_pts=frame_w_pts,
            frame_h_pts=frame_h_pts,
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
            callback=callback,
        )
        return self._enqueue_request(request)

    def render_overlay_async(
        self,
        page: Page,
        show_mode: int,
        rotation: int,
        render_scale: float,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
        apply_invert_effect: bool = True,
        apply_bitonal_effect: bool = True,
    ) -> str:
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="overlay",
            file_path=page.overlay_image_path,
            page_index=0,
            scale=render_scale,
            rotation=rotation,
            tint_rgb=(80, 80, 255) if show_mode == 2 else None,
            invert=page.invert,
            bitonal=page.bitonal,
            priority=priority,
            page_entity=page,
            bid_ref=None,
            callback=callback,
            apply_invert_effect=apply_invert_effect,
            apply_bitonal_effect=apply_bitonal_effect,
        )
        return self._enqueue_request(request)

    def render_composite_frame_async(
        self,
        page: Page,
        bid_ref: Optional[BidRef],
        scale: float,
        rotation: int,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        callback: Callable[[RenderResult], None],
        priority: int = 1,
    ) -> str:
        page_snapshot = _snapshot_page_for_render(page)
        request = RenderRequest(
            request_id=str(uuid.uuid4()),
            request_type="composite_frame",
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
            callback=callback,
            frame_x_pts=frame_x_pts,
            frame_y_pts=frame_y_pts,
            frame_w_pts=frame_w_pts,
            frame_h_pts=frame_h_pts,
        )
        return self._enqueue_request(request)

    def extract_pdf_text_async(
        self,
        file_path: str,
        page_index: int,
        callback: Callable[[RenderResult], None],
        priority: int = 2,
    ) -> str:
        request = PdfTextRequest(
            request_id=str(uuid.uuid4()),
            file_path=file_path,
            page_index=page_index,
            priority=priority,
            callback=callback,
        )
        return self._enqueue_request(request)

    def cancel_request(self, request_id: str) -> None:
        with self._lock:
            request = self._active_requests.get(request_id)
            if request:
                request.cancelled.set()
                request.native_cancel_token.cancel()

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
                _priority, _counter, request = self._request_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if request is None:
                break
            if request.cancelled.is_set():
                self._cleanup_request(request.request_id)
                continue
            with scoped_pdf_render_cancellation_token(request.native_cancel_token):
                result = self._execute_render(request)
            result_posted = False
            if not request.cancelled.is_set():
                bridge = self._render_bridge
                if bridge is not None:
                    bridge.request_callback(request, result)
                    result_posted = True
            if not result_posted:
                self._cleanup_request(request.request_id)

    def _execute_render(self, request: _QueuedRequest) -> RenderResult:
        try:
            if isinstance(request, PdfTextRequest):
                return self._execute_pdf_text(request)
            if request.request_type == "page":
                return self._execute_page_render(request)
            elif request.request_type == "tinted_page":
                return self._execute_tinted_render(request)
            elif request.request_type == "composite":
                return self._execute_composite(request)
            elif request.request_type == "overlay":
                return self._execute_overlay(request)
            elif request.request_type == "frame":
                return self._execute_frame_render(request)
            elif request.request_type == "composite_frame":
                return self._execute_composite_frame(request)
            else:
                return RenderResult(
                    request.request_id,
                    False,
                    None,
                    f"Unknown request type: {request.request_type}",
                )
        except Exception as exc:
            logger.exception("Render error: %s", exc)
            return RenderResult(request.request_id, False, None, str(exc))

    def _execute_page_render(self, request: RenderRequest) -> RenderResult:
        image = self._page_cache.get_page(
            request.file_path,
            request.page_index,
            request.scale,
            request.rotation,
            wait_for_in_flight=request.wait_for_in_flight,
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
            wait_for_in_flight=request.wait_for_in_flight,
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
            wait_for_in_flight=request.wait_for_in_flight,
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

    def _execute_pdf_text(self, request: PdfTextRequest) -> RenderResult:
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

    def _execute_frame_render(self, request: RenderRequest) -> RenderResult:
        image = self._page_cache.get_frame(
            request.file_path,
            request.page_index,
            request.scale,
            request.frame_x_pts,
            request.frame_y_pts,
            request.frame_w_pts,
            request.frame_h_pts,
            request.rotation,
            wait_for_in_flight=request.wait_for_in_flight,
        )
        if request.cancelled.is_set() or not image:
            return RenderResult(request.request_id, False, None, "Cancelled or failed")
        if request.tint_rgb:
            image = tint_image(image, *request.tint_rgb)
        return RenderResult(
            request.request_id, True, self._apply_image_effects(request, image), None
        )

    def _execute_composite_frame(self, request: RenderRequest) -> RenderResult:
        page = request.page_entity
        if not page:
            return RenderResult(request.request_id, False, None, "No page entity")
        composited = self._composite_renderer.render_composite_frame(
            page,
            request.scale,
            request.frame_x_pts,
            request.frame_y_pts,
            request.frame_w_pts,
            request.frame_h_pts,
            request.rotation,
            cancelled_check=lambda: request.cancelled.is_set(),
            wait_for_in_flight=request.wait_for_in_flight,
        )
        if not composited:
            return RenderResult(
                request.request_id,
                False,
                None,
                "Failed to render composite frame",
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
                wait_for_in_flight=request.wait_for_in_flight,
            )
        else:
            overlay_image = self._page_cache.get_page(
                request.file_path,
                request.page_index,
                request.scale,
                request.rotation,
                wait_for_in_flight=request.wait_for_in_flight,
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
            bitonal=request.bitonal and request.apply_bitonal_effect,
            invert=request.invert and request.apply_invert_effect,
        )

    def _cleanup_request(self, request_id: str):
        with self._lock:
            self._active_requests.pop(request_id, None)

    def shutdown(self) -> None:
        if self._page_cache is None:
            return
        first_shutdown = not self._shutdown_event.is_set()
        sentinels = []
        if first_shutdown:
            self._shutdown_event.set()
            with self._lock:
                for request in self._active_requests.values():
                    request.cancelled.set()
                    request.native_cancel_token.cancel()
                for _ in self._worker_threads:
                    counter = self._request_counter
                    self._request_counter += 1
                    sentinels.append((0, counter, None))
            for sentinel in sentinels:
                self._request_queue.put_nowait(sentinel)
        for thread in self._worker_threads:
            thread.join(timeout=3.0)
        live_workers = [thread for thread in self._worker_threads if thread.is_alive()]
        if live_workers:
            self._worker_threads = live_workers
            logger.error(
                "PDF rendering shutdown retained resources for %d live worker(s)",
                len(live_workers),
            )
            return
        self._worker_threads.clear()
        with self._lock:
            self._active_requests.clear()
        while not self._request_queue.empty():
            try:
                self._request_queue.get_nowait()
            except queue.Empty:
                break
        self._render_bridge.cleanup()
        self._composite_renderer.clear_cache()
        self._page_cache.clear()
        self._render_bridge = None
        self._composite_renderer = None
        self._page_cache = None
