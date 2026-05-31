import logging
from typing import Dict, List, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QObject, Signal
from ...application.events.app_events import AppEvents
from ...domain.entities.bid import Bid
from ...domain.entities.file_state import normalize_path
from ...domain.entities.identity_refs import BidRef
from ...domain.entities.loaded_file import LoadedFile
from ...domain.entities.named_view import NamedView, build_named_view_from_annotation
from ...domain.entities.project_factory import build_loaded_files
from ..config import TAB_INDEX_PROJECTS, TAB_INDEX_TAKEOFF
from ..dialogs.adjust_images_dialog import AdjustImagesDialog, ImageAdjustmentSettings
from ..dialogs.areas_dialog import BidAreasDialog
from ..dialogs.condition_types_dialog import ConditionTypesDialog
from ..dialogs.employees_dialog import EmployeesDialog
from ..dialogs.job_statuses_dialog import JobStatusesDialog
from ..dialogs.payroll_class_dialog import PayrollClassListDialog
from ..dialogs.rename_page_dialog import PageRenameTarget, RenamePageDialog
from ..dialogs.set_scale_dialog import ScaleSettings, SetScaleDialog
from ..handlers.condition_action_handler import ConditionActionHandler
from ..managers.app_config_presentation_manager import AppConfigPresentationManager
from ..managers.ui_access_manager import Feature
from ..resolvers.entity_resolver import EntityResolver
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
        self.conditions_sidebar = None
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
        self._resolver = EntityResolver(None, self.project_data)
        self._mesh_window: Optional[MeshViewWindow] = None
        self._mesh_window_action: Optional[QtGui.QAction] = None
        self._last_mesh_args: Optional[tuple] = None
        self._last_mesh_kwargs: Optional[dict] = None
        self._plan_view_handler = None
        self._takeoff_workspace_bid_ref: Optional[BidRef] = None
        self._pending_takeoff_page_uids: Optional[List[str]] = None
        self._pending_takeoff_active_page_uid: Optional[str] = None
        self._pending_takeoff_selected_area_uid: str = ""
        self._pending_takeoff_place_condition_uid: Optional[str] = None
        self._pending_takeoff_place_condition_uids: List[str] = []
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
        self._toolbar.refresh()

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

    def set_dimension_action(self, action: QtGui.QAction) -> None:
        self._toolbar.set_dimension_action(action)
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
        self._sidebar.update_conditions_quantities()
        if index == 1 and self.plan_view:
            self.plan_view.reset_ctrl_held()
        self._update_page_info_status()
        self._toolbar.refresh()

    def set_opengl_viewer(self, viewer) -> None:
        self.opengl_viewer = viewer
        self._viewer.opengl_viewer = viewer
        self._toolbar.opengl_viewer = viewer
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
            self._sync_overlay_display_mode(self.ui_state_manager.active_page_uid)
            self._sync_mesh_window_action(True)
            window.show_initial_window()
            self._replay_mesh_if_current(window)
            return
        if self._mesh_window is None:
            self._sync_mesh_window_action(False)
            return
        self._mesh_window.close()

    def _replay_mesh_if_current(self, window: MeshViewWindow) -> None:
        if not self._last_mesh_args or not self._last_mesh_kwargs:
            return
        active_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        cached_bid_ref = self._last_mesh_kwargs.get("bid_ref")
        if cached_bid_ref != active_bid_ref:
            logger.warning(
                "Discarding stale mesh replay: cached bid_ref=%s, active bid_ref=%s",
                cached_bid_ref,
                active_bid_ref,
            )
            self._last_mesh_args = None
            self._last_mesh_kwargs = None
            return
        window.apply_mesh_data(*self._last_mesh_args, **self._last_mesh_kwargs)

    def _clear_mesh_replay_buffer(self) -> None:
        self._last_mesh_args = None
        self._last_mesh_kwargs = None

    def _clear_mesh_views_for_scene_update(self, clear_embedded: bool = True) -> None:
        self._clear_mesh_replay_buffer()
        if clear_embedded and self.opengl_viewer:
            self.opengl_viewer.clear_scene()
        if self._mesh_window:
            self._mesh_window.clear_scene()

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
        self._resolver.set_plan_view(view)
        self._viewer.plan_view = view
        self._toolbar.set_plan_view(view)
        view.takeoff_selection_changed.connect(self._on_takeoff_selection_changed)
        view.backout_mode_changed.connect(self._on_backout_mode_changed)
        view.clipboard_changed.connect(self._toolbar.refresh)
        view.text_annotation_edit_mode_changed.connect(
            self._on_text_annotation_edit_mode_changed
        )
        view.page_fully_loaded.connect(self._on_plan_view_page_fully_loaded)
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
        if not visible and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            self._tab_widget.setCurrentIndex(TAB_INDEX_PROJECTS)

    def _clear_staged_takeoff_restore(self) -> None:
        self._pending_takeoff_page_uids = None
        self._pending_takeoff_active_page_uid = None
        self._pending_takeoff_selected_area_uid = ""
        self._pending_takeoff_place_condition_uid = None
        self._pending_takeoff_place_condition_uids = []

    def _reset_takeoff_workspace_state(self) -> None:
        self._takeoff_workspace_bid_ref = None
        self._clear_staged_takeoff_restore()
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
            self._load_takeoff_sidebar(bid_ref)
            self._sidebar.load_bid_layers_sidebar()
            self._sidebar.load_conditions_sidebar()
            highlighted = self._validate_condition_uids(
                self.ui_state_manager.highlighted_condition_uids
            )
            self.highlight_sidebar(highlighted)
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
                self._placement.enter(
                    self._pending_takeoff_place_condition_uid,
                    self._pending_takeoff_place_condition_uids,
                )
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

    def highlight_sidebar(self, uids: set) -> None:
        if self._nav.is_refreshing:
            return
        self.ui_state_manager.set_highlighted_conditions(uids)
        if self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(uids)

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
        if takeoff_uids:
            cond_uids = self._takeoff_uids_to_condition_uids(takeoff_uids)
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
        self._subscribe(AppEvents.TAKEOFFS_CHANGED, self._on_takeoffs_changed)
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
        self._sidebar.refresh_conditions_ui()

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

        def save_fn(changes) -> dict:
            if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
                return {}
            return (
                self._project_write_service.save_bid_areas(
                    bid_ref.file_path, bid_ref.bid_uid, changes
                )
                or {}
            )

        def on_saved() -> None:
            if self._page_settings_bar:
                self._page_settings_bar.load_bid_areas(
                    bid_ref,
                    areas_with_takeoff=self.project_data.get_area_uids_with_takeoff(),
                    selected_uid=self.ui_state_manager.selected_area_uid or None,
                )

        dialog = BidAreasDialog(
            self._icon_provider,
            parent=self.main_window,
            bid_areas=areas,
            save_fn=save_fn,
            used_uids=used_uids,
            on_saved_fn=on_saved,
            has_license=True,
            bid_ref=bid_ref,
        )
        try:
            exec_with_ost_blocking(dialog, self.event_bus)
        finally:
            dialog.cleanup()
            dialog.deleteLater()

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
            save_fn=lambda changes: self._save_master_employees(file_path, changes),
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
            used_uids=self._project_read_service.get_condition_type_uids_in_use(
                file_path
            ),
            save_fn=lambda changes: self._save_master_condition_types(
                file_path, changes
            ),
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

    def _save_master_employees(self, file_path: str, changes) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.save_employees(file_path, changes)

    def _save_master_job_statuses(self, file_path: str, changes) -> bool:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return False
        return self._project_write_service.save_job_statuses(file_path, changes)

    def _save_master_pay_classes(self, file_path: str, changes) -> dict:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return {}
        return self._project_write_service.save_pay_classes(file_path, changes) or {}

    def _save_master_condition_types(self, file_path: str, changes) -> dict:
        if not self.ui_access_manager.is_allowed(Feature.EDIT_MASTER_DATA):
            return {}
        return (
            self._project_write_service.save_condition_types(file_path, changes) or {}
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
        if self.plan_view:
            self.plan_view.reset_ctrl_held()
            self.plan_view.set_cursor_mode("select")
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
            self.plan_view.reset_ctrl_held()
            self.plan_view.set_cursor_mode("select")

    def _on_ost_status_changed(self, **_) -> None:
        self.ensure_select_mode()
        self._menu_state_signaler.request_update()

    def cleanup(self) -> None:
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
        self._resolver = None
        self.project_data = None
        self.project_operations = None
        self.visualization_service = None
        self._color_service = None
        self._icon_provider = None
        self._project_write_service = None
        self._project_read_service = None
        self.takeoff_sidebar = None
        self.conditions_sidebar = None
        self.opengl_viewer = None
        self.plan_view = None
        self._condition_handler = None

    def flush_current_page_state(self) -> None:
        self._save_current_page_view_state()

    def _on_file_opened(self, **kwargs) -> None:
        self._save_current_page_view_state()
        self._placement.force_exit()
        self._sync_undo_bid()
        self.ui_state_manager.reset_selections()
        self.main_window.project_view.set_selected_node_state(None)
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.ui_access_manager.refresh()
        self._viewer.clear_viewer()
        self._set_takeoff_tab_visible(False)
        self._rebuild_ui_after_file_load()
        self._update_export_menu_state()

    def _on_database_refreshed(self, **kwargs) -> None:
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

    def _on_takeoffs_changed(self, **kwargs) -> None:
        page_uid = kwargs.get("page_uid") or self.ui_state_manager.active_page_uid
        if page_uid:
            self._refresh_takeoff_dependent_page_controls(page_uid)
        if page_uid:
            self._update_plan_view(page_uid)
        else:
            self._update_plan_view_for_active()
        self._viewer.update_viewers(self.project_data.get_selected_page_uids())
        self._update_export_menu_state()
        self._restore_project_tree_bid_selection_if_needed()

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
            return
        has_file = bool(self.project_data.get_current_file_path())
        if snap.bid_ref:
            self.main_window.project_view.restore_bid_selection(snap.bid_ref)
            self._resolve_bid_lock_state(snap.bid_ref)
            self._reset_takeoff_workspace_state()
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
        elif snap.project_uid:
            self._reset_takeoff_workspace_state()
            self.main_window.project_view.restore_project_selection(
                snap.project_uid,
                snap.selected_file_path,
            )
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        elif snap.database_selected and snap.selected_file_path:
            self._reset_takeoff_workspace_state()
            self.main_window.project_view.restore_file_selection(
                snap.selected_file_path
            )
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        else:
            self._reset_takeoff_workspace_state()
            self._nav.finish_refresh(
                NavState.FILE_LOADED_NO_BID if has_file else NavState.NO_FILE
            )
        self.ui_access_manager.refresh()
        self._update_export_menu_state()

    def _validate_condition_uids(self, uids: set) -> set:
        if not uids:
            return set()
        conditions = self.project_data.get_bid_conditions()
        return {uid for uid in uids if uid in conditions}

    def _on_file_unloaded(self, **kwargs) -> None:
        removed_path = kwargs.get("file_path") or ""
        active_context_removed = kwargs.get("active_context_removed", True)
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
        self._save_current_page_view_state()
        self._placement.force_exit()
        self._sync_undo_bid()
        self.ui_state_manager.reset_selections()
        self.ui_state_manager.set_database_selected(False)
        self.ui_access_manager.refresh()
        self.project_data.clear_page_selection()
        self._reset_takeoff_workspace_state()
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        self._set_takeoff_tab_visible(False)
        self._refresh_project_tree_after_file_unload()
        self._update_export_menu_state()

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

    def _on_file_selected(self, **kwargs) -> None:
        file_path = kwargs.get("file_path")
        is_database_root = kwargs.get("is_database_root", False)
        project_uid = kwargs.get("project_uid")
        self._save_current_page_view_state()
        self._placement.force_exit()
        self._sync_undo_bid()
        self.ui_state_manager.reset_selections()
        self.ui_state_manager.set_database_selected(is_database_root, file_path)
        self.ui_state_manager.set_project_uid(project_uid)
        self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
        self.ui_access_manager.refresh()
        self.project_data.deselect_pages()
        self._reset_takeoff_workspace_state()
        self._set_takeoff_tab_visible(False)
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        self._update_export_menu_state()

    def _on_app_config_updated(self, **kwargs) -> None:
        self.ui_state_manager.sync_from_config()
        needs_condition_display_refresh = (
            self._app_config_presentation.apply_updated_options(
                self.main_window,
                self.main_window._config_model,
                kwargs["value"],
            )
        )
        self.main_window.menu_controller.update_menu_states()
        if needs_condition_display_refresh:
            self._refresh_condition_display_after_app_config_change()

    def _refresh_condition_display_after_app_config_change(self) -> None:
        prev_highlighted = set(self.ui_state_manager.highlighted_condition_uids)
        self._sidebar.load_conditions_sidebar()
        if prev_highlighted and self.conditions_sidebar:
            self.conditions_sidebar.highlight_conditions(prev_highlighted)
        if self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            selected_pages = self.project_data.get_selected_page_uids()
            self._viewer.update_viewers(selected_pages)
            self._update_plan_view_for_active()

    def _on_license_status_changed(self, **_) -> None:
        self._viewer.update_license_visualization_state()
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._clear_mesh_replay_buffer()
            if self._mesh_window:
                self._mesh_window.clear_scene()
        self._toolbar.refresh()
        self.ensure_select_mode()

    def _on_native_scene_updated(self, **kwargs) -> None:
        if self._nav.is_refreshing:
            return
        if not self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            self._last_mesh_args = None
            self._last_mesh_kwargs = None
            if self.opengl_viewer:
                self.opengl_viewer.clear_scene()
            if self._mesh_window:
                self._mesh_window.clear_scene()
            return
        geometries = kwargs.get("geometries") or []
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        mesh_args = (
            [g.get("vertices", []) for g in geometries],
            [g.get("normals", []) for g in geometries],
            [g.get("faces", []) for g in geometries],
            [
                {
                    "color": g.get("color", "#808080"),
                    "opacity": g.get("opacity", 1.0),
                }
                for g in geometries
            ],
        )
        mesh_kwargs = {
            "bid_ref": bid_ref,
            "condition_uids": [g.get("condition_uid", "") for g in geometries],
            "takeoff_uids": [g.get("takeoff_uid", "") for g in geometries],
        }
        self._last_mesh_args = mesh_args
        self._last_mesh_kwargs = mesh_kwargs
        if self.opengl_viewer:
            self.opengl_viewer.apply_mesh_data(*mesh_args, **mesh_kwargs)
        if self._mesh_window:
            self._mesh_window.apply_mesh_data(*mesh_args, **mesh_kwargs)
        selected_pages = self.project_data.get_selected_page_uids()
        if selected_pages:
            self._plan_view_signaler.request_update()

    def handle_bid_selection(self, bid_ref: Optional[BidRef]) -> None:
        prev_bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if bid_ref and prev_bid_ref and bid_ref == prev_bid_ref:
            return
        self._save_current_page_view_state()
        if not bid_ref:
            self._placement.force_exit()
            self._sync_undo_bid()
            self.ui_state_manager.set_bid_selection(None)
            self.ui_state_manager.set_database_selected(False)
            self.ui_state_manager.set_file_path(None)
            self._nav.transition_to(NavState.FILE_LOADED_NO_BID)
            self.ui_access_manager.refresh()
            self.project_data.deselect_pages()
            self._reset_takeoff_workspace_state()
            self._viewer.clear_viewer()
            self._clear_mesh_views_for_scene_update(clear_embedded=False)
            self.visualization_service.refresh_mesh_view([])
            self._set_takeoff_tab_visible(False)
            self._update_export_menu_state()
            return
        self.project_data.set_current_file(bid_ref.file_path)
        self._placement.force_exit()
        self.ensure_select_mode()
        self.ui_state_manager.set_bid_selection(bid_ref)
        self._sync_undo_bid()
        self.project_data.deselect_pages()
        self.ui_state_manager.set_page_selection([])
        self._viewer.clear_viewer()
        self._clear_mesh_views_for_scene_update(clear_embedded=False)
        self.visualization_service.refresh_mesh_view([])
        load_success = self.project_operations.load_bid(bid_ref)
        if not load_success:
            self.ui_state_manager.set_bid_selection(prev_bid_ref)
            self.ui_access_manager.refresh()
            self._update_export_menu_state()
            return
        self._resolve_bid_lock_state(bid_ref)
        self._reset_takeoff_workspace_state()
        self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)
        self.ui_access_manager.refresh()
        self._update_export_menu_state()
        self._set_takeoff_tab_visible(True)
        if self._tab_widget and self._tab_widget.currentIndex() == TAB_INDEX_TAKEOFF:
            self._activate_takeoff_workspace()

    def handle_page_selection(self, page_uids: List[str]) -> None:
        if self._nav.is_refreshing:
            return
        self._update_page_selection(page_uids)
        if page_uids:
            self._nav.transition_to(NavState.BID_ACTIVE_PAGES_SELECTED)
        else:
            self._nav.transition_to(NavState.BID_ACTIVE_NO_PAGES)

    def handle_active_page_changed(self, active_uid: Optional[str]) -> None:
        if self._nav.is_refreshing:
            return
        self._save_current_page_view_state(selected_page_override=active_uid)
        self.ui_state_manager.active_page_uid = active_uid
        if active_uid:
            self._update_page_settings_bar(active_uid)
            self._sync_overlay_display_mode(active_uid)
        if active_uid and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(active_uid)
        else:
            if self.plan_view:
                self.plan_view.clear()
            self._sidebar.update_conditions_quantities()
        if self._placement.is_active and self.plan_view is not None:
            assert self.plan_view._cursor_mode == "place", (
                "placement is active but plan view cursor is "
                f"{self.plan_view._cursor_mode!r} after page change"
            )
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
        self.ui_state_manager.selected_area_uid = selected_area or ""
        areas_for_page = self.project_data.get_area_uids_with_takeoff_for_page(page_uid)
        self._page_settings_bar.load_page(
            page_uid,
            page.scale_factor1,
            page.scale_factor2,
            selected_area,
            areas_with_takeoff=areas_for_page,
        )

    def _update_page_selection(self, page_uids: List[str]) -> None:
        previous = list(self.ui_state_manager.selected_page_uids)
        selected = self.project_data.select_pages(page_uids)
        self.ui_state_manager.set_page_selection(selected)
        if self.ui_access_manager.is_allowed(Feature.VIEW_3D):
            if not selected:
                self._clear_mesh_views_for_scene_update()
            elif selected != previous:
                self._clear_mesh_replay_buffer()
            self.visualization_service.refresh_mesh_view(selected)
        self._update_export_menu_state()
        self._update_page_info_status()

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
        write_svc = self._project_write_service
        active_page_uid = self.ui_state_manager.active_page_uid
        page_uid = self.plan_view.current_page_uid if self.plan_view else None
        if page_uid and self.plan_view.is_view_state_stable:
            zoom_fac, cx, cy = self.plan_view.get_view_state()
            if zoom_fac > 0:
                page = self.project_data.get_page(page_uid)
                if page:
                    page.zoom_fac = zoom_fac
                    page.current_x = cx
                    page.current_y = cy
                write_svc.save_page_view_state(
                    bid_ref.file_path, page_uid, zoom_fac, cx, cy
                )
        page_to_save = selected_page_override or page_uid or active_page_uid
        if page_to_save:
            write_svc.save_bid_selected_page(
                bid_ref.file_path, bid_ref.bid_uid, page_to_save
            )

    def _sync_overlay_display_mode(self, page_uid: Optional[str]) -> None:
        if not page_uid:
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        mode = page.image_show_mode
        if self.plan_view and self.plan_view.current_page_uid == page_uid:
            self.plan_view.set_overlay_display_mode(mode)
        if self.opengl_viewer:
            self.opengl_viewer.set_overlay_display_mode(mode)
        if self._mesh_window:
            self._mesh_window.set_overlay_display_mode(mode)

    def _load_takeoff_sidebar(self, bid_ref: BidRef) -> None:
        self._sidebar.load_takeoff_sidebar(bid_ref, self._bid_data_cache)

    def _update_plan_view_for_active(self) -> None:
        self._viewer.update_plan_view_for_active()
        self._apply_pending_hotlink_named_view_focus(require_stable=True)
        self._sidebar.update_conditions_quantities()

    def _update_plan_view(self, page_uid: Optional[str]) -> None:
        self._viewer.update_plan_view(page_uid)
        self._apply_pending_hotlink_named_view_focus(require_stable=True)
        self._sidebar.update_conditions_quantities()

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
        if not self._is_condition_placeable(condition_uid):
            self._reset_to_select_mode()
            return
        self._placement.enter(condition_uid, selected)
        self._toolbar.refresh()

    def _check_takeoffs_all_negative(self, takeoff_uids: list) -> bool:
        if not takeoff_uids:
            return False
        for uid in takeoff_uids:
            t = self._resolver.resolve_takeoff(uid)
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
            t = self._resolver.resolve_takeoff(uid)
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
            self._resolver.resolve_takeoff,
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
        write_svc = self._project_write_service
        try:
            write_svc.save_page_scale(file_path, page_uid, sf1, sf2)
        except Exception:
            logger.warning("Failed to save page scale", exc_info=True)

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
        if not self.ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS):
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
        if not self._project_write_service.delete_pages(bid_ref.file_path, [page_uid]):
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
            return
        page = self.project_data.get_page(page_uid)
        if not page:
            return
        if not page.overlay_image_path and (
            target == "overlay" or (target == "original" and not checked)
        ):
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
        self._project_write_service.save_page_overlay_image(
            file_path, page_uid, overlay_image_path
        )

    def _on_page_area_changed(
        self, file_path: str, page_uid: str, area_uid: str
    ) -> None:
        self.ui_state_manager.selected_area_uid = area_uid
        write_svc = self._project_write_service
        try:
            write_svc.save_page_area(file_path, page_uid, area_uid)
        except Exception:
            logger.warning("Failed to save page area", exc_info=True)

    def _on_overlay_display_mode_requested(self, show_mode: int) -> None:
        if show_mode not in (SHOW_ORIGINAL, SHOW_OVERLAY, SHOW_BOTH):
            return
        page_uid = self.ui_state_manager.active_page_uid
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not page_uid or not bid_ref:
            return
        if not self.ui_access_manager.is_allowed(Feature.EDIT_PAGE_SETTINGS):
            return
        try:
            success = self._project_write_service.save_page_show_mode(
                bid_ref.file_path, page_uid, show_mode
            )
        except Exception:
            logger.warning("Failed to save page show mode", exc_info=True)
            return
        if not success:
            return
        page = self.project_data.get_page(page_uid)
        if page:
            page.image_show_mode = show_mode
        self._sync_overlay_display_mode(page_uid)
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)

    def toggle_page_invert(self, invert: bool) -> None:
        self._toggle_page_image_flag(
            lambda page: page.invert,
            self._set_page_invert,
            bool(invert),
            self._project_write_service.save_page_invert,
            "Failed to save page invert state",
        )

    def toggle_page_bitonal(self, bitonal: bool) -> None:
        self._toggle_page_image_flag(
            lambda page: page.bitonal,
            self._set_page_bitonal,
            bool(bitonal),
            self._project_write_service.save_page_bitonal,
            "Failed to save page bitonal state",
        )

    @staticmethod
    def _set_page_invert(page, value: bool) -> None:
        page.invert = value

    @staticmethod
    def _set_page_bitonal(page, value: bool) -> None:
        page.bitonal = value

    def _toggle_page_image_flag(
        self, read_fn, write_fn, value: bool, save_fn, failure_message: str
    ) -> None:
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
        previous = read_fn(page)
        write_fn(page, value)
        try:
            success = save_fn(bid_ref.file_path, page_uid, value)
        except Exception:
            logger.warning(failure_message, exc_info=True)
            success = False
        if not success:
            write_fn(page, previous)
            self._update_export_menu_state()
            return
        if self.plan_view and self.ui_access_manager.is_allowed(Feature.VIEW_2D):
            self._update_plan_view(page_uid)
        self._update_export_menu_state()

    def _on_layer_visibility_toggled(self, layer_uid: str, show: bool) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        try:
            write_svc.update_layer_show(bid_ref.file_path, layer_uid, show)
        except Exception:
            logger.warning("Failed to update layer visibility", exc_info=True)

    def _on_layer_added(self, name: str, after_sequence: int) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        sidebar = self._sidebar.bid_layers_sidebar
        if not sidebar:
            return
        try:
            new_uid = self._project_write_service.insert_layer(
                bid_ref.file_path, bid_ref.bid_uid, name, after_sequence
            )
            if new_uid:
                sidebar.set_pending_selection(new_uid)
        except Exception:
            logger.warning("Failed to insert layer", exc_info=True)

    def _on_layer_deleted(self, layer_uid: str) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        try:
            write_svc.delete_layer(bid_ref.file_path, layer_uid)
        except Exception:
            logger.warning("Failed to delete layer", exc_info=True)

    def _on_layers_show_all(self, show: bool) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        try:
            write_svc.update_all_layers_show(bid_ref.file_path, bid_ref.bid_uid, show)
        except Exception:
            logger.warning("Failed to update all layers visibility", exc_info=True)

    def _on_layer_moved(self, layer_uid: str, direction: int) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        sidebar = self._sidebar.bid_layers_sidebar
        if not sidebar:
            return
        neighbor_uid = sidebar.get_neighbor_uid(direction)
        if not neighbor_uid:
            return
        try:
            self._project_write_service.swap_layer_sequence(
                bid_ref.file_path, layer_uid, neighbor_uid
            )
        except Exception:
            logger.warning("Failed to move layer", exc_info=True)

    def _on_layer_renamed(self, layer_uid: str, new_name: str) -> None:
        bid_ref = self.ui_state_manager.get_selected_bid_ref()
        if not bid_ref:
            return
        write_svc = self._project_write_service
        try:
            write_svc.update_layer_name(bid_ref.file_path, layer_uid, new_name)
        except Exception:
            logger.warning("Failed to rename layer", exc_info=True)
