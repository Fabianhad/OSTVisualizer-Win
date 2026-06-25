from typing import TypedDict


class MeshMetadata(TypedDict, total=False):
    IsNegativeQuantity: bool
    color: str
    opacity: float
    name: str
    cdn_type_uid: str
    cdn_type_name: str
    condition_color: str
    condition_ref_no: int
    takeoff_uid: str
    page_uid: str
    area_uid: str
    area_name: str
    condition_uid: str
    condition_type: int
    layer_uid: str
    visible: bool
