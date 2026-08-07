from typing import Dict, List, Optional, Protocol
from ...domain.entities.area import BidArea
from ...domain.entities.condition import Condition
from ...domain.entities.config import Config
from ...domain.entities.elevation_callout import (
    DEFAULT_ELEVATION_CALLOUT_SETTINGS,
    ElevationCalloutSettings,
)
from ...domain.entities.layer import BidLayer
from ...domain.entities.takeoff import Takeoff
from ..dtos.page_visualization_page_dto import PageVisualizationPageDto
from ..dtos.scene_data_dto import ScenePageImageLayer


class IHtmlRenderer(Protocol):
    def render(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        output_path: str,
        title: str = "3D Visualization",
        display_mode_3d: str = Config.DISPLAY_MODE_SOLID,
        display_mode_2d: str = Config.DISPLAY_MODE_SOLID,
        display_modes_synced: bool = True,
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        auto_open: bool = False,
        pages: Optional[List[PageVisualizationPageDto]] = None,
        active_page_uid: str = "",
        layers: Optional[List[BidLayer]] = None,
        areas: Optional[List[BidArea]] = None,
        page_image_layer: Optional[ScenePageImageLayer] = None,
        *,
        inactive_object_color: str,
        include_elevation_callouts: bool,
        elevation_callout_settings: ElevationCalloutSettings = (
            DEFAULT_ELEVATION_CALLOUT_SETTINGS
        ),
        elevation_callout_color: str = Config.DEFAULT_ELEVATION_CALLOUT_COLOR,
    ) -> bool: ...
