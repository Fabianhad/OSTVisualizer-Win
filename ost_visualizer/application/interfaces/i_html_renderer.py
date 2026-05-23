from typing import Dict, List, Optional, Protocol
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff


class IHtmlRenderer(Protocol):
    def render(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        output_path: str,
        title: str = "3D Visualization",
        bid_name: str = "Bid",
        color_mode: str = "Solid",
        grayscale_enabled: bool = True,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        auto_open: bool = False,
    ) -> bool: ...
