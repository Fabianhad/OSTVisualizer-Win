from typing import TypedDict


class MeshMetadata(TypedDict, total=False):
    IsNegativeQuantity: bool
    color: str
    opacity: float
    name: str
    cdn_type: str
    takeoff_uid: str
    condition_uid: str
    condition_type: int
