import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from ....application.dtos.annotation_creation_factory import AnnotationCreationFactory
from ....application.dtos.insert_annotation_spec_dto import InsertAnnotationSpec
from ....application.dtos.page_view_dto import PageViewDto
from ....application.dtos.plan_view_renderers_dto import PlanViewRenderers
from ....application.events.app_events import AppEvents
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_window_icon_provider import IWindowIconProvider
from ....domain.entities.annotation import (
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_TEXT,
    int_color_to_hex,
)
from ....domain.entities.annotation_style import AnnotationStyle
from ....domain.entities.annotation_view import AnnotationView
from ....domain.entities.bid import Bid
from ....domain.entities.config import Config
from ...actions.action_ids import ACTION_COPY, ACTION_PASTE
from ...adapters.hotlink_event_adapter import HotlinkEventAdapter
from ...components.page_combo import SinglePageComboBox
from ...components.plan_view.view import TakeoffPlanView
from ...components.resizable_combo import ResizableComboBox
from ...components.viewer_cursors import make_zoom_cursor
from ...config import (
    ACTION_NEXT_PAGE_TOOLTIP,
    ACTION_PAN_TOOLTIP,
    ACTION_PREVIOUS_PAGE_TOOLTIP,
    ACTION_RESET_VIEW_TOOLTIP,
    ACTION_SELECT_TOOLTIP,
    ACTION_ZOOM_IN_TOOLTIP,
    ACTION_ZOOM_OUT_TOOLTIP,
    ACTION_ZOOM_TOOLTIP,
    COMPACT_MARGINS,
    COMPACT_SPACING,
    DEFAULT_ICON_SIZE,
    INLINE_MARGINS,
    NAMED_VIEWS_TOOLTIP,
    NO_MARGINS,
    NO_SPACING,
    SCALE_LABEL,
    SCALE_TOOLTIP,
    VIEW_LABEL,
)
from ...dialogs.select_named_view_dialog import SelectNamedViewDialog
from ...managers.icon_manager import IconId, IconManager
from ...modes.cursor import (
    CURSOR_MODE_ANNOTATION_PLACE,
    CURSOR_MODE_PAN,
    CURSOR_MODE_SELECT,
    CURSOR_MODE_ZOOM,
)
from ...services.selection_clipboard_service import SelectionClipboardService
from ...services.selection_commands import (
    DeleteAnnotationsCommand,
    InsertAnnotationsCommand,
    PasteAnnotationsCommand,
)
from ...utils.annotation_defaults import (
    build_placed_annotation_spec,
    get_annotation_style_for_tool,
    set_annotation_style_for_tool,
)
from ...utils.annotation_delete import (
    NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
    plan_named_view_hotlink_delete,
    skipped_named_view_selection_keys,
)
from ...utils.annotation_paste import (
    annotation_paste_translation,
    translate_annotation_position,
)
from ...utils.annotation_style_controls import (
    apply_annotation_tool_icon_color,
    create_annotation_tool_split_button,
)
from ...utils.messagebox import confirm
from ...utils.named_view_focus import focus_plan_view_on_named_view
from ...utils.named_view_validation import (
    named_view_name_exists,
    show_duplicate_named_view_name,
)
from ...utils.plan_tool_registry import PlanToolSpec
from ...utils.scales import ALL_SCALES

NamedViewEntry = Tuple[str, str, str, str]
_PAGE_LOAD_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class DetachedPageViewWindowConfig:
    window_title: str
    show_scale_combo: bool
    show_select_tool: bool
    default_cursor_mode: str
    allow_annotation_editing: bool
    dropdown_state_key: str
    annotation_tool_specs: Tuple[PlanToolSpec, ...] = ()


