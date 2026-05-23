import logging
import math
from typing import List, Optional, Set
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem
from .....application.dtos.hotlink_dto import HotlinkDto
from .geometry_utils import (
    HandleInfo,
    cursor_for_direction,
    point_to_segment_distance,
    resize_cursor_for_edge,
)
from .handle_style import apply_takeoff_handle_style

logger = logging.getLogger(__name__)


class SelectionManagerMixin:
    _CORNER_HALF = 4.0
    _MID_HALF = 2.0

    def _is_selectable(self, uid: str) -> bool:
        if self._annotation_only_selection:
            ann = self._current_annotations.get(uid)
            return bool(ann and ann.is_interactive)
        if uid in self._current_takeoffs:
            return True
        ann = self._current_annotations.get(uid)
        return bool(ann and ann.is_interactive)

    def find_takeoffs_at(self, scene_pos) -> List[str]:
        seen: Set[str] = set()
        result: List[str] = []
        for item in self._scene.items(scene_pos):
            uid = item.data(0)
            if uid and uid not in seen and self._is_selectable(uid):
                seen.add(uid)
                result.append(uid)
        return result

    def _iter_ann_hits(self, scene_pos, uid_ann_pairs=None):
        if uid_ann_pairs is None:
            uid_ann_pairs = self._current_annotations.items()
        m11 = self.transform().m11()
        hit_dist = 8 / m11 if m11 > 0 else 8
        page_transform = self._current_page_transform()
        if page_transform is not None:
            inv, ok = page_transform.inverted()
            check_pos = inv.map(scene_pos) if ok else scene_pos
        else:
            check_pos = scene_pos
        cs = self._scene_builder.get_coordinate_system()
        for uid, ann in uid_ann_pairs:
            if not ann.is_interactive:
                continue
            tx = cs.transform_vertices_to_2d(ann.position)
            if (
                len(tx) >= 4
                and point_to_segment_distance(
                    check_pos.x(), check_pos.y(), tx[0], tx[1], tx[2], tx[3]
                )
                <= hit_dist
            ):
                yield uid, tx

    def find_linear_annotation_near(self, scene_pos) -> Optional[str]:
        for uid, _tx in self._iter_ann_hits(scene_pos):
            return uid
        return None

    def find_takeoff_at(
        self, scene_pos, cycle_from_uid: Optional[str] = None
    ) -> Optional[str]:
        uids = self.find_takeoffs_at(scene_pos)
        if not uids:
            ann_uid = self.find_linear_annotation_near(scene_pos)
            if ann_uid:
                uids = [ann_uid]
        if not uids:
            return None
        if cycle_from_uid and cycle_from_uid in uids:
            idx = uids.index(cycle_from_uid)
            return uids[(idx + 1) % len(uids)]
        return uids[0]

    def find_hotlink_at(self, scene_pos) -> Optional[HotlinkDto]:
        for item, link_info in self._hotlink_items:
            if item.contains(scene_pos):
                return link_info
            dx = scene_pos.x() - link_info.center_x
            dy = scene_pos.y() - link_info.center_y
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= link_info.radius:
                return link_info
        return None

    def clear_selection_items(self) -> None:
        for item in self._selection_items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self._selection_items.clear()
        self._handle_infos.clear()

    def _make_selection_handle(
        self, px: float, py: float, half: float, cursor: Qt.CursorShape
    ) -> QGraphicsRectItem:
        h = QGraphicsRectItem(-half, -half, half * 2, half * 2)
        background_color = self._current_handle_background_color()
        apply_takeoff_handle_style(h, background_color)
        h.setZValue(15)
        h.setPos(px, py)
        h.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        self._handle_infos.append(HandleInfo(item=h, cursor=cursor))
        return h

    def _make_endpoint_handles(self, tx_pos) -> List:
        if len(tx_pos) < 4:
            return []
        p0 = self._pt_to_scene(tx_pos[0], tx_pos[1])
        p1 = self._pt_to_scene(tx_pos[2], tx_pos[3])
        cur = cursor_for_direction(p1.x() - p0.x(), p1.y() - p0.y())
        return [
            self._make_selection_handle(p0.x(), p0.y(), self._CORNER_HALF, cur),
            self._make_selection_handle(p1.x(), p1.y(), self._CORNER_HALF, cur),
        ]

    def clear_selection(self, emit: bool = True) -> None:
        if not self._selected_uids:
            return
        self._selected_uids.clear()
        self.update_selection_visuals(emit=emit)

    def get_selected_takeoff_uids(self) -> List[str]:
        return sorted(
            uid for uid in self._selected_uids if uid in self._current_takeoffs
        )

    def set_selected_uids(self, uids: set, emit: bool = True) -> None:
        if self._selected_uids == uids:
            return
        self._selected_uids = set(uids)
        self.update_selection_visuals(emit=emit)

    def select_takeoffs_in_area(self, area_uid: Optional[str]) -> None:
        if not self._selection_enabled or self._cursor_mode != "select":
            return
        page_area_selections = (
            {self._current_bid_page_uid: area_uid}
            if self._current_bid_page_uid and area_uid is not None
            else None
        )
        selected_uids = set()
        for uid, takeoff in self._current_takeoffs.items():
            condition = self._current_conditions.get(takeoff.condition_uid)
            if (
                uid in self._uid_to_items
                and condition
                and condition.layer_visible
                and self._is_selectable(uid)
                and not self._color_service.should_gray_out_takeoff(
                    takeoff, page_area_selections
                )
            ):
                selected_uids.add(uid)
        self.set_selected_uids(selected_uids)

    def _pt_to_scene(self, x: float, y: float) -> QtCore.QPointF:
        transform = self._current_page_transform()
        if transform is not None:
            return transform.map(QtCore.QPointF(x, y))
        return QtCore.QPointF(x, y)

    def _scene_pos_to_ost(self, scene_pos: QtCore.QPointF) -> QtCore.QPointF:
        cs = self._scene_builder.get_coordinate_system()
        factor = cs.scale_ratio / (72.0 * cs.view_scale)
        transform = self._current_page_transform()
        if transform is not None:
            inv, ok = transform.inverted()
            if ok:
                unrotated = inv.map(scene_pos)
                return QtCore.QPointF(unrotated.x() * factor, unrotated.y() * factor)
        return QtCore.QPointF(scene_pos.x() * factor, scene_pos.y() * factor)

    def update_selection_visuals(self, emit: bool = True) -> None:
        self.clear_selection_items()
        all_keys = set(self._current_takeoffs.keys()) | set(
            self._current_annotations.keys()
        )
        valid = self._selected_uids & all_keys
        if not valid:
            if emit:
                self.takeoff_selection_changed.emit([])
            return
        if len(valid) == 1:
            uid = next(iter(valid))
            self._selection_items = self._create_single_handles(uid)
        else:
            self._selection_items = self._create_multi_borders(valid)
        for item in self._selection_items:
            self._scene.addItem(item)
        transform = self._current_page_transform()
        if transform:
            for item in self._selection_items:
                if isinstance(item, QGraphicsPathItem):
                    item.setTransform(transform)
        valid_takeoffs = valid & self._current_takeoffs.keys()
        if emit:
            self.takeoff_selection_changed.emit(list(valid_takeoffs))

    def _create_single_handles(self, uid: str) -> List:
        cs = self._scene_builder.get_coordinate_system()
        ann = self._current_annotations.get(uid)
        if ann is not None:
            if not ann.is_interactive or not ann.has_valid_position:
                return []
            return self._create_annotation_handles(ann, uid, cs)
        takeoff = self._current_takeoffs.get(uid)
        if not takeoff:
            return []
        condition = self._current_conditions.get(takeoff.condition_uid)
        if not condition:
            return []
        raw_pos = cs.parse_position(takeoff.position)
        if not raw_pos:
            return []
        tx_pos = cs.transform_vertices_to_2d(raw_pos)
        if condition.is_linear:
            if takeoff.curve >= 0 and len(raw_pos) >= 6:
                rx1, ry1, rx2, ry2, rcx, rcy = raw_pos[:6]
                rx1, ry1, rx2, ry2, rcx, rcy = self._linear_geom.proc_curved_pos(
                    raw_pos, rx1, ry1, rx2, ry2, rcx, rcy
                )
                ctrl_tx = cs.transform_vertices_to_2d([rx1, ry1, rx2, ry2, rcx, rcy])
                p0 = self._pt_to_scene(ctrl_tx[0], ctrl_tx[1])
                p1 = self._pt_to_scene(ctrl_tx[2], ctrl_tx[3])
                pc = self._pt_to_scene(ctrl_tx[4], ctrl_tx[5])
                ep_cur = cursor_for_direction(p1.x() - p0.x(), p1.y() - p0.y())
                mid_cur = resize_cursor_for_edge(p1.x() - p0.x(), p1.y() - p0.y())
                return [
                    self._make_selection_handle(
                        p0.x(), p0.y(), self._CORNER_HALF, ep_cur
                    ),
                    self._make_selection_handle(
                        p1.x(), p1.y(), self._CORNER_HALF, ep_cur
                    ),
                    self._make_selection_handle(
                        pc.x(), pc.y(), self._CORNER_HALF, mid_cur
                    ),
                ]
            return self._make_endpoint_handles(tx_pos)
        if condition.is_area:
            raw_pts = [(tx_pos[i], tx_pos[i + 1]) for i in range(0, len(tx_pos) - 1, 2)]
            pts = [self._pt_to_scene(x, y) for x, y in raw_pts]
            n = len(pts)
            if n < 2:
                return []
            handles = []
            for i in range(n):
                sp = pts[i]
                prev_pt = pts[(i - 1) % n]
                corner_cursor = resize_cursor_for_edge(
                    sp.x() - prev_pt.x(), sp.y() - prev_pt.y()
                )
                handles.append(
                    self._make_selection_handle(
                        sp.x(), sp.y(), self._CORNER_HALF, corner_cursor
                    )
                )
            for i in range(n):
                s1, s2 = pts[i], pts[(i + 1) % n]
                mx, my = (s1.x() + s2.x()) / 2, (s1.y() + s2.y()) / 2
                mid_cursor = resize_cursor_for_edge(s2.x() - s1.x(), s2.y() - s1.y())
                handles.append(
                    self._make_selection_handle(mx, my, self._MID_HALF, mid_cursor)
                )
            return handles
        if len(tx_pos) < 2:
            return []
        sp = self._pt_to_scene(tx_pos[0], tx_pos[1])
        return [
            self._make_selection_handle(
                sp.x(), sp.y(), self._CORNER_HALF, Qt.CursorShape.SizeAllCursor
            )
        ]

    def _create_annotation_handles(self, ann, uid, cs) -> List:
        atype = ann.annotation_type
        pos = ann.position
        if atype in ("line", "arrow"):
            return self._make_endpoint_handles(cs.transform_vertices_to_2d(pos))
        if atype == "hotlink":
            tx = cs.transform_vertices_to_2d(pos[:2])
            sp = self._pt_to_scene(tx[0], tx[1])
            return [
                self._make_selection_handle(
                    sp.x(), sp.y(), self._CORNER_HALF, Qt.CursorShape.SizeAllCursor
                )
            ]
        if atype == "ink":
            items = self._uid_to_items.get(uid, [])
            for item in items:
                if isinstance(item, QGraphicsPathItem):
                    path = item.path()
                    if path.elementCount() >= 2:
                        first = path.elementAt(0)
                        last = path.elementAt(path.elementCount() - 1)
                        p0 = item.mapToScene(first.x, first.y)
                        p1 = item.mapToScene(last.x, last.y)
                        return [
                            self._make_selection_handle(
                                p0.x(),
                                p0.y(),
                                self._CORNER_HALF,
                                Qt.CursorShape.ArrowCursor,
                            ),
                            self._make_selection_handle(
                                p1.x(),
                                p1.y(),
                                self._CORNER_HALF,
                                Qt.CursorShape.ArrowCursor,
                            ),
                        ]
            return []
        if atype == "text" and len(pos) >= 4:
            cx_o, cy_o, w_o, h_o = pos[0], pos[1], pos[2], pos[3]
            rot_rad = ann.stored_rotation_rad
            hw, hh = w_o / 2, h_o / 2
            offsets = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            corners_ost = []
            if rot_rad != 0.0:
                cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
                for dx, dy in offsets:
                    corners_ost.extend(
                        [
                            cx_o + dx * cos_r - dy * sin_r,
                            cy_o + dx * sin_r + dy * cos_r,
                        ]
                    )
            else:
                for dx, dy in offsets:
                    corners_ost.extend([cx_o + dx, cy_o + dy])
            tx = cs.transform_vertices_to_2d(corners_ost)
            pts = [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]
            return self._make_bbox_handles(pts)
        corners_ost = self._get_ann_corners_ost(ann)
        if corners_ost and atype in ("rect", "oval", "highlight", "namedview"):
            tx = cs.transform_vertices_to_2d(corners_ost)
            pts = [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]
            return self._make_bbox_handles(pts)
        if atype in ("polygon", "cloud") and len(pos) >= 4:
            tx = cs.transform_vertices_to_2d(pos)
            raw_pts = [(tx[i], tx[i + 1]) for i in range(0, len(tx) - 1, 2)]
            pts = [self._pt_to_scene(x, y) for x, y in raw_pts]
            n = len(pts)
            if n < 2:
                return []
            handles = []
            for i in range(n):
                sp = pts[i]
                prev_pt = pts[(i - 1) % n]
                corner_cursor = resize_cursor_for_edge(
                    sp.x() - prev_pt.x(), sp.y() - prev_pt.y()
                )
                handles.append(
                    self._make_selection_handle(
                        sp.x(), sp.y(), self._CORNER_HALF, corner_cursor
                    )
                )
            for i in range(n):
                s1, s2 = pts[i], pts[(i + 1) % n]
                mx, my = (s1.x() + s2.x()) / 2, (s1.y() + s2.y()) / 2
                mid_cursor = resize_cursor_for_edge(s2.x() - s1.x(), s2.y() - s1.y())
                handles.append(
                    self._make_selection_handle(mx, my, self._MID_HALF, mid_cursor)
                )
            return handles
        return []

    @staticmethod
    def _get_ann_corners_ost(ann) -> list:
        pos = ann.position
        atype = ann.annotation_type
        if atype in ("rect", "highlight", "namedview") and len(pos) >= 8:
            return [pos[0], pos[1], pos[6], pos[7], pos[2], pos[3], pos[4], pos[5]]
        if atype == "oval" and len(pos) >= 4:
            cx = (pos[0] + pos[2]) / 2
            cy = (pos[1] + pos[3]) / 2
            rot_rad = ann.stored_rotation_rad
            cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
            dx0, dy0 = pos[0] - cx, pos[1] - cy
            ux0 = cx + dx0 * cos_r + dy0 * sin_r
            uy0 = cy - dx0 * sin_r + dy0 * cos_r
            dx1, dy1 = pos[2] - cx, pos[3] - cy
            ux1 = cx + dx1 * cos_r + dy1 * sin_r
            uy1 = cy - dx1 * sin_r + dy1 * cos_r
            hw = abs(ux1 - ux0) / 2
            hh = abs(uy1 - uy0) / 2
            corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            result = []
            for dx, dy in corners:
                result.extend(
                    [cx + dx * cos_r - dy * sin_r, cy + dx * sin_r + dy * cos_r]
                )
            return result
        bbox = ann.get_bbox_ost()
        if bbox:
            bx1, by1, bx2, by2 = bbox
            return [bx1, by1, bx2, by1, bx2, by2, bx1, by2]
        return []

    def _make_bbox_handles(self, pts) -> List:
        n = len(pts)
        if n < 4:
            return []
        handles = []
        for i in range(n):
            sp = pts[i]
            prev_pt = pts[(i - 1) % n]
            corner_cursor = resize_cursor_for_edge(
                sp.x() - prev_pt.x(), sp.y() - prev_pt.y()
            )
            handles.append(
                self._make_selection_handle(
                    sp.x(), sp.y(), self._CORNER_HALF, corner_cursor
                )
            )
        for i in range(n):
            s1, s2 = pts[i], pts[(i + 1) % n]
            mx, my = (s1.x() + s2.x()) / 2, (s1.y() + s2.y()) / 2
            mid_cursor = resize_cursor_for_edge(s2.x() - s1.x(), s2.y() - s1.y())
            handles.append(
                self._make_selection_handle(mx, my, self._MID_HALF, mid_cursor)
            )
        return handles

    def _create_multi_borders(self, uids) -> List:
        borders = []
        yellow_pen = QPen(QColor(255, 220, 0))
        yellow_pen.setWidthF(2.0)
        yellow_pen.setCosmetic(True)
        cs = self._scene_builder.get_coordinate_system()
        for uid in uids:
            ann = self._current_annotations.get(uid)
            if ann and ann.is_text and len(ann.position) >= 4:
                pos = ann.position
                cx_o, cy_o, w_o, h_o = pos[0], pos[1], pos[2], pos[3]
                rot_rad = ann.stored_rotation_rad
                hw, hh = w_o / 2, h_o / 2
                offsets = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
                corners_ost = []
                if rot_rad != 0.0:
                    cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
                    for dx, dy in offsets:
                        corners_ost.extend(
                            [
                                cx_o + dx * cos_r - dy * sin_r,
                                cy_o + dx * sin_r + dy * cos_r,
                            ]
                        )
                else:
                    for dx, dy in offsets:
                        corners_ost.extend([cx_o + dx, cy_o + dy])
                tx = cs.transform_vertices_to_2d(corners_ost)
                path = QPainterPath()
                p0 = self._pt_to_scene(tx[0], tx[1])
                path.moveTo(p0)
                for i in range(2, len(tx), 2):
                    path.lineTo(self._pt_to_scene(tx[i], tx[i + 1]))
                path.closeSubpath()
                border = QGraphicsPathItem(path)
                border.setPen(yellow_pen)
                border.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                border.setZValue(14)
                border.setData(0, uid)
                borders.append(border)
                continue
            for item in self._uid_to_items.get(uid, []):
                border = None
                if isinstance(item, QGraphicsPathItem):
                    border = QGraphicsPathItem(item.path())
                    border.setPos(item.pos())
                    border.setTransformOriginPoint(item.transformOriginPoint())
                    border.setRotation(item.rotation())
                elif isinstance(item, QGraphicsRectItem):
                    path = QPainterPath()
                    path.addRect(item.rect())
                    border = QGraphicsPathItem(path)
                    border.setPos(item.pos())
                else:
                    path = QPainterPath()
                    path.addRect(item.boundingRect())
                    border = QGraphicsPathItem(path)
                    border.setPos(item.pos())
                    border.setRotation(item.rotation())
                if border is not None:
                    border.setData(0, uid)
                    border.setPen(yellow_pen)
                    border.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    border.setZValue(14)
                    borders.append(border)
        return borders

    def _resolve_select_cursor(self, vp_pos: QtCore.QPoint) -> Qt.CursorShape:
        if not self._selected_uids:
            return Qt.CursorShape.ArrowCursor
        for info in self._handle_infos:
            center = info.item.mapToScene(QtCore.QPointF(0.0, 0.0))
            handle_vp = self.mapFromScene(center)
            half = info.item.rect().width() / 2
            if (
                abs(vp_pos.x() - handle_vp.x()) <= half + 2
                and abs(vp_pos.y() - handle_vp.y()) <= half + 2
            ):
                return info.cursor
        scene_pos = self.mapToScene(vp_pos)
        for uid in self._selected_uids:
            for item in self._uid_to_items.get(uid, []):
                local = item.mapFromScene(scene_pos)
                if isinstance(item, QGraphicsPathItem):
                    if item.path().contains(local):
                        return Qt.CursorShape.SizeAllCursor
                elif item.contains(local):
                    return Qt.CursorShape.SizeAllCursor
        selected_ann_pairs = [
            (uid, ann)
            for uid in self._selected_uids
            if (ann := self._current_annotations.get(uid)) is not None
        ]
        for uid, _tx in self._iter_ann_hits(scene_pos, selected_ann_pairs):
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.ArrowCursor
