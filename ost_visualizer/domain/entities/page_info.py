from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class BidPageInfo:
    name: str
    image_path: Optional[str] = None
    width_pts: float = 0.0
    height_pts: float = 0.0
    scale_factor1: float = 1.0
    scale_factor2: float = 1.0
    rotation: int = 0
    flip_x: bool = False
    flip_y: bool = False
    page_index: int = 0
    layer_visible: bool = True
    overlay_image_path: Optional[str] = None
    overlay_offset_x: float = 0.0
    overlay_offset_y: float = 0.0
    overlay_rotation: float = 0.0
    overlay_resized: bool = False
    deskew_rotation_overlay: float = 0.0
    overlay_rect: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    image_show_mode: int = 0
    zoom_fac: float = 0.0
    current_x: float = 0.0
    current_y: float = 0.0
    invert: bool = False
    bitonal: bool = False
