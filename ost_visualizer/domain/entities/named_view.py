from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple
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


def named_view_bbox(
    position: Sequence[float],
) -> Optional[Tuple[float, float, float, float]]:
    count = len(position)
    pair_count = count // 2 if count % 2 == 0 else (count - 1) // 2
    if pair_count < 2:
        return None
    coords = list(position[: pair_count * 2])
    xs = coords[0::2]
    ys = coords[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def named_view_position_from_bounds(
    left: float, top: float, right: float, bottom: float
) -> List[float]:
    min_x, max_x = sorted((float(left), float(right)))
    min_y, max_y = sorted((float(top), float(bottom)))
    return [max_x, max_y, min_x, min_y, max_x, min_y, min_x, max_y, 0.0]


def named_view_edit_position_from_bounds(
    left: float, top: float, right: float, bottom: float
) -> List[float]:
    min_x, max_x = sorted((float(left), float(right)))
    min_y, max_y = sorted((float(top), float(bottom)))
    return [min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y]


def named_view_edit_position(position: Sequence[float]) -> List[float]:
    bbox = named_view_bbox(position)
    if bbox is None:
        return list(position)
    min_x, min_y, max_x, max_y = bbox
    return named_view_edit_position_from_bounds(min_x, min_y, max_x, max_y)


def normalize_named_view_position(position: Sequence[float]) -> List[float]:
    bbox = named_view_bbox(position)
    if bbox is None:
        return list(position)
    min_x, min_y, max_x, max_y = bbox
    return named_view_position_from_bounds(min_x, min_y, max_x, max_y)


def build_named_view_from_annotation(
    annotation: BidAnnotation,
) -> Optional[NamedView]:
    if not annotation.is_namedview:
        return None
    bbox = named_view_bbox(annotation.position)
    if bbox is None:
        return None
    min_x, min_y, max_x, max_y = bbox
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
