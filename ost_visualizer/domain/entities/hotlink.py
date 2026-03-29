from dataclasses import dataclass
from typing import Optional
from .annotation import BidAnnotation


@dataclass
class Hotlink:
    uid: str
    bid_page_uid: str
    bid_layer_uid: Optional[str]
    position_x: float
    position_y: float
    color: str
    target_view_uid: Optional[str] = None
    width: float = 2.0


def build_hotlink_from_annotation(annotation: BidAnnotation) -> Optional[Hotlink]:
    if not annotation.is_hotlink:
        return None
    position = annotation.position
    pos_x = position[0] if len(position) > 0 else 0.0
    pos_y = position[1] if len(position) > 1 else 0.0
    return Hotlink(
        uid=annotation.uid,
        bid_page_uid=annotation.page_uid,
        bid_layer_uid=annotation.layer_uid,
        position_x=pos_x,
        position_y=pos_y,
        color=annotation.color,
        target_view_uid=annotation.properties.get("BidPageViewUID"),
        width=annotation.width,
    )
