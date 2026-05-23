import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from ....application.dtos.page_view_dto import PageViewDto
from ....application.dtos.plan_view_renderers_dto import PlanViewRenderers
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_coordinate_transformer import ICoordinateTransformer
from ....application.interfaces.i_window_icon_provider import IWindowIconProvider
from ....domain.entities.annotation_view import AnnotationView
from ....domain.entities.bid import Bid
from ...adapters.hotlink_event_adapter import HotlinkEventAdapter
from ...components.page_combo import SinglePageComboBox
from ...components.plan_view.view import TakeoffPlanView
from ...components.resizable_combo import ResizableComboBox
from ...components.viewer_cursors import make_zoom_cursor
from ...config import (
    COMPACT_MARGINS,
    COMPACT_SPACING,
    DEFAULT_ICON_SIZE,
    NO_MARGINS,
    NO_SPACING,
)
from ...managers.icon_manager import IconId, IconManager
from ...services.selection_commands import DeleteAnnotationsCommand
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


class DetachedPageViewWindow(QtWidgets.QMainWindow):
    dropdown_size_changed = QtCore.Signal()
    _PAGE_UID_ROLE = QtCore.Qt.ItemDataRole.UserRole

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
        initial_is_maximized: bool = True,
        navigation_source: str = "unknown",
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
        self._named_views: List[NamedViewEntry] = named_views or []
        self._on_named_view_selected: Optional[Callable[[str, str], None]] = (
            on_named_view_selected
        )
        self._on_scale_changed: Optional[Callable[[str, float, float], None]] = (
            on_scale_changed
        )
        self._ann_write_svc = annotation_write_service
        self._file_path: Optional[str] = file_path
        self._undo_svc = undo_service
        self.plan_view: Optional[TakeoffPlanView] = None
        self._read_only: bool = False
        self._is_closing: bool = False
        self._show_timer: Optional[QtCore.QTimer] = None
        self._initial_show_requested: bool = False
        self._initial_page_geometry_ready: bool = False
        self._named_view_resize_focus_timer: Optional[QtCore.QTimer] = None
        self._pending_named_view_resize_focus: bool = False
        self._named_view_blank_canvas_active: bool = False
        self._hotlink_adapter: Optional[HotlinkEventAdapter] = None
        self._initial_geometry = QtCore.QByteArray()
        self._initial_show_maximized = True
        self._navigation_source = navigation_source
        self._scale_combo: Optional[QtWidgets.QComboBox] = None
        self._btn_select: Optional[QtWidgets.QToolButton] = None
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
        if bid:
            self._populate_page_combo(bid)
        if self._named_views:
            self._populate_named_view_combo()
        self.set_initial_window_state(
            initial_geometry or QtCore.QByteArray(), initial_is_maximized
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
        self, geometry: QtCore.QByteArray, is_maximized: bool
    ) -> None:
        self._initial_geometry = QtCore.QByteArray(geometry)
        self._initial_show_maximized = bool(is_maximized)
        if self._initial_geometry and not self._initial_geometry.isEmpty():
            self.restoreGeometry(self._initial_geometry)

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
        nav_layout = QtWidgets.QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(*COMPACT_MARGINS)
        nav_layout.setSpacing(COMPACT_SPACING)
        self._btn_prev = QtWidgets.QPushButton()
        IconManager.apply(self._btn_prev, IconId.PREVIOUS_PAGE)
        self._btn_prev.setIconSize(QtCore.QSize(*DEFAULT_ICON_SIZE))
        self._btn_prev.setFixedWidth(28)
        self._btn_prev.setToolTip("Previous page")
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
        self._btn_next.setToolTip("Next page")
        self._btn_next.clicked.connect(self._go_next_page)
        self._named_view_combo = ResizableComboBox()
        self._named_view_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._named_view_combo.setMinimumWidth(100)
        self._named_view_combo.setToolTip("Named views")
        nav_layout.addWidget(self._btn_prev)
        nav_layout.addWidget(self._page_combo, 1)
        nav_layout.addWidget(self._btn_next)
        nav_layout.addWidget(QtWidgets.QLabel("View"))
        nav_layout.addWidget(self._named_view_combo, 1)
        if self._config.show_scale_combo:
            self._scale_combo = QtWidgets.QComboBox()
            self._scale_combo.setFixedWidth(120)
            self._scale_combo.setToolTip("Scale")
            for sf1, sf2, label in ALL_SCALES:
                self._scale_combo.addItem(label, (sf1, sf2))
            self._scale_combo.setCurrentIndex(-1)
            nav_layout.addWidget(QtWidgets.QLabel("Scale"))
            nav_layout.addWidget(self._scale_combo)
        btn_size = QtCore.QSize(*DEFAULT_ICON_SIZE)
        self._cursor_group = QtWidgets.QButtonGroup(nav_bar)
        self._cursor_group.setExclusive(True)
        if self._config.show_select_tool:
            self._btn_select = QtWidgets.QToolButton()
            IconManager.apply(self._btn_select, IconId.SELECT_TOOL)
            self._btn_select.setIconSize(btn_size)
            self._btn_select.setCheckable(True)
            self._btn_select.setToolTip("Select")
            self._cursor_group.addButton(self._btn_select)
            nav_layout.addWidget(self._btn_select)
        self._btn_pan = QtWidgets.QToolButton()
        IconManager.apply(self._btn_pan, IconId.PAN_TOOL)
        self._btn_pan.setIconSize(btn_size)
        self._btn_pan.setCheckable(True)
        self._btn_pan.setToolTip("Pan")
        self._cursor_group.addButton(self._btn_pan)
        nav_layout.addWidget(self._btn_pan)
        self._btn_zoom_mode = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_mode, IconId.ZOOM_TOOL)
        self._btn_zoom_mode.setIconSize(btn_size)
        self._btn_zoom_mode.setCheckable(True)
        self._btn_zoom_mode.setToolTip("Zoom")
        self._cursor_group.addButton(self._btn_zoom_mode)
        nav_layout.addWidget(self._btn_zoom_mode)
        self._btn_fit = QtWidgets.QToolButton()
        IconManager.apply(self._btn_fit, IconId.RESET_VIEW)
        self._btn_fit.setIconSize(btn_size)
        self._btn_fit.setToolTip("Reset view")
        self._btn_zoom_in = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_in, IconId.ZOOM_IN)
        self._btn_zoom_in.setIconSize(btn_size)
        self._btn_zoom_in.setToolTip("Zoom in")
        self._btn_zoom_out = QtWidgets.QToolButton()
        IconManager.apply(self._btn_zoom_out, IconId.ZOOM_OUT)
        self._btn_zoom_out.setIconSize(btn_size)
        self._btn_zoom_out.setToolTip("Zoom out")
        nav_layout.addWidget(self._btn_fit)
        nav_layout.addWidget(self._btn_zoom_in)
        nav_layout.addWidget(self._btn_zoom_out)
        main_layout.addWidget(nav_bar)
        self.plan_view = TakeoffPlanView(
            self._color_service,
            self._renderers.rendering_service,
            self._renderers.load_coordinator,
            self._renderers.takeoff_renderer,
            self._renderers.annotation_renderer,
            self._renderers.linear_geometry,
        )
        self.plan_view.set_selection_enabled(self._selection_enabled())
        self.plan_view.set_annotation_only_selection(
            self._config.allow_annotation_editing
        )
        main_layout.addWidget(self.plan_view, 1)
        self._hotlink_adapter = HotlinkEventAdapter(self.event_bus)
        self._hotlink_adapter.set_plan_view(self.plan_view)
        self.plan_view.positions_flushed.connect(self._on_positions_flushed)
        self.plan_view.elements_deleted.connect(self._on_elements_deleted)
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
                    self.plan_view.set_cursor_mode("select") if checked else None
                )
            )
        self._btn_pan.toggled.connect(
            lambda checked: self.plan_view.set_cursor_mode("pan") if checked else None
        )
        self._btn_fit.clicked.connect(self.plan_view.fit_to_page)
        self._btn_zoom_in.clicked.connect(self.plan_view.zoom_in)
        self._btn_zoom_out.clicked.connect(self.plan_view.zoom_out)
        self._btn_zoom_mode.toggled.connect(
            lambda checked: self.plan_view.set_cursor_mode("zoom") if checked else None
        )
        self.plan_view.set_zoom_cursor(make_zoom_cursor())
        self._set_default_cursor_mode()

    def _set_default_cursor_mode(self) -> None:
        button_map = {
            "select": self._btn_select,
            "pan": self._btn_pan,
            "zoom": self._btn_zoom_mode,
        }
        button = button_map.get(self._config.default_cursor_mode) or self._btn_pan
        button.setChecked(True)

    def _selection_enabled(self) -> bool:
        return self._config.allow_annotation_editing and not self._read_only

    def _populate_page_combo(self, bid: Bid) -> None:
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
        try:
            idx = order.index(self.view.target_page_uid)
        except ValueError:
            return
        if idx > 0:
            self._on_page_selected(order[idx - 1])

    def _go_next_page(self) -> None:
        if not self.view or not self._on_page_selected:
            return
        order = self._page_combo.get_page_order()
        try:
            idx = order.index(self.view.target_page_uid)
        except ValueError:
            return
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
        try:
            idx = order.index(page_uid)
        except ValueError:
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
            return
        self._btn_prev.setEnabled(idx > 0)
        self._btn_next.setEnabled(idx < len(order) - 1)

    def load_view(
        self,
        view: AnnotationView,
        page_data: Optional[PageViewDto] = None,
        navigation_source: str = "unknown",
    ) -> None:
        self._navigation_source = navigation_source
        self.view = view
        if page_data is not None:
            self.page_data = page_data
        if self._should_use_named_view_blank_canvas():
            self._start_named_view_blank_canvas()
        else:
            self._reveal_named_view_blank_canvas()
        self._load_page_content()
        self._update_combo_to_page(view.target_page_uid)
        self._sync_current_page_takeoff_indicator()
        self._page_combo.set_pages_with_takeoffs(self._pages_with_takeoffs)

    def update_page(self, page_data: PageViewDto) -> None:
        if self._is_closing:
            return
        self.page_data = page_data
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

    def _load_page_content(self) -> None:
        page = self.page_data.page if self.page_data else None
        if not page:
            return
        self._update_scale_combo(page.scale_factor1, page.scale_factor2)
        try:
            self.plan_view.load_page(
                page=page,
                takeoffs=self.page_data.takeoffs,
                conditions=self.page_data.conditions,
                color_map=self.page_data.color_map,
                bid_ref=self.page_data.bid_ref,
                annotations=self.page_data.annotations,
                page_area_selections=self.page_data.page_area_selections,
            )
            self._apply_named_view_focus_if_possible(require_stable_view=False)
        except Exception:
            self.logger.exception("Error loading page into plan_view")

    def _focus_on_named_view(self) -> None:
        if self._is_closing:
            return
        named_view = self.page_data.named_view if self.page_data else None
        if not named_view:
            return
        try:
            self.plan_view.zoom_to_rect(
                named_view.min_x,
                named_view.min_y,
                named_view.max_x,
                named_view.max_y,
                margin=0.1,
            )
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
            self.restoreGeometry(geometry)
        if self._initial_show_maximized:
            self.showMaximized()
            return
        self.show()
        if geometry and not geometry.isEmpty():
            self.restoreGeometry(geometry)

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        if self._scale_combo is not None:
            self._scale_combo.setEnabled(not read_only)
        if self.plan_view:
            self.plan_view.set_selection_enabled(self._selection_enabled())

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
        if not self._ann_write_svc.save_annotation_positions(db_path, new_changes):
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
        ann_write_svc = self._ann_write_svc

        def _undo_move():
            ann_write_svc.save_annotation_positions(db_path, old_changes)

        def _redo_move():
            ann_write_svc.save_annotation_positions(db_path, new_changes)

        self._undo_svc.push(_undo_move, _redo_move)

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
        for uid in uids:
            ann = self.plan_view.get_annotation(uid)
            if ann and ann.is_interactive:
                saved_annotations.append(ann)
        if not saved_annotations:
            return
        if not self._ann_write_svc.delete_annotations(
            db_path,
            [(a.uid, a.annotation_type) for a in saved_annotations],
        ):
            return
        if self._undo_svc is None:
            return
        cmd = DeleteAnnotationsCommand(
            saved_annotations=saved_annotations,
            bid_ref=bid_ref,
            write_svc=self._ann_write_svc,
            plan_view=self.plan_view,
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
            self.plan_view.positions_flushed.disconnect(self._on_positions_flushed)
            self.plan_view.elements_deleted.disconnect(self._on_elements_deleted)
            if self._undo_svc is not None:
                self.plan_view.undo_requested.disconnect(self._undo_svc.undo)
                self.plan_view.redo_requested.disconnect(self._undo_svc.redo)
            self.plan_view.blockSignals(True)
            self.plan_view.cleanup()
            self.plan_view = None
        if self._undo_svc is not None:
            self._undo_svc.clear()
            self._undo_svc = None
        self._ann_write_svc = None
        self._file_path = None
        self._on_page_selected = None
        self._on_named_view_selected = None
        self._on_scale_changed = None
        self._page_combo.page_activated.disconnect(self._on_page_activated)
        self._page_combo.cleanup()
        self._named_view_combo.currentIndexChanged.disconnect(
            self._on_named_view_combo_changed
        )
        self._named_view_combo.cleanup_popup()
        self._named_views = []
        self.event_bus = None
        self.view = None
        self.page_data = None
        self.icon_provider = None

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.cleanup()
        super().closeEvent(event)
