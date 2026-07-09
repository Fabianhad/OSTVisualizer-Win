import logging
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.mesh_geometry_dto import MeshGeometry
from ..events.app_events import AppEvents
from ..interfaces.i_thread_scene_notifier import IThreadSceneNotifier
from ..interfaces.i_transaction_monitor import ITransactionMonitor
from ..interfaces.i_visualization_provider import IVisualizationProvider
from .project_operations_service import ProjectOperationsService

logger = logging.getLogger(__name__)


class VisualizationService:
    def __init__(
        self,
        config_model,
        project_data_service: ProjectDataService,
        project_operations_service: ProjectOperationsService,
        event_bus,
        transaction_monitor: ITransactionMonitor,
        visualization_provider: IVisualizationProvider,
        scene_notifier: IThreadSceneNotifier,
    ):
        self.config_model = config_model
        self.project_data = project_data_service
        self.project_operations = project_operations_service
        self.event_bus = event_bus
        self._transaction_monitor = transaction_monitor
        self._visualization_provider = visualization_provider
        self._mesh_generator = visualization_provider.get_mesh_generator()
        self._refresh_lock = threading.Lock()
        self._scene_notifier = scene_notifier
        self._scene_notifier.set_handlers(
            on_scene_ready=self._on_scene_ready,
            on_full_refresh=self._on_full_refresh_ready,
        )
        self._mesh_generation_id = 0
        self._mesh_generation_lock = threading.Lock()
        self._mesh_pending_task: Optional[Tuple] = None
        self._mesh_task_event = threading.Event()
        self._mesh_shutdown = threading.Event()
        self._mesh_worker = threading.Thread(
            target=self._mesh_worker_loop, daemon=True, name="MeshGenerationWorker"
        )
        self._mesh_worker.start()

    def _publish_native_scene(
        self, meshes: List, mesh_colors: Dict[str, Union[str, Dict[str, object]]]
    ) -> None:
        geometries, bounds = self._visualization_provider.convert_meshes_to_geometries(
            meshes, mesh_colors
        )
        self.event_bus.publish(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=geometries,
            bounds=bounds,
        )

    def refresh_mesh_view(self, page_uids: List[str]) -> None:
        takeoffs: List[Any] = []
        if page_uids:
            result = self.project_data.collect_takeoffs_for_pages(page_uids)
            takeoffs = result.takeoffs
        if not takeoffs:
            with self._mesh_generation_lock:
                self._mesh_generation_id += 1
                self._mesh_pending_task = None
            self._publish_native_scene([], {})
            return
        conditions = self.project_data.get_bid_conditions()
        page_area_selections = self.project_data.get_page_area_selections()
        display_mode = self.config_model.display_mode_3d
        grayscale_enabled = self.config_model.grayscale_enabled
        with self._mesh_generation_lock:
            self._mesh_generation_id += 1
            gen_id = self._mesh_generation_id
            self._mesh_pending_task = (
                takeoffs,
                conditions,
                page_area_selections,
                display_mode,
                grayscale_enabled,
                gen_id,
            )
        self._mesh_task_event.set()

    def _mesh_worker_loop(self) -> None:
        while not self._mesh_shutdown.is_set():
            self._mesh_task_event.wait(timeout=0.5)
            if self._mesh_shutdown.is_set():
                break
            self._mesh_task_event.clear()
            with self._mesh_generation_lock:
                task = self._mesh_pending_task
                self._mesh_pending_task = None
            if task is None:
                continue
            (
                takeoffs,
                conditions,
                page_area_selections,
                display_mode,
                grayscale_enabled,
                gen_id,
            ) = task
            try:
                with self._mesh_generation_lock:
                    if gen_id != self._mesh_generation_id:
                        continue
                meshes, mesh_colors, _ = self._mesh_generator.generate_meshes(
                    conditions,
                    takeoffs,
                    page_area_selections=page_area_selections,
                    display_mode=display_mode,
                    grayscale_enabled=grayscale_enabled,
                )
                with self._mesh_generation_lock:
                    if gen_id != self._mesh_generation_id:
                        continue
                geometries, bounds = (
                    self._visualization_provider.convert_meshes_to_geometries(
                        meshes, mesh_colors
                    )
                )
                with self._mesh_generation_lock:
                    if gen_id != self._mesh_generation_id:
                        continue
                self._scene_notifier.notify_scene_ready(geometries, bounds, gen_id)
            except Exception as exc:
                logger.exception("Mesh generation error: %s", exc)

    def _on_scene_ready(
        self, geometries: List[MeshGeometry], bounds: Any, gen_id: int
    ) -> None:
        with self._mesh_generation_lock:
            if gen_id != self._mesh_generation_id:
                return
        self.event_bus.publish(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=geometries,
            bounds=bounds,
        )

    def close_realtime_visualization(self) -> None:
        self._stop_file_monitoring()

    def cleanup(self) -> None:
        self._mesh_shutdown.set()
        self._mesh_task_event.set()
        self._mesh_worker.join(timeout=3.0)
        self.close_realtime_visualization()
        self._transaction_monitor.cleanup()
        self._transaction_monitor = None
        if self._scene_notifier is not None:
            self._scene_notifier.cleanup()
        self._scene_notifier = None
        self._mesh_pending_task = None
        self.config_model = None
        self._mesh_generator = None
        self._visualization_provider = None
        self.project_data = None
        self.project_operations = None
        self.event_bus = None

    def start_database_monitoring(self) -> None:
        self._start_file_monitoring()

    def stop_database_monitoring(self) -> None:
        self._stop_file_monitoring()

    def set_update_dialog_active(self, active: bool) -> None:
        self._transaction_monitor.set_update_dialog_active(active)

    def set_message_parent(self, parent) -> None:
        self._transaction_monitor.set_message_parent(parent)

    def _start_file_monitoring(self) -> None:
        if (
            self._transaction_monitor.is_monitoring()
            or not self.project_data.has_loaded_files()
        ):
            return
        file_path = self.project_data.get_current_file_path()
        if not file_path:
            return
        if self._transaction_monitor.is_available():
            self._transaction_monitor.start_monitoring(self._on_monitored_file_changed)

    def _stop_file_monitoring(self) -> None:
        self._transaction_monitor.stop_monitoring()

    def _on_monitored_file_changed(self) -> None:
        acquired = self._refresh_lock.acquire(blocking=False)
        if not acquired:
            return
        try:
            file_path = self.project_data.get_current_file_path()
            if not file_path:
                return
            success = self.project_operations.reload_database(file_path)
            if success:
                self._scene_notifier.notify_full_refresh(file_path)
        finally:
            self._refresh_lock.release()

    def _on_full_refresh_ready(self, file_path: str) -> None:
        self.event_bus.publish(
            AppEvents.DATABASE_REFRESHED,
            file_path=file_path,
        )
