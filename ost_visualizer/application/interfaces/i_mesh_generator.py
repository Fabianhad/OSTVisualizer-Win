from typing import Any, Dict, List, Optional, Protocol, Tuple, Union
from ...domain.entities.condition import Condition
from ...domain.entities.config import Config
from ...domain.entities.takeoff import Takeoff


class MeshData:
    def __init__(
        self,
        vertices: List[Tuple[float, float, float]],
        faces: List[Tuple[int, int, int]],
        edges: List[Tuple[int, int]] = None,
        metadata: Dict[str, Any] = None,
    ):
        self.vertices = vertices
        self.faces = faces
        self.edges = edges or []
        self.metadata = metadata or {}

    def __bool__(self):
        return bool(self.vertices and self.faces)


class IMeshGenerator(Protocol):
    def generate_meshes(
        self,
        bid_conditions: Dict[str, Condition],
        bid_takeoffs: List[Takeoff],
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
        display_mode: str = Config.DISPLAY_MODE_SOLID,
        grayscale_enabled: bool = True,
    ) -> Tuple[
        List[MeshData],
        Dict[str, Union[str, Dict[str, object]]],
        Tuple[float, float, float, float, float, float],
    ]: ...
