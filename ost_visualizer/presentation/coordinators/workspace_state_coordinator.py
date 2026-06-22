import logging
from typing import Callable, Dict, Optional, cast
from PySide6 import QtCore, QtWidgets
from ...application.dtos.condition_summary_dtos import ConditionSummaryGrouping
from ...domain.entities.workspace_state import (
    DetachedWindowState,
    ProjectTreeSelectionState,
    WorkspaceState,
)
from ..interfaces.i_workspace_shell import IWorkspaceShell


class WorkspaceStateCoordinator(QtCore.QObject):
    SAVE_DEBOUNCE_MS = 500
    MAIN_WINDOW_STATE_VERSION = 1
    _DETACHED_MESH = "mesh_view"
    _DETACHED_ANNOTATION = "annotation_view"
    _DETACHED_VIEW = "view_window"
    _DROPDOWN_POPUP_KEYS = {
        "main_page",
        "main_scale",
        "main_area",
        "annotation_page",
        "annotation_named_views",
        "view_page",
        "view_named_views",
    }

    def __init__(
        self, main_window: QtWidgets.QMainWindow, workspace_state_model, logger_=None
    ):
        super().__init__(main_window)
        self._host_window = main_window
        self._shell = cast(IWorkspaceShell, main_window)
        self._cleaned_up = False
        self.workspace_state_model = workspace_state_model
        self.logger = logger_ or logging.getLogger(__name__)
        self._state = workspace_state_model.state
        self._tracked_toolbars = tuple(self._shell.get_workspace_toolbars())
        self._tracked_headers = (
            self._shell.get_project_header(),
            self._shell.get_conditions_header(),
            self._shell.get_layers_header(),
        )
        self._tracked_detached_windows: Dict[str, QtWidgets.QWidget] = {}
        self._tracked_detached_destroy_callbacks: Dict[str, Callable] = {}
        self._detached_restore_applied: Dict[str, bool] = {}
        self._pending_mesh_restore = False
        self._pending_annotation_restore = False
        self._pending_view_restore = False
        self._takeoff_workspace_activation_complete = False
        self._takeoff_workspace_ready = False
        self._takeoff_workspace_ready_restore_scheduled = False
        self._pending_takeoff_splitter_sizes = list(
            self._state.takeoff_workspace.takeoff_splitter_sizes
        )
        self._pending_splitter_sizes = list(
            self._state.takeoff_workspace.left_splitter_sizes
        )
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._save_now)
        self._install_tracking()

    def _install_tracking(self) -> None:
        self._host_window.installEventFilter(self)
        for toolbar in self._tracked_toolbars:
            toolbar.installEventFilter(self)
        for header in self._tracked_headers:
            self._connect_header_tracking(header)
        self._shell.get_conditions_sidebar().group_by_type_changed.connect(
            self.request_save
        )
        self._shell.get_condition_summary_tab().summary_ui_state_changed.connect(
            self.request_save
        )
        self._shell.get_project_tree().itemExpanded.connect(self.request_save)
        self._shell.get_project_tree().itemCollapsed.connect(self.request_save)
        self._shell.get_project_tree().itemSelectionChanged.connect(self.request_save)
        self._shell.get_view_stack().currentChanged.connect(self.request_save)
        self._shell.get_takeoff_splitter().splitterMoved.connect(self.request_save)
        self._shell.get_left_splitter().splitterMoved.connect(self.request_save)
        self._shell.takeoff_sidebar.popup_size_changed.connect(
            self._on_dropdown_size_changed
        )
        self._shell.get_page_settings_bar().dropdown_size_changed.connect(
            self._on_dropdown_size_changed
        )
        self._shell.get_layers_toggle_action().toggled.connect(self.request_save)
        self._shell.get_conditions_toggle_action().toggled.connect(self.request_save)
        self._shell.get_status_bar_action().toggled.connect(self.request_save)
        self._shell.get_mesh_window_action().toggled.connect(
            self._on_mesh_window_toggled
        )
        self._shell.get_annotation_window_action().toggled.connect(
            self._on_annotation_window_toggled
        )
        self._shell.get_view_window_action().toggled.connect(
            self._on_view_window_toggled
        )
        self._shell.takeoff_sidebar.active_page_changed.connect(
            self._on_active_page_changed
        )
        self._shell.get_takeoff_plan_view().page_fully_loaded.connect(
            self._on_takeoff_page_fully_loaded
        )

    def restore_initial_state(self) -> None:
        self._restore_main_window_state(self._state)
        self._shell.set_status_bar_visible(self._state.main_window.status_bar_visible)
        self._restore_project_workspace_state()
        self._restore_takeoff_sidebar_state()
        self._shell.set_active_takeoff_view(self._state.takeoff_workspace.active_view)
        self._shell.set_takeoff_2d_tab_visible(
            self._state.takeoff_workspace.view_2d_tab_visible
        )
        self._shell.set_takeoff_3d_tab_visible(
            self._state.takeoff_workspace.view_3d_tab_visible
        )
        self._shell.set_conditions_sidebar_visible(
            self._state.takeoff_workspace.conditions_sidebar_visible
        )
        self._shell.set_layers_sidebar_visible(
            self._state.takeoff_workspace.layers_sidebar_visible
        )
        self._shell.set_workspace_toolbar_visibility_state(
            {
                "main_toolbar": self._state.toolbar_visibility.main_toolbar_visible,
                "view_toolbar": self._state.toolbar_visibility.view_toolbar_visible,
                "plan_tools_toolbar": self._state.toolbar_visibility.plan_tools_toolbar_visible,
            }
        )
        self._shell.set_annotation_styles_by_tool(
            self._state.takeoff_workspace.annotation_styles, persist=False
        )
        if self._pending_splitter_sizes:
            self._shell.set_left_splitter_sizes(self._pending_splitter_sizes)
        if self._pending_takeoff_splitter_sizes:
            self._shell.set_takeoff_splitter_sizes(self._pending_takeoff_splitter_sizes)
        self._shell.set_takeoff_dropdown_popup_sizes(
            self._state.takeoff_workspace.dropdown_popup_sizes
        )
        self._shell.sync_contextual_shell_visibility()

    def _connect_header_tracking(self, header: QtWidgets.QHeaderView) -> None:
        header.sectionMoved.connect(self.request_save)
        header.sectionResized.connect(self.request_save)
        header.sortIndicatorChanged.connect(self.request_save)

    def _restore_project_workspace_state(self) -> None:
        state = self._state.project_workspace
        header_state = self._decode_byte_array(state.header_state_b64)
        if header_state and not header_state.isEmpty():
            self._shell.restore_project_header_state(header_state)
        self._shell.set_project_group_by_job_status(state.group_by_job_status)
        self._shell.set_project_expanded_node_keys(state.expanded_node_keys)
        self._shell.set_project_selected_node(
            state.selected_node.to_dict() if state.selected_node else None
        )

    def _restore_takeoff_sidebar_state(self) -> None:
        conditions_header_state = self._decode_byte_array(
            self._state.takeoff_workspace.conditions_header_state_b64
        )
        if conditions_header_state and not conditions_header_state.isEmpty():
            self._shell.restore_conditions_header_state(conditions_header_state)
        self._shell.set_conditions_group_by_type(
            self._state.takeoff_workspace.conditions_group_by_type
        )
        self._shell.set_summary_grouping(
            ConditionSummaryGrouping(
                by_page=self._state.takeoff_workspace.summary_group_by_page,
                by_type=self._state.takeoff_workspace.summary_group_by_type,
                by_area=self._state.takeoff_workspace.summary_group_by_area,
            )
        )
        self._shell.set_summary_column_widths(
            self._state.takeoff_workspace.summary_column_widths
        )
        layers_header_state = self._decode_byte_array(
            self._state.takeoff_workspace.layers_header_state_b64
        )
        if layers_header_state and not layers_header_state.isEmpty():
            self._shell.restore_layers_header_state(layers_header_state)

    def show_main_window(self) -> None:
        if self._state.main_window.is_maximized:
            self._shell.showMaximized()
        else:
            self._shell.show()
        if self._pending_takeoff_splitter_sizes:
            QtCore.QTimer.singleShot(
                0,
                lambda: self._shell.set_takeoff_splitter_sizes(
                    self._pending_takeoff_splitter_sizes
                ),
            )
        if self._pending_splitter_sizes:
            QtCore.QTimer.singleShot(
                0,
                lambda: self._shell.set_left_splitter_sizes(
                    self._pending_splitter_sizes
                ),
            )

    def restore_deferred_state(self) -> None:
        self._pending_mesh_restore = bool(self._state.detached_windows.mesh_view.open)
        self._pending_annotation_restore = bool(
            self._state.detached_windows.annotation_view.open
        )
        self._pending_view_restore = bool(
            self._state.detached_windows.annotation_view.open
            and self._state.detached_windows.view_window.open
        )
        self._try_restore_mesh_window()
        self._try_restore_detached_page_windows()

    def on_main_tab_changed(self) -> None:
        if not self._shell.is_takeoff_tab_active():
            self._takeoff_workspace_activation_complete = False
            self._takeoff_workspace_ready = False
            self._takeoff_workspace_ready_restore_scheduled = False
            return
        self._try_restore_mesh_window()
        self._try_restore_detached_page_windows()

    def on_takeoff_workspace_activated(self) -> None:
        self._takeoff_workspace_activation_complete = True
        self._try_restore_detached_page_windows()

    def request_mesh_restore(self) -> None:
        self._pending_mesh_restore = True
        self.request_save()

    def request_annotation_restore(self) -> None:
        self._pending_annotation_restore = True
        self.request_save()

    def request_view_restore(self) -> None:
        self._pending_view_restore = True
        self.request_save()

    def track_annotation_window(self) -> None:
        self._schedule_track_detached_window(self._DETACHED_ANNOTATION)

    def track_view_window(self) -> None:
        self._schedule_track_detached_window(self._DETACHED_VIEW)

    def flush(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save_now()

    def reset_to_defaults(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._state = WorkspaceState()
        self._pending_takeoff_splitter_sizes = []
        self._pending_splitter_sizes = []
        self._pending_mesh_restore = False
        self._pending_annotation_restore = False
        self._pending_view_restore = False
        self.workspace_state_model.update_state(self._state)
        self.restore_initial_state()

    def cleanup(self) -> None:
        if self._cleaned_up:
            return
        self._cleaned_up = True
        if self._save_timer is not None:
            self._save_timer.stop()
            self._disconnect(self._save_timer.timeout, self._save_now)
            self._save_timer.deleteLater()
            self._save_timer = None
        if self._host_window is not None:
            self._host_window.removeEventFilter(self)
        for toolbar in self._tracked_toolbars:
            toolbar.removeEventFilter(self)
        for header in self._tracked_headers:
            self._disconnect(header.sectionMoved, self.request_save)
            self._disconnect(header.sectionResized, self.request_save)
            self._disconnect(header.sortIndicatorChanged, self.request_save)
        self._disconnect(
            self._shell.get_conditions_sidebar().group_by_type_changed,
            self.request_save,
        )
        self._disconnect(
            self._shell.get_condition_summary_tab().summary_ui_state_changed,
            self.request_save,
        )
        self._disconnect(self._shell.get_project_tree().itemExpanded, self.request_save)
        self._disconnect(
            self._shell.get_project_tree().itemCollapsed, self.request_save
        )
        self._disconnect(
            self._shell.get_project_tree().itemSelectionChanged, self.request_save
        )
        self._disconnect(self._shell.get_view_stack().currentChanged, self.request_save)
        self._disconnect(
            self._shell.get_takeoff_splitter().splitterMoved, self.request_save
        )
        self._disconnect(
            self._shell.get_left_splitter().splitterMoved, self.request_save
        )
        self._disconnect(
            self._shell.takeoff_sidebar.popup_size_changed,
            self._on_dropdown_size_changed,
        )
        self._disconnect(
            self._shell.get_page_settings_bar().dropdown_size_changed,
            self._on_dropdown_size_changed,
        )
        self._disconnect(
            self._shell.get_layers_toggle_action().toggled, self.request_save
        )
        self._disconnect(
            self._shell.get_conditions_toggle_action().toggled, self.request_save
        )
        self._disconnect(self._shell.get_status_bar_action().toggled, self.request_save)
        self._disconnect(
            self._shell.get_mesh_window_action().toggled,
            self._on_mesh_window_toggled,
        )
        self._disconnect(
            self._shell.get_annotation_window_action().toggled,
            self._on_annotation_window_toggled,
        )
        self._disconnect(
            self._shell.get_view_window_action().toggled,
            self._on_view_window_toggled,
        )
        self._disconnect(
            self._shell.takeoff_sidebar.active_page_changed,
            self._on_active_page_changed,
        )
        self._disconnect(
            self._shell.get_takeoff_plan_view().page_fully_loaded,
            self._on_takeoff_page_fully_loaded,
        )
        self._clear_tracked_detached_windows()
        self._tracked_toolbars = ()
        self._tracked_headers = ()
        self._host_window = None
        self._shell = None
        self.workspace_state_model = None
        self._state = None

    @staticmethod
    def _disconnect(signal, slot) -> None:
        try:
            signal.disconnect(slot)
        except (RuntimeError, TypeError):
            pass

    def request_save(self, *_args) -> None:
        if self._cleaned_up:
            return
        if self._save_timer is not None:
            self._save_timer.start()

    def eventFilter(self, watched, event) -> bool:
        if self._cleaned_up:
            return super().eventFilter(watched, event)
        event_type = event.type()
        if watched is self._host_window:
            if event_type in (
                QtCore.QEvent.Type.Move,
                QtCore.QEvent.Type.Resize,
                QtCore.QEvent.Type.WindowStateChange,
            ):
                self.request_save()
        elif any(watched is toolbar for toolbar in self._tracked_toolbars):
            if event_type in (
                QtCore.QEvent.Type.Move,
                QtCore.QEvent.Type.Resize,
                QtCore.QEvent.Type.Show,
                QtCore.QEvent.Type.Hide,
                QtCore.QEvent.Type.LayoutRequest,
                QtCore.QEvent.Type.ParentChange,
            ):
                self.request_save()
        else:
            window_key = self._find_tracked_detached_window_key(watched)
            if window_key is not None:
                if (
                    window_key == self._DETACHED_MESH
                    and event_type == QtCore.QEvent.Type.Show
                    and not self._detached_restore_applied.get(window_key, False)
                ):
                    QtCore.QTimer.singleShot(
                        0,
                        lambda window=watched: self._apply_saved_mesh_window_state(
                            window
                        ),
                    )
                if event_type in (
                    QtCore.QEvent.Type.Move,
                    QtCore.QEvent.Type.Resize,
                    QtCore.QEvent.Type.Show,
                    QtCore.QEvent.Type.Hide,
                    QtCore.QEvent.Type.WindowStateChange,
                    QtCore.QEvent.Type.Close,
                ):
                    self.request_save()
        return super().eventFilter(watched, event)

    def _restore_main_window_state(self, state: WorkspaceState) -> None:
        geometry = self._decode_byte_array(state.main_window.geometry_b64)
        if geometry and not geometry.isEmpty():
            self._shell.restoreGeometry(geometry)
        window_state = self._decode_byte_array(state.main_window.state_b64)
        if window_state and not window_state.isEmpty():
            self._shell.restoreState(window_state, self.MAIN_WINDOW_STATE_VERSION)

    def _on_mesh_window_toggled(self, visible: bool) -> None:
        if visible:
            self._schedule_track_detached_window(self._DETACHED_MESH)
        else:
            self._pending_mesh_restore = False
        self.request_save()

    def _on_annotation_window_toggled(self, visible: bool) -> None:
        if visible:
            self._schedule_track_detached_window(self._DETACHED_ANNOTATION)
            self._try_restore_view_window()
        else:
            self._pending_annotation_restore = False
        self.request_save()

    def _on_view_window_toggled(self, visible: bool) -> None:
        if visible:
            self._schedule_track_detached_window(self._DETACHED_VIEW)
        else:
            self._pending_view_restore = False
        self.request_save()

    def _on_active_page_changed(self, _page_uid) -> None:
        self._takeoff_workspace_activation_complete = False
        self._takeoff_workspace_ready = False
        self._takeoff_workspace_ready_restore_scheduled = False

    def _try_restore_annotation_window(self) -> None:
        if not self._pending_annotation_restore:
            return
        if not self._takeoff_workspace_ready:
            return
        if not self._shell.can_restore_annotation_window():
            return
        state = self._state.detached_windows.annotation_view
        geometry = self._decode_byte_array(state.geometry_b64)
        self._shell.set_annotation_window_visible(
            True,
            initial_geometry=geometry,
            initial_is_maximized=state.is_maximized,
            initial_is_fullscreen=state.is_fullscreen,
        )
        if self._shell.is_annotation_window_open():
            self._pending_annotation_restore = False
            self._schedule_track_detached_window(self._DETACHED_ANNOTATION)

    def _try_restore_mesh_window(self) -> None:
        if not self._pending_mesh_restore:
            return
        if not self._shell.is_takeoff_tab_active():
            return
        self._shell.set_mesh_window_visible(True)
        if self._shell.get_mesh_window() is not None:
            self._pending_mesh_restore = False
            self._schedule_track_detached_window(self._DETACHED_MESH)

    def _try_restore_view_window(self) -> None:
        if not self._pending_view_restore:
            return
        if not self._takeoff_workspace_ready:
            return
        if not self._shell.can_restore_view_window():
            return
        state = self._state.detached_windows.view_window
        geometry = self._decode_byte_array(state.geometry_b64)
        self._shell.set_view_window_visible(
            True,
            initial_geometry=geometry,
            initial_is_maximized=state.is_maximized,
            initial_is_fullscreen=state.is_fullscreen,
        )
        if self._shell.is_view_window_open():
            self._pending_view_restore = False
            self._schedule_track_detached_window(self._DETACHED_VIEW)

    def _try_restore_detached_page_windows(self) -> None:
        if not (self._pending_annotation_restore or self._pending_view_restore):
            return
        if not self._is_takeoff_workspace_stable():
            return
        if self._takeoff_workspace_ready_restore_scheduled:
            return
        self._takeoff_workspace_ready_restore_scheduled = True
        QtCore.QTimer.singleShot(0, self._restore_detached_page_windows_when_ready)

    def _restore_detached_page_windows_when_ready(self) -> None:
        if self._cleaned_up:
            return
        self._takeoff_workspace_ready_restore_scheduled = False
        if not self._is_takeoff_workspace_stable():
            return
        self._takeoff_workspace_ready = True
        self._try_restore_annotation_window()
        self._try_restore_view_window()

    def _on_takeoff_page_fully_loaded(self) -> None:
        self._takeoff_workspace_activation_complete = True
        self._try_restore_detached_page_windows()

    def _is_takeoff_workspace_stable(self) -> bool:
        if not self._shell.is_takeoff_tab_active():
            return False
        if not self._takeoff_workspace_activation_complete:
            return False
        if not self._shell.can_restore_annotation_window():
            return False
        if self._shell.get_active_takeoff_view() != "2d":
            return True
        plan_view = self._shell.get_takeoff_plan_view()
        return bool(plan_view.is_view_state_stable)

    def _schedule_track_detached_window(self, key: str) -> None:
        QtCore.QTimer.singleShot(
            0, lambda window_key=key: self._track_detached_window(window_key)
        )

    def _track_detached_window(self, key: str) -> None:
        if self._cleaned_up:
            return
        window = self._get_detached_window(key)
        if window is None:
            return
        previous = self._tracked_detached_windows.get(key)
        if previous is window:
            if window.isVisible() and not self._detached_restore_applied.get(
                key, False
            ):
                self._apply_restore_for_tracked_window(key, window)
            return
        if previous is not None:
            self._untrack_detached_window(key, previous)
        self._tracked_detached_windows[key] = window
        self._detached_restore_applied[key] = False
        window.installEventFilter(self)
        if key in (self._DETACHED_ANNOTATION, self._DETACHED_VIEW):
            try:
                window.dropdown_size_changed.connect(self._on_dropdown_size_changed)
            except RuntimeError:
                pass
        destroyed_callback = (
            lambda *_args, window_key=key: self._on_tracked_window_destroyed(window_key)
        )
        self._tracked_detached_destroy_callbacks[key] = destroyed_callback
        window.destroyed.connect(destroyed_callback)
        if key == self._DETACHED_MESH:
            QtCore.QTimer.singleShot(
                0,
                lambda widget=window: self._apply_saved_mesh_window_state(widget),
            )
        else:
            self._complete_detached_window_tracking(key, window)
        self.request_save()

    def _on_tracked_window_destroyed(self, key: str) -> None:
        self._tracked_detached_windows.pop(key, None)
        self._tracked_detached_destroy_callbacks.pop(key, None)
        self._detached_restore_applied.pop(key, None)
        self.request_save()

    def _clear_tracked_detached_windows(self) -> None:
        for key, window in list(self._tracked_detached_windows.items()):
            self._untrack_detached_window(key, window)
        self._tracked_detached_windows.clear()
        self._tracked_detached_destroy_callbacks.clear()
        self._detached_restore_applied.clear()

    def _untrack_detached_window(self, key: str, window: QtWidgets.QWidget) -> None:
        try:
            window.removeEventFilter(self)
        except RuntimeError:
            pass
        if key in (self._DETACHED_ANNOTATION, self._DETACHED_VIEW):
            try:
                window.dropdown_size_changed.disconnect(self._on_dropdown_size_changed)
            except (RuntimeError, TypeError):
                pass
        callback = self._tracked_detached_destroy_callbacks.pop(key, None)
        if callback is not None:
            try:
                window.destroyed.disconnect(callback)
            except (RuntimeError, TypeError):
                pass

    def _apply_saved_mesh_window_state(self, window: QtWidgets.QWidget) -> None:
        key = self._DETACHED_MESH
        if self._tracked_detached_windows.get(key) is not window:
            return
        state = self._get_detached_window_state(key)
        geometry = self._decode_byte_array(state.geometry_b64)
        try:
            if not window.isVisible():
                window.set_initial_window_state(geometry, state.is_maximized)
            else:
                if geometry and not geometry.isEmpty():
                    window.restoreGeometry(geometry)
                if state.is_maximized:
                    window.showMaximized()
                elif geometry and not geometry.isEmpty():
                    if window.isMaximized() or window.isMinimized():
                        window.showNormal()
                    window.restoreGeometry(geometry)
            self._complete_detached_window_tracking(key, window)
        except RuntimeError:
            return

    def _apply_restore_for_tracked_window(
        self, key: str, window: QtWidgets.QWidget
    ) -> None:
        if key == self._DETACHED_MESH:
            self._apply_saved_mesh_window_state(window)
            return
        self._complete_detached_window_tracking(key, window)

    def _complete_detached_window_tracking(
        self, key: str, window: QtWidgets.QWidget
    ) -> None:
        if key in (self._DETACHED_ANNOTATION, self._DETACHED_VIEW):
            window.set_dropdown_popup_sizes(
                self._state.takeoff_workspace.dropdown_popup_sizes
            )
        self._detached_restore_applied[key] = True

    def _on_dropdown_size_changed(self, *_args) -> None:
        if self._cleaned_up:
            return
        self._state.takeoff_workspace.dropdown_popup_sizes = (
            self._capture_dropdown_popup_sizes(
                self._state.takeoff_workspace.dropdown_popup_sizes
            )
        )
        self.request_save()

    def _save_now(self) -> None:
        try:
            current_state = self._capture_current_state()
            self.workspace_state_model.update_state(current_state)
            self._state = current_state
        except Exception as exc:
            self.logger.exception("Failed to persist workspace state: %s", exc)

    def _capture_current_state(self) -> WorkspaceState:
        previous = self._state
        takeoff_splitter_sizes = self._shell.get_takeoff_splitter_sizes()
        previous_takeoff_splitter_sizes = list(
            previous.takeoff_workspace.takeoff_splitter_sizes
        )
        if (
            previous_takeoff_splitter_sizes
            and not self._shell.get_takeoff_splitter().isVisible()
        ):
            takeoff_splitter_sizes = previous_takeoff_splitter_sizes
        elif sum(takeoff_splitter_sizes) <= 0 and previous_takeoff_splitter_sizes:
            takeoff_splitter_sizes = previous_takeoff_splitter_sizes
        takeoff_splitter_sizes = self._preserve_hidden_takeoff_splitter_sizes(
            takeoff_splitter_sizes,
            previous_takeoff_splitter_sizes,
        )
        splitter_sizes = self._shell.get_left_splitter_sizes()
        previous_splitter_sizes = list(previous.takeoff_workspace.left_splitter_sizes)
        if previous_splitter_sizes and not self._shell.get_left_splitter().isVisible():
            splitter_sizes = previous_splitter_sizes
        elif sum(splitter_sizes) <= 0 and previous_splitter_sizes:
            splitter_sizes = previous_splitter_sizes
        splitter_sizes = self._preserve_hidden_splitter_sizes(
            splitter_sizes,
            previous_splitter_sizes,
        )
        state = WorkspaceState()
        state.main_window.geometry_b64 = self._encode_byte_array(
            self._shell.saveGeometry()
        )
        state.main_window.state_b64 = self._encode_byte_array(
            self._shell.saveState(self.MAIN_WINDOW_STATE_VERSION)
        )
        state.main_window.is_maximized = self._shell.isMaximized()
        state.main_window.status_bar_visible = self._shell.is_status_bar_visible()
        state.project_workspace.header_state_b64 = self._encode_byte_array(
            self._shell.save_project_header_state()
        )
        state.project_workspace.expanded_node_keys = (
            self._shell.get_project_expanded_node_keys()
        )
        state.project_workspace.group_by_job_status = (
            self._shell.is_project_group_by_job_status()
        )
        state.project_workspace.selected_node = ProjectTreeSelectionState.from_dict(
            self._shell.get_project_selected_node()
        )
        state.takeoff_workspace.active_view = self._shell.get_active_takeoff_view()
        state.takeoff_workspace.view_2d_tab_visible = (
            self._shell.is_takeoff_2d_tab_visible()
        )
        state.takeoff_workspace.view_3d_tab_visible = (
            self._shell.is_takeoff_3d_tab_visible()
        )
        state.takeoff_workspace.conditions_sidebar_visible = (
            self._shell.is_conditions_sidebar_visible()
        )
        state.takeoff_workspace.layers_sidebar_visible = (
            self._shell.is_layers_sidebar_visible()
        )
        toolbar_visibility = self._shell.get_workspace_toolbar_visibility_state()
        state.toolbar_visibility.main_toolbar_visible = toolbar_visibility.get(
            "main_toolbar", True
        )
        state.toolbar_visibility.view_toolbar_visible = toolbar_visibility.get(
            "view_toolbar", True
        )
        state.toolbar_visibility.plan_tools_toolbar_visible = toolbar_visibility.get(
            "plan_tools_toolbar", True
        )
        state.takeoff_workspace.left_splitter_sizes = splitter_sizes
        state.takeoff_workspace.takeoff_splitter_sizes = takeoff_splitter_sizes
        state.takeoff_workspace.dropdown_popup_sizes = (
            self._capture_dropdown_popup_sizes(
                previous.takeoff_workspace.dropdown_popup_sizes
            )
        )
        state.takeoff_workspace.annotation_styles = (
            self._shell.get_annotation_styles_by_tool()
        )
        state.takeoff_workspace.conditions_header_state_b64 = self._encode_byte_array(
            self._shell.save_conditions_header_state()
        )
        state.takeoff_workspace.conditions_group_by_type = (
            self._shell.is_conditions_group_by_type_enabled()
        )
        summary_grouping = self._shell.get_summary_grouping()
        state.takeoff_workspace.summary_group_by_page = summary_grouping.by_page
        state.takeoff_workspace.summary_group_by_type = summary_grouping.by_type
        state.takeoff_workspace.summary_group_by_area = summary_grouping.by_area
        state.takeoff_workspace.summary_column_widths = (
            self._shell.get_summary_column_widths()
        )
        state.takeoff_workspace.layers_header_state_b64 = self._encode_byte_array(
            self._shell.save_layers_header_state()
        )
        annotation_should_be_open = (
            self._shell.get_annotation_window() is not None
            or self._pending_annotation_restore
        )
        mesh_window = self._shell.get_mesh_window()
        state.detached_windows.mesh_view = self._capture_detached_window_state(
            previous.detached_windows.mesh_view,
            mesh_window,
            is_open=mesh_window is not None or self._pending_mesh_restore,
        )
        annotation_window = self._shell.get_annotation_window()
        state.detached_windows.annotation_view = self._capture_detached_window_state(
            previous.detached_windows.annotation_view,
            annotation_window,
            is_open=annotation_should_be_open,
        )
        view_window = self._shell.get_view_window()
        state.detached_windows.view_window = self._capture_detached_window_state(
            previous.detached_windows.view_window,
            view_window,
            is_open=annotation_should_be_open
            and (view_window is not None or self._pending_view_restore),
        )
        return state

    def _capture_dropdown_popup_sizes(
        self, previous: dict[str, list[int]]
    ) -> dict[str, list[int]]:
        return self._merge_dropdown_popup_sizes(
            previous,
            self._shell.get_takeoff_dropdown_popup_sizes(),
        )

    def _merge_dropdown_popup_sizes(
        self,
        previous: dict[str, list[int]],
        current: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        merged = {
            str(key): list(value)
            for key, value in (previous or {}).items()
            if key in self._DROPDOWN_POPUP_KEYS and len(value) >= 2
        }
        for key, value in (current or {}).items():
            if (
                key in self._DROPDOWN_POPUP_KEYS
                and len(value) >= 2
                and value[0] > 0
                and value[1] > 0
            ):
                merged[str(key)] = list(value[:2])
        return merged

    def _preserve_hidden_splitter_sizes(
        self, current_sizes: list[int], previous_sizes: list[int]
    ) -> list[int]:
        sizes = [max(0, int(size)) for size in current_sizes]
        previous = [max(0, int(size)) for size in previous_sizes]
        if len(previous) < 2 or previous[0] <= 0 or previous[1] <= 0:
            return sizes
        if (
            not self._shell.is_conditions_sidebar_visible()
            or not self._shell.is_layers_sidebar_visible()
        ):
            return previous[:2]
        return sizes

    def _preserve_hidden_takeoff_splitter_sizes(
        self, current_sizes: list[int], previous_sizes: list[int]
    ) -> list[int]:
        sizes = [max(0, int(size)) for size in current_sizes]
        previous = [max(0, int(size)) for size in previous_sizes]
        if len(previous) < 2:
            return sizes
        if (
            not self._shell.is_conditions_sidebar_visible()
            and not self._shell.is_layers_sidebar_visible()
            and sizes[0] <= 0
        ):
            sizes[0] = previous[0]
        return sizes

    def _capture_detached_window_state(
        self,
        previous_state: DetachedWindowState,
        window: Optional[QtWidgets.QWidget],
        is_open: bool,
    ) -> DetachedWindowState:
        if window is None:
            return DetachedWindowState(
                open=is_open,
                geometry_b64=previous_state.geometry_b64,
                is_maximized=previous_state.is_maximized,
                is_fullscreen=previous_state.is_fullscreen,
            )
        return DetachedWindowState(
            open=is_open,
            geometry_b64=self._encode_byte_array(window.saveGeometry()),
            is_maximized=window.isMaximized(),
            is_fullscreen=window.isFullScreen(),
        )

    def _get_detached_window(self, key: str) -> Optional[QtWidgets.QWidget]:
        if key == self._DETACHED_MESH:
            return self._shell.get_mesh_window()
        if key == self._DETACHED_ANNOTATION:
            return self._shell.get_annotation_window()
        if key == self._DETACHED_VIEW:
            return self._shell.get_view_window()
        return None

    def _get_detached_window_state(self, key: str) -> DetachedWindowState:
        if key == self._DETACHED_MESH:
            return self._state.detached_windows.mesh_view
        if key == self._DETACHED_ANNOTATION:
            return self._state.detached_windows.annotation_view
        if key == self._DETACHED_VIEW:
            return self._state.detached_windows.view_window
        return DetachedWindowState()

    def _find_tracked_detached_window_key(self, watched) -> Optional[str]:
        for key, window in self._tracked_detached_windows.items():
            if window is watched:
                return key
        return None

    @staticmethod
    def _encode_byte_array(value: QtCore.QByteArray) -> Optional[str]:
        if value is None or value.isEmpty():
            return None
        return bytes(value.toBase64()).decode("ascii")

    @staticmethod
    def _decode_byte_array(value: Optional[str]) -> QtCore.QByteArray:
        if not value or not isinstance(value, str):
            return QtCore.QByteArray()
        if not value.isascii():
            return QtCore.QByteArray()
        return QtCore.QByteArray.fromBase64(value.encode("ascii"))
