from __future__ import annotations
import logging
import math
from typing import Callable, Optional, Sequence, Union
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QTimer, Signal
from ...domain.entities.identity_refs import BidRef
from ..actions.action_ids import ACTION_SHOW_ORIGINAL_IMAGE, ACTION_SHOW_OVERLAY_IMAGE
from ..config import RIGHT_CLICK_CONTEXT_MENU_MAX_MS
from ..managers.context_menu_manager import ContextMenuManager
from ..modes.cursor import CURSOR_MODE_DEFAULT, CURSOR_MODE_PAN, CURSOR_MODE_ZOOM
from ..utils.overlay_context_menu import resolve_overlay_menu_action
from ..utils.theme import set_palette_background
from ..utils.view_context_menu import (
    SelectedTakeoffContextState,
    add_common_context_submenus,
    add_context_clipboard_actions,
    add_context_command,
    add_context_page_actions,
    add_reassign_condition_submenu,
)
from ..visualization.native_page_plane import NativePageImagePlaneData
from . import ost_renderer

logger = logging.getLogger(__name__)
_CLICK_DRAG_THRESHOLD_PX = 3
_ZOOM_CLICK_WHEEL_DELTA = 120


class OpenGLViewer(QtWidgets.QWidget):
    zoom_changed = Signal(float)
    mesh_clicked = Signal(list)
    elements_deleted = Signal(list)
    assign_to_area_requested = Signal(list)
    reassign_condition_requested = Signal(list, str)
    set_negative_requested = Signal(list, bool)
    set_curved_requested = Signal(list, bool)
    overlay_display_mode_requested = Signal(int)

    def __init__(self, parent: QtWidgets.QWidget | None, color_service) -> None:
        super().__init__(parent)
        self._destroyed = False
        self._renderer: ost_renderer.Renderer | None = None
        self._pending_data: Optional[dict] = None
        self._current_bid_ref: Optional[BidRef] = None
        self._pending_camera_reset = False
        self._render_suspended = True
        self._color_service = color_service
        self.setAttribute(QtCore.Qt.WA_PaintOnScreen)
        self.setAttribute(QtCore.Qt.WA_DontCreateNativeAncestors)
        self.setAttribute(QtCore.Qt.WA_NativeWindow)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self._set_palette_background()
        self._last_mouse_pos: Optional[QtCore.QPoint] = None
        self._zoom_reference_distance: float = 0.0
        self._cursor_mode: str = CURSOR_MODE_DEFAULT
        self._zoom_cursor: Optional[QtGui.QCursor] = None
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._on_animation_frame)
        self._animation_timer.setInterval(0)
        self._camera_moving = False
        self._click_pos: Optional[QtCore.QPoint] = None
        self._click_threshold = _CLICK_DRAG_THRESHOLD_PX
        self._dragged = False
        self._right_button_press_pos: Optional[QtCore.QPoint] = None
        self._right_button_press_timer = QtCore.QElapsedTimer()
        self._right_button_dragged = False
        self._suppress_next_context_menu = False
        self._selected_takeoff_uids: list = []
        self._pick_enabled: bool = True
        self._negative_check_fn = lambda _uids: False
        self._curved_check_fn = lambda _uids: (False, False)
        self._selected_context_state_fn = None
        self._plan_texture_provider: Optional[
            Callable[[Optional[Sequence[float]]], Optional[NativePageImagePlaneData]]
        ] = None
        self._current_plan_texture: Optional[NativePageImagePlaneData] = None
        self._has_visible_plan_texture = False
        self._image_show_mode: int = 0
        self._context_menu_command_trigger = None
        self._context_menu_action_state = None
        self._context_menu_conditions_fn = lambda: {}
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.DefaultContextMenu)

    def paintEngine(self) -> None:
        return None

    def _start_right_context_tracking(self, pos: QtCore.QPoint) -> None:
        self._suppress_next_context_menu = False
        self._right_button_press_pos = pos
        self._right_button_press_timer.restart()
        self._right_button_dragged = False

    def _update_right_context_drag(self, pos: QtCore.QPoint) -> None:
        total = pos - self._right_button_press_pos
        if total.manhattanLength() >= QtWidgets.QApplication.startDragDistance():
            self._right_button_dragged = True
            self._suppress_next_context_menu = True

    def _finish_right_context_tracking(self) -> None:
        if (
            self._right_button_dragged
            or self._right_button_press_timer.elapsed()
            > RIGHT_CLICK_CONTEXT_MENU_MAX_MS
        ):
            self._suppress_next_context_menu = True
        self._right_button_press_pos = None
        self._right_button_dragged = False

    def _on_animation_frame(self) -> None:
        if not self._renderer:
            self._animation_timer.stop()
            return
        has_velocity = self._renderer.camera.has_velocity()
        if not self._camera_moving and not has_velocity:
            self._animation_timer.stop()
            return
        self.update()

    def _ensure_renderer(self) -> bool:
        if self._renderer is not None:
            return True
        if not self.winId():
            return False
        try:
            self._renderer = ost_renderer.Renderer(int(self.winId()))
            self._renderer.resize(self.width(), self.height())
            self._set_palette_background()
            self._renderer.suspend()
            if self._pending_camera_reset:
                self._renderer.camera.reset()
                self._pending_camera_reset = False
            return True
        except Exception:
            logger.exception("Failed to initialize ost_renderer")
            return False

    def paintEvent(self, event: QtGui.QPaintEvent | None = None) -> None:
        if self._ensure_renderer():
            self._renderer.render()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._renderer:
            self._renderer.resize(self.width(), self.height())

    def refresh_viewport(self) -> None:
        if self._renderer:
            self._renderer.resize(self.width(), self.height())
            if self._render_suspended:
                self._renderer.clear_frame()
        self.update()

    def set_zoom_cursor(self, cursor: QtGui.QCursor) -> None:
        self._zoom_cursor = cursor

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.setFocus(QtCore.Qt.FocusReason.MouseFocusReason)
        if self._cursor_mode == CURSOR_MODE_ZOOM and self._renderer:
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                self._start_right_context_tracking(event.pos())
            if event.button() == QtCore.Qt.MouseButton.MiddleButton:
                self._last_mouse_pos = event.pos()
                self._camera_moving = True
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                if not self._animation_timer.isActive():
                    self._animation_timer.start()
            else:
                delta = (
                    _ZOOM_CLICK_WHEEL_DELTA
                    if event.button() == QtCore.Qt.MouseButton.LeftButton
                    else -_ZOOM_CLICK_WHEEL_DELTA
                )
                self._renderer.camera.zoom(delta)
                if self._zoom_reference_distance > 1e-6:
                    dist = self._get_camera_distance()
                    self.zoom_changed.emit(self._zoom_reference_distance / dist)
                self.update()
            event.accept()
            return
        self._last_mouse_pos = event.pos()
        self._click_pos = event.pos()
        self._dragged = False
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._start_right_context_tracking(event.pos())
        self._camera_moving = True
        if self._cursor_mode == CURSOR_MODE_PAN:
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
        if not self._animation_timer.isActive():
            self._animation_timer.start()
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._cursor_mode == CURSOR_MODE_ZOOM:
            if event.button() == QtCore.Qt.MouseButton.RightButton:
                self._finish_right_context_tracking()
            if event.button() == QtCore.Qt.MouseButton.MiddleButton:
                self._last_mouse_pos = None
                self._camera_moving = False
                if self._zoom_cursor:
                    self.setCursor(self._zoom_cursor)
            event.accept()
            return
        if (
            self._click_pos is not None
            and not self._dragged
            and self._renderer
            and event.button() == QtCore.Qt.MouseButton.LeftButton
        ):
            ctrl = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier)
            self._handle_pick(event.pos(), ctrl)
        self._click_pos = None
        self._last_mouse_pos = None
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self._finish_right_context_tracking()
        self._camera_moving = False
        if self._cursor_mode == CURSOR_MODE_PAN:
            self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._cursor_mode == CURSOR_MODE_ZOOM:
            if event.buttons() & QtCore.Qt.RightButton:
                self._update_right_context_drag(event.pos())
            if (
                self._last_mouse_pos is not None
                and self._renderer
                and event.buttons() & QtCore.Qt.MiddleButton
            ):
                delta = event.pos() - self._last_mouse_pos
                self._renderer.camera.pan(delta.x(), delta.y())
                self._last_mouse_pos = event.pos()
                self.update()
            event.accept()
            return
        if self._last_mouse_pos is None or not self._renderer:
            event.ignore()
            return
        if self._click_pos is not None and not self._dragged:
            total = event.pos() - self._click_pos
            if (
                abs(total.x()) > self._click_threshold
                or abs(total.y()) > self._click_threshold
            ):
                self._dragged = True
        if event.buttons() & QtCore.Qt.RightButton:
            self._update_right_context_drag(event.pos())
        delta = event.pos() - self._last_mouse_pos
        if self._cursor_mode == CURSOR_MODE_PAN:
            if event.buttons() & QtCore.Qt.LeftButton:
                self._renderer.camera.pan(delta.x(), delta.y())
            elif event.buttons() & QtCore.Qt.RightButton:
                self._renderer.camera.rotate(delta.x(), delta.y())
        else:
            if event.buttons() & QtCore.Qt.LeftButton:
                self._renderer.camera.rotate(delta.x(), delta.y())
            elif event.buttons() & QtCore.Qt.RightButton:
                self._renderer.camera.pan(delta.x(), delta.y())
        self._last_mouse_pos = event.pos()
        self.update()
        event.accept()

    def set_pick_enabled(self, enabled: bool) -> None:
        self._pick_enabled = enabled

    def _handle_pick(self, pos: QtCore.QPoint, ctrl: bool) -> None:
        if not self._renderer or not self._pick_enabled:
            return
        dpr = self.devicePixelRatioF()
        px, py = int(pos.x() * dpr), int(pos.y() * dpr)
        mesh_idx = self._renderer.pick(px, py)
        scene = self._renderer.scene
        if mesh_idx < 0 or mesh_idx >= scene.mesh_count():
            if not ctrl:
                scene.clear_selection()
                self._selected_takeoff_uids = []
                self.mesh_clicked.emit([])
                self.update()
            return
        cond_uid = scene.get_condition_uid(mesh_idx)
        tk_uid = scene.get_takeoff_uid(mesh_idx)
        if ctrl and tk_uid:
            if tk_uid in self._selected_takeoff_uids:
                self._selected_takeoff_uids.remove(tk_uid)
                for i in range(scene.mesh_count()):
                    if scene.get_takeoff_uid(i) == tk_uid:
                        scene.set_selected(i, False)
            else:
                self._selected_takeoff_uids.append(tk_uid)
                for i in range(scene.mesh_count()):
                    if scene.get_takeoff_uid(i) == tk_uid:
                        scene.set_selected(i, True)
        else:
            scene.clear_selection()
            selected_uids = []
            for i in range(scene.mesh_count()):
                if tk_uid:
                    if scene.get_takeoff_uid(i) == tk_uid:
                        scene.set_selected(i, True)
                        if tk_uid not in selected_uids:
                            selected_uids.append(tk_uid)
                elif cond_uid:
                    if scene.get_condition_uid(i) == cond_uid:
                        scene.set_selected(i, True)
                        uid = scene.get_takeoff_uid(i)
                        if uid and uid not in selected_uids:
                            selected_uids.append(uid)
            self._selected_takeoff_uids = selected_uids
        self.mesh_clicked.emit(list(self._selected_takeoff_uids))
        self.update()

    def set_selected_takeoffs(self, takeoff_uids: list) -> None:
        self._selected_takeoff_uids = list(takeoff_uids)
        if not self._renderer:
            return
        scene = self._renderer.scene
        scene.clear_selection()
        if not takeoff_uids:
            self.update()
            return
        uid_set = set(takeoff_uids)
        for i in range(scene.mesh_count()):
            if scene.get_takeoff_uid(i) in uid_set:
                scene.set_selected(i, True)
        self.update()

    def get_selected_takeoff_uids(self) -> list:
        return list(self._selected_takeoff_uids)

    def _reconcile_selected_takeoffs_with_scene(self) -> None:
        if not self._renderer:
            return
        scene = self._renderer.scene
        available_uids = {
            uid for i in range(scene.mesh_count()) if (uid := scene.get_takeoff_uid(i))
        }
        reconciled = [
            uid for uid in self._selected_takeoff_uids if uid in available_uids
        ]
        self._selected_takeoff_uids = reconciled
        scene.clear_selection()
        if reconciled:
            uid_set = set(reconciled)
            for i in range(scene.mesh_count()):
                if scene.get_takeoff_uid(i) in uid_set:
                    scene.set_selected(i, True)

    def set_negative_check_fn(self, fn) -> None:
        self._negative_check_fn = fn

    def set_curved_check_fn(self, fn) -> None:
        self._curved_check_fn = fn

    def set_selected_context_state_fn(self, fn) -> None:
        self._selected_context_state_fn = fn

    def set_overlay_display_mode(self, mode: int) -> None:
        self._image_show_mode = int(mode)

    def set_context_menu_command_handlers(self, trigger_fn, action_state_fn) -> None:
        self._context_menu_command_trigger = trigger_fn
        self._context_menu_action_state = action_state_fn

    def set_context_menu_conditions_fn(self, fn) -> None:
        self._context_menu_conditions_fn = fn or (lambda: {})

    def set_cursor_mode(self, mode: str) -> None:
        self._cursor_mode = mode
        if mode == CURSOR_MODE_ZOOM and self._zoom_cursor:
            self.setCursor(self._zoom_cursor)
        elif mode == CURSOR_MODE_PAN:
            self.setCursor(QtCore.Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if (
            self._pick_enabled
            and self._selected_takeoff_uids
            and event.key() == QtCore.Qt.Key.Key_Delete
        ):
            uids = list(self._selected_takeoff_uids)
            self._selected_takeoff_uids = []
            if self._renderer:
                self._renderer.scene.clear_selection()
                self.update()
            self.elements_deleted.emit(uids)
            event.accept()
            return
        super().keyPressEvent(event)

    def _trigger_context_command(self, action_key: str) -> None:
        if self._context_menu_command_trigger:
            self._context_menu_command_trigger(action_key)

    def _add_context_command(
        self, menu: QtWidgets.QMenu, label: str, action_key: str
    ) -> None:
        add_context_command(
            menu,
            label,
            action_key,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )

    def _add_common_context_submenus(self, menu: QtWidgets.QMenu):
        return add_common_context_submenus(
            menu,
            self._image_show_mode,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )

    def _add_context_clipboard_actions(self, menu: QtWidgets.QMenu) -> None:
        add_context_clipboard_actions(
            menu,
            self._context_menu_command_trigger,
            self._context_menu_action_state,
        )

    def _add_context_page_actions(
        self, menu: QtWidgets.QMenu, separate_delete: bool = False
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
        overlay_action,
        original_action,
    ) -> bool:
        overlay_mode = resolve_overlay_menu_action(
            action,
            self._image_show_mode,
            overlay_action,
            original_action,
        )
        if overlay_mode is None:
            return False
        if overlay_mode != self._image_show_mode:
            command_key = (
                ACTION_SHOW_OVERLAY_IMAGE
                if action == overlay_action
                else ACTION_SHOW_ORIGINAL_IMAGE
            )
            if self._context_menu_command_trigger:
                self._trigger_context_command(command_key)
            else:
                self.overlay_display_mode_requested.emit(overlay_mode)
        return True

    def _selected_takeoff_context_state(self) -> SelectedTakeoffContextState:
        if self._selected_context_state_fn:
            state = self._selected_context_state_fn(list(self._selected_takeoff_uids))
            if state is not None:
                return state
        all_negative = self._negative_check_fn(self._selected_takeoff_uids)
        all_linear, all_curved = self._curved_check_fn(self._selected_takeoff_uids)
        return SelectedTakeoffContextState(
            takeoff_uids=list(self._selected_takeoff_uids),
            show_assign=bool(self._selected_takeoff_uids),
            show_negative=bool(self._selected_takeoff_uids),
            show_curved=all_linear,
            all_negative=all_negative,
            all_curved=all_curved,
        )

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        if self._suppress_next_context_menu:
            self._suppress_next_context_menu = False
            event.accept()
            return
        menu = QtWidgets.QMenu(self)
        selected_state = (
            self._selected_takeoff_context_state()
            if self._pick_enabled and self._selected_takeoff_uids
            else None
        )
        has_selected_takeoffs = bool(selected_state and selected_state.takeoff_uids)
        assign_action = None
        negative_action = None
        curved_action = None
        reassign_condition_menu = None
        if has_selected_takeoffs:
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
        overlay_action, original_action = self._add_common_context_submenus(menu)
        if has_selected_takeoffs:
            if selected_state.reassign_geometry_type is not None:
                reassign_condition_menu = add_reassign_condition_submenu(
                    menu,
                    dict(self._context_menu_conditions_fn() or {}),
                    selected_state.reassign_geometry_type,
                )
        menu.addSeparator()
        if has_selected_takeoffs:
            self._add_context_clipboard_actions(menu)
            menu.addSeparator()
            self._add_context_page_actions(menu)
        else:
            self._add_context_command(menu, "Paste", "paste")
            menu.addSeparator()
            self._add_context_page_actions(menu, separate_delete=True)
        action = menu.exec(event.globalPos())
        if action is None:
            event.accept()
            return
        if self._resolve_context_overlay_action(
            action, overlay_action, original_action
        ):
            event.accept()
            return
        if not has_selected_takeoffs:
            event.accept()
            return
        if reassign_condition_menu and action in reassign_condition_menu.actions:
            self.reassign_condition_requested.emit(
                list(self._selected_takeoff_uids),
                reassign_condition_menu.actions[action],
            )
        elif action == assign_action:
            self.assign_to_area_requested.emit(list(self._selected_takeoff_uids))
        elif action == negative_action:
            self.set_negative_requested.emit(
                list(self._selected_takeoff_uids), not selected_state.all_negative
            )
        elif curved_action and action == curved_action:
            self.set_curved_requested.emit(
                list(self._selected_takeoff_uids), not selected_state.all_curved
            )
        event.accept()

    def _get_camera_distance(self) -> float:
        pos = self._renderer.camera.position
        tgt = self._renderer.camera.target
        dx, dy, dz = pos.x - tgt.x, pos.y - tgt.y, pos.z - tgt.z
        return math.sqrt(dx * dx + dy * dy + dz * dz)

    def get_zoom_percent(self) -> float:
        if not self._renderer or self._zoom_reference_distance < 1e-6:
            return 100.0
        dist = self._get_camera_distance()
        if dist < 1e-6:
            return 100.0
        return self._zoom_reference_distance / dist * 100.0

    def reset_view(self) -> None:
        if not self._renderer:
            return
        bounds = self._current_view_bounds()
        if bounds is None:
            return
        self._renderer.camera.show_object(bounds)
        self._zoom_reference_distance = self._get_camera_distance()
        self.zoom_changed.emit(1.0)
        self.update()

    def set_zoom_percent(self, percent: float) -> None:
        if not self._renderer or self._zoom_reference_distance < 1e-6 or percent < 1e-6:
            return
        target_dist = self._zoom_reference_distance / (percent / 100.0)
        current_dist = self._get_camera_distance()
        if current_dist < 1e-6:
            return
        pos = self._renderer.camera.position
        tgt = self._renderer.camera.target
        dx = (pos.x - tgt.x) / current_dist
        dy = (pos.y - tgt.y) / current_dist
        dz = (pos.z - tgt.z) / current_dist
        self._renderer.camera.position = ost_renderer.Vec3(
            tgt.x + dx * target_dist,
            tgt.y + dy * target_dist,
            tgt.z + dz * target_dist,
        )
        self.update()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if not self._renderer or not self.isVisible():
            event.ignore()
            return
        self._renderer.camera.zoom(event.angleDelta().y())
        if self._zoom_reference_distance > 1e-6:
            dist = self._get_camera_distance()
            self.zoom_changed.emit(self._zoom_reference_distance / dist)
        self.update()
        event.accept()

    def set_background_color(self, color: Union[QtGui.QColor, Sequence[float]]) -> None:
        if isinstance(color, QtGui.QColor):
            r, g, b, a = color.getRgbF()
        else:
            vals = list(color)
            r, g, b, a = vals[:4] if len(vals) >= 4 else (*vals[:3], 1.0)
        if self._renderer:
            self._renderer.set_background_color(r, g, b, a)
            if self._render_suspended:
                self._renderer.clear_frame()
        self.update()

    def suspend_rendering(self) -> None:
        self._render_suspended = True
        self._pending_data = None
        if self._renderer:
            self._renderer.suspend()

    def resume_rendering(self) -> None:
        if not self._has_renderable_content():
            return
        self._render_suspended = False
        self._renderer.resume()
        self.update()

    def set_plan_texture_provider(
        self,
        provider: Optional[
            Callable[[Optional[Sequence[float]]], Optional[NativePageImagePlaneData]]
        ],
    ) -> None:
        self._plan_texture_provider = provider

    def set_plan_texture_visibility(self, visible: bool) -> None:
        if not self._renderer or self._current_plan_texture is None:
            return
        self._renderer.set_plan_texture_visibility(bool(visible))
        self._has_visible_plan_texture = bool(visible)
        self._update_after_plan_texture_change()

    def update_plan_texture(self) -> None:
        if not self._renderer:
            return
        scene_bounds = None
        if not self._renderer.scene.empty():
            bounds = self._renderer.scene.get_bounds()
            scene_bounds = (
                bounds.min.x,
                bounds.max.x,
                bounds.min.y,
                bounds.max.y,
                bounds.min.z,
                bounds.max.z,
            )
        self._replace_plan_texture(scene_bounds)
        self._update_after_plan_texture_change()

    def apply_mesh_data(
        self,
        vertices_list: Sequence[Sequence[float]],
        normals_list: Sequence[Sequence[float]],
        indices_list: Sequence[Sequence[int]],
        colors: Sequence[object],
        bid_ref: Optional[BidRef] = None,
        condition_uids: Optional[Sequence[str]] = None,
        takeoff_uids: Optional[Sequence[str]] = None,
        scene_bounds: Optional[Sequence[float]] = None,
    ) -> None:
        if QtCore.QThread.currentThread() != self.thread():
            self._validate_mesh_buffer_lengths(
                vertices_list,
                normals_list,
                indices_list,
                colors,
                condition_uids,
                takeoff_uids,
            )
            self._pending_data = {
                "vertices": vertices_list,
                "normals": normals_list,
                "indices": indices_list,
                "colors": colors,
                "bid_ref": bid_ref,
                "condition_uids": condition_uids,
                "takeoff_uids": takeoff_uids,
                "scene_bounds": scene_bounds,
            }
            QtCore.QMetaObject.invokeMethod(
                self, "_apply_pending", QtCore.Qt.QueuedConnection
            )
            return
        self._do_apply_mesh_data(
            vertices_list,
            normals_list,
            indices_list,
            colors,
            bid_ref,
            condition_uids,
            takeoff_uids,
            scene_bounds,
        )

    @staticmethod
    def _validate_mesh_buffer_lengths(
        vertices_list: Sequence[Sequence[float]],
        normals_list: Sequence[Sequence[float]],
        indices_list: Sequence[Sequence[int]],
        colors: Sequence[object],
        condition_uids: Optional[Sequence[str]] = None,
        takeoff_uids: Optional[Sequence[str]] = None,
    ) -> None:
        expected = len(vertices_list)
        lengths = {
            "normals": len(normals_list),
            "indices": len(indices_list),
            "colors": len(colors),
        }
        if condition_uids is not None:
            lengths["condition_uids"] = len(condition_uids)
        if takeoff_uids is not None:
            lengths["takeoff_uids"] = len(takeoff_uids)
        mismatched = {
            name: length for name, length in lengths.items() if length != expected
        }
        if mismatched:
            raise ValueError(
                "Mesh render buffers must have matching lengths: "
                f"vertices={expected}, "
                + ", ".join(f"{name}={length}" for name, length in mismatched.items())
            )

    @QtCore.Slot()
    def _apply_pending(self) -> None:
        if self._pending_data is None:
            return
        data = self._pending_data
        self._pending_data = None
        self._do_apply_mesh_data(
            data["vertices"],
            data["normals"],
            data["indices"],
            data["colors"],
            data["bid_ref"],
            data.get("condition_uids"),
            data.get("takeoff_uids"),
            data.get("scene_bounds"),
        )

    def _do_apply_mesh_data(
        self,
        vertices_list: Sequence[Sequence[float]],
        normals_list: Sequence[Sequence[float]],
        indices_list: Sequence[Sequence[int]],
        colors: Sequence[object],
        bid_ref: Optional[BidRef] = None,
        condition_uids: Optional[Sequence[str]] = None,
        takeoff_uids: Optional[Sequence[str]] = None,
        scene_bounds: Optional[Sequence[float]] = None,
    ) -> None:
        self._validate_mesh_buffer_lengths(
            vertices_list,
            normals_list,
            indices_list,
            colors,
            condition_uids,
            takeoff_uids,
        )
        if not self._ensure_renderer():
            return
        is_same_bid = bid_ref is not None and bid_ref == self._current_bid_ref
        is_new_bid = bid_ref is not None and bid_ref != self._current_bid_ref
        if not is_same_bid:
            self.suspend_rendering()
        self._current_bid_ref = bid_ref
        if is_new_bid:
            self._selected_takeoff_uids.clear()
        meshes = []
        for i, (verts, norms, idxs, color) in enumerate(
            zip(vertices_list, normals_list, indices_list, colors)
        ):
            if not verts or not idxs:
                continue
            mesh = ost_renderer.MeshData()
            mesh.set_vertices(verts)
            mesh.set_normals(norms)
            mesh.indices = idxs
            r, g, b, a = self._color_service.convert_to_rgba(color)
            mesh.color = ost_renderer.Color(r, g, b, a)
            if condition_uids and i < len(condition_uids):
                mesh.condition_uid = condition_uids[i]
            if takeoff_uids and i < len(takeoff_uids):
                mesh.takeoff_uid = takeoff_uids[i]
            meshes.append(mesh)
        self._renderer.scene.clear()
        for mesh in meshes:
            self._renderer.scene.add_mesh(mesh)
        self._replace_plan_texture(scene_bounds)
        self._reconcile_selected_takeoffs_with_scene()
        if not self._has_renderable_content():
            if not is_same_bid:
                self._renderer.camera.reset()
            self._renderer.suspend()
            self._render_suspended = True
            self.update()
            return
        if is_same_bid:
            if self._render_suspended:
                self.resume_rendering()
            else:
                self.update()
            return
        if is_new_bid:
            bounds = self._current_view_bounds()
            if bounds is not None:
                self._renderer.camera.show_object(bounds)
            self._zoom_reference_distance = self._get_camera_distance()
            self.zoom_changed.emit(1.0)
        self.resume_rendering()

    def _replace_plan_texture(self, scene_bounds: Optional[Sequence[float]]) -> None:
        self._current_plan_texture = None
        self._has_visible_plan_texture = False
        if not self._plan_texture_provider:
            self._renderer.clear_plan_texture()
            return
        data = self._plan_texture_provider(scene_bounds)
        if data is None:
            self._renderer.clear_plan_texture()
            return
        self._renderer.set_plan_texture(
            data.pixels_rgba,
            data.width_px,
            data.height_px,
            data.page_width,
            data.page_height,
            data.plane_x,
            data.plane_y,
            data.plane_z,
            data.opacity,
            data.visible,
            data.flip_u,
            data.flip_v,
        )
        self._current_plan_texture = data
        self._has_visible_plan_texture = bool(data.visible)

    def _has_renderable_content(self) -> bool:
        return bool(
            self._renderer
            and (not self._renderer.scene.empty() or self._has_visible_plan_texture)
        )

    def _update_after_plan_texture_change(self) -> None:
        if not self._has_renderable_content():
            self._renderer.suspend()
            self._render_suspended = True
            self.update()
            return
        if self._render_suspended:
            self.resume_rendering()
        else:
            self.update()

    def _current_view_bounds(self):
        if not self._renderer:
            return None
        has_scene = not self._renderer.scene.empty()
        has_plan = (
            self._has_visible_plan_texture and self._current_plan_texture is not None
        )
        if not has_scene and not has_plan:
            return None
        if has_scene:
            bounds = self._renderer.scene.get_bounds()
        else:
            bounds = ost_renderer.Box3()
        if has_plan:
            plan = self._current_plan_texture
            padding = max(max(plan.page_width, plan.page_height) * 0.001, 0.05)
            min_x = plan.plane_x - plan.page_width * 0.5
            max_x = plan.plane_x + plan.page_width * 0.5
            min_y = plan.plane_y - plan.page_height * 0.5
            max_y = plan.plane_y + plan.page_height * 0.5
            min_z = plan.plane_z - padding
            max_z = plan.plane_z + padding
            if bounds.is_empty():
                bounds.min = ost_renderer.Vec3(min_x, min_y, min_z)
                bounds.max = ost_renderer.Vec3(max_x, max_y, max_z)
            else:
                bounds.min = ost_renderer.Vec3(
                    min(bounds.min.x, min_x),
                    min(bounds.min.y, min_y),
                    min(bounds.min.z, min_z),
                )
                bounds.max = ost_renderer.Vec3(
                    max(bounds.max.x, max_x),
                    max(bounds.max.y, max_y),
                    max(bounds.max.z, max_z),
                )
        return bounds

    def clear_scene(self) -> None:
        self._pending_data = None
        if QtCore.QThread.currentThread() != self.thread():
            QtCore.QMetaObject.invokeMethod(
                self, "_do_clear", QtCore.Qt.QueuedConnection
            )
            return
        self._do_clear()

    @QtCore.Slot()
    def _do_clear(self) -> None:
        self._zoom_reference_distance = 0.0
        self._selected_takeoff_uids = []
        self._current_bid_ref = None
        if self._renderer:
            self._renderer.scene.clear()
            self._renderer.clear_plan_texture()
            self._renderer.camera.reset()
            self._renderer.suspend()
        else:
            self._pending_camera_reset = True
        self._current_plan_texture = None
        self._has_visible_plan_texture = False
        self._render_suspended = True
        self.update()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if not self._ensure_renderer():
            return
        if not self._has_renderable_content():
            self._render_suspended = True
            self._renderer.suspend()
            return
        self._render_suspended = False
        self._renderer.resume()
        self._renderer.render()

    def hideEvent(self, event: QtGui.QHideEvent) -> None:
        if self._renderer:
            self._renderer.suspend()
        super().hideEvent(event)

    def cleanup(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._pending_data = None
        self._current_bid_ref = None
        self._pending_camera_reset = False
        self._render_suspended = True
        self._negative_check_fn = lambda _uids: False
        self._curved_check_fn = lambda _uids: (False, False)
        self._selected_context_state_fn = None
        self._plan_texture_provider = None
        self._current_plan_texture = None
        self._has_visible_plan_texture = False
        self._context_menu_command_trigger = None
        self._context_menu_action_state = None
        self._context_menu_conditions_fn = lambda: {}
        self._zoom_cursor = None
        if self._animation_timer:
            self._animation_timer.stop()
            self._animation_timer.timeout.disconnect(self._on_animation_frame)
            self._animation_timer.deleteLater()
            self._animation_timer = None
        if self._renderer is not None:
            self._renderer.shutdown()
            self._renderer = None

    def closeEvent(self, event: QtCore.QEvent) -> None:
        self.cleanup()
        super().closeEvent(event)

    def destroy(
        self, destroyWindow: bool = True, destroySubWindows: bool = True
    ) -> None:
        self.cleanup()
        super().destroy(destroyWindow, destroySubWindows)

    def _set_palette_background(self) -> None:
        set_palette_background(self, lambda c: self.set_background_color(c))

    def changeEvent(self, event: QtCore.QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QtCore.QEvent.Type.PaletteChange:
            self._set_palette_background()
