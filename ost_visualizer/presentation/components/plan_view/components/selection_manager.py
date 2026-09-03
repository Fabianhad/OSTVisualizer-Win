import logging
import math
from dataclasses import dataclass
from typing import Collection, List, Optional, Set
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsTextItem,
)

_PENDING_MUTATION_ORIGINAL_OPACITY_ROLE = 20
from .....application.dtos.hotlink_dto import HotlinkDto
from .....domain.entities.annotation import (
    ANNOTATION_TYPE_ARROW,
    ANNOTATION_TYPE_CLOUD,
    ANNOTATION_TYPE_DIMENSION,
    ANNOTATION_TYPE_HIGHLIGHT,
    ANNOTATION_TYPE_HOTLINK,
    ANNOTATION_TYPE_INK,
    ANNOTATION_TYPE_LINE,
    ANNOTATION_TYPE_NAMED_VIEW,
    ANNOTATION_TYPE_OVAL,
    ANNOTATION_TYPE_POLYGON,
    ANNOTATION_TYPE_RECT,
    ANNOTATION_TYPE_TEXT,
)
from .....domain.entities.named_view import named_view_edit_position
from ....modes.cursor import CURSOR_MODE_SELECT
from ....visualization.pdf.renderers.annotation_renderer import (
    calculate_dimension_segments,
    canonical_highlight_quads,
    highlight_position_coordinates,
)
from .geometry_utils import (
    HandleInfo,
    cursor_for_direction,
    point_to_segment_distance,
    resize_cursor_for_edge,
)
from .graphics_items import ClippedTextGraphicsItem
from .handle_style import apply_takeoff_handle_style

logger = logging.getLogger(__name__)
_TEXT_SELECTION_OUTLINE_COLOR = QColor(128, 128, 128)


@dataclass(frozen=True)
class PolygonControlPointTarget:
    plan_item_uid: str
    kind: str
    vertex_index: int = -1
    edge_index: int = -1
    insert_point: tuple[float, float] | None = None


