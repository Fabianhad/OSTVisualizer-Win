import logging
from typing import Callable, List, Optional, Tuple
from PySide6 import QtWidgets
from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from ...application.dtos.page_view_dto import PageViewDto
from ...application.dtos.snap_preferences_dto import SnapPreferencesDto
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
from ..services.undo_redo_service import UndoRedoService
from ..services.annotation_write_coordinator import AnnotationWriteCoordinator
from .ui_access_manager import Feature


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


class _RefreshSignaler(QObject):
    refresh_requested = Signal()

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback
        self.refresh_requested.connect(self._on_refresh_requested)

    def request_refresh(self):
        self.refresh_requested.emit()

    def _on_refresh_requested(self):
        if self._callback is not None:
            self._callback()

    def cleanup(self) -> None:
        self.refresh_requested.disconnect(self._on_refresh_requested)
        self._callback = None


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
        self._ui_access_manager = None
        self._window: Optional[QtWidgets.QMainWindow] = None
        self._opening = False
        self._visibility_changed_callback = None
        self._refresh_signaler = _RefreshSignaler(self._refresh_window, parent_window)
        self.event_bus.subscribe(
            AppEvents.NATIVE_SCENE_UPDATED, self._on_native_scene_updated
        )
        self.event_bus.subscribe(
            AppEvents.LAYER_VISIBILITY_CHANGED, self._on_layer_visibility_changed
        )
        self.event_bus.subscribe(
            AppEvents.NAMED_VIEW_RENAMED, self._on_named_view_renamed
        )
        self.event_bus.subscribe(
            AppEvents.NAMED_VIEW_CREATED, self._on_named_view_created
        )
        self.event_bus.subscribe(
            AppEvents.NAMED_VIEW_DELETED, self._on_named_view_deleted
        )
        self.event_bus.subscribe(
            AppEvents.ANNOTATIONS_CHANGED, self._on_annotations_changed
        )

    def shutdown(self) -> None:
        if self.event_bus is not None:
            self.event_bus.unsubscribe(
                AppEvents.NATIVE_SCENE_UPDATED, self._on_native_scene_updated
            )
            self.event_bus.unsubscribe(
                AppEvents.LAYER_VISIBILITY_CHANGED, self._on_layer_visibility_changed
            )
            self.event_bus.unsubscribe(
                AppEvents.NAMED_VIEW_RENAMED, self._on_named_view_renamed
            )
            self.event_bus.unsubscribe(
                AppEvents.NAMED_VIEW_CREATED, self._on_named_view_created
            )
            self.event_bus.unsubscribe(
                AppEvents.NAMED_VIEW_DELETED, self._on_named_view_deleted
            )
            self.event_bus.unsubscribe(
                AppEvents.ANNOTATIONS_CHANGED, self._on_annotations_changed
            )
        if self._refresh_signaler is not None:
            self._refresh_signaler.cleanup()
            self._refresh_signaler.deleteLater()
            self._refresh_signaler = None
        if self._window is not None:
            self._window.close()
            self._window = None
            self._opening = False
            self._notify_visibility_changed()
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

    def _on_window_destroyed(self, _: QObject) -> None:
        self._window = None
        self._opening = False
        self._notify_visibility_changed()

    def _on_native_scene_updated(
        self, geometries: list, bounds: tuple | None = None
    ) -> None:
        if not self.is_view_open():
            return
        self._refresh_signaler.request_refresh()

    def _on_layer_visibility_changed(
        self,
        file_path: str = "",
        bid_uid: str = "",
        layer_uid: str = "",
        show: bool = True,
        image_layer: bool = False,
        all_layers: bool = False,
    ) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        bid_ref = view.bid_ref
        if bid_ref and (bid_ref.file_path != file_path or bid_ref.bid_uid != bid_uid):
            return
        self._refresh_signaler.request_refresh()

    def _on_named_view_renamed(self, named_view_uid: str, name: str) -> None:
        self.project_data.update_named_view_names([(named_view_uid, name)])
        if self._window is not None:
            self._window.update_named_view_name(named_view_uid, name)

    def _on_named_view_created(
        self, named_view_uid: str, page_uid: str, name: str
    ) -> None:
        view = self.repository.get_active_view()
        if view:
            self._update_window_navigation(view)

    def _on_named_view_deleted(self, named_view_uids: list | None = None) -> None:
        view = self.repository.get_active_view()
        if view:
            self._update_window_navigation(view)

    def _on_annotations_changed(
        self,
        page_uid: str = "",
        annotation_uids: list | None = None,
        annotation_types: list | None = None,
    ) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        if page_uid and view.target_page_uid != page_uid:
            return
        self._refresh_signaler.request_refresh()

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

    def set_ui_access_manager(self, manager) -> None:
        self._ui_access_manager = manager

    def set_visibility_changed_callback(self, callback) -> None:
        self._visibility_changed_callback = callback

    def _notify_visibility_changed(self) -> None:
        if self._visibility_changed_callback:
            self._visibility_changed_callback(self.is_view_open())

    def _is_read_only(self) -> bool:
        if not self._ui_access_manager:
            return False
        return not self._ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS)

    def _refresh_window(self) -> None:
        if not self.is_view_open():
            return
        view = self.repository.get_active_view()
        if not view:
            return
        page_data = self._get_page_data(view)
        self._update_window_navigation(view)
        self._window.set_read_only(self._is_read_only())
        self._window.update_page(page_data)

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
            return existing_view.uid if existing_view else ""
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
                self._window.load_view(
                    existing_view,
                    self._get_page_data(existing_view),
                    navigation_source=navigation_source,
                )
                self.bring_to_front()
                self._notify_visibility_changed()
                return existing_view.uid
        navigation_source = "hotlink" if target_named_view_uid else "unknown"
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
            self._create_window(
                view,
                initial_geometry,
                initial_is_maximized,
                initial_is_fullscreen,
                navigation_source,
            )
        except Exception:
            self._opening = False
            raise
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
        if self._window is not None:
            self._window.close()
            self._window = None
            self._opening = False
            self._notify_visibility_changed()
        else:
            self._opening = False

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
        self._window.load_view(
            view, self._get_page_data(view), navigation_source="hotlink"
        )

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

    def get_window(self):
        return self._window

    def _on_window_page_selected(self, page_uid: str) -> None:
        view = self.repository.get_active_view()
        if not view or not self._window:
            return
        view.update_view_target(page_uid=page_uid, named_view_uid=None)
        self.repository.update_view(view)
        page_data = self._get_page_data(view)
        self._window.load_view(view, page_data, navigation_source="combobox")

    def _on_window_scale_changed(self, page_uid: str, sf1: float, sf2: float) -> None:
        if not self._write_service:
            return
        view = self.repository.get_active_view()
        db_path = (
            view.file_path if view else self.project_data.get_current_bid_file_path()
        )
        if not db_path:
            return
        try:
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
        initial_geometry: Optional[QByteArray] = None,
        initial_is_maximized: bool = False,
        initial_is_fullscreen: bool = False,
        navigation_source: str = "unknown",
    ) -> None:
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
        self._window = self._window_factory(
            icon_provider=self.icon_provider,
            view=view,
            event_bus=self.event_bus,
            page_data=page_data,
            coord_system=coord_system,
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
        self._window.set_read_only(self._is_read_only())
        self._window.destroyed.connect(self._on_window_destroyed)
        self._window.show_when_page_ready()

    def _get_page_data(self, view: AnnotationView) -> PageViewDto:
        page_uid = view.target_page_uid
        bid_ref = view.bid_ref
        current_bid_ref = self.project_data.get_current_bid_ref()
        if bid_ref and current_bid_ref != bid_ref:
            return PageViewDto(page=None, bid_ref=bid_ref)
        page = self.project_data.get_page(page_uid)
        if not page:
            return PageViewDto(page=None, bid_ref=bid_ref)
        page_takeoffs = self.project_data.get_page_takeoffs(page_uid)
        page_annotations = self.project_data.get_page_annotations(page_uid)
        named_view = None
        if view.target_named_view_uid:
            for ann in page_annotations:
                nv = build_named_view_from_annotation(ann)
                if nv and nv.uid == view.target_named_view_uid:
                    named_view = nv
                    break
        conditions = self.project_data.get_bid_conditions()
        display_mode = self.config_model.display_mode_2d
        grayscale_enabled = self.config_model.grayscale_enabled
        _, color_map = self._color_service.get_color_mapping(
            conditions, page_takeoffs, display_mode, grayscale_enabled
        )
        return PageViewDto(
            page=page,
            takeoffs=page_takeoffs,
            conditions=conditions,
            color_map=color_map,
            bid_ref=bid_ref,
            annotations=page_annotations,
            ordered_pages=self.project_data.get_all_pages(),
            named_view=named_view,
            page_area_selections=self.project_data.get_page_area_selections(),
            hidden_layer_uids=self.project_data.get_hidden_layer_uids(),
            annotation_layer_uid=self.project_data.get_annotation_layer_uid(),
        )
