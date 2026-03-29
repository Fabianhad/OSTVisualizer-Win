from typing import Any, Dict, Protocol
from ...domain.entities.page import Page


class ILoadStrategy(Protocol):
    needs_async_loading: bool
    view_scale: float
    show_canvas: bool
    pdf_width_pts: float
    pdf_height_pts: float
    placeholder_width: float
    placeholder_height: float
    load_composite: bool
    load_main: bool
    load_overlay: bool
    main_scale: float
    overlay_scale: float


class IPageLoadStrategyService(Protocol):
    def determine_load_strategy(self, page: Page) -> ILoadStrategy: ...
    def create_pending_page_data(
        self,
        page: Page,
        strategy: ILoadStrategy,
        pdf_width_pts: float,
        pdf_height_pts: float,
    ) -> Dict[str, Any]: ...
