from typing import Any, Callable, List, Protocol
from ..dtos.mesh_geometry_dto import MeshGeometry


class IThreadSceneNotifier(Protocol):
    def set_handlers(
        self,
        on_scene_ready: Callable[[List[MeshGeometry], Any, int], None],
        on_full_refresh: Callable[[str], None],
    ) -> None: ...
    def notify_scene_ready(
        self, geometries: List[MeshGeometry], bounds: Any, gen_id: int
    ) -> None: ...
    def notify_full_refresh(self, file_path: str) -> None: ...
    def cleanup(self) -> None: ...