class DetachedPageViewWindow(QtWidgets.QMainWindow):
    dropdown_size_changed = QtCore.Signal()
    _PAGE_UID_ROLE = QtCore.Qt.ItemDataRole.UserRole
    _annotation_write_coordinator = None

    def __init__(
        self,
        icon_provider: IWindowIconProvider,
        view: AnnotationView,
        event_bus,
        page_data: PageViewDto,
        coord_system: ICoordinateTransformer,
        color_service: IColorService,
        renderers: PlanViewRenderers,
        config: DetachedPageViewWindowConfig,
        bid: Optional[Bid] = None,
        pages_with_takeoffs: Optional[set[str]] = None,
        on_page_selected: Optional[Callable[[str], None]] = None,
        named_views: Optional[List[NamedViewEntry]] = None,
        on_named_view_selected: Optional[Callable[[str, str], None]] = None,
        on_scale_changed: Optional[Callable[[str, float, float], None]] = None,
        annotation_write_service=None,
        file_path: Optional[str] = None,
        undo_service=None,
        initial_geometry: Optional[QtCore.QByteArray] = None,
        initial_is_maximized: bool = False,
        initial_is_fullscreen: bool = False,
        navigation_source: str = "unknown",
        show_page_index: bool = False,
        show_sheet_number: bool = False,
        roping_selection_method: str = Config.DEFAULT_ROPING_SELECTION_METHOD,
        disable_high_resolution_images: bool = False,
        intelligent_paste_enabled: bool = True,
        advanced_mouse_controls_enabled: bool = True,
        default_auto_zoom_level: int = 0,
        use_full_window_crosshairs: bool = False,
        crosshair_color: str = "#00ff00",
        crosshair_line_thickness: int = 1,
        mouse_unpressed_snap_angle: int = 15,
        mouse_pressed_snap_angle: int = 0,
        snap_to_grid_enabled: bool = True,
        snap_to_grid_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX,
        snap_to_pdf_lines_enabled: bool = True,
        snap_to_pdf_lines_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX,
        snap_to_takeoffs_enabled: bool = True,
        snap_to_takeoffs_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX,
        snap_to_right_angle_enabled: bool = False,
        snap_to_right_angle_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX,
        annotation_style_getter: Optional[Callable[[str], AnnotationStyle]] = None,
        annotation_style_setter: Optional[Callable[..., AnnotationStyle]] = None,
        linked_hotlink_resolver: Optional[Callable[[set[str]], List]] = None,
        annotation_write_coordinator=None,
        parent: Optional[QtWidgets.QWidget] = None,
    ):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.icon_provider = icon_provider
        self.view: Optional[AnnotationView] = view
        self.event_bus = event_bus
        self.page_data: Optional[PageViewDto] = page_data
        self._color_service = color_service
        self._renderers = renderers
        self._config = config
        self._pages_with_takeoffs: set[str] = set(pages_with_takeoffs or ())
        self._on_page_selected: Optional[Callable[[str], None]] = on_page_selected
        self._named_views: List[NamedViewEntry] = list(named_views or [])
        self._on_named_view_selected: Optional[Callable[[str, str], None]] = (
            on_named_view_selected
        )
        self._on_scale_changed: Optional[Callable[[str, float, float], None]] = (
            on_scale_changed
        )
        self._ann_write_svc = annotation_write_service
        self._annotation_write_coordinator = annotation_write_coordinator
        self._file_path: Optional[str] = file_path
        self._undo_svc = undo_service
        self._annotation_clipboard_svc: Optional[SelectionClipboardService] = (
            SelectionClipboardService() if config.allow_annotation_editing else None
        )
        self.plan_view: Optional[TakeoffPlanView] = None
        self._read_only: bool = False
        self._is_closing: bool = False
        self._show_timer: Optional[QtCore.QTimer] = None
        self._initial_show_requested: bool = False
        self._initial_page_geometry_ready: bool = False
        self._named_view_resize_focus_timer: Optional[QtCore.QTimer] = None
        self._pending_named_view_resize_focus: bool = False
        self._named_view_blank_canvas_active: bool = False
        self._page_view_states: dict[str, tuple[float, float, float]] = {}
        self._hotlink_adapter: Optional[HotlinkEventAdapter] = None
        self._initial_geometry = QtCore.QByteArray()
        self._initial_show_maximized = False
        self._initial_show_fullscreen = False
        self._navigation_source = navigation_source
        self._show_page_index = bool(show_page_index)
        self._show_sheet_number = bool(show_sheet_number)
        self._roping_selection_method = roping_selection_method
        self._disable_high_resolution_images = bool(disable_high_resolution_images)
        self._intelligent_paste_enabled = bool(intelligent_paste_enabled)
        self._advanced_mouse_controls_enabled = bool(advanced_mouse_controls_enabled)
        self._default_auto_zoom_level = int(default_auto_zoom_level)
        self._use_full_window_crosshairs = bool(use_full_window_crosshairs)
        self._crosshair_color = crosshair_color
        self._crosshair_line_thickness = int(crosshair_line_thickness)
        self._mouse_unpressed_snap_angle = int(mouse_unpressed_snap_angle)
        self._mouse_pressed_snap_angle = int(mouse_pressed_snap_angle)
        self._snap_to_grid_enabled = bool(snap_to_grid_enabled)
        self._snap_to_grid_threshold_px = int(snap_to_grid_threshold_px)
        self._snap_to_pdf_lines_enabled = bool(snap_to_pdf_lines_enabled)
        self._snap_to_pdf_lines_threshold_px = int(snap_to_pdf_lines_threshold_px)
        self._snap_to_takeoffs_enabled = bool(snap_to_takeoffs_enabled)
        self._snap_to_takeoffs_threshold_px = int(snap_to_takeoffs_threshold_px)
        self._snap_to_right_angle_enabled = bool(snap_to_right_angle_enabled)
        self._snap_to_right_angle_threshold_px = int(snap_to_right_angle_threshold_px)
        self._scale_combo: Optional[QtWidgets.QComboBox] = None
        self._btn_select: Optional[QtWidgets.QToolButton] = None
        self._annotation_tool_buttons: dict[str, QtWidgets.QToolButton] = {}
        self._annotation_style_getter = (
            annotation_style_getter or get_annotation_style_for_tool
        )
        self._annotation_style_setter = (
            annotation_style_setter or set_annotation_style_for_tool
        )
        self._linked_hotlink_resolver = linked_hotlink_resolver
        self.setWindowTitle(config.window_title)
        self.setWindowFlags(
            QtCore.Qt.WindowType.Window
            | QtCore.Qt.WindowType.WindowMinimizeButtonHint
            | QtCore.Qt.WindowType.WindowMaximizeButtonHint
            | QtCore.Qt.WindowType.WindowCloseButtonHint
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.icon_provider.set_window_icon(self)
        self._setup_ui()
        self.plan_view.page_geometry_ready.connect(self._on_page_geometry_ready)
        self.plan_view.page_fully_loaded.connect(self._on_page_loaded)
        self.plan_view.page_view_state_changed.connect(self._on_page_view_state_changed)
        if bid:
            self._populate_page_combo(bid)
        if self._named_views:
            self._populate_named_view_combo()
        self.set_initial_window_state(
            initial_geometry or QtCore.QByteArray(),
            initial_is_maximized,
            initial_is_fullscreen,
        )
        self._show_timer = QtCore.QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._on_show_timeout)
        self._named_view_resize_focus_timer = QtCore.QTimer(self)
        self._named_view_resize_focus_timer.setSingleShot(True)
        self._named_view_resize_focus_timer.timeout.connect(
            self._apply_named_view_focus_after_resize
        )
        self.load_view(view, navigation_source=navigation_source)

    def set_initial_window_state(
        self,
        geometry: QtCore.QByteArray,
        is_maximized: bool,
        is_fullscreen: bool = False,
    ) -> None:
        self._initial_geometry = QtCore.QByteArray(geometry)
        self._initial_show_maximized = bool(is_maximized)
        self._initial_show_fullscreen = bool(is_fullscreen)

    @staticmethod
    def _constrained_geometry_for_available_screen(
        frame: QtCore.QRect,
        available: QtCore.QRect,
        minimum_width: int,
        minimum_height: int,
    ) -> QtCore.QRect:
        width = min(max(frame.width(), minimum_width, 1), available.width())
        height = min(max(frame.height(), minimum_height, 1), available.height())
        max_x = available.right() - width + 1
        max_y = available.bottom() - height + 1
        x = min(max(frame.x(), available.x()), max_x)
        y = min(max(frame.y(), available.y()), max_y)
        return QtCore.QRect(x, y, width, height)

    def _restore_initial_geometry(self) -> None:
        if not self._initial_geometry or self._initial_geometry.isEmpty():
            return
        self.restoreGeometry(self._initial_geometry)
        self._constrain_initial_geometry_to_single_screen()

    def _available_geometry_for_initial_show(self) -> Optional[QtCore.QRect]:
        center = self.frameGeometry().center()
        screen = QtWidgets.QApplication.screenAt(center)
        if screen is None:
            screen = self.screen()
        if screen is None and self.parentWidget() is not None:
            screen = self.parentWidget().screen()
        if screen is None:
            screen = QtWidgets.QApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else None

    def _constrain_initial_geometry_to_single_screen(self) -> None:
        available = self._available_geometry_for_initial_show()
        if available is None or available.isEmpty():
            return
        frame = self.frameGeometry()
        if available.contains(frame):
            return
        self.setGeometry(
            self._constrained_geometry_for_available_screen(
                frame, available, self.minimumWidth(), self.minimumHeight()
            )
        )

    def show_when_page_ready(self) -> None:
        if self._is_closing or self.isVisible():
            return
        self._initial_show_requested = True
        if self._initial_page_geometry_ready:
            self._show_initial_window()
        elif self._show_timer is not None and not self._show_timer.isActive():
            self._show_timer.start(_PAGE_LOAD_TIMEOUT_MS)

    def _setup_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(*NO_MARGINS)
        main_layout.setSpacing(NO_SPACING)
        nav_bar = QtWidgets.QWidget()
        nav_bar.setObjectName("detachedPageViewNavigationToolbar")
        nav_layout = QtWidgets.QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(*COMPACT_MARGINS)
        nav_layout.setSpacing(COMPACT_SPACING)
        annotation_bar = None
        annotation_layout = None
        if self._config.annotation_tool_specs:
            nav_layout.setContentsMargins(
                COMPACT_MARGINS[0], COMPACT_MARGINS[1], COMPACT_MARGINS[2], 0
            )
            annotation_bar = QtWidgets.QWidget()
            annotation_bar.setObjectName("detachedPageViewAnnotationToolbar")
            annotation_layout = QtWidgets.QHBoxLayout(annotation_bar)
            annotation_layout.setContentsMargins(*INLINE_MARGINS)
            annotation_layout.setSpacing(COMPACT_SPACING)
        self._btn_prev = QtWidgets.QPushButton()
        IconManager.apply(self._btn_prev, IconId.PREVIOUS_PAGE)
        self._btn_prev.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        self._btn_prev.setFixedWidth(28)
        self._btn_prev.setToolTip(ACTION_PREVIOUS_PAGE_TOOLTIP)
        self._btn_prev.clicked.connect(self._go_prev_page)
        self._page_combo = SinglePageComboBox()
        self._page_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._page_combo.setMinimumWidth(100)
        self._btn_next = QtWidgets.QPushButton()
        IconManager.apply(self._btn_next, IconId.NEXT_PAGE)
        self._btn_next.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        self._btn_next.setFixedWidth(28)
        self._btn_next.setToolTip(ACTION_NEXT_PAGE_TOOLTIP)
        self._btn_next.clicked.connect(self._go_next_page)
        self._named_view_combo = ResizableComboBox()
        self._named_view_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._named_view_combo.setMinimumWidth(100)
        self._named_view_combo.setToolTip(NAMED_VIEWS_TOOLTIP)
        nav_layout.addWidget(self._btn_prev)
        nav_layout.addWidget(self._page_combo, 1)
        nav_layout.addWidget(self._btn_next)
        nav_layout.addWidget(QtWidgets.QLabel(VIEW_LABEL))
        nav_layout.addWidget(self._named_view_combo, 1)
        if self._config.show_scale_combo:
            self._scale_combo = QtWidgets.QComboBox()
            self._scale_combo.setFixedWidth(120)
            self._scale_combo.setToolTip(SCALE_TOOLTIP)
            for sf1, sf2, label in ALL_SCALES:
                self._scale_combo.addItem(label, (sf1, sf2))
            self._scale_combo.setCurrentIndex(-1)
            nav_layout.addWidget(QtWidgets.QLabel(SCALE_LABEL))
            nav_layout.addWidget(self._scale_combo)
        btn_size = QtCore.QSize(*DEFAULT_ICON_SIZE)
        self._cursor_group = QtWidgets.QButtonGroup(nav_bar)
        self._cursor_group.setExclusive(True)
        if self._config.show_select_tool:
            self._btn_select = QtWidgets.QToolButton()
            IconManager.apply(self._btn_select, IconId.SELECT_TOOL)
            self._btn_select.setIconSize(btn_size)
            self._btn_select.setCheckable(True)
            self._btn_select.setToolTip(ACTION_SELECT_TOOLTIP)
            self._cursor_group.addButton(self._btn_select)
            nav_layout.addWidget(self._btn_select)
        for spec in self._config.annotation_tool_specs:
            button = QtWidgets.QToolButton()
            IconManager.apply(button, spec.icon_id)
            button.setIconSize(btn_size)
            button.setCheckable(True)
            button.setToolTip(spec.tooltip)
            button.setEnabled(self._annotation_placement_enabled())
            self._cursor_group.addButton(button)
            self._annotation_tool_buttons[spec.action_key] = button
            split_button, _ = create_annotation_tool_split_button(
                annotation_bar,
                button,
                lambda annotation_type=spec.annotation_type: (
                    self._annotation_style_getter(annotation_type)
                ),
                lambda annotation_type=spec.annotation_type, **style_updates: (
                    self._annotation_style_setter(
                        annotation_type,
                        **style_updates,
                    )
                ),
                icon_size=btn_size,
                annotation_type=spec.annotation_type,
            )
            annotation_layout.addWidget(split_button)

            def _activate_annotation_tool(
                checked: bool, annotation_type: str = spec.annotation_type
            ) -> None:
                if not checked:
                    return
                if not self._activate_annotation_tool(annotation_type):
                    self._set_default_cursor_mode()

            button.toggled.connect(_activate_annotation_tool)
        if self._config.annotation_tool_specs:
            apply_annotation_tool_icon_color(self._annotation_tool_buttons)
            annotation_layout.addStretch()
        self._btn_pan = QtWidgets.QToolButton()
        IconManager.apply(self._btn_pan, IconId.PAN_TOOL)
        self._btn_pan.setIconSize(btn_size)
        self._btn_pan.setCheckable(True)
        self._btn_pan.setToolTip(ACTION_PAN_TOOLTIP)
        self._cursor_group.addButton(self._btn_pan)
        nav_layout.addWidget(self._btn_pan)
        self._btn_zoom_mode = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_mode, IconId.ZOOM_TOOL)
        self._btn_zoom_mode.setIconSize(btn_size)
        self._btn_zoom_mode.setCheckable(True)
        self._btn_zoom_mode.setToolTip(ACTION_ZOOM_TOOLTIP)
        self._cursor_group.addButton(self._btn_zoom_mode)
        nav_layout.addWidget(self._btn_zoom_mode)
        self._btn_fit = QtWidgets.QToolButton()
        IconManager.apply(self._btn_fit, IconId.RESET_VIEW)
        self._btn_fit.setIconSize(btn_size)
        self._btn_fit.setToolTip(ACTION_RESET_VIEW_TOOLTIP)
        self._btn_zoom_in = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_in, IconId.ZOOM_IN)
        self._btn_zoom_in.setIconSize(btn_size)
        self._btn_zoom_in.setToolTip(ACTION_ZOOM_IN_TOOLTIP)
        self._btn_zoom_out = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_out, IconId.ZOOM_OUT)
        self._btn_zoom_out.setIconSize(btn_size)
        self._btn_zoom_out.setToolTip(ACTION_ZOOM_OUT_TOOLTIP)
        nav_layout.addWidget(self._btn_fit)
        nav_layout.addWidget(self._btn_zoom_in)
        nav_layout.addWidget(self._btn_zoom_out)
        main_layout.addWidget(nav_bar)
        if annotation_bar is not None:
            main_layout.addWidget(annotation_bar)
        self.plan_view = TakeoffPlanView(
            self._color_service,
            self._renderers.rendering_service,
            self._renderers.load_coordinator,
            self._renderers.takeoff_renderer,
            self._renderers.annotation_renderer,
            self._renderers.linear_geometry,
            self._renderers.prefetch_coordinator,
        )
        self.plan_view.set_selection_enabled(self._selection_enabled())
        self.plan_view.set_annotation_only_selection(
            self._config.allow_annotation_editing
        )
        self.plan_view.set_text_annotation_inline_edit_enabled(
            self._selection_enabled()
        )
        self.plan_view.set_annotation_placement_allowed_fn(
            self._annotation_placement_enabled
        )
        self.plan_view.set_named_view_name_validator(self._validate_named_view_name)
        self.plan_view.set_roping_selection_method(self._roping_selection_method)
        self.plan_view.set_disable_high_resolution_images(
            self._disable_high_resolution_images
        )
        self.plan_view.set_intelligent_paste_enabled(self._intelligent_paste_enabled)
        self.plan_view.set_advanced_mouse_controls_enabled(
            self._advanced_mouse_controls_enabled
        )
        self.plan_view.set_default_auto_zoom_level(self._default_auto_zoom_level)
        self.plan_view.set_full_window_crosshairs(
            self._use_full_window_crosshairs,
            self._crosshair_color,
            self._crosshair_line_thickness,
        )
        self.plan_view.set_mouse_snap_angles(
            self._mouse_unpressed_snap_angle,
            self._mouse_pressed_snap_angle,
        )
        self._apply_plan_view_snap_preferences()
        main_layout.addWidget(self.plan_view, 1)
        self._hotlink_adapter = HotlinkEventAdapter(self.event_bus)
        self._hotlink_adapter.set_plan_view(self.plan_view)
        self.plan_view.positions_flushed.connect(self._on_positions_flushed)
        self.plan_view.annotation_text_properties_flushed.connect(
            self._on_annotation_text_properties_flushed
        )
        self.plan_view.annotation_text_and_positions_flushed.connect(
            self._on_annotation_text_and_positions_flushed
        )
        self.plan_view.annotation_styles_flushed.connect(
            self._on_annotation_styles_flushed
        )
        self.plan_view.elements_deleted.connect(self._on_elements_deleted)
        self.plan_view.annotation_created.connect(self._on_annotation_created)
        self.plan_view.text_annotation_created.connect(self._on_text_annotation_created)
        self.plan_view.named_view_created.connect(self._on_named_view_created)
        self.plan_view.hotlink_placement_requested.connect(
            self._on_hotlink_placement_requested
        )
        if self._annotation_clipboard_svc is not None:
            self.plan_view.copy_requested.connect(self._on_copy_requested)
            self.plan_view.paste_requested.connect(self._on_paste_requested)
            self.plan_view.set_context_menu_command_handlers(
                self._trigger_context_menu_command,
                self._context_menu_action_state,
            )
        if self._undo_svc is not None:
            self.plan_view.undo_requested.connect(self._undo_svc.undo)
            self.plan_view.redo_requested.connect(self._undo_svc.redo)
        self._page_combo.page_activated.connect(self._on_page_activated)
        self._page_combo.popup_size_changed.connect(self.dropdown_size_changed)
        self._named_view_combo.popup_size_changed.connect(self.dropdown_size_changed)
        self._named_view_combo.currentIndexChanged.connect(
            self._on_named_view_combo_changed
        )
        if self._scale_combo is not None:
            self._scale_combo.activated.connect(self._on_scale_activated)
        if self._btn_select is not None:
            self._btn_select.toggled.connect(
                lambda checked: (
                    self.plan_view.set_cursor_mode(CURSOR_MODE_SELECT)
                    if checked
                    else None
                )
            )
        self._btn_pan.toggled.connect(
            lambda checked: (
                self.plan_view.set_cursor_mode(CURSOR_MODE_PAN) if checked else None
            )
        )
        self._btn_fit.clicked.connect(self.plan_view.reset_view)
        self._btn_zoom_in.clicked.connect(self.plan_view.zoom_in)
        self._btn_zoom_out.clicked.connect(self.plan_view.zoom_out)
        self._btn_zoom_mode.toggled.connect(
            lambda checked: (
                self.plan_view.set_cursor_mode(CURSOR_MODE_ZOOM) if checked else None
            )
        )
        self.plan_view.cursor_mode_change_requested.connect(
            self._on_cursor_mode_change_requested
        )
        self.plan_view.set_zoom_cursor(make_zoom_cursor())
        self._set_default_cursor_mode()

    def _set_default_cursor_mode(self) -> None:
        button_map = {
            CURSOR_MODE_SELECT: self._btn_select,
            CURSOR_MODE_PAN: self._btn_pan,
            CURSOR_MODE_ZOOM: self._btn_zoom_mode,
        }
        button = button_map.get(self._config.default_cursor_mode) or self._btn_pan
        button.setChecked(True)

    def _on_cursor_mode_change_requested(self, mode: str) -> None:
        button_map = {
            CURSOR_MODE_SELECT: self._btn_select,
            CURSOR_MODE_PAN: self._btn_pan,
            CURSOR_MODE_ZOOM: self._btn_zoom_mode,
        }
        button = button_map.get(mode)
        if button is not None:
            if not button.isChecked():
                button.setChecked(True)
            return
        if mode != CURSOR_MODE_ANNOTATION_PLACE:
            return
        annotation_type = self.plan_view.annotation_place_type
        for spec in self._config.annotation_tool_specs:
            button = self._annotation_tool_buttons.get(spec.action_key)
            if button is not None and spec.annotation_type == annotation_type:
                if not button.isChecked():
                    button.setChecked(True)
                return
        for button in self._annotation_tool_buttons.values():
            if button.isChecked():
                return
        if self._annotation_tool_buttons:
            next(iter(self._annotation_tool_buttons.values())).setChecked(True)

    def _selection_enabled(self) -> bool:
        return self._config.allow_annotation_editing and not self._read_only

    def _annotation_placement_enabled(self) -> bool:
        return self._selection_enabled() and bool(
            self.page_data
            and self.page_data.is_layer_visible(self.page_data.annotation_layer_uid)
        )

    def _refresh_annotation_tool_access(self) -> None:
        enabled = self._annotation_placement_enabled()
        for button in self._annotation_tool_buttons.values():
            button.setEnabled(enabled)
        if not enabled and self.plan_view and self.plan_view.annotation_place_type:
            self._set_default_cursor_mode()

    def _activate_annotation_tool(self, annotation_type: str) -> bool:
        if not self._annotation_placement_enabled() or self.plan_view is None:
            return False
        return bool(self.plan_view.activate_annotation_placement(annotation_type))

    def _validate_named_view_name(
        self, name: str, exclude_uid: Optional[str] = None
    ) -> bool:
        if named_view_name_exists(self._named_views, name, exclude_uid=exclude_uid):
            show_duplicate_named_view_name(self)
            return False
        return True

    def refresh_annotation_style(self, annotation_type: str | None = None) -> None:
        if not self._annotation_tool_buttons:
            return
        apply_annotation_tool_icon_color(self._annotation_tool_buttons, annotation_type)

    def _populate_page_combo(self, bid: Bid) -> None:
        self._page_combo.set_label_options(
            self._show_page_index, self._show_sheet_number
        )
        self._page_combo.load_bid(bid, pages_with_takeoffs=self._pages_with_takeoffs)

    def _current_page_has_takeoffs(self) -> set[str]:
        if not self.page_data:
            return set()
        return {
            takeoff.page_uid
            for takeoff in self.page_data.takeoffs
            if takeoff and takeoff.page_uid
        }

    def _populate_named_view_combo(self) -> None:
        self._named_view_combo.blockSignals(True)
        self._named_view_combo.clear()
        by_page: dict = {}
        for nv_uid, page_uid, page_name, view_name in self._named_views:
            by_page.setdefault(page_uid, (page_name, []))[1].append((nv_uid, view_name))
        for page_uid in self._page_combo.get_page_order():
            if page_uid not in by_page:
                continue
            _page_name, entries = by_page[page_uid]
            for nv_uid, view_name in entries:
                name = view_name if view_name else nv_uid
                self._named_view_combo.addItem(name, userData=(page_uid, nv_uid))
        self._named_view_combo.setCurrentIndex(-1)
        self._named_view_combo.blockSignals(False)

    def update_navigation(
        self,
        bid: Optional[Bid],
        named_views: Optional[List[NamedViewEntry]] = None,
        pages_with_takeoffs: Optional[set[str]] = None,
    ) -> None:
        if self._is_closing:
            return
        self._pages_with_takeoffs = set(pages_with_takeoffs or ())
        self._named_views = list(named_views or [])
        if bid is None:
            self._page_combo.clear()
        else:
            self._populate_page_combo(bid)
        self._populate_named_view_combo()
        page_uid = self.view.target_page_uid if self.view else ""
        self._update_combo_to_page(page_uid)
        self._page_combo.set_pages_with_takeoffs(self._pages_with_takeoffs)

    def update_named_view_name(self, named_view_uid: str, name: str) -> None:
        if self._is_closing:
            return
        uid = str(named_view_uid)
        text = str(name)
        changed = False
        updated: List[NamedViewEntry] = []
        for nv_uid, page_uid, page_name, view_name in self._named_views:
            if nv_uid == uid:
                updated.append((nv_uid, page_uid, page_name, text))
                changed = changed or view_name != text
            else:
                updated.append((nv_uid, page_uid, page_name, view_name))
        if not changed:
            return
        self._named_views = updated
        if self.page_data is not None:
            for annotation in self.page_data.annotations:
                if annotation.uid == uid and annotation.is_namedview:
                    annotation.properties["Text"] = text
        if self.plan_view is not None:
            self.plan_view.update_named_view_label_text(uid, text)
        self._populate_named_view_combo()

    def _on_named_view_combo_changed(self, index: int) -> None:
        if self._is_closing or not self._on_named_view_selected or index < 0:
            return
        data = self._named_view_combo.itemData(index, self._PAGE_UID_ROLE)
        if not isinstance(data, tuple):
            return
        page_uid, nv_uid = data
        self._named_view_combo.blockSignals(True)
        self._named_view_combo.setCurrentIndex(-1)
        self._named_view_combo.blockSignals(False)
        self._on_named_view_selected(page_uid, nv_uid)

    def _on_page_activated(self, page_uid: str) -> None:
        if self._is_closing or not self._on_page_selected:
            return
        if self.view and page_uid != self.view.target_page_uid:
            self._on_page_selected(page_uid)

    def _go_prev_page(self) -> None:
        if not self.view or not self._on_page_selected:
            return
        order = self._page_combo.get_page_order()
        if self.view.target_page_uid not in order:
            return
        idx = order.index(self.view.target_page_uid)
        if idx > 0:
            self._on_page_selected(order[idx - 1])

    def _go_next_page(self) -> None:
        if not self.view or not self._on_page_selected:
            return
        order = self._page_combo.get_page_order()
        if self.view.target_page_uid not in order:
            return
        idx = order.index(self.view.target_page_uid)
        if idx < len(order) - 1:
            self._on_page_selected(order[idx + 1])

    def _update_combo_to_page(self, page_uid: str) -> None:
        self._page_combo.set_current_page_uid(page_uid)
        self._update_arrow_states(page_uid)

    def _update_arrow_states(self, page_uid: str) -> None:
        order = self._page_combo.get_page_order()
        if not order:
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
            return
        if page_uid not in order:
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
            return
        idx = order.index(page_uid)
        self._btn_prev.setEnabled(idx > 0)
        self._btn_next.setEnabled(idx < len(order) - 1)

    def load_view(
        self,
        view: AnnotationView,
        page_data: Optional[PageViewDto] = None,
        navigation_source: str = "unknown",
    ) -> None:
        self._reset_annotation_clipboard_if_context_changed(view)
        self._navigation_source = navigation_source
        self.view = view
        if page_data is not None:
            self.page_data = page_data
        self._refresh_annotation_tool_access()
        if self._should_use_named_view_blank_canvas():
            self._start_named_view_blank_canvas()
        else:
            self._reveal_named_view_blank_canvas()
        if not self._load_page_content():
            return
        self._update_combo_to_page(view.target_page_uid)
        self._sync_current_page_takeoff_indicator()
        self._page_combo.set_pages_with_takeoffs(self._pages_with_takeoffs)

    def update_page(self, page_data: PageViewDto) -> None:
        if self._is_closing:
            return
        self.page_data = page_data
        self._refresh_annotation_tool_access()
        self._navigation_source = "refresh"
        self._sync_current_page_takeoff_indicator()
        self._page_combo.set_pages_with_takeoffs(self._pages_with_takeoffs)
        if self._should_use_named_view_blank_canvas():
            self._start_named_view_blank_canvas()
        else:
            self._reveal_named_view_blank_canvas()
        self._load_page_content()

    def _update_scale_combo(self, sf1: float, sf2: float) -> None:
        if self._scale_combo is None:
            return
        self._scale_combo.blockSignals(True)
        idx = -1
        for i in range(self._scale_combo.count()):
            data = self._scale_combo.itemData(i)
            if data and abs(data[0] - sf1) < 1e-9 and abs(data[1] - sf2) < 1e-9:
                idx = i
                break
        self._scale_combo.setCurrentIndex(idx)
        self._scale_combo.blockSignals(False)

    def _on_scale_activated(self, index: int) -> None:
        if (
            self._scale_combo is None
            or not self._on_scale_changed
            or not self.page_data
            or not self.page_data.page
        ):
            return
        data = self._scale_combo.itemData(index)
        if data:
            sf1, sf2 = data
            self._on_scale_changed(self.page_data.page.uid, sf1, sf2)

    def _load_page_content(self) -> bool:
        page = self.page_data.page if self.page_data else None
        if not page:
            self.plan_view.clear()
            return False
        self._update_scale_combo(page.scale_factor1, page.scale_factor2)
        self._capture_refresh_view_state(page)
        try:
            self.plan_view.load_page(
                page=page,
                takeoffs=self.page_data.takeoffs,
                conditions=self.page_data.conditions,
                color_map=self.page_data.color_map,
                bid_ref=self.page_data.bid_ref,
                annotations=self.page_data.annotations,
                page_area_selections=self.page_data.page_area_selections,
                hidden_layer_uids=self.page_data.hidden_layer_uids,
            )
            self.plan_view.prefetch_nearby_pages(
                page,
                self.page_data.ordered_pages,
                self.page_data.bid_ref,
            )
            self._apply_named_view_focus_if_possible(require_stable_view=False)
            return True
        except Exception:
            self.logger.exception("Error loading page into plan_view")
            self.plan_view.clear()
            return False

    def _capture_refresh_view_state(self, page) -> None:
        if self._navigation_source != "refresh" or self.plan_view is None:
            return
        state = None
        if (
            self.plan_view.current_page_uid == page.uid
            and self.plan_view.is_view_state_stable
        ):
            state = self.plan_view.get_view_state()
            self._remember_page_view_state(page.uid, *state)
        if state is None:
            state = self._page_view_states.get(str(page.uid))
        if state is None:
            return
        zoom_fac, current_x, current_y = state
        if zoom_fac <= 0:
            return
        page.zoom_fac = zoom_fac
        page.current_x = current_x
        page.current_y = current_y

    def _remember_page_view_state(
        self, page_uid: str, zoom_fac: float, current_x: float, current_y: float
    ) -> None:
        if not page_uid or zoom_fac <= 0:
            return
        self._page_view_states[str(page_uid)] = (
            float(zoom_fac),
            float(current_x),
            float(current_y),
        )

    def _on_page_view_state_changed(
        self, page_uid: str, zoom_fac: float, current_x: float, current_y: float
    ) -> None:
        self._remember_page_view_state(page_uid, zoom_fac, current_x, current_y)

    def _focus_on_named_view(self) -> None:
        if self._is_closing:
            return
        named_view = self.page_data.named_view if self.page_data else None
        if not named_view:
            return
        try:
            focus_plan_view_on_named_view(self.plan_view, named_view)
        except Exception:
            self.logger.exception("Error focusing on named view")

    def _should_use_named_view_blank_canvas(self) -> bool:
        if not (
            self.view
            and self.view.target_named_view_uid
            and self.page_data
            and self.page_data.named_view
            and self._navigation_source in ("hotlink", "named_view_combo")
        ):
            return False
        current_page_uid = self.plan_view.current_page_uid if self.plan_view else None
        target_page_uid = self.page_data.page.uid if self.page_data.page else None
        same_loaded_page = (
            current_page_uid == target_page_uid
            and self.plan_view is not None
            and self.plan_view.is_view_state_stable
        )
        return not same_loaded_page

    def _start_named_view_blank_canvas(self) -> None:
        if not self.plan_view or self._named_view_blank_canvas_active:
            return
        self._named_view_blank_canvas_active = True
        self.plan_view.set_page_visual_reveal_deferred(True)

    def _reveal_named_view_blank_canvas(self) -> None:
        if not self.plan_view or not self._named_view_blank_canvas_active:
            return
        self._named_view_blank_canvas_active = False
        self.plan_view.reveal_deferred_page_visual()

    def _apply_named_view_focus_if_possible(self, require_stable_view: bool) -> bool:
        if (
            self._is_closing
            or not self.view
            or not self.view.target_named_view_uid
            or not self.page_data
            or not self.page_data.named_view
            or self._navigation_source not in ("hotlink", "named_view_combo")
        ):
            self._reveal_named_view_blank_canvas()
            return False
        if require_stable_view:
            if not self.plan_view.is_view_state_stable:
                return False
        elif not self.isVisible() or not self.plan_view.sceneRect().isValid():
            return False
        self._focus_on_named_view()
        return True

    def _on_page_geometry_ready(self) -> None:
        if self._is_closing:
            return
        self._initial_page_geometry_ready = True
        if self._show_timer and self._show_timer.isActive():
            self._show_timer.stop()
        if self._initial_show_requested and not self.isVisible():
            self._show_initial_window()

    def _on_page_loaded(self) -> None:
        if self._is_closing:
            return
        if self._show_timer and self._show_timer.isActive():
            self._show_timer.stop()
        if self._apply_named_view_focus_if_possible(require_stable_view=True):
            self._schedule_named_view_focus_after_resize()

    def _on_show_timeout(self) -> None:
        if self._is_closing:
            return
        if self._initial_show_requested and not self.isVisible():
            self.logger.warning("Page loading timeout - showing window anyway")
            self._show_initial_window()
        if self._apply_named_view_focus_if_possible(require_stable_view=True):
            self._schedule_named_view_focus_after_resize()
            return
        if self.view and self.view.target_named_view_uid:
            QtCore.QTimer.singleShot(0, self._focus_named_view_timeout_fallback)

    def _focus_named_view_timeout_fallback(self) -> None:
        self._focus_on_named_view()
        self._reveal_named_view_blank_canvas()

    def _schedule_named_view_focus_after_resize(self) -> None:
        if (
            self._is_closing
            or not self.view
            or not self.view.target_named_view_uid
            or self._named_view_resize_focus_timer is None
        ):
            return
        self._pending_named_view_resize_focus = True
        self._named_view_resize_focus_timer.start(120)

    def _apply_named_view_focus_after_resize(self) -> None:
        if self._is_closing or not self._pending_named_view_resize_focus:
            return
        if not self.plan_view or not self.plan_view.is_view_state_stable:
            self._schedule_named_view_focus_after_resize()
            return
        self._pending_named_view_resize_focus = False
        self._focus_on_named_view()
        self._reveal_named_view_blank_canvas()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._pending_named_view_resize_focus:
            self._schedule_named_view_focus_after_resize()

    def _show_initial_window(self) -> None:
        if self.isVisible():
            return
        geometry = self._initial_geometry
        if geometry and not geometry.isEmpty():
            self._restore_initial_geometry()
        if self._initial_show_fullscreen:
            self.showFullScreen()
            return
        if self._initial_show_maximized:
            self.showMaximized()
            return
        self.show()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        if self._scale_combo is not None:
            self._scale_combo.setEnabled(not read_only)
        self._refresh_annotation_tool_access()
        if self.plan_view:
            self.plan_view.set_selection_enabled(self._selection_enabled())
            self.plan_view.set_text_annotation_inline_edit_enabled(
                self._selection_enabled()
            )

    def apply_config_preferences(
        self,
        *,
        show_page_index: bool,
        show_sheet_number: bool,
        roping_selection_method: str,
        disable_high_resolution_images: bool,
        intelligent_paste_enabled: bool,
        advanced_mouse_controls_enabled: bool,
        default_auto_zoom_level: int,
        use_full_window_crosshairs: bool,
        crosshair_color: str,
        crosshair_line_thickness: int,
        mouse_unpressed_snap_angle: int,
        mouse_pressed_snap_angle: int,
        snap_to_grid_enabled: bool,
        snap_to_grid_threshold_px: int,
        snap_to_pdf_lines_enabled: bool,
        snap_to_pdf_lines_threshold_px: int,
        snap_to_takeoffs_enabled: bool,
        snap_to_takeoffs_threshold_px: int,
        snap_to_right_angle_enabled: bool,
        snap_to_right_angle_threshold_px: int,
    ) -> None:
        self._show_page_index = bool(show_page_index)
        self._show_sheet_number = bool(show_sheet_number)
        self._roping_selection_method = roping_selection_method
        self._disable_high_resolution_images = bool(disable_high_resolution_images)
        self._intelligent_paste_enabled = bool(intelligent_paste_enabled)
        self._advanced_mouse_controls_enabled = bool(advanced_mouse_controls_enabled)
        self._default_auto_zoom_level = int(default_auto_zoom_level)
        self._use_full_window_crosshairs = bool(use_full_window_crosshairs)
        self._crosshair_color = crosshair_color
        self._crosshair_line_thickness = int(crosshair_line_thickness)
        self._mouse_unpressed_snap_angle = int(mouse_unpressed_snap_angle)
        self._mouse_pressed_snap_angle = int(mouse_pressed_snap_angle)
        self._snap_to_grid_enabled = bool(snap_to_grid_enabled)
        self._snap_to_grid_threshold_px = int(snap_to_grid_threshold_px)
        self._snap_to_pdf_lines_enabled = bool(snap_to_pdf_lines_enabled)
        self._snap_to_pdf_lines_threshold_px = int(snap_to_pdf_lines_threshold_px)
        self._snap_to_takeoffs_enabled = bool(snap_to_takeoffs_enabled)
        self._snap_to_takeoffs_threshold_px = int(snap_to_takeoffs_threshold_px)
        self._snap_to_right_angle_enabled = bool(snap_to_right_angle_enabled)
        self._snap_to_right_angle_threshold_px = int(snap_to_right_angle_threshold_px)
        self._page_combo.set_label_options(
            self._show_page_index,
            self._show_sheet_number,
        )
        if self.plan_view is None:
            return
        self.plan_view.set_roping_selection_method(self._roping_selection_method)
        self.plan_view.set_disable_high_resolution_images(
            self._disable_high_resolution_images
        )
        self.plan_view.set_intelligent_paste_enabled(self._intelligent_paste_enabled)
        self.plan_view.set_advanced_mouse_controls_enabled(
            self._advanced_mouse_controls_enabled
        )
        self.plan_view.set_default_auto_zoom_level(self._default_auto_zoom_level)
        self.plan_view.set_full_window_crosshairs(
            self._use_full_window_crosshairs,
            self._crosshair_color,
            self._crosshair_line_thickness,
        )
        self.plan_view.set_mouse_snap_angles(
            self._mouse_unpressed_snap_angle,
            self._mouse_pressed_snap_angle,
        )
        self._apply_plan_view_snap_preferences()

    def _apply_plan_view_snap_preferences(self) -> None:
        if self.plan_view is None:
            return
        self.plan_view.set_snap_preferences(
            snap_to_grid_enabled=self._snap_to_grid_enabled,
            snap_to_grid_threshold_px=self._snap_to_grid_threshold_px,
            snap_to_pdf_lines_enabled=self._snap_to_pdf_lines_enabled,
            snap_to_pdf_lines_threshold_px=self._snap_to_pdf_lines_threshold_px,
            snap_to_takeoffs_enabled=self._snap_to_takeoffs_enabled,
            snap_to_takeoffs_threshold_px=self._snap_to_takeoffs_threshold_px,
            snap_to_right_angle_enabled=self._snap_to_right_angle_enabled,
            snap_to_right_angle_threshold_px=(self._snap_to_right_angle_threshold_px),
        )

    def _sync_current_page_takeoff_indicator(self) -> None:
        page = self.page_data.page if self.page_data else None
        if page is None or not page.uid:
            return
        if self._current_page_has_takeoffs():
            self._pages_with_takeoffs.add(page.uid)
        else:
            self._pages_with_takeoffs.discard(page.uid)

    def get_dropdown_popup_sizes(self) -> dict[str, list[int]]:
        prefix = self._config.dropdown_state_key
        return {
            f"{prefix}_page": self._page_combo.get_popup_size(),
            f"{prefix}_named_views": self._named_view_combo.get_popup_size(),
        }

    def set_dropdown_popup_sizes(self, sizes: dict[str, list[int]]) -> None:
        prefix = self._config.dropdown_state_key
        self._page_combo.set_popup_size(sizes.get(f"{prefix}_page", []))
        self._named_view_combo.set_popup_size(sizes.get(f"{prefix}_named_views", []))

    def _get_db_path(self) -> Optional[str]:
        return self._file_path

    def _on_positions_flushed(self, _takeoff_changes: list, ann_changes: list) -> None:
        if not self._config.allow_annotation_editing or self._read_only:
            return
        if self._is_closing or self._ann_write_svc is None or not ann_changes:
            return
        db_path = self._get_db_path()
        if not db_path:
            return
        new_changes = [
            (uid, ann_type, list(new_pos))
            for uid, ann_type, _old, new_pos in ann_changes
        ]
        if not self._save_annotation_positions(db_path, new_changes):
            self.plan_view.restore_flushed_positions([], ann_changes)
            return
        if self._undo_svc is None:
            return
        old_changes = [
            (uid, ann_type, list(old))
            for uid, ann_type, old, _new in ann_changes
            if old
        ]
        if not old_changes:
            return

        def _undo_move():
            self._save_annotation_positions(db_path, old_changes)

        def _redo_move():
            self._save_annotation_positions(db_path, new_changes)

        self._undo_svc.push(_undo_move, _redo_move)

    def _on_annotation_text_properties_flushed(self, changes: list) -> None:
        if not self._config.allow_annotation_editing or self._read_only:
            return
        if self._is_closing or self._ann_write_svc is None or not changes:
            return
        db_path = self._get_db_path()
        if not db_path:
            return
        new_updates = [
            (uid, ann_type, dict(new_props))
            for uid, ann_type, _old_props, new_props in changes
        ]
        success = self._save_annotation_text_properties(db_path, new_updates)
        if not success:
            self.plan_view.restore_annotation_text_properties(changes)
            return
        self._publish_named_view_renames(new_updates)
        if self._undo_svc is None:
            return
        old_updates = [
            (uid, ann_type, dict(old_props))
            for uid, ann_type, old_props, _new_props in changes
            if old_props
        ]
        if not old_updates:
            return

        def _undo_text_properties():
            if self._save_annotation_text_properties(db_path, old_updates):
                self._publish_named_view_renames(old_updates)

        def _redo_text_properties():
            if self._save_annotation_text_properties(db_path, new_updates):
                self._publish_named_view_renames(new_updates)

        self._undo_svc.push(_undo_text_properties, _redo_text_properties)

    def _on_annotation_styles_flushed(self, changes: list) -> None:
        if not self._config.allow_annotation_editing or self._read_only:
            return
        if self._is_closing or self._ann_write_svc is None or not changes:
            return
        db_path = self._get_db_path()
        if not db_path:
            return
        new_updates = [
            (uid, ann_type, dict(new_style))
            for uid, ann_type, _old_style, new_style in changes
        ]
        success = self._save_annotation_styles(db_path, new_updates)
        if not success:
            self.plan_view.restore_annotation_styles(changes)
            return
        if self._undo_svc is None:
            return
        old_updates = [
            (uid, ann_type, dict(old_style))
            for uid, ann_type, old_style, _new_style in changes
            if old_style
        ]
        if not old_updates:
            return

        def _undo_styles():
            self._save_annotation_styles(db_path, old_updates)

        def _redo_styles():
            self._save_annotation_styles(db_path, new_updates)

        self._undo_svc.push(_undo_styles, _redo_styles)

    def _publish_named_view_renames(self, updates: list) -> None:
        if self._annotation_write_coordinator is not None:
            self._annotation_write_coordinator.publish_named_view_renames(updates)
            return
        for uid, ann_type, properties in updates:
            if ann_type != ANNOTATION_TYPE_NAMED_VIEW or "Text" not in properties:
                continue
            name = str(properties["Text"] or "")
            self.event_bus.publish(
                AppEvents.NAMED_VIEW_RENAMED,
                named_view_uid=str(uid),
                name=name,
            )

    def _apply_default_annotation_layer(self, spec) -> None:
        if self.page_data is None:
            return
        factory = AnnotationCreationFactory(self.page_data.annotation_layer_uid)
        factory.assign_default_layer(spec)

    def _save_annotation_positions(self, db_path: str, changes: list) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.save_positions(db_path, changes)
        return self._ann_write_svc.save_annotation_positions(db_path, changes)

    def _save_annotation_text_properties(self, db_path: str, updates: list) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.save_text_properties(
                db_path, updates
            )
        return self._ann_write_svc.save_annotation_text_properties(db_path, updates)

    def _save_annotation_styles(self, db_path: str, updates: list) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.save_styles(db_path, updates)
        return self._ann_write_svc.save_annotation_styles(db_path, updates)

    def _save_annotation_text_and_positions(
        self, db_path: str, updates: list, positions: list
    ) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.save_text_and_positions(
                db_path, updates, positions
            )
        return self._ann_write_svc.save_annotation_text_properties_and_positions(
            db_path, updates, positions
        )

    def _insert_annotations(
        self,
        bid_ref,
        specs: List[InsertAnnotationSpec],
        ref_remap=None,
    ) -> List[str]:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.insert_annotations(
                bid_ref, specs, ref_remap=ref_remap
            )
        for spec in specs:
            self._apply_default_annotation_layer(spec)
        return list(
            self._ann_write_svc.insert_annotations(
                bid_ref.file_path,
                bid_ref.bid_uid,
                specs,
                ref_remap=ref_remap,
            )
        )

    def _delete_annotations(
        self, db_path: str, uids: List[str], specs: List[InsertAnnotationSpec]
    ) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.delete_annotations(
                db_path, uids, specs
            )
        return self._ann_write_svc.delete_annotations(
            db_path,
            [(uid, spec.annotation_type) for uid, spec in zip(uids, specs)],
        )

    def _delete_saved_annotations(self, db_path: str, annotations: list) -> bool:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.delete_saved_annotations(
                db_path, annotations
            )
        return self._ann_write_svc.delete_annotations(
            db_path,
            [
                (annotation.uid, annotation.annotation_type)
                for annotation in annotations
            ],
        )

    def _insert_saved_annotations(self, bid_ref, annotations: list) -> list:
        if self._annotation_write_coordinator is not None:
            return self._annotation_write_coordinator.insert_saved_annotations(
                bid_ref, annotations
            )
        return []

    def _reset_annotation_clipboard(self) -> None:
        if self._annotation_clipboard_svc is None:
            return
        self._annotation_clipboard_svc = SelectionClipboardService()
        if self.plan_view is not None:
            self.plan_view.clipboard_changed.emit()

    def _reset_annotation_clipboard_if_context_changed(
        self, view: AnnotationView
    ) -> None:
        if self._annotation_clipboard_svc is None:
            return
        bid_ref = view.bid_ref if view else None
        if bid_ref is None:
            self._reset_annotation_clipboard()
            return
        if not self._annotation_clipboard_svc.has_content():
            return
        if (
            self._annotation_clipboard_svc.source_file_path != bid_ref.file_path
            or self._annotation_clipboard_svc.source_bid_uid != bid_ref.bid_uid
        ):
            self._reset_annotation_clipboard()

    def _copyable_annotations_for_uids(self, uids: list) -> list:
        if self.plan_view is None:
            return []
        annotations = []
        for uid in uids:
            annotation = self.plan_view.get_annotation(uid)
            if annotation and annotation.is_interactive and not annotation.is_namedview:
                annotations.append(annotation)
        return annotations

    def _selected_copyable_annotations(self) -> list:
        if self.plan_view is None:
            return []
        return self._copyable_annotations_for_uids(self.plan_view.get_selected_uids())

    def _can_copy_selected_annotations(self) -> bool:
        return self._selection_enabled() and bool(self._selected_copyable_annotations())

    def _can_paste_annotations(self) -> bool:
        if (
            not self._selection_enabled()
            or self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or self.view is None
            or self.view.bid_ref is None
            or self._annotation_clipboard_svc is None
        ):
            return False
        bid_ref = self.view.bid_ref
        if (
            self._annotation_clipboard_svc.source_file_path != bid_ref.file_path
            or self._annotation_clipboard_svc.source_bid_uid != bid_ref.bid_uid
        ):
            return False
        return bool(
            self.plan_view.current_page_uid
            and self._annotation_clipboard_svc.annotations
        )

    def _context_menu_action_state(self, action_key: str) -> dict:
        if action_key == ACTION_COPY:
            return {"enabled": self._can_copy_selected_annotations()}
        if action_key == ACTION_PASTE:
            return {"enabled": self._can_paste_annotations()}
        return {}

    def _trigger_context_menu_command(self, action_key: str) -> None:
        if action_key == ACTION_COPY and self.plan_view is not None:
            self._on_copy_requested(self.plan_view.get_selected_uids())
        elif action_key == ACTION_PASTE:
            self._on_paste_requested()

    def _on_copy_requested(self, uids: list) -> None:
        if (
            not self._selection_enabled()
            or self._annotation_clipboard_svc is None
            or self.view is None
            or self.view.bid_ref is None
        ):
            return
        annotations = self._copyable_annotations_for_uids(uids)
        if not annotations:
            return
        self._annotation_clipboard_svc.copy(
            [],
            annotations,
            source_bid_uid=self.view.bid_ref.bid_uid,
            source_file_path=self.view.bid_ref.file_path,
        )
        if self.plan_view is not None:
            self.plan_view.clipboard_changed.emit()

    def _on_paste_requested(self) -> None:
        if not self._can_paste_annotations():
            return
        bid_ref = self.view.bid_ref
        page_uid = self.plan_view.current_page_uid
        clipboard_annotations = self._annotation_clipboard_svc.annotations
        paste_dx, paste_dy, source_anchor = annotation_paste_translation(
            self.plan_view, clipboard_annotations
        )
        specs = [
            InsertAnnotationSpec(
                page_uid=page_uid,
                annotation_type=annotation.annotation_type,
                position=translate_annotation_position(annotation, paste_dx, paste_dy),
                color=annotation.color,
                width=annotation.width,
                properties=dict(annotation.properties),
                layer_uid=annotation.layer_uid,
            )
            for annotation in clipboard_annotations
        ]
        new_uids = self._insert_annotations(bid_ref, specs)
        new_uids = list(new_uids[: len(specs)])
        specs = specs[: len(new_uids)]
        uid_type_set = {
            (uid, specs[i].annotation_type) for i, uid in enumerate(new_uids)
        }
        keys = self.plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self.plan_view.set_selected_uids(keys)
            if source_anchor:
                self.plan_view.mark_intelligent_paste_drag_pending(
                    sorted(keys),
                    source_anchor,
                )
        if self._undo_svc is None or not new_uids or not specs:
            return
        cmd = PasteAnnotationsCommand(
            specs=specs,
            new_uids=list(new_uids),
            bid_ref=bid_ref,
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_annotations_fn=(
                self._insert_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_annotations_fn=(
                self._delete_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _on_annotation_created(
        self, annotation_type: str, position: list, page_uid: str
    ) -> None:
        if not self._annotation_placement_enabled():
            return
        if (
            self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or not annotation_type
            or not page_uid
        ):
            return
        bid_ref = self.view.bid_ref if self.view else None
        if bid_ref is None:
            return
        spec = build_placed_annotation_spec(annotation_type, page_uid, list(position))
        if spec is None:
            return
        new_uids = self._insert_annotations(bid_ref, [spec])
        if not new_uids:
            return
        uid_type_set = {(new_uids[0], spec.annotation_type)}
        keys = self.plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self.plan_view.set_selected_uids(keys)
        if self._undo_svc is None:
            return
        cmd = InsertAnnotationsCommand(
            uids=list(new_uids),
            bid_ref=bid_ref,
            specs=[spec],
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_annotations_fn=(
                self._insert_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_annotations_fn=(
                self._delete_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _on_text_annotation_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._annotation_placement_enabled():
            return
        if (
            self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or not page_uid
            or not str(properties.get("Text", "")).strip()
        ):
            return
        bid_ref = self.view.bid_ref if self.view else None
        if bid_ref is None:
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_TEXT,
            page_uid,
            list(position),
        )
        if spec is None:
            return
        spec.properties = dict(properties)
        font_color = spec.properties.get("FontColor")
        if isinstance(font_color, int):
            spec.color = int_color_to_hex(font_color)
        new_uids = self._insert_annotations(bid_ref, [spec])
        if not new_uids:
            return
        uid_type_set = {(new_uids[0], spec.annotation_type)}
        keys = self.plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self.plan_view.set_selected_uids(keys)
        if self._undo_svc is None:
            return
        cmd = InsertAnnotationsCommand(
            uids=list(new_uids),
            bid_ref=bid_ref,
            specs=[spec],
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_annotations_fn=(
                self._insert_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_annotations_fn=(
                self._delete_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _on_named_view_created(
        self, position: list, page_uid: str, properties: dict
    ) -> None:
        if not self._annotation_placement_enabled():
            return
        if (
            self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or not page_uid
        ):
            return
        name = str(properties.get("Text", "") or "").strip()
        if not name:
            return
        if not self._validate_named_view_name(name, None):
            return
        bid_ref = self.view.bid_ref if self.view else None
        if bid_ref is None:
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_NAMED_VIEW, page_uid, list(position)
        )
        if spec is None:
            return
        spec.properties = {"Text": name}
        color = properties.get("Color")
        if isinstance(color, str) and color:
            spec.color = color
        new_uids = self._insert_annotations(bid_ref, [spec])
        if not new_uids:
            return
        uid_type_set = {(new_uids[0], spec.annotation_type)}
        keys = self.plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self.plan_view.set_selected_uids(keys)
        self.event_bus.publish(
            AppEvents.NAMED_VIEW_CREATED,
            named_view_uid=new_uids[0],
            page_uid=page_uid,
            name=name,
        )
        self.plan_view.activate_annotation_placement(ANNOTATION_TYPE_NAMED_VIEW)
        if self._undo_svc is None:
            return
        cmd = InsertAnnotationsCommand(
            uids=list(new_uids),
            bid_ref=bid_ref,
            specs=[spec],
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_annotations_fn=(
                self._insert_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_annotations_fn=(
                self._delete_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _on_hotlink_placement_requested(self, position: list, page_uid: str) -> None:
        if not self._annotation_placement_enabled():
            return
        if (
            self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or not page_uid
            or len(position) < 2
        ):
            return
        bid_ref = self.view.bid_ref if self.view else None
        if bid_ref is None:
            return
        self.plan_view.cancel_place_mode()
        dialog = SelectNamedViewDialog(self._named_views, parent=self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        result = dialog.result_data()
        if result.create_new:
            self.plan_view.activate_annotation_placement(ANNOTATION_TYPE_NAMED_VIEW)
            return
        if not result.named_view_uid:
            return
        spec = build_placed_annotation_spec(
            ANNOTATION_TYPE_HOTLINK, page_uid, list(position[:2])
        )
        if spec is None:
            return
        spec.properties = {"BidPageViewUID": result.named_view_uid}
        new_uids = self._insert_annotations(bid_ref, [spec])
        if not new_uids:
            return
        uid_type_set = {(new_uids[0], spec.annotation_type)}
        keys = self.plan_view.find_annotation_keys_by_uid_type(uid_type_set)
        if keys:
            self.plan_view.set_selected_uids(keys)
        self.plan_view.activate_annotation_placement(ANNOTATION_TYPE_HOTLINK)
        if self._undo_svc is None:
            return
        cmd = InsertAnnotationsCommand(
            uids=list(new_uids),
            bid_ref=bid_ref,
            specs=[spec],
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_annotations_fn=(
                self._insert_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_annotations_fn=(
                self._delete_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def _on_annotation_text_and_positions_flushed(
        self, text_changes: list, ann_position_changes: list
    ) -> None:
        if not self._config.allow_annotation_editing or self._read_only:
            return
        if (
            self._is_closing
            or self._ann_write_svc is None
            or (not text_changes and not ann_position_changes)
        ):
            return
        db_path = self._get_db_path()
        if not db_path:
            return
        new_updates = [
            (uid, ann_type, dict(new_props))
            for uid, ann_type, _old_props, new_props in text_changes
        ]
        new_positions = [
            (uid, ann_type, list(new_pos))
            for uid, ann_type, _old_pos, new_pos in ann_position_changes
        ]
        success = self._save_annotation_text_and_positions(
            db_path, new_updates, new_positions
        )
        if not success:
            self.plan_view.restore_annotation_text_and_positions(
                text_changes, ann_position_changes
            )
            return
        if self._undo_svc is None:
            return
        old_updates = [
            (uid, ann_type, dict(old_props))
            for uid, ann_type, old_props, _new_props in text_changes
            if old_props
        ]
        old_positions = [
            (uid, ann_type, list(old_pos))
            for uid, ann_type, old_pos, _new_pos in ann_position_changes
            if old_pos
        ]
        if not (old_updates or old_positions):
            return

        def _undo_text_and_position():
            self._save_annotation_text_and_positions(
                db_path, old_updates, old_positions
            )

        def _redo_text_and_position():
            self._save_annotation_text_and_positions(
                db_path, new_updates, new_positions
            )

        self._undo_svc.push(_undo_text_and_position, _redo_text_and_position)

    def _on_elements_deleted(self, uids: list) -> None:
        if not self._config.allow_annotation_editing or self._read_only:
            return
        bid_ref = self.view.bid_ref if self.view else None
        if (
            self._is_closing
            or self._ann_write_svc is None
            or self.plan_view is None
            or not uids
            or bid_ref is None
        ):
            return
        db_path = self._get_db_path()
        if not db_path:
            return
        saved_annotations = []
        annotation_selection_keys = {}
        for uid in uids:
            ann = self.plan_view.get_annotation(uid)
            if ann and ann.is_interactive:
                saved_annotations.append(ann)
                annotation_selection_keys[(str(ann.uid), str(ann.annotation_type))] = (
                    uid
                )
        if not saved_annotations:
            return
        skipped_namedview_uids: set[str] = set()
        if any(annotation.is_namedview for annotation in saved_annotations):
            resolver = self._linked_hotlink_resolver or (lambda _uids: [])
            delete_plan = plan_named_view_hotlink_delete(
                saved_annotations,
                resolver,
                lambda _annotation: confirm(
                    self,
                    "Delete Named View",
                    NAMED_VIEW_HOTLINK_DELETE_MESSAGE,
                ),
            )
            saved_annotations = delete_plan.annotations_to_delete
            skipped_namedview_uids = delete_plan.skipped_named_view_uids
            if not saved_annotations:
                self.plan_view.set_selected_uids(set(uids))
                return
        skipped_selection_keys = skipped_named_view_selection_keys(
            annotation_selection_keys, skipped_namedview_uids
        )
        if not self._delete_saved_annotations(db_path, saved_annotations):
            self.plan_view.set_selected_uids(set(uids))
            return
        if skipped_selection_keys:
            self.plan_view.set_selected_uids(skipped_selection_keys)
        if self._undo_svc is None:
            return
        cmd = DeleteAnnotationsCommand(
            saved_annotations=saved_annotations,
            bid_ref=bid_ref,
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
            insert_saved_annotations_fn=(
                self._insert_saved_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
            delete_saved_annotations_fn=(
                self._delete_saved_annotations
                if self._annotation_write_coordinator is not None
                else None
            ),
        )
        self._undo_svc.push(cmd.undo, cmd.redo)

    def cleanup(self) -> None:
        if self._is_closing:
            return
        self._is_closing = True
        if self._show_timer is not None:
            self._show_timer.stop()
            self._show_timer.deleteLater()
            self._show_timer = None
        if self._named_view_resize_focus_timer is not None:
            self._named_view_resize_focus_timer.stop()
            self._named_view_resize_focus_timer.deleteLater()
            self._named_view_resize_focus_timer = None
        self._pending_named_view_resize_focus = False
        self._reveal_named_view_blank_canvas()
        if self._hotlink_adapter is not None:
            self._hotlink_adapter.shutdown()
            self._hotlink_adapter = None
        if self.plan_view is not None:
            self.plan_view.page_geometry_ready.disconnect(self._on_page_geometry_ready)
            self.plan_view.page_fully_loaded.disconnect(self._on_page_loaded)
            self.plan_view.page_view_state_changed.disconnect(
                self._on_page_view_state_changed
            )
            self.plan_view.positions_flushed.disconnect(self._on_positions_flushed)
            self.plan_view.annotation_text_properties_flushed.disconnect(
                self._on_annotation_text_properties_flushed
            )
            self.plan_view.annotation_text_and_positions_flushed.disconnect(
                self._on_annotation_text_and_positions_flushed
            )
            self.plan_view.annotation_styles_flushed.disconnect(
                self._on_annotation_styles_flushed
            )
            self.plan_view.elements_deleted.disconnect(self._on_elements_deleted)
            self.plan_view.annotation_created.disconnect(self._on_annotation_created)
            self.plan_view.text_annotation_created.disconnect(
                self._on_text_annotation_created
            )
            self.plan_view.named_view_created.disconnect(self._on_named_view_created)
            self.plan_view.hotlink_placement_requested.disconnect(
                self._on_hotlink_placement_requested
            )
            if self._annotation_clipboard_svc is not None:
                self.plan_view.copy_requested.disconnect(self._on_copy_requested)
                self.plan_view.paste_requested.disconnect(self._on_paste_requested)
                self.plan_view.set_context_menu_command_handlers(None, None)
            self.plan_view.cursor_mode_change_requested.disconnect(
                self._on_cursor_mode_change_requested
            )
            if self._undo_svc is not None:
                self.plan_view.undo_requested.disconnect(self._undo_svc.undo)
                self.plan_view.redo_requested.disconnect(self._undo_svc.redo)
            self.plan_view.blockSignals(True)
            self.plan_view.cleanup()
            self.plan_view = None
        if self._undo_svc is not None:
            self._undo_svc.clear()
        self._undo_svc = None
        self._annotation_clipboard_svc = None
        self._ann_write_svc = None
        self._file_path = None
        self._renderers = None
        self._color_service = None
        self._config = None
        self._pages_with_takeoffs.clear()
        self._on_page_selected = None
        self._on_named_view_selected = None
        self._on_scale_changed = None
        self._page_combo.page_activated.disconnect(self._on_page_activated)
        self._page_combo.cleanup()
        self._page_combo = None
        self._named_view_combo.currentIndexChanged.disconnect(
            self._on_named_view_combo_changed
        )
        self._named_view_combo.cleanup_popup()
        self._named_view_combo = None
        self._scale_combo = None
        self._btn_select = None
        self._annotation_tool_buttons = {}
        self._page_view_states.clear()
        self._named_views = []
        self.event_bus = None
        self.view = None
        self.page_data = None
        self.icon_provider = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.cleanup()
        super().closeEvent(event)