class SelectionManagerMixin:
    _CORNER_HALF = 4.0
    _MID_HALF = 2.0
    _TEXT_ANNOTATION_HIT_TOLERANCE_PX = 4.0
    _POLYGON_CONTROL_POINT_HIT_TOLERANCE_PX = 8.0
    _hidden_layer_uids: Collection[str] = ()

    def _on_selection_changed(self) -> None:
        pass

    def _pdf_text_run_at(self, _scene_pos: QtCore.QPointF):
        return None

    def _pdf_text_char_at(self, _scene_pos: QtCore.QPointF):
        return None

    def _clear_pdf_text_selection(self) -> None:
        pass

    def select_pdf_text_at(self, _scene_pos: QtCore.QPointF) -> bool:
        return False

    def _begin_pdf_text_selection(self, _scene_pos: QtCore.QPointF) -> bool:
        return False

    def _update_pdf_text_selection_drag(self, _scene_pos: QtCore.QPointF) -> bool:
        return False

    def _finish_pdf_text_selection_drag(self) -> bool:
        return False

    def copy_selected_pdf_text(self) -> bool:
        return False

    def has_selected_pdf_text(self) -> bool:
        return False

    def _is_selectable(self, uid: str) -> bool:
        if uid in self._pending_mutation_uids:
            return False
        if self._annotation_only_selection:
            ann = self._current_annotations.get(uid)
            if ann is None or not ann.is_interactive:
                return False
            return bool(self._annotation_layer_visible(ann))
        takeoff = self._current_takeoffs.get(uid)
        if takeoff is not None:
            return takeoff.is_visible(self._current_conditions)
        ann = self._current_annotations.get(uid)
        if ann is None or not ann.is_interactive:
            return False
        return bool(self._annotation_layer_visible(ann))

    def set_pending_mutation_uids(self, uids: set[str]) -> None:
        pending = {str(uid) for uid in uids if uid}
        affected = self._pending_mutation_uids.symmetric_difference(pending)
        self._pending_mutation_uids = pending
        selected_changed = bool(self._selected_uids.intersection(pending))
        if selected_changed:
            self._selected_uids.difference_update(pending)
            self._on_selection_changed()
            self.update_selection_visuals()
        for uid in affected:
            self._apply_pending_mutation_visual(uid)
        if selected_changed:
            self._update_cursor()

    def get_pending_mutation_uids(self) -> set[str]:
        return set(self._pending_mutation_uids)

    def _apply_pending_mutation_visual(self, uid: str) -> None:
        is_pending = uid in self._pending_mutation_uids
        for item in self._uid_to_items.get(uid, ()):
            original_opacity = item.data(_PENDING_MUTATION_ORIGINAL_OPACITY_ROLE)
            if is_pending:
                if original_opacity is None:
                    item.setData(
                        _PENDING_MUTATION_ORIGINAL_OPACITY_ROLE,
                        float(item.opacity()),
                    )
                item.setOpacity(0.35)
            elif original_opacity is not None:
                item.setOpacity(float(original_opacity))
                item.setData(_PENDING_MUTATION_ORIGINAL_OPACITY_ROLE, None)

    def _annotation_layer_visible(self, annotation) -> bool:
        layer_uid = str(annotation.layer_uid or "")
        return bool(
            annotation.visible
            and (not layer_uid or layer_uid not in self._hidden_layer_uids)
        )

    def find_takeoffs_at(self, scene_pos) -> List[str]:
        seen: Set[str] = set()
        annotation_hits: List[str] = []
        takeoff_hits: List[str] = []
        for item in self._scene.items(scene_pos):
            uid = item.data(0)
            if not uid or uid in seen or not self._is_selectable(uid):
                continue
            ann = self._current_annotations.get(uid)
            if ann is not None and ann.is_text:
                if not self._text_annotation_contains_scene_point(uid, scene_pos):
                    continue
            seen.add(uid)
            if ann is not None:
                annotation_hits.append(uid)
            else:
                takeoff_hits.append(uid)
        for uid, ann in self._current_annotations.items():
            if (
                uid not in seen
                and self._is_selectable(uid)
                and ann.is_text
                and ann.is_interactive
                and self._text_annotation_contains_scene_point(uid, scene_pos)
            ):
                seen.add(uid)
                annotation_hits.append(uid)
        return annotation_hits + takeoff_hits

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
            if not ann.is_interactive or not self._annotation_layer_visible(ann):
                continue
            if ann.annotation_type not in ann.LINEAR_TYPES:
                continue
            tx = cs.transform_vertices_to_2d(ann.position)
            if len(tx) < 4:
                continue
            segments = [(tx[0], tx[1], tx[2], tx[3])]
            if ann.is_dimension:
                segments = calculate_dimension_segments(
                    tx[0],
                    tx[1],
                    tx[2],
                    tx[3],
                    max(10.0, float(ann.properties.get("FontSize", 10) or 10) * 0.8),
                )
            for x1, y1, x2, y2 in segments:
                if (
                    point_to_segment_distance(
                        check_pos.x(), check_pos.y(), x1, y1, x2, y2
                    )
                    <= hit_dist
                ):
                    yield uid, tx
                    break

    def _scene_tolerance_for_text_annotation(self) -> float:
        m11 = self.transform().m11()
        return (
            self._TEXT_ANNOTATION_HIT_TOLERANCE_PX / m11
            if m11 > 0
            else self._TEXT_ANNOTATION_HIT_TOLERANCE_PX
        )

    def _text_annotation_contains_scene_point(
        self, uid: str, scene_pos: QtCore.QPointF
    ) -> bool:
        tolerance = self._scene_tolerance_for_text_annotation()
        for item in self._uid_to_items.get(uid, []):
            if not isinstance(item, QGraphicsTextItem):
                continue
            if item.data(2) == "condition_label":
                continue
            local = item.mapFromScene(scene_pos)
            bounds = item.boundingRect()
            if isinstance(item, ClippedTextGraphicsItem):
                bounds = item.text_bounding_rect().intersected(item.clip_rect())
            if bounds.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(
                local
            ):
                return True
        return False

    def find_text_annotation_at(self, scene_pos: QtCore.QPointF) -> Optional[str]:
        for uid, ann in self._current_annotations.items():
            if (
                ann.is_text
                and self._is_selectable(uid)
                and self._text_annotation_contains_scene_point(uid, scene_pos)
            ):
                return uid
        return None

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

    def _hotlink_item_contains_scene_point(
        self, item: QGraphicsItem, link_info: HotlinkDto, scene_pos: QtCore.QPointF
    ) -> bool:
        local = item.mapFromScene(scene_pos)
        if isinstance(item, QGraphicsPathItem):
            if item.shape().contains(local) or item.path().contains(local):
                return True
        elif item.contains(local):
            return True
        dx = local.x() - link_info.center_x
        dy = local.y() - link_info.center_y
        return (dx * dx + dy * dy) ** 0.5 <= link_info.radius

    def find_selected_movable_at(self, scene_pos: QtCore.QPointF) -> Optional[str]:
        for uid in self._selected_uids:
            ann = self._current_annotations.get(uid)
            if ann is not None and ann.is_text and self._is_selectable(uid):
                if self._text_annotation_contains_scene_point(uid, scene_pos):
                    return uid
        for item, link_info in self._hotlink_items:
            scene_key = str(item.data(0) or "")
            if (
                scene_key in self._selected_uids
                and self._is_selectable(scene_key)
                and self._hotlink_item_contains_scene_point(item, link_info, scene_pos)
            ):
                return scene_key
        for uid in self.find_takeoffs_at(scene_pos):
            if uid in self._selected_uids:
                return uid
        selected_ann_pairs = []
        for uid in self._selected_uids:
            ann = self._current_annotations.get(uid)
            if (
                ann is not None
                and self._is_selectable(uid)
                and ann.annotation_type in ann.LINEAR_TYPES
            ):
                selected_ann_pairs.append((uid, ann))
        if selected_ann_pairs:
            for uid, _tx in self._iter_ann_hits(scene_pos, selected_ann_pairs):
                return uid
        return None

    def find_hotlink_at(self, scene_pos) -> Optional[HotlinkDto]:
        for item, link_info in self._hotlink_items:
            scene_key = str(item.data(0) or "")
            if (
                scene_key
                and self._is_selectable(scene_key)
                and self._hotlink_item_contains_scene_point(item, link_info, scene_pos)
            ):
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
        self._on_selection_changed()
        self.update_selection_visuals(emit=emit)
        self._update_cursor()

    def get_selected_takeoff_uids(self) -> List[str]:
        return sorted(
            uid for uid in self._selected_uids if uid in self._current_takeoffs
        )

    def get_selected_uids(self) -> List[str]:
        return sorted(self._selected_uids)

    def set_selected_uids(self, uids: set, emit: bool = True) -> None:
        uids = {uid for uid in uids if self._is_selectable(uid)}
        if self._selected_uids == uids:
            self._update_cursor()
            return
        self._selected_uids = set(uids)
        self._on_selection_changed()
        self.update_selection_visuals(emit=emit)
        self._update_cursor()

    def select_takeoffs_in_area(self, area_uid: Optional[str]) -> None:
        if not self._selection_enabled or self._cursor_mode != CURSOR_MODE_SELECT:
            return
        page_area_selections = (
            {self._current_bid_page_uid: area_uid}
            if self._current_bid_page_uid and area_uid is not None
            else None
        )
        selected_uids = set()
        for uid, takeoff in self._current_takeoffs.items():
            if (
                self._current_bid_page_uid
                and takeoff.page_uid
                and takeoff.page_uid != self._current_bid_page_uid
            ):
                continue
            if uid not in self._uid_to_items or not self._is_selectable(uid):
                continue
            if self._color_service.is_inactive_area_takeoff(
                takeoff, page_area_selections
            ):
                continue
            selected_uids.add(uid)
        self.set_selected_uids(selected_uids)
        self.takeoff_selection_command_applied.emit(self.get_selected_takeoff_uids())

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

    def _polygon_control_point_hit_tolerance(self) -> float:
        m11 = self.transform().m11()
        return (
            self._POLYGON_CONTROL_POINT_HIT_TOLERANCE_PX / m11
            if m11 > 0
            else self._POLYGON_CONTROL_POINT_HIT_TOLERANCE_PX
        )

    def _polygon_control_point_model_position(self, uid: str) -> list[float] | None:
        if not self._selection_enabled or not self._is_selectable(uid):
            return None
        takeoff = self._current_takeoffs.get(uid)
        if takeoff is not None:
            condition = self._current_conditions.get(takeoff.condition_uid)
            if condition is None or not condition.is_area:
                return None
            if takeoff.is_hole:
                parent = self._current_takeoffs.get(takeoff.parent_uid)
                parent_condition = (
                    self._current_conditions.get(parent.condition_uid)
                    if parent
                    else None
                )
                if (
                    parent is None
                    or parent.is_hole
                    or not (parent_condition and parent_condition.is_area)
                ):
                    return None
            position = takeoff.position
        else:
            annotation = self._current_annotations.get(uid)
            if annotation is None or not annotation.supports_polygon_control_points:
                return None
            position = annotation.position
        raw_pos = self._scene_builder.get_coordinate_system().parse_position(position)
        if not raw_pos or len(raw_pos) < 6 or len(raw_pos) % 2 != 0:
            return None
        return raw_pos

    def _polygon_control_point_candidates(
        self, scene_pos: QtCore.QPointF
    ) -> list[tuple[str, list[float]]]:
        seen: set[str] = set()
        ordered: list[tuple[str, list[float]]] = []
        for item in self._scene.items(scene_pos):
            uid = item.data(0)
            raw_pos = (
                self._polygon_control_point_model_position(uid)
                if uid and uid not in seen
                else None
            )
            if raw_pos is not None:
                seen.add(uid)
                ordered.append((uid, raw_pos))
        remaining: list[tuple[float, int, str, list[float]]] = []
        plan_item_uids = (*self._current_takeoffs, *self._current_annotations)
        for index, uid in enumerate(plan_item_uids):
            if uid in seen:
                continue
            raw_pos = self._polygon_control_point_model_position(uid)
            if raw_pos is None:
                continue
            z_value = max(
                (item.zValue() for item in self._uid_to_items.get(uid, [])),
                default=0.0,
            )
            remaining.append((-z_value, index, uid, raw_pos))
        ordered.extend(
            (uid, raw_pos) for _z_value, _index, uid, raw_pos in sorted(remaining)
        )
        return ordered

    @staticmethod
    def _project_ost_point_to_segment(
        px: float,
        py: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
    ) -> tuple[float, float] | None:
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 0.0:
            return None
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        return x1 + t * dx, y1 + t * dy

    def polygon_control_point_target_at(
        self, scene_pos: QtCore.QPointF
    ) -> PolygonControlPointTarget | None:
        tolerance = self._polygon_control_point_hit_tolerance()
        cs = self._scene_builder.get_coordinate_system()
        candidates: list[tuple[str, list[float], list[QtCore.QPointF]]] = []
        for uid, raw_pos in self._polygon_control_point_candidates(scene_pos):
            tx_pos = cs.transform_vertices_to_2d(raw_pos)
            scene_points = [
                self._pt_to_scene(tx_pos[index], tx_pos[index + 1])
                for index in range(0, len(tx_pos), 2)
            ]
            if len(scene_points) >= 3:
                candidates.append((uid, raw_pos, scene_points))
        for uid, _raw_pos, scene_points in candidates:
            for index, point in enumerate(scene_points):
                if (
                    math.hypot(scene_pos.x() - point.x(), scene_pos.y() - point.y())
                    <= tolerance
                ):
                    return PolygonControlPointTarget(
                        plan_item_uid=uid,
                        kind="vertex",
                        vertex_index=index,
                    )
        ost_pos = self._scene_pos_to_ost(scene_pos)
        best: tuple[float, PolygonControlPointTarget] | None = None
        for uid, raw_pos, scene_points in candidates:
            point_count = len(scene_points)
            for index in range(point_count):
                start = scene_points[index]
                end = scene_points[(index + 1) % point_count]
                distance = point_to_segment_distance(
                    scene_pos.x(),
                    scene_pos.y(),
                    start.x(),
                    start.y(),
                    end.x(),
                    end.y(),
                )
                if distance > tolerance:
                    continue
                raw_index = index * 2
                next_raw_index = ((index + 1) % point_count) * 2
                insert_point = self._project_ost_point_to_segment(
                    ost_pos.x(),
                    ost_pos.y(),
                    raw_pos[raw_index],
                    raw_pos[raw_index + 1],
                    raw_pos[next_raw_index],
                    raw_pos[next_raw_index + 1],
                )
                if insert_point is None:
                    continue
                target = PolygonControlPointTarget(
                    plan_item_uid=uid,
                    kind="edge",
                    edge_index=index,
                    insert_point=insert_point,
                )
                if best is None or distance < best[0]:
                    best = (distance, target)
            if best is not None:
                return best[1]
        return None

    def update_selection_visuals(self, emit: bool = True) -> None:
        self.clear_selection_items()
        all_keys = set(self._current_takeoffs.keys()) | set(
            self._current_annotations.keys()
        )
        valid = {
            uid for uid in self._selected_uids & all_keys if self._is_selectable(uid)
        }
        if valid != self._selected_uids:
            self._selected_uids = set(valid)
            self._on_selection_changed()
        if not valid:
            if emit:
                self.plan_item_selection_changed.emit([])
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
            self.plan_item_selection_changed.emit(list(valid))
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
        if atype in (
            ANNOTATION_TYPE_LINE,
            ANNOTATION_TYPE_ARROW,
            ANNOTATION_TYPE_DIMENSION,
        ):
            return self._make_endpoint_handles(cs.transform_vertices_to_2d(pos))
        if atype == ANNOTATION_TYPE_HOTLINK:
            tx = cs.transform_vertices_to_2d(pos[:2])
            sp = self._pt_to_scene(tx[0], tx[1])
            return [
                self._make_selection_handle(
                    sp.x(), sp.y(), self._CORNER_HALF, Qt.CursorShape.SizeAllCursor
                )
            ]
        if atype == ANNOTATION_TYPE_INK:
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
        if atype == ANNOTATION_TYPE_TEXT:
            return self._make_text_annotation_selection_items(ann, uid, cs)
        corners_ost = self._get_ann_corners_ost(ann)
        if corners_ost and atype in (
            ANNOTATION_TYPE_RECT,
            ANNOTATION_TYPE_OVAL,
            ANNOTATION_TYPE_HIGHLIGHT,
            ANNOTATION_TYPE_NAMED_VIEW,
        ):
            tx = cs.transform_vertices_to_2d(corners_ost)
            pts = [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]
            return self._make_bbox_handles(pts)
        if atype in (ANNOTATION_TYPE_POLYGON, ANNOTATION_TYPE_CLOUD) and len(pos) >= 4:
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

    def _text_annotation_resize_box_points(self, ann, cs) -> List:
        pos = ann.position
        if len(pos) < 4:
            return []
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
        return [self._pt_to_scene(tx[i], tx[i + 1]) for i in range(0, len(tx), 2)]

    def _make_text_annotation_selection_items(self, ann, uid: str, cs) -> List:
        pts = self._text_annotation_resize_box_points(ann, cs)
        if len(pts) < 4:
            return []
        polygon = QPolygonF(pts)
        if polygon.count() < 4:
            return []
        outline = self._make_text_annotation_outline_item(uid, polygon)
        return [outline] + self._make_bbox_handles(pts)

    def _make_text_annotation_outline_item(
        self, uid: str, polygon: QPolygonF
    ) -> QGraphicsPolygonItem:
        outline_pen = QPen(_TEXT_SELECTION_OUTLINE_COLOR)
        outline_pen.setWidthF(2.0)
        outline_pen.setCosmetic(True)
        outline_pen.setStyle(Qt.PenStyle.DashLine)
        outline = QGraphicsPolygonItem(polygon)
        outline.setPen(outline_pen)
        outline.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        outline.setZValue(14)
        outline.setData(0, uid)
        return outline

    @staticmethod
    def _copy_item_transform_to_border(
        source: QGraphicsItem, border: QGraphicsPathItem
    ) -> None:
        border.setPos(source.pos())
        border.setTransformOriginPoint(source.transformOriginPoint())
        border.setRotation(source.rotation())

    @staticmethod
    def _get_ann_corners_ost(ann) -> list:
        pos = ann.position
        atype = ann.annotation_type
        if atype == ANNOTATION_TYPE_NAMED_VIEW:
            return named_view_edit_position(pos)
        if atype == ANNOTATION_TYPE_HIGHLIGHT and len(pos) >= 8:
            coordinates = highlight_position_coordinates(pos)
            points = [
                (coordinates[index], coordinates[index + 1])
                for index in range(0, len(coordinates), 2)
            ]
            quads = canonical_highlight_quads(points)
            if len(quads) == 1:
                top_left, top_right, bottom_left, bottom_right = quads[0]
                return [
                    *top_left,
                    *top_right,
                    *bottom_right,
                    *bottom_left,
                ]
        if atype == ANNOTATION_TYPE_RECT and len(pos) >= 8:
            return [pos[0], pos[1], pos[6], pos[7], pos[2], pos[3], pos[4], pos[5]]
        if atype == ANNOTATION_TYPE_OVAL and len(pos) >= 4:
            geometry = ann.get_oval_geometry_ost()
            if geometry is None:
                return []
            cx, cy, hw, hh, rot_rad = geometry
            cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)
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
            if ann and ann.is_text:
                pts = self._text_annotation_resize_box_points(ann, cs)
                if len(pts) < 4:
                    continue
                polygon = QPolygonF(pts)
                border = self._make_text_annotation_outline_item(uid, polygon)
                borders.append(border)
                continue
            for item in self._uid_to_items.get(uid, []):
                border = None
                if isinstance(item, QGraphicsPathItem):
                    border = QGraphicsPathItem(item.path())
                    self._copy_item_transform_to_border(item, border)
                elif isinstance(item, QGraphicsRectItem):
                    path = QPainterPath()
                    path.addRect(item.rect())
                    border = QGraphicsPathItem(path)
                    border.setPos(item.pos())
                else:
                    path = QPainterPath()
                    path.addRect(item.boundingRect())
                    border = QGraphicsPathItem(path)
                    self._copy_item_transform_to_border(item, border)
                if border is not None:
                    border.setData(0, uid)
                    border.setPen(yellow_pen)
                    border.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                    border.setZValue(14)
                    borders.append(border)
        return borders

    def _resolve_select_cursor(self, vp_pos: QtCore.QPoint) -> Qt.CursorShape:
        scene_pos = self.mapToScene(vp_pos)
        if not self._selected_uids:
            if (
                self.find_takeoffs_at(scene_pos)
                or self.find_text_annotation_at(scene_pos) is not None
                or self.find_hotlink_at(scene_pos) is not None
            ):
                return Qt.CursorShape.ArrowCursor
            if self._pdf_text_run_at(scene_pos) is not None:
                return Qt.CursorShape.IBeamCursor
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
        if self.find_selected_movable_at(scene_pos):
            return Qt.CursorShape.SizeAllCursor
        if (
            self.find_takeoffs_at(scene_pos)
            or self.find_text_annotation_at(scene_pos) is not None
            or self.find_hotlink_at(scene_pos) is not None
        ):
            return Qt.CursorShape.ArrowCursor
        if self._pdf_text_run_at(scene_pos) is not None:
            return Qt.CursorShape.IBeamCursor
        return Qt.CursorShape.ArrowCursor
