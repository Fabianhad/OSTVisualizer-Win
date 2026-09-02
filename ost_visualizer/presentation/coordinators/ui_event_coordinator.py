import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Dict, List, Mapping, Optional, Tuple, Union
from PySide6 import QtCore, QtGui, QtWidgets
from ...application.dtos.mesh_geometry_dto import (
    MeshGeometry,
    MeshSceneIdentity,
    normalize_scene_page_uids,
)
from ...application.dtos.remote_projection_dtos import (
    RemoteProjectionBarrier,
    RemoteProjectionToken,
)
from ...application.dtos.collaboration_dtos import (
    CollaborationStatus,
    EditLeaseHandle,
    EditLeaseLoss,
    EditLeaseResult,
    MutationOutcomeStatus,
    QueuedMutationResult,
    ResourceRef,
    SynchronizationState,
)
from ...application.dtos.collaboration_resource_catalog import (
    CollaborationResourceFamily,
    CollaborationResourceType,
)
from ...application.dtos.conflict_resolution_dtos import ConflictResolutionAction
from ...application.events.app_events import AppEvents
from ...application.condition_change_impact import (
    condition_changes_require_mesh_refresh,
    condition_changes_require_plan_refresh,
)
from ...application.interfaces.i_database_catalog import DatabaseCatalogError
from ...domain.entities.bid import Bid
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.loaded_file import LoadedFile
from ...domain.entities.named_view import NamedView, build_named_view_from_annotation
from ...domain.entities.project_factory import build_loaded_files
from ...domain.services.page_image_plane_transform import (
    resolve_page_floor_elevations,
)
from ..config import TAB_INDEX_PROJECTS, TAB_INDEX_SUMMARY, TAB_INDEX_TAKEOFF
from ..dialogs.adjust_images_dialog import AdjustImagesDialog, ImageAdjustmentSettings
from ..dialogs.areas_dialog import BidAreasDialog
from ..dialogs.condition_types_dialog import ConditionTypesDialog
from ..dialogs.employees_dialog import EmployeesDialog
from ..dialogs.job_statuses_dialog import JobStatusesDialog
from ..dialogs.layers_dialog import LayersDialog, LayersDialogMode
from ..dialogs.payroll_class_dialog import PayrollClassListDialog
from ..dialogs.rename_page_dialog import PageRenameTarget, RenamePageDialog
from ..dialogs.set_scale_dialog import ScaleSettings, SetScaleDialog
from ..dialogs.synchronization_conflict_dialog import SynchronizationConflictDialog
from ..handlers.condition_action_handler import ConditionActionHandler
from ..managers.app_config_presentation_manager import AppConfigPresentationManager
from ..managers.ui_access_manager import Feature, MAIN_PLAN_SURFACE_ID
from ..services.modal_edit_lease_session import ModalEditLeaseSession
from ..modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PLACE,
    CURSOR_MODE_SELECT,
)
from ..utils.image_show_mode import SHOW_BOTH, SHOW_ORIGINAL, SHOW_OVERLAY
from ..utils.messagebox import (
    DB_LOCKED_HINT,
    confirm_delete_page_with_contents,
    show_critical,
    show_warning,
)
from ..utils.named_view_focus import focus_plan_view_on_named_view
from ..utils.ost_blocking import exec_with_ost_blocking
from ..utils.overlay_context_menu import (
    resolve_overlay_visibility_mode,
    select_overlay_image_path,
)
from ..utils.qt_callback_bridge import QtVoidCallback
from ..utils.view_context_menu import build_selected_takeoff_context_state
from ..windows.mesh_view_window import MeshViewWindow
from .navigation_state_machine import NavigationStateMachine, NavState
from .placement_coordinator import PlacementCoordinator
from .sidebar_coordinator import SidebarCoordinator
from .toolbar_state_coordinator import ToolbarStateCoordinator
from .viewer_sync_coordinator import ViewerSyncCoordinator

logger = logging.getLogger(__name__)
_BID_PAGES_LOADING_STATUS = "Loading bid pages…"
MeshRenderBuffers = Tuple[
    List[List[float]],
    List[List[float]],
    List[List[int]],
    List[Dict[str, Union[float, str]]],
    List[str],
    List[str],
]


@dataclass(frozen=True)
class _SuspendedLayerTool:
    layer_uid: str
    mode: str
    annotation_type: Optional[str] = None
    condition_uid: Optional[str] = None


@dataclass(frozen=True)
class _MeshScenePublication:
    vertices: List[List[float]]
    normals: List[List[float]]
    indices: List[List[int]]
    colors: List[Dict[str, Union[float, str]]]
    scene_identity: MeshSceneIdentity
    page_floor_elevations: Mapping[str, float]
    condition_uids: List[str]
    takeoff_uids: List[str]

    def apply_to(self, surface) -> None:
        surface.apply_mesh_data(
            self.vertices,
            self.normals,
            self.indices,
            self.colors,
            scene_identity=self.scene_identity,
            page_floor_elevations=self.page_floor_elevations,
            condition_uids=self.condition_uids,
            takeoff_uids=self.takeoff_uids,
        )


def _mesh_geometries_to_render_buffers(
    geometries: List[MeshGeometry],
) -> MeshRenderBuffers:
    return (
        [geometry.vertices for geometry in geometries],
        [geometry.normals for geometry in geometries],
        [geometry.indices for geometry in geometries],
        [
            {"color": geometry.color, "opacity": geometry.opacity}
            for geometry in geometries
        ],
        [geometry.condition_uid for geometry in geometries],
        [geometry.takeoff_uid for geometry in geometries],
    )


