from typing import Any, Callable, List, Optional
from PySide6.QtCore import QObject, Signal
from ...application.dtos.mesh_geometry_dto import MeshGeometry


class QtSceneNotifier(QObject):
    _scene_ready = Signal(list, object, int)
    _full_refresh = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._on_scene_ready: Optional[
            Callable[[List[MeshGeometry], Any, int], None]
        ] = None
        self._on_full_refresh: Optional[Callable[[str], None]] = None

    def set_handlers(
        self,
        on_scene_ready: Callable[[List[MeshGeometry], Any, int], None],
        on_full_refresh: Callable[[str], None],
    ) -> None:
        if self._on_scene_ready is not None:
            try:
                self._scene_ready.disconnect(self._on_scene_ready)
            except (TypeError, RuntimeError):
                pass
        if self._on_full_refresh is not None:
            try:
                self._full_refresh.disconnect(self._on_full_refresh)
            except (TypeError, RuntimeError):
                pass
        self._on_scene_ready = on_scene_ready
        self._on_full_refresh = on_full_refresh
        self._scene_ready.connect(on_scene_ready)
        self._full_refresh.connect(on_full_refresh)

    def notify_scene_ready(
        self, geometries: List[MeshGeometry], bounds: Any, gen_id: int
    ) -> None:
        self._scene_ready.emit(geometries, bounds, gen_id)

    def notify_full_refresh(self, file_path: str) -> None:
        self._full_refresh.emit(file_path)

    def cleanup(self) -> None:
        self.blockSignals(True)
        if self._on_scene_ready is not None:
            try:
                self._scene_ready.disconnect(self._on_scene_ready)
            except (TypeError, RuntimeError):
                pass
            self._on_scene_ready = None
        if self._on_full_refresh is not None:
            try:
                self._full_refresh.disconnect(self._on_full_refresh)
            except (TypeError, RuntimeError):
                pass
            self._on_full_refresh = None
