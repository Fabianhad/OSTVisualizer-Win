import math
import uuid
from typing import Dict, List, Optional, Set, Tuple
from PySide6 import QtCore, QtSvg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QPushButton,
    QRubberBand,
)
from ....application.dtos.hotlink_dto import HotlinkDto
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_linear_geometry import ILinearGeometry
from ....application.interfaces.i_page_load_strategy_service import (
    IPageLoadStrategyService,
)
from ....application.interfaces.i_page_rendering_service import IPageRenderingService
from ....domain.entities.annotation import BidAnnotation, int_color_to_hex
from ....domain.entities.condition import Condition
from ....domain.entities.config import Config
from ....domain.entities.identity_refs import BidRef
from ....domain.entities.page import Page
from ....domain.entities.takeoff import Takeoff
from ...configurators.window_configurator import resource_path
from ...interfaces.i_annotation_item_renderer import IAnnotationItemRenderer
from ...interfaces.i_takeoff_renderer import ITakeoffRenderer
from ...scene.scene_builder import SceneBuilder
from ...utils.color_swatch import rounded_color_swatch
from ...utils.theme import set_palette_background
from ...utils.themed_icon import apply_themed_icon, current_text_hex, recolor_svg
from ...utils.zoom_debouncer import ZoomDebouncer
from ...visualization.utils.image_effects import page_effect_paper_color
from ..viewer_cursors import OUTLINE_OFFSETS, recolor_pixmap
from .components.drag_handler import DragHandlerMixin
from .components.geometry_utils import HandleInfo, polygon_centroid
from .components.graphics_items import (
    ClippedTextGraphicsItem,
    ImageBackgroundItem,
    NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND,
    NAMED_VIEW_LABEL_ITEM_KIND,
    TileGraphicsItem,
    TileKey,
)
from .components.input_handler import InputHandlerMixin
from .components.page_loader import PageLoaderMixin
from .components.placement_mode import PlacementModeMixin
from .components.selection_manager import SelectionManagerMixin
from .components.zoom_handler import ZoomHandlerMixin

SLOPE_ROTATE_HANDLE_HEX = "#2f9e44"
SLOPE_ROTATE_HANDLE_RGB = (47, 158, 68)
_INTELLIGENT_PASTE_AXIS_SNAP_PX = 8
_INTELLIGENT_PASTE_GUIDE_HEX = "#1f9d45"
_TEXT_TOOL_ICON_SIZE = 20
_TEXT_TOOL_BUTTON_SIZE = 26
_TEXT_TOOL_COLOR_SWATCH_SIZE = 20
_TEXT_TOOL_BOLD_ICON = "format_bold_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
_TEXT_TOOL_ITALIC_ICON = "format_italic_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
_TEXT_TOOL_UNDERLINE_ICON = (
    "format_underlined_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
)
_TEXT_TOOL_ALIGN_LEFT_ICON = (
    "format_align_left_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
)
_TEXT_TOOL_ALIGN_CENTER_ICON = (
    "format_align_center_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
)
_TEXT_TOOL_ALIGN_RIGHT_ICON = (
    "format_align_right_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg"
)


def _build_annotation_dict(
    annotations: List[BidAnnotation],
    takeoff_uids: Optional[set] = None,
) -> Tuple[Dict[str, BidAnnotation], Dict[str, str]]:
    result: Dict[str, BidAnnotation] = {}
    db_uid_map: Dict[str, str] = {}
    reserved = set(takeoff_uids) if takeoff_uids else set()
    for a in annotations:
        if a.uid not in result and a.uid not in reserved:
            result[a.uid] = a
        else:
            base = f"{a.uid}_{a.annotation_type}"
            key = base
            counter = 1
            while key in result or key in reserved:
                key = f"{base}_{counter}"
                counter += 1
            result[key] = a
            db_uid_map[key] = a.uid
    return result, db_uid_map


def _rects_nearly_equal(
    left: QtCore.QRectF,
    right: QtCore.QRectF,
    tolerance: float = 0.001,
) -> bool:
    return (
        abs(left.x() - right.x()) <= tolerance
        and abs(left.y() - right.y()) <= tolerance
        and abs(left.width() - right.width()) <= tolerance
        and abs(left.height() - right.height()) <= tolerance
    )


_SCENE_RECT_MARGIN = 50.0