class UIEventCoordinator:
    def __init__(
        self,
        main_window,
        ui_state_manager,
        ui_access_manager,
        event_bus,
        project_data_service,
        project_operations_service,
        visualization_service,
        color_service,
        icon_provider,
        project_write_service,
        project_read_service,
        deferred_persistence_manager,
        sql_collaboration_coordinator,
        plan_update_callback_bridge,
        workspace_state_model,
    ):
        self.main_window = main_window
        self.ui_state_manager = ui_state_manager
        self.ui_access_manager = ui_access_manager
        self.event_bus = event_bus
        self.project_data = project_data_service
        self.project_operations = project_operations_service
        self.visualization_service = visualization_service
        self._color_service = color_service
        self._icon_provider = icon_provider
        self._project_write_service = project_write_service
        self._project_read_service = project_read_service
        self._deferred_persistence = deferred_persistence_manager
        self._sql_collaboration = sql_collaboration_coordinator
        self._workspace_state_model = workspace_state_model
        self._plan_texture_provider = None
        self.conditions_sidebar = None
        self.condition_summary_tab = None
        self.takeoff_sidebar = None
        self.opengl_viewer = None
        self.plan_view = None
        self._nav = NavigationStateMachine()
        self._sidebar = SidebarCoordinator(
            project_read_service, ui_state_manager, self.project_data
        )
        self._viewer = ViewerSyncCoordinator(
            ui_state_manager,
            ui_access_manager,
            color_service,
            self.project_data,
            plan_update_callback_bridge,
        )
        self._toolbar = ToolbarStateCoordinator(
            ui_state_manager, ui_access_manager, self.project_data
        )
        self._app_config_presentation = AppConfigPresentationManager()
        self._placement = PlacementCoordinator(
            ui_state_manager=ui_state_manager,
            ui_access_manager=ui_access_manager,
            color_service=color_service,
            project_data=self.project_data,
        )
        self._placement.set_nav(self._nav)
        ui_access_manager.set_placement_coordinator(self._placement)
        self._condition_handler = ConditionActionHandler(
            coordinator=self,
            project_write_service=project_write_service,
            project_read_service=project_read_service,
            project_data=self.project_data,
            ui_state_manager=ui_state_manager,
            workspace_state_model=workspace_state_model,
        )
        self._view_stack = None
        self._status_panel = None
        self._tab_widget = None
        self._bid_data_cache: Dict[BidRef, Bid] = {}
        self._subscriptions = []
        self._page_settings_bar = None
        self._undo_service = None
        self._suspended_layer_tool: Optional[_SuspendedLayerTool] = None
        self._mesh_window: Optional[MeshViewWindow] = None
        self._mesh_window_action: Optional[QtGui.QAction] = None
        self._last_mesh_scene: Optional[_MeshScenePublication] = None
        self._mesh_scene_dirty: bool = False
        self._dirty_mesh_page_uids: set[str] = set()
        self._pending_dirty_mesh_refresh: bool = False
        self._plan_view_handler = None
        self._takeoff_workspace_bid_ref: Optional[BidRef] = None
        self._is_cleaning_up: bool = False
        self._pending_takeoff_page_uids: Optional[List[str]] = None
        self._pending_takeoff_active_page_uid: Optional[str] = None
        self._pending_takeoff_selected_area_uid: str = ""
        self._pending_takeoff_place_condition_uid: Optional[str] = None
        self._pending_takeoff_place_condition_uids: List[str] = []
        self._selected_takeoff_uids: Tuple[str, ...] = ()
        self._selection_projected_condition_uids: set[str] = set()
        self._pending_hotlink_page_uid: Optional[str] = None
        self._pending_hotlink_named_view: Optional[NamedView] = None
        self._plan_view_signaler = QtVoidCallback(parent=main_window)
        self._plan_view_signaler.set_callback(self._update_plan_view_for_active)
        self._menu_state_signaler = QtVoidCallback(parent=main_window)
        self._menu_state_signaler.set_callback(self._update_menu_state)
        self._setup_event_subscriptions()

    def set_copy_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_copy_action(action)
        self._toolbar.refresh()

    def set_cut_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_cut_action(action)
        self._toolbar.refresh()

    def set_paste_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_paste_action(action)
        self._toolbar.refresh()

    def set_bid_clipboard(self, clipboard) -> None:
        self._toolbar.set_bid_clipboard(clipboard)
        self._toolbar.refresh()

    def refresh_toolbar(self) -> None:
        if self._is_cleaning_up or self._toolbar is None:
            return
        self._toolbar.refresh()
        self._refresh_mesh_window_access()

    def _refresh_mesh_window_access(self) -> None:
        if self._mesh_window is None:
            return
        self._mesh_window.set_pick_enabled(
            self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS)
        )
        self._mesh_window.set_editing_enabled(
            self.ui_access_manager.is_allowed(Feature.EDIT_PLAN_ITEMS)
        )

    def set_delete_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_delete_action(action)
        self._toolbar.refresh()

    def set_undo_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_undo_action(action)
        self._toolbar.refresh()

    def set_redo_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_redo_action(action)
        self._toolbar.refresh()

    def set_duplicate_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_duplicate_action(action)
        self._toolbar.refresh()

    def set_select_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_select_action(action)
        self._toolbar.refresh()

    def set_select_all_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_select_all_action(action)
        self._toolbar.refresh()

    def set_backout_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_backout_action(action)
        action.toggled.connect(self._on_backout_toggled)
        self._toolbar.refresh_backout_action()

    def set_annotation_tool_actions(self, actions: list[QtGui.QAction]) -> None:
        self._toolbar.set_annotation_tool_actions(actions)
        self._toolbar.refresh()

    def set_move_overlay_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_move_overlay_action(action)
        self._toolbar.refresh()

    def refresh_backout_action(self) -> None:
        self._toolbar.refresh_backout_action()

    def set_cover_sheet_button(self, btn: QtWidgets.QToolButton) -> None:
        self._toolbar.set_cover_sheet_button(btn)
        self._toolbar.refresh()

    def set_place_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_place_action(action)
        self._toolbar.refresh()

    def set_page_settings_bar(self, bar) -> None:
        self._page_settings_bar = bar
        self._toolbar.set_page_settings_bar(bar)
        if bar:
            bar.scale_change_requested.connect(self._on_page_scale_changed)
            bar.custom_scale_requested.connect(self.open_set_scale_dialog)
            bar.area_change_requested.connect(self._on_page_area_changed)

    def update_conditions_quantities(self) -> None:
        self._sidebar.update_conditions_quantities()

    def _load_condition_summary(self) -> None:
        if not self._sidebar:
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref and self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        ):
            self._sidebar.load_condition_summary_from_memory()
            return
        self._sidebar.load_condition_summary()

    def set_conditions_sidebar(self, sidebar) -> None:
        self.conditions_sidebar = sidebar
        self._sidebar.conditions_sidebar = sidebar
        self._toolbar.set_conditions_sidebar(sidebar)
        if sidebar:
            sidebar.condition_selected.connect(self._on_condition_selected)
            sidebar.create_requested.connect(
                self._condition_handler.on_create_requested
            )
            sidebar.duplicate_requested.connect(
                self._condition_handler.on_duplicate_requested
            )
            sidebar.paste_requested.connect(self._condition_handler.on_paste_requested)
            sidebar.delete_requested.connect(
                self._condition_handler.on_delete_requested
            )
            sidebar.edit_requested.connect(self._condition_handler.on_edit_requested)
            sidebar.condition_renamed.connect(
                self._condition_handler.on_condition_renamed
            )
            sidebar.create_folder_requested.connect(
                self._condition_handler.on_create_folder_requested
            )
            sidebar.folder_renamed.connect(self._condition_handler.on_folder_renamed)
            sidebar.folder_delete_requested.connect(
                self._condition_handler.on_folder_delete_requested
            )
            sidebar.condition_folder_move_requested.connect(
                self._condition_handler.on_move_condition_to_folder
            )
            sidebar.condition_layer_change_requested.connect(
                self._condition_handler.on_condition_layer_change_requested
            )
            sidebar.condition_type_change_requested.connect(
                self._condition_handler.on_condition_type_change_requested
            )
            self._toolbar.refresh()

    def set_condition_summary_tab(self, summary_tab) -> None:
        self.condition_summary_tab = summary_tab
        self._toolbar.set_condition_summary_tab(summary_tab)
        self._sidebar.condition_summary_tab = summary_tab
        if summary_tab:
            summary_tab.delete_requested.connect(
                self._condition_handler.on_delete_requested
            )
            summary_tab.summary_action_state_changed.connect(self._toolbar.refresh)
            summary_tab.set_grouping_rebuild_callback(
                self._sidebar.set_condition_summary_grouping
            )
        self._toolbar.refresh()

    def set_bid_layers_sidebar(self, sidebar) -> None:
        self._sidebar.bid_layers_sidebar = sidebar
        self._toolbar.set_bid_layers_sidebar(sidebar)
        if sidebar:
            sidebar.set_toggle_callback(self._on_layer_visibility_toggled)
            sidebar.layer_added.connect(self._on_layer_added)
            sidebar.layer_deleted.connect(self._on_layer_deleted)
            sidebar.layers_show_all.connect(self._on_layers_show_all)
            sidebar.layer_moved.connect(self._on_layer_moved)
            sidebar.layer_renamed.connect(self._on_layer_renamed)

    def set_undo_service(self, undo_service) -> None:
        self._undo_service = undo_service
        self._toolbar.set_undo_service(undo_service)
        if undo_service:
            undo_service.set_change_callback(self._toolbar.refresh)
        self._toolbar.refresh()

    def set_takeoff_sidebar(self, sidebar) -> None:
        self.takeoff_sidebar = sidebar
        self._sidebar.takeoff_sidebar = sidebar

    def set_view_stack(self, view_stack) -> None:
        self._view_stack = view_stack
        self._sidebar.set_view_stack(view_stack)
        self._toolbar.set_view_stack(view_stack)
        view_stack.currentChanged.connect(self._on_view_stack_changed)
        self._toolbar.refresh_backout_action()

    def _on_view_stack_changed(self, index: int) -> None:
        if (
            self._is_cleaning_up
            or self._toolbar is None
            or self._sidebar is None
            or self.ui_state_manager is None
        ):
            return
        if index != 1:
            if self._placement is None:
                return
            self._placement.force_exit()
            self.ui_state_manager.clear_place_condition()
            self._toolbar.set_select_checked()
        self._sidebar.update_conditions_quantities()
        if index == 1 and self.plan_view:
            self.plan_view.reset_ctrl_held()
        if index == 0:
            self._flush_dirty_mesh_refresh_if_needed()
            if (
                not self._mesh_scene_dirty
                and not self._pending_dirty_mesh_refresh
                and self.opengl_viewer
            ):
                self._replay_mesh_if_current(self.opengl_viewer)
        self._sync_page_info_status()
        self._toolbar.refresh()

    def set_opengl_viewer(self, viewer) -> None:
        self.opengl_viewer = viewer
        self._toolbar.opengl_viewer = viewer
        if self._plan_texture_provider:
            viewer.set_plan_texture_provider(self._plan_texture_provider)
        viewer.mesh_clicked.connect(self._on_3d_mesh_clicked)
        viewer.overlay_display_mode_requested.connect(
            self._on_overlay_display_mode_requested
        )
        viewer.set_negative_check_fn(self._check_takeoffs_all_negative)
        viewer.set_curved_check_fn(self._check_takeoffs_curved_state)
        viewer.set_selected_context_state_fn(self._selected_takeoff_context_state)
        viewer.set_context_menu_conditions_fn(self.project_data.get_bid_conditions)
        self._sync_overlay_display_mode(self.ui_state_manager.active_page_uid)
        self._viewer.update_license_plan_state()
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        self._sync_embedded_renderer_exposure()

    def set_plan_texture_provider(self, provider) -> None:
        self._plan_texture_provider = provider
        for view in self._native_3d_views():
            view.set_plan_texture_provider(provider)

    def _native_3d_views(self) -> tuple:
        return tuple(
            view for view in (self.opengl_viewer, self._mesh_window) if view is not None
        )

    def _update_native_page_textures(self) -> None:
        for view in self._native_3d_views():
            view.update_plan_texture()

    def set_plan_view_handler(self, handler) -> None:
        self._plan_view_handler = handler
        self._toolbar.set_plan_view_handler(handler)

    def set_mesh_window_action(self, action: QtGui.QAction) -> None:
        self._mesh_window_action = action
        self._sync_mesh_window_action(self._mesh_window is not None)

    def get_mesh_window(self) -> Optional[MeshViewWindow]:
        return self._mesh_window

    def set_mesh_window_visible(
        self,
        visible: bool,
        *,
        initial_geometry: Optional[QtCore.QByteArray] = None,
        initial_is_maximized: bool = True,
    ) -> None:
        if visible:
            if self._mesh_window is not None:
                self._sync_mesh_window_action(True)
                return
            window = MeshViewWindow(
                icon_provider=self._icon_provider,
                color_service=self._color_service,
                negative_check_fn=self._check_takeoffs_all_negative,
                curved_check_fn=self._check_takeoffs_curved_state,
                selected_context_state_fn=self._selected_takeoff_context_state,
                context_menu_conditions_fn=self.project_data.get_bid_conditions,
            )
            window.mesh_clicked.connect(self._on_mesh_window_clicked)
            if initial_geometry is not None:
                window.set_initial_window_state(initial_geometry, initial_is_maximized)
            if self._plan_view_handler:
                window.elements_deleted.connect(
                    self._plan_view_handler.on_elements_deleted
                )
                window.assign_to_area_requested.connect(
                    self._plan_view_handler.on_assign_to_area
                )
                window.reassign_condition_requested.connect(
                    self._plan_view_handler.on_reassign_condition
                )
                window.set_negative_requested.connect(
                    self._plan_view_handler.on_set_negative
                )
                window.set_curved_requested.connect(
                    self._plan_view_handler.on_set_curved
                )
                window.overlay_display_mode_requested.connect(
                    self._on_overlay_display_mode_requested
                )
                window.undo_requested.connect(self._plan_view_handler._undo_svc.undo)
                window.redo_requested.connect(self._plan_view_handler._undo_svc.redo)
            menu_controller = self.main_window.menu_controller
            if menu_controller:
                window.set_context_menu_command_handlers(
                    menu_controller.trigger_menu_action,
                    menu_controller.get_menu_action_state,
                )
            window_identity = id(window)
            window.destroyed.connect(
                lambda _object: self._on_mesh_window_destroyed(window_identity)
            )
            self._mesh_window = window
            self._refresh_mesh_window_access()
            if self._plan_texture_provider:
                window.set_plan_texture_provider(self._plan_texture_provider)
            self._sync_overlay_display_mode(self.ui_state_manager.active_page_uid)
            self._sync_mesh_window_action(True)
            window.show_initial_window()
            replayed_current_scene = self._replay_mesh_if_current(window)
            if not self._mesh_scene_dirty and replayed_current_scene:
                return
            bid_ref = self.ui_state_manager.get_selected_bid_ref()
            page_uids = normalize_scene_page_uids(
                self.project_data.get_selected_page_uids()
            )
            pending_identity = (
                self.visualization_service.get_pending_mesh_scene_identity()
            )
            if (
                bid_ref is not None
                and pending_identity is not None
                and pending_identity.bid_ref == bid_ref
                and pending_identity.page_uids == page_uids
            ):
                window.prepare_scene_refresh(bid_ref, page_uids)
                return
            if self._mesh_scene_dirty:
                self._pending_dirty_mesh_refresh = False
                self._flush_dirty_mesh_refresh_if_needed()
                return
            self._request_or_defer_mesh_refresh(list(page_uids))
            return
        if self._mesh_window is None:
            self._sync_mesh_window_action(False)
            return
        window = self._mesh_window
        self._mesh_window = None
        self._sync_mesh_window_action(False)
        window.close()

    def _replay_mesh_if_current(self, surface) -> bool:
        publication = self._last_mesh_scene
        if publication is None:
            return False
        active_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        active_pages = normalize_scene_page_uids(
            self.project_data.get_selected_page_uids()
        )
        scene_identity = publication.scene_identity
        if (
            not isinstance(scene_identity, MeshSceneIdentity)
            or scene_identity.bid_ref != active_bid_ref
            or scene_identity.page_uids != active_pages
        ):
            logger.warning(
                "Discarding stale mesh replay for %s; active scene is %s/%s",
                scene_identity,
                active_bid_ref,
                active_pages,
            )
            self._clear_mesh_replay_buffer()
            return False
        pending_identity = self.visualization_service.get_pending_mesh_scene_identity()
        if (
            pending_identity is not None
            and pending_identity.bid_ref == scene_identity.bid_ref
            and pending_identity.page_uids == scene_identity.page_uids
            and pending_identity.generation > scene_identity.generation
        ):
            return False
        surface.prepare_scene_refresh(active_bid_ref, active_pages)
        publication.apply_to(surface)
        return True

    def _clear_mesh_replay_buffer(self) -> None:
        self._last_mesh_scene = None

    def _invalidate_mesh_scene_request(self) -> None:
        self.visualization_service.cancel_mesh_view_refresh()
        self._clear_mesh_replay_buffer()
        self._clear_mesh_dirty_state()

    def _clear_mesh_views_for_scene_update(self) -> None:
        self._invalidate_mesh_scene_request()
        for view in self._native_3d_views():
            view.clear_scene()

    def _begin_mesh_views_for_bid_load(self, bid_ref: BidRef) -> None:
        self._invalidate_mesh_scene_request()
        for view in self._native_3d_views():
            view.begin_scene_load(bid_ref)

    def _discard_mesh_camera_states(
        self,
        *,
        bid_ref: Optional[BidRef] = None,
        file_path: Optional[str] = None,
    ) -> None:
        for view in self._native_3d_views():
            view.discard_saved_camera_states(
                bid_ref=bid_ref,
                file_path=file_path,
            )

    def _is_embedded_3d_active(self) -> bool:
        return bool(
            self._tab_widget
            and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF
            and self._view_stack
            and self._view_stack.currentIndex() == 0
        )

    def _is_detached_mesh_visible(self) -> bool:
        return bool(self._mesh_window and self._mesh_window.isVisible())

    def _needs_live_3d_mesh_refresh(self) -> bool:
        return self._is_embedded_3d_active() or self._is_detached_mesh_visible()

    def _clear_mesh_dirty_state(self) -> None:
        self._mesh_scene_dirty = False
        self._dirty_mesh_page_uids.clear()
        self._pending_dirty_mesh_refresh = False

    def _mark_mesh_scene_dirty(self, page_uids: List[str]) -> None:
        valid_uids = [str(uid) for uid in page_uids if uid]
        if not valid_uids:
            return
        self._mesh_scene_dirty = True
        self._dirty_mesh_page_uids.update(valid_uids)

    def _request_or_defer_mesh_refresh(
        self,
        page_uids: List[str],
        *,
        dirty_page_uids: Optional[List[str]] = None,
    ) -> None:
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._clear_mesh_views_for_scene_update()
            return
        pages = list(normalize_scene_page_uids(page_uids))
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref is None:
            self._clear_mesh_views_for_scene_update()
            return
        affected_pages = pages
        if dirty_page_uids is not None and pages:
            selected_page_uids = set(pages)
            affected_pages = [
                page_uid
                for page_uid in normalize_scene_page_uids(dirty_page_uids)
                if page_uid in selected_page_uids
            ]
            if not affected_pages:
                return
        cached_identity = (
            self._last_mesh_scene.scene_identity
            if self._last_mesh_scene is not None
            else None
        )
        if not (
            isinstance(cached_identity, MeshSceneIdentity)
            and cached_identity.bid_ref == bid_ref
            and cached_identity.page_uids == tuple(pages)
        ):
            self._clear_mesh_replay_buffer()
        for view in self._native_3d_views():
            view.prepare_scene_refresh(bid_ref, pages)
        if not pages:
            self._clear_mesh_dirty_state()
            self.visualization_service.refresh_mesh_view([])
            return
        if self._needs_live_3d_mesh_refresh():
            self._pending_dirty_mesh_refresh = self._mesh_scene_dirty
            self.visualization_service.refresh_mesh_view(pages)
            return
        self._mark_mesh_scene_dirty(affected_pages)

    def _flush_dirty_mesh_refresh_if_needed(self) -> None:
        if (
            not self._mesh_scene_dirty
            or self._pending_dirty_mesh_refresh
            or not self.ui_access_manager.is_allowed(Feature.VIEW_3D)
        ):
            return
        selected_pages = self.project_data.get_selected_page_uids()
        if not selected_pages:
            self._request_or_defer_mesh_refresh([])
            return
        self._pending_dirty_mesh_refresh = True
        self._request_or_defer_mesh_refresh(selected_pages)

    def _on_mesh_window_clicked(self, takeoff_uids: list) -> None:
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        self._sync_selection(self._SOURCE_3D_WINDOW, takeoff_uids)

    def _on_mesh_window_destroyed(self, window_identity: int) -> None:
        if self._mesh_window is None or id(self._mesh_window) != window_identity:
            return
        self._mesh_window = None
        self._sync_mesh_window_action(False)

    def _sync_mesh_window_action(self, visible: bool) -> None:
        if self._mesh_window_action is None:
            return
        self._mesh_window_action.blockSignals(True)
        self._mesh_window_action.setChecked(visible)
        self._mesh_window_action.blockSignals(False)

    def set_plan_view(self, view) -> None:
        self.plan_view = view
        self._viewer.plan_view = view
        self._toolbar.set_plan_view(view)
        view.takeoff_selection_changed.connect(self._on_takeoff_selection_changed)
        view.takeoff_selection_command_applied.connect(
            self._on_takeoff_selection_command_applied
        )
        view.backout_mode_changed.connect(self._on_backout_mode_changed)
        view.clipboard_changed.connect(self._toolbar.refresh)
        view.text_annotation_edit_mode_changed.connect(
            self._on_text_annotation_edit_mode_changed
        )
        view.page_fully_loaded.connect(self._on_plan_view_page_fully_loaded)
        view.page_view_state_changed.connect(self._on_plan_view_state_changed)
        self._placement.set_plan_view(view)

    def set_status_panel(self, panel) -> None:
        self._status_panel = panel

    def set_tab_widget(self, tab_widget) -> None:
        self._tab_widget = tab_widget
        self._toolbar.set_tab_widget(tab_widget)
        tab_widget.currentChanged.connect(self._on_tab_changed)
        self._sync_embedded_renderer_exposure()

    def _sync_embedded_renderer_exposure(self) -> None:
        if not self.opengl_viewer or not self._tab_widget:
            return
        self.opengl_viewer.setVisible(
            self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF
        )

    def _set_takeoff_tab_visible(self, visible: bool) -> None:
        if not self._tab_widget:
            return
        self._tab_widget.setTabVisible(TAB_INDEX_TAKEOFF, visible)
        has_summary_tab = self._tab_widget.count() > TAB_INDEX_SUMMARY
        if has_summary_tab:
            self._tab_widget.setTabVisible(TAB_INDEX_SUMMARY, visible)
        if not visible and self._tab_widget.currentIndex() in (
            (TAB_INDEX_TAKEOFF, TAB_INDEX_SUMMARY)
            if has_summary_tab
            else (TAB_INDEX_TAKEOFF,)
        ):
            self._tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)

    def _clear_staged_takeoff_restore(self) -> None:
        self._pending_takeoff_page_uids = None
        self._pending_takeoff_active_page_uid = None
        self._pending_takeoff_selected_area_uid = ""
        self._pending_takeoff_place_condition_uid = None
        self._pending_takeoff_place_condition_uids = []

    def _reset_takeoff_workspace_state(self, clear_sidebars: bool = True) -> None:
        self._takeoff_workspace_bid_ref = None
        self._clear_staged_takeoff_restore()
        self._clear_pending_hotlink_named_view_focus()
        if clear_sidebars:
            self._selected_takeoff_uids = ()
            self._selection_projected_condition_uids = set()
            self._sidebar.clear_sidebars()
            if self._page_settings_bar:
                self._page_settings_bar.clear_bid()

    def _stage_takeoff_restore(
        self,
        page_uids: Optional[List[str]] = None,
        active_page_uid: Optional[str] = None,
        selected_area_uid: str = "",
        place_condition_uid: Optional[str] = None,
        place_condition_uids: Optional[List[str]] = None,
    ) -> None:
        if page_uids is None:
            self._pending_takeoff_page_uids = None
            self._pending_takeoff_active_page_uid = None
        else:
            valid_page_uids = [
                uid for uid in page_uids if uid and self.project_data.get_page(uid)
            ]
            valid_active_uid = (
                active_page_uid
                if active_page_uid and self.project_data.get_page(active_page_uid)
                else None
            )
            if not valid_page_uids and not valid_active_uid:
                self._pending_takeoff_page_uids = None
                self._pending_takeoff_active_page_uid = None
            else:
                self._pending_takeoff_page_uids = valid_page_uids
                self._pending_takeoff_active_page_uid = (
                    valid_active_uid or valid_page_uids[0]
                )
        self._pending_takeoff_selected_area_uid = selected_area_uid or ""
        self._pending_takeoff_place_condition_uid = place_condition_uid
        self._pending_takeoff_place_condition_uids = list(place_condition_uids or [])

    def _resolve_takeoff_selection(self) -> tuple[List[str], Optional[str]]:
        if self._pending_takeoff_page_uids is not None:
            page_uids = [
                uid
                for uid in self._pending_takeoff_page_uids
                if uid and self.project_data.get_page(uid)
            ]
            active_uid = self._pending_takeoff_active_page_uid
            if active_uid and not self.project_data.get_page(active_uid):
                active_uid = None
            if not active_uid:
                active_uid = page_uids[0] if page_uids else None
            return page_uids, active_uid
        selected_uids = [
            uid
            for uid in self.ui_state_manager.selected_page_uids
            if uid and self.project_data.get_page(uid)
        ]
        active_uid = self.ui_state_manager.active_page_uid
        if active_uid and not self.project_data.get_page(active_uid):
            active_uid = None
        if selected_uids:
            if not active_uid:
                active_uid = selected_uids[0]
            return selected_uids, active_uid
        if active_uid:
            return [], active_uid
        target_page = self.project_data.get_last_selected_page_uid()
        if target_page and self.project_data.get_page(target_page):
            return [target_page], target_page
        first_page = self.takeoff_sidebar.get_first_page_uid()
        if first_page and self.project_data.get_page(first_page):
            return [first_page], first_page
        return [], None

    def _activate_takeoff_workspace(self) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref or not self.takeoff_sidebar:
            return
        needs_hydration = self._takeoff_workspace_bid_ref != bid_ref
        if needs_hydration:
            if self._page_settings_bar:
                self._page_settings_bar.load_bid_areas(
                    bid_ref,
                    areas_with_takeoff=(self.project_data.get_area_uids_with_takeoff()),
                    selected_uid=self._pending_takeoff_selected_area_uid or None,
                )
            if self._project_write_service.uses_sql_collaboration_mutations(
                bid_ref.file_path
            ):
                self._sidebar.load_takeoff_sidebar_from_memory(
                    bid_ref, self._bid_data_cache
                )
                self._sidebar.load_bid_layers_sidebar_from_memory()
                self._sidebar.refresh_conditions_from_memory()
            else:
                self._load_takeoff_sidebar(bid_ref)
                self._sidebar.load_bid_layers_sidebar()
                self._sidebar.load_conditions_sidebar()
                self._sidebar.update_conditions_quantities()
            self._load_condition_summary()
            highlighted = self._validate_condition_uids(
                self.ui_state_manager.highlighted_condition_uids
            )
            self._restore_sidebar_highlight(highlighted, reveal=False)
            self._takeoff_workspace_bid_ref = bid_ref
        should_restore_selection = (
            needs_hydration
            or self._pending_takeoff_page_uids is not None
            or not self.ui_state_manager.selected_page_uids
            or not self.ui_state_manager.active_page_uid
        )
        if should_restore_selection:
            page_uids, active_uid = self._resolve_takeoff_selection()
            active_page_changed = False
            if page_uids or self._pending_takeoff_page_uids is not None:
                active_page_changed = self.takeoff_sidebar.restore_selection(
                    page_uids, active_uid
                )
            if not active_page_changed:
                self.handle_active_page_changed(active_uid)
        else:
            self._sidebar.update_conditions_quantities()
            self._sync_page_info_status()
        if (
            self._pending_takeoff_place_condition_uid
            and self._pending_takeoff_place_condition_uid
            in self.project_data.get_bid_conditions()
        ):
            if self._is_condition_placeable(self._pending_takeoff_place_condition_uid):
                if self._is_takeoff_2d_view_active():
                    self._placement.enter(
                        self._pending_takeoff_place_condition_uid,
                        self._pending_takeoff_place_condition_uids,
                    )
                else:
                    self._reset_to_select_mode()
            else:
                self._reset_to_select_mode()
        self._clear_staged_takeoff_restore()
        self.main_window.notify_takeoff_workspace_activated()
        self._sync_embedded_renderer_exposure()

    def _on_tab_changed(self, index: int) -> None:
        if self.opengl_viewer:
            self.opengl_viewer.setVisible(False)
        if index == TAB_INDEX_TAKEOFF:
            self._activate_takeoff_workspace()
            self._update_export_menu_state()
            self._sync_page_info_status()
            return
        if index == TAB_INDEX_SUMMARY:
            self._load_condition_summary()
            self._update_export_menu_state()
            self._sync_page_info_status()
            return
        self._sync_page_info_status()
        self._update_export_menu_state()

    def navigate_to_takeoff_page(self, page_uid: str, named_view_uid: str = "") -> None:
        if not page_uid or not self.project_data.get_page(page_uid):
            self._clear_pending_hotlink_named_view_focus()
            return
        self._stage_hotlink_named_view_focus(page_uid, named_view_uid)
        self._stage_takeoff_restore([page_uid], page_uid)
        self._set_takeoff_tab_visible(True)
        if self._tab_widget and self._tab_widget.currentIndex() != TAB_INDEX_TAKEOFF:
            self._tab_widget.setCurrentIndex(TAB_INDEX_TAKEOFF)
        else:
            self._activate_takeoff_workspace()

    def apply_pending_hotlink_view_focus(self) -> None:
        self._apply_pending_hotlink_named_view_focus(require_stable=True)

    def _stage_hotlink_named_view_focus(
        self, page_uid: str, named_view_uid: str
    ) -> None:
        named_view = self._resolve_hotlink_named_view(page_uid, named_view_uid)
        if named_view is None:
            self._clear_pending_hotlink_named_view_focus()
            return
        self._pending_hotlink_page_uid = page_uid
        self._pending_hotlink_named_view = named_view
        if self._should_defer_hotlink_page_visual(page_uid):
            self.plan_view.set_page_visual_reveal_deferred(True)

    def _resolve_hotlink_named_view(
        self, page_uid: str, named_view_uid: str
    ) -> Optional[NamedView]:
        if not named_view_uid:
            return None
        for annotation in self.project_data.get_page_annotations(page_uid):
            named_view = build_named_view_from_annotation(annotation)
            if named_view and named_view.uid == named_view_uid:
                return named_view
        return None

    def _should_defer_hotlink_page_visual(self, page_uid: str) -> bool:
        if not self.plan_view:
            return False
        same_loaded_page = (
            self.plan_view.current_page_uid == page_uid
            and self.plan_view.is_view_state_stable
        )
        return not same_loaded_page

    def _clear_pending_hotlink_named_view_focus(self) -> None:
        self._pending_hotlink_page_uid = None
        self._pending_hotlink_named_view = None
        if self.plan_view:
            self.plan_view.reveal_deferred_page_visual()

    def _on_plan_view_page_fully_loaded(self) -> None:
        self._apply_pending_hotlink_named_view_focus(require_stable=True)

    def _on_plan_view_state_changed(
        self, page_uid: str, zoom_fac: float, current_x: float, current_y: float
    ) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref or not page_uid or zoom_fac <= 0:
            return
        page = self.project_data.get_page(page_uid)
        if page:
            page.zoom_fac = zoom_fac
            page.current_x = current_x
            page.current_y = current_y
        can_persist = self.ui_access_manager.is_allowed(
            Feature.EDIT_PAGE_SETTINGS
        ) or self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        if not can_persist:
            return
        self._deferred_persistence.schedule_page_view_state(
            bid_ref.file_path,
            bid_ref.bid_uid,
            page_uid,
            zoom_fac,
            current_x,
            current_y,
        )

    def _apply_pending_hotlink_named_view_focus(self, require_stable: bool) -> bool:
        named_view = self._pending_hotlink_named_view
        page_uid = self._pending_hotlink_page_uid
        if not named_view or not page_uid or not self.plan_view:
            return False
        current_page_uid = self.plan_view.current_page_uid
        if current_page_uid != page_uid:
            if current_page_uid:
                self._clear_pending_hotlink_named_view_focus()
            return False
        if require_stable and not self.plan_view.is_view_state_stable:
            return False
        if not self.plan_view.isVisible():
            return False
        focus_plan_view_on_named_view(self.plan_view, named_view)
        self._pending_hotlink_page_uid = None
        self._pending_hotlink_named_view = None
        self.plan_view.reveal_deferred_page_visual()
        return True

    def _apply_sidebar_highlight(self, uids: set, reveal: bool = True) -> bool:
        if self._nav.is_refreshing:
            return False
        self.ui_state_manager.set_highlighted_conditions(uids)
        if self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(uids, reveal=reveal)
        return True

    def highlight_sidebar(self, uids: set, reveal: bool = True) -> None:
        self._selection_projected_condition_uids = set()
        self._apply_sidebar_highlight(uids, reveal=reveal)

    def _restore_sidebar_highlight(self, uids: set, reveal: bool = False) -> None:
        takeoff_owned = self._selection_projected_condition_uids == set(uids)
        self._apply_sidebar_highlight(uids, reveal=reveal)
        if not takeoff_owned:
            self._selection_projected_condition_uids = set()

    def _is_takeoff_2d_view_active(self) -> bool:
        return self._toolbar.is_takeoff_2d_view_active()

    def _set_plan_select_mode(self) -> None:
        if self.plan_view:
            self.plan_view.reset_ctrl_held()
            self.plan_view.set_cursor_mode(CURSOR_MODE_SELECT)
        self._toolbar.set_select_checked()

    def _active_layer_tool_snapshot(
        self, layer_uid: Optional[str]
    ) -> Optional[_SuspendedLayerTool]:
        if not self.plan_view:
            return None
        layer_key = str(layer_uid) if layer_uid is not None else None
        if self.plan_view.cursor_mode == CURSOR_MODE_ANNOTATION_PLACE:
            annotation_layer_uid = self.project_data.get_annotation_layer_uid()
            if annotation_layer_uid:
                annotation_layer_key = str(annotation_layer_uid)
                if layer_key is None or layer_key == annotation_layer_key:
                    annotation_type = self.plan_view.annotation_place_type
                    if annotation_type:
                        return _SuspendedLayerTool(
                            annotation_layer_key,
                            CURSOR_MODE_ANNOTATION_PLACE,
                            annotation_type=annotation_type,
                        )
        condition_uid = (
            self.plan_view.place_condition_uid
            if self.plan_view.cursor_mode == CURSOR_MODE_PLACE
            else None
        )
        if condition_uid:
            condition = self.project_data.get_bid_conditions().get(condition_uid)
            if condition and condition.layer_uid:
                condition_layer_key = str(condition.layer_uid)
                if layer_key is None or layer_key == condition_layer_key:
                    return _SuspendedLayerTool(
                        condition_layer_key,
                        CURSOR_MODE_PLACE,
                        condition_uid=condition_uid,
                    )
        return None

    def _suspend_active_layer_tool(self, layer_uid: Optional[str] = None) -> None:
        suspended = self._active_layer_tool_snapshot(layer_uid)
        if suspended is None:
            return
        self._suspended_layer_tool = suspended
        self._set_plan_select_mode()

    def _restore_suspended_layer_tool(self, layer_uid: Optional[str] = None) -> None:
        suspended = self._suspended_layer_tool
        if suspended is None or not self.plan_view:
            return
        layer_key = str(layer_uid) if layer_uid is not None else None
        if layer_key is not None and suspended.layer_uid != layer_key:
            return
        if self.plan_view.cursor_mode != CURSOR_MODE_SELECT:
            self._suspended_layer_tool = None
            return
        if suspended.mode == CURSOR_MODE_ANNOTATION_PLACE and suspended.annotation_type:
            if self.ui_access_manager.is_allowed(Feature.PLACE_ANNOTATIONS):
                self.plan_view.activate_annotation_placement(suspended.annotation_type)
        elif suspended.mode == CURSOR_MODE_PLACE and suspended.condition_uid:
            condition = self.project_data.get_bid_conditions().get(
                suspended.condition_uid
            )
            if (
                condition
                and condition.layer_visible
                and self._is_takeoff_2d_view_active()
                and self.ui_access_manager.is_allowed(Feature.PLACE_PLAN_ITEMS)
            ):
                self._placement.enter(
                    suspended.condition_uid, [suspended.condition_uid]
                )
        self._suspended_layer_tool = None

    def _canonical_takeoff_selection(
        self, uids: list
    ) -> tuple[Tuple[str, ...], set[str]]:
        condition_uid_by_takeoff = {
            takeoff.uid: takeoff.condition_uid
            for takeoff in self.project_data.get_all_takeoffs()
        }
        selected = tuple(
            sorted({uid for uid in uids if uid in condition_uid_by_takeoff})
        )
        condition_uids = {condition_uid_by_takeoff[uid] for uid in selected}
        return selected, condition_uids

    def _project_takeoff_selection_conditions(
        self,
        condition_uids: set[str],
        *,
        selection_changed: bool,
        selection_command_applied: bool = False,
    ) -> bool:
        current = set(self.ui_state_manager.highlighted_condition_uids)
        previously_projected = set(self._selection_projected_condition_uids)
        if condition_uids:
            sidebar_projection = (
                set(self.conditions_sidebar.get_selected_condition_uids())
                if self.conditions_sidebar
                else set(condition_uids)
            )
            projection_complete = (
                current == condition_uids and sidebar_projection == condition_uids
            )
            if projection_complete:
                if previously_projected:
                    self._selection_projected_condition_uids = set(condition_uids)
                return False
            takeoff_owns_highlight = bool(previously_projected)
            if takeoff_owns_highlight or selection_changed or selection_command_applied:
                self._selection_projected_condition_uids = set(condition_uids)
                takeoff_owns_highlight = True
            if not takeoff_owns_highlight:
                return False
            return self._apply_sidebar_highlight(condition_uids)
        placement_owns_highlight = bool(
            self._placement.is_active
            and self._placement.condition_uid
            and self._placement.condition_uid in previously_projected
        )
        selection_owns_highlight = bool(
            previously_projected and current.issubset(previously_projected)
        )
        if not selection_owns_highlight or placement_owns_highlight:
            return False
        if not current:
            self._selection_projected_condition_uids = set()
            return False
        projection_changed = self._apply_sidebar_highlight(set())
        if projection_changed:
            self._selection_projected_condition_uids = set()
        return projection_changed

    _SOURCE_2D = "2d"
    _SOURCE_3D = "3d_embedded"
    _SOURCE_3D_WINDOW = "3d_window"
    _SOURCE_MODEL = "model"

    def _sync_selection(
        self,
        source: str,
        takeoff_uids: list,
        *,
        selection_command_applied: bool = False,
    ) -> None:
        if self._placement is None or self._nav is None:
            return
        selected_uids, cond_uids = self._canonical_takeoff_selection(takeoff_uids)
        previous_selection = self._selected_takeoff_uids
        selection_changed = selected_uids != previous_selection
        self._selected_takeoff_uids = selected_uids
        projection_changed = self._project_takeoff_selection_conditions(
            cond_uids,
            selection_changed=selection_changed,
            selection_command_applied=selection_command_applied,
        )
        if not selection_changed:
            if (
                projection_changed
                and self._tab_widget
                and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF
            ):
                self._toolbar.refresh()
            return
        if selected_uids:
            mirrored_uids = list(selected_uids)
            if source != self._SOURCE_2D and self.plan_view:
                self.plan_view.set_selected_uids(set(selected_uids), emit=False)
            if source != self._SOURCE_3D and self.opengl_viewer:
                self.opengl_viewer.set_selected_takeoffs(mirrored_uids)
            if source != self._SOURCE_3D_WINDOW and self._mesh_window:
                self._mesh_window.set_selected_takeoffs(mirrored_uids)
        else:
            if source != self._SOURCE_2D and self.plan_view:
                self.plan_view.clear_selection(emit=False)
            if source != self._SOURCE_3D and self.opengl_viewer:
                self.opengl_viewer.set_selected_takeoffs([])
            if source != self._SOURCE_3D_WINDOW and self._mesh_window:
                self._mesh_window.set_selected_takeoffs([])
        if self._tab_widget and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            self._toolbar.refresh()

    def _on_3d_mesh_clicked(self, takeoff_uids: list) -> None:
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        self._sync_selection(self._SOURCE_3D, takeoff_uids)

    def _on_takeoff_selection_changed(self, uids: list) -> None:
        if self._placement is None or self._nav is None:
            return
        self._sync_selection(self._SOURCE_2D, uids)
        self._restore_project_tree_bid_selection_if_needed()

    def _on_takeoff_selection_command_applied(self, uids: list) -> None:
        if self._placement is None or self._nav is None:
            return
        self._sync_selection(
            self._SOURCE_2D,
            uids,
            selection_command_applied=True,
        )
        self._restore_project_tree_bid_selection_if_needed()

    def _on_backout_mode_changed(self, _active: bool) -> None:
        self._toolbar.refresh_backout_action()

    def _on_backout_toggled(self, checked: bool) -> None:
        if not self.plan_view:
            self._toolbar.refresh_backout_action()
            return
        if checked:
            parent_uid = self._toolbar.current_backout_candidate_uid()
            if not parent_uid:
                self._toolbar.refresh_backout_action()
                return
            if not self.plan_view.enter_backout_mode(parent_uid):
                self._toolbar.refresh_backout_action()
                return
            takeoff = self.plan_view.get_takeoff(parent_uid)
            condition_uid = takeoff.condition_uid if takeoff else None
            if not condition_uid or not self._placement.enter(
                condition_uid, [condition_uid]
            ):
                self.plan_view.cancel_backout_mode()
                self._toolbar.refresh_backout_action()
                return
            self._toolbar.refresh_backout_action()
            return
        self.plan_view.cancel_backout_mode()
        self._toolbar.refresh_backout_action()

    def _on_text_annotation_edit_mode_changed(self, active: bool) -> None:
        self.ui_access_manager.set_text_annotation_edit_active(
            active, surface_id=MAIN_PLAN_SURFACE_ID
        )
        self._update_menu_state()

    def _setup_event_subscriptions(self) -> None:
        self._subscribe(AppEvents.FILE_OPENED, self._on_file_opened)
        self._subscribe(AppEvents.DATABASE_REFRESHED, self._on_database_refreshed)
        self._subscribe(
            AppEvents.DATABASE_CAPABILITIES_CHANGED,
            self._on_database_capabilities_changed,
        )
        self._subscribe(AppEvents.TAKEOFFS_CHANGED, self._on_takeoffs_changed)
        self._subscribe(AppEvents.ANNOTATIONS_CHANGED, self._on_annotations_changed)
        self._subscribe(
            AppEvents.PENDING_PLAN_MUTATIONS_CHANGED,
            self._on_pending_plan_mutations_changed,
        )
        self._subscribe(
            AppEvents.CONDITIONS_CHANGED,
            self._on_conditions_changed,
        )
        self._subscribe(AppEvents.REMOTE_AREAS_CHANGED, self._on_remote_areas_changed)
        self._subscribe(
            AppEvents.REMOTE_BID_CONTENT_CHANGED,
            self._on_remote_bid_content_changed,
        )
        self._subscribe(
            AppEvents.REMOTE_HIERARCHY_CHANGED,
            self._on_remote_hierarchy_changed,
        )
        self._subscribe(
            AppEvents.REMOTE_PLAN_PROJECTION_REQUESTED,
            self._on_remote_plan_projection_requested,
        )
        self._subscribe(
            AppEvents.COLLABORATION_STATE_CHANGED,
            self._on_collaboration_state_changed,
        )
        self._subscribe(
            AppEvents.COLLABORATION_MUTATION_STATE_CHANGED,
            self._on_collaboration_mutation_state_changed,
        )
        self._subscribe(AppEvents.PRESENCE_CHANGED, self._on_presence_changed)
        self._subscribe(
            AppEvents.FULL_RECONCILIATION_REQUIRED,
            self._on_full_reconciliation_required,
        )
        self._subscribe(
            AppEvents.SYNCHRONIZATION_CONFLICT,
            self._on_synchronization_conflict,
        )
        self._subscribe(AppEvents.EDIT_LEASE_LOST, self._on_edit_lease_lost)
        self._subscribe(AppEvents.FILE_UNLOADED, self._on_file_unloaded)
        self._subscribe(AppEvents.FILE_SELECTED, self._on_file_selected)
        self._subscribe(AppEvents.APP_CONFIG_UPDATED, self._on_app_config_updated)
        self._subscribe(
            AppEvents.LICENSE_STATUS_CHANGED, self._on_license_status_changed
        )
        self._subscribe(AppEvents.NATIVE_SCENE_UPDATED, self._on_native_scene_updated)
        self._subscribe(AppEvents.OST_STATUS_CHANGED, self._on_ost_status_changed)

    def _subscribe(self, event_name: str, callback) -> None:
        self.event_bus.subscribe(event_name, callback)
        self._subscriptions.append((event_name, callback))

    def _update_export_menu_state(self) -> None:
        self._update_menu_state()
        self._toolbar.refresh()

    def _update_menu_state(self) -> None:
        self.main_window.menu_controller.update_menu_states()

    def refresh_conditions_ui(self) -> None:
        self._sidebar.refresh_conditions_from_memory()
        self._viewer.update_plan_view_for_active()

    def request_collaboration_edit(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        callback: Callable[[EditLeaseResult], None],
        *,
        dependency_resources: tuple[ResourceRef, ...] = (),
        operation_id: str = "",
        owning_surface: str = "desktop",
    ) -> None:
        def resolved(result: EditLeaseResult) -> None:
            if self._is_cleaning_up:
                if result.handle is not None:
                    self._sql_collaboration.end_edit_lease(result.handle)
                callback(
                    EditLeaseResult(
                        False,
                        "The edit was cancelled while the view was closing.",
                    )
                )
                return
            if not self._collaboration_edit_context_is_current(
                database_id, resources, owning_surface
            ):
                if result.handle is not None:
                    self._sql_collaboration.end_edit_lease(result.handle)
                callback(
                    EditLeaseResult(
                        False,
                        "The edit was cancelled because its original context changed.",
                    )
                )
                return
            if not result.granted:
                if owning_surface == "main-plan":
                    self._prepare_for_modal_mutation_error(database_id)
                show_warning(
                    self.main_window,
                    "Editing Unavailable",
                    result.message or "The edit lease could not be acquired.",
                )
            callback(result)

        self._sql_collaboration.request_local_edit(
            database_id,
            resources,
            resolved,
            dependency_resources=dependency_resources,
            operation_id=operation_id,
            owning_surface=owning_surface,
        )

    def _collaboration_edit_context_is_current(
        self,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        owning_surface: str,
    ) -> bool:
        if (
            owning_surface == "condition-sidebar"
            and self._tab_widget.currentIndex() != TAB_INDEX_TAKEOFF
        ):
            return False
        if normalize_path(
            self.ui_state_manager.selected_file_path or ""
        ) != normalize_path(database_id):
            return False
        bid_uids = {
            str(resource.bid_uid)
            for resource in resources
            if resource.bid_uid is not None
        }
        if not bid_uids:
            return True
        selected_bid = self.ui_state_manager.get_selected_bid_ref()
        return bool(
            len(bid_uids) == 1
            and selected_bid is not None
            and normalize_path(selected_bid.file_path) == normalize_path(database_id)
            and str(selected_bid.bid_uid) in bid_uids
        )

    def end_collaboration_edit(self, handle: EditLeaseHandle) -> None:
        self._sql_collaboration.end_edit_lease(handle)

    def _exec_with_collaboration_lease(
        self,
        dialog: QtWidgets.QDialog,
        database_id: str,
        resources: tuple[ResourceRef, ...],
        cleanup: Callable[[], None],
        after_close: Optional[Callable[[bool], None]] = None,
        lease_session: Optional[ModalEditLeaseSession] = None,
    ) -> None:
        def resolved(result: EditLeaseResult) -> None:
            executed = False
            try:
                if result.granted:
                    if lease_session is not None:
                        lease_session.accept_initial_lease(result)
                    exec_with_ost_blocking(dialog, self.event_bus)
                    executed = True
            finally:
                if lease_session is not None:
                    lease_session.close()
                elif result.handle is not None:
                    self.end_collaboration_edit(result.handle)
                if after_close is not None:
                    after_close(executed)
                cleanup()
                dialog.deleteLater()

        self.request_collaboration_edit(
            database_id,
            resources,
            resolved,
            operation_id=type(dialog).__name__,
            owning_surface="main-window-dialog",
        )

    def can_renumber_conditions(self) -> bool:
        return self._condition_handler.can_renumber_conditions()

    def renumber_conditions(self) -> None:
        self._condition_handler.on_renumber_requested()

    def open_areas_dialog(self) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        areas = (
            self.project_data.get_bid_area_snapshot()
            if uses_sql_queue
            else self._project_read_service.get_bid_areas(
                bid_ref.file_path, bid_ref.bid_uid
            )
        )
        used_uids = self.project_data.get_area_uids_with_takeoff()
        area_bid_uid = (
            int(bid_ref.bid_uid) if str(bid_ref.bid_uid).isdecimal() else None
        )
        area_resource = ResourceRef(
            CollaborationResourceType.AREAS_COLLECTION.value,
            bid_ref.bid_uid,
            area_bid_uid,
        )
        area_resources = (
            area_resource,
            *(ResourceRef("area", str(area.uid), area_bid_uid) for area in areas),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                bid_ref.file_path,
                area_resources,
                "BidAreasDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )

        def save_fn(changes):
            return self._save_bid_areas_from_dialog(bid_ref, changes)

        dialog = BidAreasDialog(
            self._icon_provider,
            parent=self.main_window,
            bid_areas=areas,
            save_fn=save_fn,
            save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_bid_areas_async(
                            bid_ref,
                            changes,
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            used_uids=used_uids,
            has_license=True,
            bid_ref=bid_ref,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)

        def after_close(executed: bool) -> None:
            if (
                executed
                and dialog.has_saved_changes()
                and not uses_sql_queue
                and not self._project_write_service.reload_and_notify(bid_ref.file_path)
            ):
                show_warning(
                    self.main_window,
                    "Refresh Error",
                    "The bid area changes were saved, but the area list could not be "
                    "refreshed. Reopen the database to see the latest bid areas.",
                )

        self._exec_with_collaboration_lease(
            dialog,
            bid_ref.file_path,
            area_resources,
            dialog.cleanup,
            after_close,
            lease_session,
        )

    def _save_bid_areas_from_dialog(self, bid_ref, changes):
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return None
        result = self._project_write_service.save_bid_areas_result(
            bid_ref.file_path,
            bid_ref.bid_uid,
            changes,
            publish_database_refreshed_after_write=False,
        )
        if not result.write_success:
            return None
        if result.refresh_failed:
            show_warning(
                self.main_window,
                "Refresh Error",
                "The bid area changes were saved, but the area list could not be "
                "refreshed. Reopen the database to see the latest bid areas.",
            )
        return result

    def _save_bid_areas_async(
        self,
        bid_ref,
        changes,
        completed,
        *,
        edit_lease_handle: Optional[EditLeaseHandle] = None,
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            completed(False, None)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if result.outcome_status in (
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            ):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                authoritative = result.authoritative_result
                maps = dict(authoritative.created_uid_maps) if authoritative else {}
                completed(True, dict(maps.get("areas", ())))
                return
            self.present_queued_mutation_error(
                bid_ref.file_path,
                "Bid Areas",
                result,
            )
            completed(False, None)

        try:
            if edit_lease_handle is None:
                self._project_write_service.queue_bid_areas_save(
                    bid_ref.file_path, bid_ref.bid_uid, changes, finish
                )
            else:
                self._project_write_service.queue_bid_areas_save(
                    bid_ref.file_path,
                    bid_ref.bid_uid,
                    changes,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, "Bid Areas", str(exc))
            return False
        return True

    def save_bid_areas_async(self, bid_ref, changes, completed) -> bool:
        return self._save_bid_areas_async(bid_ref, changes, completed)

    def open_employees_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        if uses_sql_queue:
            employees = self.project_data.get_employee_snapshot(file_path)
            pay_classes = self.project_data.get_pay_class_snapshot(file_path)
            used_employee_uids = self.project_data.get_used_employee_uids(file_path)
        else:
            employees, pay_classes = (
                self._project_read_service.get_employees_and_pay_classes(file_path)
            )
            used_employee_uids = self._project_read_service.get_estimator_uids_in_use(
                file_path
            )
        resources = (
            ResourceRef(
                CollaborationResourceType.EMPLOYEES_COLLECTION.value, "database"
            ),
            ResourceRef(
                CollaborationResourceType.PAY_CLASSES_COLLECTION.value, "database"
            ),
            *(ResourceRef("employee", str(item.uid)) for item in employees),
            *(ResourceRef("pay_class", str(item.uid)) for item in pay_classes),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "EmployeesDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = EmployeesDialog(
            self._icon_provider,
            parent=self.main_window,
            employees=employees,
            used_uids=used_employee_uids,
            pay_classes=pay_classes,
            save_fn=lambda changes: self._save_master_employees_result(
                file_path, changes
            ),
            save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Employees",
                            self._project_write_service.queue_employees_save,
                            changes,
                            lease_completed,
                            "employees",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            pay_classes_save_fn=lambda changes: self._save_master_pay_classes(
                file_path, changes
            ),
            pay_classes_save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Payroll Classes",
                            self._project_write_service.queue_pay_classes_save,
                            changes,
                            lease_completed,
                            "pay_classes",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            menu_mode=True,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog, file_path, resources, dialog.cleanup, lease_session=lease_session
        )

    def open_job_statuses_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        if uses_sql_queue:
            job_statuses = self.project_data.get_job_status_snapshot(file_path)
            used_job_status_uids = self.project_data.get_used_job_status_uids(file_path)
        else:
            bid_ref = self.ui_state_manager.get_selected_bid_ref()
            data = (
                self._project_read_service.get_cover_sheet_data(
                    file_path, bid_ref.bid_uid
                )
                if bid_ref
                and normalize_path(bid_ref.file_path) == normalize_path(file_path)
                else None
            )
            job_statuses = (
                data.job_statuses
                if data
                else self._project_read_service.get_job_statuses(file_path)
            )
            used_job_status_uids = (
                data.used_job_status_uids if data is not None else set()
            )
        resources = (
            ResourceRef(
                CollaborationResourceType.JOB_STATUSES_COLLECTION.value,
                "database",
            ),
            *(ResourceRef("job_status", str(item.uid)) for item in job_statuses),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "JobStatusesDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = JobStatusesDialog(
            self._icon_provider,
            parent=self.main_window,
            job_statuses=job_statuses,
            used_job_status_uids=used_job_status_uids,
            save_fn=lambda changes: self._save_master_job_statuses(file_path, changes),
            save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Job Statuses",
                            self._project_write_service.queue_job_statuses_save,
                            changes,
                            lease_completed,
                            "job_statuses",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            menu_mode=True,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def open_condition_types_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        resources = (
            ResourceRef(
                CollaborationResourceType.CONDITION_TYPES_COLLECTION.value,
                "database",
            ),
        )
        condition_types = list(
            (
                self.project_data.get_cdn_types()
                if uses_sql_queue
                else self._project_read_service.get_cdn_types(file_path)
            ).values()
        )
        resources = (
            *resources,
            *(ResourceRef("condition_type", str(item.uid)) for item in condition_types),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "ConditionTypesDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = ConditionTypesDialog(
            self._icon_provider,
            parent=self.main_window,
            condition_types=condition_types,
            save_fn=lambda changes: self._save_master_condition_types(
                file_path, changes
            ),
            save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: (
                            self._save_master_condition_types_async(
                                file_path,
                                changes,
                                lease_completed,
                                edit_lease_handle=handle,
                            )
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            blocked_delete_uids_fn=(
                (lambda _uids: set())
                if uses_sql_queue
                else lambda uids: {
                    str(uid)
                    for uid in self._project_write_service.validate_condition_types_delete(
                        file_path, uids
                    ).blocked_uids
                }
            ),
            delete_fn=lambda uids: self._delete_master_condition_types(file_path, uids),
            reload_fn=(
                (lambda: list(self.project_data.get_cdn_types().values()))
                if uses_sql_queue
                else lambda: list(
                    self._project_read_service.get_cdn_types(file_path).values()
                )
            ),
            has_license=True,
            menu_mode=True,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def open_payroll_classes_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        if uses_sql_queue:
            employees = self.project_data.get_employee_snapshot(file_path)
            pay_classes = self.project_data.get_pay_class_snapshot(file_path)
        else:
            employees, pay_classes = (
                self._project_read_service.get_employees_and_pay_classes(file_path)
            )
        used_pay_class_uids = {
            str(employee.pay_class_uid)
            for employee in employees
            if employee.pay_class_uid
        }
        resources = (
            ResourceRef(
                CollaborationResourceType.PAY_CLASSES_COLLECTION.value,
                "database",
            ),
            *(ResourceRef("pay_class", str(item.uid)) for item in pay_classes),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "PayrollClassListDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = PayrollClassListDialog(
            self._icon_provider,
            parent=self.main_window,
            pay_classes=pay_classes,
            used_pay_class_uids=used_pay_class_uids,
            save_fn=lambda changes: self._save_master_pay_classes(file_path, changes),
            save_async_fn=(
                (
                    lambda changes, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_master_data_async(
                            file_path,
                            "Payroll Classes",
                            self._project_write_service.queue_pay_classes_save,
                            changes,
                            lease_completed,
                            "pay_classes",
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            menu_mode=True,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def open_default_layers_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        layers = (
            self.project_data.get_default_layer_snapshot(file_path)
            if uses_sql_queue
            else self._project_read_service.get_default_layers(file_path)
        )
        reload_layers = (
            (lambda: self.project_data.get_default_layer_snapshot(file_path))
            if uses_sql_queue
            else (lambda: self._project_read_service.get_default_layers(file_path))
        )
        resources = (
            ResourceRef(
                CollaborationResourceType.DEFAULT_LAYERS_COLLECTION.value,
                "database",
            ),
        )
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "LayersDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = LayersDialog(
            self._icon_provider,
            parent=self.main_window,
            layers=layers,
            reload_fn=reload_layers,
            insert_fn=lambda name, after_sequence: (
                self._insert_default_layer_from_dialog(file_path, name, after_sequence)
            ),
            delete_many_fn=lambda layer_uids: (
                self._delete_default_layers_from_dialog(file_path, layer_uids)
            ),
            update_show_fn=lambda layer_uid, show: (
                self._update_default_layer_show_from_dialog(file_path, layer_uid, show)
            ),
            update_all_show_fn=lambda show: (
                self._update_all_default_layers_show_from_dialog(file_path, show)
            ),
            update_name_fn=lambda layer_uid, name: (
                self._update_default_layer_name_from_dialog(file_path, layer_uid, name)
            ),
            move_fn=lambda layer_uid, neighbor_uid: (
                self._move_default_layer_from_dialog(file_path, layer_uid, neighbor_uid)
            ),
            insert_async_fn=(
                (
                    lambda name, sequence, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_async(
                            file_path,
                            "New Default Layer",
                            lambda callback: (
                                self._project_write_service.queue_default_layer_insert(
                                    file_path,
                                    name,
                                    sequence,
                                    callback,
                                    edit_lease_handle=handle,
                                )
                            ),
                            lease_completed,
                            "default_layers",
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            delete_many_async_fn=(
                (
                    lambda uids, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_async(
                            file_path,
                            "Delete Default Layer",
                            lambda callback: (
                                self._project_write_service.queue_default_layers_delete(
                                    file_path,
                                    uids,
                                    callback,
                                    edit_lease_handle=handle,
                                )
                            ),
                            lease_completed,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            update_name_async_fn=(
                (
                    lambda uid, name, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_update_async(
                            file_path,
                            "rename",
                            {"layer_uid": uid, "name": name},
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            move_async_fn=(
                (
                    lambda uid, neighbor, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_update_async(
                            file_path,
                            "reorder",
                            {"layer_uid": uid, "neighbor_uid": neighbor},
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            update_show_async_fn=(
                (
                    lambda uid, show, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_update_async(
                            file_path,
                            "show",
                            {"layer_uid": uid, "show": show},
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            update_all_show_async_fn=(
                (
                    lambda show, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_default_layer_update_async(
                            file_path,
                            "show_all",
                            {"show": show},
                            lease_completed,
                            edit_lease_handle=handle,
                        ),
                        completed,
                    )
                )
                if uses_sql_queue
                else None
            ),
            has_license=True,
            mode=LayersDialogMode.DEFAULT_LAYERS,
            workspace_state_model=self._workspace_state_model,
        )
        if lease_session is not None:
            lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def _save_master_data_async(
        self,
        file_path: str,
        title: str,
        queue_fn,
        changes,
        completed,
        result_family: str,
        *,
        edit_lease_handle: Optional[EditLeaseHandle] = None,
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            completed(False, None)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if self._modal_mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                authoritative = result.authoritative_result
                maps = dict(authoritative.created_uid_maps) if authoritative else {}
                completed(True, dict(maps.get(result_family, ())))
                return
            self.present_queued_mutation_error(file_path, title, result)
            completed(False, None)

        try:
            if edit_lease_handle is None:
                queue_fn(file_path, changes, finish)
            else:
                queue_fn(
                    file_path,
                    changes,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, title, str(exc))
            return False
        return True

    def _save_default_layer_async(
        self,
        file_path: str,
        title: str,
        submit,
        completed,
        result_family: str = "",
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            completed(False, None)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if self._modal_mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                value = None
                if result_family and result.authoritative_result is not None:
                    mapping = dict(result.authoritative_result.created_uid_maps).get(
                        result_family, ()
                    )
                    value = dict(mapping).get("0")
                completed(True, value)
                return
            self.present_queued_mutation_error(file_path, title, result)
            completed(False, None)

        try:
            submit(finish)
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, title, str(exc))
            return False
        return True

    def _save_default_layer_update_async(
        self,
        file_path: str,
        operation: str,
        values: dict,
        completed,
        *,
        edit_lease_handle: Optional[EditLeaseHandle] = None,
    ) -> bool:
        return self._save_default_layer_async(
            file_path,
            "Default Layers",
            lambda callback: (
                self._project_write_service.queue_default_layer_update(
                    file_path, operation, values, callback
                )
                if edit_lease_handle is None
                else self._project_write_service.queue_default_layer_update(
                    file_path,
                    operation,
                    values,
                    callback,
                    edit_lease_handle=edit_lease_handle,
                )
            ),
            completed,
        )

    def _save_master_employees_result(self, file_path: str, changes):
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        result = self._project_write_service.save_employees_result(file_path, changes)
        if result.refresh_failed:
            show_warning(
                self.main_window,
                "Refresh Error",
                "The employee changes were saved, but the employee list could not be "
                "refreshed. Reopen the database to see the latest employees.",
            )
        return result

    def _save_master_job_statuses(self, file_path: str, changes) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.save_job_statuses(file_path, changes)

    def _save_master_pay_classes(self, file_path: str, changes) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.save_pay_classes(file_path, changes)

    def _save_master_condition_types(self, file_path: str, changes) -> Optional[dict]:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return None
        result = self._project_write_service.save_condition_types_result(
            file_path, changes
        )
        if not result.write_success:
            return None
        if result.refresh_failed:
            show_warning(
                self.main_window,
                "Refresh Error",
                "The condition type changes were saved, but the condition type list "
                "could not be refreshed. Reopen the database to see the latest "
                "condition types.",
            )
        return result.value

    def _save_master_condition_types_async(
        self,
        file_path: str,
        changes,
        completed,
        *,
        edit_lease_handle: Optional[EditLeaseHandle] = None,
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            completed(False, None)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if self._modal_mutation_result_remains_pending(result):
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                authoritative = result.authoritative_result
                maps = dict(authoritative.created_uid_maps) if authoritative else {}
                completed(True, dict(maps.get("condition_types", ())))
                return
            self.present_queued_mutation_error(
                file_path,
                "Condition Types",
                result,
            )
            completed(False, None)

        try:
            if edit_lease_handle is None:
                self._project_write_service.queue_condition_types_save(
                    file_path, changes, finish
                )
            else:
                self._project_write_service.queue_condition_types_save(
                    file_path,
                    changes,
                    finish,
                    edit_lease_handle=edit_lease_handle,
                )
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, "Condition Types", str(exc))
            return False
        return True

    @staticmethod
    def _modal_mutation_result_remains_pending(
        result: QueuedMutationResult,
    ) -> bool:
        return result.outcome_status in {
            MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
            MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
        }

    def _delete_master_condition_types(self, file_path: str, uids: list):
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return None
        result = self._project_write_service.delete_condition_types_result(
            file_path, uids
        )
        if result.refresh_failed:
            show_warning(
                self.main_window,
                "Refresh Error",
                "The condition type changes were saved, but the condition type list "
                "could not be refreshed. Reopen the database to see the latest "
                "condition types.",
            )
        return result

    def _insert_default_layer_from_dialog(
        self, file_path: str, name: str, after_sequence: int
    ) -> Optional[str]:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return None
        result = self._project_write_service.insert_default_layer_result(
            file_path, name, after_sequence
        )
        if not result.write_success or result.value is None:
            return None
        if result.refresh_failed:
            show_warning(
                self.main_window,
                "Refresh Error",
                "The default layer was saved, but the default layer list could not "
                "be refreshed. Reopen the database to see the latest default layers.",
            )
        return str(result.value)

    def _delete_default_layers_from_dialog(self, file_path: str, layer_uids: list):
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return None
        return self._project_write_service.delete_default_layers(file_path, layer_uids)

    def _update_default_layer_show_from_dialog(
        self, file_path: str, layer_uid: str, show: bool
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.update_default_layer_show(
            file_path, layer_uid, show
        )

    def _update_all_default_layers_show_from_dialog(
        self, file_path: str, show: bool
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.update_all_default_layers_show(
            file_path, show
        )

    def _update_default_layer_name_from_dialog(
        self, file_path: str, layer_uid: str, name: str
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.update_default_layer_name(
            file_path, layer_uid, name
        )

    def _move_default_layer_from_dialog(
        self, file_path: str, layer_uid: str, neighbor_uid: str
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.swap_default_layer_sequence(
            file_path, layer_uid, neighbor_uid
        )

    def _resolve_master_data_file_path(self) -> Optional[str]:
        return self.main_window.get_selected_database_context_file_path()

    def _editable_master_data_file_path(self) -> Optional[str]:
        file_path = self._resolve_master_data_file_path()
        if not file_path:
            return None
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return None
        self.project_data.set_current_file(file_path)
        return file_path

    @property
    def placement(self) -> PlacementCoordinator:
        return self._placement

    def _is_condition_placeable(self, condition_uid: str) -> bool:
        condition = self.project_data.get_bid_conditions().get(condition_uid)
        return bool(condition and condition.layer_visible)

    def _reset_to_select_mode(self) -> None:
        self._placement.force_exit()
        self._set_plan_select_mode()
        self._toolbar.refresh()

    def _reconcile_active_placement(self) -> None:
        if self._placement.reconcile_authoritative_conditions():
            return
        self._set_plan_select_mode()
        self._toolbar.refresh()

    def _prepare_for_modal_mutation_error(self, database_id: str) -> None:
        if database_id != self.project_data.get_current_file_path():
            return
        self._reset_to_select_mode()
        if self._plan_view_handler is not None:
            self._plan_view_handler.prepare_for_modal_mutation_error()
        elif self.plan_view is not None:
            self.plan_view.prepare_for_modal_mutation_error()

    def present_queued_mutation_error(
        self,
        database_id: str,
        title: str,
        result: QueuedMutationResult,
        *,
        critical: bool = False,
    ) -> None:
        if self._is_cleaning_up:
            return
        if result.outcome_status == MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED:
            return
        self._prepare_for_modal_mutation_error(database_id)
        if result.outcome_status == MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN:
            show_warning(
                self.main_window,
                "SQL Synchronization",
                result.message
                or "The committed update requires authoritative SQL recovery.",
            )
            return
        message = result.message or f"The {title.lower()} could not be completed."
        if critical:
            show_critical(self.main_window, title, message)
        else:
            show_warning(self.main_window, title, message)

    def ensure_select_mode(self) -> None:
        selected_takeoff_condition_uid = (
            self.plan_view.selected_takeoff_condition_uid() if self.plan_view else None
        )
        if (
            self.plan_view
            and not self._placement.is_active
            and not self.plan_view.is_rotate_mode_active
            and not self.ui_state_manager.highlighted_condition_uids
            and not selected_takeoff_condition_uid
        ):
            self._set_plan_select_mode()

    def _on_ost_status_changed(self, active: bool = False) -> None:
        self.ensure_select_mode()
        if self.condition_summary_tab:
            self.condition_summary_tab.refresh_view()
        self._menu_state_signaler.request()

    def cleanup(self) -> None:
        if self._is_cleaning_up:
            return
        self._is_cleaning_up = True
        self.project_operations.cancel_navigation_load()
        if self._status_panel:
            self._status_panel.set_page_info("")
        self._sync_collaboration_status("", reset_mutation=True)
        self._invalidate_mesh_scene_request()
        if self._plan_view_handler is not None:
            self._plan_view_handler.invalidate_pending_takeoff_placements()
        if self._view_stack:
            try:
                self._view_stack.currentChanged.disconnect(self._on_view_stack_changed)
            except (TypeError, RuntimeError):
                pass
        if self._tab_widget:
            try:
                self._tab_widget.currentChanged.disconnect(self._on_tab_changed)
            except (TypeError, RuntimeError):
                pass
        if self._undo_service:
            self._undo_service.set_change_callback(None)
        for event_name, callback in self._subscriptions:
            self.event_bus.unsubscribe(event_name, callback)
        self._subscriptions.clear()
        for signaler in (
            self._plan_view_signaler,
            self._menu_state_signaler,
        ):
            if signaler:
                signaler.cleanup()
        if self._bid_data_cache:
            self._bid_data_cache.clear()
        self._bid_data_cache = None
        if self._mesh_window is not None:
            self._mesh_window.close()
            self._mesh_window = None
        self._mesh_window_action = None
        if self._placement:
            self._placement.cleanup()
        self._placement = None
        if self.opengl_viewer:
            self.opengl_viewer.cleanup()
        if self.takeoff_sidebar:
            self.takeoff_sidebar.cleanup()
        if self.plan_view:
            self.plan_view.cleanup()
        if self._sidebar:
            self._sidebar.cleanup()
        if self._viewer:
            self._viewer.cleanup()
        if self._toolbar:
            self._toolbar.cleanup()
        self._plan_view_signaler = None
        self._menu_state_signaler = None
        self._nav = None
        self._sidebar = None
        self._viewer = None
        self._toolbar = None
        self._undo_service = None
        self.main_window = None
        self.ui_state_manager = None
        self.ui_access_manager = None
        self.event_bus = None
        self.project_data = None
        self.project_operations = None
        self.visualization_service = None
        self._color_service = None
        self._icon_provider = None
        self._project_write_service = None
        self._project_read_service = None
        self.takeoff_sidebar = None
        self.conditions_sidebar = None
        self.condition_summary_tab = None
        self.opengl_viewer = None
        self.plan_view = None
        self._condition_handler = None
        self._deferred_persistence = None
        self._status_panel = None

    def capture_current_page_state_for_shutdown(self) -> None:
        self._save_current_page_view_state()

    def _on_file_opened(self, file_path: str = "") -> None:
        self._save_current_page_view_state()
        self._placement.force_exit()
        self.ui_state_manager.reset_selections()
        self._sync_undo_bid()
        self.main_window.project_view.set_selected_node_state(None)
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.ui_access_manager.refresh()
        self._viewer.clear_plan_view()
        self._clear_mesh_views_for_scene_update()
        self._set_takeoff_tab_visible(False)
        self._rebuild_ui_after_file_load()
        self._update_export_menu_state()
        self.main_window.set_database_window_title(file_path)

    def _on_database_refreshed(
        self,
        file_path: str = "",
        external_change: bool = False,
    ) -> None:
        if file_path:
            if external_change:
                self._deferred_persistence.cancel_for_file(file_path)
                if self._undo_service:
                    self._undo_service.clear()
            elif not self._flush_deferred_for_file(file_path):
                return
        if not self._nav.start_refresh(
            self.ui_state_manager,
            self._placement,
            selected_area_uid=self.ui_state_manager.selected_area_uid,
        ):
            return
        selected_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if selected_bid_ref is not None:
            selected_pages = list(self.ui_state_manager.selected_page_uids)
            self._clear_mesh_views_for_scene_update()
            self._mark_mesh_scene_dirty(selected_pages)
        try:
            self._do_file_refresh()
        finally:
            self._finish_refresh()
            self._flush_dirty_mesh_refresh_if_needed()

    def _on_database_capabilities_changed(self, file_path: str = "") -> None:
        if not file_path or file_path == self.ui_state_manager.selected_file_path:
            self.ui_access_manager.refresh()
            selected_file_path = self.ui_state_manager.selected_file_path
            if selected_file_path and not self.ui_access_manager.is_database_editable():
                self._deferred_persistence.cancel_for_file(selected_file_path)
            self._update_menu_state()
            self._refresh_mesh_window_access()

    def _is_summary_tab_active(self) -> bool:
        return bool(
            self._tab_widget
            and self._tab_widget.count() > TAB_INDEX_SUMMARY
            and self._tab_widget.currentIndex() == TAB_INDEX_SUMMARY
        )

    def _on_takeoffs_changed(
        self,
        page_uid: str = "",
        page_uids: Optional[List[str]] = None,
        takeoff_uids: list | None = None,
        condition_uids: list | None = None,
        update_shell: bool = True,
        update_plan: bool = True,
        update_mesh: bool = True,
    ) -> None:
        affected_page_uids = list(
            dict.fromkeys(str(uid) for uid in (page_uids or ()) if uid)
        )
        if not affected_page_uids and page_uid:
            affected_page_uids = [str(page_uid)]
        active_page_uid = self.ui_state_manager.active_page_uid
        for affected_page_uid in affected_page_uids:
            self._refresh_takeoff_dependent_page_controls(affected_page_uid)
        active_page_affected = not affected_page_uids or (
            active_page_uid in affected_page_uids
        )
        if update_plan and active_page_uid and active_page_affected:
            self._update_plan_view(
                active_page_uid,
                condition_uids=condition_uids,
                takeoff_uids=takeoff_uids,
            )
        elif update_plan and not active_page_uid:
            self._update_plan_view_for_active(
                condition_uids=condition_uids,
                takeoff_uids=takeoff_uids,
            )
        elif update_plan:
            self._sidebar.update_conditions_quantities(condition_uids=condition_uids)
        if update_mesh:
            selected_page_uids = self.project_data.get_selected_page_uids()
            self._request_or_defer_mesh_refresh(
                selected_page_uids,
                dirty_page_uids=affected_page_uids or None,
            )
        if self._is_summary_tab_active():
            self._load_condition_summary()
        if update_shell:
            self._update_export_menu_state()
            self._restore_project_tree_bid_selection_if_needed()

    def _on_pending_plan_mutations_changed(
        self,
        database_id: str,
        takeoff_uids: Optional[List[str]] = None,
        pending: bool = True,
    ) -> None:
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected is None or selected.file_path != database_id:
            return
        changed = {str(uid) for uid in (takeoff_uids or ()) if uid}
        for view in self._native_3d_views():
            existing = view.get_pending_mutation_uids()
            next_uids = (
                existing.union(changed) if pending else existing.difference(changed)
            )
            view.set_pending_mutation_uids(next_uids)

    def _on_remote_bid_content_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        families: Optional[List[str]] = None,
        resource_uids_by_family: Optional[Dict[str, List[str]]] = None,
        defer_plan_projection: bool = False,
        local_completion: bool = False,
    ) -> None:
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid):
            return
        changed_families = set(families or [])
        changed_uids = resource_uids_by_family or {}
        annotations_changed = (
            CollaborationResourceFamily.ANNOTATIONS.value in changed_families
        )
        layers_changed = CollaborationResourceFamily.LAYERS.value in changed_families
        pages_changed = CollaborationResourceFamily.PAGES.value in changed_families
        if layers_changed:
            self._deferred_persistence.invalidate_layer_visual_revisions(
                database_id,
                changed_uids.get(CollaborationResourceFamily.LAYERS.value) or None,
            )
        if pages_changed:
            self._deferred_persistence.invalidate_page_visual_revisions(
                database_id,
                changed_uids.get(CollaborationResourceFamily.PAGES.value) or None,
            )
        if self._undo_service and changed_families and not local_completion:
            self._undo_service.clear()
        if pages_changed and not local_completion:
            changed_page_uids = changed_uids.get(
                CollaborationResourceFamily.PAGES.value
            )
            self._deferred_persistence.cancel_pages(
                database_id,
                bid_uid,
                list(changed_page_uids) if changed_page_uids else None,
            )
        if CollaborationResourceFamily.TAKEOFFS.value in changed_families:
            if self._selected_takeoff_uids:
                self._sync_selection(
                    self._SOURCE_MODEL, list(self._selected_takeoff_uids)
                )
            self._on_takeoffs_changed(
                page_uid=self.ui_state_manager.active_page_uid,
                takeoff_uids=(
                    changed_uids.get(CollaborationResourceFamily.TAKEOFFS.value) or None
                ),
                update_shell=False,
                update_plan=not defer_plan_projection,
                update_mesh=not defer_plan_projection,
            )
        if annotations_changed:
            self._on_annotations_changed(
                page_uid=self.ui_state_manager.active_page_uid,
                annotation_uids=(
                    changed_uids.get(CollaborationResourceFamily.ANNOTATIONS.value)
                    or None
                ),
                update_shell=False,
                update_plan=(
                    not defer_plan_projection
                    and not layers_changed
                    and not pages_changed
                ),
            )
        if pages_changed:
            if self._pending_takeoff_page_uids is not None:
                valid_pages, active_page = self._resolve_takeoff_selection()
                self._clear_staged_takeoff_restore()
            else:
                valid_pages = [
                    uid
                    for uid in self.ui_state_manager.selected_page_uids
                    if self.project_data.get_page(uid)
                ]
                active_page = self.ui_state_manager.active_page_uid
                if active_page and not self.project_data.get_page(active_page):
                    ordered_pages = sorted(
                        self.project_data.get_all_pages(),
                        key=lambda page: page.sequence,
                    )
                    active_page = ordered_pages[0].uid if ordered_pages else None
            self.ui_state_manager.set_page_selection(valid_pages)
            self.ui_state_manager.active_page_uid = active_page
            self.project_data.select_pages(valid_pages)
            self._sidebar.load_takeoff_sidebar_from_memory(
                selected, self._bid_data_cache
            )
            self.takeoff_sidebar.restore_selection(valid_pages, active_page)
            if active_page:
                self._update_page_settings_bar(active_page)
                if not defer_plan_projection:
                    self._update_plan_view(active_page)
            else:
                self._viewer.clear_plan_view()
            if not defer_plan_projection:
                self._request_or_defer_mesh_refresh(valid_pages)
        if layers_changed and self._sidebar.bid_layers_sidebar:
            self._sidebar.bid_layers_sidebar.load_layers(
                self.project_data.get_bid_layer_snapshot(),
                used_uids=self.project_data.get_layer_uids_in_use(),
            )
            self._sidebar.refresh_conditions_from_memory()
        if layers_changed:
            self._reconcile_active_placement()
        if layers_changed and not pages_changed and not defer_plan_projection:
            self._update_plan_view_for_active()
        if (
            layers_changed
            and CollaborationResourceFamily.TAKEOFFS.value not in changed_families
            and not pages_changed
            and not defer_plan_projection
        ):
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        self._update_export_menu_state()
        self._restore_project_tree_bid_selection_if_needed()

    def _on_annotations_changed(
        self,
        page_uid: str = "",
        page_uids: Optional[List[str]] = None,
        annotation_uids: Optional[List[str]] = None,
        annotation_types: Optional[List[str]] = None,
        update_shell: bool = True,
        update_plan: bool = True,
    ) -> None:
        affected_page_uids = list(
            dict.fromkeys(str(uid) for uid in (page_uids or ()) if uid)
        )
        if not affected_page_uids and page_uid:
            affected_page_uids = [str(page_uid)]
        active_page_uid = self.ui_state_manager.active_page_uid
        if update_plan and (
            not affected_page_uids or active_page_uid in affected_page_uids
        ):
            self._update_plan_view_annotations(
                active_page_uid,
                annotation_uids=annotation_uids,
                annotation_types=annotation_types,
            )
        if update_shell:
            self._update_export_menu_state()
            self._restore_project_tree_bid_selection_if_needed()

    def _on_conditions_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        condition_uids: Optional[List[str]] = None,
        changed_fields: Optional[List[str]] = None,
        change_operations: Optional[List[str]] = None,
        defer_plan_projection: bool = False,
        invalidates_undo: bool = False,
    ) -> None:
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid):
            return
        operations = set(change_operations or ())
        self._reconcile_active_placement()
        if self._undo_service and invalidates_undo:
            self._undo_service.clear()
        valid_highlights = self._validate_condition_uids(
            self.ui_state_manager.highlighted_condition_uids
        )
        self.ui_state_manager.set_highlighted_conditions(valid_highlights)
        self._sidebar.refresh_conditions_from_memory()
        self._restore_sidebar_highlight(valid_highlights, reveal=False)
        if not defer_plan_projection and condition_changes_require_plan_refresh(
            changed_fields or (), operations
        ):
            self._update_plan_view_for_active(condition_uids=condition_uids)
        if not defer_plan_projection and condition_changes_require_mesh_refresh(
            changed_fields or (), operations
        ):
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        self._update_export_menu_state()

    def _on_remote_areas_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        area_uids: Optional[List[str]] = None,
        defer_plan_projection: bool = False,
    ) -> None:
        del area_uids
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid):
            return
        if self._undo_service:
            self._undo_service.clear()
        if self._page_settings_bar:
            selected_area_uid = self._page_settings_bar.get_selected_area_uid()
            self._page_settings_bar.load_bid_areas(
                selected,
                areas=self.project_data.get_bid_area_snapshot(),
                areas_with_takeoff=self.project_data.get_area_uids_with_takeoff(),
                selected_uid=selected_area_uid,
            )
            self._refresh_takeoff_dependent_page_controls(
                self.ui_state_manager.active_page_uid
            )
        if not defer_plan_projection:
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        if self._is_summary_tab_active():
            self._sidebar.load_condition_summary_from_memory()

    def _on_collaboration_state_changed(
        self,
        database_id: str = "",
        state: str = "",
        message: str = "",
    ) -> None:
        selected = self.ui_state_manager.selected_file_path or ""
        if (
            database_id == selected
            and state
            not in {
                SynchronizationState.HEALTHY.value,
                SynchronizationState.CATCHING_UP.value,
            }
            and self._plan_view_handler is not None
        ):
            self._plan_view_handler.hide_pending_takeoff_placement_previews()
        if database_id and state not in {
            SynchronizationState.HEALTHY.value,
            SynchronizationState.CATCHING_UP.value,
        }:
            self._deferred_persistence.cancel_for_file(database_id)
            if database_id == selected:
                self._placement.force_exit()
        if self._status_panel and database_id == selected:
            self._status_panel.set_collaboration_state(state, message)

    def _on_collaboration_mutation_state_changed(
        self,
        database_id: str = "",
        operation_id: str = "",
        mutation_type: str = "",
        state: str = "",
        message: str = "",
        pending_count: int = 0,
    ) -> None:
        del operation_id, mutation_type
        selected = self.ui_state_manager.selected_file_path or ""
        if self._status_panel and database_id == selected:
            collaboration_status = self._sql_collaboration.status(database_id)
            self._status_panel.set_collaboration_state(
                collaboration_status.state.value,
                collaboration_status.message,
            )
            self._status_panel.set_collaboration_mutation_state(
                state,
                pending_count,
                message,
            )

    def _on_edit_lease_lost(
        self,
        loss: EditLeaseLoss,
    ) -> None:
        if self._plan_view_handler is not None:
            self._plan_view_handler.on_edit_lease_lost(loss)

    def _on_presence_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        users: Optional[List] = None,
    ) -> None:
        if not self._status_panel:
            return
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected == BidRef(database_id, bid_uid):
            self._status_panel.set_collaboration_presence(users or [])

    def _sync_collaboration_status(
        self,
        database_id: str,
        *,
        reset_mutation: bool,
    ) -> Optional[CollaborationStatus]:
        if not self._status_panel:
            return None
        self._status_panel.set_collaboration_presence([])
        if reset_mutation:
            self._status_panel.set_collaboration_mutation_state("", 0)
        if not database_id:
            self._status_panel.set_collaboration_state("stopped")
            return None
        collaboration_status = self._sql_collaboration.status(database_id)
        self._status_panel.set_collaboration_state(
            collaboration_status.state.value,
            collaboration_status.message,
        )
        return collaboration_status

    def _on_full_reconciliation_required(
        self, database_id: str = "", reason: str = ""
    ) -> None:
        self._deferred_persistence.cancel_for_file(database_id)
        recovery_started = self._sql_collaboration.resume_controlled_recovery(
            database_id
        )
        if database_id != self.project_data.get_current_file_path():
            return
        if recovery_started:
            return
        self._prepare_for_modal_mutation_error(database_id)
        show_warning(
            self.main_window,
            "SQL Synchronization",
            reason or "The SQL database could not be reconciled safely.",
        )

    def _on_remote_hierarchy_changed(
        self,
        database_id: str = "",
        defer_plan_projection: bool = False,
    ) -> None:
        del defer_plan_projection
        active_bid = self.project_data.get_current_bid_ref()
        selected_bid = self.ui_state_manager.get_selected_bid_ref()
        selected_database_id = self.ui_state_manager.selected_file_path
        self._do_file_refresh()
        if self.project_data.get_current_file_path() and normalize_path(
            self.project_data.get_current_file_path()
        ) == normalize_path(database_id):
            self.refresh_conditions_ui()
        if active_bid is None:
            if selected_database_id and normalize_path(
                selected_database_id
            ) != normalize_path(database_id):
                return
            restored_bid = selected_bid
            selected_node = self.main_window.project_view.get_selected_node_state()
            if (
                restored_bid is None
                and selected_node
                and selected_node.get("kind") == "bid"
                and normalize_path(selected_node.get("file_path") or "")
                == normalize_path(database_id)
                and selected_node.get("bid_uid")
            ):
                restored_bid = BidRef(
                    database_id,
                    str(selected_node["bid_uid"]),
                )
            if (
                restored_bid is not None
                and normalize_path(restored_bid.file_path)
                == normalize_path(database_id)
                and self.project_data.get_bid(restored_bid) is not None
            ):
                self.handle_bid_selection(restored_bid, force=True)
                return
            if (
                not self.ui_state_manager.selected_file_path
                and self.project_data.get_current_file_path() == database_id
            ):
                self.main_window.project_view.restore_file_selection(database_id)
                self.main_window.project_view.notify_current_selection()
            return
        if active_bid.file_path != database_id:
            return
        if self.project_data.get_bid(active_bid) is not None:
            self.main_window.project_view.restore_bid_selection(active_bid)
            return
        self._on_file_selected(database_id, is_database_root=True)
        self.main_window.project_view.restore_file_selection(database_id)

    def _on_remote_plan_projection_requested(
        self,
        database_id: str,
        bid_uid: str,
        runtime_generation: int,
        families: tuple[str, ...],
        condition_uids: tuple[str, ...],
        condition_changed_fields: tuple[str, ...] | None,
        condition_change_operations: tuple[str, ...],
        areas_changed: bool,
        resource_uids_by_family: dict[str, tuple[str, ...]],
        barrier: RemoteProjectionBarrier,
    ) -> None:
        selected_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        requested_bid_ref = BidRef(database_id, bid_uid)
        mesh_families = {
            CollaborationResourceFamily.LAYERS.value,
            CollaborationResourceFamily.PAGES.value,
            CollaborationResourceFamily.TAKEOFFS.value,
        }
        condition_mesh_refresh = (
            condition_changed_fields is not None
            and condition_changes_require_mesh_refresh(
                condition_changed_fields, condition_change_operations
            )
        )
        if (
            not self._is_cleaning_up
            and selected_bid_ref == requested_bid_ref
            and (
                areas_changed
                or condition_mesh_refresh
                or bool(mesh_families.intersection(families))
            )
        ):
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        plan_families = {
            CollaborationResourceFamily.ANNOTATIONS.value,
            CollaborationResourceFamily.LAYERS.value,
            CollaborationResourceFamily.PAGES.value,
            CollaborationResourceFamily.TAKEOFFS.value,
        }
        condition_plan_refresh = (
            condition_changed_fields is not None
            and condition_changes_require_plan_refresh(
                condition_changed_fields, condition_change_operations
            )
        )
        plan_projection_required = (
            areas_changed
            or condition_plan_refresh
            or bool(plan_families.intersection(families))
        )
        if (
            self._is_cleaning_up
            or selected_bid_ref != requested_bid_ref
            or not self.ui_state_manager.active_page_uid
            or self.plan_view is None
            or not plan_projection_required
        ):
            return
        token = barrier.register("main-plan")
        try:
            accepted = self._viewer.request_remote_plan_update(
                database_id=database_id,
                runtime_generation=runtime_generation,
                bid_uid=bid_uid,
                resource_uids_by_family=resource_uids_by_family,
                barrier=barrier,
                completion=lambda success: self._complete_remote_plan_projection(
                    token,
                    success,
                    condition_uids,
                    CollaborationResourceFamily.TAKEOFFS.value in families,
                ),
            )
        except Exception:
            token.complete(False)
            raise
        if not accepted:
            token.complete(False)

    def _complete_remote_plan_projection(
        self,
        token: RemoteProjectionToken,
        success: bool,
        condition_uids: tuple[str, ...],
        takeoffs_changed: bool,
    ) -> None:
        if success and not self._is_cleaning_up:
            self._apply_pending_hotlink_named_view_focus(require_stable=True)
            if condition_uids:
                self._sidebar.update_conditions_quantities(
                    condition_uids=list(condition_uids)
                )
            elif takeoffs_changed:
                self._sidebar.update_conditions_quantities()
        token.complete(success)

    def _on_synchronization_conflict(
        self,
        database_id: str = "",
        resource_type: str = "",
        resource_id: str = "",
        bid_uid: str = "",
        message: str = "",
        blocks_database: bool = True,
        draft_id: str = "",
        allowed_actions: Optional[List[str]] = None,
    ) -> None:
        if blocks_database:
            self._sql_collaboration.enter_conflict(database_id, message)
        else:
            self._sql_collaboration.enter_resource_conflict(
                database_id,
                ResourceRef(
                    resource_type,
                    resource_id,
                    int(bid_uid) if bid_uid else None,
                ),
                message,
            )
        actions = tuple(
            ConflictResolutionAction(action) for action in (allowed_actions or ())
        )
        if not actions:
            actions = (
                ConflictResolutionAction.RELOAD,
                ConflictResolutionAction.CANCEL_READ_ONLY,
            )
        self._prepare_for_modal_mutation_error(database_id)
        dialog = SynchronizationConflictDialog(
            self._icon_provider,
            message
            or f"{resource_type} {resource_id} changed in another session. "
            "Reload the database before saving again.",
            actions,
            self.main_window,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
            action = dialog.selected_action()
        finally:
            dialog.deleteLater()
        if action in {
            ConflictResolutionAction.RELOAD,
            ConflictResolutionAction.DISCARD_DRAFT,
        }:
            if draft_id:
                self._sql_collaboration.discard_local_draft(database_id, draft_id)
            self._on_full_reconciliation_required(database_id, message)

    def _restore_project_tree_bid_selection_if_needed(self) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        selected_node = self.main_window.project_view.get_selected_node_state()
        if (
            selected_node
            and selected_node.get("kind") == "bid"
            and selected_node.get("bid_uid") == bid_ref.bid_uid
            and normalize_path(selected_node.get("file_path") or "")
            == normalize_path(bid_ref.file_path)
        ):
            return
        self.main_window.project_view.restore_bid_selection(bid_ref)

    def _refresh_takeoff_dependent_page_controls(self, page_uid: str) -> None:
        has_takeoffs = self.project_data.has_takeoffs_for_pages([page_uid])
        if self.takeoff_sidebar:
            self.takeoff_sidebar.set_page_has_takeoffs(page_uid, has_takeoffs)
        if not self._page_settings_bar:
            return
        bid_areas = self.project_data.get_area_uids_with_takeoff()
        if page_uid == self.ui_state_manager.active_page_uid:
            page_areas = self.project_data.get_area_uids_with_takeoff_for_page(page_uid)
            self._page_settings_bar.update_area_usage(bid_areas, page_areas)
        else:
            self._page_settings_bar.update_area_usage(bid_areas)

    def _do_file_refresh(self) -> None:
        hierarchy = self.project_data.get_hierarchy()
        loaded_files = build_loaded_files(hierarchy)
        self._cache_bid_data(loaded_files)
        self.main_window.project_view.build_complete_structure(loaded_files)

    def refresh_hierarchy_projection(self) -> None:
        if not self._is_cleaning_up:
            self._do_file_refresh()

    def _finish_refresh(self) -> None:
        snap = self._nav.refresh_snapshot
        if not snap:
            self._nav.finish_refresh(NavState.FILE_LOADED_NO_BID)
            self.main_window.refresh_window_title()
            return
        has_file = bool(self.project_data.get_current_file_path())
        if snap.bid_ref:
            if not self.project_data.get_bid(snap.bid_ref):
                self._reset_takeoff_workspace_state()
                self.ui_state_manager.set_bid_selection(None)
                self._sync_undo_bid()
                self.project_data.deselect_pages()
                self._clear_mesh_views_for_scene_update()
                self._discard_mesh_camera_states(bid_ref=snap.bid_ref)
                self.main_window.project_view.restore_file_selection(
                    snap.selected_file_path or snap.bid_ref.file_path
                )
                self._set_takeoff_tab_visible(False)
                self._nav.finish_refresh(
                    NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
                )
                self.ui_access_manager.refresh()
                self._update_menu_state()
                self.main_window.set_database_window_title(
                    snap.selected_file_path or snap.bid_ref.file_path
                )
                return
            self.main_window.project_view.restore_bid_selection(snap.bid_ref)
            if self.project_data.get_current_bid_ref() != snap.bid_ref:
                self._nav.finish_refresh(
                    NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
                )
                self.handle_bid_selection(snap.bid_ref, force=True)
                return
            self._resolve_bid_lock_state(snap.bid_ref)
            self._reset_takeoff_workspace_state(clear_sidebars=False)
            valid_highlighted = self._validate_condition_uids(
                snap.highlighted_condition_uids
            )
            self.ui_state_manager.set_highlighted_conditions(valid_highlighted)
            can_restore_placement = bool(
                snap.place_condition_uid
                and snap.place_condition_uid in self.project_data.get_bid_conditions()
                and self._is_condition_placeable(snap.place_condition_uid)
            )
            if snap.place_condition_uid and not can_restore_placement:
                self._reset_to_select_mode()
            self._stage_takeoff_restore(
                page_uids=snap.page_uids,
                active_page_uid=snap.active_page_uid,
                selected_area_uid=snap.selected_area_uid,
                place_condition_uid=(
                    snap.place_condition_uid if can_restore_placement else None
                ),
                place_condition_uids=(
                    snap.place_condition_uids if can_restore_placement else []
                ),
            )
            base_target = self._nav.compute_state_for(
                has_file=has_file,
                bid_ref=snap.bid_ref,
                active_page_uid=snap.active_page_uid,
            )
            self._nav.finish_refresh(base_target)
            if (
                self._tab_widget
                and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF
            ):
                self._activate_takeoff_workspace()
            elif (
                self._tab_widget
                and self._tab_widget.currentIndex() == TAB_INDEX_SUMMARY
            ):
                self._load_condition_summary()
        elif snap.project_uid:
            self._reset_takeoff_workspace_state()
            restored_project_file_path = (
                self.project_data.get_hierarchy().find_file_path_for_project(
                    snap.project_uid,
                    snap.selected_file_path,
                )
            )
            if restored_project_file_path:
                self.main_window.project_view.restore_project_selection(
                    snap.project_uid,
                    snap.selected_file_path or restored_project_file_path,
                )
            else:
                selected_file_path = (
                    snap.selected_file_path or self.project_data.get_current_file_path()
                )
                self.ui_state_manager.reset_selections()
                self.ui_state_manager.set_database_selected(
                    bool(selected_file_path), selected_file_path
                )
                if selected_file_path:
                    self.main_window.project_view.restore_file_selection(
                        selected_file_path
                    )
            self._set_takeoff_tab_visible(False)
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        elif snap.database_selected and snap.selected_file_path:
            self._reset_takeoff_workspace_state()
            self.main_window.project_view.restore_file_selection(
                snap.selected_file_path
            )
            self._set_takeoff_tab_visible(False)
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        else:
            self._reset_takeoff_workspace_state()
            self._set_takeoff_tab_visible(False)
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        self.ui_access_manager.refresh()
        self._update_menu_state()
        self.main_window.refresh_window_title()

    def _validate_condition_uids(self, uids: set) -> set:
        if not uids:
            return set()
        conditions = self.project_data.get_bid_conditions()
        return {uid for uid in uids if uid in conditions}

    def _on_file_unloaded(
        self, file_path: str = "", active_context_removed: bool = True
    ) -> None:
        self.project_operations.cancel_navigation_load(file_path)
        removed_path = file_path or ""
        selected_path = self.ui_state_manager.selected_file_path
        if removed_path and selected_path:
            active_context_removed = active_context_removed or (
                normalize_path(removed_path) == normalize_path(selected_path)
            )
        if not active_context_removed:
            self._discard_mesh_camera_states(file_path=removed_path)
            self._refresh_project_tree_after_file_unload()
            self.ui_access_manager.refresh()
            self._update_menu_state()
            return
        self._placement.force_exit()
        self.ui_state_manager.reset_selections()
        self.ui_state_manager.set_database_selected(False)
        self._sync_undo_bid()
        self.ui_access_manager.refresh()
        self.project_data.clear_page_selection()
        self._reset_takeoff_workspace_state()
        self._viewer.clear_plan_view()
        self._clear_mesh_views_for_scene_update()
        self._discard_mesh_camera_states(file_path=removed_path)
        self._set_takeoff_tab_visible(False)
        self._refresh_project_tree_after_file_unload()
        self._update_export_menu_state()
        self._sync_page_info_status()
        self._sync_collaboration_status("", reset_mutation=True)
        self.main_window.refresh_window_title()

    def _refresh_project_tree_after_file_unload(self) -> None:
        has_files = bool(self.project_data.get_current_file_path())
        if has_files:
            hierarchy = self.project_data.get_hierarchy()
            loaded_files = build_loaded_files(hierarchy)
            self._cache_bid_data(loaded_files)
            self.main_window.project_view.build_complete_structure(loaded_files)
            self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        else:
            self.main_window.project_view.reset()
            self._sync_monitoring_state()
            self._nav.transition_to(NavState.NO_FILE)

    def _on_file_selected(
        self,
        file_path: str | None = None,
        project_uid: str | None = None,
        is_database_root: bool = False,
    ) -> None:
        self.project_operations.cancel_navigation_load()
        self._save_current_page_view_state()
        self._placement.force_exit()
        self.ui_state_manager.reset_selections()
        self.ui_state_manager.set_database_selected(is_database_root, file_path)
        self.ui_state_manager.set_project_uid(project_uid)
        self.main_window.refresh_window_title()
        self.project_data.clear_bid()
        self._sync_undo_bid()
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.ui_access_manager.refresh()
        self.project_data.deselect_pages()
        self._reset_takeoff_workspace_state()
        self._set_takeoff_tab_visible(False)
        self._viewer.clear_plan_view()
        self._clear_mesh_views_for_scene_update()
        self._update_export_menu_state()
        self._sync_page_info_status()
        collaboration_status = self._sync_collaboration_status(
            file_path or "",
            reset_mutation=True,
        )
        if collaboration_status is not None:
            if (
                collaboration_status.state
                == SynchronizationState.RECONCILIATION_REQUIRED
            ):
                self._on_full_reconciliation_required(
                    file_path,
                    collaboration_status.message,
                )

    def _on_app_config_updated(self, setting: str = "", value=None) -> None:
        _ = setting
        self.ui_state_manager.sync_from_config()
        needs_condition_display_refresh = (
            self._app_config_presentation.apply_updated_options(
                self.main_window,
                self.main_window._config_model,
                value,
            )
        )
        self.main_window.menu_controller.update_menu_states()
        if needs_condition_display_refresh:
            self._refresh_condition_display_after_app_config_change()

    def _refresh_condition_display_after_app_config_change(self) -> None:
        prev_highlighted = set(self.ui_state_manager.highlighted_condition_uids)
        self._sidebar.refresh_conditions_from_memory()
        if prev_highlighted and self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(prev_highlighted)
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            selected_pages = self.project_data.get_selected_page_uids()
            self._request_or_defer_mesh_refresh(selected_pages)
        if self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view_for_active()
            self.main_window.refresh_detached_plan_views()

    def _on_license_status_changed(self, has_license: bool) -> None:
        del has_license
        self._viewer.update_license_plan_state()
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        else:
            self._clear_mesh_views_for_scene_update()
        self.ensure_select_mode()

    def _on_native_scene_updated(
        self,
        geometries: List[MeshGeometry],
        scene_identity: MeshSceneIdentity,
        scene_failed: bool,
    ) -> None:
        if self._is_cleaning_up or self._nav.is_refreshing:
            return
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._clear_mesh_views_for_scene_update()
            return
        if scene_identity.generation <= 0:
            logger.warning("Discarding native scene without a complete identity")
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        selected_pages = normalize_scene_page_uids(
            self.project_data.get_selected_page_uids()
        )
        if (
            scene_identity.bid_ref != bid_ref
            or scene_identity.page_uids != selected_pages
        ):
            return
        cached_identity = (
            self._last_mesh_scene.scene_identity
            if self._last_mesh_scene is not None
            else None
        )
        if (
            isinstance(cached_identity, MeshSceneIdentity)
            and cached_identity.bid_ref == scene_identity.bid_ref
            and cached_identity.page_uids == scene_identity.page_uids
            and cached_identity.generation >= scene_identity.generation
        ):
            return
        if scene_failed:
            cached_scene_matches = bool(
                isinstance(cached_identity, MeshSceneIdentity)
                and cached_identity.bid_ref == scene_identity.bid_ref
                and cached_identity.page_uids == scene_identity.page_uids
            )
            if not cached_scene_matches:
                self._clear_mesh_replay_buffer()
            self._pending_dirty_mesh_refresh = False
            self._mark_mesh_scene_dirty(list(scene_identity.page_uids))
            for surface, is_live in (
                (self.opengl_viewer, self._is_embedded_3d_active()),
                (self._mesh_window, self._is_detached_mesh_visible()),
            ):
                if surface is not None and is_live:
                    surface.apply_scene_failure(scene_identity)
            return
        (
            vertices,
            normals,
            indices,
            colors,
            condition_uids,
            takeoff_uids,
        ) = _mesh_geometries_to_render_buffers(geometries)
        page_floor_elevations = MappingProxyType(
            resolve_page_floor_elevations(
                (geometry.page_uid, geometry.vertices[2::3]) for geometry in geometries
            )
        )
        publication = _MeshScenePublication(
            vertices=vertices,
            normals=normals,
            indices=indices,
            colors=colors,
            scene_identity=scene_identity,
            page_floor_elevations=page_floor_elevations,
            condition_uids=condition_uids,
            takeoff_uids=takeoff_uids,
        )
        self._last_mesh_scene = publication
        if self._pending_dirty_mesh_refresh:
            self._clear_mesh_dirty_state()
        live_embedded = self._is_embedded_3d_active()
        live_detached = self._is_detached_mesh_visible()
        live_surfaces = tuple(
            surface
            for surface, is_live in (
                (self.opengl_viewer, live_embedded),
                (self._mesh_window, live_detached),
            )
            if surface is not None and is_live
        )
        for surface in live_surfaces:
            publication.apply_to(surface)
        if selected_pages and live_surfaces:
            self._plan_view_signaler.request()

    def handle_bid_selection(
        self, bid_ref: Optional[BidRef], force: bool = False
    ) -> None:
        prev_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if (
            bid_ref
            and prev_bid_ref
            and bid_ref == prev_bid_ref
            and not force
            and not self.project_operations.navigation_load_in_progress()
        ):
            return
        self._save_current_page_view_state()
        if not bid_ref:
            self.project_operations.cancel_navigation_load()
            if prev_bid_ref:
                self._sql_collaboration.update_presence(
                    prev_bid_ref.file_path, None, None
                )
            if self._plan_view_handler is not None:
                self._plan_view_handler.hide_pending_takeoff_placement_previews()
            self._placement.force_exit()
            self.ui_state_manager.set_bid_selection(None)
            self.ui_state_manager.set_database_selected(False)
            self.ui_state_manager.set_file_path(None)
            self.project_data.clear_bid()
            self._sync_undo_bid()
            self._nav.transition_to(
                self._nav.compute_state_for(
                    has_file=bool(self.project_data.get_current_file_path()),
                    bid_ref=None,
                    active_page_uid=None,
                )
            )
            self.ui_access_manager.refresh()
            self.project_data.deselect_pages()
            self._reset_takeoff_workspace_state()
            self._viewer.clear_plan_view()
            self._clear_mesh_views_for_scene_update()
            self._set_takeoff_tab_visible(False)
            self._update_export_menu_state()
            self._sync_page_info_status()
            self._sync_collaboration_status("", reset_mutation=True)
            self.main_window.refresh_window_title()
            return
        prev_current_file_path = self.project_data.get_current_file_path()
        has_loaded_file = bool(
            prev_current_file_path or self.project_data.get_bid(bid_ref)
        )
        if not self._nav.begin_bid_load(has_loaded_file):
            self._sync_page_info_status()
            return
        try:
            self.project_operations.request_load_bid(
                bid_ref,
                lambda success, message: self._complete_bid_navigation_load(
                    bid_ref,
                    prev_bid_ref,
                    prev_current_file_path,
                    success,
                    message,
                ),
            )
            self._sync_page_info_status()
        except DatabaseCatalogError as exc:
            logger.warning("Failed to start the selected SQL bid load", exc_info=True)
            self._complete_bid_navigation_load(
                bid_ref,
                prev_bid_ref,
                prev_current_file_path,
                False,
                str(exc),
            )
        except Exception as exc:
            logger.exception("Failed to start the selected bid load")
            self._complete_bid_navigation_load(
                bid_ref,
                prev_bid_ref,
                prev_current_file_path,
                False,
                str(exc) or exc.__class__.__name__,
            )

    def _complete_bid_navigation_load(
        self,
        bid_ref: BidRef,
        prev_bid_ref: Optional[BidRef],
        prev_current_file_path: Optional[str],
        load_success: bool,
        load_error: str,
    ) -> None:
        if self._is_cleaning_up:
            return
        if not load_success:
            if prev_current_file_path:
                self.project_data.set_current_file(prev_current_file_path)
            elif prev_bid_ref:
                self.project_data.set_current_file(prev_bid_ref.file_path)
            self.ui_access_manager.refresh()
            self._update_menu_state()
            self._restore_project_tree_bid_selection_if_needed()
            if load_error:
                show_warning(self.main_window, "Open SQL Bid", load_error)
            self._sync_page_info_status()
            return
        if prev_bid_ref and bid_ref.file_path != prev_bid_ref.file_path:
            self._sql_collaboration.update_presence(prev_bid_ref.file_path, None, None)
        if self._plan_view_handler is not None:
            self._plan_view_handler.hide_pending_takeoff_placement_previews()
        self._placement.force_exit()
        self.ensure_select_mode()
        self.ui_state_manager.set_bid_selection(bid_ref)
        self._sync_collaboration_status(
            bid_ref.file_path,
            reset_mutation=bool(
                prev_bid_ref and prev_bid_ref.file_path != bid_ref.file_path
            ),
        )
        self._sql_collaboration.update_presence(
            bid_ref.file_path, bid_ref.bid_uid, None
        )
        self._sync_undo_bid()
        self.project_data.deselect_pages()
        self.ui_state_manager.set_page_selection([])
        self._viewer.clear_plan_view()
        self._begin_mesh_views_for_bid_load(bid_ref)
        self._resolve_bid_lock_state(bid_ref)
        self._reset_takeoff_workspace_state()
        self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        self.ui_access_manager.refresh()
        self._update_export_menu_state()
        self.main_window.refresh_window_title()
        self._set_takeoff_tab_visible(True)
        if self._tab_widget and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            self._activate_takeoff_workspace()
        self._sync_page_info_status()

    def handle_page_selection(self, page_uids: List[str]) -> None:
        if self._nav.is_refreshing:
            return
        if not self.ui_state_manager.get_selected_bid_ref():
            if self.ui_state_manager.selected_page_uids:
                self._update_page_selection([])
            return
        self._update_page_selection(page_uids)

    def handle_active_page_changed(self, active_uid: Optional[str]) -> None:
        if self._nav.is_refreshing:
            return
        self._save_current_page_view_state(selected_page_override=active_uid)
        self.ui_state_manager.active_page_uid = active_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        self._sync_navigation_for_active_page(bid_ref, active_uid)
        if bid_ref:
            self._sql_collaboration.update_presence(
                bid_ref.file_path, bid_ref.bid_uid, active_uid
            )
        if active_uid:
            self._update_page_settings_bar(active_uid)
            self._sync_overlay_display_mode(active_uid)
            self._update_native_page_textures()
        if active_uid and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(active_uid)
        else:
            self._viewer.clear_plan_view()
            self._sidebar.update_conditions_quantities()
        if (
            self._placement.is_active
            and self.plan_view is not None
            and self.plan_view.cursor_mode != CURSOR_MODE_PLACE
        ):
            logger.warning(
                "Resetting stale placement state after page change because plan "
                "view cursor is %r",
                self.plan_view.cursor_mode,
            )
            self._placement.force_exit()
        self._sync_page_info_status()
        self._update_export_menu_state()

    def _sync_navigation_for_active_page(
        self, bid_ref: Optional[BidRef], active_page_uid: Optional[str]
    ) -> None:
        if not bid_ref:
            return
        if not active_page_uid:
            if self._placement.is_active:
                self._placement.force_exit()
            if self._nav.current_state != NavState.BID_ACTIVE_NO_PAGES:
                self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
            return
        if self._nav.current_state == NavState.PLACE_MODE:
            return
        if self._nav.current_state == NavState.FILE_LOADED_NO_BID:
            self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        if self._nav.current_state != NavState.BID_ACTIVE_PAGES_SELECTED:
            self._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)

    def _sync_page_info_status(self) -> None:
        if not self._status_panel:
            return
        if self.project_operations.navigation_load_in_progress():
            self._status_panel.set_page_info(_BID_PAGES_LOADING_STATUS)
            return
        if not self._tab_widget or self._tab_widget.currentIndex() not in (
            TAB_INDEX_TAKEOFF,
            TAB_INDEX_SUMMARY,
        ):
            self._status_panel.set_page_info("")
            return
        selected = self.ui_state_manager.selected_page_uids
        if not selected:
            self._status_panel.set_page_info("")
            return
        on_3d = self._view_stack is not None and self._view_stack.currentIndex() == 0
        if on_3d:
            names = []
            for uid in selected:
                page = self.project_data.get_page(uid)
                names.append(page.name if page else uid)
            self._status_panel.set_page_info(", ".join(names))
            return
        uid = self.ui_state_manager.active_page_uid or selected[0]
        page = self.project_data.get_page(uid)
        name = page.name if page else uid
        self._status_panel.set_page_info(name)

    def sync_after_startup_load(self) -> None:
        hierarchy = self.project_data.get_hierarchy()
        loaded_files = build_loaded_files(hierarchy)
        self._cache_bid_data(loaded_files)
        self.main_window.project_view.build_complete_structure(loaded_files)
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.main_window.project_view.notify_current_selection()

    def _rebuild_ui_after_file_load(self) -> None:
        hierarchy = self.project_data.get_hierarchy()
        loaded_files = build_loaded_files(hierarchy)
        self._cache_bid_data(loaded_files)
        self._reset_takeoff_workspace_state()
        self.main_window.project_view.build_complete_structure(loaded_files)

    def _update_page_settings_bar(self, page_uid: str) -> None:
        if not self._page_settings_bar or not page_uid:
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        selected_area = self.project_data.get_page_area_selections().get(page_uid)
        areas_for_page = self.project_data.get_area_uids_with_takeoff_for_page(page_uid)
        self._page_settings_bar.load_page(
            page_uid,
            page.scale_factor1,
            page.scale_factor2,
            selected_area,
            areas_with_takeoff=areas_for_page,
        )
        self.ui_state_manager.selected_area_uid = (
            self._page_settings_bar.get_selected_area_uid() or ""
        )

    def _update_page_selection(self, page_uids: List[str]) -> None:
        previous = list(self.ui_state_manager.selected_page_uids)
        selected = self.project_data.select_pages(page_uids)
        self.ui_state_manager.set_page_selection(selected)
        selection_changed = normalize_scene_page_uids(
            selected
        ) != normalize_scene_page_uids(previous)
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            if selection_changed:
                self._request_or_defer_mesh_refresh(selected)
            elif self._mesh_scene_dirty:
                self._flush_dirty_mesh_refresh_if_needed()
        self._sidebar.update_conditions_quantities()
        self._update_export_menu_state()
        self._sync_page_info_status()

    def _cache_bid_data(self, loaded_files: List[LoadedFile]) -> None:
        if self._bid_data_cache:
            self._bid_data_cache.clear()
        cache: Dict[BidRef, Bid] = {}
        for loaded_file in loaded_files:
            file_path = loaded_file.file_path
            for project in loaded_file.projects:
                for bid in project.bids:
                    ref = BidRef(file_path=file_path, bid_uid=bid.uid)
                    cache[ref] = bid
            for bid in loaded_file.orphan_bids:
                ref = BidRef(file_path=file_path, bid_uid=bid.uid)
                cache[ref] = bid
        self._bid_data_cache = cache
        self._sync_monitoring_state()

    def _sync_undo_bid(self) -> None:
        if not self._undo_service:
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        self._undo_service.set_active_bid(bid_ref)

    def _sync_monitoring_state(self) -> None:
        self.visualization_service.start_database_monitoring()

    def _save_current_page_view_state(
        self, selected_page_override: Optional[str] = None
    ) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        active_page_uid = self.ui_state_manager.active_page_uid
        page_uid = self.plan_view.current_page_uid if self.plan_view else None
        can_persist = self.ui_access_manager.is_allowed(
            Feature.EDIT_PAGE_SETTINGS
        ) or self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        if page_uid and self.plan_view.is_view_state_stable:
            zoom_fac, cx, cy = self.plan_view.get_view_state()
            if zoom_fac > 0:
                page = self.project_data.get_page(page_uid)
                if page:
                    page.zoom_fac = zoom_fac
                    page.current_x = cx
                    page.current_y = cy
                if can_persist:
                    self._deferred_persistence.schedule_page_view_state(
                        bid_ref.file_path,
                        bid_ref.bid_uid,
                        page_uid,
                        zoom_fac,
                        cx,
                        cy,
                    )
        if not can_persist:
            return
        page_to_save = selected_page_override or page_uid or active_page_uid
        if page_to_save:
            if not self.project_data.get_page(page_to_save):
                self._deferred_persistence.cancel_bid_selected_pages(
                    bid_ref.file_path, [bid_ref.bid_uid]
                )
                return
            self._deferred_persistence.schedule_bid_selected_page(
                bid_ref.file_path, bid_ref.bid_uid, page_to_save
            )

    def _flush_deferred_for_file(self, file_path: Optional[str]) -> bool:
        if not file_path:
            return True
        return bool(self._deferred_persistence.flush_for_file(file_path))

    def flush_deferred_for_file(self, file_path: Optional[str]) -> bool:
        return self._flush_deferred_for_file(file_path)

    def _sync_overlay_display_mode(self, page_uid: Optional[str]) -> None:
        if not page_uid:
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        mode = page.image_show_mode
        if self.plan_view and self.plan_view.current_page_uid == page_uid:
            self.plan_view.set_overlay_display_mode(mode)
        for view in self._native_3d_views():
            view.set_overlay_display_mode(mode)

    def _load_takeoff_sidebar(self, bid_ref: BidRef) -> None:
        self._sidebar.load_takeoff_sidebar(bid_ref, self._bid_data_cache)

    def _update_plan_view_for_active(
        self, condition_uids=None, takeoff_uids=None
    ) -> None:
        self._viewer.update_plan_view_for_active(changed_takeoff_uids=takeoff_uids)
        self._apply_pending_hotlink_named_view_focus(require_stable=True)
        if condition_uids is None:
            self._sidebar.update_conditions_quantities()
        else:
            self._sidebar.update_conditions_quantities(condition_uids=condition_uids)

    def _update_plan_view(
        self, page_uid: Optional[str], condition_uids=None, takeoff_uids=None
    ) -> None:
        self._viewer.update_plan_view(page_uid, changed_takeoff_uids=takeoff_uids)
        self._apply_pending_hotlink_named_view_focus(require_stable=True)
        if condition_uids is None:
            self._sidebar.update_conditions_quantities()
        else:
            self._sidebar.update_conditions_quantities(condition_uids=condition_uids)

    def _update_plan_view_annotations(
        self,
        page_uid: Optional[str],
        annotation_uids: Optional[List[str]] = None,
        annotation_types: Optional[List[str]] = None,
    ) -> None:
        active_page_uid = self.ui_state_manager.active_page_uid
        if page_uid and page_uid != active_page_uid:
            return
        self._viewer.update_plan_view(
            page_uid or active_page_uid,
            changed_annotation_uids=annotation_uids,
            changed_annotation_types=annotation_types,
        )
        self._apply_pending_hotlink_named_view_focus(require_stable=True)

    def _on_condition_selected(self, condition_uid: str) -> None:
        self._selection_projected_condition_uids = set()
        if not condition_uid:
            self.ui_state_manager.set_highlighted_conditions(set())
            selected_takeoff_condition_uid = (
                self.plan_view.selected_takeoff_condition_uid()
                if self.plan_view
                else None
            )
            if not selected_takeoff_condition_uid:
                self._placement.force_exit()
                self.ensure_select_mode()
            self._toolbar.refresh()
            return
        if self.conditions_sidebar:
            selected = self.conditions_sidebar.get_selected_condition_uids()
        else:
            selected = [condition_uid]
        self.ui_state_manager.set_highlighted_conditions(set(selected))
        if not self._is_takeoff_2d_view_active() or not self._is_condition_placeable(
            condition_uid
        ):
            self._reset_to_select_mode()
            return
        self._placement.enter(condition_uid, selected)
        self._toolbar.refresh()

    def _check_takeoffs_all_negative(self, takeoff_uids: list) -> bool:
        if not takeoff_uids:
            return False
        for uid in takeoff_uids:
            t = self.project_data.get_takeoff(uid)
            if t is None or not t.is_negative:
                return False
        return True

    def _check_takeoffs_curved_state(self, takeoff_uids: list) -> tuple:
        if not takeoff_uids:
            return False, False
        conditions = self.project_data.get_bid_conditions()
        all_linear = True
        all_curved = True
        for uid in takeoff_uids:
            t = self.project_data.get_takeoff(uid)
            if t is None:
                return False, False
            c = conditions.get(t.condition_uid)
            if c is None or not c.is_linear:
                all_linear = False
                break
            if t.curve < 0:
                all_curved = False
        return all_linear, all_curved

    def _selected_takeoff_context_state(self, takeoff_uids: list):
        return build_selected_takeoff_context_state(
            takeoff_uids,
            self.project_data.get_takeoff,
            self.project_data.get_bid_conditions(),
        )

    def _resolve_bid_lock_state(self, bid_ref: BidRef) -> None:
        bid = self.project_data.get_bid(bid_ref)
        bid_status = bid.status if bid else None
        if self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        ):
            is_locked = any(
                status.name == bid_status and status.locked
                for status in self.project_data.get_job_status_snapshot(
                    bid_ref.file_path
                )
            )
        else:
            is_locked = self._project_read_service.is_bid_locked(
                bid_ref.file_path, bid_status
            )
        self.project_data.set_current_bid_locked(is_locked)

    def _on_page_scale_changed(
        self, file_path: str, page_uid: str, sf1: float, sf2: float
    ) -> None:
        if not self._flush_deferred_for_file(file_path):
            self._update_page_settings_bar(page_uid)
            return
        write_svc = self._project_write_service

        def complete(result: QueuedMutationResult) -> None:
            if result.outcome_status in {
                MutationOutcomeStatus.COMMITTED,
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            bid_ref = self.ui_state_manager.get_selected_bid_ref()
            if (
                bid_ref is not None
                and bid_ref.file_path == file_path
                and self.ui_state_manager.active_page_uid == page_uid
            ):
                self._update_page_settings_bar(page_uid)

        queued = write_svc.queue_page_setting_if_sql(
            file_path,
            page_uid,
            "scale",
            [sf1, sf2],
            callback=complete,
        )
        if queued is not None:
            if not queued:
                self._update_page_settings_bar(page_uid)
            return
        success = False
        try:
            success = bool(write_svc.save_page_scale(file_path, page_uid, sf1, sf2))
        except Exception:
            logger.warning("Failed to save page scale", exc_info=True)
        if not success:
            self._update_page_settings_bar(page_uid)

    def rotate_selected_takeoffs_left(self) -> None:
        if self._can_transform_selected_takeoffs():
            self.plan_view.rotate_selected_takeoffs(-90.0)

    def rotate_selected_takeoffs_right(self) -> None:
        if self._can_transform_selected_takeoffs():
            self.plan_view.rotate_selected_takeoffs(90.0)

    def flip_selected_takeoffs_horizontal(self) -> None:
        if self._can_transform_selected_takeoffs():
            self.plan_view.flip_selected_takeoffs(horizontal=True)

    def flip_selected_takeoffs_vertical(self) -> None:
        if self._can_transform_selected_takeoffs():
            self.plan_view.flip_selected_takeoffs(horizontal=False)

    def _can_transform_selected_takeoffs(self) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PLAN_ITEMS):
            return False
        return bool(self.plan_view and self.plan_view.has_selected_takeoffs)

    def rotate_image_left(self) -> None:
        self._adjust_current_page_image(rotation_delta=-90)

    def rotate_image_right(self) -> None:
        self._adjust_current_page_image(rotation_delta=90)

    def flip_image_horizontal(self) -> None:
        self._adjust_current_page_image(toggle_flip_x=True)

    def flip_image_vertical(self) -> None:
        self._adjust_current_page_image(toggle_flip_y=True)

    def _adjust_current_page_image(
        self,
        rotation_delta: int = 0,
        toggle_flip_x: bool = False,
        toggle_flip_y: bool = False,
    ) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        rotation = (int(page.rotation or 0) + rotation_delta) % 360
        if rotation not in (0, 90, 180, 270):
            rotation = 0
        flip_x = (not page.flip_x) if toggle_flip_x else page.flip_x
        flip_y = (not page.flip_y) if toggle_flip_y else page.flip_y
        self._save_current_page_view_state(selected_page_override=page_uid)
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        queued = self._project_write_service.queue_page_setting_if_sql(
            bid_ref.file_path,
            page_uid,
            "image_adjustments",
            [rotation, flip_x, flip_y, page.invert, page.bitonal],
        )
        if queued is None:
            self._project_write_service.save_page_image_adjustments(
                bid_ref.file_path,
                [page_uid],
                rotation,
                flip_x,
                flip_y,
                page.invert,
                page.bitonal,
            )

    def open_adjust_images_dialog(self) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        resources = self._page_dialog_resources(bid_ref, page_uid)
        lease_session = (
            ModalEditLeaseSession(
                self,
                bid_ref.file_path,
                resources,
                "AdjustImagesDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = AdjustImagesDialog(
            self._icon_provider,
            self.main_window,
            page.rotation,
            page.flip_x,
            page.flip_y,
            page.invert,
            page.bitonal,
            save_fn=lambda settings: self._save_image_adjustments(
                bid_ref.file_path, page_uid, settings
            ),
            save_async_fn=(
                (
                    lambda settings, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_image_adjustments_async(
                            bid_ref,
                            page_uid,
                            settings,
                            lambda success: lease_completed(success, None),
                            edit_lease_handle=handle,
                        ),
                        lambda success, _value: completed(success),
                    )
                )
                if uses_sql_queue
                else None
            ),
        )
        if lease_session is None:
            try:
                exec_with_ost_blocking(dialog, self.event_bus)
            finally:
                dialog.deleteLater()
            return
        lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            bid_ref.file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def _page_dialog_resources(
        self, bid_ref: BidRef, current_page_uid: str
    ) -> tuple[ResourceRef, ...]:
        bid_value = int(bid_ref.bid_uid)
        page_uids = [target.uid for target in self._rename_page_targets()]
        if current_page_uid not in page_uids:
            page_uids.append(current_page_uid)
        return tuple(ResourceRef("page", uid, bid_value) for uid in page_uids)

    def _page_setting_uids(self, page_uid: str, apply_to_all_pages: bool) -> List[str]:
        if not apply_to_all_pages:
            return [page_uid]
        if not self.takeoff_sidebar:
            return []
        return [
            uid
            for uid in self.takeoff_sidebar.get_page_order()
            if uid and self.project_data.get_page(uid)
        ]

    def _save_image_adjustments(
        self, file_path: str, page_uid: str, settings: ImageAdjustmentSettings
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        page_uids = self._page_setting_uids(page_uid, settings.apply_to_all_pages)
        if not page_uids:
            return False
        if not self._flush_deferred_for_file(file_path):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if (
            bid_ref is not None
            and bid_ref.file_path == file_path
            and self._project_write_service.uses_sql_collaboration_mutations(file_path)
        ):
            updates = [
                [
                    uid,
                    settings.rotation,
                    settings.flip_x,
                    settings.flip_y,
                    settings.invert,
                    settings.bitonal,
                ]
                for uid in page_uids
            ]
            return (
                self._project_write_service.queue_page_settings(
                    file_path,
                    bid_ref.bid_uid,
                    "image_adjustments",
                    updates,
                    lambda _result: None,
                )
                >= 0
            )
        return self._project_write_service.save_page_image_adjustments(
            file_path,
            page_uids,
            settings.rotation,
            settings.flip_x,
            settings.flip_y,
            settings.invert,
            settings.bitonal,
        )

    def _save_image_adjustments_async(
        self,
        bid_ref: BidRef,
        page_uid: str,
        settings: ImageAdjustmentSettings,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle,
    ) -> bool:
        page_uids = self._page_setting_uids(page_uid, settings.apply_to_all_pages)
        updates = [
            [
                uid,
                settings.rotation,
                settings.flip_x,
                settings.flip_y,
                settings.invert,
                settings.bitonal,
            ]
            for uid in page_uids
        ]
        return self._save_page_settings_async(
            bid_ref,
            "image_adjustments",
            updates,
            "Adjust Images",
            completed,
            edit_lease_handle,
        )

    def open_set_scale_dialog(
        self, file_path: Optional[str] = None, page_uid: Optional[str] = None
    ) -> None:
        page_uid = page_uid or self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        file_path = file_path or (bid_ref.file_path if bid_ref else None)
        if not page_uid or not file_path:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            file_path
        )
        resources = self._page_dialog_resources(bid_ref, page_uid) if bid_ref else ()
        lease_session = (
            ModalEditLeaseSession(
                self,
                file_path,
                resources,
                "SetScaleDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue and bid_ref is not None
            else None
        )
        dialog = SetScaleDialog(
            self._icon_provider,
            self.main_window,
            page.scale_factor1,
            page.scale_factor2,
            save_fn=lambda settings: self._save_scale_settings(
                file_path, page_uid, settings
            ),
            save_async_fn=(
                (
                    lambda settings, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_scale_settings_async(
                            bid_ref,
                            page_uid,
                            settings,
                            lambda success: lease_completed(success, None),
                            edit_lease_handle=handle,
                        ),
                        lambda success, _value: completed(success),
                    )
                )
                if lease_session is not None
                else None
            ),
        )
        if lease_session is None:
            try:
                exec_with_ost_blocking(dialog, self.event_bus)
            finally:
                dialog.deleteLater()
            return
        lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def _save_scale_settings(
        self, file_path: str, page_uid: str, settings: ScaleSettings
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        page_uids = self._page_setting_uids(page_uid, settings.apply_to_all_pages)
        if not page_uids:
            return False
        if not self._flush_deferred_for_file(file_path):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if (
            bid_ref is not None
            and bid_ref.file_path == file_path
            and self._project_write_service.uses_sql_collaboration_mutations(file_path)
        ):
            return (
                self._project_write_service.queue_page_settings(
                    file_path,
                    bid_ref.bid_uid,
                    "scale",
                    [
                        [uid, settings.scale_factor1, settings.scale_factor2]
                        for uid in page_uids
                    ],
                    lambda _result: None,
                )
                >= 0
            )
        if len(page_uids) == 1:
            return self._project_write_service.save_page_scale(
                file_path,
                page_uids[0],
                settings.scale_factor1,
                settings.scale_factor2,
            )
        return self._project_write_service.save_page_scales(
            file_path,
            page_uids,
            settings.scale_factor1,
            settings.scale_factor2,
        )

    def _save_scale_settings_async(
        self,
        bid_ref: BidRef,
        page_uid: str,
        settings: ScaleSettings,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle,
    ) -> bool:
        page_uids = self._page_setting_uids(page_uid, settings.apply_to_all_pages)
        updates = [
            [uid, settings.scale_factor1, settings.scale_factor2] for uid in page_uids
        ]
        return self._save_page_settings_async(
            bid_ref,
            "scale",
            updates,
            "Set Scale",
            completed,
            edit_lease_handle,
        )

    def _save_page_settings_async(
        self,
        bid_ref: BidRef,
        setting_kind: str,
        updates: list,
        title: str,
        completed,
        edit_lease_handle: EditLeaseHandle,
    ) -> bool:
        if not updates or not self.ui_access_manager.is_allowed(
            Feature.EDIT_PAGE_SETTINGS
        ):
            completed(False)
            return False
        if not self._flush_deferred_for_file(bid_ref.file_path):
            completed(False)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                completed(True)
                return
            self.present_queued_mutation_error(bid_ref.file_path, title, result)
            completed(False)

        try:
            self._project_write_service.queue_page_settings(
                bid_ref.file_path,
                bid_ref.bid_uid,
                setting_kind,
                updates,
                finish,
                edit_lease_handle=edit_lease_handle,
            )
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, title, str(exc))
            return False
        return True

    def open_rename_page_dialog(self) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        pages = self._rename_page_targets()
        if not pages:
            return
        if not any(page.uid == page_uid for page in pages):
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        bid_value = int(bid_ref.bid_uid) if uses_sql_queue else None
        resources = tuple(ResourceRef("page", page.uid, bid_value) for page in pages)
        lease_session = (
            ModalEditLeaseSession(
                self,
                bid_ref.file_path,
                resources,
                "RenamePageDialog",
                event_bus=self.event_bus,
            )
            if uses_sql_queue
            else None
        )
        dialog = RenamePageDialog(
            self._icon_provider,
            self.main_window,
            pages,
            page_uid,
            save_fn=lambda target_page_uid, new_name: self._save_page_name(
                bid_ref.file_path, target_page_uid, new_name
            ),
            save_async_fn=(
                (
                    lambda target_page_uid, new_name, completed: lease_session.submit_mutation(
                        lambda handle, lease_completed: self._save_page_name_async(
                            bid_ref,
                            target_page_uid,
                            new_name,
                            lambda success: lease_completed(success, None),
                            edit_lease_handle=handle,
                        ),
                        lambda success, _value: completed(success),
                    )
                )
                if uses_sql_queue
                else None
            ),
        )
        if lease_session is None:
            try:
                exec_with_ost_blocking(dialog, self.event_bus)
            finally:
                dialog.deleteLater()
            return
        lease_session.bind_dialog(dialog)
        self._exec_with_collaboration_lease(
            dialog,
            bid_ref.file_path,
            resources,
            dialog.cleanup,
            lease_session=lease_session,
        )

    def _rename_page_targets(self) -> List[PageRenameTarget]:
        if not self.takeoff_sidebar:
            return []
        targets: List[PageRenameTarget] = []
        for page_uid in self.takeoff_sidebar.get_page_order():
            page = self.project_data.get_page(page_uid) if page_uid else None
            if page:
                targets.append(PageRenameTarget(uid=page.uid, name=page.name))
        return targets

    def _save_page_name(self, file_path: str, page_uid: str, new_name: str) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        if not self._flush_deferred_for_file(file_path):
            return False
        queued = self._project_write_service.queue_page_setting_if_sql(
            file_path,
            page_uid,
            "name",
            [new_name],
        )
        if queued is not None:
            return queued
        return self._project_write_service.save_page_name(file_path, page_uid, new_name)

    def _save_page_name_async(
        self,
        bid_ref: BidRef,
        page_uid: str,
        new_name: str,
        completed,
        *,
        edit_lease_handle: EditLeaseHandle,
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            completed(False)
            return False
        if not self._flush_deferred_for_file(bid_ref.file_path):
            completed(False)
            return False

        def finish(result: QueuedMutationResult) -> None:
            if result.outcome_status in {
                MutationOutcomeStatus.COMMIT_STATUS_UNKNOWN,
                MutationOutcomeStatus.COMMITTED_PROJECTION_FAILED,
            }:
                return
            if result.outcome_status == MutationOutcomeStatus.COMMITTED:
                completed(True)
                return
            self.present_queued_mutation_error(bid_ref.file_path, "Rename Page", result)
            completed(False)

        try:
            self._project_write_service.queue_page_settings(
                bid_ref.file_path,
                bid_ref.bid_uid,
                "name",
                [[page_uid, new_name]],
                finish,
                edit_lease_handle=edit_lease_handle,
            )
        except (RuntimeError, ValueError) as exc:
            show_warning(self.main_window, "Rename Page", str(exc))
            return False
        return True

    def can_delete_current_page(self) -> bool:
        if not self.main_window.is_takeoff_tab_active():
            return False
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        if not self.ui_state_manager.get_selected_bid_ref():
            return False
        page_uid = self.ui_state_manager.active_page_uid
        if not page_uid or not self.project_data.get_page(page_uid):
            return False
        if not self.takeoff_sidebar:
            return False
        return len(self.takeoff_sidebar.get_page_order()) > 1

    def delete_current_page(self) -> None:
        if not self.can_delete_current_page():
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        page_uid = self.ui_state_manager.active_page_uid
        page = self.project_data.get_page(page_uid) if page_uid else None
        if not bid_ref or not page_uid or not page:
            return
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        pages_with_content = (
            self.project_data.get_page_delete_content_snapshot(
                bid_ref.file_path, bid_ref.bid_uid
            )
            if uses_sql_queue
            else self._project_read_service.get_pages_with_delete_content(
                bid_ref.file_path, bid_ref.bid_uid
            )
        )
        if pages_with_content is None:
            show_critical(
                self.main_window,
                "Delete Page",
                f"Failed to verify page contents. {DB_LOCKED_HINT}",
            )
            return
        loaded_page_has_content = bool(
            self.project_data.get_page_takeoffs(page_uid)
            or self.project_data.get_page_annotations(page_uid)
        )
        if str(page_uid) in pages_with_content or loaded_page_has_content:
            if not confirm_delete_page_with_contents(
                self.main_window, self._page_delete_display_name(page)
            ):
                return
        if not self._stage_selection_after_page_delete(page_uid):
            return
        if not self._flush_deferred_for_file(bid_ref.file_path):
            self._clear_staged_takeoff_restore()
            return
        if uses_sql_queue:
            self._project_write_service.queue_pages_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                [page_uid],
                lambda result: self._on_queued_page_delete_complete(
                    bid_ref.file_path, result
                ),
            )
            return
        if not self._project_write_service.delete_pages(bid_ref.file_path, [page_uid]):
            self._clear_staged_takeoff_restore()
            show_critical(
                self.main_window,
                "Delete Page",
                f"Failed to delete page. {DB_LOCKED_HINT}",
            )

    def _on_queued_page_delete_complete(
        self, database_id: str, result: QueuedMutationResult
    ) -> None:
        if result.outcome_status == MutationOutcomeStatus.COMMITTED:
            return
        self._clear_staged_takeoff_restore()
        self.present_queued_mutation_error(
            database_id,
            "Delete Page",
            result,
            critical=True,
        )

    def _stage_selection_after_page_delete(self, page_uid: str) -> bool:
        if not self.takeoff_sidebar:
            return False
        page_order = [uid for uid in self.takeoff_sidebar.get_page_order() if uid]
        if page_uid not in page_order:
            return False
        remaining = [uid for uid in page_order if uid != page_uid]
        if not remaining:
            show_warning(
                self.main_window,
                "Delete Page",
                "Cannot delete the last page in the bid.",
            )
            return False
        deleted_index = page_order.index(page_uid)
        next_index = min(deleted_index, len(remaining) - 1)
        next_uid = remaining[next_index]
        self._stage_takeoff_restore(page_uids=[next_uid], active_page_uid=next_uid)
        return True

    @staticmethod
    def _page_delete_display_name(page) -> str:
        if page.name:
            return page.name
        if page.image_path:
            return page.image_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        return f"Page {page.uid}"

    def select_overlay_image(self) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        path = select_overlay_image_path(
            self.main_window, page.overlay_image_path or ""
        )
        if not path:
            return
        if self._is_cleaning_up:
            return
        if (
            self.ui_state_manager.get_selected_bid_ref() != bid_ref
            or self.ui_state_manager.active_page_uid != page_uid
            or self.project_data.get_page(page_uid) is not page
        ):
            show_warning(
                self.main_window,
                "Overlay Selection Cancelled",
                "The selected page changed while the file dialog was open. "
                "Please choose the overlay again.",
            )
            return
        self._save_page_overlay_image(bid_ref.file_path, page_uid, path)

    def remove_overlay_image(self) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if not page or not page.overlay_image_path:
            return
        self._save_page_overlay_image(bid_ref.file_path, page_uid, "")

    def show_overlay_image(self, checked: bool) -> None:
        self._set_overlay_visibility("overlay", checked)

    def show_original_image(self, checked: bool) -> None:
        self._set_overlay_visibility("original", checked)

    def _set_overlay_visibility(self, target: str, checked: bool) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        if not page_uid:
            self._update_export_menu_state()
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            self._update_export_menu_state()
            return
        has_original = bool(page.image_path)
        has_overlay = bool(page.overlay_image_path)
        source_unavailable = (target == "original" and not has_original) or (
            target == "overlay" and not has_overlay
        )
        hides_only_source = (
            target == "original" and not checked and not has_overlay
        ) or (target == "overlay" and not checked and not has_original)
        if source_unavailable or hides_only_source:
            self._update_export_menu_state()
            return
        show_mode = resolve_overlay_visibility_mode(
            page.image_show_mode, target, checked
        )
        if show_mode == page.image_show_mode:
            return
        self._on_overlay_display_mode_requested(show_mode)

    def _save_page_overlay_image(
        self, file_path: str, page_uid: str, overlay_image_path: str
    ) -> None:
        self._save_current_page_view_state(selected_page_override=page_uid)
        if not self._flush_deferred_for_file(file_path):
            return
        queued = self._project_write_service.queue_page_setting_if_sql(
            file_path,
            page_uid,
            "overlay_image",
            [overlay_image_path],
        )
        if queued is None:
            self._project_write_service.save_page_overlay_image(
                file_path, page_uid, overlay_image_path
            )

    def _on_page_area_changed(
        self, file_path: str, page_uid: str, area_uid: str
    ) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref is None or bid_ref.file_path != file_path:
            return
        page_area_selections = self.project_data.get_page_area_selections()
        previous_area_uid = page_area_selections.get(page_uid)
        self._project_page_area_if_current(bid_ref, page_uid, area_uid)
        self._deferred_persistence.schedule_page_area_selection(
            file_path,
            page_uid,
            area_uid or "",
            restore_authoritative=lambda: self._project_page_area_if_current(
                bid_ref,
                page_uid,
                previous_area_uid or "",
            ),
            project_value=lambda: self._project_page_area_if_current(
                bid_ref,
                page_uid,
                area_uid,
            ),
        )

    def _project_page_area_if_current(
        self,
        bid_ref: BidRef,
        page_uid: str,
        area_uid: str,
    ) -> None:
        if not self._page_setting_context_is_current(bid_ref, page_uid):
            return
        page_area_selections = self.project_data.get_page_area_selections()
        page_area_selections[page_uid] = area_uid if area_uid else None
        self.ui_state_manager.selected_area_uid = area_uid or ""
        self._viewer.update_plan_view(page_uid)
        self.main_window.refresh_detached_plan_views()
        self._request_or_defer_mesh_refresh(
            self.project_data.get_selected_page_uids()
        )
        self._apply_pending_hotlink_named_view_focus(require_stable=True)

    def _on_overlay_display_mode_requested(self, show_mode: int) -> None:
        if show_mode not in (SHOW_ORIGINAL, SHOW_OVERLAY, SHOW_BOTH):
            return
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page = self.project_data.get_page(page_uid)
        if page is None:
            return
        previous_show_mode = page.image_show_mode
        self._save_current_page_view_state(selected_page_override=page_uid)
        self._project_page_show_mode_if_current(bid_ref, page_uid, show_mode)
        self._deferred_persistence.schedule_page_show_mode(
            bid_ref.file_path,
            page_uid,
            show_mode,
            restore_authoritative=lambda: self._project_page_show_mode_if_current(
                bid_ref,
                page_uid,
                previous_show_mode,
            ),
            project_value=lambda: self._project_page_show_mode_if_current(
                bid_ref,
                page_uid,
                show_mode,
            ),
        )

    def _project_page_show_mode_if_current(
        self,
        bid_ref: BidRef,
        page_uid: str,
        show_mode: int,
    ) -> None:
        if not self._page_setting_context_is_current(bid_ref, page_uid):
            return
        page = self.project_data.get_page(page_uid)
        if page is None:
            return
        page.image_show_mode = show_mode
        self._sync_overlay_display_mode(page_uid)
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)
        self.main_window.refresh_detached_plan_views()
        self._update_export_menu_state()

    def _page_setting_context_is_current(
        self,
        bid_ref: BidRef,
        page_uid: str,
    ) -> bool:
        return bool(
            self.ui_state_manager.get_selected_bid_ref() == bid_ref
            and self.ui_state_manager.active_page_uid == page_uid
            and self.project_data.get_page(page_uid) is not None
        )

    def toggle_page_invert(self, invert: bool) -> None:
        self._toggle_page_image_flag(
            "invert",
            self._set_page_invert,
            bool(invert),
        )

    def toggle_page_bitonal(self, bitonal: bool) -> None:
        self._toggle_page_image_flag(
            "bitonal",
            self._set_page_bitonal,
            bool(bitonal),
        )

    @staticmethod
    def _set_page_invert(page, value: bool) -> None:
        page.invert = value

    @staticmethod
    def _set_page_bitonal(page, value: bool) -> None:
        page.bitonal = value

    def _toggle_page_image_flag(self, flag_name: str, write_fn, value: bool) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            self._update_export_menu_state()
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            self._update_export_menu_state()
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            self._update_export_menu_state()
            return
        self._save_current_page_view_state(selected_page_override=page_uid)
        if flag_name == "invert":
            previous_value = bool(page.invert)
        elif flag_name == "bitonal":
            previous_value = bool(page.bitonal)
        else:
            raise ValueError("Unsupported deferred page image flag")
        self._project_page_image_flag_if_current(
            bid_ref,
            page_uid,
            flag_name,
            write_fn,
            value,
        )
        callbacks = {
            "restore_authoritative": lambda: self._project_page_image_flag_if_current(
                bid_ref,
                page_uid,
                flag_name,
                write_fn,
                previous_value,
            ),
            "project_value": lambda: self._project_page_image_flag_if_current(
                bid_ref,
                page_uid,
                flag_name,
                write_fn,
                value,
            ),
        }
        if flag_name == "invert":
            self._deferred_persistence.schedule_page_invert(
                bid_ref.file_path, page_uid, value, **callbacks
            )
        elif flag_name == "bitonal":
            self._deferred_persistence.schedule_page_bitonal(
                bid_ref.file_path, page_uid, value, **callbacks
            )

    def _project_page_image_flag_if_current(
        self,
        bid_ref: BidRef,
        page_uid: str,
        flag_name: str,
        write_fn,
        value: bool,
    ) -> None:
        if not self._page_setting_context_is_current(bid_ref, page_uid):
            return
        page = self.project_data.get_page(page_uid)
        if page is None:
            return
        write_fn(page, value)
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)
        self.main_window.refresh_detached_plan_views()
        self._update_export_menu_state()

    def _on_layer_visibility_toggled(self, layer_uid: str, show: bool) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        self.update_layer_visibility_deferred(layer_uid, show)

    def _layer_has_condition_rows(self, layer_uid: str) -> bool:
        layer_key = str(layer_uid)
        return any(
            str(condition.layer_uid or "") == layer_key
            for condition in self.project_data.get_bid_conditions().values()
        )

    def update_layer_visibility_deferred(self, layer_uid: str, show: bool) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return False
        layer = next(
            (
                layer
                for layer in self.project_data.get_bid_layer_snapshot()
                if str(layer.uid) == str(layer_uid)
            ),
            None,
        )
        if layer is None:
            return False
        previous_show = bool(layer.show)
        if not self._project_layer_visibility_if_current(bid_ref, layer_uid, show):
            return False
        self._deferred_persistence.schedule_layer_show(
            bid_ref.file_path,
            layer_uid,
            show,
            restore_authoritative=lambda: self._project_layer_visibility_if_current(
                bid_ref,
                layer_uid,
                previous_show,
            ),
            project_value=lambda: self._project_layer_visibility_if_current(
                bid_ref,
                layer_uid,
                show,
            ),
        )
        return True

    def _project_layer_visibility_if_current(
        self,
        bid_ref: BidRef,
        layer_uid: str,
        show: bool,
    ) -> bool:
        if self.ui_state_manager.get_selected_bid_ref() != bid_ref:
            return False
        if not any(
            str(layer.uid) == str(layer_uid)
            for layer in self.project_data.get_bid_layer_snapshot()
        ):
            return False
        image_layer = self.project_data.is_image_layer_uid(layer_uid)
        condition_layer = self._layer_has_condition_rows(layer_uid)
        if not show and not image_layer:
            self._suspend_active_layer_tool(layer_uid)
        changed_page_uids = self.project_data.update_layer_visibility(layer_uid, show)
        if image_layer:
            self._update_native_page_textures()
        self.event_bus.publish(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            file_path=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            layer_uid=layer_uid,
            show=show,
            image_layer=image_layer,
            all_layers=False,
        )
        if self._sidebar.bid_layers_sidebar:
            self._sidebar.bid_layers_sidebar.set_layer_visible(layer_uid, show)
        if condition_layer:
            self._refresh_conditions_sidebar_layer_visibility_from_memory(layer_uid)
        self._apply_layer_visibility_to_current_plan_view(
            layer_uid,
            show,
            changed_page_uids=changed_page_uids,
        )
        if condition_layer:
            self._request_or_defer_mesh_refresh(
                self.project_data.get_selected_page_uids()
            )
        self._update_export_menu_state()
        if show and not image_layer:
            self._restore_suspended_layer_tool(layer_uid)
        return True

    def _apply_layer_visibility_to_current_plan_view(
        self,
        layer_uid: str,
        show: bool,
        *,
        changed_page_uids: Optional[List[str]] = None,
        all_layers: bool = False,
    ) -> None:
        active_page_uid = self.ui_state_manager.active_page_uid
        if not active_page_uid or not self.plan_view:
            return
        if self.plan_view.current_page_uid != active_page_uid:
            self._update_plan_view(active_page_uid)
            return
        changed_page_uid_set = {str(uid) for uid in (changed_page_uids or [])}
        page_layer_changed = active_page_uid in changed_page_uid_set
        if page_layer_changed:
            page = self.project_data.get_page(active_page_uid)
            if page and self.plan_view.apply_page_image_layer_visibility(page):
                if not all_layers:
                    return
            else:
                self._update_plan_view(active_page_uid)
                return
        conditions = self.project_data.get_bid_conditions()
        if all_layers and self.plan_view.apply_all_layer_visibility(show, conditions):
            return
        if not all_layers and self.plan_view.apply_layer_visibility(
            layer_uid, show, conditions
        ):
            return
        self._update_plan_view(active_page_uid)

    def _on_layer_added(self, name: str, after_sequence: int) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        sidebar = self._sidebar.bid_layers_sidebar
        if not sidebar:
            return
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        ):
            self._project_write_service.queue_layer_insert(
                bid_ref.file_path,
                bid_ref.bid_uid,
                name,
                after_sequence,
                lambda result: self._on_queued_layer_insert_complete(sidebar, result),
            )
            return
        try:
            result = self._project_write_service.insert_layer_result(
                bid_ref.file_path, bid_ref.bid_uid, name, after_sequence
            )
            if not result.write_success or not result.value:
                self._sidebar.load_bid_layers_sidebar()
                return
            if result.refresh_failed:
                show_warning(
                    self.main_window,
                    "Refresh Error",
                    "The layer was created, but the layer list could not be "
                    "refreshed. Reopen the database to see the new layer.",
                )
                return
            sidebar.set_pending_selection(str(result.value))
        except Exception:
            logger.warning("Failed to insert layer", exc_info=True)
            self._sidebar.load_bid_layers_sidebar()

    def _on_queued_layer_insert_complete(
        self, sidebar, result: QueuedMutationResult
    ) -> None:
        if (
            result.outcome_status == MutationOutcomeStatus.COMMITTED
            and result.created_resource_ids
        ):
            sidebar.set_pending_selection(result.created_resource_ids[0])
            return
        logger.warning("Queued SQL layer insertion failed: %s", result.message)
        if not self._is_cleaning_up:
            self._sidebar.load_bid_layers_sidebar_from_memory()
            self.present_queued_mutation_error(
                result.database_id, "Layer Creation", result
            )

    def _on_layer_deleted(self, layer_uid: str) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if write_svc.uses_sql_collaboration_mutations(bid_ref.file_path):
            write_svc.queue_layer_delete(
                bid_ref.file_path,
                bid_ref.bid_uid,
                layer_uid,
                self._on_queued_layer_write_complete,
            )
            return
        try:
            write_svc.delete_layer(bid_ref.file_path, layer_uid)
        except Exception:
            logger.warning("Failed to delete layer", exc_info=True)

    def _on_layers_show_all(self, show: bool) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        self.update_all_layers_visibility_deferred(show)

    def update_all_layers_visibility_deferred(self, show: bool) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return False
        uses_sql_queue = self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        )
        if self._sidebar.bid_layers_sidebar:
            layers = self._sidebar.bid_layers_sidebar.get_layers()
            self._sidebar.bid_layers_sidebar.set_all_layers_visible(show)
        elif uses_sql_queue:
            layers = self.project_data.get_bid_layer_snapshot()
        else:
            layers = self._project_read_service.get_merged_bid_layers(
                bid_ref.file_path, bid_ref.bid_uid
            )
        previous_visibility = {
            str(layer.uid): bool(layer.show) for layer in layers
        }
        if not show:
            self._suspend_active_layer_tool()
        self.project_data.set_bid_layer_visibility(layers)
        changed_page_uids = self.project_data.update_all_layer_visibility(show)
        self._update_native_page_textures()
        self.event_bus.publish(
            AppEvents.LAYER_VISIBILITY_CHANGED,
            file_path=bid_ref.file_path,
            bid_uid=bid_ref.bid_uid,
            show=show,
            all_layers=True,
        )
        self._refresh_conditions_sidebar_layer_visibility_from_memory(
            update_summary=False
        )
        for layer in layers:
            self._deferred_persistence.schedule_layer_show(
                bid_ref.file_path,
                layer.uid,
                show,
                restore_authoritative=lambda layer_uid=str(layer.uid): (
                    self._project_layer_visibility_if_current(
                        bid_ref,
                        layer_uid,
                        previous_visibility[layer_uid],
                    )
                ),
                project_value=lambda layer_uid=str(layer.uid): (
                    self._project_layer_visibility_if_current(
                        bid_ref,
                        layer_uid,
                        show,
                    )
                ),
            )
        self._apply_layer_visibility_to_current_plan_view(
            "",
            show,
            changed_page_uids=changed_page_uids,
            all_layers=True,
        )
        self._request_or_defer_mesh_refresh(self.project_data.get_selected_page_uids())
        self._load_condition_summary()
        self._update_export_menu_state()
        if show:
            self._restore_suspended_layer_tool()
        return True

    def _refresh_conditions_sidebar_layer_visibility_from_memory(
        self,
        layer_uid: Optional[str] = None,
        *,
        update_summary: bool = True,
    ) -> None:
        conditions = self.project_data.get_bid_conditions()
        grayscale = self.ui_state_manager.state.grayscale_enabled
        if self.conditions_sidebar:
            self.conditions_sidebar.apply_layer_visibility_state(
                conditions,
                grayscale,
                layer_uid,
            )
        if not update_summary:
            return
        if self.condition_summary_tab:
            self.condition_summary_tab.apply_layer_visibility_state(
                conditions,
                grayscale,
                layer_uid,
            )

    def _on_layer_moved(self, layer_uid: str, direction: int) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        sidebar = self._sidebar.bid_layers_sidebar
        if not sidebar:
            return
        neighbor_uid = sidebar.get_neighbor_uid(direction)
        if not neighbor_uid:
            return
        if not self._flush_deferred_for_file(bid_ref.file_path):
            return
        if self._project_write_service.uses_sql_collaboration_mutations(
            bid_ref.file_path
        ):
            self._project_write_service.queue_layer_reorder(
                bid_ref.file_path,
                bid_ref.bid_uid,
                layer_uid,
                neighbor_uid,
                self._on_queued_layer_write_complete,
            )
            return
        try:
            self._project_write_service.swap_layer_sequence(
                bid_ref.file_path, layer_uid, neighbor_uid
            )
        except Exception:
            logger.warning("Failed to move layer", exc_info=True)

    def _on_layer_renamed(self, layer_uid: str, new_name: str) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        uses_sql_queue = write_svc.uses_sql_collaboration_mutations(bid_ref.file_path)
        success = False
        if not self._flush_deferred_for_file(bid_ref.file_path):
            if uses_sql_queue:
                self._sidebar.load_bid_layers_sidebar_from_memory()
            else:
                self._sidebar.load_bid_layers_sidebar()
            return
        if uses_sql_queue:
            write_svc.queue_layer_rename(
                bid_ref.file_path,
                bid_ref.bid_uid,
                layer_uid,
                new_name,
                self._on_queued_layer_write_complete,
            )
            return
        try:
            success = bool(
                write_svc.update_layer_name(bid_ref.file_path, layer_uid, new_name)
            )
        except Exception:
            logger.warning("Failed to rename layer", exc_info=True)
        if not success:
            self._sidebar.load_bid_layers_sidebar()

    def _on_queued_layer_write_complete(self, result: QueuedMutationResult) -> None:
        if result.outcome_status == MutationOutcomeStatus.COMMITTED:
            return
        logger.warning("Queued SQL layer update failed: %s", result.message)
        if not self._is_cleaning_up:
            self._sidebar.load_bid_layers_sidebar_from_memory()
            self.present_queued_mutation_error(
                result.database_id, "Layer Update", result
            )
