from dataclasses import dataclass
from PySide6 import QtCore, QtGui, QtWidgets
from ..adapters.hotlink_event_adapter import HotlinkEventAdapter
from ..components.conditions_sidebar import ConditionsSidebar
from ..components.layers_sidebar import BidLayersSidebar
from ..components.mesh_view import OpenGLViewer
from ..components.page_combo import PageComboBox
from ..components.page_settings_bar import PageSettingsBar
from ..components.plan_view.view import TakeoffPlanView
from ..components.popup_tracking_combo import PopupTrackingComboBox
from ..components.project_tree_view import ProjectView
from ..components.status_panel import StatusPanel
from ..components.viewer_cursors import (
    make_move_overlay_cursor,
    make_rotate_cursor,
    make_zoom_cursor,
)
from ..config import (
    ACTION_NEXT_PAGE_LABEL,
    ACTION_NEXT_PAGE_TOOLTIP,
    ACTION_PREVIOUS_PAGE_LABEL,
    ACTION_PREVIOUS_PAGE_TOOLTIP,
    ACTION_RESET_VIEW_LABEL,
    ACTION_RESET_VIEW_TOOLTIP,
    ACTION_ZOOM_IN_LABEL,
    ACTION_ZOOM_IN_TOOLTIP,
    ACTION_MOVE_OVERLAY_IMAGE_LABEL,
    ACTION_MOVE_OVERLAY_IMAGE_TOOLTIP,
    ACTION_ZOOM_OUT_LABEL,
    ACTION_ZOOM_OUT_TOOLTIP,
    ANNOTATION_VIEW_WINDOW_ACTION_LABEL,
    ANNOTATION_WINDOW_TITLE,
    COMPACT_SPACING,
    DEFAULT_ICON_SIZE,
    DETACH_3D_VIEW_TOOLTIP,
    INLINE_MARGINS,
    MAIN_TOOLBAR_LABEL,
    NO_MARGINS,
    NO_SPACING,
    SIDEBAR_MIN_WIDTH,
    TAB_INDEX_TAKEOFF,
    PLAN_TOOLS_TOOLBAR_LABEL,
    OVERLAY_TOOLS_TOOLBAR_LABEL,
    VIEW_LABEL,
    VIEW_TOOLBAR_LABEL,
    VIEW_WINDOW_TITLE,
    VIEWER_2D_LABEL,
    VIEWER_2D_TOOLTIP,
    VIEWER_3D_LABEL,
    VIEWER_3D_TOOLTIP,
    VIEWER_ZOOM_COMBO_WIDTH,
    VIEWER_ZOOM_FACTOR,
    VIEWER_ZOOM_LEVELS,
    VIEWER_ZOOM_POPUP_HIDDEN_DELAY_MS,
)
from ..controllers.menu_controller import MenuController
from ..handlers.plan_view_action_handler import PlanViewActionHandler
from ..managers.icon_manager import IconId, IconManager
from ..managers.shortcut_manager import ShortcutManager
from ..managers.ui_access_manager import Feature
from ..services.undo_redo_service import UndoRedoService
from ..utils.annotation_style_controls import (
    apply_annotation_tool_icon_color,
    create_annotation_tool_split_button,
)
from ..utils.plan_tool_registry import PLAN_ANNOTATION_TOOL_SPECS, PLAN_TOOL_SPECS


class _PlanRibbonToolBar(QtWidgets.QToolBar):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._preferred_docked_height = 0

    def set_preferred_docked_height(self, height: int) -> None:
        height = max(0, int(height))
        if self._preferred_docked_height == height:
            return
        self._preferred_docked_height = height
        self.updateGeometry()

    def sizeHint(self) -> QtCore.QSize:
        hint = super().sizeHint()
        if (
            not self.isFloating()
            and self.orientation() == QtCore.Qt.Orientation.Vertical
            and self._preferred_docked_height > 0
        ):
            hint.setHeight(max(hint.height(), self._preferred_docked_height))
        return hint

    def minimumSizeHint(self) -> QtCore.QSize:
        hint = super().minimumSizeHint()
        if (
            not self.isFloating()
            and self.orientation() == QtCore.Qt.Orientation.Vertical
            and self._preferred_docked_height > 0
        ):
            hint.setHeight(max(hint.height(), self._preferred_docked_height))
        return hint


