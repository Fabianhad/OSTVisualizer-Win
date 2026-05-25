import math
from typing import List, Optional
from PySide6 import QtCore
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainterPath, QTransform, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsPathItem, QMenu, QRubberBand
from ....config import RIGHT_CLICK_CONTEXT_MENU_MAX_MS
from ....managers.context_menu_manager import ContextMenuManager
from ....utils.overlay_context_menu import resolve_overlay_menu_action
from ....utils.view_context_menu import (
    SelectedTakeoffContextState,
    add_common_context_submenus,
    add_context_clipboard_actions,
    add_context_command,
    add_context_page_actions,
    add_reassign_condition_submenu,
    build_selected_takeoff_context_state,
)
from .geometry_utils import (
    mirror_points_around,
    polygon_centroid,
    rotate_points_around,
    rotate_position_coords,
)


def _ink_strip_prefix(pos: List[float]) -> List[float]:
    start = 1 if len(pos) % 2 == 1 else 0
    return list(pos[start:])


def _ink_add_prefix(
    coords: List[float], orig_pos: List[float], snapped_deg: float = 0.0
) -> List[float]:
    delta_rad = math.radians(snapped_deg)
    has_prefix = len(orig_pos) % 2 == 1
    if has_prefix:
        return [orig_pos[0] + delta_rad] + coords
    return [delta_rad] + coords


def _update_ann_trailing_rotation(pos: List[float], snapped_deg: float) -> None:
    delta_rad = math.radians(snapped_deg)
    if len(pos) % 2 == 1:
        pos[-1] = pos[-1] + delta_rad
    else:
        pos.append(delta_rad)


def _rotate_annotation(
    ann, orig_pos: List[float], snapped_deg: float, cx: float, cy: float
) -> List[float]:
    if (ann.is_text or ann.annotation_type == "callout") and len(orig_pos) >= 4:
        new_pos = list(orig_pos)
        new_pos[0], new_pos[1] = rotate_points_around(
            orig_pos[:2], snapped_deg, cx, cy
        )[:2]
        delta_rad = math.radians(snapped_deg)
        existing_rot = orig_pos[4] if len(orig_pos) >= 5 else 0.0
        new_pos[4:5] = [existing_rot + delta_rad]
        return new_pos
    if ann.is_ink:
        coords = _ink_strip_prefix(orig_pos)
        rotated = rotate_points_around(coords, snapped_deg, cx, cy)
        return _ink_add_prefix(rotated, orig_pos, snapped_deg)
    new_pos = rotate_points_around(orig_pos, snapped_deg, cx, cy)
    if ann.annotation_type not in ("cloud", "polygon", "hotlink"):
        _update_ann_trailing_rotation(new_pos, snapped_deg)
    return new_pos


