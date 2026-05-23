from typing import Dict
from ...domain.entities.page import Page


def build_page_info(
    page: Page,
    pdf_width_pts: float,
    pdf_height_pts: float,
    view_scale: float,
    rotation: int,
) -> Dict:
    return {
        "scale_factor1": page.scale_factor1 or 1.0,
        "scale_factor2": page.scale_factor2 or 1.0,
        "rotation": rotation,
        "flip_x": 1 if page.flip_x else 0,
        "flip_y": 1 if page.flip_y else 0,
        "width": pdf_width_pts,
        "height": pdf_height_pts,
        "view_scale": view_scale,
    }
