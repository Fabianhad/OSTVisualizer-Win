from dataclasses import dataclass

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
