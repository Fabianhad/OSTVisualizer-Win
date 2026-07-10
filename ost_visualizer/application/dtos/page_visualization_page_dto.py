from typing import Optional, TypedDict


class PageVisualizationPageDto(TypedDict):
    uid: str
    label: str
    name: str
    sheet_no: str
    sequence: int
    width: float
    height: float
    page_width: float
    page_height: float
    image_layer_uid: str
    pdf_path: Optional[str]
    pdf_page_index: int
    scale_ratio: float
    rotation: int
    flip_x: bool
    flip_y: bool
