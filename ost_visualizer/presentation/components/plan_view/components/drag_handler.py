import math
from typing import List, Optional, Tuple
from PySide6 import QtCore
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)
from .....domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_OVAL,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)
from ....visualization.core.geometry.takeoff_geometry import compute_line_angle
from ....visualization.pdf.renderers.annotation_item_renderer import (
    DIMENSION_FONT_SIZE_ADJUSTMENT,
    build_dimension_path,
    create_dimension_text_item,
    update_dimension_text_item,
)
from ....visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_geometry,
    create_cloud_path_points,
)
from .geometry_utils import polygon_is_valid, signed_area
from .graphics_items import ClippedTextGraphicsItem


def _line_line_intersect(
    p1x: float,
    p1y: float,
    d1x: float,
    d1y: float,
    p2x: float,
    p2y: float,
    d2x: float,
    d2y: float,
) -> Optional[Tuple[float, float]]:
    det = d1x * d2y - d1y * d2x
    if abs(det) < 1e-12:
        return None
    t = ((p2x - p1x) * d2y - (p2y - p1y) * d2x) / det
    return p1x + d1x * t, p1y + d1y * t


class DragHandlerMixin:
    def _build_area_annotation_path(
        self, annotation_type: str, area_pts: List[Tuple[float, float]]
    ) -> QPainterPath:
        path = QPainterPath()
        if not area_pts:
            return path
        if annotation_type == ANNOTATION_TYPE_CLOUD and len(area_pts) >= 3:
            segments = create_cloud_path_points(area_pts)
            for idx, (_start, cp1, cp2, end) in enumerate(segments):
                if idx == 0:
                    path.moveTo(area_pts[0][0], area_pts[0][1])
                path.cubicTo(cp1[0], cp1[1], cp2[0], cp2[1], end[0], end[1])
            path.closeSubpath()
            return path
        path.moveTo(area_pts[0][0], area_pts[0][1])
        for px, py in area_pts[1:]:
            path.lineTo(px, py)
        if len(area_pts) >= 3:
            path.closeSubpath()
        return path

    def _polygon_edit_geometry_valid(
        self, new_pos: List[float], area_pts: List[Tuple[float, float]]
    ) -> bool:
        if len(area_pts) < 3 or not polygon_is_valid(area_pts):
            return False
        if self._drag_last_valid_new_pos:
            orig_sign = signed_area(self._drag_last_valid_new_pos)
            new_sign = signed_area(new_pos)
            if orig_sign and new_sign and (orig_sign > 0) != (new_sign > 0):
                return False
        return True

    def _update_dimension_preview_items(self, ann, uid: str, new_pos, cs) -> None:
        dimension = calculate_dimension_geometry(
            ann, new_pos, cs.transform_vertices_to_2d
        )
        if not dimension:
            return
        items = self._uid_to_items.get(uid, [])
        if not items or not isinstance(items[0], QGraphicsPathItem):
            return
        path_item = items[0]
        path_item.setPos(0.0, 0.0)
        path_item.setPath(build_dimension_path(dimension, cs))
        text_item = None
        for item in items[1:]:
            if isinstance(item, QGraphicsTextItem):
                text_item = item
                break
        if text_item is None:
            text_item = create_dimension_text_item(
                dimension,
                ann.color,
                cs,
                DIMENSION_FONT_SIZE_ADJUSTMENT,
            )
            if text_item is None:
                return
            text_item.setData(0, uid)
            transform = self._current_page_transform()
            if transform is not None:
                text_item.setTransform(transform)
            self._scene.addItem(text_item)
            items.append(text_item)
            if text_item not in self._takeoff_items:
                self._takeoff_items.append(text_item)
        else:
            update_dimension_text_item(
                text_item,
                dimension,
                ann.color,
                cs,
                DIMENSION_FONT_SIZE_ADJUSTMENT,
            )

    def _drag_preview_color_for_takeoff(self, takeoff, condition):
        return self._color_service.get_2d_color_for_takeoff(
            takeoff,
            condition,
            self._current_color_map,
            self._current_page_area_selections,
        )

    def _refresh_takeoff_pattern_preview(
        self,
        uid: str,
        path_item: QGraphicsPathItem,
        path: QPainterPath,
        condition,
        pattern_angle: float | None = None,
    ) -> None:
        color_hex, opacity = self._drag_preview_color_for_takeoff(
            self._current_takeoffs[uid], condition
        )
        qcolor = QColor(color_hex)
        pattern_type = condition.pattern if condition.pattern else 1
        spacing = condition.spacing if condition.spacing else 4.0
        fill_brush, pattern_items = self._scene_builder.build_pattern_fill(
            path, pattern_type, qcolor, opacity, spacing, 2.0, pattern_angle
        )
        border_pen = QPen(qcolor)
        border_pen.setWidthF(2.0)
        border_pen.setCosmetic(True)
        path_item.setPen(border_pen)
        path_item.setBrush(
            fill_brush if fill_brush is not None else QBrush(Qt.BrushStyle.NoBrush)
        )
        existing_items = list(self._uid_to_items.get(uid, []))
        preserved_items: List = []
        for item in existing_items[1:]:
            is_pattern_line = (
                isinstance(item, QGraphicsPathItem)
                and item.brush().style() == Qt.BrushStyle.NoBrush
            )
            if is_pattern_line:
                if item.scene() is self._scene:
                    self._scene.removeItem(item)
                if item in self._takeoff_items:
                    self._takeoff_items.remove(item)
            else:
                preserved_items.append(item)
        transform = self._current_page_transform()
        if transform is None:
            transform = path_item.transform()
        new_items: List = [path_item]
        for pattern_item in pattern_items:
            pattern_item.setData(0, uid)
            pattern_item.setData(1, condition.uid)
            pattern_item.setZValue(path_item.zValue())
            pattern_item.setVisible(path_item.isVisible())
            pattern_item.setTransform(transform)
            self._scene.addItem(pattern_item)
            if pattern_item not in self._takeoff_items:
                self._takeoff_items.append(pattern_item)
            new_items.append(pattern_item)
        new_items.extend(preserved_items)
        self._uid_to_items[uid] = new_items

    def _apply_hole_cutout_preview_style(
        self, uid: str, path_item: QGraphicsPathItem, path: QPainterPath
    ) -> None:
        path_item.setPos(0.0, 0.0)
        path_item.setPath(path)
        path_item.setPen(QPen(Qt.PenStyle.NoPen))
        path_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        existing_items = list(self._uid_to_items.get(uid, []))
        preserved_items: List = []
        for item in existing_items[1:]:
            if isinstance(item, QGraphicsPathItem):
                if item.scene() is self._scene:
                    self._scene.removeItem(item)
                if item in self._takeoff_items:
                    self._takeoff_items.remove(item)
            else:
                preserved_items.append(item)
        self._uid_to_items[uid] = [path_item, *preserved_items]

    def scene_to_ost_delta(self, dx: float, dy: float) -> Tuple[float, float]:
        cs = self._scene_builder.get_coordinate_system()
        factor = cs.scale_ratio / (72.0 * cs.view_scale)
        transform = self._current_page_transform()
        if transform is not None:
            inv, ok = transform.inverted()
            if ok:
                origin = inv.map(QtCore.QPointF(0.0, 0.0))
                mapped = inv.map(QtCore.QPointF(dx, dy))
                dx = mapped.x() - origin.x()
                dy = mapped.y() - origin.y()
        return dx * factor, dy * factor

    def ost_to_scene_delta(self, ost_dx: float, ost_dy: float) -> Tuple[float, float]:
        cs = self._scene_builder.get_coordinate_system()
        inv_factor = 72.0 * cs.view_scale / cs.scale_ratio
        sdx = ost_dx * inv_factor
        sdy = ost_dy * inv_factor
        transform = self._current_page_transform()
        if transform is not None:
            origin = transform.map(QtCore.QPointF(0.0, 0.0))
            mapped = transform.map(QtCore.QPointF(sdx, sdy))
            sdx = mapped.x() - origin.x()
            sdy = mapped.y() - origin.y()
        return sdx, sdy

    def snap_ost(self, val: float) -> float:
        if self._snap_increments <= 0:
            return val
        return round(val / self._snap_increments) * self._snap_increments

    def compute_new_position(
        self,
        orig_pos: List[float],
        ost_dx: float,
        ost_dy: float,
        handle_idx: int,
        corner_count: int,
        move_only_first_pair: bool = False,
        free_mode: bool = False,
    ) -> List[float]:
        pos = list(orig_pos)
        n_pairs = len(pos) // 2
        if handle_idx == -1:
            snapped_dx = self.snap_ost(pos[0] + ost_dx) - pos[0]
            snapped_dy = self.snap_ost(pos[1] + ost_dy) - pos[1]
            limit = 2 if move_only_first_pair else len(pos) - 1
            for i in range(0, limit, 2):
                pos[i] = pos[i] + snapped_dx
                pos[i + 1] = pos[i + 1] + snapped_dy
        elif corner_count > 0 and handle_idx >= corner_count:
            edge_i = handle_idx - corner_count
            ci0 = edge_i
            ci1 = (edge_i + 1) % corner_count
            if free_mode or corner_count < 3:
                snapped_dx, snapped_dy = self._snap_angle(0.0, 0.0, ost_dx, ost_dy)
                pos[ci0 * 2] = self.snap_ost(pos[ci0 * 2] + snapped_dx)
                pos[ci0 * 2 + 1] = self.snap_ost(pos[ci0 * 2 + 1] + snapped_dy)
                pos[ci1 * 2] = self.snap_ost(pos[ci1 * 2] + snapped_dx)
                pos[ci1 * 2 + 1] = self.snap_ost(pos[ci1 * 2 + 1] + snapped_dy)
            else:
                pos = self._constrained_edge_resize(
                    pos, ost_dx, ost_dy, ci0, ci1, corner_count
                )
        elif handle_idx == 2 and corner_count == 0 and len(pos) >= 6:
            lx, ly = pos[2] - pos[0], pos[3] - pos[1]
            line_len = math.hypot(lx, ly)
            if line_len > 1e-9:
                dx_n, dy_n = lx / line_len, ly / line_len
                perp_x, perp_y = -dy_n, dx_n
                perp_proj = ost_dx * perp_x + ost_dy * perp_y
                mx = (pos[0] + pos[2]) * 0.5
                my = (pos[1] + pos[3]) * 0.5
                if len(pos) >= 7:
                    pos[6] = pos[6] - perp_proj
                    offset = -pos[6]
                    pos[4] = mx + perp_x * offset
                    pos[5] = my + perp_y * offset
                else:
                    pos[4] = pos[4] + perp_x * perp_proj
                    pos[5] = pos[5] + perp_y * perp_proj
        elif 0 <= handle_idx < n_pairs:
            new_x = self.snap_ost(pos[handle_idx * 2] + ost_dx)
            new_y = self.snap_ost(pos[handle_idx * 2 + 1] + ost_dy)
            if n_pairs >= 2 and corner_count == 0 and handle_idx < 2:
                other_idx = 1 - handle_idx
                ox, oy = pos[other_idx * 2], pos[other_idx * 2 + 1]
                new_x, new_y = self._snap_angle(ox, oy, new_x, new_y)
            elif corner_count > 0:
                prev_idx = (handle_idx - 1) % corner_count
                ox, oy = pos[prev_idx * 2], pos[prev_idx * 2 + 1]
                new_x, new_y = self._snap_angle(ox, oy, new_x, new_y)
            if corner_count == 0 and len(pos) >= 6 and handle_idx < 2:
                old_lx = pos[2] - pos[0]
                old_ly = pos[3] - pos[1]
                old_len = math.hypot(old_lx, old_ly)
                if old_len > 1e-9:
                    old_perp_x, old_perp_y = -old_ly / old_len, old_lx / old_len
                    old_mx = (pos[0] + pos[2]) / 2.0
                    old_my = (pos[1] + pos[3]) / 2.0
                    perp_dist = (pos[4] - old_mx) * old_perp_x + (
                        pos[5] - old_my
                    ) * old_perp_y
                else:
                    perp_dist = 0.0
                pos[handle_idx * 2] = new_x
                pos[handle_idx * 2 + 1] = new_y
                new_lx = pos[2] - pos[0]
                new_ly = pos[3] - pos[1]
                new_len = math.hypot(new_lx, new_ly)
                new_mx = (pos[0] + pos[2]) / 2.0
                new_my = (pos[1] + pos[3]) / 2.0
                if new_len > 1e-9:
                    new_perp_x, new_perp_y = -new_ly / new_len, new_lx / new_len
                    pos[4] = new_mx + new_perp_x * perp_dist
                    pos[5] = new_my + new_perp_y * perp_dist
                else:
                    pos[4] = new_mx
                    pos[5] = new_my
            else:
                pos[handle_idx * 2] = new_x
                pos[handle_idx * 2 + 1] = new_y
        return pos

    def _constrained_edge_resize(
        self,
        pos: List[float],
        ost_dx: float,
        ost_dy: float,
        ci0: int,
        ci1: int,
        corner_count: int,
    ) -> List[float]:
        ex = pos[ci1 * 2] - pos[ci0 * 2]
        ey = pos[ci1 * 2 + 1] - pos[ci0 * 2 + 1]
        edge_len = math.hypot(ex, ey)
        if edge_len < 1e-9:
            return pos
        nx = -ey / edge_len
        ny = ex / edge_len
        proj = ost_dx * nx + ost_dy * ny
        moved_c0x = pos[ci0 * 2] + nx * proj
        moved_c0y = pos[ci0 * 2 + 1] + ny * proj
        moved_c1x = pos[ci1 * 2] + nx * proj
        moved_c1y = pos[ci1 * 2 + 1] + ny * proj
        prev = (ci0 - 1) % corner_count
        nxt = (ci1 + 1) % corner_count
        new_c0 = _line_line_intersect(
            pos[prev * 2],
            pos[prev * 2 + 1],
            pos[ci0 * 2] - pos[prev * 2],
            pos[ci0 * 2 + 1] - pos[prev * 2 + 1],
            moved_c0x,
            moved_c0y,
            ex,
            ey,
        )
        new_c1 = _line_line_intersect(
            pos[nxt * 2],
            pos[nxt * 2 + 1],
            pos[ci1 * 2] - pos[nxt * 2],
            pos[ci1 * 2 + 1] - pos[nxt * 2 + 1],
            moved_c1x,
            moved_c1y,
            ex,
            ey,
        )
        if new_c0:
            pos[ci0 * 2] = self.snap_ost(new_c0[0])
            pos[ci0 * 2 + 1] = self.snap_ost(new_c0[1])
        if new_c1:
            pos[ci1 * 2] = self.snap_ost(new_c1[0])
            pos[ci1 * 2 + 1] = self.snap_ost(new_c1[1])
        return pos

    def update_drag_handle_positions(
        self,
        new_pos: List[float],
        uid: str,
        scene_dx: float = 0.0,
        scene_dy: float = 0.0,
    ) -> None:
        cs = self._scene_builder.get_coordinate_system()
        ann = self._current_annotations.get(uid)
        is_ann = ann is not None and ann.is_interactive
        if not is_ann:
            takeoff = self._current_takeoffs.get(uid)
            if not takeoff:
                return
            condition = self._current_conditions.get(takeoff.condition_uid)
            if not condition:
                return
        else:
            condition = None
        if is_ann and ann.annotation_type not in ann.LINEAR_TYPES:
            self._update_ann_drag(ann, new_pos, uid, cs, scene_dx, scene_dy)
            return
        tx = cs.transform_vertices_to_2d(new_pos)
        if not tx or len(tx) < 2:
            return
        n_h = len(self._handle_infos)
        if not n_h:
            return
        is_curved_linear = (
            not is_ann
            and condition is not None
            and condition.is_linear
            and n_h >= 3
            and len(new_pos) >= 6
        )
        if is_ann or condition.is_linear:
            if len(tx) >= 4 and n_h >= 2:
                self._handle_infos[0].item.setPos(self._pt_to_scene(tx[0], tx[1]))
                self._handle_infos[1].item.setPos(self._pt_to_scene(tx[2], tx[3]))
            if is_curved_linear and len(new_pos) >= 6:
                rx = list(new_pos[:6])
                rx[0], rx[1], rx[2], rx[3], rx[4], rx[5] = (
                    self._linear_geom.proc_curved_pos(
                        new_pos, rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]
                    )
                )
                ctrl_tx = cs.transform_vertices_to_2d(rx)
                if len(ctrl_tx) >= 6:
                    self._handle_infos[2].item.setPos(
                        self._pt_to_scene(ctrl_tx[4], ctrl_tx[5])
                    )
        elif condition.is_area:
            area_pts: List[Tuple[float, float]] = [
                (tx[i], tx[i + 1]) for i in range(0, len(tx) - 1, 2)
            ]
            is_area_vertex_drag = self._drag_handle_index >= 0 and len(tx) >= 6
            area_valid = True
            if is_area_vertex_drag:
                area_valid = self._polygon_edit_geometry_valid(new_pos, area_pts)
            if area_valid and takeoff.is_hole:
                area_valid = self._validate_hole_position(takeoff, new_pos, area_pts)
            if area_valid and not takeoff.is_hole and is_area_vertex_drag:
                area_valid = self._validate_parent_contains_holes(uid, new_pos)
            if area_valid:
                n = len(area_pts)
                for i in range(min(n, n_h)):
                    self._handle_infos[i].item.setPos(
                        self._pt_to_scene(area_pts[i][0], area_pts[i][1])
                    )
                for i in range(n):
                    mid_i = n + i
                    if mid_i < n_h:
                        p1, p2 = area_pts[i], area_pts[(i + 1) % n]
                        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
                        self._handle_infos[mid_i].item.setPos(self._pt_to_scene(mx, my))
            if area_valid:
                self._drag_last_valid_new_pos = list(new_pos)
            if is_area_vertex_drag and area_valid:
                new_path = QPainterPath()
                new_path.moveTo(area_pts[0][0], area_pts[0][1])
                for px, py in area_pts[1:]:
                    new_path.lineTo(px, py)
                new_path.closeSubpath()
                items_for_uid = self._uid_to_items.get(uid, [])
                if items_for_uid and isinstance(items_for_uid[0], QGraphicsPathItem):
                    if takeoff.is_hole:
                        self._apply_hole_cutout_preview_style(
                            uid, items_for_uid[0], new_path
                        )
                    else:
                        items_for_uid[0].setPos(0.0, 0.0)
                        items_for_uid[0].setPath(new_path)
                        self._refresh_takeoff_pattern_preview(
                            uid, items_for_uid[0], new_path, condition
                        )
                if takeoff.is_hole:
                    self._update_parent_hole_path(takeoff.parent_uid, uid, new_path)
                elif self._has_child_holes(uid):
                    self._rebuild_parent_with_holes(uid, new_path)
                else:
                    self._refresh_condition_text_labels_for_takeoff(uid)
        elif len(tx) >= 2 and n_h >= 1:
            self._handle_infos[0].item.setPos(self._pt_to_scene(tx[0], tx[1]))
        if self._drag_handle_index >= 0 and len(tx) >= 4:
            x1, y1, x2, y2 = tx[0], tx[1], tx[2], tx[3]
            items_for_uid = self._uid_to_items.get(uid, [])
            path_item = (
                items_for_uid[0]
                if items_for_uid and isinstance(items_for_uid[0], QGraphicsPathItem)
                else None
            )
            if path_item is not None:
                if is_ann:
                    if ann.is_dimension:
                        self._update_dimension_preview_items(ann, uid, new_pos, cs)
                    else:
                        new_path = QPainterPath()
                        new_path.moveTo(x1, y1)
                        new_path.lineTo(x2, y2)
                        if ann.annotation_type == ANNOTATION_TYPE_ARROW:
                            arrow_size = max(ann.width * 20, 24.0)
                            angle = math.atan2(y2 - y1, x2 - x1)
                            arrow_angle = math.radians(30)
                            lx = x2 - arrow_size * math.cos(angle - arrow_angle)
                            ly = y2 - arrow_size * math.sin(angle - arrow_angle)
                            rx = x2 - arrow_size * math.cos(angle + arrow_angle)
                            ry = y2 - arrow_size * math.sin(angle + arrow_angle)
                            new_path.moveTo(lx, ly)
                            new_path.lineTo(x2, y2)
                            new_path.lineTo(rx, ry)
                        path_item.setPos(0.0, 0.0)
                        path_item.setPath(new_path)
                elif condition.is_linear:
                    thickness_ost = condition.thickness if condition.thickness else 1.0
                    thickness_px = max(cs.ost_to_screen_pixels(thickness_ost), 2.0)
                    new_path = None
                    if is_curved_linear and len(new_pos) >= 6:
                        rx = list(new_pos[:6])
                        rx[0], rx[1], rx[2], rx[3], rx[4], rx[5] = (
                            self._linear_geom.proc_curved_pos(
                                new_pos, rx[0], rx[1], rx[2], rx[3], rx[4], rx[5]
                            )
                        )
                        ctrl_tx = cs.transform_vertices_to_2d(rx)
                        if len(ctrl_tx) >= 6:
                            cx1, cy1 = ctrl_tx[0], ctrl_tx[1]
                            cx2, cy2 = ctrl_tx[2], ctrl_tx[3]
                            ccx, ccy = ctrl_tx[4], ctrl_tx[5]
                            curve_pts = self._linear_geom.gen_curve_pts(
                                cx1, cy1, cx2, cy2, ccx, ccy, 24
                            )
                            if len(curve_pts) >= 2:
                                inner, outer = (
                                    self._linear_geom.gen_thick_curve_offsets(
                                        curve_pts, thickness_px
                                    )
                                )
                                new_path = QPainterPath()
                                new_path.moveTo(inner[0][0], inner[0][1])
                                for px, py in inner[1:]:
                                    new_path.lineTo(px, py)
                                for px, py in reversed(outer):
                                    new_path.lineTo(px, py)
                                new_path.closeSubpath()
                    if new_path is None:
                        seg_len = self._linear_geom.calc_chord_length(x1, y1, x2, y2)
                        if seg_len >= 0.001:
                            ddx = (x2 - x1) / seg_len
                            ddy = (y2 - y1) / seg_len
                            ox = -ddy * thickness_px / 2
                            oy = ddx * thickness_px / 2
                            new_path = QPainterPath()
                            new_path.moveTo(x1 + ox, y1 + oy)
                            new_path.lineTo(x1 - ox, y1 - oy)
                            new_path.lineTo(x2 - ox, y2 - oy)
                            new_path.lineTo(x2 + ox, y2 + oy)
                            new_path.closeSubpath()
                    if new_path is not None:
                        path_item.setPos(0.0, 0.0)
                        path_item.setPath(new_path)
                        pattern_angle = compute_line_angle(x1, y1, x2, y2)
                        self._refresh_takeoff_pattern_preview(
                            uid, path_item, new_path, condition, pattern_angle
                        )
        is_body_move = self._drag_handle_index == -1 or (
            not is_ann
            and not condition.is_linear
            and not condition.is_area
            and self._drag_handle_index >= 0
        )
        if self._drag_item_orig_positions and is_body_move:
            use_pos = (
                self._drag_last_valid_new_pos
                if self._drag_last_valid_new_pos
                else new_pos
            )
            if (
                self._drag_orig_position
                and len(use_pos) >= 2
                and len(self._drag_orig_position) >= 2
            ):
                ost_dx = use_pos[0] - self._drag_orig_position[0]
                ost_dy = use_pos[1] - self._drag_orig_position[1]
                sdx, sdy = self.ost_to_scene_delta(ost_dx, ost_dy)
            else:
                sdx, sdy = scene_dx, scene_dy
            delta = QtCore.QPointF(sdx, sdy)
            for item in self._uid_to_items.get(uid, []):
                orig = self._drag_item_orig_positions.get(id(item))
                if orig is not None:
                    item.setPos(orig + delta)
            if not is_ann and takeoff.is_hole and self._drag_last_valid_new_pos:
                hole_tx = cs.transform_vertices_to_2d(use_pos)
                moved_hole_path = QPainterPath()
                moved_hole_path.moveTo(hole_tx[0], hole_tx[1])
                for hi in range(2, len(hole_tx) - 1, 2):
                    moved_hole_path.lineTo(hole_tx[hi], hole_tx[hi + 1])
                moved_hole_path.closeSubpath()
                self._update_parent_hole_path(takeoff.parent_uid, uid, moved_hole_path)

    def _update_ann_drag(self, ann, new_pos, uid, cs, scene_dx, scene_dy):
        atype = ann.annotation_type
        n_h = len(self._handle_infos)
        is_body = self._drag_handle_index == -1
        if atype in (
            ANNOTATION_TYPE_TEXT,
            ANNOTATION_TYPE_RECT,
            ANNOTATION_TYPE_OVAL,
            ANNOTATION_TYPE_HIGHLIGHT,
            ANNOTATION_TYPE_NAMED_VIEW,
        ):
            if atype == ANNOTATION_TYPE_TEXT and len(new_pos) >= 4:
                cx, cy, w, h = new_pos[0], new_pos[1], new_pos[2], new_pos[3]
                bx1, by1, bx2, by2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            elif len(new_pos) >= 4:
                n_pairs = len(new_pos) // 2
                xs = [new_pos[i * 2] for i in range(n_pairs)]
                ys = [new_pos[i * 2 + 1] for i in range(n_pairs)]
                bx1, by1, bx2, by2 = min(xs), min(ys), max(xs), max(ys)
            else:
                bx1 = by1 = bx2 = by2 = 0
            if not is_body and n_h >= 4:
                self._update_bbox_handles(cs, bx1, by1, bx2, by2, n_h)
                self._update_annotation_selection_outline_from_box(
                    uid, cs, bx1, by1, bx2, by2
                )
            if not is_body:
                tx = cs.transform_vertices_to_2d([bx1, by1, bx2, by2])
                self._rebuild_ann_shape_path(atype, uid, tx[0], tx[1], tx[2], tx[3])
        elif (
            atype in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD)
            and len(new_pos) >= 4
        ):
            tx = cs.transform_vertices_to_2d(new_pos)
            area_pts = [(tx[i], tx[i + 1]) for i in range(0, len(tx) - 1, 2)]
            is_vertex_drag = self._drag_handle_index >= 0 and len(area_pts) >= 3
            if is_vertex_drag and not self._polygon_edit_geometry_valid(
                new_pos, area_pts
            ):
                return
            n = len(area_pts)
            if n_h >= n:
                for i in range(n):
                    self._handle_infos[i].item.setPos(
                        self._pt_to_scene(area_pts[i][0], area_pts[i][1])
                    )
                for i in range(n):
                    mid_i = n + i
                    if mid_i < n_h:
                        p1, p2 = area_pts[i], area_pts[(i + 1) % n]
                        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
                        self._handle_infos[mid_i].item.setPos(self._pt_to_scene(mx, my))
            if not is_body:
                new_path = self._build_area_annotation_path(atype, area_pts)
                items = self._uid_to_items.get(uid, [])
                if items and isinstance(items[0], QGraphicsPathItem):
                    items[0].setPos(0.0, 0.0)
                    items[0].setPath(new_path)
        if is_body and self._drag_item_orig_positions:
            if ann.is_ink:
                sdx, sdy = scene_dx, scene_dy
            else:
                use_pos = self._drag_last_valid_new_pos or new_pos
                orig = self._drag_orig_position
                if orig and len(use_pos) >= 2 and len(orig) >= 2:
                    ost_dx = use_pos[0] - orig[0]
                    ost_dy = use_pos[1] - orig[1]
                    sdx, sdy = self.ost_to_scene_delta(ost_dx, ost_dy)
                else:
                    sdx, sdy = scene_dx, scene_dy
            delta = QPointF(sdx, sdy)
            for item in self._uid_to_items.get(uid, []):
                orig_p = self._drag_item_orig_positions.get(id(item))
                if orig_p is not None:
                    item.setPos(orig_p + delta)
            for item in self._selection_items:
                orig_p = self._drag_item_orig_positions.get(id(item))
                if orig_p is not None:
                    item.setPos(orig_p + delta)
        self._drag_last_valid_new_pos = list(new_pos)

    def _update_bbox_handles(self, cs, ox1, oy1, ox2, oy2, n_h):
        corners_ost = [ox1, oy1, ox2, oy1, ox2, oy2, ox1, oy2]
        tx = cs.transform_vertices_to_2d(corners_ost)
        pts = [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]
        n = len(pts)
        for i in range(min(n, n_h)):
            self._handle_infos[i].item.setPos(pts[i])
        for i in range(n):
            mid_i = n + i
            if mid_i < n_h:
                p1, p2 = pts[i], pts[(i + 1) % n]
                self._handle_infos[mid_i].item.setPos(
                    type(p1)((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
                )

    def _update_annotation_selection_outline_from_box(
        self, uid: str, cs, ox1: float, oy1: float, ox2: float, oy2: float
    ) -> None:
        corners_ost = [ox1, oy1, ox2, oy1, ox2, oy2, ox1, oy2]
        tx = cs.transform_vertices_to_2d(corners_ost)
        pts = [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]
        if len(pts) < 4:
            return
        polygon = QPolygonF(pts)
        for item in self._selection_items:
            if isinstance(item, QGraphicsPolygonItem) and item.data(0) == uid:
                item.setPolygon(polygon)
                return

    def _rebuild_ann_shape_path(self, atype, uid, x1, y1, x2, y2):
        items = self._uid_to_items.get(uid, [])
        if not items:
            return
        main = items[0]
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
        if isinstance(main, QGraphicsPathItem):
            new_path = QPainterPath()
            if atype == ANNOTATION_TYPE_OVAL:
                new_path.addEllipse(rect)
            else:
                new_path.addRect(rect)
            main.setPos(0.0, 0.0)
            main.setPath(new_path)
            return
        if isinstance(main, QGraphicsRectItem):
            old_top_left = main.mapToScene(main.rect().topLeft())
            dx = rect.left() - old_top_left.x()
            dy = rect.top() - old_top_left.y()
            main.setPos(0.0, 0.0)
            main.setRect(rect)
            for follow in items[1:]:
                follow.setPos(follow.pos().x() + dx, follow.pos().y() + dy)
            return
        if isinstance(main, QGraphicsTextItem):
            main.setPos(rect.topLeft())
            main.setTextWidth(rect.width())
            if isinstance(main, ClippedTextGraphicsItem):
                main.set_clip_rect(QRectF(0.0, 0.0, rect.width(), rect.height()))

    def _update_parent_hole_path(
        self, parent_uid: str, dragged_hole_uid: str, new_hole_path: QPainterPath
    ) -> None:
        parent = self._current_takeoffs.get(parent_uid)
        if not parent:
            return
        cs = self._scene_builder.get_coordinate_system()
        parent_pos = cs.parse_position(parent.position)
        if not parent_pos or len(parent_pos) < 6:
            return
        parent_tx = cs.transform_vertices_to_2d(parent_pos)
        combined = QPainterPath()
        combined.moveTo(parent_tx[0], parent_tx[1])
        for i in range(2, len(parent_tx) - 1, 2):
            combined.lineTo(parent_tx[i], parent_tx[i + 1])
        combined.closeSubpath()
        for child in self._current_takeoffs.values():
            if child.parent_uid != parent_uid:
                continue
            if child.uid == dragged_hole_uid:
                combined = combined.subtracted(new_hole_path)
            else:
                child_pos = cs.parse_position(child.position)
                if child_pos and len(child_pos) >= 6:
                    child_tx = cs.transform_vertices_to_2d(child_pos)
                    child_path = QPainterPath()
                    child_path.moveTo(child_tx[0], child_tx[1])
                    for i in range(2, len(child_tx) - 1, 2):
                        child_path.lineTo(child_tx[i], child_tx[i + 1])
                    child_path.closeSubpath()
                    combined = combined.subtracted(child_path)
        parent_items = self._uid_to_items.get(parent_uid, [])
        for item in parent_items:
            if isinstance(item, QGraphicsPathItem):
                item.setPos(0.0, 0.0)
                item.setPath(combined)
                parent_condition = self._current_conditions.get(parent.condition_uid)
                if parent_condition is not None:
                    self._refresh_takeoff_pattern_preview(
                        parent_uid, item, combined, parent_condition
                    )
                self._refresh_condition_text_labels_for_takeoff(parent_uid)
                break

    def _has_child_holes(self, parent_uid: str) -> bool:
        for t in self._current_takeoffs.values():
            if t.parent_uid == parent_uid:
                return True
        return False

    def _rebuild_parent_with_holes(
        self, parent_uid: str, parent_path: QPainterPath
    ) -> None:
        cs = self._scene_builder.get_coordinate_system()
        combined = QPainterPath(parent_path)
        for child in self._current_takeoffs.values():
            if child.parent_uid != parent_uid:
                continue
            child_pos = cs.parse_position(child.position)
            if child_pos and len(child_pos) >= 6:
                child_tx = cs.transform_vertices_to_2d(child_pos)
                child_path = QPainterPath()
                child_path.moveTo(child_tx[0], child_tx[1])
                for i in range(2, len(child_tx) - 1, 2):
                    child_path.lineTo(child_tx[i], child_tx[i + 1])
                child_path.closeSubpath()
                combined = combined.subtracted(child_path)
        parent_items = self._uid_to_items.get(parent_uid, [])
        for item in parent_items:
            if isinstance(item, QGraphicsPathItem):
                item.setPos(0.0, 0.0)
                item.setPath(combined)
                parent = self._current_takeoffs.get(parent_uid)
                parent_condition = (
                    self._current_conditions.get(parent.condition_uid)
                    if parent
                    else None
                )
                if parent_condition is not None:
                    self._refresh_takeoff_pattern_preview(
                        parent_uid, item, combined, parent_condition
                    )
                self._refresh_condition_text_labels_for_takeoff(parent_uid)
                break

    def _validate_parent_contains_holes(
        self, parent_uid: str, new_parent_pos: List[float]
    ) -> bool:
        cs = self._scene_builder.get_coordinate_system()
        parent_tx = cs.transform_vertices_to_2d(new_parent_pos)
        parent_path = QPainterPath()
        parent_path.moveTo(parent_tx[0], parent_tx[1])
        for i in range(2, len(parent_tx) - 1, 2):
            parent_path.lineTo(parent_tx[i], parent_tx[i + 1])
        parent_path.closeSubpath()
        for child in self._current_takeoffs.values():
            if child.parent_uid != parent_uid:
                continue
            child_pos = cs.parse_position(child.position)
            if not child_pos or len(child_pos) < 6:
                continue
            child_tx = cs.transform_vertices_to_2d(child_pos)
            child_path = QPainterPath()
            child_path.moveTo(child_tx[0], child_tx[1])
            for i in range(2, len(child_tx) - 1, 2):
                child_path.lineTo(child_tx[i], child_tx[i + 1])
            child_path.closeSubpath()
            if not child_path.subtracted(parent_path).isEmpty():
                return False
        return True

    def _validate_hole_position(
        self, takeoff, new_pos: List[float], area_pts: List[Tuple[float, float]]
    ) -> bool:
        cs = self._scene_builder.get_coordinate_system()
        parent = self._current_takeoffs.get(takeoff.parent_uid)
        if not parent:
            return False
        parent_pos = cs.parse_position(parent.position)
        if not parent_pos or len(parent_pos) < 6:
            return False
        parent_tx = cs.transform_vertices_to_2d(parent_pos)
        parent_path = QPainterPath()
        parent_path.moveTo(parent_tx[0], parent_tx[1])
        for i in range(2, len(parent_tx) - 1, 2):
            parent_path.lineTo(parent_tx[i], parent_tx[i + 1])
        parent_path.closeSubpath()
        new_hole_path = QPainterPath()
        new_hole_path.moveTo(area_pts[0][0], area_pts[0][1])
        for px, py in area_pts[1:]:
            new_hole_path.lineTo(px, py)
        new_hole_path.closeSubpath()
        if not new_hole_path.subtracted(parent_path).isEmpty():
            return False
        for sibling in self._current_takeoffs.values():
            if sibling.parent_uid != takeoff.parent_uid:
                continue
            if sibling.uid == takeoff.uid:
                continue
            sib_pos = cs.parse_position(sibling.position)
            if not sib_pos or len(sib_pos) < 6:
                continue
            sib_tx = cs.transform_vertices_to_2d(sib_pos)
            sib_path = QPainterPath()
            sib_path.moveTo(sib_tx[0], sib_tx[1])
            for i in range(2, len(sib_tx) - 1, 2):
                sib_path.lineTo(sib_tx[i], sib_tx[i + 1])
            sib_path.closeSubpath()
            if new_hole_path.intersects(sib_path):
                return False
        return True