class _PlanToolbarLayoutSyncFilter(QtCore.QObject):
    def __init__(self, callback, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (
            QtCore.QEvent.Type.Show,
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.LayoutRequest,
        ):
            QtCore.QTimer.singleShot(0, self._callback)
        return super().eventFilter(watched, event)


@dataclass
class ComponentBundle:
    central_widget: QtWidgets.QWidget
    tab_widget: QtWidgets.QTabWidget
    takeoff_tab: QtWidgets.QWidget
    project_view: ProjectView
    takeoff_sidebar: PageComboBox
    conditions_sidebar: ConditionsSidebar
    opengl_viewer: OpenGLViewer
    plan_view: TakeoffPlanView
    view_stack: QtWidgets.QStackedWidget
    status_panel: StatusPanel
    plan_tools_toolbar: QtWidgets.QToolBar
    overlay_tools_toolbar: QtWidgets.QToolBar
    view_toolbar: QtWidgets.QToolBar
    main_toolbar: QtWidgets.QToolBar
    view_2d_action: QtGui.QAction
    view_3d_action: QtGui.QAction
    new_project_action: QtGui.QAction
    new_folder_action: QtGui.QAction
    new_database_action: QtGui.QAction
    open_files_action: QtGui.QAction
    copy_action: QtGui.QAction
    cut_action: QtGui.QAction
    paste_action: QtGui.QAction
    delete_action: QtGui.QAction
    undo_action: QtGui.QAction
    redo_action: QtGui.QAction
    duplicate_action: QtGui.QAction
    zoom_in_action: QtGui.QAction
    zoom_out_action: QtGui.QAction
    reset_view_action: QtGui.QAction
    next_page_action: QtGui.QAction
    previous_page_action: QtGui.QAction
    plan_tool_actions: dict[str, QtGui.QAction]
    select_action: QtGui.QAction
    pan_action: QtGui.QAction
    zoom_mode_action: QtGui.QAction
    backout_action: QtGui.QAction
    move_overlay_action: QtGui.QAction
    cover_sheet_button: QtWidgets.QToolButton
    page_settings_bar: PageSettingsBar
    bid_layers_sidebar: BidLayersSidebar
    takeoff_splitter: QtWidgets.QSplitter
    left_splitter: QtWidgets.QSplitter
    layers_toggle_action: QtGui.QAction
    conditions_toggle_action: QtGui.QAction
    annotation_window_action: QtGui.QAction
    view_window_action: QtGui.QAction
    place_action: QtGui.QAction = None
    mesh_window_action: QtGui.QAction = None
    plan_view_handler: object = None
    undo_service: object = None


class ComponentBuilder:
    def __init__(self, window: QtWidgets.QMainWindow):
        self.window = window

    def build_components(
        self,
        event_bus,
        color_service,
        coordinate_transformer_factory,
        infrastructure_provider,
        project_read_service,
        project_write_service,
        project_data_service,
        annotation_write_service,
        register_hotlink_adapter_fn,
        ui_state_manager,
        ui_event_handler,
        ui_access_manager=None,
    ) -> ComponentBundle:
        central_widget = QtWidgets.QWidget()
        central_layout = QtWidgets.QVBoxLayout(central_widget)
        central_layout.setContentsMargins(*INLINE_MARGINS)
        central_layout.setSpacing(NO_SPACING)
        tab_widget = QtWidgets.QTabWidget(central_widget)
        tab_widget.setDocumentMode(True)
        projects_tab = QtWidgets.QWidget()
        bids_layout = QtWidgets.QVBoxLayout(projects_tab)
        bids_layout.setContentsMargins(*NO_MARGINS)
        bids_layout.setSpacing(COMPACT_SPACING)
        project_view = ProjectView(
            parent=projects_tab,
            event_bus=event_bus,
            on_bid_selection=ui_event_handler.handle_bid_selection,
            on_bid_activated=lambda _bid_ref: tab_widget.setCurrentIndex(
                TAB_INDEX_TAKEOFF
            ),
            on_page_selection=ui_event_handler.handle_page_selection,
        )
        bids_layout.addWidget(project_view)
        tab_widget.addTab(projects_tab, "Projects")
        takeoff_tab = QtWidgets.QWidget()
        takeoff_layout = QtWidgets.QHBoxLayout(takeoff_tab)
        takeoff_layout.setContentsMargins(*NO_MARGINS)
        takeoff_layout.setSpacing(NO_SPACING)
        page_combo = PageComboBox()
        page_combo.page_selection_changed.connect(
            ui_event_handler.handle_page_selection
        )
        page_combo.active_page_changed.connect(
            ui_event_handler.handle_active_page_changed
        )
        viewer_container = QtWidgets.QWidget(takeoff_tab)
        viewer_container_layout = QtWidgets.QVBoxLayout(viewer_container)
        viewer_container_layout.setContentsMargins(*NO_MARGINS)
        viewer_container_layout.setSpacing(NO_SPACING)
        view_toolbar = QtWidgets.QToolBar()
        view_toolbar.setMovable(False)
        view_toolbar.setFloatable(False)
        view_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        btn_3d = QtWidgets.QToolButton()
        btn_3d.setText(VIEWER_3D_LABEL)
        btn_3d.setCheckable(True)
        btn_3d.setChecked(True)
        btn_3d.setToolTip(VIEWER_3D_TOOLTIP)
        btn_2d = QtWidgets.QToolButton()
        btn_2d.setText(VIEWER_2D_LABEL)
        btn_2d.setCheckable(True)
        btn_2d.setToolTip(VIEWER_2D_TOOLTIP)
        view_group = QtWidgets.QButtonGroup(takeoff_tab)
        view_group.addButton(btn_3d, 0)
        view_group.addButton(btn_2d, 1)
        btn_3d_action = view_toolbar.addWidget(btn_3d)
        btn_2d_action = view_toolbar.addWidget(btn_2d)
        view_stack = QtWidgets.QStackedWidget(viewer_container)
        viewer_frame_3d = QtWidgets.QFrame()
        viewer_frame_3d.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        viewer_layout_3d = QtWidgets.QVBoxLayout(viewer_frame_3d)
        viewer_layout_3d.setContentsMargins(*NO_MARGINS)
        viewer_layout_3d.setSpacing(NO_SPACING)
        canvas = OpenGLViewer(viewer_frame_3d, color_service)
        canvas.setContentsMargins(*NO_MARGINS)
        viewer_layout_3d.addWidget(canvas)
        viewer_frame_2d = QtWidgets.QFrame()
        viewer_frame_2d.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        viewer_layout_2d = QtWidgets.QVBoxLayout(viewer_frame_2d)
        viewer_layout_2d.setContentsMargins(*NO_MARGINS)
        viewer_layout_2d.setSpacing(NO_SPACING)
        coord_system = coordinate_transformer_factory.create()
        renderers = infrastructure_provider.create_plan_view_renderers(
            coord_system, color_service
        )
        plan_view = TakeoffPlanView(
            color_service,
            renderers.rendering_service,
            renderers.load_coordinator,
            renderers.takeoff_renderer,
            renderers.annotation_renderer,
            renderers.linear_geometry,
            viewer_frame_2d,
        )
        if ui_access_manager:
            plan_view.set_text_annotation_inline_edit_allowed_fn(
                lambda: ui_access_manager.is_allowed(Feature.EDIT_ANNOTATION_TEXT)
            )
        plan_view.setContentsMargins(*NO_MARGINS)
        viewer_layout_2d.addWidget(plan_view)
        hotlink_adapter = HotlinkEventAdapter(event_bus)
        hotlink_adapter.set_plan_view(plan_view)
        register_hotlink_adapter_fn(hotlink_adapter)
        view_stack.addWidget(viewer_frame_3d)
        view_stack.addWidget(viewer_frame_2d)
        plan_view.setEnabled(False)
        btn_3d.clicked.connect(lambda: view_stack.setCurrentIndex(0))
        btn_2d.clicked.connect(lambda: view_stack.setCurrentIndex(1))
        main_toolbar = QtWidgets.QToolBar(viewer_container)
        main_toolbar.setMovable(False)
        main_toolbar.setFloatable(False)
        main_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        main_toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly)
        previous_page_action = QtGui.QAction(
            ACTION_PREVIOUS_PAGE_LABEL, viewer_container
        )
        IconManager.apply(previous_page_action, IconId.PREVIOUS_PAGE)
        previous_page_action.setToolTip(ACTION_PREVIOUS_PAGE_TOOLTIP)
        previous_page_action.triggered.connect(page_combo.go_prev)
        btn_prev_page = QtWidgets.QToolButton()
        btn_prev_page.setDefaultAction(previous_page_action)
        btn_prev_page.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        main_toolbar.addWidget(btn_prev_page)
        main_toolbar.addWidget(page_combo)
        next_page_action = QtGui.QAction(ACTION_NEXT_PAGE_LABEL, viewer_container)
        IconManager.apply(next_page_action, IconId.NEXT_PAGE)
        next_page_action.setToolTip(ACTION_NEXT_PAGE_TOOLTIP)
        next_page_action.triggered.connect(self.window.go_next_takeoff_page)
        btn_next_page = QtWidgets.QToolButton()
        btn_next_page.setDefaultAction(next_page_action)
        btn_next_page.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        main_toolbar.addWidget(btn_next_page)

        def _update_page_nav_actions(_uid=None) -> None:
            order = page_combo.get_page_order()
            active_uid = page_combo.get_active_page_uid()
            active_index = order.index(active_uid) if active_uid in order else -1
            can_go_prev = active_index > 0
            can_go_next = active_index >= 0 and (
                active_index < len(order) - 1
                or (
                    active_index == len(order) - 1
                    and self.window.can_add_page_from_takeoff_tab()
                )
            )
            previous_page_action.setEnabled(can_go_prev)
            next_page_action.setEnabled(can_go_next)

        _update_page_nav_actions()
        page_combo.active_page_changed.connect(_update_page_nav_actions)
        page_nav_spacer = QtWidgets.QWidget()
        page_nav_spacer.setFixedWidth(6)
        main_toolbar.addWidget(page_nav_spacer)
        plan_tool_group = QtGui.QActionGroup(viewer_container)
        plan_tool_group.setExclusive(True)
        plan_tool_actions = {}
        for spec in PLAN_TOOL_SPECS:
            action = QtGui.QAction(spec.label, viewer_container)
            IconManager.apply(action, spec.icon_id)
            action.setCheckable(True)
            action.setToolTip(spec.tooltip)
            if spec.action_key == "select_tool":
                action.setChecked(True)
            plan_tool_group.addAction(action)
            plan_tool_actions[spec.action_key] = action
            if spec.annotation_type is not None:
                button = QtWidgets.QToolButton(viewer_container)
                button.setDefaultAction(action)
                button.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
                split_button, _ = create_annotation_tool_split_button(
                    viewer_container,
                    button,
                    lambda annotation_type=spec.annotation_type: (
                        self.window.get_annotation_style_for_tool(annotation_type)
                    ),
                    lambda annotation_type=spec.annotation_type, **style_kwargs: (
                        self.window.set_annotation_style_for_tool(
                            annotation_type, **style_kwargs
                        )
                    ),
                    icon_size=QtCore.QSize(*DEFAULT_ICON_SIZE),
                    annotation_type=spec.annotation_type,
                )
                main_toolbar.addWidget(split_button)
            else:
                main_toolbar.addAction(action)
        apply_annotation_tool_icon_color(plan_tool_actions)
        select_action = plan_tool_actions["select_tool"]
        place_action = plan_tool_actions["place_tool"]
        pan_action = plan_tool_actions["pan_tool"]
        zoom_mode_action = plan_tool_actions["zoom_tool"]
        _zoom_cursor = make_zoom_cursor()
        plan_view.set_zoom_cursor(_zoom_cursor)
        canvas.set_zoom_cursor(_zoom_cursor)
        plan_view.set_rotate_cursor(make_rotate_cursor())
        plan_view.set_move_overlay_cursor(make_move_overlay_cursor())
        fit_action = QtGui.QAction(ACTION_RESET_VIEW_LABEL, viewer_container)
        IconManager.apply(fit_action, IconId.RESET_VIEW)
        fit_action.setToolTip(ACTION_RESET_VIEW_TOOLTIP)
        main_toolbar.addAction(fit_action)
        zoom_in_action = QtGui.QAction(ACTION_ZOOM_IN_LABEL, viewer_container)
        IconManager.apply(zoom_in_action, IconId.ZOOM_IN)
        zoom_in_action.setToolTip(ACTION_ZOOM_IN_TOOLTIP)
        main_toolbar.addAction(zoom_in_action)
        zoom_out_action = QtGui.QAction(ACTION_ZOOM_OUT_LABEL, viewer_container)
        IconManager.apply(zoom_out_action, IconId.ZOOM_OUT)
        zoom_out_action.setToolTip(ACTION_ZOOM_OUT_TOOLTIP)
        main_toolbar.addAction(zoom_out_action)
        zoom_combo = PopupTrackingComboBox(
            popup_hidden_delay_ms=VIEWER_ZOOM_POPUP_HIDDEN_DELAY_MS
        )
        zoom_combo.setEditable(True)
        zoom_combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        zoom_combo.setFixedWidth(VIEWER_ZOOM_COMBO_WIDTH)
        for _lvl in VIEWER_ZOOM_LEVELS:
            zoom_combo.addItem(f"{_lvl}%", _lvl)
        zoom_combo.setCurrentIndex(-1)
        zoom_combo.setEditText("100%")
        main_toolbar.addWidget(zoom_combo)
        page_settings_bar = PageSettingsBar(
            icon_provider=self.window.icon_provider,
            event_bus=event_bus,
            load_areas_fn=project_read_service.get_bid_areas,
            save_areas_fn=project_write_service.save_bid_areas_result,
            parent=viewer_container,
            ui_access_manager=ui_access_manager,
        )
        main_toolbar.addWidget(page_settings_bar)
        plan_view.set_selection_enabled(True)
        _undo_svc = UndoRedoService()
        if ui_access_manager:
            _undo_svc.set_write_guard(
                lambda: ui_access_manager.is_allowed(Feature.SELECT_PLAN_ITEMS)
            )
        _plan_view_handler = PlanViewActionHandler(
            plan_view=plan_view,
            ui_state_manager=ui_state_manager,
            project_data_svc=project_data_service,
            project_write_svc=project_write_service,
            annotation_write_svc=annotation_write_service,
            page_settings_bar=page_settings_bar,
            undo_svc=_undo_svc,
            event_bus=event_bus,
            ui_access_manager=ui_access_manager,
        )
        _plan_view_handler.connect_signals()
        _last_2d_zoom = [1.0]
        _popup_open = [False]
        zoom_combo.popup_shown.connect(lambda: _popup_open.__setitem__(0, True))
        zoom_combo.popup_hidden.connect(lambda: _popup_open.__setitem__(0, False))

        def _update_combo(factor: float) -> None:
            zoom_combo.blockSignals(True)
            zoom_combo.lineEdit().blockSignals(True)
            zoom_combo.setCurrentIndex(-1)
            zoom_combo.lineEdit().setText(f"{int(factor * 100)}%")
            zoom_combo.lineEdit().blockSignals(False)
            zoom_combo.blockSignals(False)

        def _on_zoom_changed(factor: float) -> None:
            _last_2d_zoom[0] = factor
            if view_stack.currentIndex() == 1:
                _update_combo(factor)

        def _on_zoom_combo_activated(index: int) -> None:
            if not _popup_open[0]:
                return
            if index < 0:
                return
            percent = zoom_combo.itemData(index)
            if percent is None:
                return
            percent = float(percent)
            if view_stack.currentIndex() == 0:
                canvas.set_zoom_percent(percent)
                _update_combo(percent / 100.0)
            else:
                plan_view.set_zoom_percent(percent)

        def _on_zoom_text_entered() -> None:
            text = zoom_combo.currentText().strip().rstrip("%")
            try:
                percent = float(text)
                if percent > 0:
                    if view_stack.currentIndex() == 0:
                        canvas.set_zoom_percent(percent)
                        _update_combo(percent / 100.0)
                    else:
                        plan_view.set_zoom_percent(percent)
            except ValueError:
                pass

        def _on_view_changed(index: int) -> None:
            btn_3d.blockSignals(True)
            btn_2d.blockSignals(True)
            btn_3d.setChecked(index == 0)
            btn_2d.setChecked(index == 1)
            btn_3d.blockSignals(False)
            btn_2d.blockSignals(False)
            canvas.setEnabled(index == 0)
            plan_view.setEnabled(index == 1)
            if index == 0:
                ui_event_handler.placement.force_exit()
                select_action.setChecked(True)
                _update_combo(canvas.get_zoom_percent() / 100.0)
            else:
                _update_combo(_last_2d_zoom[0])
            if not ui_event_handler._is_cleaning_up:
                ui_event_handler.refresh_toolbar()

        def _on_zoom_in() -> None:
            if view_stack.currentIndex() == 0:
                pct = canvas.get_zoom_percent() * VIEWER_ZOOM_FACTOR
                canvas.set_zoom_percent(pct)
                _update_combo(pct / 100.0)
            else:
                plan_view.zoom_in()

        def _on_zoom_out() -> None:
            if view_stack.currentIndex() == 0:
                pct = canvas.get_zoom_percent() / VIEWER_ZOOM_FACTOR
                canvas.set_zoom_percent(pct)
                _update_combo(pct / 100.0)
            else:
                plan_view.zoom_out()

        def _on_3d_zoom_changed(factor: float) -> None:
            if view_stack.currentIndex() == 0:
                _update_combo(factor)

        plan_view.zoom_changed.connect(_on_zoom_changed)
        canvas.zoom_changed.connect(_on_3d_zoom_changed)
        view_stack.currentChanged.connect(_on_view_changed)
        zoom_combo.activated.connect(_on_zoom_combo_activated)
        zoom_combo.lineEdit().returnPressed.connect(_on_zoom_text_entered)
        select_action.toggled.connect(
            lambda checked: plan_view.set_cursor_mode("select") if checked else None
        )

        def _on_place_toggled(checked: bool) -> None:
            if not checked:
                return
            if view_stack.currentIndex() != 1:
                select_action.setChecked(True)
                return
            if plan_view.place_condition_uid:
                return
            selected = (
                conditions_sidebar.get_selected_condition_uids()
                if conditions_sidebar
                else []
            )
            placement = ui_event_handler.placement
            if selected:
                uid = selected[-1]
                if placement.enter(uid, selected):
                    return
            selected_takeoff_condition_uid = plan_view.selected_takeoff_condition_uid()
            if selected_takeoff_condition_uid:
                if placement.enter(
                    selected_takeoff_condition_uid,
                    [selected_takeoff_condition_uid],
                ):
                    return
            select_action.setChecked(True)

        place_action.toggled.connect(_on_place_toggled)
        pan_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode("pan") if checked else None,
                canvas.set_cursor_mode("pan" if checked else "default"),
            )
        )

        def _on_annotation_tool_toggled(checked: bool, annotation_type: str) -> None:
            if not checked:
                return
            if plan_view.activate_annotation_placement(annotation_type):
                return
            select_action.setChecked(True)

        for spec in PLAN_ANNOTATION_TOOL_SPECS:
            action = plan_tool_actions[spec.action_key]
            action.toggled.connect(
                lambda checked, annotation_type=spec.annotation_type: (
                    _on_annotation_tool_toggled(checked, annotation_type)
                )
            )
        zoom_mode_action.toggled.connect(
            lambda checked: (
                plan_view.set_cursor_mode("zoom") if checked else None,
                canvas.set_cursor_mode("zoom" if checked else "default"),
            )
        )

        def _on_cursor_mode_change_requested(mode: str) -> None:
            action_map = {
                "select": select_action,
                "place": place_action,
                "pan": pan_action,
                "zoom": zoom_mode_action,
            }
            action = action_map.get(mode)
            if mode == "annotation_place":
                action = next(
                    (
                        plan_tool_actions[spec.action_key]
                        for spec in PLAN_ANNOTATION_TOOL_SPECS
                        if plan_tool_actions[spec.action_key].isChecked()
                    ),
                    plan_tool_actions[PLAN_ANNOTATION_TOOL_SPECS[0].action_key],
                )
            if action and not action.isChecked():
                action.setChecked(True)

        plan_view.cursor_mode_change_requested.connect(_on_cursor_mode_change_requested)

        def _on_fit() -> None:
            if view_stack.currentIndex() == 0:
                canvas.reset_view()
                _update_combo(1.0)
            else:
                plan_view.fit_to_page()

        fit_action.triggered.connect(_on_fit)
        zoom_in_action.triggered.connect(_on_zoom_in)
        zoom_out_action.triggered.connect(_on_zoom_out)
        plan_tools_toolbar = _PlanRibbonToolBar(self.window)
        plan_tools_toolbar.setObjectName("planToolsToolbar")
        plan_tools_toolbar.setWindowTitle(PLAN_TOOLS_TOOLBAR_LABEL)
        plan_tools_toolbar.setMovable(True)
        plan_tools_toolbar.setFloatable(True)
        plan_tools_toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        plan_tools_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        plan_tools_toolbar.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        plan_tools_toolbar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        )
        workspace_view_toolbar = _PlanRibbonToolBar(self.window)
        workspace_view_toolbar.setObjectName("viewToolbar")
        workspace_view_toolbar.setWindowTitle(VIEW_TOOLBAR_LABEL)
        workspace_view_toolbar.setMovable(True)
        workspace_view_toolbar.setFloatable(True)
        workspace_view_toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        workspace_view_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        workspace_view_toolbar.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        workspace_view_toolbar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        )
        overlay_tools_toolbar = _PlanRibbonToolBar(self.window)
        overlay_tools_toolbar.setObjectName("overlayToolsToolbar")
        overlay_tools_toolbar.setWindowTitle(OVERLAY_TOOLS_TOOLBAR_LABEL)
        overlay_tools_toolbar.setMovable(True)
        overlay_tools_toolbar.setFloatable(True)
        overlay_tools_toolbar.setOrientation(QtCore.Qt.Orientation.Vertical)
        overlay_tools_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        overlay_tools_toolbar.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        overlay_tools_toolbar.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed,
            QtWidgets.QSizePolicy.Policy.MinimumExpanding,
        )
        ann_action = QtGui.QAction(
            ANNOTATION_VIEW_WINDOW_ACTION_LABEL, viewer_container
        )
        IconManager.apply(ann_action, IconId.ANNOTATION_WINDOW)
        ann_action.setCheckable(True)
        ann_action.setToolTip(ANNOTATION_WINDOW_TITLE)
        ann_action.toggled.connect(self.window.set_annotation_window_visible)
        view_window_action = QtGui.QAction(VIEW_LABEL, viewer_container)
        IconManager.apply(view_window_action, IconId.VIEW_WINDOW)
        view_window_action.setCheckable(True)
        view_window_action.setEnabled(False)
        view_window_action.setToolTip(VIEW_WINDOW_TITLE)
        view_window_action.toggled.connect(self.window.set_view_window_visible)
        mesh_window_action = QtGui.QAction(VIEWER_3D_LABEL, viewer_container)
        IconManager.apply(mesh_window_action, IconId.VIEW_3D)
        mesh_window_action.setCheckable(True)
        mesh_window_action.setToolTip(DETACH_3D_VIEW_TOOLTIP)
        mesh_window_action.toggled.connect(self.window.set_mesh_window_visible)
        ui_event_handler.set_mesh_window_action(mesh_window_action)
        backout_action = QtGui.QAction("Backout Mode", viewer_container)
        IconManager.apply(backout_action, IconId.BACKOUT_MODE)
        _BACKOUT_ENABLED_TOOLTIP = "Create a backout in the selected area takeoff"
        _BACKOUT_DISABLED_TOOLTIP = "Select a visible area takeoff to create a backout."
        backout_action.setToolTip(_BACKOUT_DISABLED_TOOLTIP)
        backout_action.setCheckable(True)
        backout_action.setEnabled(False)
        plan_tools_toolbar.addAction(backout_action)
        move_overlay_action = QtGui.QAction(
            ACTION_MOVE_OVERLAY_IMAGE_LABEL, viewer_container
        )
        IconManager.apply(move_overlay_action, IconId.MOVE_OVERLAY_IMAGE)
        move_overlay_action.setToolTip(ACTION_MOVE_OVERLAY_IMAGE_TOOLTIP)
        move_overlay_action.setEnabled(False)
        move_overlay_action.triggered.connect(
            lambda _checked=False: plan_view.show_overlay_move_handle()
        )
        overlay_tools_toolbar.addAction(move_overlay_action)
        workspace_main_toolbar = QtWidgets.QToolBar(self.window)
        workspace_main_toolbar.setWindowTitle(MAIN_TOOLBAR_LABEL)
        workspace_main_toolbar.setMovable(True)
        workspace_main_toolbar.setFloatable(True)
        workspace_main_toolbar.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        workspace_main_toolbar.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        new_project_action = QtGui.QAction("Project", self.window)
        IconManager.apply(new_project_action, IconId.NEW_PROJECT)
        new_project_action.setToolTip("New Project")
        new_folder_action = QtGui.QAction("Folder", self.window)
        IconManager.apply(new_folder_action, IconId.NEW_FOLDER)
        new_folder_action.setToolTip("New Folder")
        new_database_action = QtGui.QAction("Database", self.window)
        IconManager.apply(new_database_action, IconId.NEW_DATABASE)
        new_database_action.setToolTip("New Database")
        new_menu = QtWidgets.QMenu(workspace_main_toolbar)
        new_menu.addAction(new_project_action)
        new_menu.addSeparator()
        new_menu.addAction(new_folder_action)
        new_menu.addAction(new_database_action)
        new_button = QtWidgets.QToolButton()
        new_button.setText("New")
        IconManager.apply(new_button, IconId.NEW_PROJECT)
        new_button.setToolTip("New Project")
        new_button.setMenu(new_menu)
        new_button.setPopupMode(
            QtWidgets.QToolButton.ToolButtonPopupMode.MenuButtonPopup
        )
        new_button.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))

        def _sync_new_button_enabled() -> None:
            new_button.setEnabled(
                new_project_action.isEnabled()
                or new_folder_action.isEnabled()
                or new_database_action.isEnabled()
            )

        new_project_action.changed.connect(_sync_new_button_enabled)
        new_folder_action.changed.connect(_sync_new_button_enabled)
        new_database_action.changed.connect(_sync_new_button_enabled)
        new_button.clicked.connect(
            lambda _checked=False: (
                new_project_action.trigger() if new_project_action.isEnabled() else None
            )
        )
        open_files_action = QtGui.QAction("Open...", self.window)
        IconManager.apply(open_files_action, IconId.OPEN_FILES)
        ShortcutManager.apply_to_action(open_files_action, "open_files")
        open_files_action.setToolTip("Open")
        copy_action = QtGui.QAction("Copy", self.window)
        IconManager.apply(copy_action, IconId.COPY)
        ShortcutManager.apply_to_action(copy_action, "copy")
        copy_action.setToolTip("Copy")
        copy_action.setEnabled(False)
        cut_action = QtGui.QAction("Cut", self.window)
        IconManager.apply(cut_action, IconId.CUT)
        ShortcutManager.apply_to_action(cut_action, "cut")
        cut_action.setToolTip("Cut")
        cut_action.setEnabled(False)
        paste_action = QtGui.QAction("Paste", self.window)
        IconManager.apply(paste_action, IconId.PASTE)
        ShortcutManager.apply_to_action(paste_action, "paste")
        paste_action.setToolTip("Paste")
        paste_action.setEnabled(False)
        duplicate_action = QtGui.QAction("Duplicate", self.window)
        IconManager.apply(duplicate_action, IconId.DUPLICATE)
        ShortcutManager.apply_to_action(duplicate_action, "duplicate")
        duplicate_action.setToolTip("Duplicate")
        duplicate_action.setEnabled(False)
        delete_action = QtGui.QAction("Delete", self.window)
        IconManager.apply(delete_action, IconId.DELETE)
        ShortcutManager.apply_to_action(delete_action, "delete")
        delete_action.setToolTip("Delete")
        delete_action.setEnabled(False)
        undo_action = QtGui.QAction("Undo", self.window)
        IconManager.apply(undo_action, IconId.UNDO)
        ShortcutManager.apply_to_action(undo_action, "undo")
        undo_action.setToolTip("Undo")
        undo_action.setEnabled(False)
        redo_action = QtGui.QAction("Redo", self.window)
        IconManager.apply(redo_action, IconId.REDO)
        ShortcutManager.apply_to_action(redo_action, "redo")
        redo_action.setToolTip("Redo")
        redo_action.setEnabled(False)
        workspace_main_toolbar.addWidget(new_button)
        workspace_main_toolbar.addAction(open_files_action)
        workspace_main_toolbar.addAction(copy_action)
        workspace_main_toolbar.addAction(cut_action)
        workspace_main_toolbar.addAction(paste_action)
        workspace_main_toolbar.addAction(duplicate_action)
        workspace_main_toolbar.addAction(delete_action)
        workspace_main_toolbar.addAction(undo_action)
        workspace_main_toolbar.addAction(redo_action)
        cover_sheet_button = QtWidgets.QToolButton()
        cover_sheet_button.setText("Cover Sheet")
        IconManager.apply(cover_sheet_button, IconId.COVER_SHEET)
        cover_sheet_button.setToolButtonStyle(
            QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        cover_sheet_button.setToolTip("Show Cover Sheet")
        cover_sheet_button.setEnabled(False)
        workspace_main_toolbar.addWidget(cover_sheet_button)
        self.window.addToolBar(
            QtCore.Qt.ToolBarArea.TopToolBarArea, workspace_main_toolbar
        )
        viewer_container_layout.addWidget(view_toolbar)
        viewer_container_layout.addWidget(main_toolbar)
        viewer_container_layout.addWidget(view_stack, 1)
        self.window.addToolBar(
            QtCore.Qt.ToolBarArea.RightToolBarArea, plan_tools_toolbar
        )
        self.window.addToolBar(
            QtCore.Qt.ToolBarArea.RightToolBarArea, overlay_tools_toolbar
        )
        self.window.addToolBar(
            QtCore.Qt.ToolBarArea.RightToolBarArea, workspace_view_toolbar
        )
        plan_tools_toolbar.setVisible(False)
        overlay_tools_toolbar.setVisible(False)
        workspace_view_toolbar.setVisible(False)
        conditions_sidebar = ConditionsSidebar(
            takeoff_tab, uom_label_fn=project_read_service.get_uom_label
        )
        bid_layers_sidebar = BidLayersSidebar(takeoff_tab)
        left_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, takeoff_tab)
        left_splitter.addWidget(conditions_sidebar)
        left_splitter.addWidget(bid_layers_sidebar)
        left_splitter.setMinimumWidth(SIDEBAR_MIN_WIDTH)
        left_splitter.setStretchFactor(0, 1)
        left_splitter.setStretchFactor(1, 1)
        takeoff_splitter = QtWidgets.QSplitter(
            QtCore.Qt.Orientation.Horizontal, takeoff_tab
        )
        takeoff_splitter.addWidget(left_splitter)
        takeoff_splitter.addWidget(viewer_container)
        takeoff_splitter.setStretchFactor(0, 0)
        takeoff_splitter.setStretchFactor(1, 1)

        def _sync_left_sidebar_visibility() -> None:
            left_splitter.setVisible(
                not conditions_sidebar.isHidden() or not bid_layers_sidebar.isHidden()
            )

        layers_toggle_action = QtGui.QAction("Layers Sidebar", viewer_container)
        layers_toggle_action.setCheckable(True)
        layers_toggle_action.setChecked(not bid_layers_sidebar.isHidden())
        layers_toggle_action.setToolTip("Hide/Show Layers Sidebar")
        IconManager.apply(layers_toggle_action, IconId.LAYERS_SIDEBAR)

        def _set_layers_visible(visible: bool) -> None:
            bid_layers_sidebar.setVisible(visible)
            _sync_left_sidebar_visibility()

        layers_toggle_action.toggled.connect(_set_layers_visible)
        conditions_toggle_action = QtGui.QAction("Conditions Sidebar", viewer_container)
        conditions_toggle_action.setCheckable(True)
        conditions_toggle_action.setChecked(not conditions_sidebar.isHidden())
        conditions_toggle_action.setToolTip("Hide/Show Conditions Sidebar")
        IconManager.apply(conditions_toggle_action, IconId.CONDITIONS_SIDEBAR)

        def _set_conditions_visible(visible: bool) -> None:
            conditions_sidebar.setVisible(visible)
            _sync_left_sidebar_visibility()

        conditions_toggle_action.toggled.connect(_set_conditions_visible)
        workspace_view_toolbar.addAction(conditions_toggle_action)
        workspace_view_toolbar.addAction(layers_toggle_action)
        workspace_view_toolbar.addAction(ann_action)
        workspace_view_toolbar.addAction(view_window_action)
        workspace_view_toolbar.addAction(mesh_window_action)
        takeoff_layout.addWidget(takeoff_splitter)
        _sync_left_sidebar_visibility()
        tab_widget.addTab(takeoff_tab, "Takeoff")
        tab_widget.setTabVisible(TAB_INDEX_TAKEOFF, False)
        central_layout.addWidget(tab_widget)
        status_panel = StatusPanel(central_widget)

        def _sync_plan_toolbar_heights() -> None:
            docked_toolbars = (
                plan_tools_toolbar,
                overlay_tools_toolbar,
                workspace_view_toolbar,
            )
            if any(
                toolbar.isFloating()
                or self.window.toolBarArea(toolbar)
                != QtCore.Qt.ToolBarArea.RightToolBarArea
                for toolbar in docked_toolbars
            ):
                for toolbar in docked_toolbars:
                    toolbar.set_preferred_docked_height(0)
                return
            host = self.window.centralWidget() or self.window
            available_height = host.height()
            if available_height <= 0:
                available_height = self.window.contentsRect().height()
            if available_height <= 0:
                return
            target_height = max(1, available_height // len(docked_toolbars))
            for toolbar in docked_toolbars:
                toolbar.set_preferred_docked_height(target_height)

        def _schedule_plan_toolbar_height_sync(*_args) -> None:
            QtCore.QTimer.singleShot(0, _sync_plan_toolbar_heights)

        toolbar_layout_sync_filter = _PlanToolbarLayoutSyncFilter(
            _sync_plan_toolbar_heights, self.window
        )
        self.window.installEventFilter(toolbar_layout_sync_filter)
        plan_tools_toolbar.topLevelChanged.connect(_schedule_plan_toolbar_height_sync)
        overlay_tools_toolbar.topLevelChanged.connect(
            _schedule_plan_toolbar_height_sync
        )
        workspace_view_toolbar.topLevelChanged.connect(
            _schedule_plan_toolbar_height_sync
        )
        plan_tools_toolbar.visibilityChanged.connect(_schedule_plan_toolbar_height_sync)
        overlay_tools_toolbar.visibilityChanged.connect(
            _schedule_plan_toolbar_height_sync
        )
        workspace_view_toolbar.visibilityChanged.connect(
            _schedule_plan_toolbar_height_sync
        )

        def _on_area_placement_in_progress(in_progress: bool) -> None:
            left_splitter.setEnabled(not in_progress)
            main_toolbar.setEnabled(not in_progress)
            view_toolbar.setEnabled(not in_progress)
            tab_widget.tabBar().setEnabled(not in_progress)
            workspace_main_toolbar.setEnabled(not in_progress)
            plan_tools_toolbar.setEnabled(not in_progress)
            overlay_tools_toolbar.setEnabled(not in_progress)
            workspace_view_toolbar.setEnabled(not in_progress)
            self.window.menuBar().setEnabled(not in_progress)
            if in_progress:
                self.window.setCursor(QtCore.Qt.CursorShape.CrossCursor)
            else:
                self.window.unsetCursor()

        plan_view.area_placement_in_progress.connect(_on_area_placement_in_progress)
        workspace_main_toolbar.setObjectName("mainToolbar")
        _sync_plan_toolbar_heights()
        return ComponentBundle(
            central_widget=central_widget,
            tab_widget=tab_widget,
            takeoff_tab=takeoff_tab,
            project_view=project_view,
            takeoff_sidebar=page_combo,
            conditions_sidebar=conditions_sidebar,
            opengl_viewer=canvas,
            plan_view=plan_view,
            view_stack=view_stack,
            status_panel=status_panel,
            plan_tools_toolbar=plan_tools_toolbar,
            overlay_tools_toolbar=overlay_tools_toolbar,
            view_toolbar=workspace_view_toolbar,
            main_toolbar=workspace_main_toolbar,
            view_2d_action=btn_2d_action,
            view_3d_action=btn_3d_action,
            new_project_action=new_project_action,
            new_folder_action=new_folder_action,
            new_database_action=new_database_action,
            open_files_action=open_files_action,
            copy_action=copy_action,
            cut_action=cut_action,
            paste_action=paste_action,
            delete_action=delete_action,
            undo_action=undo_action,
            redo_action=redo_action,
            duplicate_action=duplicate_action,
            zoom_in_action=zoom_in_action,
            zoom_out_action=zoom_out_action,
            reset_view_action=fit_action,
            next_page_action=next_page_action,
            previous_page_action=previous_page_action,
            plan_tool_actions=plan_tool_actions,
            select_action=select_action,
            pan_action=pan_action,
            zoom_mode_action=zoom_mode_action,
            backout_action=backout_action,
            move_overlay_action=move_overlay_action,
            cover_sheet_button=cover_sheet_button,
            page_settings_bar=page_settings_bar,
            bid_layers_sidebar=bid_layers_sidebar,
            takeoff_splitter=takeoff_splitter,
            left_splitter=left_splitter,
            layers_toggle_action=layers_toggle_action,
            conditions_toggle_action=conditions_toggle_action,
            annotation_window_action=ann_action,
            view_window_action=view_window_action,
            place_action=place_action,
            mesh_window_action=mesh_window_action,
            plan_view_handler=_plan_view_handler,
            undo_service=_undo_svc,
        )

    def create_menu(
        self,
        config_service,
        ui_state_manager,
        handlers,
        ui_access_manager,
        project_data_service,
        export_service,
        project_read_service,
        project_write_service,
        infrastructure_provider,
        event_bus,
        file_loading_service,
        create_new_database_fn,
        shared_actions=None,
    ) -> MenuController:
        menu_controller = MenuController(
            self.window,
            self.window.icon_provider,
            config_service,
            ui_state_manager,
            handlers,
            ui_access_manager,
            project_data_service=project_data_service,
            export_service=export_service,
            project_read_service=project_read_service,
            project_write_service=project_write_service,
            infrastructure_provider=infrastructure_provider,
            event_bus=event_bus,
            file_loading_service=file_loading_service,
            create_new_database_fn=create_new_database_fn,
            shared_actions=shared_actions,
        )
        menu_bar = menu_controller.create_menu()
        self.window.setMenuBar(menu_bar)
        return menu_controller
