from typing import Dict, List, Optional, Protocol, Sequence, Tuple, Union
from ..dtos.mesh_geometry_dto import MeshGeometry
from .i_exporter import IExportStrategy
from .i_mesh_generator import IMeshGenerator, MeshData

Bounds = Tuple[float, float, float, float, float, float]


class IVisualizationProvider(Protocol):
    def get_mesh_generator(self) -> IMeshGenerator: ...
    def get_export_strategy(self, format_key: str) -> Optional[IExportStrategy]: ...
    def get_available_formats(self) -> List[str]: ...
    def convert_meshes_to_geometries(
        self,
        meshes: Sequence[MeshData],
        mesh_colors: Dict[str, Union[str, Dict[str, object]]],
    ) -> Tuple[List[MeshGeometry], Bounds]: ...