class TakeoffPlanView(
    InputHandlerMixin,
    ZoomHandlerMixin,
    PageLoaderMixin,
    SelectionManagerMixin,
    DragHandlerMixin,
    PlacementModeMixin,
    QGraphicsView,
):
    hotlink_clicked = Signal(object)
    page_geometry_ready = Signal()
    page_fully_loaded = Signal()
    zoom_changed = Signal(float)
    assign_to_area_requested = Signal(list)
    reassign_condition_requested = Signal(list, str)
    set_negative_requested = Signal(list, bool)
    set_curved_requested = Signal(list, bool)
    overlay_display_mode_requested = Signal(int)
    positions_flushed = Signal(list, list)
    annotation_text_properties_flushed = Signal(list)
    annotation_text_and_positions_flushed = Signal(list, list)
    condition_text_properties_flushed = Signal(list)
    text_annotation_edit_mode_changed = Signal(bool)
    rotations_flushed = Signal(list)
    group_rotation_flushed = Signal(list, list, list)
    takeoff_created = Signal(str, list, str)
    hole_created = Signal(str, list, str, str)
    elements_deleted = Signal(list)
    takeoff_selection_changed = Signal(list)
    cursor_mode_change_requested = Signal(str)
    undo_requested = Signal()
    redo_requested = Signal()
    copy_requested = Signal(list)
    area_placement_in_progress = Signal(bool)
    backout_mode_changed = Signal(bool)
    place_exited = Signal()
    paste_requested = Signal()
    clipboard_changed = Signal()
    paste_backouts_placed = Signal(list, object)
    MIN_ZOOM = 0.05
    MAX_ZOOM = 16.0
    ZOOM_FACTOR = 1.15
    TILE_SIZE_PX: int = 1024
    _TILE_ACTIVATE_RATIO: float = 1.1

    def __init__(
        self,
        color_service: IColorService,
        rendering_service: IPageRenderingService,
        load_coordinator: IPageLoadStrategyService,
        takeoff_renderer: ITakeoffRenderer,
        annotation_renderer: IAnnotationItemRenderer,
        linear_geometry: ILinearGeometry,
        parent=None,
    ):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._load_coordinator = load_coordinator
        self._color_service = color_service
        self._linear_geom = linear_geometry
        self._scene_builder = SceneBuilder(
            takeoff_renderer,
            annotation_renderer,
        )
        self._rendering_service = rendering_service
        self._current_render_requests: List[str] = []
        self._pending_page_data: Optional[Dict] = None
        self._defer_page_visual_reveal: bool = False
        self._deferred_page_visual_result: Optional[Tuple[str, Dict, object]] = None
        self._background_item: Optional[ImageBackgroundItem] = None
        self._overlay_items: List[QGraphicsPixmapItem] = []
        self._zoom_debouncer = ZoomDebouncer(delay_ms=180, parent=self)
        self._zoom_debouncer.zoom_settled.connect(self._update_tile_coverage)
        self._scene_scale: float = 2.0
        self._can_zoom_rerender: bool = False
        self._is_composite_mode: bool = False
        self._loaded_visual_kind: Optional[str] = None
        self._pdf_width_pts: float = 0.0
        self._pdf_height_pts: float = 0.0
        self._tile_items: Dict[TileKey, TileGraphicsItem] = {}
        self._tile_requests: Dict[TileKey, str] = {}
        self._tile_scale: float = 0.0
        self._base_raster_scale: float = 0.0
        self._base_raster_request_id: Optional[str] = None
        self._base_raster_request_scale: float = 0.0
        self._base_correction_request_generation_id: int = 0
        self._page_render_generation_id: int = 0
        self._white_canvas_item: Optional[QGraphicsRectItem] = None
        self._takeoff_items: List = []
        self._hotlink_items: List[Tuple[QGraphicsItem, HotlinkDto]] = []
        self._current_bid_ref: Optional[BidRef] = None
        self._current_bid_page_uid: Optional[str] = None
        self._current_page: Optional[Page] = None
        self._current_render_identity: Optional[Dict] = None
        self._current_load_token: str = ""
        self._current_rotation: int = 0
        self._current_flip_x: bool = False
        self._current_flip_y: bool = False
        self._panning = False
        self._last_pan_point = None
        self._cursor_mode: str = "select"
        self._right_pan_active: bool = False
        self._right_pan_press_pos: Optional[QtCore.QPoint] = None
        self._right_pan_press_timer = QtCore.QElapsedTimer()
        self._right_pan_dragged: bool = False
        self._suppress_next_context_menu: bool = False
        self._ctrl_held: bool = False
        self._persistent_cursor_mode: str = "select"
        self._pre_zoom_persistent_mode: Optional[str] = None
        self._pre_pan_persistent_mode: Optional[str] = None
        self._zoom_cursor: QCursor = QCursor(Qt.CursorShape.CrossCursor)
        self._rotate_cursor: QCursor = QCursor(Qt.CursorShape.CrossCursor)
        self._rotate_handle_item: Optional[QGraphicsPixmapItem] = None
        self._rotate_line_item: Optional[QGraphicsLineItem] = None
        self._rotate_line_outline_item: Optional[QGraphicsLineItem] = None
        self._rotate_handle_uid: Optional[str] = None
        self._rotate_center_scene: QtCore.QPointF = QtCore.QPointF()
        self._rotate_handle_radius: float = 0.0
        self._rotate_handle_start_angle_deg: float = -90.0
        self._rotation_drag_uid: Optional[str] = None
        self._rotation_drag_active: bool = False
        self._rotation_drag_last_angle: float = 0.0
        self._rotation_drag_accumulated_deg: float = 0.0
        self._rotation_drag_snapped_deg: float = 0.0
        self._rotation_drag_preview_items: list = []
        self._rotation_drag_handle_origins: list = []
        self._rotation_drag_orig_positions: Dict[str, List[float]] = {}
        self._rotation_drag_orig_rotations: Dict[str, float] = {}
        self._rotate_ost_center: Tuple[float, float] = (0.0, 0.0)
        self._dirty_rotations: Dict[str, float] = {}
        self._rotation_before_edit: Dict[str, float] = {}
        self._rubber_band: Optional[QRubberBand] = None
        self._rubber_band_origin = None
        self._load_initial_view_mode: str = "fit"
        self._default_auto_zoom_level: int = 0
        self._load_geometry_ready: bool = False
        self._load_view_applied: bool = False
        self._load_waiting_for_visibility: bool = False
        self._load_geometry_notified: bool = False
        self._saved_scroll_state: Optional[Tuple[int, int]] = None
        self._zoom_press_ctrl: bool = False
        self._selection_enabled: bool = False
        self._annotation_only_selection: bool = False
        self._selected_uids: Set[str] = set()
        self._selection_items: List = []
        self._handle_infos: List[HandleInfo] = []
        self._current_takeoffs: Dict[str, Takeoff] = {}
        self._current_conditions: Dict[str, Condition] = {}
        self._current_color_map: Dict[str, str] = {}
        self._current_annotations: Dict[str, BidAnnotation] = {}
        self._uid_to_items: Dict[str, List] = {}
        self._select_band_origin: Optional[QtCore.QPointF] = None
        self._select_band_active: bool = False
        self._select_band_dragged: bool = False
        self._roping_selection_method: str = "touching"
        self._disable_high_resolution_images: bool = False
        self._intelligent_paste_enabled: bool = True
        self._show_right_angle_line_indicator: bool = False
        self._right_angle_indicator_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._use_full_window_crosshairs: bool = False
        self._crosshair_color: str = "#00ff00"
        self._crosshair_line_thickness: int = 1
        self._mouse_unpressed_snap_angle: int = 15
        self._mouse_pressed_snap_angle: int = 0
        self._snap_to_grid_enabled: bool = True
        self._snap_to_grid_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._snap_to_pdf_lines_enabled: bool = True
        self._snap_to_pdf_lines_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._snap_to_takeoffs_enabled: bool = True
        self._snap_to_takeoffs_threshold_px: int = Config.DEFAULT_SNAP_THRESHOLD_PX
        self._intelligent_paste_pending_uids: List[str] = []
        self._intelligent_paste_pending_source_anchor_ost: Optional[
            Tuple[float, float]
        ] = None
        self._intelligent_paste_active: bool = False
        self._intelligent_paste_source_anchor_ost: Optional[Tuple[float, float]] = None
        self._intelligent_paste_anchor_start_ost: Optional[Tuple[float, float]] = None
        self._intelligent_paste_drag_positions_start_ost: Dict[str, List[float]] = {}
        self._intelligent_paste_guide_items: List[QGraphicsItem] = []
        self._advanced_mouse_controls_enabled: bool = True
        self._press_changed_selection: bool = False
        self._snap_increments: float = 0.0
        self._dirty_positions: Dict[str, List[float]] = {}
        self._dirty_ann_positions: Dict[str, Tuple[str, List[float]]] = {}
        self._position_before_edit: Dict[str, List[float]] = {}
        self._ann_db_uid_map: Dict[str, str] = {}
        self._drag_takeoff_uid: Optional[str] = None
        self._drag_handle_index: int = -2
        self._drag_handle_corner_count: int = 0
        self._drag_orig_position: List[float] = []
        self._drag_item_orig_positions: Dict[int, QtCore.QPointF] = {}
        self._drag_item_orig_paths: Dict[int, QPainterPath] = {}
        self._drag_uid_orig_items: Dict[str, List] = {}
        self._drag_multi_orig_positions: Dict[str, List[float]] = {}
        self._drag_last_valid_new_pos: List[float] = []
        self._last_mouse_vp_pos: Optional[QtCore.QPoint] = None
        self._place_session_uid: Optional[str] = None
        self._place_all_condition_uids: List[str] = []
        self._place_points: List[Tuple[float, float]] = []
        self._place_preview_items: List[QGraphicsItem] = []
        self._takeoff_snap_index = None
        self._pdf_snap_index = None
        self._takeoff_snap_index_dirty: bool = True
        self._pdf_snap_index_dirty: bool = True
        self._pdf_snap_segments_cache_key = None
        self._pdf_snap_segments_cache: List[tuple] = []
        self._backout_parent_uid: Optional[str] = None
        self._backout_active_uid: Optional[str] = None
        self._backout_mode_active: bool = False
        self._backout_orig_parent_path = None
        self._backout_last_valid_ost: Optional[Tuple[float, float]] = None
        self._area_in_progress: bool = False
        self._place_linear_dragging: bool = False
        self._place_area_rect_dragging: bool = False
        self._place_flashing: bool = False
        self._paste_backout_active: bool = False
        self._paste_backout_sources: List[Dict] = []
        self._paste_backout_source_bid_uid: Optional[str] = None
        self._paste_backout_group_centroid: Tuple[float, float] = (0.0, 0.0)
        self._paste_backout_preview_items: List[QGraphicsItem] = []
        self._context_menu_command_trigger = None
        self._context_menu_action_state = None
        self._selected_text_item: Optional[QGraphicsTextItem] = None
        self._selected_text_annotation_uid: Optional[str] = None
        self._selected_text_model_font_size: Optional[int] = None
        self._selected_text_annotation_font_scale: float = 1.0
        self._editing_text_annotation_uid: Optional[str] = None
        self._editing_named_view_uid: Optional[str] = None
        self._editing_named_view_item: Optional[QGraphicsTextItem] = None
        self._editing_text_document = None
        self._editing_text_original: str = ""
        self._finishing_text_annotation_edit: bool = False
        self._text_annotation_inline_edit_enabled: bool = True
        self._text_annotation_inline_edit_allowed_fn = None
        self._condition_text_toolbar = self._build_condition_text_toolbar()
        self._condition_text_toolbar.hide()
        self._scene.focusItemChanged.connect(self._on_scene_focus_item_changed)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._set_palette_background()

    def _build_condition_text_toolbar(self) -> QFrame:
        toolbar = QFrame(self)
        toolbar.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(3)
        self._condition_text_font_combo = QFontComboBox(toolbar)
        self._condition_text_font_combo.currentFontChanged.connect(
            lambda _font: self._apply_condition_text_format()
        )
        layout.addWidget(self._condition_text_font_combo)
        self._condition_text_size_combo = QComboBox(toolbar)
        for size in (8, 9, 10, 11, 12, 14, 16, 18, 24, 36):
            self._condition_text_size_combo.addItem(str(size), size)
        self._condition_text_size_combo.setCurrentText("9")
        self._condition_text_size_combo.currentIndexChanged.connect(
            lambda _index: self._apply_condition_text_format()
        )
        layout.addWidget(self._condition_text_size_combo)
        self._condition_text_color_btn = QPushButton(toolbar)
        self._condition_text_color_btn.setFixedSize(
            _TEXT_TOOL_BUTTON_SIZE, _TEXT_TOOL_BUTTON_SIZE
        )
        self._condition_text_color_btn.setToolTip("Text color")
        self._update_condition_text_color_swatch(QColor("#000000"))
        self._condition_text_color_btn.clicked.connect(self._pick_condition_text_color)
        layout.addWidget(self._condition_text_color_btn)
        self._condition_text_bold_btn = self._make_text_toggle_button(
            toolbar, _TEXT_TOOL_BOLD_ICON, "Bold"
        )
        self._condition_text_italic_btn = self._make_text_toggle_button(
            toolbar, _TEXT_TOOL_ITALIC_ICON, "Italic"
        )
        self._condition_text_underline_btn = self._make_text_toggle_button(
            toolbar, _TEXT_TOOL_UNDERLINE_ICON, "Underline"
        )
        for button in (
            self._condition_text_bold_btn,
            self._condition_text_italic_btn,
            self._condition_text_underline_btn,
        ):
            layout.addWidget(button)
        self._condition_text_align_left_btn = self._make_text_align_button(
            toolbar,
            _TEXT_TOOL_ALIGN_LEFT_ICON,
            "Align left",
            Qt.AlignmentFlag.AlignLeft,
        )
        self._condition_text_align_center_btn = self._make_text_align_button(
            toolbar,
            _TEXT_TOOL_ALIGN_CENTER_ICON,
            "Align center",
            Qt.AlignmentFlag.AlignHCenter,
        )
        self._condition_text_align_right_btn = self._make_text_align_button(
            toolbar,
            _TEXT_TOOL_ALIGN_RIGHT_ICON,
            "Align right",
            Qt.AlignmentFlag.AlignRight,
        )
        for button in (
            self._condition_text_align_left_btn,
            self._condition_text_align_center_btn,
            self._condition_text_align_right_btn,
        ):
            layout.addWidget(button)
        toolbar.adjustSize()
        toolbar.move(8, 8)
        return toolbar

    def _make_text_toggle_button(
        self, parent: QFrame, icon_name: str, tooltip: str
    ) -> QPushButton:
        button = QPushButton(parent)
        button.setCheckable(True)
        button.setFixedSize(_TEXT_TOOL_BUTTON_SIZE, _TEXT_TOOL_BUTTON_SIZE)
        button.setIconSize(QtCore.QSize(_TEXT_TOOL_ICON_SIZE, _TEXT_TOOL_ICON_SIZE))
        button.setToolTip(tooltip)
        apply_themed_icon(button, icon_name)
        button.toggled.connect(lambda _checked: self._apply_condition_text_format())
        return button

    def _make_text_align_button(
        self,
        parent: QFrame,
        icon_name: str,
        tooltip: str,
        alignment: Qt.AlignmentFlag,
    ) -> QPushButton:
        button = QPushButton(parent)
        button.setCheckable(True)
        button.setFixedSize(_TEXT_TOOL_BUTTON_SIZE, _TEXT_TOOL_BUTTON_SIZE)
        button.setIconSize(QtCore.QSize(_TEXT_TOOL_ICON_SIZE, _TEXT_TOOL_ICON_SIZE))
        button.setToolTip(tooltip)
        apply_themed_icon(button, icon_name)
        button.clicked.connect(
            lambda _checked=False, align=alignment: self._set_condition_text_alignment(
                align
            )
        )
        return button

    def _position_condition_text_toolbar(self) -> None:
        toolbar = self._condition_text_toolbar
        if toolbar is not None:
            toolbar.move(8, 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_condition_text_toolbar()

    def _condition_text_label_at(
        self, viewport_pos: QtCore.QPoint
    ) -> Optional[QGraphicsTextItem]:
        item = self.itemAt(viewport_pos)
        if isinstance(item, QGraphicsTextItem) and item.data(2) == "condition_label":
            return item
        return None

    def _named_view_label_at(
        self, viewport_pos: QtCore.QPoint
    ) -> Optional[QGraphicsTextItem]:
        item = self.itemAt(viewport_pos)
        if (
            isinstance(item, QGraphicsTextItem)
            and item.data(2) == NAMED_VIEW_LABEL_ITEM_KIND
        ):
            return item
        return None

    def _select_condition_text_label(self, item: QGraphicsTextItem) -> None:
        self._finish_active_inline_text_edit(commit=True)
        self._show_text_toolbar_for_item(item, annotation_uid=None)

    def _show_text_toolbar_for_item(
        self, item: QGraphicsTextItem, annotation_uid: Optional[str]
    ) -> None:
        if (
            self._selected_text_item is not None
            and self._selected_text_item is not item
        ):
            self._selected_text_item.setSelected(False)
        self._selected_text_item = item
        self._selected_text_annotation_uid = annotation_uid
        self._selected_text_model_font_size = self._model_font_size_for_text_item(
            item, annotation_uid
        )
        self._selected_text_annotation_font_scale = (
            self._rendered_to_model_font_scale(
                item, self._selected_text_model_font_size
            )
            if annotation_uid is not None
            else 1.0
        )
        item.setSelected(annotation_uid is None)
        self._sync_condition_text_controls(item)
        self._condition_text_toolbar.show()
        self._condition_text_toolbar.raise_()

    def _clear_text_selection(self) -> None:
        self._finish_active_inline_text_edit(commit=True)
        self._clear_text_toolbar_target()

    def _clear_text_toolbar_target(self) -> None:
        if self._selected_text_item is not None:
            self._selected_text_item.setSelected(False)
        self._selected_text_item = None
        self._selected_text_annotation_uid = None
        self._selected_text_model_font_size = None
        self._selected_text_annotation_font_scale = 1.0
        self._condition_text_toolbar.hide()

    def _set_condition_text_control_signals_blocked(self, blocked: bool) -> None:
        for widget in (
            self._condition_text_font_combo,
            self._condition_text_size_combo,
            self._condition_text_bold_btn,
            self._condition_text_italic_btn,
            self._condition_text_underline_btn,
            self._condition_text_align_left_btn,
            self._condition_text_align_center_btn,
            self._condition_text_align_right_btn,
        ):
            widget.blockSignals(blocked)

    def _sync_condition_text_controls(self, item: QGraphicsTextItem) -> None:
        font = item.font()
        self._set_condition_text_control_signals_blocked(True)
        self._condition_text_font_combo.setCurrentFont(font)
        point_size = self._selected_text_model_font_size
        if point_size is None:
            point_size = max(font.pointSize(), 1)
        if self._condition_text_size_combo.findData(point_size) < 0:
            self._condition_text_size_combo.addItem(str(point_size), point_size)
        self._condition_text_size_combo.setCurrentText(str(point_size))
        self._condition_text_bold_btn.setChecked(font.bold())
        self._condition_text_italic_btn.setChecked(font.italic())
        self._condition_text_underline_btn.setChecked(font.underline())
        alignment = item.document().defaultTextOption().alignment()
        self._sync_condition_text_alignment_buttons(alignment)
        self._set_condition_text_alignment_buttons_enabled(
            self._selected_text_annotation_uid is not None
        )
        self._update_condition_text_color_swatch(item.defaultTextColor())
        self._set_condition_text_control_signals_blocked(False)

    def _set_condition_text_alignment_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self._condition_text_align_left_btn,
            self._condition_text_align_center_btn,
            self._condition_text_align_right_btn,
        ):
            button.setEnabled(enabled)

    def _sync_condition_text_alignment_buttons(
        self, alignment: Qt.AlignmentFlag
    ) -> None:
        centered = bool(alignment & Qt.AlignmentFlag.AlignHCenter)
        right = bool(alignment & Qt.AlignmentFlag.AlignRight)
        self._condition_text_align_left_btn.setChecked(not centered and not right)
        self._condition_text_align_center_btn.setChecked(centered)
        self._condition_text_align_right_btn.setChecked(right)

    def _update_condition_text_color_swatch(self, color: QColor) -> None:
        self._condition_text_color_btn.setIcon(
            QIcon(rounded_color_swatch(color, _TEXT_TOOL_COLOR_SWATCH_SIZE))
        )
        self._condition_text_color_btn.setIconSize(
            QtCore.QSize(_TEXT_TOOL_COLOR_SWATCH_SIZE, _TEXT_TOOL_COLOR_SWATCH_SIZE)
        )
        self._condition_text_color_btn.setToolTip(f"Text color ({color.name()})")

    def _apply_condition_text_format(self) -> None:
        item = self._selected_text_item
        if item is None:
            return
        uid = self._selected_text_annotation_uid
        model_size = int(self._condition_text_size_combo.currentData() or 9)
        self._selected_text_model_font_size = model_size
        font = QFont(self._condition_text_font_combo.currentFont())
        rendered_size = max(
            1, int(round(model_size * self._selected_text_annotation_font_scale))
        )
        font.setPointSize(rendered_size)
        font.setBold(self._condition_text_bold_btn.isChecked())
        font.setItalic(self._condition_text_italic_btn.isChecked())
        font.setUnderline(self._condition_text_underline_btn.isChecked())
        item.setFont(font)
        if uid is None:
            self._refresh_condition_text_label_layout(item)
        self._persist_selected_text_annotation()
        self._refresh_selected_text_annotation_selection_visuals()

    def _pick_condition_text_color(self) -> None:
        item = self._selected_text_item
        if item is None:
            return
        color = QColorDialog.getColor(item.defaultTextColor(), self)
        if color.isValid():
            uid = self._selected_text_annotation_uid
            item.setDefaultTextColor(color)
            self._update_condition_text_color_swatch(color)
            if uid is None:
                self._refresh_condition_text_label_layout(item)
            self._persist_selected_text_annotation(autosize=False)

    def _set_condition_text_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        item = self._selected_text_item
        if item is None or self._selected_text_annotation_uid is None:
            return
        option = QTextOption(item.document().defaultTextOption())
        option.setAlignment(alignment)
        item.document().setDefaultTextOption(option)
        self._set_condition_text_control_signals_blocked(True)
        self._sync_condition_text_alignment_buttons(alignment)
        self._set_condition_text_control_signals_blocked(False)
        self._persist_selected_text_annotation(autosize=False)
        self._refresh_selected_text_annotation_selection_visuals()

    def _refresh_selected_text_annotation_selection_visuals(self) -> None:
        uid = self._selected_text_annotation_uid
        if uid is None or uid not in self._selected_uids:
            return
        self.update_selection_visuals(emit=False)

    def _autosize_text_annotation_box(
        self,
        uid: str,
        item: QGraphicsTextItem,
        text_override: Optional[str] = None,
    ) -> Optional[Tuple[str, str, List[float], List[float]]]:
        ann = self._current_annotations.get(uid)
        if ann is None or not ann.is_text or len(ann.position) < 4:
            return None
        scene_width, scene_height = self._text_annotation_document_scene_size(
            item, text_override
        )
        cs = self._scene_builder.get_coordinate_system()
        ost_per_scene_px = 1.0 / cs.ost_to_screen_pixels(1.0)
        new_width = max(scene_width * ost_per_scene_px, 0.01)
        new_height = max(scene_height * ost_per_scene_px, 0.01)
        old_position = list(ann.position)
        if math.isclose(
            old_position[2], new_width, rel_tol=0.0, abs_tol=1e-6
        ) and math.isclose(old_position[3], new_height, rel_tol=0.0, abs_tol=1e-6):
            self._apply_text_annotation_box_to_item(ann, item)
            return None
        new_position = list(old_position)
        new_position[2] = new_width
        new_position[3] = new_height
        ann.position = new_position
        self._apply_text_annotation_box_to_item(ann, item)
        self._refresh_selected_text_annotation_selection_visuals()
        return (
            self._ann_db_uid_map.get(uid, uid),
            ann.annotation_type,
            old_position,
            list(new_position),
        )

    def _text_annotation_document_scene_size(
        self,
        item: QGraphicsTextItem,
        text_override: Optional[str] = None,
    ) -> Tuple[float, float]:
        document = QTextDocument()
        document.setDefaultFont(item.font())
        document.setDefaultTextOption(QTextOption(item.document().defaultTextOption()))
        document.setDocumentMargin(item.document().documentMargin())
        document.setPlainText(
            text_override if text_override is not None else item.toPlainText()
        )
        document.setTextWidth(-1)
        size = document.size()
        return max(size.width(), 1.0), max(size.height(), 1.0)

    def _apply_text_annotation_box_to_item(
        self, ann: BidAnnotation, item: QGraphicsTextItem
    ) -> None:
        if len(ann.position) < 4:
            return
        cx, cy, width, height = ann.position[:4]
        cs = self._scene_builder.get_coordinate_system()
        scene_width = cs.ost_to_screen_pixels(width)
        scene_height = cs.ost_to_screen_pixels(height)
        top_left = self._ost_to_scene_pos(cx - width / 2.0, cy - height / 2.0)
        item.setPos(top_left)
        item.setTextWidth(scene_width)
        item.setTransformOriginPoint(scene_width / 2.0, scene_height / 2.0)
        if isinstance(item, ClippedTextGraphicsItem):
            item.set_clip_rect(QtCore.QRectF(0.0, 0.0, scene_width, scene_height))

    def _model_font_size_for_text_item(
        self, item: QGraphicsTextItem, annotation_uid: Optional[str]
    ) -> int:
        if annotation_uid is not None:
            ann = self._current_annotations.get(annotation_uid)
            if ann is not None:
                return max(int(ann.properties.get("FontSize", 12) or 12), 1)
        return max(item.font().pointSize(), 1)

    def _rendered_to_model_font_scale(
        self, item: QGraphicsTextItem, model_font_size: Optional[int]
    ) -> float:
        rendered_size = item.font().pointSize()
        if rendered_size <= 0 or model_font_size is None or model_font_size <= 0:
            return 1.0
        return rendered_size / model_font_size

    def _text_toolbar_contains_widget(self, widget) -> bool:
        toolbar = self._condition_text_toolbar
        if toolbar is None or widget is None:
            return False
        if widget is toolbar:
            return True
        return toolbar.isAncestorOf(widget)

    def _text_toolbar_combo_popup_open(self) -> bool:
        return (
            self._condition_text_font_combo.view().isVisible()
            or self._condition_text_size_combo.view().isVisible()
        )

    def _text_toolbar_contains_global_point(self, global_pos: QtCore.QPoint) -> bool:
        toolbar = self._condition_text_toolbar
        if toolbar is None or toolbar.isHidden():
            return False
        return toolbar.rect().contains(toolbar.mapFromGlobal(global_pos))

    def _text_toolbar_has_focus_or_pointer(self) -> bool:
        if self._text_toolbar_contains_widget(QApplication.focusWidget()):
            return True
        if self._text_toolbar_combo_popup_open():
            return True
        return self._text_toolbar_contains_global_point(QCursor.pos())

    def _text_annotation_item(self, uid: str) -> Optional[QGraphicsTextItem]:
        for item in self._uid_to_items.get(uid, []):
            if (
                isinstance(item, QGraphicsTextItem)
                and item.data(2) != "condition_label"
                and item.data(2) != NAMED_VIEW_LABEL_ITEM_KIND
            ):
                return item
        return None

    def _named_view_label_item(self, uid: str) -> Optional[QGraphicsTextItem]:
        for item in self._uid_to_items.get(uid, []):
            if (
                isinstance(item, QGraphicsTextItem)
                and item.data(2) == NAMED_VIEW_LABEL_ITEM_KIND
            ):
                return item
        return None

    def _named_view_label_background_item(
        self, uid: str
    ) -> Optional[QGraphicsRectItem]:
        for item in self._uid_to_items.get(uid, []):
            if (
                isinstance(item, QGraphicsRectItem)
                and item.data(2) == NAMED_VIEW_LABEL_BACKGROUND_ITEM_KIND
            ):
                return item
        return None

    def _named_view_label_contains_scene_point(
        self, uid: str, scene_pos: QtCore.QPointF
    ) -> bool:
        item = self._named_view_label_item(uid)
        if item is None:
            return False
        return item.boundingRect().contains(item.mapFromScene(scene_pos))

    def _select_text_annotation_label(self, uid: str) -> bool:
        item = self._text_annotation_item(uid)
        ann = self._current_annotations.get(uid)
        if item is None or ann is None or not ann.is_text:
            return False
        self._show_text_toolbar_for_item(item, annotation_uid=uid)
        return True

    def _restore_selected_text_annotation_toolbar(self, uid: Optional[str]) -> None:
        if uid is None or uid not in self._selected_uids:
            return
        ann = self._current_annotations.get(uid)
        if ann is None or not ann.is_text:
            return
        self._select_text_annotation_label(uid)

    def _selected_condition_text_label_target(
        self,
    ) -> Optional[Tuple[str, str]]:
        item = self._selected_text_item
        if (
            self._selected_text_annotation_uid is not None
            or item is None
            or item.data(2) != "condition_label"
        ):
            return None
        takeoff_uid = item.data(0)
        label_kind = item.data(3)
        if takeoff_uid is None or label_kind is None:
            return None
        return str(takeoff_uid), str(label_kind)

    def _restore_selected_condition_text_label_toolbar(
        self, target: Optional[Tuple[str, str]]
    ) -> None:
        if target is None:
            return
        takeoff_uid, label_kind = target
        item = self._condition_label_text_item(takeoff_uid, label_kind)
        if item is None:
            return
        self._show_text_toolbar_for_item(item, annotation_uid=None)

    def _begin_text_annotation_edit(self, uid: str) -> bool:
        if not self._can_begin_text_annotation_inline_edit():
            return False
        self._finish_named_view_rename(commit=True)
        if (
            self._editing_text_annotation_uid is not None
            and self._editing_text_annotation_uid != uid
        ):
            self._finish_text_annotation_edit(commit=True)
        was_inactive = self._editing_text_annotation_uid is None
        if not self._select_text_annotation_label(uid):
            return False
        item = self._selected_text_item
        ann = self._current_annotations.get(uid)
        if item is None or ann is None:
            return False
        self._editing_text_annotation_uid = uid
        self._editing_text_original = str(ann.properties.get("Text", ""))
        item.setPlainText(self._editing_text_original)
        self._set_inline_text_document(item.document())
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        item.setFocus(Qt.FocusReason.MouseFocusReason)
        if was_inactive:
            self.text_annotation_edit_mode_changed.emit(True)
        return True

    def _begin_named_view_rename(self, uid: str) -> bool:
        if not self._can_begin_text_annotation_inline_edit():
            return False
        self._finish_text_annotation_edit(commit=True)
        if (
            self._editing_named_view_uid is not None
            and self._editing_named_view_uid != uid
        ):
            self._finish_named_view_rename(commit=True)
        item = self._named_view_label_item(uid)
        ann = self._current_annotations.get(uid)
        if item is None or ann is None or not ann.is_namedview:
            return False
        was_inactive = not self.is_text_annotation_inline_edit_active()
        self._clear_text_toolbar_target()
        self._editing_named_view_uid = uid
        self._editing_named_view_item = item
        self._editing_text_original = str(ann.properties.get("Text", ""))
        item.setPlainText(self._editing_text_original)
        self._set_inline_text_document(item.document())
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        item.setFocus(Qt.FocusReason.MouseFocusReason)
        self._refresh_named_view_label_background(uid)
        if was_inactive:
            self.text_annotation_edit_mode_changed.emit(True)
        return True

    def _set_inline_text_document(self, document) -> None:
        if self._editing_text_document is document:
            return
        self._clear_inline_text_document()
        self._editing_text_document = document
        document.contentsChanged.connect(self._refresh_active_inline_text_visuals)

    def _clear_inline_text_document(self) -> None:
        if self._editing_text_document is None:
            return
        self._editing_text_document.contentsChanged.disconnect(
            self._refresh_active_inline_text_visuals
        )
        self._editing_text_document = None

    def _refresh_active_inline_text_visuals(self) -> None:
        self._refresh_selected_text_annotation_selection_visuals()
        if self._editing_named_view_uid is not None:
            self._refresh_named_view_label_background(self._editing_named_view_uid)

    def _on_scene_focus_item_changed(self, new_item, old_item, _reason) -> None:
        editing_item = self._active_inline_text_item()
        if (
            editing_item is not None
            and old_item is editing_item
            and new_item is not editing_item
            and not self._text_toolbar_has_focus_or_pointer()
        ):
            self._finish_active_inline_text_edit(commit=True)

    def _inline_text_annotation_editor_contains_scene_point(
        self, scene_pos: QtCore.QPointF
    ) -> bool:
        uid = self._editing_text_annotation_uid
        if uid is None:
            return False
        return self._text_annotation_contains_scene_point(uid, scene_pos)

    def _active_inline_text_editor_contains_scene_point(
        self, scene_pos: QtCore.QPointF
    ) -> bool:
        if self._editing_text_annotation_uid is not None:
            return self._inline_text_annotation_editor_contains_scene_point(scene_pos)
        if self._editing_named_view_uid is not None:
            return self._named_view_label_contains_scene_point(
                self._editing_named_view_uid, scene_pos
            )
        return False

    def _active_inline_text_item(self) -> Optional[QGraphicsTextItem]:
        if self._editing_text_annotation_uid is not None:
            return self._text_annotation_item(self._editing_text_annotation_uid)
        if self._editing_named_view_uid is not None:
            return self._editing_named_view_item
        return None

    def _finish_active_inline_text_edit(self, commit: bool) -> None:
        if self._editing_named_view_uid is not None:
            self._finish_named_view_rename(commit)
        self._finish_text_annotation_edit(commit)

    def _finish_text_annotation_edit(self, commit: bool) -> None:
        if (
            self._finishing_text_annotation_edit
            or self._editing_text_annotation_uid is None
        ):
            return
        uid = self._editing_text_annotation_uid
        item = self._text_annotation_item(uid)
        ann = self._current_annotations.get(uid)
        error: Optional[Exception] = None
        self._finishing_text_annotation_edit = True
        try:
            if item is not None:
                if commit and ann is not None:
                    text = item.toPlainText()
                    try:
                        self._persist_text_annotation(uid, item, text_override=text)
                    except Exception as exc:
                        error = exc
                elif not commit:
                    item.setPlainText(self._editing_text_original)
                item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                item.clearFocus()
            self._clear_inline_text_document()
            self._editing_text_annotation_uid = None
            self._editing_text_original = ""
            self.text_annotation_edit_mode_changed.emit(False)
        finally:
            self._finishing_text_annotation_edit = False
        if error is not None:
            raise error

    def _finish_named_view_rename(self, commit: bool) -> None:
        if self._editing_named_view_uid is None:
            return
        uid = self._editing_named_view_uid
        item = self._editing_named_view_item
        ann = self._current_annotations.get(uid)
        try:
            if item is not None:
                if commit and ann is not None:
                    self._persist_named_view_name(uid, item.toPlainText())
                elif not commit:
                    item.setPlainText(self._editing_text_original)
                item.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
                item.clearFocus()
        finally:
            self._clear_inline_text_document()
            self._editing_named_view_uid = None
            self._editing_named_view_item = None
            self._editing_text_original = ""
            self.text_annotation_edit_mode_changed.emit(False)
        self._refresh_named_view_label_background(uid)

    def _persist_named_view_name(self, uid: str, text: str) -> None:
        ann = self._current_annotations.get(uid)
        if ann is None or not ann.is_namedview:
            return
        old_text = str(ann.properties.get("Text", ""))
        if old_text == text:
            return
        old_props = {"Text": old_text}
        new_props = {"Text": text}
        ann.properties.update(new_props)
        self.annotation_text_properties_flushed.emit(
            [
                (
                    self._ann_db_uid_map.get(uid, uid),
                    ann.annotation_type,
                    old_props,
                    new_props,
                )
            ]
        )

    def _refresh_named_view_label_background(self, uid: str) -> None:
        label = self._named_view_label_item(uid)
        background = self._named_view_label_background_item(uid)
        if label is None or background is None:
            return
        padding = 3.0
        bounds = label.boundingRect()
        pos = label.pos()
        background.setRect(
            QtCore.QRectF(
                pos.x() + bounds.left() + 1.0,
                pos.y() + bounds.top() + 1.0,
                max(bounds.width() - 2.0, 1.0) + padding * 2.0,
                max(bounds.height() - 2.0, 1.0) + padding * 2.0,
            )
        )

    def is_text_annotation_inline_edit_active(self) -> bool:
        return (
            self._editing_text_annotation_uid is not None
            or self._editing_named_view_uid is not None
        )

    def set_text_annotation_inline_edit_enabled(self, enabled: bool) -> None:
        self._text_annotation_inline_edit_enabled = bool(enabled)
        if not enabled:
            self._finish_active_inline_text_edit(commit=True)

    def set_text_annotation_inline_edit_allowed_fn(self, allowed_fn) -> None:
        self._text_annotation_inline_edit_allowed_fn = allowed_fn

    def _can_begin_text_annotation_inline_edit(self) -> bool:
        if not self._text_annotation_inline_edit_enabled or not self._selection_enabled:
            return False
        if self._text_annotation_inline_edit_allowed_fn is None:
            return True
        return bool(self._text_annotation_inline_edit_allowed_fn())

    def handle_inline_text_shortcut(self, action_key: str) -> bool:
        item = self._active_inline_text_item()
        if item is None or not self.is_text_annotation_inline_edit_active():
            return False
        cursor = item.textCursor()
        if action_key == "select_all":
            cursor.select(QTextCursor.SelectionType.Document)
            item.setTextCursor(cursor)
            return True
        if action_key == "copy":
            text = cursor.selectedText()
            if text:
                QApplication.clipboard().setText(text)
            return True
        if action_key == "cut":
            text = cursor.selectedText()
            if text:
                QApplication.clipboard().setText(text)
                cursor.removeSelectedText()
                item.setTextCursor(cursor)
            return True
        if action_key == "paste":
            cursor.insertText(QApplication.clipboard().text())
            item.setTextCursor(cursor)
            return True
        if action_key == "delete":
            if cursor.hasSelection():
                cursor.removeSelectedText()
            else:
                cursor.deleteChar()
            item.setTextCursor(cursor)
            return True
        return False

    def _text_annotation_properties(
        self,
        uid: str,
        item: QGraphicsTextItem,
        text_override: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        ann = self._current_annotations.get(uid)
        if ann is None:
            return None
        font = item.font()
        color = item.defaultTextColor()
        alignment = item.document().defaultTextOption().alignment()
        if alignment & Qt.AlignmentFlag.AlignRight:
            text_align = 2
        elif alignment & Qt.AlignmentFlag.AlignHCenter:
            text_align = 1
        else:
            text_align = 0
        font_size = (
            self._selected_text_model_font_size
            if uid == self._selected_text_annotation_uid
            else None
        )
        if font_size is None or font_size <= 0:
            font_size = font.pointSize()
        if font_size <= 0:
            font_size = int(ann.properties.get("FontSize", 12) or 12)
        font_color = color.red() | (color.green() << 8) | (color.blue() << 16)
        return {
            "Text": (
                text_override
                if text_override is not None
                else str(ann.properties.get("Text", ""))
            ),
            "FontName": font.family(),
            "FontColor": font_color,
            "FontSize": int(font_size),
            "FontBold": bool(font.bold()),
            "FontItalic": bool(font.italic()),
            "FontUnderline": bool(font.underline()),
            "TextAlign": text_align,
        }

    def _persist_selected_text_annotation(
        self, text_override: Optional[str] = None, *, autosize: bool = True
    ) -> None:
        uid = self._selected_text_annotation_uid
        item = self._selected_text_item
        if item is None:
            return
        if uid is None:
            self._persist_selected_condition_text_label(item)
            return
        self._persist_text_annotation(uid, item, text_override, autosize=autosize)

    def _refresh_condition_text_label_layout(self, item: QGraphicsTextItem) -> None:
        if item.data(2) != "condition_label":
            return
        takeoff_uid = item.data(0)
        label_kind = item.data(3)
        path_item = self._condition_label_takeoff_path_item(str(takeoff_uid))
        if path_item is None:
            return
        path = path_item.path()
        condition = self._condition_label_condition(str(takeoff_uid))
        self._position_condition_text_label(item, path, condition)
        if (
            label_kind == "display_dimension"
            and condition is not None
            and condition.is_area
        ):
            name_item = self._condition_label_text_item(
                str(takeoff_uid), "display_name"
            )
            if name_item is not None:
                self._position_condition_text_label(name_item, path, condition)
                name_item.update()
        item.setSelected(True)
        item.update()
        self.viewport().update()

    def _position_condition_text_label(
        self,
        item: QGraphicsTextItem,
        path: QPainterPath,
        condition: Optional[Condition],
    ) -> None:
        label_kind = item.data(3)
        text_bounds = item.boundingRect()
        if label_kind == "display_dimension":
            center = self._condition_label_path_centroid(path)
            if center is None:
                bounds_center = path.boundingRect().center()
                center = bounds_center.x(), bounds_center.y()
            item.setPos(
                center[0] - text_bounds.width() / 2.0,
                center[1] - text_bounds.height() / 2.0,
            )
        elif condition is not None and condition.is_area:
            dimension_item = self._condition_label_text_item(
                str(item.data(0)), "display_dimension", exclude=item
            )
            if dimension_item is not None:
                dimension_bounds = dimension_item.boundingRect()
                dimension_center_x = (
                    dimension_item.pos().x() + dimension_bounds.width() / 2.0
                )
                item.setPos(
                    dimension_center_x - text_bounds.width() / 2.0,
                    dimension_item.pos().y() + dimension_bounds.height() + 4.0,
                )
            else:
                center = self._condition_label_path_centroid(path)
                if center is None:
                    bounds_center = path.boundingRect().center()
                    center = bounds_center.x(), bounds_center.y()
                item.setPos(
                    center[0] - text_bounds.width() / 2.0,
                    center[1] - text_bounds.height() / 2.0,
                )
        else:
            bounds = path.boundingRect()
            item.setPos(
                bounds.center().x() - text_bounds.width() / 2.0,
                bounds.bottom() + 4.0,
            )

    def _condition_label_condition(self, takeoff_uid: str) -> Optional[Condition]:
        takeoff = self._current_takeoffs.get(takeoff_uid)
        if takeoff is None:
            return None
        return self._current_conditions.get(takeoff.condition_uid)

    def _condition_label_text_item(
        self,
        takeoff_uid: str,
        label_kind: str,
        exclude: Optional[QGraphicsTextItem] = None,
    ) -> Optional[QGraphicsTextItem]:
        for candidate in self._uid_to_items.get(takeoff_uid, []):
            if (
                candidate is not exclude
                and isinstance(candidate, QGraphicsTextItem)
                and candidate.data(2) == "condition_label"
                and candidate.data(3) == label_kind
            ):
                return candidate
        return None

    def _condition_label_takeoff_path_item(self, takeoff_uid: str):
        for candidate in self._uid_to_items.get(takeoff_uid, []):
            if (
                isinstance(candidate, QGraphicsPathItem)
                and candidate.data(2) != "condition_label"
            ):
                return candidate
        return None

    def _condition_label_path_centroid(
        self, path: QPainterPath
    ) -> Optional[Tuple[float, float]]:
        points = []
        for i in range(path.elementCount()):
            elem = path.elementAt(i)
            if elem.type.value in (0, 1):
                points.append((elem.x, elem.y))
        if len(points) < 3:
            return None
        flat_points = [coord for point in points for coord in point]
        return polygon_centroid(flat_points, len(points))

    def _persist_selected_condition_text_label(self, item: QGraphicsTextItem) -> None:
        takeoff_uid = item.data(0)
        label_kind = item.data(3)
        if takeoff_uid is None:
            return
        takeoff = self._current_takeoffs.get(str(takeoff_uid))
        if takeoff is None:
            return
        font = item.font()
        color = item.defaultTextColor()
        prefix = "dimension_font" if label_kind == "display_dimension" else "name_font"
        new_props = {
            f"{prefix}_name": font.family(),
            f"{prefix}_color": color.red()
            | (color.green() << 8)
            | (color.blue() << 16),
            f"{prefix}_size": int(self._selected_text_model_font_size or 9),
            f"{prefix}_bold": bool(font.bold()),
            f"{prefix}_italic": bool(font.italic()),
            f"{prefix}_underline": bool(font.underline()),
        }
        old_props = {
            key: self._takeoff_text_style_value(takeoff, key) for key in new_props
        }
        if old_props == new_props:
            return
        self._apply_takeoff_text_style_values(takeoff, new_props)
        self.condition_text_properties_flushed.emit(
            [(takeoff.uid, str(label_kind), old_props, dict(new_props))]
        )

    def _takeoff_text_style_value(self, takeoff: Takeoff, key: str):
        if key == "dimension_font_name":
            return takeoff.dimension_font_name
        if key == "dimension_font_color":
            return takeoff.dimension_font_color
        if key == "dimension_font_size":
            return takeoff.dimension_font_size
        if key == "dimension_font_bold":
            return takeoff.dimension_font_bold
        if key == "dimension_font_italic":
            return takeoff.dimension_font_italic
        if key == "dimension_font_underline":
            return takeoff.dimension_font_underline
        if key == "name_font_name":
            return takeoff.name_font_name
        if key == "name_font_color":
            return takeoff.name_font_color
        if key == "name_font_size":
            return takeoff.name_font_size
        if key == "name_font_bold":
            return takeoff.name_font_bold
        if key == "name_font_italic":
            return takeoff.name_font_italic
        if key == "name_font_underline":
            return takeoff.name_font_underline
        raise KeyError(key)

    def _apply_takeoff_text_style_values(
        self, takeoff: Takeoff, values: Dict[str, object]
    ) -> None:
        if "dimension_font_name" in values:
            takeoff.dimension_font_name = str(values["dimension_font_name"])
        if "dimension_font_color" in values:
            takeoff.dimension_font_color = int(values["dimension_font_color"])
        if "dimension_font_size" in values:
            takeoff.dimension_font_size = int(values["dimension_font_size"])
        if "dimension_font_bold" in values:
            takeoff.dimension_font_bold = bool(values["dimension_font_bold"])
        if "dimension_font_italic" in values:
            takeoff.dimension_font_italic = bool(values["dimension_font_italic"])
        if "dimension_font_underline" in values:
            takeoff.dimension_font_underline = bool(values["dimension_font_underline"])
        if "name_font_name" in values:
            takeoff.name_font_name = str(values["name_font_name"])
        if "name_font_color" in values:
            takeoff.name_font_color = int(values["name_font_color"])
        if "name_font_size" in values:
            takeoff.name_font_size = int(values["name_font_size"])
        if "name_font_bold" in values:
            takeoff.name_font_bold = bool(values["name_font_bold"])
        if "name_font_italic" in values:
            takeoff.name_font_italic = bool(values["name_font_italic"])
        if "name_font_underline" in values:
            takeoff.name_font_underline = bool(values["name_font_underline"])

    def _persist_text_annotation(
        self,
        uid: str,
        item: QGraphicsTextItem,
        text_override: Optional[str] = None,
        *,
        autosize: bool = True,
    ) -> None:
        ann = self._current_annotations.get(uid)
        new_props = self._text_annotation_properties(uid, item, text_override)
        if ann is None or new_props is None:
            return
        position_change = (
            self._autosize_text_annotation_box(uid, item, text_override)
            if autosize
            else None
        )
        keys = tuple(new_props.keys())
        old_props = {key: ann.properties.get(key) for key in keys}
        old_props["FontColor"] = self._annotation_font_color_int(ann)
        props_changed = any(old_props.get(key) != new_props.get(key) for key in keys)
        if not props_changed and position_change is None:
            return
        text_changes = []
        if props_changed:
            ann.properties.update(new_props)
            ann.color = int_color_to_hex(int(new_props["FontColor"]))
            text_changes.append(
                (
                    self._ann_db_uid_map.get(uid, uid),
                    ann.annotation_type,
                    old_props,
                    dict(new_props),
                )
            )
        position_changes = [position_change] if position_change is not None else []
        if text_changes and position_changes:
            self.annotation_text_and_positions_flushed.emit(
                text_changes, position_changes
            )
        elif text_changes:
            self.annotation_text_properties_flushed.emit(text_changes)
        else:
            self.positions_flushed.emit([], position_changes)

    def _annotation_font_color_int(self, annotation: BidAnnotation) -> int:
        value = annotation.properties.get("FontColor")
        if isinstance(value, int):
            return value
        color = QColor(str(value or annotation.color))
        if not color.isValid():
            return 0
        return color.red() | (color.green() << 8) | (color.blue() << 16)

    def set_context_menu_command_handlers(self, trigger_fn, action_state_fn) -> None:
        self._context_menu_command_trigger = trigger_fn
        self._context_menu_action_state = action_state_fn

    @property
    def current_page_uid(self) -> Optional[str]:
        return self._current_bid_page_uid

    def set_overlay_display_mode(self, mode: int) -> None:
        if self._current_page is not None:
            self._current_page.image_show_mode = int(mode)

    def _build_render_identity(
        self, page: Page, bid_ref: Optional[BidRef]
    ) -> Dict[str, object]:
        return {
            "bid_ref": bid_ref,
            "page_uid": page.uid,
            "page_index": page.page_index,
            "image_path": page.image_path or "",
            "overlay_image_path": page.overlay_image_path or "",
            "show_mode": page.image_show_mode,
            "rotation": page.rotation,
            "flip_x": page.flip_x,
            "flip_y": page.flip_y,
            "invert": page.invert,
            "bitonal": page.bitonal,
            "layer_visible": page.layer_visible,
            "width_pts": page.width_pts,
            "height_pts": page.height_pts,
            "overlay_offset_x": page.overlay_offset_x,
            "overlay_offset_y": page.overlay_offset_y,
            "overlay_rotation": page.overlay_rotation,
            "overlay_deskew": page.deskew_rotation_overlay,
        }

    def get_coordinate_system(self):
        return self._scene_builder.get_coordinate_system()

    def _page_canvas_color(self) -> QColor:
        page = self._current_page
        if page is None:
            return page_effect_paper_color()
        return page_effect_paper_color(invert=page.invert, bitonal=page.bitonal)

    def _current_handle_background_color(self) -> QColor:
        return self._page_canvas_color()

    def _ost_to_scene_pos(self, ost_x: float, ost_y: float) -> QtCore.QPointF:
        cs = self._scene_builder.get_coordinate_system()
        factor = 72.0 * cs.view_scale / cs.scale_ratio
        return self._pt_to_scene(ost_x * factor, ost_y * factor)

    def _page_scene_rect(self) -> QtCore.QRectF:
        for item in (self._background_item, self._white_canvas_item):
            if item is None or item.scene() is not self._scene:
                continue
            item_rect = item.sceneBoundingRect()
            if not item_rect.isNull():
                return item_rect
        return QtCore.QRectF()

    def _page_reset_scene_rect(self) -> QtCore.QRectF:
        page_rect = self._page_scene_rect()
        if page_rect.isNull() or not page_rect.isValid():
            return page_rect
        return page_rect.adjusted(
            -_SCENE_RECT_MARGIN,
            -_SCENE_RECT_MARGIN,
            _SCENE_RECT_MARGIN,
            _SCENE_RECT_MARGIN,
        )

    def _set_scene_rect_preserving_view_center(self, rect: QtCore.QRectF) -> None:
        current_rect = self._scene.sceneRect()
        if current_rect.isValid() and _rects_nearly_equal(current_rect, rect):
            return
        center = None
        viewport = self.viewport()
        if (
            self._load_view_applied
            and viewport is not None
            and viewport.size().isValid()
        ):
            center = self.mapToScene(viewport.rect().center())
        self._scene.setSceneRect(rect)
        if center is not None:
            self.centerOn(center)

    def _update_scene_rect(self) -> None:
        rect = QtCore.QRectF()
        scene_items = []
        if self._background_item is not None:
            scene_items.append(self._background_item)
        if self._white_canvas_item is not None:
            scene_items.append(self._white_canvas_item)
        scene_items.extend(self._takeoff_items)
        scene_items.extend(item for item, _ in self._hotlink_items)
        for item in scene_items:
            if item is None or item.scene() is not self._scene:
                continue
            item_rect = item.sceneBoundingRect()
            if item_rect.isNull():
                continue
            rect = item_rect if rect.isNull() else rect.united(item_rect)
        if rect.isNull():
            self._scene_builder.update_scene_rect(self._scene)
            return
        self._set_scene_rect_preserving_view_center(
            rect.adjusted(
                -_SCENE_RECT_MARGIN,
                -_SCENE_RECT_MARGIN,
                _SCENE_RECT_MARGIN,
                _SCENE_RECT_MARGIN,
            )
        )

    def _capture_view_state_to_page(self, page: Optional[Page]) -> None:
        if page is None or self._current_bid_page_uid != page.uid:
            return
        if not self._load_view_applied or not self._scene.sceneRect().isValid():
            return
        zoom_fac, cx, cy = self.get_view_state()
        if zoom_fac <= 0:
            return
        page.zoom_fac = zoom_fac
        page.current_x = cx
        page.current_y = cy

    def _capture_scroll_state(self) -> None:
        h_scroll = self.horizontalScrollBar()
        v_scroll = self.verticalScrollBar()
        self._saved_scroll_state = (
            h_scroll.value() if h_scroll is not None else 0,
            v_scroll.value() if v_scroll is not None else 0,
        )

    def _restore_scroll_state(self) -> None:
        if self._saved_scroll_state is None:
            return
        h_value, v_value = self._saved_scroll_state
        h_scroll = self.horizontalScrollBar()
        v_scroll = self.verticalScrollBar()
        if h_scroll is not None:
            h_scroll.setValue(h_value)
        if v_scroll is not None:
            v_scroll.setValue(v_value)
        self._saved_scroll_state = None

    def _begin_load_cycle(self, page: Page, preserve_current_view: bool) -> None:
        self._saved_scroll_state = None
        self._current_load_token = uuid.uuid4().hex
        if preserve_current_view:
            self._capture_view_state_to_page(page)
            self._capture_scroll_state()
        if page.zoom_fac > 0:
            self._load_initial_view_mode = "restore"
        elif self._default_auto_zoom_level > 0:
            self._load_initial_view_mode = "auto_zoom"
        else:
            self._load_initial_view_mode = "fit"
        self._load_geometry_ready = False
        self._load_view_applied = False
        self._load_waiting_for_visibility = False
        self._load_geometry_notified = False

    def _mark_load_geometry_ready(self) -> None:
        self._update_scene_rect()
        self._load_geometry_ready = True
        if not self._load_geometry_notified:
            self._load_geometry_notified = True
            self.page_geometry_ready.emit()
        self._finalize_page_load_if_ready()

    def _apply_current_view_contract(self, consume_scroll_state: bool) -> None:
        if (
            self._load_initial_view_mode == "restore"
            and self._current_page is not None
            and self._current_page.zoom_fac > 0
        ):
            if not self.restore_view_state(
                self._current_page.zoom_fac,
                self._current_page.current_x,
                self._current_page.current_y,
            ):
                self.fit_to_page()
            elif consume_scroll_state:
                self._restore_scroll_state()
        elif self._load_initial_view_mode == "auto_zoom":
            self.set_zoom_percent(self._default_auto_zoom_level)
        else:
            self.fit_to_page()

    def _apply_loading_view_contract(self) -> None:
        if (
            self._load_view_applied
            or not self.isVisible()
            or not self._scene.sceneRect().isValid()
        ):
            return
        self._apply_current_view_contract(consume_scroll_state=False)

    def _apply_pending_visible_view_state(self) -> None:
        if (
            self._load_view_applied
            or not self.isVisible()
            or not self.viewport().size().isValid()
        ):
            return
        self._apply_loading_view_contract()
        self._finalize_page_load_if_ready()

    def _finalize_page_load_if_ready(self) -> bool:
        if not self._load_geometry_ready or self._load_view_applied:
            return False
        if not self.isVisible():
            self._load_waiting_for_visibility = True
            return False
        self._load_waiting_for_visibility = False
        self._apply_current_view_contract(consume_scroll_state=True)
        self._saved_scroll_state = None
        self._load_view_applied = True
        self.page_fully_loaded.emit()
        return True

    @property
    def has_selection(self) -> bool:
        return bool(self._selected_uids)

    @property
    def has_selected_takeoffs(self) -> bool:
        return self._selection_enabled and any(
            uid in self._current_takeoffs for uid in self._selected_uids
        )

    @property
    def has_takeoff_objects(self) -> bool:
        return bool(self._current_takeoffs)

    @property
    def is_rotate_mode_active(self) -> bool:
        return (
            self._cursor_mode in ("rotate", "slope_rotate")
            or self._rotation_drag_active
        )

    @property
    def is_view_state_stable(self) -> bool:
        return self._load_view_applied and self._scene.sceneRect().isValid()

    @property
    def place_condition_uid(self) -> Optional[str]:
        return self._place_session_uid

    @property
    def backout_mode_active(self) -> bool:
        return self._backout_mode_active

    @property
    def snap_increments(self) -> float:
        return self._snap_increments

    def get_takeoff(self, uid: str):
        return self._current_takeoffs.get(uid)

    def backout_parent_candidate_uid(self) -> Optional[str]:
        if len(self._selected_uids) != 1:
            return None
        uid = next(iter(self._selected_uids))
        return self._valid_backout_parent_uid(uid)

    def is_backout_context_valid(self) -> bool:
        if not (
            self._backout_mode_active
            and self._backout_parent_uid
            and self._backout_active_uid
        ):
            return False
        parent_uid = self._valid_backout_parent_uid(self._backout_parent_uid)
        if parent_uid != self._backout_parent_uid:
            return False
        parent = self._current_takeoffs.get(parent_uid)
        return bool(parent and parent.condition_uid == self._backout_active_uid)

    def _valid_backout_parent_uid(self, parent_uid: Optional[str]) -> Optional[str]:
        if not parent_uid:
            return None
        takeoff = self._current_takeoffs.get(parent_uid)
        if not takeoff or takeoff.is_hole:
            return None
        condition = self._current_conditions.get(takeoff.condition_uid)
        if not condition or not condition.is_area:
            return None
        if not condition.layer_visible:
            return None
        cs = self._scene_builder.get_coordinate_system()
        parent_pos = cs.parse_position(takeoff.position)
        if not parent_pos or len(parent_pos) < 6:
            return None
        return takeoff.uid

    def _cancel_backout_if_invalid(self) -> None:
        has_backout_state = bool(
            self._backout_mode_active
            or self._backout_parent_uid
            or self._backout_active_uid
        )
        if has_backout_state and not self.is_backout_context_valid():
            self._clear_backout_state()

    def get_annotation(self, uid: str):
        return self._current_annotations.get(uid)

    def find_annotation_keys_by_uid_type(self, uid_type_set: set) -> set:
        return {
            key
            for key, ann in self._current_annotations.items()
            if (ann.uid, ann.annotation_type) in uid_type_set
        }

    def reset_ctrl_held(self) -> None:
        if self._ctrl_held:
            self._ctrl_held = False
            self._update_cursor()

    def set_annotation_only_selection(self, enabled: bool) -> None:
        self._annotation_only_selection = enabled

    def set_zoom_cursor(self, cursor: QCursor) -> None:
        self._zoom_cursor = cursor

    def set_rotate_cursor(self, cursor: QCursor) -> None:
        self._rotate_cursor = cursor

    def set_selection_enabled(self, enabled: bool) -> None:
        self._selection_enabled = enabled
        if not enabled:
            self.clear_selection_items()
            had_selection = bool(self._selected_uids)
            self._selected_uids.clear()
            if had_selection:
                self.takeoff_selection_changed.emit([])

    def set_roping_selection_method(self, method: str) -> None:
        self._roping_selection_method = (
            "inclusive" if method == "inclusive" else "touching"
        )

    def set_disable_high_resolution_images(self, disabled: bool) -> None:
        disabled = bool(disabled)
        if self._disable_high_resolution_images == disabled:
            return
        self._disable_high_resolution_images = disabled
        self.refresh_current_render_quality()

    def refresh_current_render_quality(self) -> None:
        if not self._current_page:
            return
        self._clear_tiles()
        self._cancel_optional_base_correction()
        if not self._can_zoom_rerender:
            self.viewport().update()
            return
        if self._disable_high_resolution_images:
            if (
                not self._is_composite_mode
                and self._background_item is not None
                and abs(self._base_raster_scale - self._scene_scale) > 1e-6
            ):
                self._request_optional_base_correction(
                    self._scene_scale,
                    self._advance_render_generation(),
                )
            self.viewport().update()
            return
        self._update_tile_coverage(self.transform().m11())
        self.viewport().update()

    def set_intelligent_paste_enabled(self, enabled: bool) -> None:
        self._intelligent_paste_enabled = bool(enabled)
        if not enabled:
            self.finish_intelligent_paste_placement()

    @property
    def intelligent_paste_enabled(self) -> bool:
        return self._intelligent_paste_enabled

    def _on_selection_changed(self) -> None:
        pending_uids = set(self._intelligent_paste_pending_uids)
        if pending_uids and not pending_uids.issubset(self._selected_uids):
            self.finish_intelligent_paste_placement()
        if (
            self._selected_text_annotation_uid is not None
            and self._selected_text_annotation_uid not in self._selected_uids
        ):
            self._clear_text_selection()

    def _current_mouse_scene_position(self) -> Optional[QtCore.QPointF]:
        if self._last_mouse_vp_pos is not None:
            return self.mapToScene(self._last_mouse_vp_pos)
        viewport = self.viewport()
        if viewport is not None and viewport.size().isValid():
            return self.mapToScene(viewport.rect().center())
        return None

    def current_mouse_ost_position(self) -> Optional[Tuple[float, float]]:
        scene_pos = self._current_mouse_scene_position()
        if scene_pos is None:
            return None
        ost_pos = self._scene_pos_to_ost(scene_pos)
        return ost_pos.x(), ost_pos.y()

    def mark_intelligent_paste_drag_pending(
        self,
        pasted_uids: list,
        source_anchor_ost: Tuple[float, float],
    ) -> bool:
        if not self._intelligent_paste_enabled or not pasted_uids:
            return False
        self.finish_intelligent_paste_placement(clear_pending=False)
        self._intelligent_paste_pending_uids = [str(uid) for uid in pasted_uids]
        self._intelligent_paste_pending_source_anchor_ost = (
            float(source_anchor_ost[0]),
            float(source_anchor_ost[1]),
        )
        return True

    def begin_intelligent_paste_drag_if_pending(
        self, drag_positions: Dict[str, List[float]]
    ) -> bool:
        if (
            not self._intelligent_paste_enabled
            or not self._intelligent_paste_pending_uids
            or self._intelligent_paste_pending_source_anchor_ost is None
        ):
            return False
        drag_uids = set(drag_positions)
        pending_uids = set(self._intelligent_paste_pending_uids)
        if not pending_uids.issubset(drag_uids):
            self.finish_intelligent_paste_placement()
            return False
        anchor_position = None
        drag_start_positions = {}
        for uid in self._intelligent_paste_pending_uids:
            pos = drag_positions.get(uid)
            if pos and len(pos) >= 2:
                anchor_position = pos
                break
        if anchor_position is None:
            self.finish_intelligent_paste_placement()
            return False
        for uid in self._intelligent_paste_pending_uids:
            pos = drag_positions.get(uid)
            if not pos or len(pos) < 2:
                continue
            drag_start_positions[uid] = [float(value) for value in pos]
        if not drag_start_positions:
            self.finish_intelligent_paste_placement()
            return False
        self._intelligent_paste_active = True
        self._intelligent_paste_source_anchor_ost = (
            self._intelligent_paste_pending_source_anchor_ost
        )
        self._intelligent_paste_anchor_start_ost = (
            float(anchor_position[0]),
            float(anchor_position[1]),
        )
        self._intelligent_paste_drag_positions_start_ost = drag_start_positions
        self._intelligent_paste_pending_uids = []
        self._intelligent_paste_pending_source_anchor_ost = None
        self._clear_intelligent_paste_guides()
        return True

    def finish_intelligent_paste_placement(self, clear_pending: bool = True) -> None:
        if clear_pending:
            self._intelligent_paste_pending_uids = []
            self._intelligent_paste_pending_source_anchor_ost = None
        self._intelligent_paste_active = False
        self._intelligent_paste_source_anchor_ost = None
        self._intelligent_paste_anchor_start_ost = None
        self._intelligent_paste_drag_positions_start_ost = {}
        self._clear_intelligent_paste_guides()

    def _clear_intelligent_paste_guides(self) -> None:
        for item in self._intelligent_paste_guide_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._intelligent_paste_guide_items.clear()

    def _set_intelligent_paste_guides(
        self, show_x_axis: bool, show_y_axis: bool, ost_dx: float, ost_dy: float
    ) -> None:
        self._clear_intelligent_paste_guides()
        if not (show_x_axis or show_y_axis):
            return
        rect = self._page_scene_rect()
        if rect.isNull() or not rect.isValid():
            rect = self._scene.sceneRect()
        if rect.isNull() or not rect.isValid():
            return
        bounds_scene = self._intelligent_paste_preview_bounds_scene(ost_dx, ost_dy)
        if bounds_scene is None:
            return
        guide_specs = []
        if show_x_axis:
            guide_specs.extend(
                (
                    (rect.left(), bounds_scene.top(), rect.right(), bounds_scene.top()),
                    (
                        rect.left(),
                        bounds_scene.bottom(),
                        rect.right(),
                        bounds_scene.bottom(),
                    ),
                )
            )
        if show_y_axis:
            guide_specs.extend(
                (
                    (
                        bounds_scene.left(),
                        rect.top(),
                        bounds_scene.left(),
                        rect.bottom(),
                    ),
                    (
                        bounds_scene.right(),
                        rect.top(),
                        bounds_scene.right(),
                        rect.bottom(),
                    ),
                )
            )
        if not guide_specs:
            return
        pen = QPen(QColor(_INTELLIGENT_PASTE_GUIDE_HEX))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        for x1, y1, x2, y2 in guide_specs:
            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(pen)
            line.setZValue(1000)
            self._scene.addItem(line)
            self._intelligent_paste_guide_items.append(line)

    def _intelligent_paste_preview_bounds_scene(
        self, ost_dx: float, ost_dy: float
    ) -> Optional[QtCore.QRectF]:
        min_x = min_y = max_x = max_y = None
        for uid, start_pos in self._intelligent_paste_drag_positions_start_ost.items():
            preview_pos = self._compute_snapped_multi_drag_position(
                uid, start_pos, ost_dx, ost_dy
            )
            for i in range(0, len(preview_pos) - 1, 2):
                point = self._ost_to_scene_pos(preview_pos[i], preview_pos[i + 1])
                if min_x is None:
                    min_x = max_x = point.x()
                    min_y = max_y = point.y()
                else:
                    min_x = min(min_x, point.x())
                    min_y = min(min_y, point.y())
                    max_x = max(max_x, point.x())
                    max_y = max(max_y, point.y())
        if min_x is None:
            return None
        return QtCore.QRectF(
            QtCore.QPointF(min_x, min_y),
            QtCore.QPointF(max_x, max_y),
        ).normalized()

    def _snapped_intelligent_paste_delta(
        self, ost_dx: float, ost_dy: float, snap_x_axis: bool, snap_y_axis: bool
    ) -> Tuple[float, float]:
        source_x, source_y = self._intelligent_paste_source_anchor_ost
        anchor_x, anchor_y = self._intelligent_paste_anchor_start_ost
        candidate_x = anchor_x + ost_dx
        candidate_y = anchor_y + ost_dy
        if snap_x_axis:
            ost_dy += source_y - candidate_y
        if snap_y_axis:
            ost_dx += source_x - candidate_x
        return ost_dx, ost_dy

    def apply_intelligent_paste_axis_snap(
        self, ost_dx: float, ost_dy: float
    ) -> Tuple[float, float]:
        if (
            not self._intelligent_paste_active
            or self._intelligent_paste_source_anchor_ost is None
            or self._intelligent_paste_anchor_start_ost is None
        ):
            return ost_dx, ost_dy
        source_x, source_y = self._intelligent_paste_source_anchor_ost
        anchor_x, anchor_y = self._intelligent_paste_anchor_start_ost
        candidate_x = anchor_x + ost_dx
        candidate_y = anchor_y + ost_dy
        source_scene = self._ost_to_scene_pos(source_x, source_y)
        candidate_scene = self._ost_to_scene_pos(candidate_x, candidate_y)
        source_vp = self.mapFromScene(source_scene)
        candidate_vp = self.mapFromScene(candidate_scene)
        snap_x_axis = abs(candidate_vp.y() - source_vp.y()) <= (
            _INTELLIGENT_PASTE_AXIS_SNAP_PX
        )
        snap_y_axis = abs(candidate_vp.x() - source_vp.x()) <= (
            _INTELLIGENT_PASTE_AXIS_SNAP_PX
        )
        ost_dx, ost_dy = self._snapped_intelligent_paste_delta(
            ost_dx, ost_dy, snap_x_axis, snap_y_axis
        )
        self._set_intelligent_paste_guides(snap_x_axis, snap_y_axis, ost_dx, ost_dy)
        return ost_dx, ost_dy

    def set_advanced_mouse_controls_enabled(self, enabled: bool) -> None:
        self._advanced_mouse_controls_enabled = bool(enabled)
        if not enabled:
            self.reset_ctrl_held()
            self._zoom_press_ctrl = False

    def set_default_auto_zoom_level(self, percent: int) -> None:
        self._default_auto_zoom_level = max(0, min(1600, int(percent)))

    def set_right_angle_line_indicator_enabled(self, enabled: bool) -> None:
        self._show_right_angle_line_indicator = bool(enabled)
        self.viewport().update()

    def set_full_window_crosshairs(
        self, enabled: bool, color: str, line_thickness: int
    ) -> None:
        self._use_full_window_crosshairs = bool(enabled)
        self._crosshair_color = str(color)
        self._crosshair_line_thickness = int(line_thickness)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setMouseTracking(self._use_full_window_crosshairs)
            viewport.update()

    def set_mouse_snap_angles(self, unpressed_angle: int, pressed_angle: int) -> None:
        self._mouse_unpressed_snap_angle = int(unpressed_angle)
        self._mouse_pressed_snap_angle = int(pressed_angle)

    def set_snap_preferences(
        self,
        *,
        snap_to_grid_enabled: bool,
        snap_to_grid_threshold_px: int,
        snap_to_pdf_lines_enabled: bool,
        snap_to_pdf_lines_threshold_px: int,
        snap_to_takeoffs_enabled: bool,
        snap_to_takeoffs_threshold_px: int,
        right_angle_indicator_threshold_px: int,
    ) -> None:
        self._snap_to_grid_enabled = bool(snap_to_grid_enabled)
        self._snap_to_grid_threshold_px = int(snap_to_grid_threshold_px)
        self._snap_to_pdf_lines_enabled = bool(snap_to_pdf_lines_enabled)
        self._snap_to_pdf_lines_threshold_px = int(snap_to_pdf_lines_threshold_px)
        self._snap_to_takeoffs_enabled = bool(snap_to_takeoffs_enabled)
        self._snap_to_takeoffs_threshold_px = int(snap_to_takeoffs_threshold_px)
        self._right_angle_indicator_threshold_px = int(
            right_angle_indicator_threshold_px
        )

    def drawForeground(self, painter: QPainter, rect: QtCore.QRectF) -> None:
        super().drawForeground(painter, rect)
        if (
            not self._use_full_window_crosshairs
            or self._cursor_mode != "place"
            or self._last_mouse_vp_pos is None
        ):
            return
        viewport = self.viewport()
        if viewport is None or not viewport.rect().contains(self._last_mouse_vp_pos):
            return
        scene_pos = self.mapToScene(self._last_mouse_vp_pos)
        visible_rect = self.mapToScene(viewport.rect()).boundingRect()
        if not visible_rect.isValid():
            return
        pen = QPen(QColor(self._crosshair_color))
        pen.setWidthF(float(self._crosshair_line_thickness))
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        painter.drawLine(
            QtCore.QPointF(visible_rect.left(), scene_pos.y()),
            QtCore.QPointF(visible_rect.right(), scene_pos.y()),
        )
        painter.drawLine(
            QtCore.QPointF(scene_pos.x(), visible_rect.top()),
            QtCore.QPointF(scene_pos.x(), visible_rect.bottom()),
        )
        painter.restore()

    def selected_takeoff_condition_uid(self) -> Optional[str]:
        if len(self._selected_uids) != 1:
            return None
        uid = next(iter(self._selected_uids))
        takeoff = self._current_takeoffs.get(uid)
        if not takeoff:
            return None
        if takeoff.condition_uid not in self._current_conditions:
            return None
        return takeoff.condition_uid

    def delete_selected(self) -> None:
        if not self._selection_enabled or not self._selected_uids:
            return
        uids = list(self._selected_uids)
        self._selected_uids.clear()
        self.update_selection_visuals()
        self._invalidate_snap_index()
        self.elements_deleted.emit(uids)
        self._update_cursor()

    def duplicate_selected(self) -> None:
        if not self._selection_enabled or not self._selected_uids:
            return
        self.copy_requested.emit(list(self._selected_uids))
        self.paste_requested.emit()

    def copy_selected(self) -> None:
        if not self._selection_enabled or not self._selected_uids:
            return
        self.copy_requested.emit(list(self._selected_uids))

    def paste_clipboard(self) -> None:
        if not self._selection_enabled:
            return
        self.paste_requested.emit()

    def select_all(self) -> None:
        if not self._selection_enabled or self._cursor_mode != "select":
            return
        all_uids = {
            uid
            for uid in (
                set(self._current_takeoffs.keys())
                | set(self._current_annotations.keys())
            )
            if self._is_selectable(uid)
        }
        self._selected_uids = all_uids
        self.update_selection_visuals()

    def set_snap_settings(self, takeoff_increments: float, measure_base: int) -> None:
        if takeoff_increments <= 0:
            self._snap_increments = 0.0
            return
        if measure_base == 1:
            self._snap_increments = takeoff_increments / 25.4
        else:
            self._snap_increments = takeoff_increments

    def _flush_dirty_positions(self) -> None:
        if not self._dirty_positions and not self._dirty_ann_positions:
            return
        if self._dirty_positions:
            self._invalidate_snap_index()
        dirty = dict(self._dirty_positions)
        ann_dirty = dict(self._dirty_ann_positions)
        prev = dict(self._position_before_edit)
        self._dirty_positions.clear()
        self._dirty_ann_positions.clear()
        self._position_before_edit.clear()
        takeoff_changes = [(uid, prev.get(uid, []), pos) for uid, pos in dirty.items()]
        ann_changes = [
            (self._ann_db_uid_map.get(uid, uid), ann_type, prev.get(uid, []), new_pos)
            for uid, (ann_type, new_pos) in ann_dirty.items()
        ]
        self.positions_flushed.emit(takeoff_changes, ann_changes)

    def _element_center(self, uid: str, cs, mode: str = "screen"):
        takeoff = self._current_takeoffs.get(uid)
        if takeoff and takeoff.position:
            pos = cs.parse_position(takeoff.position)
            if not pos or len(pos) < 2:
                return None
            tx = cs.transform_vertices_to_2d(pos) if mode == "screen" else pos
            condition = self._current_conditions.get(takeoff.condition_uid)
            if (
                len(pos) >= 6
                and condition
                and condition.is_linear
                and takeoff.curve >= 0
            ):
                rx = list(pos[:6])
                rx[0], rx[1], rx[2], rx[3], rx[4], rx[5] = (
                    self._linear_geom.proc_curved_pos(
                        pos, rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]
                    )
                )
                pts = cs.transform_vertices_to_2d(rx) if mode == "screen" else rx
                return pts[4], pts[5]
            n = len(tx) // 2
            if condition and condition.is_area and n >= 3:
                return polygon_centroid(tx, n)
            if condition and condition.is_linear and len(tx) >= 4:
                return (tx[0] + tx[2]) / 2, (tx[1] + tx[3]) / 2
            xs = [tx[i * 2] for i in range(n)]
            ys = [tx[i * 2 + 1] for i in range(n)]
            return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        ann = self._current_annotations.get(uid)
        if ann and ann.is_interactive and len(ann.position) >= 2:
            pos = ann.position
            if ann.is_text:
                if mode == "screen" and len(pos) >= 5 and pos[4] != 0.0:
                    cx_o, cy_o, w_o, h_o = pos[0], pos[1], pos[2], pos[3]
                    rad = pos[4]
                    cos_r, sin_r = math.cos(rad), math.sin(rad)
                    tl_x = cx_o - w_o / 2
                    tl_y = cy_o - h_o / 2
                    vis_cx = tl_x + (w_o / 2) * cos_r - (h_o / 2) * sin_r
                    vis_cy = tl_y + (w_o / 2) * sin_r + (h_o / 2) * cos_r
                    tx = cs.transform_vertices_to_2d([vis_cx, vis_cy])
                    return tx[0], tx[1]
                tx = (
                    cs.transform_vertices_to_2d(pos[:2])
                    if mode == "screen"
                    else pos[:2]
                )
                return tx[0], tx[1]
            if ann.is_ink:
                start = 1 if len(pos) % 2 == 1 else 0
                coords = pos[start:]
                tx = cs.transform_vertices_to_2d(coords) if mode == "screen" else coords
            else:
                tx = cs.transform_vertices_to_2d(pos) if mode == "screen" else pos
            n = len(tx) // 2
            if n >= 2:
                xs = [tx[i * 2] for i in range(n)]
                ys = [tx[i * 2 + 1] for i in range(n)]
                return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
            return tx[0], tx[1]
        return None

    def _is_rotatable_uid(self, uid: str) -> bool:
        ann = self._current_annotations.get(uid)
        if ann is not None:
            return ann.is_interactive and ann.can_rotate
        return uid in self._current_takeoffs

    def _create_rotate_handle(
        self,
        uids=None,
        *,
        start_angle_degrees: Optional[float] = None,
        slope_mode: bool = False,
    ) -> bool:
        self._remove_rotate_handle()
        if uids is None:
            uids = set(self._selected_uids)
        elif isinstance(uids, str):
            uids = {uids}
        uids = {uid for uid in uids if self._is_rotatable_uid(uid)}
        if not uids:
            return False
        cs = self._scene_builder.get_coordinate_system()
        screen_centers = []
        ost_centers = []
        first_uid = None
        for uid in uids:
            sc = self._element_center(uid, cs, "screen")
            oc = self._element_center(uid, cs, "ost")
            if sc and oc:
                screen_centers.append(sc)
                ost_centers.append(oc)
                if first_uid is None:
                    first_uid = uid
        if not screen_centers:
            return False
        cx = sum(c[0] for c in screen_centers) / len(screen_centers)
        cy = sum(c[1] for c in screen_centers) / len(screen_centers)
        ost_cx = sum(c[0] for c in ost_centers) / len(ost_centers)
        ost_cy = sum(c[1] for c in ost_centers) / len(ost_centers)
        self._rotate_ost_center = (ost_cx, ost_cy)
        center_scene = self._pt_to_scene(cx, cy)
        vp_scale = self.transform().m11()
        radius = 60.0 / vp_scale
        start_angle = -90.0 if start_angle_degrees is None else start_angle_degrees
        start_angle_rad = math.radians(start_angle)
        handle_x = center_scene.x() + radius * math.cos(start_angle_rad)
        handle_y = center_scene.y() + radius * math.sin(start_angle_rad)
        svg_path = resource_path(
            "resources",
            "icons",
            "replay_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        hex_color = SLOPE_ROTATE_HANDLE_HEX if slope_mode else current_text_hex()
        svg_data = recolor_svg(svg_path, hex_color)
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg_data))
        icon_pm = QPixmap(24, 24)
        icon_pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(icon_pm)
        renderer.render(painter)
        painter.end()
        black_pm = recolor_pixmap(icon_pm, QColor(0, 0, 0))
        outlined_pm = QPixmap(26, 26)
        outlined_pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(outlined_pm)
        for dx, dy in OUTLINE_OFFSETS:
            painter.drawPixmap(1 + dx, 1 + dy, black_pm)
        painter.drawPixmap(1, 1, icon_pm)
        painter.end()
        handle = QGraphicsPixmapItem(outlined_pm)
        handle.setOffset(-13, -13)
        handle.setZValue(20)
        handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        handle.setPos(handle_x, handle_y)
        black_pen = QPen(QColor(0, 0, 0))
        black_pen.setWidthF(3.0)
        black_pen.setCosmetic(True)
        line_outline = QGraphicsLineItem(
            center_scene.x(), center_scene.y(), handle_x, handle_y
        )
        line_outline.setPen(black_pen)
        line_outline.setZValue(17)
        text_color = (
            QColor(*SLOPE_ROTATE_HANDLE_RGB)
            if slope_mode
            else self.palette().color(QPalette.ColorRole.WindowText)
        )
        line_pen = QPen(text_color)
        line_pen.setWidthF(1.0)
        line_pen.setCosmetic(True)
        line = QGraphicsLineItem(center_scene.x(), center_scene.y(), handle_x, handle_y)
        line.setPen(line_pen)
        line.setZValue(18)
        self._scene.addItem(line_outline)
        self._scene.addItem(line)
        self._scene.addItem(handle)
        self._rotate_handle_item = handle
        self._rotate_line_item = line
        self._rotate_line_outline_item = line_outline
        self._rotate_handle_uid = first_uid
        self._rotate_center_scene = center_scene
        self._rotate_handle_radius = radius
        self._rotate_handle_start_angle_deg = start_angle
        return True

    def _remove_rotate_handle(self) -> None:
        if self._rotate_handle_item is not None:
            if self._rotate_handle_item.scene() is self._scene:
                self._scene.removeItem(self._rotate_handle_item)
            self._rotate_handle_item = None
        if self._rotate_line_item is not None:
            if self._rotate_line_item.scene() is self._scene:
                self._scene.removeItem(self._rotate_line_item)
            self._rotate_line_item = None
        if self._rotate_line_outline_item is not None:
            if self._rotate_line_outline_item.scene() is self._scene:
                self._scene.removeItem(self._rotate_line_outline_item)
            self._rotate_line_outline_item = None
        self._rotate_handle_uid = None
        self._rotate_handle_start_angle_deg = -90.0
        self._rotation_drag_uid = None
        self._rotation_drag_active = False

    def _flush_dirty_rotations(self) -> None:
        if not self._dirty_rotations:
            return
        dirty = dict(self._dirty_rotations)
        prev = dict(self._rotation_before_edit)
        self._dirty_rotations.clear()
        self._rotation_before_edit.clear()
        rotation_changes = [
            (uid, prev.get(uid, 0.0), rot) for uid, rot in dirty.items()
        ]
        self.rotations_flushed.emit(rotation_changes)

    def _flush_rotation_group(self) -> None:
        pos_dirty = dict(self._dirty_positions)
        ann_dirty = dict(self._dirty_ann_positions)
        pos_prev = dict(self._position_before_edit)
        rot_dirty = dict(self._dirty_rotations)
        rot_prev = dict(self._rotation_before_edit)
        self._dirty_positions.clear()
        self._dirty_ann_positions.clear()
        self._position_before_edit.clear()
        self._dirty_rotations.clear()
        self._rotation_before_edit.clear()
        takeoff_changes = [
            (uid, pos_prev.get(uid, []), pos) for uid, pos in pos_dirty.items()
        ]
        ann_changes = [
            (
                self._ann_db_uid_map.get(uid, uid),
                ann_type,
                pos_prev.get(uid, []),
                new_pos,
            )
            for uid, (ann_type, new_pos) in ann_dirty.items()
        ]
        rotation_changes = [
            (uid, rot_prev.get(uid, 0.0), rot) for uid, rot in rot_dirty.items()
        ]
        self.group_rotation_flushed.emit(takeoff_changes, ann_changes, rotation_changes)

    def _set_page_overlay_items_visible(self, visible: bool) -> None:
        for item in self._takeoff_items:
            item.setVisible(visible)
        for item, _ in self._hotlink_items:
            item.setVisible(visible)
        for item in self._selection_items:
            item.setVisible(visible)

    def load_page(
        self,
        page: Page,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        bid_ref: Optional[BidRef] = None,
        annotations: Optional[List[BidAnnotation]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> bool:
        return self._load_page_impl(
            page,
            takeoffs,
            conditions,
            color_map,
            bid_ref,
            annotations,
            page_area_selections,
        )

    def _load_page_impl(
        self,
        page: Page,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        bid_ref: Optional[BidRef] = None,
        annotations: Optional[List[BidAnnotation]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> bool:
        resolved_bid_ref = bid_ref
        next_render_identity = self._build_render_identity(page, resolved_bid_ref)
        strategy = self._load_coordinator.determine_load_strategy(page)
        project_changed = resolved_bid_ref != self._current_bid_ref
        if strategy.load_composite:
            expected_visual_kind = "composite"
        elif strategy.load_main:
            expected_visual_kind = "page"
        elif strategy.load_overlay:
            expected_visual_kind = "overlay"
        else:
            expected_visual_kind = None
        has_loaded_visual_layer = (
            not strategy.needs_async_loading
            or self._loaded_visual_kind == expected_visual_kind
        )
        same_page_refresh = (
            not project_changed
            and self._current_page is not None
            and self._current_render_identity == next_render_identity
            and has_loaded_visual_layer
        )
        self._begin_load_cycle(
            page,
            preserve_current_view=same_page_refresh and self._load_view_applied,
        )
        if same_page_refresh:
            self._refresh_overlays(
                page,
                takeoffs,
                conditions,
                color_map,
                annotations,
                page_area_selections,
                resolved_bid_ref,
            )
            self._mark_load_geometry_ready()
            return True
        self._cancel_pending_renders()
        saved_selection = set() if project_changed else set(self._selected_uids)
        page_changed = (
            self._current_page is not None and self._current_page.uid != page.uid
        )
        if project_changed or page_changed:
            self._clear_backout_state()
        saved_cursor = self._persistent_cursor_mode
        preserve_place = not project_changed and self._place_session_uid is not None
        active_load_token = self._current_load_token
        self.clear(preserve_place_session=preserve_place)
        self._current_load_token = active_load_token
        self._current_bid_ref = resolved_bid_ref
        self.resetTransform()
        self._scene.setSceneRect(QtCore.QRectF())
        if not preserve_place and saved_cursor != "place":
            self._apply_cursor_mode(saved_cursor)
            self.cursor_mode_change_requested.emit(saved_cursor)
        self._current_takeoffs = {t.uid: t for t in takeoffs}
        self._invalidate_snap_index()
        self._current_conditions = conditions
        self._cancel_backout_if_invalid()
        self._current_color_map = color_map
        self._current_page = page
        self._current_bid_page_uid = page.uid
        self._current_render_identity = next_render_identity
        self._advance_render_generation()
        self._current_rotation = page.rotation
        self._current_flip_x = page.flip_x
        self._current_flip_y = page.flip_y
        has_image_file = bool(page.has_image and page.image_path)
        is_pdf_image = has_image_file and page.image_path.lower().endswith(".pdf")
        self._scene_scale = strategy.view_scale
        rotation = page.rotation
        self._can_zoom_rerender = (
            is_pdf_image
            and (strategy.load_main or strategy.load_composite)
            and page.layer_visible
        )
        self._is_composite_mode = strategy.load_composite
        pdf_width_pts = strategy.pdf_width_pts
        pdf_height_pts = strategy.pdf_height_pts
        self._pdf_width_pts = pdf_width_pts
        self._pdf_height_pts = pdf_height_pts
        if strategy.show_canvas:
            self._white_canvas_item = self._scene_builder.create_white_canvas(
                self._scene,
                strategy.placeholder_width,
                strategy.placeholder_height,
                color=self._page_canvas_color(),
            )
        page_info = self._scene_builder.build_page_info(
            page,
            pdf_width_pts,
            pdf_height_pts,
            strategy.view_scale,
            rotation,
        )
        self._takeoff_items, self._uid_to_items = (
            self._scene_builder.add_takeoff_overlays(
                self._scene,
                takeoffs,
                conditions,
                color_map,
                page_info,
                page_area_selections,
            )
        )
        if annotations:
            annotation_dict, db_uid_map = _build_annotation_dict(
                annotations,
                takeoff_uids=set(self._current_takeoffs.keys()),
            )
            annotation_items, hotlinks, ann_uid_to_items = (
                self._scene_builder.add_annotation_overlays(
                    self._scene,
                    list(annotation_dict.items()),
                    page_info,
                    self._current_bid_page_uid,
                )
            )
            self._takeoff_items.extend(annotation_items)
            self._hotlink_items.extend(hotlinks)
            self._uid_to_items.update(ann_uid_to_items)
            self._current_annotations = annotation_dict
            self._ann_db_uid_map = db_uid_map
        else:
            self._current_annotations = {}
            self._ann_db_uid_map = {}
        self._apply_page_transform_to_items()
        if self._defer_page_visual_reveal:
            self._set_page_overlay_items_visible(False)
        self._update_scene_rect()
        if strategy.needs_async_loading and strategy.show_canvas:
            self._apply_loading_view_contract()
        self._selected_uids = saved_selection & (
            self._current_takeoffs.keys() | self._current_annotations.keys()
        )
        if self._selected_uids or saved_selection:
            self.update_selection_visuals()
        if strategy.needs_async_loading:
            self._pending_page_data = self._load_coordinator.create_pending_page_data(
                page,
                strategy,
                pdf_width_pts,
                pdf_height_pts,
            )
            self._pending_page_data["bid_ref"] = resolved_bid_ref
            self._pending_page_data["load_token"] = self._current_load_token
            self._pending_page_data["render_identity"] = dict(next_render_identity)
            if strategy.load_composite or strategy.load_main:
                if strategy.load_composite:
                    base_raster_scale = strategy.main_scale
                else:
                    base_raster_scale = self._target_base_raster_scale(
                        strategy.main_scale
                    )
                self._pending_page_data["render_scale"] = base_raster_scale
                self._pending_page_data["base_raster_scale"] = base_raster_scale
                if strategy.load_composite:
                    self.load_composite_async(
                        page,
                        resolved_bid_ref,
                        base_raster_scale,
                        rotation,
                    )
                else:
                    self.load_page_async(
                        page.image_path,
                        page.page_index,
                        base_raster_scale,
                        rotation,
                        page.invert,
                        page.bitonal,
                    )
            elif strategy.load_overlay:
                self.load_overlay_async(
                    page,
                    resolved_bid_ref,
                    strategy.view_scale,
                    page.image_show_mode,
                    rotation,
                )
        else:
            self._loaded_visual_kind = expected_visual_kind
            self._mark_load_geometry_ready()
        return True

    def _refresh_overlays(
        self,
        page: Page,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        annotations: Optional[List[BidAnnotation]],
        page_area_selections: Optional[Dict[str, Optional[str]]],
        bid_ref: Optional[BidRef],
    ) -> None:
        self._refresh_overlays_impl(
            page,
            takeoffs,
            conditions,
            color_map,
            annotations,
            page_area_selections,
            bid_ref,
        )

    def _refresh_overlays_impl(
        self,
        page: Page,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        annotations: Optional[List[BidAnnotation]],
        page_area_selections: Optional[Dict[str, Optional[str]]],
        bid_ref: Optional[BidRef],
    ) -> None:
        self._flush_dirty_positions()
        saved_text_annotation_uid = self._selected_text_annotation_uid
        saved_condition_label_target = self._selected_condition_text_label_target()
        self._clear_text_selection()
        self.clear_selection_items()
        saved_selection = set(self._selected_uids)
        self._selected_uids.clear()
        self._drag_takeoff_uid = None
        self._drag_handle_index = -2
        self._drag_orig_position = []
        self._drag_item_orig_positions = {}
        self._drag_item_orig_paths = {}
        self._drag_uid_orig_items = {}
        self._drag_multi_orig_positions = {}
        self._drag_last_valid_new_pos = []
        self._remove_rotate_handle()
        self._rotation_drag_uid = None
        self._rotation_drag_active = False
        items_to_remove: set = set()
        for item in self._takeoff_items:
            items_to_remove.add(item)
        for item, _ in self._hotlink_items:
            items_to_remove.add(item)
        for item in items_to_remove:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._takeoff_items.clear()
        self._hotlink_items.clear()
        self._uid_to_items = {}
        self._current_page = page
        self._current_bid_page_uid = page.uid if page else None
        self._current_bid_ref = bid_ref
        self._current_render_identity = self._build_render_identity(page, bid_ref)
        self._current_takeoffs = {t.uid: t for t in takeoffs}
        self._invalidate_snap_index()
        self._current_conditions = conditions
        self._cancel_backout_if_invalid()
        self._current_color_map = color_map
        rotation = page.rotation
        page_info = self._scene_builder.build_page_info(
            page,
            self._pdf_width_pts,
            self._pdf_height_pts,
            self._scene_scale,
            rotation,
        )
        self._takeoff_items, self._uid_to_items = (
            self._scene_builder.add_takeoff_overlays(
                self._scene,
                takeoffs,
                conditions,
                color_map,
                page_info,
                page_area_selections,
            )
        )
        if annotations:
            annotation_dict, db_uid_map = _build_annotation_dict(
                annotations, takeoff_uids=set(self._current_takeoffs.keys())
            )
            annotation_items, hotlinks, ann_uid_to_items = (
                self._scene_builder.add_annotation_overlays(
                    self._scene,
                    list(annotation_dict.items()),
                    page_info,
                    self._current_bid_page_uid,
                )
            )
            self._takeoff_items.extend(annotation_items)
            self._hotlink_items.extend(hotlinks)
            self._uid_to_items.update(ann_uid_to_items)
            self._current_annotations = annotation_dict
            self._ann_db_uid_map = db_uid_map
        else:
            self._current_annotations = {}
            self._ann_db_uid_map = {}
        self._apply_page_transform_to_items()
        if self._defer_page_visual_reveal:
            self._set_page_overlay_items_visible(False)
        self._selected_uids = saved_selection & (
            self._current_takeoffs.keys() | self._current_annotations.keys()
        )
        if self._selected_uids or saved_selection:
            self.update_selection_visuals()
        self._restore_selected_text_annotation_toolbar(saved_text_annotation_uid)
        self._restore_selected_condition_text_label_toolbar(
            saved_condition_label_target
        )
        if self._cursor_mode == "rotate":
            if not (
                self._selected_uids and self._create_rotate_handle(self._selected_uids)
            ):
                self._apply_cursor_mode("select")
                self.cursor_mode_change_requested.emit("select")
        elif self._cursor_mode == "slope_rotate":
            if not self._create_slope_rotate_handle():
                self._apply_cursor_mode("select")
                self.cursor_mode_change_requested.emit("select")
        self._update_cursor()

    def refresh_current_page_overlays(
        self,
        page: Page,
        takeoffs: List[Takeoff],
        conditions: Dict[str, Condition],
        color_map: Dict[str, str],
        bid_ref: Optional[BidRef] = None,
        annotations: Optional[List[BidAnnotation]] = None,
        page_area_selections: Optional[Dict[str, Optional[str]]] = None,
    ) -> bool:
        if self._current_bid_page_uid != page.uid:
            return False
        next_render_identity = self._build_render_identity(page, bid_ref)
        if self._current_render_identity != next_render_identity:
            return False
        self._refresh_overlays(
            page,
            takeoffs,
            conditions,
            color_map,
            annotations,
            page_area_selections,
            bid_ref,
        )
        self._update_scene_rect()
        self.viewport().update()
        return True

    def clear(self, preserve_place_session: bool = False):
        self.finish_intelligent_paste_placement()
        if self._place_session_uid is not None and not preserve_place_session:
            self._exit_place_mode()
        elif preserve_place_session and self._place_session_uid is not None:
            self.clear_place_preview()
            self._reset_place_session_state()
        if not preserve_place_session:
            self._clear_backout_state()
        self._flush_dirty_rotations()
        self._flush_dirty_positions()
        self._cancel_tile_requests()
        if self._background_item is not None:
            self._background_item.clear_image()
        for item in self._tile_items.values():
            item.clear_image()
        for item in self._overlay_items:
            item.setPixmap(QPixmap())
        self._tile_items.clear()
        self._tile_scale = 0.0
        self._cancel_optional_base_correction()
        self._base_raster_scale = 0.0
        self._selection_items.clear()
        self._handle_infos.clear()
        self._selected_uids.clear()
        self._clear_text_selection()
        self._takeoff_items.clear()
        self._hotlink_items.clear()
        self._uid_to_items = {}
        self._scene.clear()
        self._current_takeoffs = {}
        self._invalidate_snap_index()
        self._current_conditions = {}
        self._current_color_map = {}
        self._current_annotations = {}
        self._ann_db_uid_map = {}
        self.takeoff_selection_changed.emit([])
        self._select_band_origin = None
        self._select_band_active = False
        self._select_band_dragged = False
        self._press_changed_selection = False
        self._zoom_press_ctrl = False
        self._rubber_band_origin = None
        self._drag_takeoff_uid = None
        self._drag_handle_index = -2
        self._drag_orig_position = []
        self._drag_handle_corner_count = 0
        self._drag_item_orig_positions = {}
        self._drag_item_orig_paths = {}
        self._drag_uid_orig_items = {}
        self._drag_multi_orig_positions = {}
        self._drag_last_valid_new_pos = []
        self._rotate_handle_item = None
        self._rotate_line_item = None
        self._rotate_line_outline_item = None
        self._rotate_handle_uid = None
        self._rotate_center_scene = QtCore.QPointF()
        self._rotate_handle_radius = 0.0
        self._rotation_drag_uid = None
        self._rotation_drag_active = False
        self._rotation_drag_last_angle = 0.0
        self._rotation_drag_accumulated_deg = 0.0
        self._rotation_drag_snapped_deg = 0.0
        self._rotation_drag_preview_items = []
        self._rotation_drag_handle_origins = []
        self._rotation_drag_orig_positions = {}
        self._rotation_drag_orig_rotations = {}
        self._rotate_ost_center = (0.0, 0.0)
        self._dirty_rotations.clear()
        self._rotation_before_edit.clear()
        if not preserve_place_session:
            self._apply_cursor_mode("select")
            self.cursor_mode_change_requested.emit("select")
        if self._paste_backout_active:
            self._paste_backout_active = False
            self._paste_backout_sources = []
            self._paste_backout_source_bid_uid = None
            self._paste_backout_group_centroid = (0.0, 0.0)
            self.clear_paste_backout_preview()
        self._current_page = None
        self._current_bid_ref = None
        self._current_bid_page_uid = None
        self._current_render_identity = None
        self._current_load_token = ""
        self._advance_render_generation()
        self._current_rotation = 0
        self._current_flip_x = False
        self._current_flip_y = False
        self._background_item = None
        self._overlay_items = []
        self._white_canvas_item = None
        self._can_zoom_rerender = False
        self._is_composite_mode = False
        self._loaded_visual_kind = None
        self._pdf_width_pts = 0.0
        self._pdf_height_pts = 0.0
        self._load_geometry_ready = False
        self._load_view_applied = False
        self._load_waiting_for_visibility = False
        self._load_geometry_notified = False
        self._saved_scroll_state = None
        self._pending_page_data = None
        self._deferred_page_visual_result = None

    def set_cursor_mode(self, mode: str) -> None:
        if mode != "select":
            self.finish_intelligent_paste_placement()
        if mode == "place":
            if not self.enter_place_mode():
                return
        else:
            self._exit_place_mode()
            self._clear_backout_state()
        self._apply_cursor_mode(mode)

    def update_color_map(self, color_map: Dict[str, str]) -> None:
        self._current_color_map = color_map

    def activate_place_for_condition(
        self, condition_uid: str, all_condition_uids: list = None
    ) -> bool:
        self.finish_intelligent_paste_placement()
        if not PlacementModeMixin.enter_place_mode_for_condition(self, condition_uid):
            return False
        self._place_all_condition_uids = self._filter_place_conditions(
            condition_uid, all_condition_uids or []
        )
        self._apply_cursor_mode("place")
        self.cursor_mode_change_requested.emit("place")
        return True

    def _filter_place_conditions(self, active_uid: str, uids: list) -> list:
        if len(uids) <= 1:
            return []
        active = self._current_conditions.get(active_uid)
        if not active:
            return []
        same_type = [
            uid
            for uid in uids
            if uid != active_uid
            and uid in self._current_conditions
            and self._current_conditions[uid].layer_visible
            and self._current_conditions[uid].condition_type == active.condition_type
        ]
        return same_type

    def enter_backout_mode(self, parent_uid: str) -> bool:
        parent_uid = self._valid_backout_parent_uid(parent_uid)
        if not parent_uid:
            self._clear_backout_state()
            return False
        self._set_backout_state(
            parent_uid, self._current_takeoffs[parent_uid].condition_uid
        )
        return True

    def is_inside_parent(self, ost_x: float, ost_y: float) -> bool:
        if not self._backout_parent_uid:
            return False
        parent = self._current_takeoffs.get(self._backout_parent_uid)
        if not parent or not parent.position:
            return False
        cs = self._scene_builder.get_coordinate_system()
        parent_pos = cs.parse_position(parent.position)
        if not parent_pos or len(parent_pos) < 6:
            return False
        parent_tx = cs.transform_vertices_to_2d(parent_pos)
        parent_path = QPainterPath()
        parent_path.moveTo(parent_tx[0], parent_tx[1])
        for i in range(2, len(parent_tx) - 1, 2):
            parent_path.lineTo(parent_tx[i], parent_tx[i + 1])
        parent_path.closeSubpath()
        pt_tx = cs.transform_vertices_to_2d([ost_x, ost_y])
        return parent_path.contains(QtCore.QPointF(pt_tx[0], pt_tx[1]))

    def cancel_place_mode(self) -> None:
        self._exit_place_mode()
        self._clear_backout_state()
        self.cursor_mode_change_requested.emit("select")

    def cancel_backout_mode(self) -> None:
        self._clear_backout_state()

    def begin_paste_backout(
        self,
        takeoffs: list,
        extras_by_uid: Dict[str, Dict],
        source_bid_uid: Optional[str],
    ) -> bool:
        self.finish_intelligent_paste_placement()
        valid_takeoffs = [
            t for t in takeoffs if t and t.position and len(t.position) >= 6
        ]
        if not valid_takeoffs:
            return False
        has_host = any(
            not t.is_hole
            and self._current_conditions.get(t.condition_uid) is not None
            and self._current_conditions[t.condition_uid].is_area
            for t in self._current_takeoffs.values()
        )
        if not has_host:
            return False
        sources: List[Dict] = []
        all_vertex_xs: List[float] = []
        all_vertex_ys: List[float] = []
        for t in valid_takeoffs:
            pos = list(t.position)
            n = len(pos) // 2
            for i in range(n):
                all_vertex_xs.append(pos[i * 2])
                all_vertex_ys.append(pos[i * 2 + 1])
            sources.append(
                {
                    "condition_uid": t.condition_uid,
                    "position": pos,
                    "rotation": t.rotation,
                    "is_negative": t.is_negative,
                    "extras": dict(extras_by_uid.get(t.uid, {})),
                }
            )
        group_cx = sum(all_vertex_xs) / len(all_vertex_xs)
        group_cy = sum(all_vertex_ys) / len(all_vertex_ys)
        self._paste_backout_active = True
        self._paste_backout_sources = sources
        self._paste_backout_source_bid_uid = source_bid_uid
        self._paste_backout_group_centroid = (group_cx, group_cy)
        self._apply_cursor_mode("paste_backout")
        self.cursor_mode_change_requested.emit("paste_backout")
        if self._last_mouse_vp_pos is not None:
            self.update_paste_backout_preview(self.mapToScene(self._last_mouse_vp_pos))
        return True

    def cancel_paste_backout(self) -> None:
        if not self._paste_backout_active:
            return
        self._paste_backout_active = False
        self._paste_backout_sources = []
        self._paste_backout_source_bid_uid = None
        self._paste_backout_group_centroid = (0.0, 0.0)
        self.clear_paste_backout_preview()
        self._apply_cursor_mode("select")
        self.cursor_mode_change_requested.emit("select")

    def _set_backout_state(self, parent_uid: str, condition_uid: str) -> None:
        changed = (
            not self._backout_mode_active
            or self._backout_parent_uid != parent_uid
            or self._backout_active_uid != condition_uid
        )
        self._backout_mode_active = True
        self._backout_parent_uid = parent_uid
        self._backout_active_uid = condition_uid
        self._backout_last_valid_ost = None
        if changed:
            self.backout_mode_changed.emit(True)

    def _clear_backout_state(self) -> None:
        was_backout = self._backout_mode_active or bool(
            self._backout_parent_uid or self._backout_active_uid
        )
        self._backout_mode_active = False
        self._backout_parent_uid = None
        self._backout_active_uid = None
        self._backout_last_valid_ost = None
        if was_backout:
            self.backout_mode_changed.emit(False)

    def _apply_cursor_mode(self, mode: str) -> None:
        self._cursor_mode = mode
        self._persistent_cursor_mode = mode
        if mode != "zoom" and not self._right_pan_active:
            self._pre_zoom_persistent_mode = None
        self._update_cursor()

    def _set_palette_background(self):
        set_palette_background(self, lambda c: self.setBackgroundBrush(QBrush(c)))

    def cleanup(self):
        self._zoom_debouncer.cancel()
        self._finish_active_inline_text_edit(commit=True)
        self._cancel_pending_renders()
        self._rendering_service.shutdown()
        self.clear()
        self._scene.focusItemChanged.disconnect(self._on_scene_focus_item_changed)
        self._condition_text_toolbar.deleteLater()
        self._condition_text_toolbar = None
        self._selected_text_item = None
        self._selected_text_annotation_uid = None
        self._selected_text_model_font_size = None
        self._selected_text_annotation_font_scale = 1.0
        self._editing_text_annotation_uid = None
        self._editing_named_view_uid = None
        self._editing_named_view_item = None
        self._clear_inline_text_document()
        self._editing_text_original = ""
        self._text_annotation_inline_edit_allowed_fn = None
        self._rendering_service = None
        self._load_coordinator = None
        self._color_service = None
        self._scene_builder = None
        self._pending_page_data = None
