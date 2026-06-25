from typing import Dict, List, Optional, Protocol
from ..dtos.scene_data_dto import ScenePageImageLayer
from ...domain.entities.area import BidArea
from ...domain.entities.config import Config
from ...domain.entities.condition import Condition
from ...domain.entities.layer import BidLayer
from ...domain.entities.takeoff import Takeoff


class IHtmlRenderer(Protocol):
    def render(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        output_path: str,
        title: str = "3D Visualization",
        bid_name: str = "Bid",
        color_mode: str = Config.COLOR_MODE_SOLID,
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        auto_open: bool = False,
        pdf_path: Optional[str] = None,
        pdf_page_index: int = 0,
        page_width_inches: float = 0.0,
        page_height_inches: float = 0.0,
        page_uid: str = "",
        page_width_2d: float = 0.0,
        page_height_2d: float = 0.0,
        page_scale_ratio: float = 1.0,
        page_rotation: int = 0,
        page_flip_x: bool = False,
        page_flip_y: bool = False,
        layers: Optional[List[BidLayer]] = None,
        areas: Optional[List[BidArea]] = None,
        page_image_layer: Optional[ScenePageImageLayer] = None,
    ) -> bool: ...