class InputHandlerMixin:
    _advanced_mouse_controls_enabled: bool = True
    _intelligent_paste_active: bool = False
    _use_full_window_crosshairs: bool = False
    _pdf_text_drag_anchor: Optional[tuple] = None

    def _request_crosshair_repaint(self) -> None:
        if not self._use_full_window_crosshairs:
            return
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def _advanced_mouse_controls_active(self) -> bool:
        return self._advanced_mouse_controls_enabled

    def apply_intelligent_paste_axis_snap(
        self, ost_dx: float, ost_dy: float
    ) -> tuple[float, float]:
        return ost_dx, ost_dy

    def begin_intelligent_paste_drag_if_pending(self, _drag_positions) -> bool:
        return False

    def finish_intelligent_paste_placement(self) -> None:
        pass

    def _on_selection_changed(self) -> None:
        pass

    def _roping_item_selection_mode(self):
        if self._roping_selection_method == "inclusive":
            return Qt.ItemSelectionMode.ContainsItemShape
        return Qt.ItemSelectionMode.IntersectsItemShape

    def _restore_drag_preview_positions(self) -> None:
        if (
            not self._drag_item_orig_positions
            and not self._drag_item_orig_paths
            and not self._drag_uid_orig_items
        ):
            return
        uids = set()
        if self._drag_takeoff_uid:
            uids.add(self._drag_takeoff_uid)
        uids.update(self._drag_multi_orig_positions.keys())
        for uid in uids:
            original_items = self._drag_uid_orig_items.get(uid)
            if original_items is not None:
                original_item_ids = {id(item) for item in original_items}
                for item in list(self._uid_to_items.get(uid, [])):
                    if id(item) not in original_item_ids:
                        if item.scene() is self._scene:
                            self._scene.removeItem(item)
                        if item in self._takeoff_items:
                            self._takeoff_items.remove(item)
                self._uid_to_items[uid] = list(original_items)
                for item in original_items:
                    if item.scene() is not self._scene:
                        self._scene.addItem(item)
                    if item not in self._takeoff_items:
                        self._takeoff_items.append(item)
            for item in self._uid_to_items.get(uid, []):
                orig = self._drag_item_orig_positions.get(id(item))
                if orig is not None:
                    item.setPos(orig)
                orig_path = self._drag_item_orig_paths.get(id(item))
                if orig_path is not None and isinstance(item, QGraphicsPathItem):
                    item.setPath(orig_path)
        for item in self._selection_items:
            orig = self._drag_item_orig_positions.get(id(item))
            if orig is not None:
                item.setPos(orig)

    def _clear_drag_tracking(self, restore_preview: bool = False) -> None:
        if restore_preview:
            self._restore_drag_preview_positions()
        self._drag_takeoff_uid = None
        self._drag_handle_index = -2
        self._drag_orig_position = []
        self._drag_handle_corner_count = 0
        self._drag_item_orig_positions = {}
        self._drag_item_orig_paths = {}
        self._drag_uid_orig_items = {}
        self._drag_multi_orig_positions = {}
        self._drag_last_valid_new_pos = []

    def _has_active_drag_interaction(self) -> bool:
        return (
            self._select_band_origin is not None
            or self._select_band_active
            or self._select_band_dragged
            or self._zoom_press_ctrl
            or self._drag_handle_index >= -1
            or self._drag_takeoff_uid is not None
            or bool(self._drag_multi_orig_positions)
        )

    def _cancel_active_drag_interaction(self, restore_preview: bool = True) -> bool:
        if not self._has_active_drag_interaction():
            return False
        if self._rubber_band is not None:
            self._rubber_band.hide()
        self._rubber_band_origin = None
        self._select_band_origin = None
        self._select_band_active = False
        self._select_band_dragged = False
        self._zoom_press_ctrl = False
        self._clear_drag_tracking(restore_preview=restore_preview)
        return True

    def _clear_stale_drag_tracking_if_mouse_released(self, event: QMouseEvent) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            return
        self._cancel_active_drag_interaction(restore_preview=True)

    def _apply_wheel_zoom(self, event: QWheelEvent, delta_y: float) -> None:
        factor = self.ZOOM_FACTOR if delta_y > 0 else 1.0 / self.ZOOM_FACTOR
        cursor_vp = event.position().toPoint()
        scene_before = self.mapToScene(cursor_vp)
        self._apply_zoom(factor)
        new_vp = self.mapFromScene(scene_before)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + new_vp.x() - cursor_vp.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + new_vp.y() - cursor_vp.y()
        )

    def wheelEvent(self, event: QWheelEvent):
        advanced_mouse_controls = self._advanced_mouse_controls_active()
        mods = event.modifiers()
        pixel_delta = event.pixelDelta()
        if not pixel_delta.isNull():
            delta_y = pixel_delta.y()
        else:
            delta_y = event.angleDelta().y() / 120.0 * 80
        if self._cursor_mode == "zoom":
            if not (mods & Qt.KeyboardModifier.ControlModifier):
                self._apply_wheel_zoom(event, delta_y)
            self._sync_rubber_band_to_viewport()
            event.accept()
            return
        if advanced_mouse_controls and mods & Qt.KeyboardModifier.ControlModifier:
            self._apply_wheel_zoom(event, delta_y)
        elif advanced_mouse_controls and mods & Qt.KeyboardModifier.ShiftModifier:
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta_y)
            )
        else:
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta_y)
            )
        self._sync_rubber_band_to_viewport()
        event.accept()

    def _sync_rubber_band_to_viewport(self) -> None:
        if self._last_mouse_vp_pos is None:
            return
        if (
            self._select_band_active
            and self._rubber_band
            and self._select_band_origin is not None
        ):
            vp_origin = self.mapFromScene(self._select_band_origin)
            self._rubber_band.setGeometry(
                QRect(vp_origin, self._last_mouse_vp_pos).normalized()
            )
        elif self._rubber_band_origin is not None and self._rubber_band is not None:
            vp_origin = self.mapFromScene(self._rubber_band_origin)
            self._rubber_band.setGeometry(
                QRect(vp_origin, self._last_mouse_vp_pos).normalized()
            )
        else:
            self._update_cursor()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self._cursor_mode == "place":
            event.accept()
            return
        vp_pos = event.position().toPoint()
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._cursor_mode != "zoom"
            and self._selection_enabled
        ):
            scene_pos = self.mapToScene(vp_pos)
            named_view_label = self._named_view_label_at(vp_pos)
            if named_view_label is not None:
                named_view_uid = named_view_label.data(0)
                if named_view_uid is not None:
                    self._flush_dirty_positions()
                    self._selected_uids = {str(named_view_uid)}
                    self._on_selection_changed()
                    self.update_selection_visuals()
                    self._begin_named_view_rename(str(named_view_uid))
                    event.accept()
                    return
            text_uid = self.find_text_annotation_at(scene_pos)
            if text_uid:
                self._flush_dirty_positions()
                self._selected_uids = {text_uid}
                self._on_selection_changed()
                self.update_selection_visuals()
                self._select_text_annotation_label(text_uid)
                self._begin_text_annotation_edit(text_uid)
                event.accept()
                return
        self.mousePressEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        advanced_mouse_controls = self._advanced_mouse_controls_active()
        vp_pos = event.position().toPoint()
        self._last_mouse_vp_pos = vp_pos
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.is_text_annotation_inline_edit_active()
        ):
            scene_pos = self.mapToScene(vp_pos)
            if self._active_inline_text_editor_contains_scene_point(scene_pos):
                super().mousePressEvent(event)
                return
            self._finish_active_inline_text_edit(commit=True)
        if event.button() == Qt.MouseButton.LeftButton and self._cursor_mode != "place":
            text_label = self._condition_text_label_at(vp_pos)
            if text_label is not None:
                self._clear_pdf_text_selection()
                self._select_condition_text_label(text_label)
                event.accept()
                return
            self._clear_text_selection()
            text_uid = (
                self.find_text_annotation_at(self.mapToScene(vp_pos))
                if self._selection_enabled
                else None
            )
            if text_uid is not None:
                self._clear_pdf_text_selection()
                self._select_text_annotation_label(text_uid)
        if event.button() == Qt.MouseButton.MiddleButton:
            if not advanced_mouse_controls:
                super().mousePressEvent(event)
                return
            if self._ctrl_held or self._cursor_mode == "place":
                event.accept()
                return
            if (
                self._persistent_cursor_mode == "zoom"
                and self._pre_zoom_persistent_mode
            ):
                self._persistent_cursor_mode = self._pre_zoom_persistent_mode
                self.cursor_mode_change_requested.emit(self._persistent_cursor_mode)
                event.accept()
                return
            if not self._pre_zoom_persistent_mode:
                self._pre_zoom_persistent_mode = self._persistent_cursor_mode
            self._persistent_cursor_mode = "zoom"
            self.cursor_mode_change_requested.emit("zoom")
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._suppress_next_context_menu = False
            if not advanced_mouse_controls:
                super().mousePressEvent(event)
                return
            if self._cursor_mode == "place":
                event.accept()
                return
            if self._cursor_mode == "zoom" or self._ctrl_held:
                self._apply_zoom(1.0 / self.ZOOM_FACTOR)
            self._right_pan_active = True
            self._right_pan_press_pos = vp_pos
            self._right_pan_press_timer.restart()
            self._right_pan_dragged = False
            self._pre_pan_persistent_mode = self._persistent_cursor_mode
            self._panning = True
            self._last_pan_point = vp_pos
            if not self._ctrl_held:
                self.cursor_mode_change_requested.emit("pan")
            self._update_cursor()
            event.accept()
            return
        if self._cursor_mode == "zoom":
            if event.button() == Qt.MouseButton.LeftButton:
                self._rubber_band_origin = self.mapToScene(vp_pos)
                if self._rubber_band is None:
                    self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
                self._rubber_band.setGeometry(QRect(vp_pos, vp_pos))
                self._rubber_band.show()
                event.accept()
            else:
                super().mousePressEvent(event)
        elif (
            self._cursor_mode == "place" and event.button() == Qt.MouseButton.LeftButton
        ):
            self.handle_place_press(event)
        elif (
            self._cursor_mode == "paste_backout"
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.handle_paste_backout_press(event)
        elif (
            self._cursor_mode in ("rotate", "slope_rotate")
            and event.button() == Qt.MouseButton.LeftButton
        ):
            near_handle = False
            if self._rotate_handle_item is not None:
                handle_vp = self.mapFromScene(self._rotate_handle_item.pos())
                dist = math.hypot(
                    vp_pos.x() - handle_vp.x(), vp_pos.y() - handle_vp.y()
                )
                near_handle = dist <= 16
            if near_handle:
                scene_pos = self.mapToScene(vp_pos)
                dx = scene_pos.x() - self._rotate_center_scene.x()
                dy = scene_pos.y() - self._rotate_center_scene.y()
                self._rotation_drag_last_angle = math.degrees(math.atan2(dy, dx))
                self._rotation_drag_accumulated_deg = 0.0
                self._rotation_drag_uid = self._rotate_handle_uid
                self._rotation_drag_active = True
                self._rotation_drag_snapped_deg = 0.0
                self._rotation_drag_orig_positions = {}
                self._rotation_drag_orig_rotations = {}
                self._rotation_drag_preview_items = []
                if self._cursor_mode == "slope_rotate":
                    uid = self._rotate_handle_uid
                    takeoff = self._current_takeoffs.get(uid)
                    if takeoff is not None:
                        self._rotation_drag_uid = uid
                        self._rotation_drag_orig_rotations[uid] = takeoff.rotation
                    else:
                        self._rotation_drag_active = False
                    event.accept()
                    return
                rotation_preview_uids = self._selected_rotation_preview_uids()
                for sel_uid in rotation_preview_uids:
                    t = self._current_takeoffs.get(sel_uid)
                    if t:
                        self._rotation_drag_orig_positions[sel_uid] = list(t.position)
                        self._rotation_drag_orig_rotations[sel_uid] = t.rotation
                    else:
                        ann = self._current_annotations.get(sel_uid)
                        if ann and ann.is_interactive:
                            self._rotation_drag_orig_positions[sel_uid] = list(
                                ann.position
                            )
                self._rotation_drag_handle_origins = [
                    (info.item, QtCore.QPointF(info.item.pos()))
                    for info in self._handle_infos
                ]
                seen_preview_items = set()

                def _bake_rotation(item):
                    if item.rotation() != 0.0:
                        origin = item.transformOriginPoint()
                        rot = item.rotation()
                        bake = QTransform()
                        bake.translate(origin.x(), origin.y())
                        bake.rotate(rot)
                        bake.translate(-origin.x(), -origin.y())
                        item.setTransform(bake * item.transform())
                        item.setRotation(0)
                        item.setTransformOriginPoint(0, 0)

                def _register_preview_item(item):
                    if item.data(2) == "condition_label":
                        return
                    key = id(item)
                    if key in seen_preview_items:
                        return
                    seen_preview_items.add(key)
                    local_center = item.mapFromScene(self._rotate_center_scene)
                    item.setTransformOriginPoint(local_center)
                    self._rotation_drag_preview_items.append(item)

                for sel_uid in rotation_preview_uids:
                    for item in self._uid_to_items.get(sel_uid, []):
                        _bake_rotation(item)
                        _register_preview_item(item)
                for item in self._selection_items:
                    if (
                        isinstance(item, QGraphicsPathItem)
                        and item.data(0) in rotation_preview_uids
                    ):
                        _bake_rotation(item)
                        _register_preview_item(item)
                event.accept()
                return
            scene_pos = self.mapToScene(vp_pos)
            hit_uid = self.find_takeoff_at(scene_pos)
            if not (hit_uid and hit_uid in self._selected_uids):
                self._remove_rotate_handle()
                self._apply_cursor_mode("select")
                self.cursor_mode_change_requested.emit("select")
            else:
                self._remove_rotate_handle()
        if event.button() == Qt.MouseButton.LeftButton and self._cursor_mode not in (
            "zoom",
            "place",
        ):
            if (
                self._cursor_mode in ("select", "rotate", "slope_rotate")
                and self._selection_enabled
            ):
                ctrl_zoom_requested = advanced_mouse_controls and (
                    bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                    or self._ctrl_held
                )
                self._zoom_press_ctrl = (
                    ctrl_zoom_requested and self._cursor_mode == "select"
                )
                self._select_band_origin = self.mapToScene(vp_pos)
                self._select_band_active = False
                self._select_band_dragged = False
                self._press_changed_selection = False
                self._clear_drag_tracking(restore_preview=True)
                if self._zoom_press_ctrl:
                    event.accept()
                    return
                scene_pos = self.mapToScene(vp_pos)
                multi = bool(
                    event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier
                    )
                )
                _can_start_drag = False
                if len(self._selected_uids) == 1:
                    for info in self._handle_infos:
                        center = info.item.mapToScene(QtCore.QPointF(0.0, 0.0))
                        handle_vp = self.mapFromScene(center)
                        half = info.item.rect().width() / 2
                        if (
                            abs(vp_pos.x() - handle_vp.x()) <= half + 2
                            and abs(vp_pos.y() - handle_vp.y()) <= half + 2
                        ):
                            _can_start_drag = True
                            break
                if not _can_start_drag:
                    hit_uid = self.find_selected_movable_at(scene_pos)
                    if not hit_uid:
                        hit_uid = self.find_takeoff_at(scene_pos)
                    hit_ann = (
                        self._current_annotations.get(hit_uid) if hit_uid else None
                    )
                    if hit_ann and hit_ann.is_hotlink:
                        hit_uid = None
                    if hit_uid:
                        if hit_uid in self._selected_uids:
                            _can_start_drag = True
                        elif not multi:
                            if any(
                                u in self._selected_uids
                                for u in self.find_takeoffs_at(scene_pos)
                            ):
                                _can_start_drag = True
                            else:
                                self._flush_dirty_positions()
                                self._selected_uids = {hit_uid}
                                self._on_selection_changed()
                                self.update_selection_visuals()
                                self._press_changed_selection = True
                                _can_start_drag = True
                if _can_start_drag:
                    if len(self._selected_uids) == 1:
                        uid = next(iter(self._selected_uids))
                        takeoff = self._current_takeoffs.get(uid)
                        ann = (
                            self._current_annotations.get(uid) if not takeoff else None
                        )
                        elem_pos = list(
                            takeoff.position if takeoff else ann.position if ann else []
                        )
                        if elem_pos:
                            self._drag_takeoff_uid = uid
                            self._drag_orig_position = elem_pos
                            self._drag_item_orig_positions = {
                                id(item): item.pos()
                                for item in self._uid_to_items.get(uid, [])
                            }
                            self._drag_item_orig_paths = {
                                id(item): QPainterPath(item.path())
                                for item in self._uid_to_items.get(uid, [])
                                if isinstance(item, QGraphicsPathItem)
                            }
                            self._drag_uid_orig_items = {
                                uid: list(self._uid_to_items.get(uid, []))
                            }
                            for info in self._handle_infos:
                                self._drag_item_orig_positions[id(info.item)] = (
                                    info.item.pos()
                                )
                            for item in self._selection_items:
                                self._drag_item_orig_positions.setdefault(
                                    id(item), item.pos()
                                )
                            self._drag_handle_index = -1
                            for i, info in enumerate(self._handle_infos):
                                center = info.item.mapToScene(QtCore.QPointF(0.0, 0.0))
                                handle_vp = self.mapFromScene(center)
                                half = info.item.rect().width() / 2
                                if (
                                    abs(vp_pos.x() - handle_vp.x()) <= half + 2
                                    and abs(vp_pos.y() - handle_vp.y()) <= half + 2
                                ):
                                    self._drag_handle_index = i
                                    break
                            if takeoff:
                                condition = self._current_conditions.get(
                                    takeoff.condition_uid
                                )
                                if condition and condition.is_area:
                                    self._drag_handle_corner_count = (
                                        len(takeoff.position) // 2
                                    )
                                    self._drag_last_valid_new_pos = list(
                                        takeoff.position
                                    )
                            elif ann and ann.can_resize:
                                atype = ann.annotation_type
                                if atype in ("polygon", "cloud"):
                                    self._drag_handle_corner_count = (
                                        len(ann.position) // 2
                                    )
                                elif atype in (
                                    "rect",
                                    "oval",
                                    "highlight",
                                    "namedview",
                                    "text",
                                ):
                                    if atype != "text" or len(ann.position) >= 4:
                                        self._drag_handle_corner_count = 4
                                        if self._drag_handle_index >= 0:
                                            self._unrotate_annotation_for_resize(
                                                ann, uid
                                            )
                    elif len(self._selected_uids) > 1:
                        self._drag_item_orig_positions = {}
                        for uid in self._selected_uids:
                            takeoff = self._current_takeoffs.get(uid)
                            ann = (
                                self._current_annotations.get(uid)
                                if not takeoff
                                else None
                            )
                            pos = (
                                list(takeoff.position)
                                if takeoff
                                else list(ann.position) if ann else None
                            )
                            if pos:
                                self._drag_multi_orig_positions[uid] = pos
                                for item in self._uid_to_items.get(uid, []):
                                    self._drag_item_orig_positions[id(item)] = (
                                        item.pos()
                                    )
                        for item in self._selection_items:
                            self._drag_item_orig_positions[id(item)] = item.pos()
                if _can_start_drag:
                    drag_positions = {}
                    if self._drag_takeoff_uid and self._drag_orig_position:
                        drag_positions[self._drag_takeoff_uid] = (
                            self._drag_orig_position
                        )
                    elif self._drag_multi_orig_positions:
                        drag_positions = self._drag_multi_orig_positions
                    self.begin_intelligent_paste_drag_if_pending(drag_positions)
                    self._update_cursor(vp_pos)
                else:
                    self.finish_intelligent_paste_placement()
                    if (
                        not multi
                        and not self.find_hotlink_at(scene_pos)
                        and self._begin_pdf_text_selection(scene_pos)
                    ):
                        self._select_band_origin = None
                        self._select_band_active = False
                        self._select_band_dragged = False
                        event.accept()
                        return
                event.accept()
            elif (
                self._cursor_mode == "pan"
                and self._ctrl_held
                and advanced_mouse_controls
            ):
                self._zoom_press_ctrl = True
                self._select_band_origin = self.mapToScene(vp_pos)
                self._select_band_active = False
                self._select_band_dragged = False
                event.accept()
            elif self._cursor_mode == "pan":
                self._panning = True
                self._last_pan_point = vp_pos
                self._update_cursor()
                event.accept()
            else:
                scene_pos = self.mapToScene(vp_pos)
                hotlink_info = self.find_hotlink_at(scene_pos)
                if hotlink_info:
                    self.hotlink_clicked.emit(hotlink_info)
                    event.accept()
                else:
                    super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        cur_vp = event.position().toPoint()
        self._last_mouse_vp_pos = cur_vp
        self._request_crosshair_repaint()
        self._clear_stale_drag_tracking_if_mouse_released(event)
        if self._cursor_mode == "place":
            if self._panning and self._last_pan_point:
                delta = cur_vp - self._last_pan_point
                self._last_pan_point = cur_vp
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x()
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y()
                )
                event.accept()
                return
            if not self._place_flashing:
                scene_pos = self.mapToScene(cur_vp)
                condition = self._current_conditions.get(
                    self._backout_active_uid or self._place_session_uid
                )
                cond_type = condition.condition_type if condition else -1
                if self._should_update_place_preview(cond_type):
                    self.update_place_preview(scene_pos)
            event.accept()
            return
        if self._cursor_mode == "paste_backout":
            if self._panning and self._last_pan_point:
                delta = cur_vp - self._last_pan_point
                self._last_pan_point = cur_vp
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x()
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y()
                )
                event.accept()
                return
            self.update_paste_backout_preview(self.mapToScene(cur_vp))
            event.accept()
            return
        if self._rotation_drag_active:
            scene_pos = self.mapToScene(cur_vp)
            dx = scene_pos.x() - self._rotate_center_scene.x()
            dy = scene_pos.y() - self._rotate_center_scene.y()
            current_angle = math.degrees(math.atan2(dy, dx))
            angle_step = current_angle - self._rotation_drag_last_angle
            angle_step = (angle_step + 180) % 360 - 180
            self._rotation_drag_last_angle = current_angle
            self._rotation_drag_accumulated_deg += angle_step
            mods = event.modifiers()
            if mods & Qt.KeyboardModifier.ShiftModifier:
                snapped_deg = self._rotation_drag_accumulated_deg
            elif mods & Qt.KeyboardModifier.ControlModifier:
                snapped_deg = round(self._rotation_drag_accumulated_deg / 45.0) * 45.0
            else:
                snapped_deg = round(self._rotation_drag_accumulated_deg / 15.0) * 15.0
            if snapped_deg != self._rotation_drag_snapped_deg:
                single = len(self._selected_uids) == 1
                if self._cursor_mode == "slope_rotate":
                    self._rotation_drag_snapped_deg = snapped_deg
                    self._update_rotation_handle_preview(snapped_deg)
                    event.accept()
                    return
                if single:
                    takeoff = self._current_takeoffs.get(self._rotation_drag_uid)
                    if takeoff and takeoff.is_hole and takeoff.parent_uid:
                        candidate_pos = rotate_position_coords(
                            self._rotation_drag_orig_positions[self._rotation_drag_uid],
                            snapped_deg,
                            is_area=True,
                        )
                        if self._check_hole_overlap(
                            candidate_pos,
                            parent_uid=takeoff.parent_uid,
                            exclude_uid=self._rotation_drag_uid,
                        ):
                            event.accept()
                            return
                self._rotation_drag_snapped_deg = snapped_deg
                for item in self._rotation_drag_preview_items:
                    item.setRotation(snapped_deg)
                self._update_rotation_handle_preview(snapped_deg)
                rad = math.radians(snapped_deg)
                cos_a = math.cos(rad)
                sin_a = math.sin(rad)
                cx = self._rotate_center_scene.x()
                cy = self._rotate_center_scene.y()
                for handle_item, orig_pos in self._rotation_drag_handle_origins:
                    hdx = orig_pos.x() - cx
                    hdy = orig_pos.y() - cy
                    handle_item.setPos(
                        cx + hdx * cos_a - hdy * sin_a,
                        cy + hdx * sin_a + hdy * cos_a,
                    )
                if single:
                    takeoff = self._current_takeoffs.get(self._rotation_drag_uid)
                    if takeoff and takeoff.is_hole:
                        rotated_pos = rotate_position_coords(
                            self._rotation_drag_orig_positions[self._rotation_drag_uid],
                            snapped_deg,
                            is_area=True,
                        )
                        cs = self._scene_builder.get_coordinate_system()
                        hole_tx = cs.transform_vertices_to_2d(rotated_pos)
                        hole_path = QPainterPath()
                        hole_path.moveTo(hole_tx[0], hole_tx[1])
                        for hi in range(2, len(hole_tx) - 1, 2):
                            hole_path.lineTo(hole_tx[hi], hole_tx[hi + 1])
                        hole_path.closeSubpath()
                        self._update_parent_hole_path(
                            takeoff.parent_uid, takeoff.uid, hole_path
                        )
            event.accept()
            return
        if self._pdf_text_drag_anchor is not None:
            self._update_pdf_text_selection_drag(self.mapToScene(cur_vp))
            event.accept()
            return
        if self._select_band_origin is not None:
            vp_origin = self.mapFromScene(self._select_band_origin)
            delta = cur_vp - vp_origin
            if abs(delta.x()) > 5 or abs(delta.y()) > 5:
                self._select_band_dragged = True
            if (
                self._zoom_press_ctrl
                and self._select_band_dragged
                and not self._select_band_active
            ):
                self._rubber_band_origin = self._select_band_origin
                self._select_band_origin = None
                self._clear_drag_tracking(restore_preview=True)
                if self._rubber_band is None:
                    self._rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, self)
                vp_rb = self.mapFromScene(self._rubber_band_origin)
                self._rubber_band.setGeometry(QRect(vp_rb, cur_vp).normalized())
                self._rubber_band.show()
                event.accept()
                return
            if not self._select_band_active and (
                abs(delta.x()) > 5 or abs(delta.y()) > 5
            ):
                if not self._drag_takeoff_uid and not self._drag_multi_orig_positions:
                    self._select_band_active = True
                    if self._rubber_band is None:
                        self._rubber_band = QRubberBand(
                            QRubberBand.Shape.Rectangle, self
                        )
                    self._rubber_band.setGeometry(QRect(vp_origin, vp_origin))
                    self._rubber_band.show()
            if self._select_band_active and self._rubber_band is not None:
                self._rubber_band.setGeometry(QRect(vp_origin, cur_vp).normalized())
                event.accept()
                return
            if (
                self._drag_takeoff_uid
                and self._drag_handle_index >= -1
                and self._drag_orig_position
            ):
                scene_cur = self.mapToScene(cur_vp)
                sdx = scene_cur.x() - self._select_band_origin.x()
                sdy = scene_cur.y() - self._select_band_origin.y()
                ost_dx, ost_dy = self.scene_to_ost_delta(sdx, sdy)
                ost_dx, ost_dy = self.apply_intelligent_paste_axis_snap(ost_dx, ost_dy)
                _drag_ann = self._current_annotations.get(self._drag_takeoff_uid)
                if (
                    _drag_ann
                    and _drag_ann.is_interactive
                    and self._drag_handle_index >= 0
                ):
                    new_pos = self._compute_ann_resize(
                        _drag_ann,
                        self._drag_orig_position,
                        ost_dx,
                        ost_dy,
                        self._drag_handle_index,
                        self._drag_handle_corner_count,
                    )
                else:
                    _text_move = (
                        _drag_ann is not None
                        and _drag_ann.is_text
                        and self._drag_handle_index == -1
                    )
                    _shift = bool(
                        event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
                    )
                    new_pos = self.compute_new_position(
                        self._drag_orig_position,
                        ost_dx,
                        ost_dy,
                        self._drag_handle_index,
                        self._drag_handle_corner_count,
                        move_only_first_pair=_text_move,
                        free_mode=_shift,
                    )
                    if _drag_ann and _drag_ann.is_ink and len(new_pos) % 2 == 1:
                        new_pos[0] = self._drag_orig_position[0]
                self.update_drag_handle_positions(
                    new_pos, self._drag_takeoff_uid, sdx, sdy
                )
                event.accept()
                return
            if self._drag_multi_orig_positions and self._drag_item_orig_positions:
                scene_cur = self.mapToScene(cur_vp)
                sdx = scene_cur.x() - self._select_band_origin.x()
                sdy = scene_cur.y() - self._select_band_origin.y()
                ost_dx, ost_dy = self.scene_to_ost_delta(sdx, sdy)
                ost_dx, ost_dy = self.apply_intelligent_paste_axis_snap(ost_dx, ost_dy)
                self._update_snapped_multi_drag_preview(sdx, sdy, ost_dx, ost_dy)
                event.accept()
                return
        if self._rubber_band is not None and self._rubber_band_origin is not None:
            vp_origin = self.mapFromScene(self._rubber_band_origin)
            self._rubber_band.setGeometry(QRect(vp_origin, cur_vp).normalized())
            event.accept()
            return
        if self._panning and self._last_pan_point:
            if self._right_pan_active:
                total = cur_vp - self._right_pan_press_pos
                threshold = QApplication.startDragDistance()
                if total.manhattanLength() >= threshold:
                    self._right_pan_dragged = True
                    self._suppress_next_context_menu = True
            delta = cur_vp - self._last_pan_point
            self._last_pan_point = cur_vp
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x()
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y()
            )
            if self._can_zoom_rerender:
                self._zoom_debouncer.handle_scale_changed(self.transform().m11())
            event.accept()
        else:
            super().mouseMoveEvent(event)
            self._update_cursor(cur_vp)

    def mouseReleaseEvent(self, event: QMouseEvent):
        vp_pos = event.position().toPoint()
        self._last_mouse_vp_pos = vp_pos
        if event.button() == Qt.MouseButton.RightButton and self._right_pan_active:
            held_ms = self._right_pan_press_timer.elapsed()
            if self._right_pan_dragged or held_ms > RIGHT_CLICK_CONTEXT_MENU_MAX_MS:
                self._suppress_next_context_menu = True
            self._right_pan_active = False
            self._panning = False
            self._last_pan_point = None
            self._right_pan_press_pos = None
            self._right_pan_dragged = False
            self._persistent_cursor_mode = self._pre_pan_persistent_mode
            self._pre_pan_persistent_mode = None
            self.cursor_mode_change_requested.emit(self._persistent_cursor_mode)
            self._update_cursor()
            event.accept()
            return
        if self._cursor_mode == "place" and event.button() == Qt.MouseButton.LeftButton:
            if self.handle_place_release_area(event):
                return
            if self.handle_place_release_linear(event):
                return
        if self._rotation_drag_active and event.button() == Qt.MouseButton.LeftButton:
            snapped_deg = self._rotation_drag_snapped_deg
            single = len(self._selected_uids) == 1
            slope_mode = self._cursor_mode == "slope_rotate"
            rotation_drag_uid = self._rotation_drag_uid
            self._rotation_drag_active = False
            self._rotation_drag_uid = None
            self._rotation_drag_last_angle = 0.0
            self._rotation_drag_accumulated_deg = 0.0
            self._rotation_drag_snapped_deg = 0.0
            self._rotation_drag_preview_items = []
            self._rotation_drag_handle_origins = []
            if abs(snapped_deg) > 1e-9:
                if slope_mode:
                    self._apply_slope_rotation(rotation_drag_uid, snapped_deg)
                elif single:
                    uid = next(iter(self._selected_uids))
                    self._apply_single_rotation(uid, snapped_deg)
                else:
                    self._apply_multi_rotation(snapped_deg)
            self._restore_rotation_handles_if_needed()
            self._update_cursor()
            event.accept()
            return
        if (
            self._pdf_text_drag_anchor is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._update_pdf_text_selection_drag(self.mapToScene(vp_pos))
            self._finish_pdf_text_selection_drag()
            self._selected_uids.clear()
            self._on_selection_changed()
            self.update_selection_visuals()
            self._update_cursor()
            event.accept()
            return
        if (
            self._select_band_origin is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            origin = self._select_band_origin
            was_drag = self._select_band_active
            was_dragged = self._select_band_dragged
            zoom_click = self._zoom_press_ctrl
            self._select_band_origin = None
            self._select_band_active = False
            self._select_band_dragged = False
            self._zoom_press_ctrl = False
            if zoom_click and not was_dragged and self._drag_takeoff_uid is None:
                self._apply_zoom(self.ZOOM_FACTOR)
                event.accept()
                return
            if was_drag and self._rubber_band:
                self._rubber_band.hide()
                vp_origin = self.mapFromScene(origin)
                rect = QRect(vp_origin, vp_pos).normalized()
                if rect.width() > 2 and rect.height() > 2:
                    scene_rect = self.mapToScene(rect).boundingRect()
                    new_uids = set()
                    for item in self._scene.items(
                        scene_rect, self._roping_item_selection_mode()
                    ):
                        uid = item.data(0)
                        if uid and self._is_selectable(uid):
                            new_uids.add(uid)
                    multi = bool(
                        event.modifiers()
                        & (
                            Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.ShiftModifier
                        )
                    )
                    self._flush_dirty_positions()
                    if multi:
                        self._selected_uids ^= new_uids
                    else:
                        self._selected_uids = new_uids
                    self._on_selection_changed()
                    self.update_selection_visuals()
                    self._update_cursor()
                event.accept()
                return
            else:
                if (
                    not was_dragged
                    and self._drag_takeoff_uid
                    and self._drag_item_orig_positions
                ):
                    for item in self._uid_to_items.get(self._drag_takeoff_uid, []):
                        orig = self._drag_item_orig_positions.get(id(item))
                        if orig is not None:
                            item.setPos(orig)
                    self._drag_item_orig_positions = {}
                    self._drag_takeoff_uid = None
                    self._drag_handle_index = -2
                    self._drag_orig_position = []
                if was_dragged and (
                    self._drag_takeoff_uid is not None
                    or self._drag_multi_orig_positions
                ):
                    if self._drag_takeoff_uid and self._drag_orig_position:
                        release_scene = self.mapToScene(vp_pos)
                        sdx = release_scene.x() - origin.x()
                        sdy = release_scene.y() - origin.y()
                        ost_dx, ost_dy = self.scene_to_ost_delta(sdx, sdy)
                        ost_dx, ost_dy = self.apply_intelligent_paste_axis_snap(
                            ost_dx, ost_dy
                        )
                        _drag_ann = self._current_annotations.get(
                            self._drag_takeoff_uid
                        )
                        if (
                            _drag_ann
                            and _drag_ann.is_interactive
                            and self._drag_handle_index >= 0
                        ):
                            new_pos = self._compute_ann_resize(
                                _drag_ann,
                                self._drag_orig_position,
                                ost_dx,
                                ost_dy,
                                self._drag_handle_index,
                                self._drag_handle_corner_count,
                            )
                        else:
                            _text_move = (
                                _drag_ann is not None
                                and _drag_ann.is_text
                                and self._drag_handle_index == -1
                            )
                            if _drag_ann and _drag_ann.is_ink:
                                new_pos = self.compute_new_position(
                                    self._drag_orig_position,
                                    ost_dy,
                                    ost_dx,
                                    -1,
                                    0,
                                )
                                if len(new_pos) % 2 == 1:
                                    new_pos[0] = self._drag_orig_position[0]
                            else:
                                _shift_r = bool(
                                    event.modifiers()
                                    & QtCore.Qt.KeyboardModifier.ShiftModifier
                                )
                                new_pos = self.compute_new_position(
                                    self._drag_orig_position,
                                    ost_dx,
                                    ost_dy,
                                    self._drag_handle_index,
                                    self._drag_handle_corner_count,
                                    move_only_first_pair=_text_move,
                                    free_mode=_shift_r,
                                )
                        takeoff = self._current_takeoffs.get(self._drag_takeoff_uid)
                        condition = (
                            self._current_conditions.get(takeoff.condition_uid)
                            if takeoff
                            else None
                        )
                        if (
                            condition
                            and condition.is_area
                            and self._drag_last_valid_new_pos
                        ):
                            new_pos = self._drag_last_valid_new_pos
                        uid = self._drag_takeoff_uid
                        if uid in self._current_takeoffs:
                            takeoff = self._current_takeoffs.get(uid)
                            if takeoff:
                                takeoff.position = new_pos
                            if uid not in self._position_before_edit:
                                self._position_before_edit[uid] = list(
                                    self._drag_orig_position
                                )
                            self._dirty_positions[uid] = new_pos
                            if (
                                self._drag_handle_index == -1
                                and condition
                                and condition.is_area
                            ):
                                for child in self._current_takeoffs.values():
                                    if child.parent_uid == uid:
                                        orig_child_pos = list(child.position)
                                        if child.uid not in self._position_before_edit:
                                            self._position_before_edit[child.uid] = (
                                                orig_child_pos
                                            )
                                        new_child_pos = list(orig_child_pos)
                                        for ci in range(0, len(new_child_pos) - 1, 2):
                                            new_child_pos[ci] = self.snap_ost(
                                                new_child_pos[ci] + ost_dx
                                            )
                                            new_child_pos[ci + 1] = self.snap_ost(
                                                new_child_pos[ci + 1] + ost_dy
                                            )
                                        child.position = new_child_pos
                                        self._dirty_positions[child.uid] = new_child_pos
                        elif uid in self._current_annotations:
                            ann = self._current_annotations.get(uid)
                            if ann:
                                ann.position = new_pos
                                if uid not in self._position_before_edit:
                                    self._position_before_edit[uid] = list(
                                        self._drag_orig_position
                                    )
                                self._dirty_ann_positions[uid] = (
                                    ann.annotation_type,
                                    new_pos,
                                )
                    if self._drag_multi_orig_positions:
                        release_scene = self.mapToScene(vp_pos)
                        sdx = release_scene.x() - origin.x()
                        sdy = release_scene.y() - origin.y()
                        ost_dx, ost_dy = self.scene_to_ost_delta(sdx, sdy)
                        ost_dx, ost_dy = self.apply_intelligent_paste_axis_snap(
                            ost_dx, ost_dy
                        )
                        for uid, orig_pos in self._drag_multi_orig_positions.items():
                            new_pos = self._compute_snapped_multi_drag_position(
                                uid, orig_pos, ost_dx, ost_dy
                            )
                            if uid in self._current_takeoffs:
                                takeoff = self._current_takeoffs.get(uid)
                                if takeoff:
                                    takeoff.position = new_pos
                                if uid not in self._position_before_edit:
                                    self._position_before_edit[uid] = list(orig_pos)
                                self._dirty_positions[uid] = new_pos
                            elif uid in self._current_annotations:
                                ann = self._current_annotations.get(uid)
                                if ann:
                                    ann.position = new_pos
                                    if uid not in self._position_before_edit:
                                        self._position_before_edit[uid] = list(orig_pos)
                                    self._dirty_ann_positions[uid] = (
                                        ann.annotation_type,
                                        new_pos,
                                    )
                    self._flush_dirty_positions()
                    self._clear_drag_tracking()
                    self.finish_intelligent_paste_placement()
                    self._update_cursor()
                    event.accept()
                    return
                self._drag_handle_index = -2
                scene_pos = origin
                multi = bool(
                    event.modifiers()
                    & (
                        Qt.KeyboardModifier.ControlModifier
                        | Qt.KeyboardModifier.ShiftModifier
                    )
                )
                cycle_uid = None
                if (
                    not multi
                    and not self._press_changed_selection
                    and len(self._selected_uids) == 1
                ):
                    current_uid = next(iter(self._selected_uids))
                    hits = self.find_takeoffs_at(scene_pos)
                    if current_uid in hits and len(hits) > 1:
                        cycle_uid = current_uid
                hotlink_info = self.find_hotlink_at(scene_pos)
                if hotlink_info:
                    self._clear_pdf_text_selection()
                    self.hotlink_clicked.emit(hotlink_info)
                else:
                    uid = self.find_takeoff_at(scene_pos, cycle_from_uid=cycle_uid)
                    if uid:
                        self._clear_pdf_text_selection()
                        if multi:
                            if uid in self._selected_uids:
                                self._flush_dirty_positions()
                                self._selected_uids.discard(uid)
                            else:
                                self._selected_uids.add(uid)
                        else:
                            if uid not in self._selected_uids:
                                self._flush_dirty_positions()
                            self._selected_uids = {uid}
                        self._on_selection_changed()
                        self.update_selection_visuals()
                    else:
                        selected_pdf_text = self.select_pdf_text_at(scene_pos)
                        if not multi:
                            self._flush_dirty_positions()
                            self._selected_uids.clear()
                        self._on_selection_changed()
                        self.update_selection_visuals()
                        if not selected_pdf_text:
                            self._clear_pdf_text_selection()
                if self._cursor_mode == "rotate" and len(self._selected_uids) == 1:
                    if not self._create_rotate_handle(next(iter(self._selected_uids))):
                        self._apply_cursor_mode("select")
                        self.cursor_mode_change_requested.emit("select")
                self._update_cursor()
                event.accept()
                return
        if (
            self._rubber_band is not None
            and self._rubber_band_origin is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._rubber_band.hide()
            vp_origin = self.mapFromScene(self._rubber_band_origin)
            self._rubber_band_origin = None
            self._zoom_press_ctrl = False
            rect = QRect(vp_origin, vp_pos).normalized()
            if rect.width() > 5 and rect.height() > 5:
                scene_rect = self.mapToScene(rect).boundingRect()
                if scene_rect.isValid():
                    self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
                    new_scale = self.transform().m11()
                    self._zoom_debouncer.handle_scale_changed(new_scale)
                    self.zoom_changed.emit(new_scale * self._scene_scale * 0.333)
            elif self._cursor_mode == "zoom":
                self._apply_zoom(self.ZOOM_FACTOR)
            event.accept()
        elif self._panning and event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._last_pan_point = None
            self._update_cursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _unrotate_annotation_for_resize(self, ann, uid: str) -> None:
        pos = list(ann.position)
        stored_rad = ann.stored_rotation_rad
        if stored_rad == 0.0:
            return
        stored_deg = math.degrees(stored_rad)
        atype = ann.annotation_type
        if atype == "text" and len(pos) >= 5:
            pos[4] = 0.0
        elif atype in ("rect", "highlight", "namedview", "oval"):
            n_coords = len(pos) - 1 if len(pos) % 2 == 1 else len(pos)
            coord_pos = pos[:n_coords]
            cx = sum(coord_pos[i] for i in range(0, n_coords, 2)) / (n_coords // 2)
            cy = sum(coord_pos[i] for i in range(1, n_coords, 2)) / (n_coords // 2)
            unrotated = rotate_points_around(coord_pos, -stored_deg, cx, cy)
            pos = list(unrotated)
        if uid not in self._position_before_edit:
            self._position_before_edit[uid] = list(ann.position)
        ann.position = pos
        self._dirty_ann_positions[uid] = (ann.annotation_type, pos)
        self._drag_orig_position = list(pos)
        self._flush_dirty_positions()

    def _compute_snapped_multi_drag_position(
        self, uid: str, orig_pos: list, ost_dx: float, ost_dy: float
    ) -> list:
        ann = self._current_annotations.get(uid)
        if ann and ann.is_ink:
            new_pos = self.compute_new_position(orig_pos, ost_dy, ost_dx, -1, 0)
            if len(new_pos) % 2 == 1:
                new_pos[0] = orig_pos[0]
            return new_pos
        text_move = ann is not None and ann.is_text
        return self.compute_new_position(
            orig_pos,
            ost_dx,
            ost_dy,
            -1,
            0,
            move_only_first_pair=text_move,
        )

    def _snapped_multi_drag_scene_delta(
        self,
        orig_pos: list,
        new_pos: list,
        fallback_sdx: float,
        fallback_sdy: float,
    ) -> QtCore.QPointF:
        if len(orig_pos) < 2 or len(new_pos) < 2:
            return QtCore.QPointF(fallback_sdx, fallback_sdy)
        item_sdx, item_sdy = self.ost_to_scene_delta(
            new_pos[0] - orig_pos[0],
            new_pos[1] - orig_pos[1],
        )
        return QtCore.QPointF(item_sdx, item_sdy)

    def _update_snapped_multi_drag_preview(
        self, scene_dx: float, scene_dy: float, ost_dx: float, ost_dy: float
    ) -> None:
        fallback_delta = QtCore.QPointF(scene_dx, scene_dy)
        preview_delta_by_uid = {}
        for uid, orig_pos in self._drag_multi_orig_positions.items():
            new_pos = self._compute_snapped_multi_drag_position(
                uid, orig_pos, ost_dx, ost_dy
            )
            delta = self._snapped_multi_drag_scene_delta(
                orig_pos, new_pos, scene_dx, scene_dy
            )
            preview_delta_by_uid[uid] = delta
            for item in self._uid_to_items.get(uid, []):
                orig = self._drag_item_orig_positions.get(id(item))
                if orig is not None:
                    item.setPos(orig + delta)
        for item in self._selection_items:
            orig = self._drag_item_orig_positions.get(id(item))
            if orig is not None:
                delta = preview_delta_by_uid.get(item.data(0), fallback_delta)
                item.setPos(orig + delta)

    def _compute_ann_resize(
        self, ann, orig_pos, ost_dx, ost_dy, handle_idx, corner_count
    ):
        atype = ann.annotation_type
        if atype in ("polygon", "cloud"):
            return self.compute_new_position(
                orig_pos,
                ost_dx,
                ost_dy,
                handle_idx,
                corner_count,
            )
        if atype in ("line", "arrow"):
            return self.compute_new_position(
                orig_pos,
                ost_dx,
                ost_dy,
                handle_idx,
                0,
            )
        bbox = ann.get_bbox_ost()
        if not bbox:
            return list(orig_pos)
        ox1, oy1, ox2, oy2 = bbox
        dx = self.snap_ost(ost_dx)
        dy = self.snap_ost(ost_dy)
        nx1, ny1, nx2, ny2 = self._apply_bbox_handle(
            ox1,
            oy1,
            ox2,
            oy2,
            handle_idx,
            corner_count,
            dx,
            dy,
        )
        pos = list(orig_pos)
        if atype == "text" and len(pos) >= 4:
            pos[2] = abs(nx2 - nx1)
            pos[3] = abs(ny2 - ny1)
            pos[0] = (nx1 + nx2) / 2
            pos[1] = (ny1 + ny2) / 2
            return pos
        ow = ox2 - ox1
        oh = oy2 - oy1
        n_pairs = len(pos) // 2
        for i in range(n_pairs):
            px, py = pos[i * 2], pos[i * 2 + 1]
            pos[i * 2] = nx1 + (px - ox1) / ow * (nx2 - nx1) if abs(ow) > 1e-9 else nx1
            pos[i * 2 + 1] = (
                ny1 + (py - oy1) / oh * (ny2 - ny1) if abs(oh) > 1e-9 else ny1
            )
        return pos

    @staticmethod
    def _apply_bbox_handle(x1, y1, x2, y2, handle_idx, corner_count, dx, dy):
        if handle_idx < corner_count:
            if handle_idx == 0:
                x1 += dx
                y1 += dy
            elif handle_idx == 1:
                x2 += dx
                y1 += dy
            elif handle_idx == 2:
                x2 += dx
                y2 += dy
            elif handle_idx == 3:
                x1 += dx
                y2 += dy
        else:
            edge = handle_idx - corner_count
            if edge == 0:
                y1 += dy
            elif edge == 1:
                x2 += dx
            elif edge == 2:
                y2 += dy
            elif edge == 3:
                x1 += dx
        return x1, y1, x2, y2

    def _update_rotation_handle_preview(self, snapped_deg: float) -> None:
        if (
            self._rotate_handle_item is None
            or self._rotate_line_item is None
            or self._rotate_line_outline_item is None
        ):
            return
        new_angle_rad = math.radians(self._rotate_handle_start_angle_deg + snapped_deg)
        cx = self._rotate_center_scene.x()
        cy = self._rotate_center_scene.y()
        new_hx = cx + self._rotate_handle_radius * math.cos(new_angle_rad)
        new_hy = cy + self._rotate_handle_radius * math.sin(new_angle_rad)
        self._rotate_handle_item.setPos(new_hx, new_hy)
        self._rotate_line_item.setLine(cx, cy, new_hx, new_hy)
        self._rotate_line_outline_item.setLine(cx, cy, new_hx, new_hy)

    def _selected_area_slope_uid(self) -> str:
        if not self._selection_enabled or len(self._selected_uids) != 1:
            return ""
        uid = next(iter(self._selected_uids))
        takeoff = self._current_takeoffs.get(uid)
        if not takeoff or takeoff.is_hole or len(takeoff.position) < 6:
            return ""
        condition = self._current_conditions.get(takeoff.condition_uid)
        if (
            not condition
            or not condition.is_area
            or not condition.layer_visible
            or not abs(condition.rise)
            or not abs(condition.run)
        ):
            return ""
        return uid

    def _create_slope_rotate_handle(self) -> bool:
        uid = self._selected_area_slope_uid()
        if not uid:
            return False
        takeoff = self._current_takeoffs[uid]
        return self._create_rotate_handle(
            {uid},
            start_angle_degrees=math.degrees(-takeoff.rotation),
            slope_mode=True,
        )

    def _apply_slope_rotation(self, uid: Optional[str], snapped_deg: float) -> None:
        if not uid:
            return
        takeoff = self._current_takeoffs.get(uid)
        if takeoff is None:
            return
        orig_rotation = self._rotation_drag_orig_rotations.get(uid, takeoff.rotation)
        if uid not in self._rotation_before_edit:
            self._rotation_before_edit[uid] = orig_rotation
        new_rotation = orig_rotation - math.radians(snapped_deg)
        takeoff.rotation = new_rotation
        self._dirty_rotations[uid] = new_rotation
        self._flush_dirty_rotations()

    def _apply_single_rotation(self, uid: str, snapped_deg: float) -> None:
        ann = self._current_annotations.get(uid)
        if ann and ann.is_interactive:
            if not ann.can_rotate:
                return
            orig_pos = self._rotation_drag_orig_positions[uid]
            sc = self._element_center(
                uid, self._scene_builder.get_coordinate_system(), "ost"
            )
            cx, cy = sc if sc else (orig_pos[0], orig_pos[1])
            new_pos = _rotate_annotation(ann, orig_pos, snapped_deg, cx, cy)
            ann.position = new_pos
            if uid not in self._position_before_edit:
                self._position_before_edit[uid] = list(orig_pos)
            self._dirty_ann_positions[uid] = (ann.annotation_type, new_pos)
            self._flush_dirty_positions()
            return
        takeoff = self._current_takeoffs[uid]
        condition = self._current_conditions.get(takeoff.condition_uid)
        is_count = condition is not None and condition.is_count
        is_area = condition is not None and condition.is_area
        is_linear = condition is not None and condition.is_linear
        is_curved = is_linear and takeoff.curve >= 0
        orig_pos = self._rotation_drag_orig_positions[uid]
        if is_count:
            orig_rot = self._rotation_drag_orig_rotations[uid]
            if uid not in self._rotation_before_edit:
                self._rotation_before_edit[uid] = orig_rot
            new_rotation = orig_rot + math.radians(snapped_deg)
            takeoff.rotation = new_rotation
            self._dirty_rotations[uid] = new_rotation
            self._flush_dirty_rotations()
        else:
            new_pos = rotate_position_coords(
                orig_pos,
                snapped_deg,
                is_area,
                is_curved,
                is_linear,
                linear_geom=self._linear_geom,
            )
            if takeoff.is_hole and takeoff.parent_uid:
                if self._check_hole_overlap(
                    new_pos,
                    parent_uid=takeoff.parent_uid,
                    exclude_uid=uid,
                ):
                    for item in self._uid_to_items.get(uid, []):
                        if isinstance(item, QGraphicsPathItem):
                            item.setRotation(0.0)
                            item.setTransformOriginPoint(0.0, 0.0)
                    self.update_selection_visuals()
                    self._create_rotate_handle(uid)
                    return
            if uid not in self._position_before_edit:
                self._position_before_edit[uid] = list(orig_pos)
            takeoff.position = new_pos
            self._dirty_positions[uid] = new_pos
            if is_area:
                n_parent = len(orig_pos) // 2
                if n_parent >= 3:
                    pcx, pcy = polygon_centroid(orig_pos, n_parent)
                    for child in self._current_takeoffs.values():
                        if child.parent_uid != uid:
                            continue
                        child_orig = list(child.position)
                        if child.uid not in self._position_before_edit:
                            self._position_before_edit[child.uid] = child_orig
                        child_new = rotate_points_around(
                            child_orig, snapped_deg, pcx, pcy
                        )
                        child.position = child_new
                        self._dirty_positions[child.uid] = child_new
            self._flush_dirty_positions()

    def _apply_multi_rotation(self, snapped_deg: float) -> None:
        ost_cx, ost_cy = self._rotate_ost_center
        has_positions = False
        has_rotations = False
        rotated_uids = set()
        for uid in self._selected_uids:
            if uid not in self._rotation_drag_orig_positions:
                continue
            orig_pos = self._rotation_drag_orig_positions[uid]
            if uid not in self._position_before_edit:
                self._position_before_edit[uid] = list(orig_pos)
            ann = self._current_annotations.get(uid)
            if ann and ann.is_interactive:
                if not ann.can_rotate:
                    continue
                new_pos = _rotate_annotation(ann, orig_pos, snapped_deg, ost_cx, ost_cy)
                ann.position = new_pos
                self._dirty_ann_positions[uid] = (ann.annotation_type, new_pos)
                has_positions = True
                continue
            takeoff = self._current_takeoffs[uid]
            condition = self._current_conditions.get(takeoff.condition_uid)
            new_pos = rotate_points_around(orig_pos, snapped_deg, ost_cx, ost_cy)
            takeoff.position = new_pos
            self._dirty_positions[uid] = new_pos
            rotated_uids.add(uid)
            has_positions = True
            if condition and condition.is_count:
                orig_rot = self._rotation_drag_orig_rotations[uid]
                if uid not in self._rotation_before_edit:
                    self._rotation_before_edit[uid] = orig_rot
                new_rotation = orig_rot + math.radians(snapped_deg)
                takeoff.rotation = new_rotation
                self._dirty_rotations[uid] = new_rotation
                has_rotations = True
        for uid in list(rotated_uids):
            takeoff = self._current_takeoffs[uid]
            condition = self._current_conditions.get(takeoff.condition_uid)
            if condition and condition.is_area:
                orig_pos = self._rotation_drag_orig_positions[uid]
                n_parent = len(orig_pos) // 2
                if n_parent >= 3:
                    pcx, pcy = polygon_centroid(orig_pos, n_parent)
                    for child in self._current_takeoffs.values():
                        if child.parent_uid != uid or child.uid in rotated_uids:
                            continue
                        child_orig = list(child.position)
                        if child.uid not in self._position_before_edit:
                            self._position_before_edit[child.uid] = child_orig
                        child_new = rotate_points_around(
                            child_orig, snapped_deg, pcx, pcy
                        )
                        child.position = child_new
                        self._dirty_positions[child.uid] = child_new
        if has_positions or has_rotations:
            self._flush_rotation_group()

    def _selected_rotation_preview_uids(self) -> set:
        return {uid for uid in self._selected_uids if self._is_rotatable_uid(uid)}

    def rotate_selected_takeoffs(self, degrees: float) -> None:
        self._transform_selected_takeoffs("rotate", degrees=degrees)

    def flip_selected_takeoffs(self, horizontal: bool) -> None:
        self._transform_selected_takeoffs("flip", horizontal=horizontal)

    def _selected_takeoff_uids_for_transform(self) -> set:
        if not self._selection_enabled:
            return set()
        return {
            uid
            for uid in self._selected_uids
            if uid in self._current_takeoffs and self._current_takeoffs[uid].position
        }

    def _takeoff_transform_center(self, uids: set):
        xs = []
        ys = []
        for uid in uids:
            pos = self._current_takeoffs[uid].position
            for i in range(len(pos) // 2):
                xs.append(pos[i * 2])
                ys.append(pos[i * 2 + 1])
        if not xs or not ys:
            return None
        return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0

    def _expanded_takeoff_transform_uids(self, selected_uids: set) -> set:
        affected = set(selected_uids)
        for uid in selected_uids:
            takeoff = self._current_takeoffs.get(uid)
            if not takeoff:
                continue
            condition = self._current_conditions.get(takeoff.condition_uid)
            if not condition or not condition.is_area:
                continue
            for child in self._current_takeoffs.values():
                if child.parent_uid == uid:
                    affected.add(child.uid)
        return affected

    def _transform_selected_takeoffs(
        self, transform_kind: str, degrees: float = 0.0, horizontal: bool = False
    ) -> None:
        if transform_kind not in ("rotate", "flip"):
            raise ValueError(f"Unknown takeoff transform: {transform_kind}")
        selected_uids = self._selected_takeoff_uids_for_transform()
        if not selected_uids:
            return
        center = self._takeoff_transform_center(selected_uids)
        if center is None:
            return
        center_x, center_y = center
        affected_uids = self._expanded_takeoff_transform_uids(selected_uids)
        has_changes = False
        for uid in affected_uids:
            takeoff = self._current_takeoffs.get(uid)
            if not takeoff or not takeoff.position:
                continue
            condition = self._current_conditions.get(takeoff.condition_uid)
            orig_pos = list(takeoff.position)
            if transform_kind == "rotate":
                new_pos = rotate_points_around(orig_pos, degrees, center_x, center_y)
            else:
                new_pos = mirror_points_around(orig_pos, center_x, center_y, horizontal)
            if uid not in self._position_before_edit:
                self._position_before_edit[uid] = orig_pos
            takeoff.position = new_pos
            self._dirty_positions[uid] = new_pos
            has_changes = True
            if condition and condition.is_count:
                orig_rotation = takeoff.rotation
                if uid not in self._rotation_before_edit:
                    self._rotation_before_edit[uid] = orig_rotation
                if transform_kind == "rotate":
                    new_rotation = orig_rotation + math.radians(degrees)
                elif horizontal:
                    new_rotation = math.pi - orig_rotation
                else:
                    new_rotation = -orig_rotation
                takeoff.rotation = new_rotation
                self._dirty_rotations[uid] = new_rotation
        if has_changes:
            self._flush_rotation_group()

    def _restore_rotation_handles_if_needed(self) -> None:
        if self._cursor_mode == "slope_rotate":
            if not self._create_slope_rotate_handle():
                self._apply_cursor_mode("select")
                self.cursor_mode_change_requested.emit("select")
            return
        if self._cursor_mode != "rotate":
            return
        if not self._selected_uids:
            self._remove_rotate_handle()
            return
        self.update_selection_visuals(emit=False)
        if not self._create_rotate_handle(self._selected_uids):
            self._apply_cursor_mode("select")
            self.cursor_mode_change_requested.emit("select")

    def keyPressEvent(self, event) -> None:
        if (
            event.key() == Qt.Key.Key_Escape
            and self.is_text_annotation_inline_edit_active()
        ):
            self._finish_active_inline_text_edit(commit=False)
            event.accept()
            return
        if self.is_text_annotation_inline_edit_active():
            super().keyPressEvent(event)
            return
        if (
            self._advanced_mouse_controls_active()
            and event.key() == Qt.Key.Key_Control
            and not event.isAutoRepeat()
        ):
            self._ctrl_held = True
            self._update_cursor()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z and self._selection_enabled:
                self.undo_requested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Y and self._selection_enabled:
                self.redo_requested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_C and self.copy_selected_pdf_text():
                event.accept()
                return
            if event.key() == Qt.Key.Key_C and self._selected_uids:
                self.copy_requested.emit(list(self._selected_uids))
                event.accept()
                return
            if event.key() == Qt.Key.Key_V and self._selection_enabled:
                self.paste_requested.emit()
                event.accept()
                return
            if event.key() == Qt.Key.Key_R and self._selected_uids:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    if self._cursor_mode == "slope_rotate":
                        self._remove_rotate_handle()
                        self._apply_cursor_mode("select")
                        self.cursor_mode_change_requested.emit("select")
                    elif self._create_slope_rotate_handle():
                        self._apply_cursor_mode("slope_rotate")
                        self.cursor_mode_change_requested.emit("slope_rotate")
                    event.accept()
                    return
                if self._rotate_handle_uid is not None:
                    self._remove_rotate_handle()
                    self._apply_cursor_mode("select")
                    self.cursor_mode_change_requested.emit("select")
                else:
                    if self._create_rotate_handle(self._selected_uids):
                        self._apply_cursor_mode("rotate")
                        self.cursor_mode_change_requested.emit("rotate")
                event.accept()
                return
        if (
            self._cursor_mode in ("rotate", "slope_rotate")
            and event.key() == Qt.Key.Key_Escape
        ):
            self._remove_rotate_handle()
            self._apply_cursor_mode("select")
            self.cursor_mode_change_requested.emit("select")
            event.accept()
            return
        if self._intelligent_paste_active and event.key() == Qt.Key.Key_Escape:
            self._cancel_active_drag_interaction(restore_preview=True)
            self.finish_intelligent_paste_placement()
            self._update_cursor()
            event.accept()
            return
        if self._cursor_mode == "paste_backout" and event.key() == Qt.Key.Key_Escape:
            self.cancel_paste_backout()
            event.accept()
            return
        if self._cursor_mode == "place" and event.key() == Qt.Key.Key_Escape:
            self.finish_intelligent_paste_placement()
            if self._place_points:
                self._place_points.pop()
                self.clear_place_preview()
                if self._place_points:
                    if self._last_mouse_vp_pos is not None:
                        scene_pos = self.mapToScene(self._last_mouse_vp_pos)
                        self.update_place_preview(scene_pos)
                    self.viewport().update()
                else:
                    self._place_linear_dragging = False
                    self._place_area_rect_dragging = False
                    self._set_area_placement_in_progress(False)
            else:
                self._place_linear_dragging = False
                self._place_area_rect_dragging = False
                self.clear_place_preview()
                self._set_area_placement_in_progress(False)
            event.accept()
            return
        if (
            self._selection_enabled
            and self._selected_uids
            and event.key() == Qt.Key.Key_Delete
        ):
            uids = list(self._selected_uids)
            self._selected_uids.clear()
            self._on_selection_changed()
            self.update_selection_visuals()
            self._invalidate_snap_index()
            self.elements_deleted.emit(uids)
            self._update_cursor()
            event.accept()
            return
        if (
            self._selection_enabled
            and self._cursor_mode == "select"
            and event.key() == Qt.Key.Key_A
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.select_all()
            event.accept()
            return
        _arrow_keys = {
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        }
        if (
            self._selection_enabled
            and self._cursor_mode in ("select", "place", "rotate")
            and self._selected_uids
            and event.key() in _arrow_keys
        ):
            step = self._snap_increments if self._snap_increments > 0 else 1.0
            key = event.key()
            ost_dx = (
                -step
                if key == Qt.Key.Key_Left
                else (step if key == Qt.Key.Key_Right else 0.0)
            )
            ost_dy = (
                -step
                if key == Qt.Key.Key_Up
                else (step if key == Qt.Key.Key_Down else 0.0)
            )
            cs = self._scene_builder.get_coordinate_system()
            scene_dx = ost_dx * 72.0 * cs.view_scale / cs.scale_ratio
            scene_dy = ost_dy * 72.0 * cs.view_scale / cs.scale_ratio
            bulk = []
            for uid in self._selected_uids:
                takeoff = self._current_takeoffs.get(uid)
                if not takeoff:
                    continue
                pos = list(takeoff.position)
                if uid not in self._position_before_edit:
                    self._position_before_edit[uid] = list(pos)
                n = (len(pos) // 2) * 2
                for i in range(0, n, 2):
                    pos[i] += ost_dx
                    pos[i + 1] += ost_dy
                takeoff.position = pos
                for item in self._uid_to_items.get(uid, []):
                    item.moveBy(scene_dx, scene_dy)
                bulk.append((uid, pos))
            for item in self._selection_items:
                item.moveBy(scene_dx, scene_dy)
            for uid, pos in bulk:
                self._dirty_positions[uid] = pos
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Control and not event.isAutoRepeat():
            self._ctrl_held = False
            if self._zoom_press_ctrl:
                self._cancel_active_drag_interaction(restore_preview=True)
            self._update_cursor()
        super().keyReleaseEvent(event)

    def _resolve_cursor(self, vp_pos) -> Qt.CursorShape:
        if self._panning and not (self._right_pan_active and self._ctrl_held):
            return Qt.CursorShape.ClosedHandCursor
        if self._rotation_drag_active:
            return self._rotate_cursor
        if self._cursor_mode in ("place", "paste_backout"):
            return Qt.CursorShape.CrossCursor
        if self._zoom_press_ctrl:
            return self._zoom_cursor
        active_press = (
            self._select_band_origin is not None or self._rotation_drag_active
        )
        if active_press:
            if self._drag_handle_index == -1:
                return Qt.CursorShape.SizeAllCursor
            if 0 <= self._drag_handle_index < len(self._handle_infos):
                return self._handle_infos[self._drag_handle_index].cursor
        if (
            self._advanced_mouse_controls_active()
            and self._ctrl_held
            and self._cursor_mode not in ("rotate", "slope_rotate")
            and not active_press
        ):
            return self._zoom_cursor
        if self._cursor_mode == "zoom":
            return self._zoom_cursor
        if self._cursor_mode == "pan":
            return Qt.CursorShape.OpenHandCursor
        if self._cursor_mode in ("rotate", "slope_rotate"):
            if self._rotate_handle_item is not None and vp_pos is not None:
                handle_vp = self.mapFromScene(self._rotate_handle_item.pos())
                dist = math.hypot(
                    vp_pos.x() - handle_vp.x(), vp_pos.y() - handle_vp.y()
                )
                if dist <= 16:
                    return self._rotate_cursor
            if vp_pos is not None:
                return self._resolve_select_cursor(vp_pos)
            return Qt.CursorShape.ArrowCursor
        if self._cursor_mode == "select" and vp_pos is not None:
            return self._resolve_select_cursor(vp_pos)
        return Qt.CursorShape.ArrowCursor

    def _update_cursor(self, vp_pos=None) -> None:
        if vp_pos is None:
            vp_pos = self._last_mouse_vp_pos
        self.viewport().setCursor(self._resolve_cursor(vp_pos))

    def _trigger_context_command(self, action_key: str) -> None:
        if self._context_menu_command_trigger:
            self._context_menu_command_trigger(action_key)

    def _add_context_command(self, menu: QMenu, label: str, action_key: str) -> None:
        add_context_command(
            menu,
            label,
            action_key,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )

    def _add_common_context_submenus(self, menu: QMenu):
        current_mode = (
            self._current_page.image_show_mode if self._current_page is not None else 0
        )
        has_overlay = bool(
            self._current_page is not None and self._current_page.overlay_image_path
        )
        overlay_action, original_action = add_common_context_submenus(
            menu,
            current_mode,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
            has_overlay_image=has_overlay,
        )
        return current_mode, overlay_action, original_action

    def _add_context_clipboard_actions(self, menu: QMenu) -> None:
        add_context_clipboard_actions(
            menu,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )

    def _add_context_page_actions(
        self, menu: QMenu, separate_delete: bool = False
    ) -> None:
        add_context_page_actions(
            menu,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
            separate_delete=separate_delete,
        )

    def _resolve_context_overlay_action(
        self,
        action,
        current_mode: int,
        overlay_action,
        original_action,
    ) -> bool:
        overlay_mode = resolve_overlay_menu_action(
            action,
            current_mode,
            overlay_action,
            original_action,
        )
        if overlay_mode is None:
            return False
        if overlay_mode != current_mode:
            self._trigger_context_command(
                (
                    "show_overlay_image"
                    if action == overlay_action
                    else "show_original_image"
                )
            )
        return True

    def _selected_takeoff_context_state(self) -> SelectedTakeoffContextState:
        takeoff_uids = [
            uid for uid in self._selected_uids if uid in self._current_takeoffs
        ]
        return build_selected_takeoff_context_state(
            takeoff_uids,
            self._current_takeoffs.get,
            self._current_conditions,
        )

    def _show_background_context_menu(self, event) -> None:
        menu = QMenu(self)
        current_mode, overlay_action, original_action = (
            self._add_common_context_submenus(menu)
        )
        menu.addSeparator()
        self._add_context_command(menu, "Paste", "paste")
        menu.addSeparator()
        self._add_context_page_actions(menu, separate_delete=True)
        self.reset_ctrl_held()
        action = menu.exec(event.globalPos())
        if action is None:
            return
        self._resolve_context_overlay_action(
            action, current_mode, overlay_action, original_action
        )

    def _add_pdf_text_context_clipboard_actions(self, menu: QMenu) -> None:
        ContextMenuManager.add_action(
            menu,
            ContextMenuManager.action_spec(
                None,
                "Copy",
                callback=self.copy_selected_pdf_text,
                enabled=self.has_selected_pdf_text(),
                action_key="copy",
            ),
        )
        self._add_context_command(menu, "Paste", "paste")

    def _show_pdf_text_context_menu(self, event) -> None:
        menu = QMenu(self)
        current_mode, overlay_action, original_action = (
            self._add_common_context_submenus(menu)
        )
        menu.addSeparator()
        self._add_pdf_text_context_clipboard_actions(menu)
        menu.addSeparator()
        self._add_context_page_actions(menu, separate_delete=True)
        self.reset_ctrl_held()
        action = menu.exec(event.globalPos())
        if action is None:
            return
        self._resolve_context_overlay_action(
            action, current_mode, overlay_action, original_action
        )

    def contextMenuEvent(self, event) -> None:
        if self._right_pan_active or self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            event.accept()
            return
        selected_state = self._selected_takeoff_context_state()
        if not selected_state.takeoff_uids and self.has_selected_pdf_text():
            self._show_pdf_text_context_menu(event)
            event.accept()
            return
        if not selected_state.takeoff_uids:
            self._show_background_context_menu(event)
            event.accept()
            return
        menu = QMenu(self)
        assign_action = None
        negative_action = None
        curved_action = None
        if selected_state.show_curved:
            curved_action = ContextMenuManager.add_action(
                menu,
                ContextMenuManager.action_spec(
                    None,
                    "Set as Curved Segment",
                    checkable=True,
                    checked=selected_state.all_curved,
                ),
            )
        if selected_state.show_assign:
            assign_action = ContextMenuManager.add_action(
                menu,
                ContextMenuManager.action_spec(None, "Assign to Current Area"),
            )
        if selected_state.show_negative:
            negative_action = ContextMenuManager.add_action(
                menu,
                ContextMenuManager.action_spec(
                    None,
                    "Count as Negative Quantity",
                    checkable=True,
                    checked=selected_state.all_negative,
                ),
            )
        if curved_action or assign_action or negative_action:
            menu.addSeparator()
        current_mode, overlay_action, original_action = (
            self._add_common_context_submenus(menu)
        )
        reassign_condition_menu = add_reassign_condition_submenu(
            menu, self._current_conditions
        )
        menu.addSeparator()
        self._add_context_clipboard_actions(menu)
        menu.addSeparator()
        self._add_context_page_actions(menu)
        self.reset_ctrl_held()
        action = menu.exec(event.globalPos())
        if action is None:
            event.accept()
            return
        if self._resolve_context_overlay_action(
            action, current_mode, overlay_action, original_action
        ):
            event.accept()
            return
        selected_takeoff_uids = list(selected_state.takeoff_uids)
        if reassign_condition_menu and action in reassign_condition_menu.actions:
            self.reassign_condition_requested.emit(
                selected_takeoff_uids, reassign_condition_menu.actions[action]
            )
        elif assign_action and action == assign_action:
            self.assign_to_area_requested.emit(selected_takeoff_uids)
        elif negative_action and action == negative_action:
            self.set_negative_requested.emit(
                selected_takeoff_uids, not selected_state.all_negative
            )
        elif curved_action and action == curved_action:
            self.set_curved_requested.emit(
                selected_takeoff_uids, not selected_state.all_curved
            )
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_pending_visible_view_state()
        if not self._load_view_applied:
            QtCore.QTimer.singleShot(0, self._finalize_page_load_if_ready)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_pending_visible_view_state()
        if (
            self._load_waiting_for_visibility
            and not self._load_view_applied
            and self.isVisible()
            and self.viewport().size().isValid()
        ):
            QtCore.QTimer.singleShot(0, self._finalize_page_load_if_ready)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._cancel_active_drag_interaction(restore_preview=True)
        self.reset_ctrl_held()

    def leaveEvent(self, event) -> None:
        if not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            self._cancel_active_drag_interaction(restore_preview=True)
        if self._selection_enabled and self._cursor_mode == "select":
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self._last_mouse_vp_pos = None
        self.viewport().update()
        super().leaveEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            self._set_palette_background()
