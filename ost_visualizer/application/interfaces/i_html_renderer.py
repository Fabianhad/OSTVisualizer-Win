from typing import Dict, List, Optional, Protocol
from ...domain.entities.area import BidArea
from ...domain.entities.condition import Condition
from ...domain.entities.config import Config
from ...domain.entities.layer import BidLayer
from ...domain.entities.takeoff import Takeoff
from ..dtos.html_export_page_dto import HtmlExportPageDto
from ..dtos.scene_data_dto import ScenePageImageLayer


class IHtmlRenderer(Protocol):
    def render(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        output_path: str,
        title: str = "3D Visualization",
        bid_name: str = "Bid",
        display_mode_3d: str = Config.DISPLAY_MODE_SOLID,
        display_mode_2d: str = Config.DISPLAY_MODE_SOLID,
        display_modes_synced: bool = True,
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        auto_open: bool = False,
        pages: Optional[List[HtmlExportPageDto]] = None,
        active_page_uid: str = "",
        layers: Optional[List[BidLayer]] = None,
        areas: Optional[List[BidArea]] = None,
        page_image_layer: Optional[ScenePageImageLayer] = None,
    ) -> bool: ...
