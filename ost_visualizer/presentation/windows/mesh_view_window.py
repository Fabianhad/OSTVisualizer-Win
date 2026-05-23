from typing import Optional, Sequence
from PySide6 import QtCore, QtGui, QtWidgets
from ...application.interfaces.i_window_icon_provider import IWindowIconProvider
from ...domain.entities.identity_refs import BidRef
from ..components.mesh_view import OpenGLViewer
from ..components.popup_tracking_combo import PopupTrackingComboBox
from ..components.viewer_cursors import make_zoom_cursor
from ..config import DEFAULT_ICON_SIZE, NO_MARGINS, NO_SPACING
from ..managers.icon_manager import IconId, IconManager
from ..managers.shortcut_manager import ShortcutManager

_ZOOM_LEVELS = [5, 10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 800, 1600]
_ZOOM_FACTOR = 1.15
_RESIZE_DEBOUNCE_MS = 100
_POPUP_CLOSE_DEFER_MS = 100


class MeshViewWindow(QtWidgets.QMainWindow):
    mesh_clicked = QtCore.Signal(list)
    elements_deleted = QtCore.Signal(list)
    assign_to_area_requested = QtCore.Signal(list)
    reassign_condition_requested = QtCore.Signal(list, str)
    set_negative_requested = QtCore.Signal(list, bool)
    set_curved_requested = QtCore.Signal(list, bool)
    overlay_display_mode_requested = QtCore.Signal(int)
    undo_requested = QtCore.Signal()
    redo_requested = QtCore.Signal()

    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        color_service,
        negative_check_fn=None,
        curved_check_fn=None,
        selected_context_state_fn=None,
        context_menu_conditions_fn=None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self._is_closing = False
        self._initial_geometry = QtCore.QByteArray()
        self._initial_show_maximized = True
        self.icon_provider = icon_provider
        self._color_service = color_service
        self.viewer: Optional[OpenGLViewer] = None
        self._zoom_combo: Optional[QtWidgets.QComboBox] = None
        self._context_menu_command_trigger = None
        self._context_menu_action_state = None
        self.setWindowTitle("3D View")
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window
            | QtCore.Qt.WindowType.WindowMinimizeButtonHint
            | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            | QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.icon_provider.set_window_icon(self)
        self._resize_timer = QtCore.QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._on_resize_settled)
        self._setup_ui(
            negative_check_fn,
            curved_check_fn,
            selected_context_state_fn,
            context_menu_conditions_fn,
        )
        ShortcutManager.register_shortcut(self, "undo", self.undo_requested.emit)
        ShortcutManager.register_shortcut(self, "redo", self.redo_requested.emit)

    def set_initial_window_state(
        self, geometry: QtCore.QByteArray, is_maximized: bool
    ) -> None:
        self._initial_geometry = QtCore.QByteArray(geometry)
        self._initial_show_maximized = bool(is_maximized)
        if self._initial_geometry and not self._initial_geometry.isEmpty():
            self.restoreGeometry(self._initial_geometry)

    def show_initial_window(self) -> None:
        geometry = self._initial_geometry
        if self._initial_show_maximized:
            if geometry and not geometry.isEmpty():
                self.restoreGeometry(geometry)
            self.showMaximized()
            return
        if geometry and not geometry.isEmpty():
            if self.isMaximized() or self.isMinimized():
                self.showNormal()
            self.restoreGeometry(geometry)
            self.show()
            return
        self.show()

    def _setup_ui(
        self,
        negative_check_fn,
        curved_check_fn,
        selected_context_state_fn,
        context_menu_conditions_fn,
    ) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(*NO_MARGINS)
        main_layout.setSpacing(NO_SPACING)
        toolbar = QtWidgets.QToolBar(self)
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        cursor_group = QtGui.QActionGroup(toolbar)
        cursor_group.setExclusive(True)
        default_action = QtGui.QAction("Orbit", toolbar)
        IconManager.apply(default_action, IconId.SELECT_TOOL)
        default_action.setCheckable(True)
        default_action.setChecked(True)
        default_action.setToolTip("Orbit")
        cursor_group.addAction(default_action)
        toolbar.addAction(default_action)
        pan_action = QtGui.QAction("Pan", toolbar)
        IconManager.apply(pan_action, IconId.PAN_TOOL)
        pan_action.setCheckable(True)
        pan_action.setToolTip("Pan")
        cursor_group.addAction(pan_action)
        toolbar.addAction(pan_action)
        zoom_mode_action = QtGui.QAction("Zoom", toolbar)
        IconManager.apply(zoom_mode_action, IconId.ZOOM_TOOL)
        zoom_mode_action.setCheckable(True)
        zoom_mode_action.setToolTip("Zoom")
        cursor_group.addAction(zoom_mode_action)
        toolbar.addAction(zoom_mode_action)
        fit_action = QtGui.QAction("Reset View", toolbar)
        IconManager.apply(fit_action, IconId.RESET_VIEW)
        fit_action.setToolTip("Reset view")
        toolbar.addAction(fit_action)
        zoom_in_action = QtGui.QAction("Zoom In", toolbar)
        IconManager.apply(zoom_in_action, IconId.ZOOM_IN)
        zoom_in_action.setToolTip("Zoom in")
        toolbar.addAction(zoom_in_action)
        zoom_out_action = QtGui.QAction("Zoom Out", toolbar)
        IconManager.apply(zoom_out_action, IconId.ZOOM_OUT)
        zoom_out_action.setToolTip("Zoom out")
        toolbar.addAction(zoom_out_action)
        self._zoom_combo = PopupTrackingComboBox(
            popup_hidden_delay_ms=_POPUP_CLOSE_DEFER_MS
        )
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._zoom_combo.setFixedWidth(80)
        for lvl in _ZOOM_LEVELS:
            self._zoom_combo.addItem(f"{lvl}%", lvl)
        self._zoom_combo.setCurrentIndex(-1)
        self._zoom_combo.setEditText("100%")
        toolbar.addWidget(self._zoom_combo)
        main_layout.addWidget(toolbar)
        self.viewer = OpenGLViewer(central, self._color_service)
        self.viewer.set_zoom_cursor(make_zoom_cursor())
        self.viewer.set_context_menu_command_handlers(
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )
        main_layout.addWidget(self.viewer, 1)
        if negative_check_fn:
            self.viewer.set_negative_check_fn(negative_check_fn)
        if curved_check_fn:
            self.viewer.set_curved_check_fn(curved_check_fn)
        if selected_context_state_fn:
            self.viewer.set_selected_context_state_fn(selected_context_state_fn)
        if context_menu_conditions_fn:
            self.viewer.set_context_menu_conditions_fn(context_menu_conditions_fn)
        self.viewer.mesh_clicked.connect(self.mesh_clicked)
        self.viewer.elements_deleted.connect(self.elements_deleted)
        self.viewer.assign_to_area_requested.connect(self.assign_to_area_requested)
        self.viewer.reassign_condition_requested.connect(
            self.reassign_condition_requested
        )
        self.viewer.set_negative_requested.connect(self.set_negative_requested)
        self.viewer.set_curved_requested.connect(self.set_curved_requested)
        self.viewer.overlay_display_mode_requested.connect(
            self.overlay_display_mode_requested
        )
        default_action.toggled.connect(
            lambda checked: self.viewer.set_cursor_mode("default") if checked else None
        )
        pan_action.toggled.connect(
            lambda checked: self.viewer.set_cursor_mode("pan" if checked else "default")
        )
        zoom_mode_action.toggled.connect(
            lambda checked: self.viewer.set_cursor_mode(
                "zoom" if checked else "default"
            )
        )
        fit_action.triggered.connect(self._on_reset_view)
        zoom_in_action.triggered.connect(self._on_zoom_in)
        zoom_out_action.triggered.connect(self._on_zoom_out)
        self.viewer.zoom_changed.connect(self._update_zoom_combo)
        self._popup_open = False
        self._zoom_combo.popup_shown.connect(self._on_zoom_popup_shown)
        self._zoom_combo.popup_hidden.connect(self._on_zoom_popup_hidden)
        self._zoom_combo.activated.connect(self._on_zoom_combo_activated)
        self._zoom_combo.lineEdit().returnPressed.connect(self._on_zoom_text_entered)

    def _on_zoom_popup_shown(self) -> None:
        self._popup_open = True

    def _on_zoom_popup_hidden(self) -> None:
        self._popup_open = False

    def _update_zoom_combo(self, factor: float) -> None:
        if not self._zoom_combo:
            return
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.lineEdit().blockSignals(True)
        self._zoom_combo.setCurrentIndex(-1)
        self._zoom_combo.lineEdit().setText(f"{int(factor * 100)}%")
        self._zoom_combo.lineEdit().blockSignals(False)
        self._zoom_combo.blockSignals(False)

    def _on_reset_view(self) -> None:
        if self.viewer:
            self.viewer.reset_view()
            self._update_zoom_combo(1.0)

    def _on_zoom_in(self) -> None:
        if not self.viewer:
            return
        pct = self.viewer.get_zoom_percent() * _ZOOM_FACTOR
        self.viewer.set_zoom_percent(pct)
        self._update_zoom_combo(pct / 100.0)

    def _on_zoom_out(self) -> None:
        if not self.viewer:
            return
        pct = self.viewer.get_zoom_percent() / _ZOOM_FACTOR
        self.viewer.set_zoom_percent(pct)
        self._update_zoom_combo(pct / 100.0)

    def _on_zoom_combo_activated(self, index: int) -> None:
        if not self._popup_open or not self.viewer or index < 0:
            return
        percent = self._zoom_combo.itemData(index)
        if percent is None:
            return
        self.viewer.set_zoom_percent(float(percent))
        self._update_zoom_combo(float(percent) / 100.0)

    def _on_zoom_text_entered(self) -> None:
        if not self.viewer or not self._zoom_combo:
            return
        text = self._zoom_combo.currentText().strip().rstrip("%")
        try:
            percent = float(text)
            if percent > 0:
                self.viewer.set_zoom_percent(percent)
                self._update_zoom_combo(percent / 100.0)
        except ValueError:
            pass

    def apply_mesh_data(
        self,
        vertices_list: Sequence,
        normals_list: Sequence,
        indices_list: Sequence,
        colors: Sequence,
        bid_ref: Optional[BidRef] = None,
        condition_uids: Optional[Sequence[str]] = None,
        takeoff_uids: Optional[Sequence[str]] = None,
    ) -> None:
        if self._is_closing or not self.viewer:
            return
        self.viewer.apply_mesh_data(
            vertices_list,
            normals_list,
            indices_list,
            colors,
            bid_ref=bid_ref,
            condition_uids=condition_uids,
            takeoff_uids=takeoff_uids,
        )

    def set_selected_takeoffs(self, takeoff_uids: list) -> None:
        if self.viewer:
            self.viewer.set_selected_takeoffs(takeoff_uids)

    def get_selected_takeoff_uids(self) -> list:
        return self.viewer.get_selected_takeoff_uids() if self.viewer else []

    def set_pick_enabled(self, enabled: bool) -> None:
        if self.viewer:
            self.viewer.set_pick_enabled(enabled)

    def set_overlay_display_mode(self, mode: int) -> None:
        if self.viewer:
            self.viewer.set_overlay_display_mode(mode)

    def set_context_menu_command_handlers(self, trigger_fn, action_state_fn) -> None:
        self._context_menu_command_trigger = trigger_fn
        self._context_menu_action_state = action_state_fn
        if self.viewer:
            self.viewer.set_context_menu_command_handlers(trigger_fn, action_state_fn)

    def set_selected_context_state_fn(self, fn) -> None:
        if self.viewer:
            self.viewer.set_selected_context_state_fn(fn)

    def set_context_menu_conditions_fn(self, fn) -> None:
        if self.viewer:
            self.viewer.set_context_menu_conditions_fn(fn)

    def clear_scene(self) -> None:
        if self.viewer:
            self.viewer.clear_scene()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._is_closing:
            self._resize_timer.start()

    def _on_resize_settled(self) -> None:
        if self._is_closing or not self.viewer:
            return
        self.viewer.refresh_viewport()

    def cleanup(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer.timeout.disconnect(self._on_resize_settled)
            self._resize_timer.deleteLater()
            self._resize_timer = None
        if self.viewer is not None:
            self.viewer.blockSignals(True)
            self.viewer.cleanup()
            self.viewer = None
        self._zoom_combo = None
        self.icon_provider = None
        self._color_service = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.cleanup()
        super().closeEvent(event)
