from typing import Any, Dict, List, Optional, Protocol, Tuple
from PySide6.QtWidgets import QGraphicsItem
from ...application.dtos.hotlink_dto import HotlinkDto
from ...application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ...domain.entities.annotation import BidAnnotation

AnnotationItemResult = Tuple[QGraphicsItem, Optional[HotlinkDto]]
AnnotationItemsResult = Tuple[
    List[AnnotationItemResult], Dict[str, List[QGraphicsItem]]
]


class IAnnotationItemRenderer(Protocol):
    @property
    def coordinate_system(self) -> ICoordinateTransformer: ...
    def set_page_info(self, page_info: Dict[str, Any]) -> None: ...
    def create_all_annotation_items(
        self,
        annotations: List[Tuple[str, BidAnnotation]],
        page_info: Optional[Dict[str, Any]] = None,
        bid_page_uid: Optional[str] = None,
    ) -> AnnotationItemsResult: ...
