import logging
import threading
from typing import Any, List, Optional, Tuple
from ...domain.entities.database_descriptor import DatabaseBackend
from ...domain.entities.identity_refs import BidRef
from ...domain.services.project_data_service import ProjectDataService
from ..dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
    normalize_scene_page_uids,
)
from ..events.app_events import AppEvents
from ..interfaces.i_database_descriptor_registry import IDatabaseDescriptorRegistry
from ..interfaces.i_thread_callback_bridge import IThreadCallbackBridge
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
        database_descriptor_registry: IDatabaseDescriptorRegistry,
        callback_bridge: IThreadCallbackBridge,
        visualization_provider: IVisualizationProvider,
        scene_notifier: IThreadSceneNotifier,
    ):
        self.config_model = config_model
        self.project_data = project_data_service
        self.project_operations = project_operations_service
        self.event_bus = event_bus
        self._transaction_monitor = transaction_monitor
        self._database_descriptor_registry = database_descriptor_registry
        self._callback_bridge = callback_bridge
        self._visualization_provider = visualization_provider
        self._mesh_generator = visualization_provider.get_mesh_generator()
        self._scene_notifier = scene_notifier
        self._scene_notifier.set_handlers(
            on_scene_ready=self._on_scene_ready,
            on_full_refresh=self._on_full_refresh_ready,
        )
        self._database_monitor_generation = 0
        self._monitored_access_locator: Optional[str] = None
        self._mesh_generation_id = 0
        self._mesh_generation_identity: Optional[MeshSceneIdentity] = None
        self._mesh_generation_delivered = True
        self._mesh_generation_lock = threading.Lock()
        self._mesh_pending_task: Optional[Tuple] = None
        self._mesh_task_event = threading.Event()
        self._mesh_shutdown = threading.Event()
        self._mesh_worker = threading.Thread(
            target=self._mesh_worker_loop, daemon=True, name="MeshGenerationWorker"
        )
        self._mesh_worker.start()

    def cancel_mesh_view_refresh(self) -> None:
        with self._mesh_generation_lock:
            self._mesh_generation_id += 1
            self._mesh_pending_task = None
            self._mesh_generation_identity = None
            self._mesh_generation_delivered = True

    def _is_current_mesh_generation(self, generation: int) -> bool:
        with self._mesh_generation_lock:
            return (
                not self._mesh_shutdown.is_set()
                and generation == self._mesh_generation_id
            )

    def _claim_mesh_result(self, generation: int) -> Optional[MeshSceneIdentity]:
        with self._mesh_generation_lock:
            if (
                self._mesh_shutdown.is_set()
                or generation != self._mesh_generation_id
                or self._mesh_generation_delivered
                or self._mesh_generation_identity is None
                or self._mesh_generation_identity.generation != generation
            ):
                return None
            self._mesh_generation_delivered = True
            return self._mesh_generation_identity

    def _start_mesh_generation_locked(
        self, bid_ref: BidRef, page_uids: List[str]
    ) -> MeshSceneIdentity:
        self._mesh_generation_id += 1
        identity = MeshSceneIdentity(
            bid_ref=bid_ref,
            page_uids=tuple(page_uids),
            generation=self._mesh_generation_id,
        )
        self._mesh_generation_identity = identity
        self._mesh_generation_delivered = False
        return identity

    def refresh_mesh_view(self, page_uids: List[str]) -> None:
        bid_ref = self.project_data.get_current_bid_ref()
        if bid_ref is None:
            self.cancel_mesh_view_refresh()
            return
        normalized_page_uids = list(normalize_scene_page_uids(page_uids))
        takeoffs = []
        if normalized_page_uids:
            result = self.project_data.collect_takeoffs_for_pages(normalized_page_uids)
            takeoffs = result.takeoffs
        if not takeoffs:
            self._publish_empty_mesh_scene(bid_ref, normalized_page_uids)
            return
        conditions = self.project_data.get_bid_conditions()
        page_area_selections = self.project_data.get_page_area_selections()
        display_mode = self.config_model.display_mode_3d
        grayscale_enabled = self.config_model.grayscale_enabled
        with self._mesh_generation_lock:
            identity = self._start_mesh_generation_locked(bid_ref, normalized_page_uids)
            self._mesh_pending_task = (
                takeoffs,
                conditions,
                page_area_selections,
                display_mode,
                grayscale_enabled,
                identity.generation,
            )
        self._mesh_task_event.set()

    def _publish_empty_mesh_scene(self, bid_ref: BidRef, page_uids: List[str]) -> None:
        with self._mesh_generation_lock:
            identity = self._start_mesh_generation_locked(bid_ref, page_uids)
            self._mesh_pending_task = None
        geometries, bounds = self._visualization_provider.convert_meshes_to_geometries(
            [], {}
        )
        self._on_scene_ready(geometries, bounds, identity.generation)

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
                if not self._is_current_mesh_generation(gen_id):
                    continue
                meshes, mesh_colors, _ = self._mesh_generator.generate_meshes(
                    conditions,
                    takeoffs,
                    page_area_selections=page_area_selections,
                    display_mode=display_mode,
                    grayscale_enabled=grayscale_enabled,
                )
                if not self._is_current_mesh_generation(gen_id):
                    continue
                geometries, bounds = (
                    self._visualization_provider.convert_meshes_to_geometries(
                        meshes, mesh_colors
                    )
                )
                if not self._is_current_mesh_generation(gen_id):
                    continue
                self._scene_notifier.notify_scene_ready(geometries, bounds, gen_id)
            except Exception as exc:
                logger.exception("Mesh generation error: %s", exc)
                if self._is_current_mesh_generation(gen_id):
                    self._scene_notifier.notify_scene_ready([], None, gen_id)

    def _on_scene_ready(
        self, geometries: List[MeshGeometry], bounds: Any, gen_id: int
    ) -> None:
        identity = self._claim_mesh_result(gen_id)
        if identity is None:
            return
        self.event_bus.publish(
            AppEvents.NATIVE_SCENE_UPDATED,
            geometries=geometries,
            bounds=bounds,
            scene_identity=identity,
        )

    def close_realtime_visualization(self) -> None:
        self.stop_database_monitoring()

    def cleanup(self) -> None:
        self.cancel_mesh_view_refresh()
        self._mesh_shutdown.set()
        self._mesh_task_event.set()
        self._mesh_worker.join(timeout=3.0)
        self.close_realtime_visualization()
        self._transaction_monitor.cleanup()
        self._transaction_monitor = None
        self._database_descriptor_registry = None
        self._callback_bridge = None
        self._monitored_access_locator = None
        self._scene_notifier.cleanup()
        self._scene_notifier = None
        self._mesh_pending_task = None
        self._mesh_generation_identity = None
        self.config_model = None
        self._mesh_generator = None
        self._visualization_provider = None
        self.project_data = None
        self.project_operations = None
        self.event_bus = None

    def start_database_monitoring(self) -> None:
        if not self.project_data.has_loaded_files():
            self.stop_database_monitoring()
            return
        file_path = self.project_data.get_current_file_path()
        if not file_path or not self._is_access_database(file_path):
            self.stop_database_monitoring()
            return
        if self._transaction_monitor.is_monitoring():
            if self._monitored_access_locator == file_path:
                return
            self.stop_database_monitoring()
        self._database_monitor_generation += 1
        generation = self._database_monitor_generation
        self._monitored_access_locator = file_path
        self._transaction_monitor.start_monitoring(
            lambda: self._on_monitored_file_changed(file_path, generation)
        )

    def stop_database_monitoring(self) -> None:
        self._database_monitor_generation += 1
        self._monitored_access_locator = None
        self._transaction_monitor.stop_monitoring()

    def set_update_dialog_active(self, active: bool) -> None:
        self._transaction_monitor.set_update_dialog_active(active)

    def set_message_parent(self, parent) -> None:
        self._transaction_monitor.set_message_parent(parent)

    def _on_monitored_file_changed(self, locator: str, generation: int) -> None:
        self._callback_bridge.dispatch(
            self._reload_monitored_access_database,
            (locator, generation),
        )

    def _reload_monitored_access_database(self, payload: tuple[str, int]) -> None:
        locator, generation = payload
        if (
            generation != self._database_monitor_generation
            or locator != self._monitored_access_locator
            or self.project_data.get_current_file_path() != locator
            or not self._is_access_database(locator)
        ):
            return
        success = self.project_operations.reload_database(locator)
        if success:
            self._scene_notifier.notify_full_refresh(locator)

    def _is_access_database(self, locator: str) -> bool:
        descriptor = self._database_descriptor_registry.resolve(locator)
        return descriptor is not None and descriptor.backend == DatabaseBackend.ACCESS

    def _on_full_refresh_ready(self, file_path: str) -> None:
        self.event_bus.publish(
            AppEvents.DATABASE_REFRESHED,
            file_path=file_path,
        )
