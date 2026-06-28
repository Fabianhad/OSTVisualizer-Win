from typing import Callable, Protocol
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.page import Page
from ..dtos.render_result_dto import RenderResult


class IPageRenderingService(Protocol):
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
        tint_rgb: tuple[int, int, int] | None = None,
        apply_invert_effect: bool = True,
        apply_bitonal_effect: bool = True,
    ) -> str: ...
    def render_composite_async(
        self,
        page: Page,
        bid_ref: BidRef | None,
        render_scale: float,
        rotation: int,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
    ) -> str: ...
    def render_overlay_async(
        self,
        page: Page,
        bid_ref: BidRef | None,
        view_scale: float,
        show_mode: int,
        rotation: int,
        callback: Callable[[RenderResult], None],
        priority: int = 0,
        render_scale: float | None = None,
        apply_invert_effect: bool = True,
        apply_bitonal_effect: bool = True,
    ) -> str: ...
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
        tint_rgb: tuple[int, int, int] | None = None,
    ) -> str: ...
    def render_composite_frame_async(
        self,
        page: Page,
        bid_ref: BidRef | None,
        scale: float,
        rotation: int,
        frame_x_pts: float,
        frame_y_pts: float,
        frame_w_pts: float,
        frame_h_pts: float,
        callback: Callable[[RenderResult], None],
        priority: int = 1,
    ) -> str: ...
    def extract_pdf_text_async(
        self,
        file_path: str,
        page_index: int,
        callback: Callable[[RenderResult], None],
        priority: int = 2,
    ) -> str: ...
    def cancel_request(self, request_id: str) -> None: ...
    def shutdown(self) -> None: ...
