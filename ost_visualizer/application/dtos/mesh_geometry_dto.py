from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MeshGeometry:
    vertices: List[float]
    normals: List[float]
    indices: List[int]
    color: str
    opacity: float
    condition_uid: str
    takeoff_uid: str
