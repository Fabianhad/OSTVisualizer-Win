import math
import uuid
from typing import Dict, List, Optional, Set, Tuple
from PySide6 import QtCore, QtSvg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QRubberBand,
)
from ....application.dtos.hotlink_dto import HotlinkDto
from ....application.interfaces.i_color_service import IColorService
from ....application.interfaces.i_linear_geometry import ILinearGeometry
from ....application.interfaces.i_page_load_strategy_service import (
    IPageLoadStrategyService,
)
from ....application.interfaces.i_page_rendering_service import IPageRenderingService
from ....domain.entities.annotation import BidAnnotation
from ....domain.entities.condition import Condition
from ....domain.entities.identity_refs import BidRef
from ....domain.entities.page import Page
from ....domain.entities.takeoff import Takeoff
from ...configurators.window_configurator import resource_path
from ...interfaces.i_annotation_item_renderer import IAnnotationItemRenderer
from ...interfaces.i_takeoff_renderer import ITakeoffRenderer
from ...scene.scene_builder import SceneBuilder
from ...utils.theme import set_palette_background
from ...utils.themed_icon import current_text_hex, recolor_svg
from ...utils.zoom_debouncer import ZoomDebouncer
from ...visualization.utils.image_effects import page_effect_paper_color
from ..viewer_cursors import OUTLINE_OFFSETS, recolor_pixmap
from .components.drag_handler import DragHandlerMixin
from .components.geometry_utils import HandleInfo, polygon_centroid
from .components.graphics_items import ImageBackgroundItem, TileGraphicsItem, TileKey
from .components.input_handler import InputHandlerMixin
from .components.page_loader import PageLoaderMixin
from .components.placement_mode import PlacementModeMixin
from .components.selection_manager import SelectionManagerMixin
from .components.zoom_handler import ZoomHandlerMixin


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
    set_negative_requested = Signal(list, bool)
    set_curved_requested = Signal(list, bool)
    overlay_display_mode_requested = Signal(int)
    positions_flushed = Signal(list, list)
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
        self._drag_multi_orig_positions: Dict[str, List[float]] = {}
        self._drag_last_valid_new_pos: List[float] = []
        self._last_mouse_vp_pos: Optional[QtCore.QPoint] = None
        self._place_session_uid: Optional[str] = None
        self._place_all_condition_uids: List[str] = []
        self._place_points: List[Tuple[float, float]] = []
        self._place_preview_items: List[QGraphicsItem] = []
        self._snap_index = None
        self._snap_index_dirty: bool = True
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
        self._load_initial_view_mode = "restore" if page.zoom_fac > 0 else "fit"
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
        return self._cursor_mode == "rotate" or self._rotation_drag_active

    @property
    def is_view_state_stable(self) -> bool:
        return self._load_view_applied and self._scene.sceneRect().isValid()

    @property
    def place_condition_uid(self) -> Optional[str]:
        return self._place_session_uid

    @property
    def backout_parent_uid(self) -> Optional[str]:
        return self._backout_parent_uid

    @property
    def backout_mode_active(self) -> bool:
        return self._backout_mode_active

    @property
    def snap_increments(self) -> float:
        return self._snap_increments

    def get_takeoff(self, uid: str):
        return self._current_takeoffs.get(uid)

    def get_condition(self, condition_uid: str):
        return self._current_conditions.get(condition_uid)

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

    def _create_rotate_handle(self, uids=None) -> bool:
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
        handle_x = center_scene.x()
        handle_y = center_scene.y() - radius
        svg_path = resource_path(
            "resources",
            "icons",
            "replay_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg",
        )
        hex_color = current_text_hex()
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
        text_color = self.palette().color(QPalette.ColorRole.WindowText)
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
        if project_changed:
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
        if (
            self._backout_parent_uid
            and self._backout_parent_uid not in self._current_takeoffs
        ):
            self._backout_parent_uid = None
            self._backout_active_uid = None
        self._current_conditions = conditions
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
        if self._selected_uids:
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
        self.clear_selection_items()
        saved_selection = set(self._selected_uids)
        self._selected_uids.clear()
        self._drag_takeoff_uid = None
        self._drag_handle_index = -2
        self._drag_orig_position = []
        self._drag_item_orig_positions = {}
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
        if self._selected_uids:
            self.update_selection_visuals()
        if self._cursor_mode == "rotate":
            if self._selected_uids and self._create_rotate_handle(self._selected_uids):
                pass
            else:
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
        if self._place_session_uid is not None and not preserve_place_session:
            self._exit_place_mode()
        elif preserve_place_session and self._place_session_uid is not None:
            self.clear_place_preview()
            self._reset_place_session_state()
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
        if mode == "place":
            if not self.enter_place_mode():
                return
        else:
            self._exit_place_mode()
        self._apply_cursor_mode(mode)

    def update_color_map(self, color_map: Dict[str, str]) -> None:
        self._current_color_map = color_map

    def activate_place_for_condition(
        self, condition_uid: str, all_condition_uids: list = None
    ) -> bool:
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
        takeoff = self._current_takeoffs.get(parent_uid)
        if not takeoff:
            return False
        condition = self._current_conditions.get(takeoff.condition_uid)
        if not condition or not condition.is_area:
            return False
        self._backout_parent_uid = parent_uid
        self._backout_active_uid = takeoff.condition_uid
        self._backout_mode_active = True
        self.backout_mode_changed.emit(True)
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

    def _clear_backout_state(self) -> None:
        was_backout = self._backout_mode_active
        self._backout_mode_active = False
        self._backout_parent_uid = None
        self._backout_active_uid = None
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
        self._cancel_pending_renders()
        self._rendering_service.shutdown()
        self.clear()
        self._rendering_service = None
        self._load_coordinator = None
        self._color_service = None
        self._scene_builder = None
        self._pending_page_data = None
