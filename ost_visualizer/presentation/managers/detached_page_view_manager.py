import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from PySide6 import QtWidgets
from PySide6.QtCore import QByteArray, Qt
from ...application.dtos.page_view_dto import PageViewDto
from ...application.dtos.snap_preferences_dto import SnapPreferencesDto
from ...application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
    RemoteProjectionToken,
)
from ...application.events.app_events import AppEvents
from ...application.interfaces.i_color_service import IColorService
from ...application.interfaces.i_coordinate_transformer_factory import (
    ICoordinateTransformerFactory,
)
from ...application.interfaces.i_infrastructure_service_provider import (
    IInfrastructureServiceProvider,
)
from ...application.interfaces.i_shutdown_aware import IShutdownAware
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.annotation_view import AnnotationView
from ...domain.entities.named_view import build_named_view_from_annotation
from ...domain.entities.workspace_state import DetachedWindowState
from ...domain.repositories.i_annotation_view_repository import (
    IAnnotationViewRepository,
)
from ...domain.services.project_data_service import ProjectDataService
from ..services.annotation_write_coordinator import AnnotationWriteCoordinator
from ..services.undo_redo_service import UndoRedoService
from ..utils.qt_callback_bridge import QtVoidCallback
from ..coordinators.remote_plan_update_pipeline import RemotePlanUpdatePipeline
from .ui_access_manager import (
    PlanSurfaceAccessContext,
    PlanSurfaceAccessState,
)


def _collect_pages_from_bid(bid) -> List[Tuple[str, str]]:
    result: List[Tuple[str, str]] = []
    for folder in bid.folders.values():
        _collect_pages_from_folder(folder, result)
    for page in bid.pages_without_folder:
        result.append((page.uid, page.name))
    return result


def _collect_pages_from_folder(folder, result: List[Tuple[str, str]]) -> None:
    for subfolder in folder.subfolders.values():
        _collect_pages_from_folder(subfolder, result)
    for page in folder.pages:
        result.append((page.uid, page.name))


@dataclass(frozen=True)
class _DetachedPlanIdentity:
    database_id: str
    bid_uid: str
    page_uid: str
    view_uid: str
    surface_id: str
    update_generation: int
    barrier: RemoteProjectionBarrier


@dataclass(frozen=True)
class _DetachedPlanSnapshot:
    page: object
    takeoffs: tuple
    conditions: tuple
    annotations: tuple
    bid_ref: object
    ordered_pages: tuple
    target_named_view_uid: Optional[str]
    page_area_selections: tuple
    hidden_layer_uids: frozenset[str]
    annotation_layer_uid: Optional[str]
    display_mode: str
    grayscale_enabled: bool
    identity: Optional[_DetachedPlanIdentity] = None


