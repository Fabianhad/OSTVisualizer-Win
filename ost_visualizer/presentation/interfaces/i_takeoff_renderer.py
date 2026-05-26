from typing import Any, Dict, List, Optional, Protocol, Tuple
from PySide6.QtGui import QBrush, QColor, QPainterPath
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem
from ...application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ...domain.entities.condition import Condition
from ...domain.entities.takeoff import Takeoff


class ITakeoffRenderer(Protocol):
    @property
    def coordinate_system(self) -> ICoordinateTransformer: ...
    def set_page_info(self, page_info: Dict[str, Any]) -> None: ...
    def create_all_path_items(
        self,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        opacity: float = 0.5,
        page_info: Optional[Dict[str, Any]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> List[Tuple[str, QGraphicsItem | List[QGraphicsItem]]]: ...
    def build_pattern_fill(
        self,
        path: QPainterPath,
        pattern_type: int,
        color: QColor,
        opacity: float,
        spacing: float,
        line_width: float,
        orientation_angle: Optional[float] = None,
    ) -> Tuple[Optional[QBrush], List[QGraphicsPathItem]]: ...
