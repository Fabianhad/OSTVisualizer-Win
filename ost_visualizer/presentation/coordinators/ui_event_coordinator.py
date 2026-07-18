import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, Signal
from ...application.dtos.mesh_geometry_dto import MeshGeometry
from ...application.dtos.collaboration_dtos import ResourceRef
from ...application.events.app_events import AppEvents
from ...domain.entities.bid import Bid
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.loaded_file import LoadedFile
from ...domain.entities.named_view import NamedView, build_named_view_from_annotation
from ...domain.entities.project_factory import build_loaded_files
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
from ..handlers.condition_action_handler import ConditionActionHandler
from ..managers.app_config_presentation_manager import AppConfigPresentationManager
from ..managers.ui_access_manager import Feature
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
from ..utils.view_context_menu import build_selected_takeoff_context_state
from ..windows.mesh_view_window import MeshViewWindow
from .navigation_state_machine import NavigationStateMachine, NavState
from .placement_coordinator import PlacementCoordinator
from .sidebar_coordinator import SidebarCoordinator
from .toolbar_state_coordinator import ToolbarStateCoordinator
from .viewer_sync_coordinator import ViewerSyncCoordinator

logger = logging.getLogger(__name__)
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


class _MainThreadSignaler(QObject):
    update_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callback = None

    def set_callback(self, callback):
        self._callback = callback
        self.update_requested.connect(self._on_update_requested)

    def request_update(self):
        self.update_requested.emit()

    def _on_update_requested(self):
        if self._callback:
            self._callback()

    def cleanup(self) -> None:
        self.update_requested.disconnect()
        self._callback = None


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
            self.visualization_service,
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
        self._last_mesh_args: Optional[tuple] = None
        self._last_mesh_options: Optional[dict] = None
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
        self._last_takeoff_selection_context_by_source: Dict[
            str, Tuple[Tuple[str, ...], Tuple[str, ...]]
        ] = {}
        self._pending_hotlink_page_uid: Optional[str] = None
        self._pending_hotlink_named_view: Optional[NamedView] = None
        self._plan_view_signaler = _MainThreadSignaler(main_window)
        self._plan_view_signaler.set_callback(self._update_plan_view_for_active)
        self._menu_state_signaler = _MainThreadSignaler(main_window)
        self._menu_state_signaler.set_callback(self._update_export_menu_state)
        self._delete_state_signaler = _MainThreadSignaler(main_window)
        self._delete_state_signaler.set_callback(self._toolbar.refresh)
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
        if self._sidebar:
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
                and self._last_mesh_args
                and self._last_mesh_options
            ):
                self.opengl_viewer.apply_mesh_data(
                    *self._last_mesh_args, **self._last_mesh_options
                )
        self._update_page_info_status()
        self._toolbar.refresh()

    def set_opengl_viewer(self, viewer) -> None:
        self.opengl_viewer = viewer
        self._viewer.opengl_viewer = viewer
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
        self._viewer.update_license_visualization_state()
        self._sync_embedded_renderer_exposure()

    def set_plan_texture_provider(self, provider) -> None:
        self._plan_texture_provider = provider
        for view in self._native_3d_views():
            view.set_plan_texture_provider(provider)

    def _native_3d_views(self) -> tuple:
        return tuple(
            view for view in (self.opengl_viewer, self._mesh_window) if view is not None
        )

    def _update_native_page_visibility(self) -> None:
        page_uid = self.ui_state_manager.active_page_uid
        page = self.project_data.get_page(page_uid) if page_uid else None
        if page is None:
            return
        visible = bool(page.layer_visible)
        for view in self._native_3d_views():
            view.set_plan_texture_visibility(visible)

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
            window.destroyed.connect(self._on_mesh_window_destroyed)
            self._mesh_window = window
            self._refresh_mesh_window_access()
            if self._plan_texture_provider:
                window.set_plan_texture_provider(self._plan_texture_provider)
            self._sync_overlay_display_mode(self.ui_state_manager.active_page_uid)
            self._sync_mesh_window_action(True)
            window.show_initial_window()
            if self._mesh_scene_dirty:
                self._flush_dirty_mesh_refresh_if_needed()
            else:
                self._replay_mesh_if_current(window)
            return
        if self._mesh_window is None:
            self._sync_mesh_window_action(False)
            return
        self._mesh_window.close()

    def _replay_mesh_if_current(self, window: MeshViewWindow) -> None:
        if not self._last_mesh_args or not self._last_mesh_options:
            return
        active_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        cached_bid_ref = self._last_mesh_options.get("bid_ref")
        if cached_bid_ref != active_bid_ref:
            logger.warning(
                "Discarding stale mesh replay: cached bid_ref=%s, active bid_ref=%s",
                cached_bid_ref,
                active_bid_ref,
            )
            self._last_mesh_args = None
            self._last_mesh_options = None
            return
        window.apply_mesh_data(*self._last_mesh_args, **self._last_mesh_options)

    def _clear_mesh_replay_buffer(self) -> None:
        self._last_mesh_args = None
        self._last_mesh_options = None

    def _clear_mesh_views_for_scene_update(self, clear_embedded: bool = True) -> None:
        self._clear_mesh_replay_buffer()
        self._clear_mesh_dirty_state()
        if clear_embedded and self.opengl_viewer:
            self.opengl_viewer.clear_scene()
        if self._mesh_window:
            self._mesh_window.clear_scene()

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
        pages = [str(uid) for uid in page_uids if uid]
        if not pages:
            self._clear_mesh_views_for_scene_update()
            self.visualization_service.refresh_mesh_view([])
            return
        if self._needs_live_3d_mesh_refresh():
            self._pending_dirty_mesh_refresh = self._mesh_scene_dirty
            self.visualization_service.refresh_mesh_view(pages)
            return
        self._mark_mesh_scene_dirty(dirty_page_uids or pages)

    def _flush_dirty_mesh_refresh_if_needed(self) -> None:
        if not self._mesh_scene_dirty or not self.ui_access_manager.is_allowed(
            Feature.VIEW_3D
        ):
            return
        selected_pages = self.project_data.get_selected_page_uids()
        if not selected_pages:
            self._clear_mesh_views_for_scene_update()
            self.visualization_service.refresh_mesh_view([])
            return
        self._pending_dirty_mesh_refresh = True
        self.visualization_service.refresh_mesh_view(selected_pages)

    def _on_mesh_window_clicked(self, takeoff_uids: list) -> None:
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
            return
        self._sync_selection(self._SOURCE_3D_WINDOW, takeoff_uids)

    def _on_mesh_window_destroyed(self, _: QObject) -> None:
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
        view.backout_mode_changed.connect(self._on_backout_mode_changed)
        view.clipboard_changed.connect(self._toolbar.refresh)
        view.text_annotation_edit_mode_changed.connect(
            self._on_text_annotation_edit_mode_changed
        )
        view.page_fully_loaded.connect(self._on_plan_view_page_fully_loaded)
        view.page_view_state_changed.connect(self._on_plan_view_state_changed)
        view.overlay_display_mode_requested.connect(
            self._on_overlay_display_mode_requested
        )
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
        self._last_takeoff_selection_context_by_source.clear()
        if clear_sidebars:
            self._sidebar.clear_sidebars()
        if clear_sidebars and self._page_settings_bar:
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
            self._load_takeoff_sidebar(bid_ref)
            self._sidebar.load_bid_layers_sidebar()
            self._sidebar.load_conditions_sidebar()
            self._load_condition_summary()
            highlighted = self._validate_condition_uids(
                self.ui_state_manager.highlighted_condition_uids
            )
            self.highlight_sidebar(highlighted, reveal=False)
            self._takeoff_workspace_bid_ref = bid_ref
        should_restore_selection = (
            needs_hydration
            or self._pending_takeoff_page_uids is not None
            or not self.ui_state_manager.selected_page_uids
            or not self.ui_state_manager.active_page_uid
        )
        if should_restore_selection:
            page_uids, active_uid = self._resolve_takeoff_selection()
            if page_uids or self._pending_takeoff_page_uids is not None:
                self.takeoff_sidebar.restore_selection(page_uids, active_uid)
        else:
            self._sidebar.update_conditions_quantities()
            self._update_page_info_status()
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
        self._toolbar.refresh()
        if index == TAB_INDEX_TAKEOFF:
            self._activate_takeoff_workspace()
            self._update_export_menu_state()
            return
        if index == TAB_INDEX_SUMMARY:
            self._load_condition_summary()
            self._update_export_menu_state()
            return
        self._clear_page_info_status()
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
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        self._deferred_persistence.schedule_page_view_state(
            bid_ref.file_path, page_uid, zoom_fac, current_x, current_y
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

    def highlight_sidebar(self, uids: set, reveal: bool = True) -> None:
        if self._nav.is_refreshing:
            return
        self.ui_state_manager.set_highlighted_conditions(uids)
        if self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(uids, reveal=reveal)

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

    def _takeoff_uids_to_condition_uids(self, uids: list) -> set:
        if not uids:
            return set()
        wanted = set(uids)
        result = set()
        for takeoff in self.project_data.get_all_takeoffs():
            if takeoff.uid in wanted:
                result.add(takeoff.condition_uid)
        return result

    _SOURCE_2D = "2d"
    _SOURCE_3D = "3d_embedded"
    _SOURCE_3D_WINDOW = "3d_window"

    def _sync_selection(self, source: str, takeoff_uids: list) -> None:
        if self._placement is None or self._nav is None:
            return
        if takeoff_uids:
            cond_uids = self._takeoff_uids_to_condition_uids(takeoff_uids)
            selection_context = (tuple(sorted(takeoff_uids)), tuple(sorted(cond_uids)))
            selection_changed = (
                self._last_takeoff_selection_context_by_source.get(source)
                != selection_context
            )
            self._last_takeoff_selection_context_by_source[source] = selection_context
            current_highlight = set(self.ui_state_manager.highlighted_condition_uids)
            highlight_missing = bool(cond_uids) and not current_highlight
            if selection_changed or highlight_missing:
                self.highlight_sidebar(cond_uids)
            if source != self._SOURCE_2D and self.plan_view:
                self.plan_view.set_selected_uids(set(takeoff_uids), emit=False)
            if source != self._SOURCE_3D and self.opengl_viewer:
                self.opengl_viewer.set_selected_takeoffs(takeoff_uids)
            if source != self._SOURCE_3D_WINDOW and self._mesh_window:
                self._mesh_window.set_selected_takeoffs(takeoff_uids)
            if (
                source != self._SOURCE_2D
                and self._placement.is_active
                and len(cond_uids) == 1
            ):
                new_uid = next(iter(cond_uids))
                if (
                    new_uid != self._placement.condition_uid
                    and self._is_condition_placeable(new_uid)
                ):
                    self._placement.enter(new_uid, list(cond_uids))
        else:
            self._last_takeoff_selection_context_by_source[source] = ((), ())
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
        self.ui_access_manager.set_text_annotation_edit_active(active)
        self._update_export_menu_state()

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
            AppEvents.REMOTE_CONDITIONS_CHANGED,
            self._on_remote_conditions_changed,
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
            AppEvents.COLLABORATION_STATE_CHANGED,
            self._on_collaboration_state_changed,
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
        self.main_window.menu_controller.update_menu_states()
        self._toolbar.refresh()

    def refresh_conditions_ui(self) -> None:
        self._sidebar.refresh_conditions_from_memory()

    def begin_collaboration_edit(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> bool:
        return self._sql_collaboration.begin_local_edit(database_id, resources)

    def end_collaboration_edit(
        self, database_id: str, resources: tuple[ResourceRef, ...]
    ) -> None:
        self._sql_collaboration.end_local_edit(database_id, resources)

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
        areas = self._project_read_service.get_bid_areas(
            bid_ref.file_path, bid_ref.bid_uid
        )
        used_uids = self.project_data.get_area_uids_with_takeoff()

        def save_fn(changes):
            return self._save_bid_areas_from_dialog(bid_ref, changes)

        dialog = BidAreasDialog(
            self._icon_provider,
            parent=self.main_window,
            bid_areas=areas,
            save_fn=save_fn,
            used_uids=used_uids,
            has_license=True,
            bid_ref=bid_ref,
        )
        area_bid_uid = (
            int(bid_ref.bid_uid) if str(bid_ref.bid_uid).isdecimal() else None
        )
        area_resource = ResourceRef("areas_collection", bid_ref.bid_uid, area_bid_uid)
        if not self.begin_collaboration_edit(bid_ref.file_path, (area_resource,)):
            dialog.cleanup()
            dialog.deleteLater()
            return
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            self.end_collaboration_edit(bid_ref.file_path, (area_resource,))
            dialog.cleanup()
            saved_changes = dialog.has_saved_changes()
            dialog.deleteLater()
        if saved_changes and not self._project_write_service.reload_and_notify(
            bid_ref.file_path
        ):
            show_warning(
                self.main_window,
                "Refresh Error",
                "The bid area changes were saved, but the area list could not be "
                "refreshed. Reopen the database to see the latest bid areas.",
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

    def open_employees_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        employees, pay_classes = (
            self._project_read_service.get_employees_and_pay_classes(file_path)
        )
        used_employee_uids = self._project_read_service.get_estimator_uids_in_use(
            file_path
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
            pay_classes_save_fn=lambda changes: self._save_master_pay_classes(
                file_path, changes
            ),
            menu_mode=True,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def open_job_statuses_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        data = (
            self._project_read_service.get_cover_sheet_data(file_path, bid_ref.bid_uid)
            if bid_ref
            and normalize_path(bid_ref.file_path) == normalize_path(file_path)
            else None
        )
        job_statuses = (
            data.job_statuses
            if data
            else self._project_read_service.get_job_statuses(file_path)
        )
        used_job_status_uids = data.used_job_status_uids if data is not None else set()
        dialog = JobStatusesDialog(
            self._icon_provider,
            parent=self.main_window,
            job_statuses=job_statuses,
            used_job_status_uids=used_job_status_uids,
            save_fn=lambda changes: self._save_master_job_statuses(file_path, changes),
            menu_mode=True,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def open_condition_types_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        dialog = ConditionTypesDialog(
            self._icon_provider,
            parent=self.main_window,
            condition_types=list(
                self._project_read_service.get_cdn_types(file_path).values()
            ),
            save_fn=lambda changes: self._save_master_condition_types(
                file_path, changes
            ),
            blocked_delete_uids_fn=lambda uids: {
                str(uid)
                for uid in self._project_write_service.validate_condition_types_delete(
                    file_path, uids
                ).blocked_uids
            },
            delete_fn=lambda uids: self._delete_master_condition_types(file_path, uids),
            reload_fn=lambda: list(
                self._project_read_service.get_cdn_types(file_path).values()
            ),
            has_license=True,
            menu_mode=True,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def open_payroll_classes_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        employees, pay_classes = (
            self._project_read_service.get_employees_and_pay_classes(file_path)
        )
        used_pay_class_uids = {
            str(employee.pay_class_uid)
            for employee in employees
            if employee.pay_class_uid
        }
        dialog = PayrollClassListDialog(
            self._icon_provider,
            parent=self.main_window,
            pay_classes=pay_classes,
            used_pay_class_uids=used_pay_class_uids,
            save_fn=lambda changes: self._save_master_pay_classes(file_path, changes),
            menu_mode=True,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

    def open_default_layers_dialog(self) -> None:
        file_path = self._editable_master_data_file_path()
        if not file_path:
            return
        dialog = LayersDialog(
            self._icon_provider,
            parent=self.main_window,
            layers=self._project_read_service.get_default_layers(file_path),
            reload_fn=lambda: self._project_read_service.get_default_layers(file_path),
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
            has_license=True,
            mode=LayersDialogMode.DEFAULT_LAYERS,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

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
        self._menu_state_signaler.request_update()

    def cleanup(self) -> None:
        self._is_cleaning_up = True
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
            self._delete_state_signaler,
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
        self._delete_state_signaler = None
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

    def flush_current_page_state(self) -> bool:
        self._save_current_page_view_state()
        return bool(self._deferred_persistence.flush())

    def _on_file_opened(self, file_path: str = "") -> None:
        self._save_current_page_view_state()
        self._placement.force_exit()
        self.ui_state_manager.reset_selections()
        self._sync_undo_bid()
        self.main_window.project_view.set_selected_node_state(None)
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.ui_access_manager.refresh()
        self._viewer.clear_viewer()
        self._set_takeoff_tab_visible(False)
        self._rebuild_ui_after_file_load()
        self._update_export_menu_state()
        self.main_window.set_database_window_title(file_path)

    def _on_database_refreshed(self, file_path: str = "") -> None:
        if file_path and not self._flush_deferred_for_file(file_path):
            return
        if not self._nav.start_refresh(
            self.ui_state_manager,
            self._placement,
            selected_area_uid=self.ui_state_manager.selected_area_uid,
        ):
            return
        try:
            self._do_file_refresh()
        finally:
            self._finish_refresh()

    def _on_database_capabilities_changed(self, file_path: str = "") -> None:
        if not file_path or file_path == self.ui_state_manager.selected_file_path:
            self.ui_access_manager.refresh()
            selected_file_path = self.ui_state_manager.selected_file_path
            if selected_file_path and not self.ui_access_manager.is_database_editable():
                self._deferred_persistence.cancel_for_file(selected_file_path)
            self._update_export_menu_state()
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
        takeoff_uids: list | None = None,
        condition_uids: list | None = None,
        update_shell: bool = True,
    ) -> None:
        page_uid = page_uid or self.ui_state_manager.active_page_uid
        if page_uid:
            self._refresh_takeoff_dependent_page_controls(page_uid)
        if page_uid:
            self._update_plan_view(
                page_uid,
                condition_uids=condition_uids,
                takeoff_uids=takeoff_uids,
            )
        else:
            self._update_plan_view_for_active(
                condition_uids=condition_uids,
                takeoff_uids=takeoff_uids,
            )
        self._request_or_defer_mesh_refresh(
            self.project_data.get_selected_page_uids(),
            dirty_page_uids=[page_uid] if page_uid else None,
        )
        if self._is_summary_tab_active():
            self._load_condition_summary()
        if update_shell:
            self._update_export_menu_state()
            self._restore_project_tree_bid_selection_if_needed()

    def _on_remote_bid_content_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        families: Optional[List[str]] = None,
        resource_uids_by_family: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid):
            return
        changed_families = set(families or [])
        changed_uids = resource_uids_by_family or {}
        if self._undo_service and changed_families & {"takeoffs", "annotations"}:
            self._undo_service.clear()
        if "takeoffs" in changed_families:
            self._on_takeoffs_changed(
                page_uid=self.ui_state_manager.active_page_uid,
                takeoff_uids=changed_uids.get("takeoffs") or None,
                update_shell=False,
            )
        if "annotations" in changed_families:
            self._on_annotations_changed(
                page_uid=self.ui_state_manager.active_page_uid,
                annotation_uids=changed_uids.get("annotations") or None,
                update_shell=False,
            )
        if "pages" in changed_families:
            valid_pages = [
                uid
                for uid in self.ui_state_manager.selected_page_uids
                if self.project_data.get_page(uid)
            ]
            active_page = self.ui_state_manager.active_page_uid
            if active_page and not self.project_data.get_page(active_page):
                ordered_pages = sorted(
                    self.project_data.get_all_pages(), key=lambda page: page.sequence
                )
                active_page = ordered_pages[0].uid if ordered_pages else None
            self.ui_state_manager.set_page_selection(valid_pages)
            self.ui_state_manager.active_page_uid = active_page
            self.project_data.select_pages(valid_pages)
            self._sidebar.load_takeoff_sidebar_from_memory(
                selected, self._bid_data_cache
            )
            if active_page:
                self._update_page_settings_bar(active_page)
                self._update_plan_view(active_page)
            else:
                self._viewer.clear_viewer()
        if "layers" in changed_families and self._sidebar.bid_layers_sidebar:
            self._sidebar.bid_layers_sidebar.load_layers(
                self.project_data.get_bid_layer_snapshot(),
                used_uids=self.project_data.get_layer_uids_in_use(),
            )
            self._sidebar.refresh_conditions_from_memory()
            self._update_plan_view_for_active()
        self._update_export_menu_state()
        self._restore_project_tree_bid_selection_if_needed()

    def _on_annotations_changed(
        self,
        page_uid: str = "",
        annotation_uids: Optional[List[str]] = None,
        annotation_types: Optional[List[str]] = None,
        update_shell: bool = True,
    ) -> None:
        self._update_plan_view_annotations(
            page_uid,
            annotation_uids=annotation_uids,
            annotation_types=annotation_types,
        )
        if update_shell:
            self._update_export_menu_state()
            self._restore_project_tree_bid_selection_if_needed()

    def _on_remote_conditions_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        condition_uids: Optional[List[str]] = None,
    ) -> None:
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid):
            return
        if self._undo_service:
            self._undo_service.clear()
        valid_highlights = self._validate_condition_uids(
            self.ui_state_manager.highlighted_condition_uids
        )
        self.ui_state_manager.highlighted_condition_uids = valid_highlights
        self._sidebar.refresh_conditions_from_memory()
        self.highlight_sidebar(valid_highlights, reveal=False)
        self._update_plan_view_for_active(condition_uids=condition_uids)
        self._update_export_menu_state()

    def _on_remote_areas_changed(
        self,
        database_id: str = "",
        bid_uid: str = "",
        area_uids: Optional[List[str]] = None,
    ) -> None:
        del area_uids
        selected = self.ui_state_manager.get_selected_bid_ref()
        if selected != BidRef(database_id, bid_uid) or not self._page_settings_bar:
            return
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
        if self._is_summary_tab_active():
            self._sidebar.load_condition_summary_from_memory()

    def _on_collaboration_state_changed(
        self,
        database_id: str = "",
        state: str = "",
        message: str = "",
    ) -> None:
        selected = self.ui_state_manager.selected_file_path or ""
        if self._status_panel and database_id == selected:
            self._status_panel.set_collaboration_state(state, message)
        self.ui_access_manager.refresh()
        self._update_export_menu_state()

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

    def _on_full_reconciliation_required(
        self, database_id: str = "", reason: str = ""
    ) -> None:
        if database_id != self.project_data.get_current_file_path():
            return
        if not self._flush_deferred_for_file(database_id):
            return
        if self.project_operations.reload_database(database_id):
            self.event_bus.publish(AppEvents.DATABASE_REFRESHED, file_path=database_id)
            return
        show_warning(
            self.main_window,
            "SQL Synchronization",
            reason or "The SQL database could not be reconciled safely.",
        )

    def _on_remote_hierarchy_changed(self, database_id: str = "") -> None:
        active_bid = self.project_data.get_current_bid_ref()
        self._do_file_refresh()
        if active_bid is None or active_bid.file_path != database_id:
            return
        if self.project_data.get_bid(active_bid) is not None:
            self.main_window.project_view.restore_bid_selection(active_bid)
            return
        self._on_file_selected(database_id, is_database_root=True)
        self.main_window.project_view.restore_file_selection(database_id)

    def _on_synchronization_conflict(
        self,
        database_id: str = "",
        resource_type: str = "",
        resource_id: str = "",
        bid_uid: str = "",
        message: str = "",
        blocks_database: bool = True,
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
            )
        show_warning(
            self.main_window,
            "SQL Edit Conflict",
            message
            or f"{resource_type} {resource_id} changed in another session. "
            "Reload the database before saving again.",
        )

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
                self.main_window.project_view.restore_file_selection(
                    snap.selected_file_path or snap.bid_ref.file_path
                )
                self._set_takeoff_tab_visible(False)
                self._nav.finish_refresh(
                    NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
                )
                self.ui_access_manager.refresh()
                self._toolbar.refresh()
                self._update_export_menu_state()
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
                page_uids=snap.page_uids,
                placement_active=False,
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
                    snap.project_uid
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
        self._update_export_menu_state()
        self.main_window.refresh_window_title()

    def _validate_condition_uids(self, uids: set) -> set:
        if not uids:
            return set()
        conditions = self.project_data.get_bid_conditions()
        return {uid for uid in uids if uid in conditions}

    def _on_file_unloaded(
        self, file_path: str = "", active_context_removed: bool = True
    ) -> None:
        removed_path = file_path or ""
        selected_path = self.ui_state_manager.selected_file_path
        if removed_path and selected_path:
            active_context_removed = active_context_removed or (
                normalize_path(removed_path) == normalize_path(selected_path)
            )
        if not active_context_removed:
            self._refresh_project_tree_after_file_unload()
            self.ui_access_manager.refresh()
            self._update_export_menu_state()
            return
        self._placement.force_exit()
        self.ui_state_manager.reset_selections()
        self.ui_state_manager.set_database_selected(False)
        self._sync_undo_bid()
        self.ui_access_manager.refresh()
        self.project_data.clear_page_selection()
        self._reset_takeoff_workspace_state()
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        self._set_takeoff_tab_visible(False)
        self._refresh_project_tree_after_file_unload()
        self._update_export_menu_state()
        if self._status_panel:
            self._status_panel.set_collaboration_state("stopped")
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
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        self._update_export_menu_state()
        if self._status_panel and file_path:
            collaboration_status = self._sql_collaboration.status(file_path)
            self._status_panel.set_collaboration_state(
                collaboration_status.state.value,
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
        self._sidebar.load_conditions_sidebar()
        self._load_condition_summary()
        if prev_highlighted and self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(prev_highlighted)
        if self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            selected_pages = self.project_data.get_selected_page_uids()
            self._request_or_defer_mesh_refresh(selected_pages)
            self._update_plan_view_for_active()

    def _on_license_status_changed(self, has_license: bool) -> None:
        self._viewer.update_license_visualization_state()
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._clear_mesh_replay_buffer()
            if self._mesh_window:
                self._mesh_window.clear_scene()
        self._toolbar.refresh()
        self.ensure_select_mode()

    def _on_native_scene_updated(
        self, geometries: List[MeshGeometry], bounds: tuple | None = None
    ) -> None:
        if self._nav.is_refreshing:
            return
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._last_mesh_args = None
            self._last_mesh_options = None
            self._clear_mesh_dirty_state()
            if self.opengl_viewer:
                self.opengl_viewer.clear_scene()
            if self._mesh_window:
                self._mesh_window.clear_scene()
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        (
            vertices,
            normals,
            indices,
            colors,
            condition_uids,
            takeoff_uids,
        ) = _mesh_geometries_to_render_buffers(geometries)
        mesh_args = (vertices, normals, indices, colors)
        mesh_options = {
            "bid_ref": bid_ref,
            "condition_uids": condition_uids,
            "takeoff_uids": takeoff_uids,
        }
        if bounds is not None:
            mesh_options["scene_bounds"] = bounds
        self._last_mesh_args = mesh_args
        self._last_mesh_options = mesh_options
        if self._pending_dirty_mesh_refresh:
            self._clear_mesh_dirty_state()
        live_embedded = self._is_embedded_3d_active()
        live_detached = self._is_detached_mesh_visible()
        if live_embedded and self.opengl_viewer:
            self.opengl_viewer.apply_mesh_data(*mesh_args, **mesh_options)
        if live_detached and self._mesh_window:
            self._mesh_window.apply_mesh_data(*mesh_args, **mesh_options)
        selected_pages = self.project_data.get_selected_page_uids()
        if selected_pages and (live_embedded or live_detached):
            self._plan_view_signaler.request_update()

    def handle_bid_selection(
        self, bid_ref: Optional[BidRef], force: bool = False
    ) -> None:
        prev_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref and prev_bid_ref and bid_ref == prev_bid_ref and not force:
            return
        self._save_current_page_view_state()
        if prev_bid_ref and (
            bid_ref is None or bid_ref.file_path != prev_bid_ref.file_path
        ):
            self._sql_collaboration.update_presence(prev_bid_ref.file_path, None, None)
        if not bid_ref:
            self._placement.force_exit()
            self.ui_state_manager.set_bid_selection(None)
            self.ui_state_manager.set_database_selected(False)
            self.ui_state_manager.set_file_path(None)
            self.project_data.clear_bid()
            self._sync_undo_bid()
            self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
            self.ui_access_manager.refresh()
            self.project_data.deselect_pages()
            self._reset_takeoff_workspace_state()
            self._viewer.clear_viewer()
            self._clear_mesh_views_for_scene_update(clear_embedded=False)
            self.visualization_service.refresh_mesh_view([])
            self._set_takeoff_tab_visible(False)
            self._update_export_menu_state()
            self.main_window.refresh_window_title()
            return
        prev_current_file_path = self.project_data.get_current_file_path()
        self.project_data.set_current_file(bid_ref.file_path)
        load_success = self.project_operations.load_bid(bid_ref)
        if not load_success:
            if prev_current_file_path:
                self.project_data.set_current_file(prev_current_file_path)
            elif prev_bid_ref:
                self.project_data.set_current_file(prev_bid_ref.file_path)
            self.ui_access_manager.refresh()
            self._update_export_menu_state()
            self._restore_project_tree_bid_selection_if_needed()
            return
        self._placement.force_exit()
        self.ensure_select_mode()
        self.ui_state_manager.set_bid_selection(bid_ref)
        self._sql_collaboration.update_presence(
            bid_ref.file_path, bid_ref.bid_uid, None
        )
        self._sync_undo_bid()
        self.project_data.deselect_pages()
        self.ui_state_manager.set_page_selection([])
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        self._resolve_bid_lock_state(bid_ref)
        self._reset_takeoff_workspace_state()
        self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        self.ui_access_manager.refresh()
        self._update_export_menu_state()
        self.main_window.refresh_window_title()
        self._set_takeoff_tab_visible(True)
        if self._tab_widget and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            self._activate_takeoff_workspace()

    def handle_page_selection(self, page_uids: List[str]) -> None:
        if self._nav.is_refreshing:
            return
        if not self.ui_state_manager.get_selected_bid_ref():
            if self.ui_state_manager.selected_page_uids:
                self._update_page_selection([])
            return
        selected = self._update_page_selection(page_uids)
        if self._nav.current_state == NavState.FILE_LOADED_NO_BID:
            self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        if selected:
            self._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        else:
            self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)

    def handle_active_page_changed(self, active_uid: Optional[str]) -> None:
        if self._nav.is_refreshing:
            return
        self._save_current_page_view_state(selected_page_override=active_uid)
        self.ui_state_manager.active_page_uid = active_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
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
            if self.plan_view:
                self.plan_view.clear()
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
        self._update_page_info_status()
        self._update_export_menu_state()

    def _clear_page_info_status(self) -> None:
        if self._status_panel:
            self._status_panel.set_page_info("")

    def _update_page_info_status(self) -> None:
        if not self._status_panel:
            return
        selected = self.ui_state_manager.selected_page_uids
        if not selected:
            self._clear_page_info_status()
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

    def _update_page_selection(self, page_uids: List[str]) -> List[str]:
        previous = list(self.ui_state_manager.selected_page_uids)
        selected = self.project_data.select_pages(page_uids)
        self.ui_state_manager.set_page_selection(selected)
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            if not selected:
                self._clear_mesh_views_for_scene_update()
            elif selected != previous:
                self._clear_mesh_replay_buffer()
            self._request_or_defer_mesh_refresh(selected)
        self._sidebar.update_conditions_quantities()
        self._update_export_menu_state()
        self._update_page_info_status()
        return selected

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
        if self._bid_data_cache:
            self.visualization_service.start_database_monitoring()
        else:
            self.visualization_service.stop_database_monitoring()

    def _save_current_page_view_state(
        self, selected_page_override: Optional[str] = None
    ) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        active_page_uid = self.ui_state_manager.active_page_uid
        page_uid = self.plan_view.current_page_uid if self.plan_view else None
        can_persist = self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS)
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
                        bid_ref.file_path, page_uid, zoom_fac, cx, cy
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
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.deleteLater()

    def _save_image_adjustments(
        self, file_path: str, page_uid: str, settings: ImageAdjustmentSettings
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        page_uids = [page_uid]
        if settings.apply_to_all_pages:
            if not self.takeoff_sidebar:
                return False
            page_uids = [
                uid
                for uid in self.takeoff_sidebar.get_page_order()
                if uid and self.project_data.get_page(uid)
            ]
        if not page_uids:
            return False
        if not self._flush_deferred_for_file(file_path):
            return False
        return self._project_write_service.save_page_image_adjustments(
            file_path,
            page_uids,
            settings.rotation,
            settings.flip_x,
            settings.flip_y,
            settings.invert,
            settings.bitonal,
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
        dialog = SetScaleDialog(
            self._icon_provider,
            self.main_window,
            page.scale_factor1,
            page.scale_factor2,
            save_fn=lambda settings: self._save_scale_settings(
                file_path, page_uid, settings
            ),
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.deleteLater()

    def _save_scale_settings(
        self, file_path: str, page_uid: str, settings: ScaleSettings
    ) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return False
        page_uids = [page_uid]
        if settings.apply_to_all_pages:
            if not self.takeoff_sidebar:
                return False
            page_uids = [
                uid
                for uid in self.takeoff_sidebar.get_page_order()
                if uid and self.project_data.get_page(uid)
            ]
        if not page_uids:
            return False
        if not self._flush_deferred_for_file(file_path):
            return False
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
        dialog = RenamePageDialog(
            self._icon_provider,
            self.main_window,
            pages,
            page_uid,
            save_fn=lambda target_page_uid, new_name: self._save_page_name(
                bid_ref.file_path, target_page_uid, new_name
            ),
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.deleteLater()

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
        return self._project_write_service.save_page_name(file_path, page_uid, new_name)

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
        pages_with_content = self._project_read_service.get_pages_with_delete_content(
            bid_ref.file_path, bid_ref.bid_uid
        )
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
        if not self._project_write_service.delete_pages(bid_ref.file_path, [page_uid]):
            self._clear_staged_takeoff_restore()
            show_critical(
                self.main_window,
                "Delete Page",
                f"Failed to delete page. {DB_LOCKED_HINT}",
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
        if not page.overlay_image_path and (
            target == "overlay" or (target == "original" and not checked)
        ):
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
        self._project_write_service.save_page_overlay_image(
            file_path, page_uid, overlay_image_path
        )

    def _on_page_area_changed(
        self, file_path: str, page_uid: str, area_uid: str
    ) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        page_area_selections = self.project_data.get_page_area_selections()
        page_area_selections[page_uid] = area_uid if area_uid else None
        self.ui_state_manager.selected_area_uid = area_uid or ""
        self._deferred_persistence.schedule_page_area_selection(
            file_path, page_uid, area_uid or ""
        )
        if page_uid == self.ui_state_manager.active_page_uid:
            self._viewer.update_plan_view(page_uid)
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
        self._save_current_page_view_state(selected_page_override=page_uid)
        if page:
            page.image_show_mode = show_mode
        self._deferred_persistence.schedule_page_show_mode(
            bid_ref.file_path, page_uid, show_mode
        )
        self._sync_overlay_display_mode(page_uid)
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)
        self._update_export_menu_state()

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
        write_fn(page, value)
        if flag_name == "invert":
            self._deferred_persistence.schedule_page_invert(
                bid_ref.file_path, page_uid, value
            )
        elif flag_name == "bitonal":
            self._deferred_persistence.schedule_page_bitonal(
                bid_ref.file_path, page_uid, value
            )
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)
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
        image_layer = self.project_data.is_image_layer_uid(layer_uid)
        condition_layer = self._layer_has_condition_rows(layer_uid)
        if not show and not image_layer:
            self._suspend_active_layer_tool(layer_uid)
        changed_page_uids = self.project_data.update_layer_visibility(layer_uid, show)
        if image_layer:
            self._update_native_page_visibility()
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
        self._deferred_persistence.schedule_layer_show(
            bid_ref.file_path, layer_uid, show
        )
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
        self._toolbar.refresh()
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

    def _on_layer_deleted(self, layer_uid: str) -> None:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        if not self._flush_deferred_for_file(bid_ref.file_path):
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
        if self._sidebar.bid_layers_sidebar:
            layers = self._sidebar.bid_layers_sidebar.get_layers()
            self._sidebar.bid_layers_sidebar.set_all_layers_visible(show)
        else:
            layers = self._project_read_service.get_merged_bid_layers(
                bid_ref.file_path, bid_ref.bid_uid
            )
        if not show:
            self._suspend_active_layer_tool()
        self.project_data.set_bid_layer_visibility(layers)
        changed_page_uids = self.project_data.update_all_layer_visibility(show)
        self._update_native_page_visibility()
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
                bid_ref.file_path, layer.uid, show
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
        self._toolbar.refresh()
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
        success = False
        if not self._flush_deferred_for_file(bid_ref.file_path):
            self._sidebar.load_bid_layers_sidebar()
            return
        try:
            success = bool(
                write_svc.update_layer_name(bid_ref.file_path, layer_uid, new_name)
            )
        except Exception:
            logger.warning("Failed to rename layer", exc_info=True)
        if not success:
            self._sidebar.load_bid_layers_sidebar()