class DetachedPageViewManager(IShutdownAware):
    def __init__(
        self,
        event_bus,
        icon_provider: IWindowIconProvider,
        repository: IAnnotationViewRepository,
        project_data: ProjectDataService,
        config_model,
        coord_factory: ICoordinateTransformerFactory,
        color_service: IColorService,
        infrastructure_provider: IInfrastructureServiceProvider,
        ui_access_manager,
        window_factory: Callable[..., QtWidgets.QMainWindow],
        write_service=None,
        annotation_write_service=None,
        saved_window_state_provider: Optional[Callable[[], DetachedWindowState]] = None,
        parent_window: Optional[QtWidgets.QWidget] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.event_bus = event_bus
        self.icon_provider = icon_provider
        self.repository = repository
        self.project_data = project_data
        self.config_model = config_model
        self._coord_factory = coord_factory
        self.parent_window = parent_window
        self.logger = logger or logging.getLogger(__name__)
        self._color_service = color_service
        self._infrastructure_provider = infrastructure_provider
        self._window_factory = window_factory
        self._write_service = write_service
        self._annotation_write_service = annotation_write_service
        self._saved_window_state_provider = saved_window_state_provider
        self._ui_access_manager = ui_access_manager
        self._access_listener_registered = False
        self._window: Optional[QtWidgets.QMainWindow] = None
        self._window_undo_service: Optional[UndoRedoService] = None
        self._opening = False
        self._lifecycle_generation = 0
        self._visibility_changed_callback = None
        self._refresh_signaler = QtVoidCallback(self._refresh_window, parent_window)
        self._remote_update_generation = 0
        self._remote_surface_id = f"detached-plan:{id(self)}"
        self._remote_plan_pipeline = RemotePlanUpdatePipeline(
            callback_bridge=infrastructure_provider.get_thread_callback_bridge(),
            prepare=self._prepare_page_data,
            apply=self._apply_remote_page_data,
            is_current=self._is_remote_page_data_current,
            coalesce=lambda _previous, current: current,
            can_coalesce=self._can_coalesce_remote_page_data,
        )
        self.event_bus.subscribe(
            AppEvents.DATABASE_REFRESHED, self._on_database_refreshed
        )
        self.event_bus.subscribe(AppEvents.TAKEOFFS_CHANGED, self._on_takeoffs_changed)
        self.event_bus.subscribe(
            AppEvents.LAYER_VISIBILITY_CHANGED, self._on_layer_visibility_changed
        )
        self.event_bus.subscribe(
            AppEvents.ANNOTATIONS_CHANGED, self._on_annotations_changed
        )
        self.event_bus.subscribe(
            AppEvents.REMOTE_BID_CONTENT_CHANGED,
            self._on_remote_bid_content_changed,
        )
        self.event_bus.subscribe(
            AppEvents.REMOTE_CONDITIONS_CHANGED,
            self._on_remote_conditions_changed,
        )
        self.event_bus.subscribe(
            AppEvents.REMOTE_AREAS_CHANGED,
            self._on_remote_areas_changed,
        )
        self.event_bus.subscribe(
            AppEvents.REMOTE_HIERARCHY_CHANGED,
            self._on_remote_hierarchy_changed,
        )
        self.event_bus.subscribe(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            self._on_remote_plan_projection_requested,
        )

    def shutdown(self) -> None:
        def cleanup_step(description: str, action: Callable[[], None]) -> None:
            try:
                action()
            except Exception:
                self.logger.exception(
                    "Failed to %s during detached-view manager shutdown", description
                )

        self._lifecycle_generation += 1
        self._opening = False
        self._release_access_tracking(suppress_errors=True)
        event_bus = self.event_bus
        if event_bus is not None:
            subscriptions = (
                (AppEvents.DATABASE_REFRESHED, self._on_database_refreshed),
                (AppEvents.TAKEOFFS_CHANGED, self._on_takeoffs_changed),
                (AppEvents.LAYER_VISIBILITY_CHANGED, self._on_layer_visibility_changed),
                (AppEvents.ANNOTATIONS_CHANGED, self._on_annotations_changed),
                (
                    AppEvents.REMOTE_BID_CONTENT_CHANGED,
                    self._on_remote_bid_content_changed,
                ),
                (
                    AppEvents.REMOTE_CONDITIONS_CHANGED,
                    self._on_remote_conditions_changed,
                ),
                (AppEvents.REMOTE_AREAS_CHANGED, self._on_remote_areas_changed),
                (AppEvents.REMOTE_HIERARCHY_CHANGED, self._on_remote_hierarchy_changed),
                (
                    AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
                    self._on_remote_plan_projection_requested,
                ),
            )
            for event_name, callback in subscriptions:
                cleanup_step(
                    f"unsubscribe {event_name}",
                    lambda event_name=event_name, callback=callback: event_bus.unsubscribe(
                        event_name, callback
                    ),
                )
        self._remote_update_generation += 1
        if self._remote_plan_pipeline is not None:
            cleanup_step(
                "clean up the remote plan pipeline", self._remote_plan_pipeline.cleanup
            )
            self._remote_plan_pipeline = None
        if self._refresh_signaler is not None:
            cleanup_step(
                "clean up the refresh signaler", self._refresh_signaler.cleanup
            )
            cleanup_step(
                "delete the refresh signaler", self._refresh_signaler.deleteLater
            )
            self._refresh_signaler = None
        if self._window is not None:
            window = self._window
            cleanup_step("close the detached window", window.close)
            if self._window is window:
                self._window = None
                self._window_undo_service = None
                self._opening = False
                cleanup_step(
                    "publish detached visibility", self._notify_visibility_changed
                )
        self._visibility_changed_callback = None
        self._ui_access_manager = None
        self.event_bus = None
        self.icon_provider = None
        self.repository = None
        self.project_data = None
        self.config_model = None
        self._coord_factory = None
        self.parent_window = None
        self._color_service = None
        self._infrastructure_provider = None
        self._window_factory = None
        self._write_service = None
        self._annotation_write_service = None
        self._saved_window_state_provider = None

    def _on_window_destroyed(self, window_identity: int) -> None:
        if self._window is None or id(self._window) != window_identity:
            return
        self._release_access_tracking(suppress_errors=True)
        self._window = None
        self._window_undo_service = None
        self._opening = False
        self._notify_visibility_changed()

    def _on_takeoffs_changed(
        self,
        page_uid: str = "",
        page_uids: Optional[list] = None,
        takeoff_uids: Optional[list] = None,
        condition_uids: Optional[list] = None,
    ) -> None:
        del takeoff_uids, condition_uids
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if (
            view is None
            or view.bid_ref is None
            or view.bid_ref != self.project_data.get_current_bid_ref()
        ):
            return
        affected_page_uids = list(
            dict.fromkeys(str(uid) for uid in (page_uids or ()) if uid)
        )
        if not affected_page_uids and page_uid:
            affected_page_uids = [str(page_uid)]
        if not affected_page_uids:
            return
        for affected_page_uid in affected_page_uids:
            self._window.set_page_has_takeoffs(
                affected_page_uid,
                self.project_data.has_takeoffs_for_pages([affected_page_uid]),
            )
        if view.target_page_uid not in affected_page_uids:
            return
        self._apply_window_page(view, self._get_page_data(view))

    def _on_database_refreshed(self, file_path: str = "") -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        bid_ref = view.bid_ref
        if bid_ref and file_path and bid_ref.file_path != file_path:
            return
        self._refresh_signaler.request()

    def _on_layer_visibility_changed(
        self,
        file_path: str = "",
        bid_uid: str = "",
        layer_uid: str = "",
        show: bool = True,
        image_layer: bool = False,
        all_layers: bool = False,
    ) -> None:
        del layer_uid, show, image_layer, all_layers
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        bid_ref = view.bid_ref
        if bid_ref and (bid_ref.file_path != file_path or bid_ref.bid_uid != bid_uid):
            return
        self._refresh_signaler.request()

    def _on_annotations_changed(
        self,
        page_uid: str = "",
        page_uids: Optional[list] = None,
        annotation_uids: list | None = None,
        annotation_types: list | None = None,
    ) -> None:
        del annotation_uids, annotation_types
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        affected_page_uids = set(page_uids or ([page_uid] if page_uid else []))
        if affected_page_uids and view.target_page_uid not in affected_page_uids:
            return
        self._refresh_signaler.request()

    def _on_remote_bid_content_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        families: Optional[List[str]] = None,
        defer_plan_projection: bool = False,
        **_event_data,
    ) -> None:
        view = self.repository.get_active_view()
        if (
            view is None
            or view.bid_ref is None
            or view.bid_ref.file_path != database_id
            or view.bid_ref.bid_uid != bid_uid
        ):
            return
        if self._window_undo_service is not None and families:
            self._window_undo_service.clear()
        if not defer_plan_projection:
            self._refresh_signaler.request()

    def _on_remote_conditions_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        defer_plan_projection: bool = False,
        **_event_data,
    ) -> None:
        view = self.repository.get_active_view()
        if (
            view is None
            or view.bid_ref is None
            or view.bid_ref.file_path != database_id
            or view.bid_ref.bid_uid != bid_uid
        ):
            return
        if self._window_undo_service is not None:
            self._window_undo_service.clear()
        if not defer_plan_projection:
            self._refresh_signaler.request()

    def _on_remote_areas_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        defer_plan_projection: bool = False,
        **_event_data,
    ) -> None:
        self._on_remote_conditions_changed(
            database_id, bid_uid, defer_plan_projection=defer_plan_projection
        )

    def _on_remote_hierarchy_changed(
        self,
        database_id: str = "",
        defer_plan_projection: bool = False,
        **_event_data,
    ) -> None:
        view = self.repository.get_active_view()
        if (
            view is None
            or view.bid_ref is None
            or view.bid_ref.file_path != database_id
        ):
            return
        if not defer_plan_projection:
            self._refresh_signaler.request()

    def _on_remote_plan_projection_requested(
        self,
        database_id: str,
        bid_uid: str,
        runtime_generation: int,
        families: tuple[str, ...],
        condition_uids: tuple[str, ...],
        resource_uids_by_family: dict[str, tuple[str, ...]],
        barrier: RemoteProjectionBarrier,
    ) -> None:
        del families, condition_uids, resource_uids_by_family
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if (
            view is None
            or view.bid_ref is None
            or view.bid_ref.file_path != database_id
            or view.bid_ref.bid_uid != bid_uid
            or not view.target_page_uid
            or barrier.database_id != database_id
            or barrier.runtime_generation != runtime_generation
        ):
            return
        self._remote_update_generation += 1
        identity = _DetachedPlanIdentity(
            database_id=database_id,
            bid_uid=bid_uid,
            page_uid=view.target_page_uid,
            view_uid=view.uid,
            surface_id=self._remote_surface_id,
            update_generation=self._remote_update_generation,
            barrier=barrier,
        )
        snapshot = self._capture_page_data(view, identity)
        if snapshot is None:
            return
        token = barrier.register(self._remote_surface_id)
        self._remote_plan_pipeline.submit(
            snapshot,
            lambda success: self._complete_remote_projection(token, success),
        )

    @staticmethod
    def _complete_remote_projection(
        token: RemoteProjectionToken, success: bool
    ) -> None:
        token.complete(success)

    def _get_bid_for_view(self, view: AnnotationView):
        bid_ref = view.bid_ref if view else None
        if not bid_ref:
            return None
        return self.project_data.get_bid(bid_ref)

    def _update_window_navigation(self, view: AnnotationView) -> None:
        if self._window is None:
            return
        bid = self._get_bid_for_view(view)
        named_views = self._collect_named_views(bid) if bid else []
        self._window.update_navigation(
            bid,
            named_views=named_views,
            pages_with_takeoffs=self._collect_pages_with_takeoffs(view.bid_ref),
        )

    def set_visibility_changed_callback(self, callback) -> None:
        self._visibility_changed_callback = callback

    def _notify_visibility_changed(self) -> None:
        if self._visibility_changed_callback:
            self._visibility_changed_callback(self.is_view_open())

    def _get_access_state(
        self,
        view: AnnotationView,
        page_data: PageViewDto,
    ) -> PlanSurfaceAccessState:
        annotation_layer_visible = bool(
            page_data and page_data.is_layer_visible(page_data.annotation_layer_uid)
        )
        context = PlanSurfaceAccessContext(
            surface_id=self._remote_surface_id,
            database_id=str(view.bid_ref.file_path or ""),
            bid_ref=view.bid_ref,
            page_uid=str(view.target_page_uid or ""),
            annotation_layer_visible=annotation_layer_visible,
        )
        return self._ui_access_manager.get_plan_surface_access(context)

    def _refresh_access_state(self) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        self._window.set_access_state(
            self._get_access_state(view, self._window.page_data)
        )

    def _register_access_listener(self) -> None:
        if self._access_listener_registered or self._ui_access_manager is None:
            return
        self._ui_access_manager.subscribe_access_state_changed(
            self._refresh_access_state
        )
        self._access_listener_registered = True

    def _unregister_access_listener(self) -> None:
        if not self._access_listener_registered:
            return
        manager = self._ui_access_manager
        self._access_listener_registered = False
        if manager is not None:
            manager.unsubscribe_access_state_changed(self._refresh_access_state)

    def _clear_surface_interaction(self) -> None:
        if self._ui_access_manager is not None:
            self._ui_access_manager.clear_plan_surface_interaction(
                self._remote_surface_id
            )

    def _release_access_tracking(self, *, suppress_errors: bool = False) -> None:
        errors = []
        try:
            self._unregister_access_listener()
        except Exception as exc:
            self.logger.exception("Failed to unregister detached-view access listener")
            errors.append(exc)
        try:
            self._clear_surface_interaction()
        except Exception as exc:
            self.logger.exception("Failed to clear detached-view interaction state")
            errors.append(exc)
        if errors and not suppress_errors:
            raise errors[0]

    def _on_window_area_placement_changed(self, active: bool) -> None:
        if self._ui_access_manager is None or not self.is_view_open():
            return
        self._ui_access_manager.set_area_placement_active(
            bool(active), surface_id=self._remote_surface_id
        )

    def _on_window_inline_text_edit_changed(self, active: bool) -> None:
        if self._ui_access_manager is None or not self.is_view_open():
            return
        self._ui_access_manager.set_text_annotation_edit_active(
            bool(active), surface_id=self._remote_surface_id
        )

    def _refresh_window(self) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        page_data = self._get_page_data(view)
        if page_data.page is None and self._retarget_missing_active_page(view):
            page_data = self._get_page_data(view)
        self._update_window_navigation(view)
        self._apply_window_page(view, page_data)

    def refresh_active_view(self) -> None:
        self._refresh_window()

    def _apply_window_page(self, view: AnnotationView, page_data: PageViewDto) -> None:
        self._window.set_access_state(self._get_access_state(view, page_data))
        self._window.update_page(page_data)

    def _retarget_missing_active_page(self, view: AnnotationView) -> bool:
        bid_ref = view.bid_ref
        if bid_ref and self.project_data.get_current_bid_ref() != bid_ref:
            return False
        bid = self._get_bid_for_view(view)
        if bid is None:
            return False
        page_uids = [uid for uid, _name in _collect_pages_from_bid(bid)]
        target_page_uid = str(view.target_page_uid or "")
        if target_page_uid in page_uids:
            return False
        replacement_uid = page_uids[0] if page_uids else ""
        if target_page_uid == replacement_uid and view.target_named_view_uid is None:
            return False
        view.update_view_target(page_uid=replacement_uid, named_view_uid=None)
        self.repository.update_view(view)
        return True

    def get_active_view(self) -> Optional[AnnotationView]:
        return self.repository.get_active_view()

    def open_view(
        self,
        bid_ref,
        target_page_uid: str,
        target_named_view_uid: Optional[str] = None,
        initial_geometry: Optional[QByteArray] = None,
        initial_is_maximized: bool = False,
        initial_is_fullscreen: bool = False,
    ) -> str:
        if self._opening:
            existing_view = self.repository.get_active_view()
            if (
                existing_view is not None
                and existing_view.bid_ref == bid_ref
                and existing_view.target_page_uid == target_page_uid
                and existing_view.target_named_view_uid == target_named_view_uid
            ):
                return existing_view.uid
        if self.is_view_open():
            existing_view = self.repository.get_active_view()
            if existing_view:
                navigation_source = "hotlink" if target_named_view_uid else "unknown"
                existing_view.bid_uid = bid_ref.bid_uid
                existing_view.file_path = bid_ref.file_path
                existing_view.update_view_target(
                    page_uid=target_page_uid, named_view_uid=target_named_view_uid
                )
                self.repository.update_view(existing_view)
                self._update_window_navigation(existing_view)
                page_data = self._get_page_data(existing_view)
                self._window.set_access_state(
                    self._get_access_state(existing_view, page_data)
                )
                self._window.load_view(
                    existing_view,
                    page_data,
                    navigation_source=navigation_source,
                )
                self.bring_to_front()
                self._notify_visibility_changed()
                return existing_view.uid
        navigation_source = "hotlink" if target_named_view_uid else "unknown"
        lifecycle_generation = self._lifecycle_generation + 1
        self._lifecycle_generation = lifecycle_generation
        self._opening = True
        try:
            view = self.repository.create_view(
                bid_ref=bid_ref,
                target_page_uid=target_page_uid,
                target_named_view_uid=target_named_view_uid,
            )
            initial_geometry, initial_is_maximized, initial_is_fullscreen = (
                self._resolve_initial_window_state(
                    initial_geometry,
                    initial_is_maximized,
                    initial_is_fullscreen,
                )
            )
            committed = self._create_window(
                view,
                lifecycle_generation,
                initial_geometry,
                initial_is_maximized,
                initial_is_fullscreen,
                navigation_source,
            )
        except Exception:
            if self._lifecycle_generation == lifecycle_generation:
                self._opening = False
            raise
        if not committed or self._lifecycle_generation != lifecycle_generation:
            return ""
        self._opening = False
        self._notify_visibility_changed()
        return view.uid

    def _resolve_initial_window_state(
        self,
        initial_geometry: Optional[QByteArray],
        initial_is_maximized: bool,
        initial_is_fullscreen: bool,
    ) -> Tuple[Optional[QByteArray], bool, bool]:
        if (
            initial_geometry is not None
            or initial_is_maximized
            or initial_is_fullscreen
            or self._saved_window_state_provider is None
        ):
            return initial_geometry, initial_is_maximized, initial_is_fullscreen
        state = self._saved_window_state_provider()
        return (
            self._decode_window_geometry(state.geometry_b64),
            state.is_maximized,
            state.is_fullscreen,
        )

    @staticmethod
    def _decode_window_geometry(value: Optional[str]) -> Optional[QByteArray]:
        if value is None:
            return None
        if not isinstance(value, str):
            return QByteArray()
        if not value.isascii():
            return QByteArray()
        return QByteArray.fromBase64(value.encode("ascii"))

    def close_view(self) -> None:
        self._lifecycle_generation += 1
        self._opening = False
        self._remote_update_generation += 1
        self._release_access_tracking(suppress_errors=True)
        if self._window is not None:
            window = self._window
            window.close()
            if self._window is window:
                self._window = None
                self._window_undo_service = None
                self._notify_visibility_changed()

    def navigate_to_view(self, page_uid: str, named_view_uid: str) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        current_bid_ref = self.project_data.get_current_bid_ref()
        if current_bid_ref:
            view.bid_uid = current_bid_ref.bid_uid
            view.file_path = current_bid_ref.file_path
        view.update_view_target(page_uid=page_uid, named_view_uid=named_view_uid)
        self.repository.update_view(view)
        page_data = self._get_page_data(view)
        self._window.set_access_state(self._get_access_state(view, page_data))
        self._window.load_view(view, page_data, navigation_source="hotlink")

    def bring_to_front(self) -> None:
        if not self._window:
            return
        if self._window.windowState() & Qt.WindowState.WindowMinimized:
            if self._window.isMaximized():
                self._window.showMaximized()
            else:
                self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def is_view_open(self) -> bool:
        return self._window is not None

    def has_active_view_lifecycle(self) -> bool:
        return self._opening or self._window is not None

    def get_window(self):
        return self._window

    def _on_window_page_selected(self, page_uid: str) -> None:
        view = self.repository.get_active_view()
        if not view or not self._window:
            return
        view.update_view_target(page_uid=page_uid, named_view_uid=None)
        self.repository.update_view(view)
        page_data = self._get_page_data(view)
        self._window.set_access_state(self._get_access_state(view, page_data))
        self._window.load_view(view, page_data, navigation_source="combobox")

    def _on_window_scale_changed(self, page_uid: str, sf1: float, sf2: float) -> None:
        view = self.repository.get_active_view()
        if (
            not self._write_service
            or not self._ui_access_manager
            or not self._window
            or view is None
            or not self._get_access_state(
                view, self._window.page_data
            ).can_edit_page_settings
            or str(view.target_page_uid or "") != str(page_uid or "")
        ):
            return
        db_path = view.file_path
        if not db_path:
            return
        try:
            saved = self._write_service.queue_page_setting_if_sql(
                db_path,
                page_uid,
                "scale",
                [sf1, sf2],
                owning_surface="detached-plan",
            )
            if saved is None:
                saved = self._write_service.save_page_scale(db_path, page_uid, sf1, sf2)
            if saved is False:
                self._refresh_window()
        except Exception:
            self.logger.exception("Failed to save page scale from detached view")
            self._refresh_window()

    def _on_window_named_view_selected(
        self, page_uid: str, named_view_uid: str
    ) -> None:
        view = self.repository.get_active_view()
        if not view or not self._window:
            return
        view.update_view_target(page_uid=page_uid, named_view_uid=named_view_uid)
        self.repository.update_view(view)
        page_data = self._get_page_data(view)
        self._window.set_access_state(self._get_access_state(view, page_data))
        self._window.load_view(view, page_data, navigation_source="named_view_combo")

    def _collect_named_views(self, bid) -> List[Tuple[str, str, str, str]]:
        result: List[Tuple[str, str, str, str]] = []
        page_entries = _collect_pages_from_bid(bid)
        for page_uid, page_name in page_entries:
            for ann in self.project_data.get_page_annotations(page_uid):
                nv = build_named_view_from_annotation(ann)
                if nv:
                    result.append((nv.uid, page_uid, page_name, nv.name or nv.uid))
        return result

    def _collect_pages_with_takeoffs(self, bid_ref) -> set[str]:
        current_bid_ref = self.project_data.get_current_bid_ref()
        if bid_ref and current_bid_ref != bid_ref:
            return set()
        return {
            takeoff.page_uid
            for takeoff in self.project_data.get_all_takeoffs()
            if takeoff and takeoff.page_uid
        }

    def _create_window(
        self,
        view: AnnotationView,
        lifecycle_generation: int,
        initial_geometry: Optional[QByteArray] = None,
        initial_is_maximized: bool = False,
        initial_is_fullscreen: bool = False,
        navigation_source: str = "unknown",
    ) -> bool:
        page_data = self._get_page_data(view)
        coord_system = self._coord_factory.create()
        color_service = self._color_service
        bid_ref = view.bid_ref
        bid = self._get_bid_for_view(view)
        file_path = (
            bid_ref.file_path
            if bid_ref
            else self.project_data.get_current_bid_file_path()
        )
        named_views = self._collect_named_views(bid) if bid else []
        renderers = self._infrastructure_provider.create_plan_view_renderers(
            coord_system, color_service
        )
        undo_svc = UndoRedoService()
        if bid_ref:
            undo_svc.set_active_bid(bid_ref)
        annotation_write_coordinator = AnnotationWriteCoordinator(
            self._annotation_write_service,
            self.project_data,
            self.event_bus,
        )
        snap_preferences = SnapPreferencesDto.from_config(self.config_model)
        window = self._window_factory(
            icon_provider=self.icon_provider,
            view=view,
            event_bus=self.event_bus,
            page_data=page_data,
            color_service=color_service,
            renderers=renderers,
            bid=bid,
            pages_with_takeoffs=self._collect_pages_with_takeoffs(bid_ref),
            on_page_selected=self._on_window_page_selected,
            named_views=named_views,
            on_named_view_selected=self._on_window_named_view_selected,
            on_scale_changed=self._on_window_scale_changed,
            annotation_write_service=self._annotation_write_service,
            annotation_write_coordinator=annotation_write_coordinator,
            project_write_service=self._write_service,
            file_path=file_path,
            undo_service=undo_svc,
            initial_geometry=initial_geometry,
            initial_is_maximized=initial_is_maximized,
            initial_is_fullscreen=initial_is_fullscreen,
            navigation_source=navigation_source,
            show_page_index=self.config_model.display_page_index_with_sheet_name,
            show_sheet_number=self.config_model.display_sheet_number_with_sheet_name,
            roping_selection_method=self.config_model.roping_selection_method,
            disable_high_resolution_images=(
                self.config_model.disable_high_resolution_images
            ),
            intelligent_paste_enabled=self.config_model.enable_intelligent_paste,
            advanced_mouse_controls_enabled=(
                self.config_model.enable_advanced_mouse_controls
            ),
            default_auto_zoom_level=self.config_model.default_auto_zoom_level,
            use_full_window_crosshairs=self.config_model.use_full_window_crosshairs,
            crosshair_color=self.config_model.crosshair_color,
            crosshair_line_thickness=self.config_model.crosshair_line_thickness,
            mouse_unpressed_snap_angle=self.config_model.mouse_unpressed_snap_angle,
            mouse_pressed_snap_angle=self.config_model.mouse_pressed_snap_angle,
            annotation_style_getter=(
                self.parent_window.get_annotation_style_for_tool
                if self.parent_window is not None
                else None
            ),
            annotation_style_setter=(
                self.parent_window.set_annotation_style_for_tool
                if self.parent_window is not None
                else None
            ),
            linked_hotlink_resolver=self.project_data.find_hotlinks_targeting,
            **snap_preferences.to_options(),
            parent=self.parent_window,
        )
        if lifecycle_generation != self._lifecycle_generation:
            window.close()
            return False
        try:
            window.set_access_state(self._get_access_state(view, page_data))
            window.area_placement_state_changed.connect(
                self._on_window_area_placement_changed
            )
            window.inline_text_edit_state_changed.connect(
                self._on_window_inline_text_edit_changed
            )
            window_identity = id(window)
            window.destroyed.connect(
                lambda _object: self._on_window_destroyed(window_identity)
            )
            self._window = window
            self._window_undo_service = undo_svc
            self._register_access_listener()
            window.show_when_page_ready()
        except Exception:
            self._release_access_tracking(suppress_errors=True)
            if self._window is window:
                self._window = None
                self._window_undo_service = None
            try:
                window.close()
            except Exception:
                self.logger.exception(
                    "Failed to close partially initialized detached view"
                )
            raise
        return True

    def _get_page_data(self, view: AnnotationView) -> PageViewDto:
        self._remote_update_generation += 1
        snapshot = self._capture_page_data(view)
        if snapshot is None:
            return PageViewDto(page=None, bid_ref=view.bid_ref)
        return self._prepare_page_data(snapshot)

    def _capture_page_data(
        self,
        view: AnnotationView,
        identity: Optional[_DetachedPlanIdentity] = None,
    ) -> Optional[_DetachedPlanSnapshot]:
        page_uid = view.target_page_uid
        bid_ref = view.bid_ref
        current_bid_ref = self.project_data.get_current_bid_ref()
        if bid_ref and current_bid_ref != bid_ref:
            return None
        page = self.project_data.get_page(page_uid)
        if not page:
            return None
        page_takeoffs = self.project_data.get_page_takeoffs(page_uid)
        page_annotations = self.project_data.get_page_annotations(page_uid)
        conditions = self.project_data.get_bid_conditions()
        ordered_pages = self.project_data.get_all_pages()
        page_area_selections = self.project_data.get_page_area_selections()
        if identity is not None:
            page = deepcopy(page)
            page_takeoffs = deepcopy(page_takeoffs)
            page_annotations = deepcopy(page_annotations)
            conditions = deepcopy(conditions)
            ordered_pages = deepcopy(ordered_pages)
            page_area_selections = deepcopy(page_area_selections)
        return _DetachedPlanSnapshot(
            page=page,
            takeoffs=tuple(page_takeoffs),
            conditions=tuple(conditions.items()),
            annotations=tuple(page_annotations),
            bid_ref=bid_ref,
            ordered_pages=tuple(ordered_pages),
            target_named_view_uid=view.target_named_view_uid,
            page_area_selections=tuple(page_area_selections.items()),
            hidden_layer_uids=frozenset(self.project_data.get_hidden_layer_uids()),
            annotation_layer_uid=self.project_data.get_annotation_layer_uid(),
            display_mode=self.config_model.display_mode_2d,
            grayscale_enabled=self.config_model.grayscale_enabled,
            identity=identity,
        )

    def _prepare_page_data(self, snapshot: _DetachedPlanSnapshot) -> PageViewDto:
        named_view = None
        if snapshot.target_named_view_uid:
            for ann in snapshot.annotations:
                nv = build_named_view_from_annotation(ann)
                if nv and nv.uid == snapshot.target_named_view_uid:
                    named_view = nv
                    break
        conditions = dict(snapshot.conditions)
        _, color_map = self._color_service.get_color_mapping(
            conditions,
            snapshot.takeoffs,
            snapshot.display_mode,
            snapshot.grayscale_enabled,
        )
        return PageViewDto(
            page=snapshot.page,
            takeoffs=list(snapshot.takeoffs),
            conditions=conditions,
            color_map=color_map,
            bid_ref=snapshot.bid_ref,
            annotations=list(snapshot.annotations),
            ordered_pages=list(snapshot.ordered_pages),
            named_view=named_view,
            page_area_selections=dict(snapshot.page_area_selections),
            hidden_layer_uids=set(snapshot.hidden_layer_uids),
            annotation_layer_uid=snapshot.annotation_layer_uid,
        )

    def _is_remote_page_data_current(self, snapshot: _DetachedPlanSnapshot) -> bool:
        identity = snapshot.identity
        if identity is None or self._window is None:
            return False
        view = self.repository.get_active_view()
        return (
            identity.update_generation == self._remote_update_generation
            and identity.surface_id == self._remote_surface_id
            and identity.barrier.is_current()
            and view is not None
            and view.uid == identity.view_uid
            and view.bid_ref is not None
            and view.bid_ref.file_path == identity.database_id
            and view.bid_ref.bid_uid == identity.bid_uid
            and view.target_page_uid == identity.page_uid
            and not self._window.plan_view.has_active_remote_projection_blocker()
        )

    @staticmethod
    def _can_coalesce_remote_page_data(
        previous: _DetachedPlanSnapshot, current: _DetachedPlanSnapshot
    ) -> bool:
        previous_identity = previous.identity
        current_identity = current.identity
        if previous_identity is None or current_identity is None:
            return False
        return (
            previous_identity.database_id,
            previous_identity.bid_uid,
            previous_identity.page_uid,
            previous_identity.view_uid,
            previous_identity.surface_id,
            previous_identity.barrier.database_id,
            previous_identity.barrier.runtime_generation,
        ) == (
            current_identity.database_id,
            current_identity.bid_uid,
            current_identity.page_uid,
            current_identity.view_uid,
            current_identity.surface_id,
            current_identity.barrier.database_id,
            current_identity.barrier.runtime_generation,
        )

    def _apply_remote_page_data(self, page_data: PageViewDto) -> bool:
        if self._window is None:
            return False
        view = self.repository.get_active_view()
        if view is None:
            return False
        self._update_window_navigation(view)
        self._window.set_access_state(self._get_access_state(view, page_data))
        self._window.update_page(page_data)
        return True
