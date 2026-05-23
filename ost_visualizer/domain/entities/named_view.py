from dataclasses import dataclass
from typing import Optional
from .annotation import BidAnnotation


@dataclass
class NamedView:
    uid: str
    bid_page_uid: str
    name: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    center_x: float
    center_y: float
    width: float
    height: float


def build_named_view_from_annotation(
    annotation: BidAnnotation,
) -> Optional[NamedView]:
    if not annotation.is_namedview:
        return None
    position = annotation.position
    if len(position) < 8:
        return None
    xs = [position[i] for i in range(0, 8, 2)]
    ys = [position[i + 1] for i in range(0, 8, 2)]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return NamedView(
        uid=annotation.uid,
        bid_page_uid=annotation.page_uid,
        name=annotation.properties.get("Text", ""),
        min_x=min_x,
        min_y=min_y,
        max_x=max_x,
        max_y=max_y,
        center_x=(min_x + max_x) / 2,
        center_y=(min_y + max_y) / 2,
        width=max_x - min_x,
        height=max_y - min_y,
    )
