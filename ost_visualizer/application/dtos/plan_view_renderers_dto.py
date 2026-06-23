from dataclasses import dataclass
from typing import Any
from ..interfaces.i_linear_geometry import ILinearGeometry
from ..interfaces.i_page_load_strategy_service import IPageLoadStrategyService
from ..interfaces.i_page_rendering_service import IPageRenderingService


@dataclass(frozen=True)
class PlanViewRenderers:
    page_cache: Any
    rendering_service: IPageRenderingService
    load_coordinator: IPageLoadStrategyService
    prefetch_coordinator: Any
    takeoff_renderer: Any
    annotation_renderer: Any
    linear_geometry: ILinearGeometry
