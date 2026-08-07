from typing import TypedDict


class PageRenderInfo(TypedDict, total=False):
    scale_factor1: float
    scale_factor2: float
    rotation: int
    flip_x: bool
    flip_y: bool
    width: float
    height: float
    view_scale: float
    coord_offset_x: float
    coord_offset_y: float
