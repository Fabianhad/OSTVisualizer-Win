from dataclasses import dataclass
from typing import Optional
from ..entities.tower_crane_spec import TowerCraneSpec

INCHES_PER_METRE = 39.37007874015748


@dataclass(frozen=True)
class TowerCranePlacement:
    takeoff_uid: str
    condition_uid: str
    page_uid: str
    x: float
    y: float
    z: float
    rotation: float
    inactive: bool = False
    spec: Optional[TowerCraneSpec] = None
